#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""漏报率测试：把正确文件故意改坏，看校验器能不能抓到。

和反向用例（人手写的坏文件）互补：这里用随机批量突变，能量出「检出率」，
抓出某类错误系统性漏报的地方。

用法：
    python tools/fuzz_check.py 文件.ow [--rounds 20]
    python tools/fuzz_check.py --corpus            # 跑私有语料里的全部文件
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("--corpus", action="store_true")
    ap.add_argument("--rounds", type=int, default=20)
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

    total = {}
    for path in files:
        print("\n== %s" % os.path.basename(path))
        stat = run_one(path, a.rounds, verbose=a.verbose)
        for name, (hit, hit_warn, miss, misses) in stat.items():
            t = total.setdefault(name, [0, 0, 0])
            t[0] += hit
            t[1] += hit_warn
            t[2] += miss
            print("   %-22s 检出 %2d / %2d%s" % (name, hit, hit + hit_warn + miss,
                                                 "（其中提示级 %d）" % hit_warn if hit_warn else ""))

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
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
