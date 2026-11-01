#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出发布文件：默认只出源码版；要混淆再显式指定。

用法：
  python publish.py 模式.ow --outdir ./publish                    # 只出源码版
  python publish.py 模式.ow --outdir ./publish --obf vars,numbers # 出源码版 + 混淆版

--obf 可选项（颗粒度对齐 VS Code 插件的五类，另加数值）：

  numbers        数值字面量改写成等价表达式（本项目自有，插件没有）
  vars           变量/子程序改名不可读（对应插件「混淆变量」）
  rules          追加永不触发的假规则（对应插件「混淆规则」的「填充虚假规则」）
  rulenames      规则名清空：`规则("名字")` → `规则("")`（对应插件「移除规则名」）
  comments       删注释：`//…`、`/* … */`、独占一行的 `"…"` 字符串注释（对应插件「移除注释」）
  indexes        数组下标改写成 乘(...) 表达式（对应插件「混淆索引」）
  local-indexes  本地索引同样改写（对应插件「混淆本地索引」）
  strings        字符串隐藏（**未实现**：会改变字符串比较语义，交给插件做）

`--obf all` = numbers,vars,rules,rulenames,comments,indexes,local-indexes。
插件在混淆这一步顺手做掉的「删注释 + 清空规则名」，本脚本要显式勾选，不勾就原样保留。

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
import obfuscate_values  # noqa: E402

NO_SLOTS = core.VERIFIED_NO_SLOTS
CHOICES = {"numbers", "vars", "rules", "rulenames", "comments", "indexes", "local-indexes", "strings", "all"}


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
    out = []
    for line in text.split("\n"):
        code, comment = _split_line_comment(line)
        masked = core._mask(code)          # 字符串内容被抹成空格，用来避开字符串里的同名文本
        def _repl(m):
            name = m.group("dot") or m.group("bare")
            pos = m.start("dot") if m.group("dot") else m.start("bare")
            if pos < len(masked) and masked[pos] != code[pos]:
                return m.group(0)          # 落在字符串里，别动
            new_name = mapping[name]
            return ("." + new_name) if m.group("dot") else new_name
        out.append(pat.sub(_repl, code) + comment)
    return "\n".join(out), len(mapping)


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


def lint_errors(path, sigs=None, labels=None, settings=None):
    """走完整校验（与 ws.py check 同一套数据表），只返回 error。"""
    data = os.path.normpath(os.path.join(HERE, "..", "data"))
    return [p for p in core.full_lint(path, data) if p[1] == "error"]


def main():
    ap = argparse.ArgumentParser(description="出发布文件（默认只出源码版）")
    ap.add_argument("src")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--obf", default="", help="逗号分隔：numbers,vars,rules,rulenames,comments,indexes,local-indexes,all")
    ap.add_argument("--fix", action="store_true", help="自动把会被拒绝的「无」改成「全部禁用」")
    args = ap.parse_args()

    picked = {x.strip() for x in args.obf.split(",") if x.strip()}
    unknown = picked - CHOICES
    if unknown:
        sys.exit("不认识的混淆项：%s（可选：%s）" % (", ".join(sorted(unknown)), ", ".join(sorted(CHOICES))))
    if "all" in picked:
        picked |= {"numbers", "vars", "rules", "rulenames", "comments", "indexes", "local-indexes"}
        picked.discard("all")

    if "strings" in picked:
        sys.exit("字符串混淆会改变比较语义，请用 VS Code 插件执行；本脚本不提供。")

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

    if "indexes" in picked or "local-indexes" in picked:
        obf = obfuscate_indexes(obf)
    if "comments" in picked:
        obf = strip_comments(obf)
        print("已删注释（// 、/* */ 、独占一行的字符串注释）")
    if "rulenames" in picked:
        obf, _blanked = blank_rule_names(obf)
        print("已清空规则名 %d 个（规则(\"名字\") → 规则(\"\")）" % _blanked)
    if "vars" in picked:
        obf, renamed = rename_vars(obf)
        decls = count_var_decls(obf)
        if renamed:
            print("已改名变量 %d 个（声明和引用同步改）" % renamed)
        elif decls:
            # issue #8：以前这里打「已改名变量/子程序 0 个」，看着像「没什么可改的」，
            # 其实是声明格式没被认出来。这种情况必须吵一句。
            print("⚠ 发现 %d 个变量声明，但一个都没改名——检查声明格式（每行应是 `索引: 名字`）" % decls)
        else:
            print("⚠ 这个文件里没有 `索引: 名字` 形式的变量声明，没有可改名的东西")
    if "rules" in picked:
        obf = add_fake_rules(obf)
        print("已追加 3 条假规则（永不触发的空规则；要清空现有规则名请加 rulenames）")

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
        from element_count2 import estimate2 as estimate
        _est_obf = estimate(obf_path)
        if _est_clean:
            delta = (_est_obf - _est_clean) / max(_est_clean, 1) * 100
            print("元素数：源码版 %d → 混淆版 %d（%+.1f%%）" % (_est_clean, _est_obf, delta))
            print("  注：numbers 混淆会把一个字面量拆成表达式，元素数会上升；模型对复杂表达式偏低 3% 左右")
            if _est_obf > 30000:
                print("  ⚠ 接近 32768 上限，建议减少混淆项（尤其 numbers / rules）")
            elif delta > 15:
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
    old = sys.argv
    sys.argv = ["publish.py"] + argv
    try:
        return main()
    finally:
        sys.argv = old


if __name__ == "__main__":
    sys.exit(main())
