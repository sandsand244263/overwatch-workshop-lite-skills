#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数值混淆：把工坊代码里的数值字面量换成等价表达式，防止别人直接读数。

用法：
  python obfuscate_values.py 原文件.ow --out 混淆版.ow
  python obfuscate_values.py 原文件.ow --out 混淆版.ow --factor 7 --dry-run

原理：n -> (n * F / F)，F 取奇数（默认 7）。整数乘除在浮点里是精确的
（只要 n*F 不超过 2^24），不像 10000000 * 0.000X 那样有精度损失。

只改「动作/条件里的数值参数」，以下一律不碰：
  - 设置块（大厅/模式/英雄/综合）里的值
  - 变量声明、变量索引、数组下标 [n]
  - 事件块（含英雄过滤）
  - 字符串内部的数字、注释里的数字
  - 参数位是「选择/变量/玩家/队伍」的（枚举和引用不接受表达式）
  - 地图 GUID（超长整数）
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402

NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")


def load_types(sig_path):
    """{函数名: [参数类型标签]}"""
    _sigs, labels, _opts = core.load_signatures(sig_path)
    return labels


def split_top_level_args(text):
    return core.split_args(text)


def obfuscatable(kind):
    """参数标签是否允许写表达式（数值类才混淆）。"""
    if not kind:
        return True
    return not any(x in kind for x in ("选择", "变量", "玩家", "队伍"))


def mask_strings(line):
    """返回同长度掩码文本，字符串内容与注释替换成空格。"""
    out, in_str, escaped, i = [], False, False, 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
                out.append('"')
                i += 1
                continue
            out.append(" ")
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append('"')
            i += 1
            continue
        if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            out.append(" " * (len(line) - i))
            break
        out.append(ch)
        i += 1
    return "".join(out)


def rewrite_line(line, labels, factor):
    """把一行里的数值参数改成 (n * F / F)。返回 (新行, 改动数)。"""
    code = mask_strings(line)
    changed = 0

    # 逐个函数调用处理，从内到外由 split_args 保证只切顶层
    for m in re.finditer(r"([\u4e00-\u9fffA-Za-z_][\u4e00-\u9fffA-Za-z0-9_]*)\(([^()]*(?:\([^()]*\)[^()]*)*)\)", code):
        name, inner = m.group(1), m.group(2)
        if name not in labels:
            continue
        args = split_top_level_args(inner)
        kinds = labels[name]
        new_args = list(args)
        for idx, arg in enumerate(args):
            kind = kinds[idx] if idx < len(kinds) else ""
            if not obfuscatable(kind):
                continue
            if not re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", arg):
                continue
            value = arg.strip()
            if float(value) >= 1e6:          # 地图 GUID 之类，放过
                continue
            new_args[idx] = "(%s * %d / %d)" % (value, factor, factor)
            changed += 1
        if changed:
            new_inner = ", ".join(new_args)
            # 只替换这一处（在原始行上按位置替换，保留字符串不动）
            start = m.start(2)
            end = m.end(2)
            line = line[:start] + new_inner + line[end:]
            code = mask_strings(line)
    return line, changed


def main():
    ap = argparse.ArgumentParser(description="工坊数值混淆")
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--factor", type=int, default=7, help="混淆系数，必须为奇数（默认 7）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--signatures", default=os.path.join(HERE, "..", "data", "signatures.md"))
    args = ap.parse_args()

    if args.factor % 2 == 0:
        sys.exit("系数必须是奇数，否则乘法可能引入浮点误差")

    labels = load_types(args.signatures)
    lines = open(args.src, encoding="utf-8").read().replace("\r\n", "\n").split("\n")

    stack, pending = [], None
    out_lines, total = [], 0
    for line in lines:
        stripped = line.strip()
        if stripped in core.BLOCK_KEYWORDS or stripped.startswith("规则("):
            pending = "规则" if stripped.startswith("规则(") else stripped
            out_lines.append(line)
            continue
        if stripped.startswith("{"):
            stack.append(pending or (stack[-1] if stack else None))
            pending = None
            out_lines.append(line)
            continue
        if stripped.startswith("}"):
            if stack:
                stack.pop()
            out_lines.append(line)
            continue

        block = stack[-1] if stack else None
        if block in ("动作", "条件"):
            new_line, n = rewrite_line(line, labels, args.factor)
            total += n
            out_lines.append(new_line)
        else:
            out_lines.append(line)

    text = "\n".join(out_lines)
    if args.dry_run:
        print(text)
        print("\n[dry-run] 共混淆 %d 处数值" % total, file=sys.stderr)
        return 0

    with open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", "\r\n"))
    print("已写出 %s，混淆 %d 处数值" % (args.out, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
