#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""元素数估算。

依据：Zezombye（overpy 作者）的元素计算研究（workshop.codes wiki 收录）：
  - 规则 1、动作 1、条件 1、值函数 1
  - 数组 2、字符串 2（每个插值再 +1）、数字按 1 算
  - 动作/条件的每个顶层参数少算 1（最低 0）
  - 注释、设置块、事件块不计

本地校准：docs/element-costs.md 里 76 条实测用于对照，命中率写在 docs/limits.md。
结论口径：只用于"写的时候别撞 32768"，最终数字以游戏「显示诊断结果 → 总计元素数量」为准。
"""
import re

NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])")
CALL = re.compile(r"([\u4e00-\u9fffA-Za-z_][\u4e00-\u9fffA-Za-z0-9_]*)\(")
STRING = re.compile(r'"[^"\n]*"')


def value_cost(expr):
    """一个表达式（不含外层减 1）的元素成本。"""
    e = expr.strip()
    if not e:
        return 0
    cost = 0
    strings = STRING.findall(e)
    for s in strings:
        cost += 2 + s.count("{")          # 字符串本身 2，每个插值 +1
    stripped = STRING.sub("", e)
    calls = CALL.findall(stripped)
    cost += len(calls)                    # 每个函数/常量调用 1
    cost += len(NUMBER.findall(stripped)) # 每个数字 1
    if not calls and not strings and not NUMBER.search(stripped):
        cost += 1                         # 裸常量（真/假/空/事件玩家…）
    return cost


def statement_cost(line):
    """一行动作或条件：语句 1 + 参数成本 - 顶层参数个数。"""
    body = line.strip().rstrip(";")
    if not body:
        return 0
    args = []
    depth = 0
    cur = ""
    inside = False
    for ch in body:
        if ch == '"':
            inside = not inside
        if not inside:
            if ch in "，," and depth == 0 and cur.strip():
                args.append(cur)
                cur = ""
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        cur += ch
    if cur.strip():
        args.append(cur)
    total = 1
    for a in args:
        c = value_cost(a)
        total += max(0, c - 1)            # 顶层参数少算 1
    return total


def estimate(path, sigs=None, labels=None):
    text = open(path, encoding="utf-8").read()
    rules = len(re.findall(r"^\s*规则\(", text, re.M))
    subs = len(re.findall(r"^\s*\d+\s*:\s*[A-Za-z_]\w*\s*$", text, re.M))
    conds = acts = 0
    inner_cond = inner_act = 0
    stack, pending = [], None
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if s in ("事件", "条件", "动作", "变量", "设置", "子程序", "规则"):
            pending = s
            continue
        if s.startswith("{"):
            stack.append(pending or (stack[-1] if stack else None))
            pending = None
            continue
        if s.startswith("}"):
            if stack:
                stack.pop()
            continue
        block = stack[-1] if stack else None
        if not s or block in ("事件", "变量", "设置"):
            continue
        if block == "条件":
            conds += 1
            inner_cond += statement_cost(s)
        elif block == "动作":
            acts += 1
            inner_act += statement_cost(s)
    total = rules + subs + conds + acts + inner_cond + inner_act
    detail = {"规则": rules, "子程序": subs, "条件": conds, "动作": acts,
              "条件内部": inner_cond, "动作内部": inner_act}
    return total, detail


def describe(detail):
    return "规则 %d / 子程序 %d / 条件 %d(内部 %d) / 动作 %d(内部 %d)" % (
        detail["规则"], detail["子程序"], detail["条件"], detail["条件内部"],
        detail["动作"], detail["动作内部"])

