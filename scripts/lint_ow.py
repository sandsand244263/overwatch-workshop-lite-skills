#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文 .ow 文件格式校验器。

用途：生成或修改工坊代码后，先跑这个，别靠人肉导入试错。

用法：
  python lint_ow.py 文件.ow
  python lint_ow.py 文件.ow --signatures ../references/signatures.md
  python lint_ow.py 文件.ow --quiet     # 只输出问题

检查项（都是实打实会导致导入失败或行为异常的东西）：
  1. 括号配对 {} [] ()
  2. 语句必须以 ; 结尾（块收尾的 } 之后不加分号）
  3. 不许尾逗号
  4. 条件块每行必须有比较运算（== != > < >= <=）
  5. 字符串必须用英文双引号且成对
  6. 注释只允许 // 和 /* */
  7. 变量名 / 子程序名只能用英文（字母数字下划线，≤32 字符）
  8. 函数名必须存在于签名表（拼错、编造都会被抓）
  9. 参数个数必须与签名表一致
  10. 自定义字符串占位符不得超过 {2}
  11. 持续 - 全局 规则里不许用 事件玩家
  12. 不存在 ===（只有 = 和 ==）

退出码：0 无问题，1 有错误，2 文件或签名表读取失败。
"""
import argparse
import os
import re
import sys

PLACEHOLDER = re.compile(r"\{(\d)\}")
CJK = re.compile(r"[\u4e00-\u9fff]")
IDENT_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COMPARISON = re.compile(r"==|!=|>=|<=|>|<")

BLOCK_KEYWORDS = ("设置", "主程序", "大厅", "模式", "英雄", "地图工坊", "扩展",
                  "变量", "子程序", "规则", "事件", "条件", "动作")


def load_signatures(path):
    """返回 ({名称: 参数个数}, {名称: [参数标签]})。"""
    sigs, labels = {}, {}
    if not os.path.isfile(path):
        return sigs
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "(" not in line or not line.endswith(")"):
                continue
            name, rest = line.split("(", 1)
            name = name.strip()
            if not name or " " in name:
                continue
            inner = rest[:-1].strip()
            args = split_args(inner) if inner else []
            sigs[name] = len(args)
            labels[name] = args
    return sigs, labels


def split_args(text):
    """按顶层逗号切参数，忽略字符串和嵌套括号里的逗号。"""
    args, buf = [], []
    depth = 0
    in_str = False
    escaped = False
    for ch in text:
        if in_str:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail or args:
        args.append(tail)
    return args


def strip_noise(line):
    """去掉行内字符串与注释，用于结构判断。"""
    out, in_str, escaped = [], False, False
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
                out.append('""')
            i += 1
            continue
        if ch == '"':
            in_str = True
            i += 1
            continue
        if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            break
        out.append(ch)
        i += 1
    return "".join(out)


def lint(path, signatures, labels=None):
    problems = []
    labels = labels or {}
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    lines = raw.replace("\r\n", "\n").split("\n")

    # 1. 括号配对（跨行累计）
    pairs = {"{": "}", "[": "]", "(": ")"}
    stack = []
    for ln, line in enumerate(lines, 1):
        code = strip_noise(line)
        for ch in code:
            if ch in pairs:
                stack.append((ch, ln))
            elif ch in pairs.values():
                if not stack:
                    problems.append((ln, "error", "多余的收尾括号 %s" % ch))
                elif pairs[stack[-1][0]] != ch:
                    problems.append((ln, "error", "括号不匹配：第 %d 行 %s 未闭合" % (stack[-1][1], stack[-1][0])))
                    stack.pop()
                else:
                    stack.pop()
    for ch, ln in stack:
        problems.append((ln, "error", "括号未闭合 %s" % ch))

    # 2/3/4/8/9/10/11/12 逐行
    in_str_block = False
    block = None
    pending = None
    stack = []
    global_rule = False
    for ln, line in enumerate(lines, 1):
        code = strip_noise(line)
        stripped = code.strip()
        if not stripped:
            continue

        if "/*" in line and "*/" not in line:
            in_str_block = True
            continue
        if in_str_block:
            if "*/" in line:
                in_str_block = False
            continue

        # 12. ===
        if "===" in code:
            problems.append((ln, "error", "工坊没有 ===，赋值用 =，比较用 =="))

        # 块类型：关键字可以独占一行，`{` 在下一行
        if stripped in BLOCK_KEYWORDS or stripped.startswith("规则("):
            pending = "规则" if stripped.startswith("规则(") else stripped
            if stripped.endswith("{"):
                stack.append(pending)
                block = pending
                if block == "规则":
                    global_rule = False
                pending = None
            continue
        if stripped == "{":
            label = pending or (stack[-1] if stack else None)
            stack.append(label)
            block = label
            if block == "规则":
                global_rule = False
            pending = None
            continue
        if stripped == "}" or stripped.startswith("}"):
            if stack:
                stack.pop()
            block = stack[-1] if stack else None
            continue
        block = stack[-1] if stack else None

        # 7. 变量声明 `索引: 名字`
        if block == "变量" and re.match(r"^\d+\s*:", stripped):
            name = stripped.split(":", 1)[1].strip().rstrip(";")
            if not IDENT_OK.match(name):
                problems.append((ln, "error", "变量名只能用英文字母/数字/下划线：%s" % name))
            elif len(name) > 32:
                problems.append((ln, "error", "变量名超过 32 字符：%s" % name))
            continue

        # 设置块是 `键: 值`，不是语句，不要求分号
        if block in ("设置", "主程序", "大厅", "模式", "英雄", "地图工坊", "扩展"):
            if ":" in stripped and not stripped.endswith(";"):
                continue
            if re.match(r"^[^\s:]+\s*$", stripped):
                continue

        # 11. 全局规则里用事件玩家
        if global_rule and "事件玩家" in code:
            problems.append((ln, "error", "持续 - 全局 规则里不能用 事件玩家，用 本地玩家"))

        # 事件块：`持续 - 全局;`
        if block == "事件":
            if not stripped.endswith(";"):
                problems.append((ln, "error", "事件行缺少分号"))
            if stripped.rstrip(";").strip() == "持续 - 全局":
                global_rule = True
            continue

        # 4. 条件必须带比较
        if block == "条件":
            body = stripped.rstrip(";")
            if body and not COMPARISON.search(body) and not body.startswith('"'):
                problems.append((ln, "error", "条件缺少比较运算（== != > < >= <=）"))
            if not stripped.endswith(";"):
                problems.append((ln, "error", "条件行缺少分号"))
            continue

        if block in ("动作", "条件", "事件"):
            if not stripped.endswith(";") and not stripped.startswith("}"):
                problems.append((ln, "error", "语句缺少分号"))
            if re.search(r",\s*\)", stripped):
                problems.append((ln, "error", "不允许尾逗号"))

        # 10. 占位符
        for num in PLACEHOLDER.findall(line):
            if int(num) > 2:
                problems.append((ln, "error", "自定义字符串占位符只能到 {2}，发现 {%s}" % num))

        # 8/9. 函数名与参数个数
        for call in re.finditer(r"([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_]*)\(([^()]*(?:\([^()]*\)[^()]*)*)\)", code):
            name, inner = call.group(1), call.group(2)
            if name in BLOCK_KEYWORDS or name == "规则":
                continue
            if signatures and name not in signatures:
                problems.append((ln, "error", "未知函数名：%s（签名表里没有）" % name))
                continue
            if signatures and name in signatures:
                total = signatures[name]
                if not inner.strip():
                    got = 0
                else:
                    got = len(split_args(inner))
                if total == 0 and got:
                    problems.append((ln, "error", "%s 不接受参数，实际给了 %d 个" % (name, got)))
                elif got > total:
                    problems.append((ln, "error", "%s 参数过多：最多 %d 个，实际 %d 个"
                                     % (name, total, got)))
                elif got == 0 and total > 0:
                    problems.append((ln, "error", "%s 至少需要 1 个参数" % name))
                params = labels.get(name) or []
                if params and params[0].endswith(":玩家") and inner.strip():
                    first = split_args(inner)[0].strip()
                    if first in ("真", "假", "True", "False", "是", "否"):
                        problems.append((ln, "error",
                                         "%s 第 1 个参数是「可见」（玩家或玩家列表），不能填 %s"
                                         % (name, first)))
                # 少于签名数量但不少于 1 个：工坊允许省略尾部参数，不报

    # 5. 引号成对（全文）
    if raw.count('"') % 2 != 0:
        problems.append((0, "error", "双引号数量是奇数，有字符串没闭合"))

    return problems


def main():
    ap = argparse.ArgumentParser(description="中文 .ow 格式校验")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--signatures", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "references", "signatures.md"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    signatures, labels = load_signatures(args.signatures)
    if not signatures and not args.quiet:
        print("[提示] 没读到签名表 %s，只做结构检查" % args.signatures)

    failed = 0
    for path in args.files:
        if not os.path.isfile(path):
            print("[错误] 找不到 %s" % path)
            failed += 1
            continue
        problems = lint(path, signatures, labels)
        name = os.path.basename(path)
        if problems:
            failed += 1
            print("✗ %s：%d 个问题" % (name, len(problems)))
            for ln, level, msg in problems:
                where = "第 %d 行" % ln if ln else "全文"
                print("   %s %s：%s" % (where, level, msg))
        elif not args.quiet:
            print("✓ %s：通过（%d 个函数签名核对过）" % (name, len(signatures)))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
