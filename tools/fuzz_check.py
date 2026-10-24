#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""漏报率测试：把正确文件故意改坏，看校验器能不能抓到。

和反向用例（人手写的坏文件）互补：这里用随机批量突变，能量出「检出率」，
抓出某类错误系统性漏报的地方。

两个指标口径，别混：
  检出率（原有，逐条「检出 k / M」和「合计」百分比）= 报出来的处数 / 注入处数
  漏报率（本版新增，末尾「漏报率」两节）          = 漏报处数 / 注入处数 = (M-k)/M
其中 M = 注入处数（突变真的改到文本的轮次；这一行改不动时不计入），
k = 校验器报出来的处数（必改 + 提示两档都算「发现」）。

用法：
    python tools/fuzz_check.py 文件.ow [--rounds 20]
    python tools/fuzz_check.py --corpus                        # 跑私有语料里的全部文件
    python tools/fuzz_check.py --corpus --rounds 200 --jobs 8   # 大样本（默认按 CPU 并行）
"""
import argparse
import glob
import os
import random
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import core  # noqa: E402
import local_paths  # noqa: E402

DATA = os.path.join(SKILL, "data")

# 每类突变：(名字, 说明, 函数(text) -> text 或 None)
def _pick_line(lines, pred):
    idx = [i for i, l in enumerate(lines) if pred(l)]
    return random.choice(idx) if idx else None


def mut_drop_semicolon(text):
    lines = text.split("\n")
    i = _pick_line(lines, lambda l: l.strip().endswith(";") and "规则(" not in l
                   and not l.strip().startswith("//"))
    if i is None:
        return None
    lines[i] = lines[i].rstrip()[:-1]
    return "\n".join(lines)


def mut_unknown_function(text):
    lines = text.split("\n")
    i = _pick_line(lines, lambda l: re.search(r"[\u4e00-\u9fa5]{3,}\(", l) and "规则(" not in l)
    if i is None:
        return None
    m = re.search(r"([\u4e00-\u9fa5]{3,})\(", lines[i])
    lines[i] = lines[i][:m.start(1)] + "未知动作" + lines[i][m.end(1):]
    return "\n".join(lines)


def mut_bad_setting_value(text):
    lines = text.split("\n")
    i = _pick_line(lines, lambda l: re.match(r"^\s*[^:：]+:\s*[\d.]+%?\s*$", l))
    if i is None:
        return None
    lines[i] = re.sub(r":\s*[\d.]+%?\s*$", ": 999999", lines[i])
    return "\n".join(lines)


def mut_bad_map(text):
    lines = text.split("\n")
    i = _pick_line(lines, lambda l: "地图(" in l)
    if i is None:
        return None
    lines[i] = re.sub(r"地图\([^()]*\)", "地图(不存在的测试地图)", lines[i])
    return "\n".join(lines)


def mut_undeclared_var(text):
    lines = text.split("\n")
    i = _pick_line(lines, lambda l: re.search(r"全局\.[A-Za-z_]\w*", l))
    if i is None:
        return None
    lines[i] = re.sub(r"全局\.[A-Za-z_]\w*", "全局.ZZZNotDeclared", lines[i], count=1)
    return "\n".join(lines)


def mut_drop_end(text):
    lines = text.split("\n")
    i = _pick_line(lines, lambda l: l.strip() == "End;")
    if i is None:
        return None
    lines[i] = lines[i].replace("End;", "")
    return "\n".join(lines)


def mut_drop_paren(text):
    lines = text.split("\n")
    i = _pick_line(lines, lambda l: l.strip().endswith(");") and l.count("(") >= 2)
    if i is None:
        return None
    j = lines[i].rfind(")")
    if j < 0:
        return None
    lines[i] = lines[i][:j] + lines[i][j + 1:]
    return "\n".join(lines)


def mut_bad_team_word(text):
    lines = text.split("\n")
    i = _pick_line(lines, lambda l: "所有队伍" in l)
    if i is None:
        return None
    lines[i] = lines[i].replace("所有队伍", "全部队伍", 1)
    return "\n".join(lines)


def mut_bare_string(text):
    lines = text.split("\n")
    i = _pick_line(lines, lambda l: "自定义字符串(" in l and '"' in l and l.strip().endswith(";"))
    if i is None:
        return None
    lines[i] = re.sub(r'自定义字符串\((\s*"[^"]*")', r"\1", lines[i], count=1)
    return "\n".join(lines)


MUTATIONS = [
    ("删掉一个分号", mut_drop_semicolon),
    ("换成不存在的动作名", mut_unknown_function),
    ("设置值改成超范围", mut_bad_setting_value),
    ("地图名改成不存在的", mut_bad_map),
    ("引用未声明的变量", mut_undeclared_var),
    ("删掉一个 End;", mut_drop_end),
    ("删掉一个右括号", mut_drop_paren),
    ("所有队伍 → 全部队伍", mut_bad_team_word),
    ("字符串没包 自定义字符串", mut_bare_string),
]

# 漏报率按「检查类别」分组：一类突变对应校验器里的一组检查
CATEGORY = {
    "删掉一个分号": "语法结构",
    "删掉一个 End;": "语法结构",
    "删掉一个右括号": "语法结构",
    "换成不存在的动作名": "名字与引用",
    "引用未声明的变量": "名字与引用",
    "所有队伍 → 全部队伍": "名字与引用",
    "设置值改成超范围": "设置与地图",
    "地图名改成不存在的": "设置与地图",
    "字符串没包 自定义字符串": "字符串写法",
}
CAT_ORDER = ["语法结构", "名字与引用", "设置与地图", "字符串写法"]


def check_file(path):
    """返回 (必改条数, 提示条数)。

    两档分开统计：必改是「会挡导入」的硬错；提示级（如大厅边界、皮肤上限）
    只要报出来也算「发现」，否则一堆提示级检查坏了也看不出来（同 E-15 的教训）。
    """
    probs = core.full_lint(path, DATA)
    errs = [p for p in probs if p[1] == "error"]
    warns = [p for p in probs if p[1] != "error"]
    return len(errs), len(warns)


def run_one(path, rounds, verbose=False):
    base, _enc = core.read_text(path)
    stat = {}
    for name, fn in MUTATIONS:
        hit = hit_warn = miss = 0
        misses = []
        for _ in range(rounds):
            mutated = fn(base)
            if mutated is None or mutated == base:
                continue
            fd, tmp = tempfile.mkstemp(suffix=".ow")
            os.close(fd)
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(mutated)
            n_err, n_warn = check_file(tmp)
            os.remove(tmp)
            if n_err:
                hit += 1
            elif n_warn:
                hit_warn += 1
            else:
                miss += 1
                diffs = [(i + 1, a, b) for i, (a, b) in
                         enumerate(zip(base.split("\n"), mutated.split("\n"))) if a != b]
                if diffs:
                    misses.append(diffs[0])
        if hit + hit_warn + miss:
            stat[name] = (hit, hit_warn, miss, misses[:2])
            if verbose and miss:
                print("   ✗ %s：漏报 %d/%d，例：第 %s 行 %r → %r"
                      % (name, miss, hit + hit_warn + miss, misses[0][0],
                         misses[0][1][:60], misses[0][2][:60]))
    return stat


def _sample_diff(base_lines, mutated):
    diffs = [(i + 1, a, b) for i, (a, b) in
             enumerate(zip(base_lines, mutated.split("\n"))) if a != b]
    return diffs[0] if diffs else None


# ---------------------------------------------------------------- 并行执行
def _chunk_task(task):
    """一个任务 = 一个文件 × 一类突变 × 若干轮 -> (path, name, hit, warn, miss, 漏报样例)。"""
    path, name, idxs = task
    import random as _rnd
    fn = dict(MUTATIONS)[name]
    base, _enc = core.read_text(path)
    base_lines = base.split("\n")
    hit = warn = miss = 0
    sample = None
    for r in idxs:
        _rnd.seed("%s|%s|%d" % (os.path.basename(path), name, r))
        mutated = fn(base)
        if mutated is None or mutated == base:
            continue
        fd, tmp = tempfile.mkstemp(suffix=".ow")
        os.close(fd)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(mutated)
        try:
            n_err, n_warn = check_file(tmp)
        finally:
            os.remove(tmp)
        if n_err:
            hit += 1
        elif n_warn:
            warn += 1
        else:
            miss += 1
            if sample is None:
                sample = _sample_diff(base_lines, mutated)
    return (path, name, hit, warn, miss, sample)


def run_all_parallel(files, rounds, jobs, chunk=20):
    """按 (文件 × 突变 × 20 轮) 切任务分进程跑；结果按文件聚回原来的字典结构。"""
    import multiprocessing as mp
    tasks = []
    for path in files:
        for name, _fn in MUTATIONS:
            for start in range(0, rounds, chunk):
                tasks.append((path, name, list(range(start, min(start + chunk, rounds)))))
    stats = {}
    with mp.Pool(jobs) as pool:
        for path, name, hit, warn, miss, sample in pool.imap_unordered(_chunk_task, tasks):
            if not (hit + warn + miss):
                continue                      # 这一行改不动/没有可改的行：不算「注入」
            cur = stats.setdefault(path, {}).setdefault(name, [0, 0, 0, []])
            cur[0] += hit
            cur[1] += warn
            cur[2] += miss
            if sample and len(cur[3]) < 2:
                cur[3].append(sample)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("--corpus", action="store_true")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--jobs", type=int, default=0, help="并行进程数，0=按 CPU 自动（1=不分进程）")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()

    if a.file:
        files = [a.file]
    else:
        corpus = local_paths.corpus_dir()
        files = sorted(glob.glob(os.path.join(corpus, "*.ow"))) if corpus else []
        if not files:
            print("没有可测的文件：%s" % (local_paths.hint() if not corpus else "语料目录里没有 .ow：%s" % corpus))
            return 2

    jobs = a.jobs or min(8, os.cpu_count() or 1)
    if len(files) * len(MUTATIONS) * a.rounds < 200:
        jobs = 1                      # 小样本不值得起进程池

    if jobs > 1:
        allstat = run_all_parallel(files, a.rounds, jobs)
    else:
        allstat = {}
        for path in files:
            allstat[path] = run_one(path, a.rounds, verbose=a.verbose)

    total = {}
    for path in files:
        print("\n== %s" % os.path.basename(path))
        stat = allstat.get(path, {})
        for name, _fn in MUTATIONS:          # 按 MUTATIONS 原顺序打印，输出格式不变
            if name not in stat:
                continue
            hit, hit_warn, miss, misses = stat[name]
            t = total.setdefault(name, [0, 0, 0])
            t[0] += hit
            t[1] += hit_warn
            t[2] += miss
            print("   %-22s 检出 %2d / %2d%s" % (name, hit, hit + hit_warn + miss,
                                                 "（其中提示级 %d）" % hit_warn if hit_warn else ""))
            if a.verbose and miss and misses:
                print("   ✗ %s：漏报 %d/%d，例：第 %s 行 %r → %r"
                      % (name, miss, hit + hit_warn + miss, misses[0][0],
                         misses[0][1][:60], misses[0][2][:60]))

    print("\n== 合计")
    bad = 0
    for name, (hit, hit_warn, miss) in sorted(total.items(), key=lambda kv: kv[1][2], reverse=True):
        n = hit + hit_warn + miss
        rate = 100.0 * (hit + hit_warn) / n if n else 0
        extra = "（提示级 %d，占 %.0f%%）" % (hit_warn, 100.0 * hit_warn / n) if hit_warn else ""
        print("   %-22s %5.1f%%  (%d/%d)%s" % (name, rate, hit + hit_warn, n, extra))
        if miss:
            bad += miss
    print("\n总漏报 %d 处" % bad)

    # ---- 本版新增：漏报率 (M-k)/M，按检查类别分组；与上面的「检出率」是两个口径 ----
    cat = {}
    for name, (hit, hit_warn, miss) in total.items():
        c = CATEGORY.get(name, "其他")
        row = cat.setdefault(c, [0, 0, 0])
        row[0] += hit + hit_warn + miss      # 注入 M
        row[1] += hit + hit_warn             # 检出 k
        row[2] += miss
    print("\n== 漏报率（按检查类别；口径 漏报/注入 = (M-k)/M，与上面的检出率互补）")
    print("   %-12s %6s %6s %6s %8s" % ("类别", "注入M", "检出k", "漏报", "漏报率"))
    m_all = k_all = 0
    order = [c for c in CAT_ORDER if c in cat] + [c for c in sorted(cat) if c not in CAT_ORDER]
    for c in order:
        m, k, miss = cat[c]
        m_all += m
        k_all += k
        print("   %-12s %6d %6d %6d %7.1f%%" % (c, m, k, miss, 100.0 * miss / m if m else 0))
    if m_all:
        print("   %-12s %6d %6d %6d %7.1f%%" % ("合计", m_all, k_all, m_all - k_all,
                                                100.0 * (m_all - k_all) / m_all))
    print("\n== 漏报率（按突变，逐条）")
    for name, _fn in MUTATIONS:
        if name not in total:
            continue
        hit, hit_warn, miss = total[name]
        m = hit + hit_warn + miss
        if not m:
            continue
        print("   %-22s 漏报 %3d / 注入 %3d  漏报率 %5.1f%%" % (name, miss, m, 100.0 * miss / m))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
