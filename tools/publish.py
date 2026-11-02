#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出发布文件：默认只出源码版；要混淆再显式指定。

用法：
  python publish.py 模式.ow --outdir ./publish                    # 只出源码版
  python publish.py 模式.ow --outdir ./publish --obf vars,numbers # 出源码版 + 混淆版

--obf 可选项（对齐 VS Code 插件 obfuscate.ts，另加数值混淆）：

  numbers        数值字面量改写成等价表达式 (n * F / F)（本项目自有，插件没有）
  vars           变量/子程序改名不可读，声明和引用同步（对应插件「混淆变量」的改名部分）
  fakevars       变量表/子程序表整表重建，假名填满 128 位（对应插件「混淆变量」的填充部分）
  rules          追加 3 条永不触发的假规则（轻量版）
  fill           按元素预算铺满假规则：查看器警告 + 5 条篡改保护 + 1 元素空规则（对应插件「混淆规则」）
  rulenames      规则名清空：`规则("名字")` → `规则("")`（插件混淆时无条件做）
  comments       删注释：`//…`、`/* … */`、独占一行的 `"…"`（插件混淆时无条件做）
  viewer         删「记入查看器 / 启用查看器录制 / 禁用查看器录制」动作（插件混淆时也会删）
  indexes        服务端索引：`[21]` → `[(21 * 9 / 9)]`（恒等，不赌浮点；对应插件「混淆索引」）
  local-indexes  客户端计算函数的索引：`[3]` → `[3.27]` 这类小数抖动（对应插件「混淆本地索引」）
  strings        字符串混淆：字符位移到私用区码位，`/* @SKIP_OBFUSCATE_STRING */` 之间不动

`--obf all` = 上面全部（含 strings；字符串比较会被影响，介意就单独勾）。
`--budget N` 配合 fill：混淆后允许达到的元素总数，默认 32000（上限 32768 留 768 余量）。

