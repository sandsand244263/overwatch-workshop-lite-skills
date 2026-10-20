#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文 .ow 文件格式校验器。

基准：references/golden.ow（游戏里复制出来的真实文件），改代码前先看它。

用法：
  python lint_ow.py 文件.ow [更多文件...]

检查项（都会直接导致导入失败或行为异常）：
  1. 括号配对，跨行续写自动识别
  2. 语句以 ; 结尾；块收尾的 } 不加分号；设置块用 `键: 值`
  3. 不许尾逗号
  4. 条件块每行必须有比较运算
  5. 字符串用英文双引号且成对
  6. 变量名 / 子程序名只能是英文字母数字下划线，≤ 32 字符
  7. 变量块必须分 `全局:` / `玩家:` 两段，声明写段内
  8. 引用的变量必须已声明，且段位一致
  9. 函数名必须存在于签名表；参数个数不能超过签名；「可见」参数不能填真假
  10. 自定义字符串占位符不得超过 {2}
  11. 事件块只能是 1 行（全局事件）或 3 行（事件; 队伍; 英雄;）
  12. 持续 - 全局 规则里不许用 事件玩家
  13. 不存在 ===

退出码：0 无问题，1 有错误。
"""
import argparse
import os
import re
import sys

PLACEHOLDER = re.compile(r"\{(\d)\}")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COMPARISON = re.compile(r"==|!=|>=|<=|>|<")
VAR_REF = re.compile(r"(全局|本地玩家|事件玩家|攻击方|被攻击方|主机玩家|本市玩家)\.([A-Za-z_][A-Za-z0-9_]*)")

BLOCK_KEYWORDS = ("设置", "主程序", "大厅", "模式", "英雄", "地图工坊", "扩展",
                  "变量", "子程序", "规则", "事件", "条件", "动作")
CONTROL = ("While", "If", "Else If", "Else", "End", "For", "For 全局变量", "For 玩家变量",
           "如条件为“真”则循环", "如条件为“假”则循环",
           "如条件为“真”则中止", "如条件为“假”则中止")
SETTINGS_BLOCKS = ("设置", "主程序", "大厅", "模式", "英雄", "地图工坊", "扩展")
VAR_SECTIONS = ("全局:", "玩家:")


def split_args(text):
    args, buf = [], []
    depth, in_str, escaped = 0, False, False
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


def load_signatures(path):
    sigs, labels = {}, {}
    if not os.path.isfile(path):
        return sigs, labels
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


def scan_calls(text, sigs, labels, problems):
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
            continue
        if ch.isalpha() or ch == "_" or "\u4e00" <= ch <= "\u9fff":
            start = i
            while i < n and (text[i].isalnum() or text[i] == "_" or "\u4e00" <= text[i] <= "\u9fff"):
                i += 1
            name = text[start:i]
            if i < n and text[i] == "(" and name not in BLOCK_KEYWORDS and name not in CONTROL:
                depth, j, in_str = 1, i + 1, False
                while j < n and depth:
                    c = text[j]
                    if in_str:
                        if c == "\\":
                            j += 1
                        elif c == '"':
                            in_str = False
                    elif c == '"':
                        in_str = True
                    elif c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                    j += 1
                inner = text[i + 1:j - 1]
                line = text[:start].count("\n") + 1
                if sigs and name not in sigs:
                    problems.append((line, "error", "未知函数名：%s（签名表里没有）" % name))
                elif sigs:
                    total = sigs[name]
                    got = len(split_args(inner)) if inner.strip() else 0
                    if total == 0 and got:
                        problems.append((line, "error", "%s 不接受参数，实际给了 %d 个" % (name, got)))
                    elif got > total:
                        problems.append((line, "error", "%s 参数过多：最多 %d 个，实际 %d 个"
                                         % (name, total, got)))
                    elif got == 0 and total > 0:
                        problems.append((line, "error", "%s 至少需要 1 个参数" % name))
                    params = labels.get(name) or []
                    if params and params[0].endswith(":玩家") and inner.strip():
                        first = split_args(inner)[0].strip()
                        if first in ("真", "假", "True", "False"):
                            problems.append((line, "error",
                                             "%s 第 1 个参数是「可见」（玩家或玩家列表），不能填 %s"
                                             % (name, first)))
                i = j
                continue
            continue
        i += 1


def lint(path, sigs, labels):
    problems = []
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    text = raw.replace("\r\n", "\n")
    lines = text.split("\n")

    stack, pending = [], None
    paren_depth = 0
    var_section = None
    declared = {"全局": set(), "玩家": set()}
    global_rule = False
    in_comment = False

    for ln, line in enumerate(lines, 1):
        code = strip_noise(line)
        stripped = code.strip()

        if in_comment:
            if "*/" in line:
                in_comment = False
            continue
        if "/*" in line and "*/" not in line:
            in_comment = True
            continue

        opens = code.count("(") - code.count(")")
        if paren_depth > 0:                      # 续行：只跟括号，不判语句结束
            paren_depth += opens
            continue
        if not stripped:
            continue

        for num in PLACEHOLDER.findall(line):
            if int(num) > 2:
                problems.append((ln, "error", "自定义字符串占位符只能到 {2}，发现 {%s}" % num))
        if "===" in code:
            problems.append((ln, "error", "工坊没有 ===，赋值用 =，比较用 =="))

        block = stack[-1] if stack else None

        if block == "变量" and stripped in VAR_SECTIONS:
            var_section = stripped.rstrip(":")
            continue

        if stripped in BLOCK_KEYWORDS or stripped.startswith("规则("):
            pending = "规则" if stripped.startswith("规则(") else stripped
            if stripped.endswith("{"):
                stack.append(pending)
                if pending == "规则":
                    global_rule = False
                if pending == "变量":
                    var_section = None
                pending = None
            continue
        if stripped.startswith("{") or stripped == "{":
            label = pending or (stack[-1] if stack else None)
            stack.append(label)
            if label == "规则":
                global_rule = False
            if label == "变量":
                var_section = None
            pending = None
            continue
        if stripped.startswith("}"):
            if stack:
                stack.pop()
            continue
        block = stack[-1] if stack else None

        if block == "子程序":
            if not re.match(r"^\d+\s*:", stripped):
                problems.append((ln, "error", "子程序块里只能写 `索引: 子程序名`：%s" % stripped))
            else:
                name = stripped.split(":", 1)[1].strip()
                if not IDENT.match(name):
                    problems.append((ln, "error", "子程序名只能用英文字母/数字/下划线：%s" % name))
            continue

        if block == "变量":
            if re.match(r"^\d+\s*:", stripped):
                if var_section is None:
                    problems.append((ln, "error", "变量声明必须写在 `全局:` 或 `玩家:` 段内"))
                else:
                    name = stripped.split(":", 1)[1].strip()
                    if not IDENT.match(name):
                        problems.append((ln, "error", "变量名只能用英文字母/数字/下划线：%s" % name))
                    elif len(name) > 32:
                        problems.append((ln, "error", "变量名超过 32 字符：%s" % name))
                    else:
                        declared[var_section].add(name)
                continue
            problems.append((ln, "error", "变量块里只能有 `全局:` / `玩家:` 段和 `索引: 变量名`"))
            continue

        if block in SETTINGS_BLOCKS:
            continue

        if global_rule and "事件玩家" in code:
            problems.append((ln, "error", "持续 - 全局 规则里不能用 事件玩家，用 本地玩家"))
        if block == "规则" and stripped.startswith("持续 - 全局;"):
            global_rule = True

        if block == "事件":
            if not stripped.endswith(";") and opens <= 0:
                problems.append((ln, "error", "事件行缺少分号"))
            continue

        if block == "条件":
            if not stripped.endswith(";") and opens <= 0:
                problems.append((ln, "error", "条件行缺少分号"))
            body = stripped.rstrip(";")
            if body and not COMPARISON.search(body):
                problems.append((ln, "error", "条件缺少比较运算（== != > < >= <=）"))
            continue

        if stripped.startswith('"') and stripped.endswith('"'):   # 动作块里的纯字符串行 = 注释
            continue

        if block in ("动作", "子程序"):
            if not stripped.endswith(";") and not stripped.endswith("{") and opens <= 0:
                problems.append((ln, "error", "语句缺少分号"))
            if re.search(r",\s*\)", stripped):
                problems.append((ln, "error", "不允许尾逗号"))

        if opens > 0:
            paren_depth += opens

    for chunk in re.findall(r"事件\s*\{([^}]*)\}", text, re.S):
        count = len([x for x in chunk.split(";") if x.strip()])
        if count not in (0, 1, 3):
            problems.append((0, "error",
                             "事件块只能是 1 行（全局事件）或 3 行（事件; 队伍; 英雄;），这里是 %d 行" % count))

    masked = strip_noise(text)
    for m in VAR_REF.finditer(masked):
        owner, name = m.group(1), m.group(2)
        section = "全局" if owner == "全局" else "玩家"
        if name not in declared[section]:
            problems.append((0, "warning", "变量 %s.%s 未声明（应在 `%s:` 段里）" % (owner, name, section)))

    scan_calls(masked, sigs, labels, problems)

    if raw.count('"') % 2:
        problems.append((0, "error", "双引号数量是奇数，有字符串没闭合"))

    seen, unique = set(), []
    for item in problems:
        key = (item[0], item[2])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def main():
    ap = argparse.ArgumentParser(description="中文 .ow 格式校验")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--signatures", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "references", "signatures.md"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    sigs, labels = load_signatures(args.signatures)
    if not sigs and not args.quiet:
        print("[提示] 没读到签名表 %s，只做结构检查" % args.signatures)

    failed = 0
    for path in args.files:
        if not os.path.isfile(path):
            print("[错误] 找不到 %s" % path)
            failed += 1
            continue
        problems = lint(path, sigs, labels)
        errors = [p for p in problems if p[1] == "error"]
        name = os.path.basename(path)
        if errors:
            failed += 1
        if problems:
            print("✗ %s：%d 个问题" % (name, len(problems)))
            for ln, level, msg in problems:
                where = "第 %d 行" % ln if ln else "全文"
                print("   %s %s：%s" % (where, level, msg))
        elif not args.quiet:
            print("✓ %s：通过" % name)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
