#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出发布文件：默认只出源码版；要混淆再显式指定。

用法：
  python publish.py 模式.ow --outdir ./publish                    # 只出源码版
  python publish.py 模式.ow --outdir ./publish --obf vars,numbers # 出源码版 + 混淆版

--obf 可选项（颗粒度对齐 VS Code 插件的五类，另加数值）：

  numbers        数值字面量改写成等价表达式（本项目自有，插件没有）
  vars           变量/子程序改名不可读（对应插件「混淆变量」）
  rules          追加永不触发的假规则（对应插件「混淆规则」）
  indexes        数组下标改写成 乘(...) 表达式（对应插件「混淆索引」）
  local-indexes  本地索引同样改写（对应插件「混淆本地索引」）
  strings        字符串隐藏（**未实现**：会改变字符串比较语义，交给插件做）

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
CHOICES = {"numbers", "vars", "rules", "indexes", "local-indexes", "strings"}


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


def rename_vars(text, seed=20261020):
    rng = random.Random(seed)
    names = re.findall(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$", text, re.M)
    mapping = {n: random_name(rng) for n in set(names)}
    for old in sorted(mapping, key=len, reverse=True):
        text = re.sub(r"(?<![\w.])%s(?![\w])" % re.escape(old), mapping[old], text)
    return text, len(mapping)


def obfuscate_indexes(text):
    """把 [数字] 改成 [乘(10000000, 0.0000001*数字)]，对齐插件的索引混淆。"""
    def repl(m):
        num = m.group(1)
        try:
            factor = float(num) * 0.0000001
        except ValueError:
            return m.group(0)
        return "[乘(10000000, %s)]" % ("%f" % factor).rstrip("0")
    return re.sub(r"\[(\d+)\]", repl, text)


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


def lint_errors(path, sigs, labels, settings):
    return [p for p in core.lint(path, sigs, labels, settings) if p[1] == "error"]


def main():
    ap = argparse.ArgumentParser(description="出发布文件（默认只出源码版）")
    ap.add_argument("src")
    ap.add_argument("--outdir", default=".")
    ap.add_argument("--obf", default="", help="逗号分隔：numbers,vars,rules,indexes,local-indexes")
    ap.add_argument("--fix", action="store_true", help="自动把会被拒绝的「无」改成「全部禁用」")
    args = ap.parse_args()

    picked = {x.strip() for x in args.obf.split(",") if x.strip()}
    unknown = picked - CHOICES
    if unknown:
        sys.exit("不认识的混淆项：%s（可选：%s）" % (", ".join(sorted(unknown)), ", ".join(sorted(CHOICES))))
    if "strings" in picked:
        sys.exit("字符串混淆会改变比较语义，请用 VS Code 插件执行；本脚本不提供。")

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
    if "vars" in picked:
        obf, renamed = rename_vars(obf)
        print("已改名变量/子程序 %d 个" % renamed)
    if "rules" in picked:
        obf = add_fake_rules(obf)
        print("已追加 3 条假规则")

    obf_path = os.path.join(args.outdir, base + ".obf.ow")
    open(obf_path, "w", encoding="utf-8", newline="").write(obf.replace("\n", "\r\n"))

    errors = lint_errors(obf_path, sigs, labels, settings)
    if errors:
        print("✗ 混淆版没过校验（源码版可用，可只用它）：")
        for ln, _l, msg in errors[:10]:
            print("   第 %s 行：%s" % (ln or "?", msg))
        return 1
    print("✓ 混淆版：%s（用了：%s）" % (obf_path, ", ".join(sorted(picked))))
    print("\n导入后看一眼诊断里的「总计元素数量」，混淆会增加额度消耗。")
    return 0


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