不做混淆时不读任何混淆配置、不生成第二份文件。
"""
import argparse
import os
import random
import re
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402
import obf_parts  # noqa: E402
import obfuscate_values  # noqa: E402

NO_SLOTS = core.VERIFIED_NO_SLOTS
CHOICES = {"numbers", "vars", "fakevars", "rules", "fill", "rulenames", "comments", "viewer",
           "indexes", "local-indexes", "strings", "all"}


def fix_no_to_disabled(text):
    out, changed = [], 0
    for line in text.split("\n"):
        new = line
        for name in TEXT_FUNCS:
            new = re.sub(r"(%s\s*\([^\n]*),\s*无\s*,([^\n]*\)\s*;)" % name, r"\1, 全部禁用,\2", new)
        for name in TAIL_FUNCS:
            new = re.sub(r"(%s\s*\([^\n]*),\s*无\s*(\)\s*;)" % name, r"\1, 全部禁用\2", new)
        if new != line:
            changed += 1
        out.append(new)
    return "\n".join(out), changed


def random_name(rng):
    return "v" + "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(5))


def _split_line_comment(line):
    """把行尾 `//` 注释切出来（字符串里的 `//` 不算）。返回 (code, comment)。"""
    in_str = escaped = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return line[:i], line[i:]
        i += 1
    return line, ""


def count_var_decls(text):
    """变量声明行数（允许行尾带 `//` 注释）。"""
    n = 0
    for line in text.split("\n"):
        code, _cm = _split_line_comment(line)
        if re.match(r"^\s*\d+\s*:\s*[A-Za-z_]\w*\s*$", code):
            n += 1
    return n


def rename_vars(text, seed=20261020):
    """变量/子程序改随机名，声明与引用同步替换；行尾 `//` 注释原样保留。

    issue #8：旧实现要求「变量名后面直接到行尾」，带 `//` 注释的声明
    （工具自己推荐的写法、真实模式里 129 个变量全带注释）一个都匹配不到，
    于是改名 0 个还只用正常语气打印一句「已改名变量/子程序 0 个」。
    """
    rng = random.Random(seed)
    decl = re.compile(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$")
    names = set()
    for line in text.split("\n"):
        code, _cm = _split_line_comment(line)
        m = decl.match(code)
        if m:
            names.add(m.group(1))
    mapping = {n: random_name(rng) for n in names}
    if not mapping:
        return text, 0

    alt = "|".join(re.escape(n) for n in sorted(mapping, key=len, reverse=True))
    # 变量引用有两种：裸名（声明行、动作参数），以及「某个东西.名字」——
    # 前缀不一定是 全局/事件玩家：玩家变量自己也能当持有者（`攻击方.HookedCount`），
    # 所以「点号后面」一律认，别再列死前缀表（issue #8 修完改名数后暴露的第二处）。
    pat = re.compile(r"(?:\.(?P<dot>%s)|(?<![\w.])(?P<bare>%s))(?![\w])" % (alt, alt))
    # issue #17：不能按物理行各自遮罩——跨行字符串的续行开头就是那个收尾引号，
    # 整行会被当成字符串内容，续行里的引用一个都改不到（7 千行模式 13 处，产物直接导不进去）。
    # 改成全文遮罩（core.mask_text 的字符串状态跨行延续，长度与原文一致），再在原文上逐处替换。
    masked = core.mask_text(text)
    out, last, renamed = [], 0, 0
    for m in pat.finditer(text):
        if m.start() < len(masked) and masked[m.start()] != text[m.start()]:
            continue                    # 落在字符串 / 注释里，别动
        name = m.group("dot") or m.group("bare")
        out.append(text[last:m.start()])
        out.append(("." + mapping[name]) if m.group("dot") else mapping[name])
        last = m.end()
        renamed += 1
    out.append(text[last:])
    return "".join(out), len(mapping)


INDEX_FACTORS = (3, 7, 9, 11, 13)


def _index_expr(n, rng):
    """把整数下标藏成恒等表达式 `(n * m / m)`（issue #9）。

    旧写法 `[乘(10000000, 0.0000021)]` 在 double 下等于 20.999999999999996，
    1..3000 里有 357 个整数算不回原值；游戏若截断下标就静默取错元素。
    `(n * m / m)` 先乘整数再除同一个整数，IEEE 正确舍入保证结果与 n 完全相等
    （0..200000 × 3/7/9/11/13 全测过，0 例偏差），跟 `numbers` 那套同一原理。
    """
    m = rng.choice(INDEX_FACTORS)
    if (n * m) / m != n:          # 兜底：真算不准就不动这一处
        return None
    return "[(%d * %d / %d)]" % (n, m, m)

def obfuscate_indexes(text, seed=20261031):
    """把 [数字] 改写成恒等表达式，防止别人直接读下标。"""
    rng = random.Random(seed)
    def repl(m):
        try:
            n = int(m.group(1))
        except ValueError:
            return m.group(0)
        expr = _index_expr(n, rng)
        return expr if expr else m.group(0)
    return re.sub(r"\[(\d+)\]", repl, text)

def strip_comments(text):
    """删掉注释：`//…`、`/* … */`、以及独占一行的 `"…"` 字符串注释。

    对齐 VS Code 插件混淆时的「移除注释」：插件在混淆这一步把规则区的
    `//`、`/* */` 和字符串注释统统抹掉（issue #9 核对源码确认）。
    字符串里的 `//` 不动——`自定义字符串("http://…")` 里的两个斜杠是内容，不是注释。
    """
    out, i, n = [], 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j == -1 else j            # 换行留着，行号不会串
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        out.append(ch)
        i += 1
    cleaned = "".join(out)
    keep = []
    for line in cleaned.split("\n"):
        if re.fullmatch(r'\s*"(?:[^"\\]|\\.)*"\s*', line):
            continue                            # 独占一行的字符串注释
        keep.append(line)
    return "\n".join(keep)


def blank_rule_names(text):
    """规则名清空：`规则("名字")` → `规则("")`（对齐插件混淆时「移除规则名」）。"""
    hits = [0]

    def _repl(m):
        hits[0] += 1
        return m.group(1) + '("")'

    out = re.sub(r'((?:禁用)?规则)\s*\(\s*"(?:[^"\\]|\\.)*"\s*\)', _repl, text)
    return out, hits[0]

def add_fake_rules(text, count=3, seed=20261020):
    """追加永不触发的假规则（对齐插件「混淆规则」）。"""
    rng = random.Random(seed)
    block = []
    for _ in range(count):
        frac = rng.randint(1, 9)
        block.append('规则("")\n{\n\t事件\n\t{\n\t\t持续 - 全局;\n\t}\n\n'
                     '\t条件\n\t{\n\t\t0.000%d == 假;\n\t}\n\n'
                     '\t动作\n\t{\n\t\tWhile(真);\n\t\tEnd;\n\t}\n}\n' % frac)
    return text.rstrip("\n") + "\n\n" + "\n".join(block)


def estimate_path(path):
    """估元素数；没有 element_count2 就返回 None。"""
    try:
        from element_count2 import estimate2
        return estimate2(path)
    except Exception:
        return None


def lint_errors(path, sigs=None, labels=None, settings=None):
    """走完整校验（与 ws.py check 同一套数据表），只返回 error。"""
    data = os.path.normpath(os.path.join(HERE, "..", "data"))
    return [p for p in core.full_lint(path, data) if p[1] == "error"]


def main():
    ap = argparse.ArgumentParser(description="出发布文件（默认只出源码版）")
    ap.add_argument("src")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--obf", default="", help="逗号分隔：numbers,vars,fakevars,rules,fill,rulenames,comments,viewer,indexes,local-indexes,strings,all")
    ap.add_argument("--budget", type=int, default=None, help="混淆后允许达到的元素总数（fill 用，默认 32000，留 768 余量）")
    ap.add_argument("--fix", action="store_true", help="自动把会被拒绝的「无」改成「全部禁用」")
    args = ap.parse_args()

    picked = {x.strip() for x in args.obf.split(",") if x.strip()}
    unknown = picked - CHOICES
    if unknown:
        sys.exit("不认识的混淆项：%s（可选：%s）" % (", ".join(sorted(unknown)), ", ".join(sorted(CHOICES))))
    if "all" in picked:
        picked |= {"numbers", "vars", "fakevars", "rules", "rulenames", "comments", "viewer",
                   "indexes", "local-indexes", "strings", "fill"}
        picked.discard("all")

    import time
    _T0 = time.time()
    data = os.path.normpath(os.path.join(HERE, "..", "data"))
    sigs, labels, _opts = core.load_signatures(os.path.join(data, "signatures.md"))
    settings = core.load_settings_schema(os.path.join(data, "settings.tsv"))

    text = open(args.src, encoding="utf-8").read().replace("\r\n", "\n")
    if args.fix:
        text, fixed = fix_no_to_disabled(text)
        if fixed:
            print("已修复 %d 处「无」→「全部禁用」" % fixed)

    os.makedirs(args.outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.src))[0]
    clean_path = os.path.join(args.outdir, base + ".ow")
    open(clean_path, "w", encoding="utf-8", newline="").write(text.replace("\n", "\r\n"))

    errors = lint_errors(clean_path, sigs, labels, settings)
    if errors:
        print("✗ 源码版没过校验，已停止：")
        for ln, _l, msg in errors[:10]:
            print("   第 %s 行：%s" % (ln or "?", msg))
        return 1
    print("✓ 源码版：%s" % clean_path)
    try:
        from element_count2 import estimate2 as estimate
        _est_clean = estimate(clean_path)
    except Exception:
        _est_clean = None

    if not picked:
        print("\n未指定 --obf，不出混淆版。")
        return 0

    obf = text
    if "numbers" in picked:
        lines, stack, pending, out = obf.split("\n"), [], None, []
        for line in lines:
            stripped = line.strip()
            if stripped in core.BLOCK_KEYWORDS or stripped.startswith("规则("):
                pending = "规则" if stripped.startswith("规则(") else stripped
                out.append(line)
                continue
            if stripped.startswith("{"):
                stack.append(pending or (stack[-1] if stack else None))
                pending = None
                out.append(line)
                continue
            if stripped.startswith("}"):
                if stack:
                    stack.pop()
                out.append(line)
                continue
            if stack and stack[-1] in ("动作", "条件"):
                line, _n = obfuscate_values.rewrite_line(line, labels, 7)
            out.append(line)
        obf = "\n".join(out)

    if "viewer" in picked:
        obf, _v = obf_parts.strip_viewer_actions(obf)
        print("已删查看器动作 %d 条（记入查看器 / 启用/禁用查看器录制）" % _v)
    if "vars" in picked:
        obf, renamed = rename_vars(obf)
        decls = count_var_decls(obf)
        if renamed:
            print("已改名变量 %d 个（声明和引用同步改；产物接着过一遍完整校验）" % renamed)
        elif decls:
            # issue #8：以前这里打「已改名变量/子程序 0 个」，看着像「没什么可改的」，
            # 其实是声明格式没被认出来。这种情况必须吵一句。
            print("⚠ 发现 %d 个变量声明，但一个都没改名——检查声明格式（每行应是 `索引: 名字`）" % decls)
        else:
            print("⚠ 这个文件里没有 `索引: 名字` 形式的变量声明，没有可改名的东西")
    if "fakevars" in picked:
        obf, _tbl = obf_parts.rebuild_tables(obf)
        print("已重建变量表/子程序表：全局 %d 条、玩家 %d 条、子程序 %d 条（填满 128 位）"
              % (_tbl["全局"], _tbl["玩家"], _tbl["子程序"]))
    if "strings" in picked:
        obf, _sh = obf_parts.obfuscate_strings(obf)
        print("已混淆字符串 %d 处（字符位移到私用区；和玩家名比较的字符串要包 @SKIP_OBFUSCATE_STRING）" % _sh)
    if "comments" in picked:
        obf = strip_comments(obf)
        print("已删注释（// 、/* */ 、独占一行的字符串注释）")
    if "rulenames" in picked:
        obf, _blanked = blank_rule_names(obf)
        print("已清空规则名 %d 个（规则(\"名字\") → 规则(\"\")）" % _blanked)
    if "indexes" in picked or "local-indexes" in picked:
        obf, (_si, _li) = obf_parts.split_indices(obf,
                                                  do_server="indexes" in picked,
                                                  do_local="local-indexes" in picked)
        if "indexes" in picked:
            print("已混淆服务端索引 %d 处（恒等写法 n*m/m）" % _si)
        if "local-indexes" in picked:
            print("已混淆本地索引 %d 处（小数抖动，只往正方向偏，取回还是原下标）" % _li)
    if "fill" in picked:
        budget = args.budget if args.budget is not None else 32000
        if args.budget is None:
            print("目标元素总数 %d（32768 上限留 768 余量；要改加 --budget）" % budget)
        # issue #16：预算是「模型口径」，模型对真实元素数偏低（实测倍率到 1.21），
        # 按 32000 填进去真实值会到 3.5 万，直接导不进去。超最坏上限就自动压下来。
        from element_count2 import interval as _interval, CAP as _CAP, RATIO_HI as _HI
        _worst = _interval(budget)[1]
        if _worst > _CAP:
            _safe = int(_CAP / _HI)
            print("⚠ 预算 %d 是模型口径，按最坏倍率 %.2f 会到 %d（超上限 %d）：自动下调到 %d（最坏 %d）"
                  % (budget, _HI, _worst, _CAP, _safe, _interval(_safe)[1]))
            budget = _safe
        # 只填差额：混淆本身已经吃掉一部分额度，填到用户给的总数为止
        _tmp = os.path.join(args.outdir, base + ".est.tmp.ow")
        with open(_tmp, "w", encoding="utf-8", newline="") as f:
            f.write(obf.replace("\n", "\r\n"))
        _cur = estimate_path(_tmp)
        try:
            os.remove(_tmp)
        except OSError:
            pass
        remaining = budget - (_cur or 0)
        if remaining <= 0:
            print("⚠ 混淆后元素数已到 %d，没有余额再填假规则（跳过 fill）" % (_cur or 0))
        else:
            obf, _fill = obf_parts.fill_rules(obf, remaining)
            print("已填充假规则：查看器警告 %d、篡改保护 %d、1 元素空规则 %d（总预算 %d，已用 %d，余 %d）"
                  % (_fill["警告"], _fill["篡改"], _fill["空规则"], budget, _cur or 0, _fill["剩余预算"]))
    elif "rules" in picked:
        obf = add_fake_rules(obf)
        print("已追加 3 条假规则（永不触发的空规则；要按元素预算铺满用 fill）")
    obf_path = os.path.join(args.outdir, base + ".obf.ow")
    open(obf_path, "w", encoding="utf-8", newline="").write(obf.replace("\n", "\r\n"))

    errors = lint_errors(obf_path, sigs, labels, settings)
    if errors:
        print("✗ 混淆版没过校验（源码版可用，可只用它）：")
        for ln, _l, msg in errors[:10]:
            print("   第 %s 行：%s" % (ln or "?", msg))
        return 1
    print("✓ 混淆版：%s（用了：%s）" % (obf_path, ", ".join(sorted(picked))))
    try:
        from element_count2 import estimate2 as estimate, interval, CAP
        _est_obf = estimate(obf_path)
        if _est_clean:
            delta = (_est_obf - _est_clean) / max(_est_clean, 1) * 100
            print("元素数：源码版 %d → 混淆版 %d（%+.1f%%）" % (_est_clean, _est_obf, delta))
            _lo, _hi = interval(_est_obf)
            print("  混淆版模型估 %d，最坏 %d（真实模式模型一律偏低，上界按最坏情况算；口径同 ws.py count）"
                  % (_est_obf, _hi))
            if _lo > CAP:
                print("  ✗ 必定超上限：按最低增幅也算到 %d，已过 %d，先压元素（见 docs/cost-patterns.md）"
                      % (_lo, CAP))
            elif _hi > CAP:
                print("  ⚠ 可能超上限：最坏情况 %d（超 %d），真实值落在 %d 以上就导不进去，别赌"
                      % (_hi, _hi - CAP, CAP))
            else:
                print("  上限 %d，按最坏情况还余 %d 个。" % (CAP, CAP - _hi))
            if delta > 15 and _est_obf >= 10000:
                print("  ⚠ 混淆让元素数涨了 %.0f%%，若离上限不远请改用 vars / indexes" % delta)
    except Exception:
        pass
    print("\n导入后看一眼诊断里的「总计元素数量」，混淆会增加额度消耗。")
    _summarize(_T0, clean_path, obf_path, picked)
    return 0


def _summarize(t0, clean, obf, picked):
    import time as _t
    dt = _t.time() - t0
    print("\n完成，用时 %.2f 秒" % dt)
    print("  源码版：%s" % clean)
    if obf:
        print("  混淆版：%s（%s）" % (obf, ", ".join(sorted(picked)) or "无"))


def main_with_args(args):
    """给 ws.py publish 子命令用：把 argparse 结果塞回去执行。"""
    argv = [args.src, "--outdir", args.outdir, "--obf", args.obf]
    if getattr(args, "fix", False):
        argv.append("--fix")
    # issue #16：这里原来只搬 src/outdir/obf/fix，--budget 被吞掉，fill 永远按 32000 填
    if getattr(args, "budget", None) is not None:
        argv += ["--budget", str(args.budget)]
    old = sys.argv
    sys.argv = ["publish.py"] + argv
    try:
        return main()
    finally:
        sys.argv = old


if __name__ == "__main__":
    sys.exit(main())
