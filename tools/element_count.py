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


COMPARE = re.compile(r"\s*(==|!=|>=|<=|>|<|&&|\|\|)\s*")


def value_cost(expr, variables=None, depth=0):
    """一个表达式（不含外层减 1）的元素成本。权重来自 12 个标定探针（见 docs/limits.md）。"""
    e = expr.strip()
    variables = variables or set()
    if not e:
        return 0
    if re.fullmatch(r"-?\d+(\.\d+)?", e):
        return 2                      # 数字 = 数值() + 字面量
    if re.fullmatch(r'"[^"]*"', e):
        return 5 + len(re.findall(r"\{\d\}", e))
    m = re.match(r"^([\u4e00-\u9fff\w]+)\((.*)\)$", e)
    if m:
        name, inner = m.group(1), m.group(2)
        if name == "自定义字符串":
            return 5 + len(re.findall(r"\{\d\}", inner))
        args = [a for a in split_args(inner) if a.strip()]
        base = 2 if name == "数组" else 1
        return base + sum(value_cost(a, variables, depth + 1) for a in args)
    if re.match(r"^[^\s()]+\.[\w\u4e00-\u9fff]+$", e):
        return 2
    if depth >= 1 and e in SET_CONSTANTS:
        return 2                       # 集合类常量嵌在函数里 +1（实测 E01）
    return 1                           # 其余常量（含颜色/球体/可见）恒为 1（实测 H05-H07）


def split_args(s):
    out = []
    depth = 0
    cur = ""
    inside = False
    for ch in s:
        if ch == '"':
            inside = not inside
        if not inside:
            if ch in "，," and depth == 0:
                out.append(cur)
                cur = ""
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        cur += ch
    if cur.strip():
        out.append(cur)
    return out


COMPARE_BONUS = 3
IF_CALL_BONUS = 5      # 实测 K6：If(余数(1,3) == 0)
COND_COST = 3           # 实测 E4：条件块里一条 `1 == 1;` 记 3
IF_LITERAL_BONUS = 2   # 实测 K5：If(1 == 1)
FOR_BONUS = 3          # 实测 K11：For 全局变量(i,1,5,1)
ELSEIF_BONUS = 1       # 实测 K12：Else If 分支
BIGTEXT_ALLPLAYERS_DISCOUNT = 1   # 实测 K3/K8：大字体信息(所有玩家(…), …) 比通用模型少 1
# 只有"集合类"常量嵌在函数里才 +2；标量常量（白色/球体/可见…）仍算 1
SET_CONSTANTS = {"所有队伍", "所有玩家", "全部队伍", "所有英雄", "全部英雄", "全部", "双方", "队伍1", "队伍2"}   # While/If 的条件里出现比较运算符时固定 +3（实测 G02/G04）




def block_cost(line, variables=None):
    """While(...) / If(...) 这类块语句：1 + 条件成本（不打折），含比较再 +3。"""
    body = line.strip().rstrip(";")
    p1 = body.find("(")
    if p1 < 0:
        return 1
    cond = body[p1 + 1:body.rfind(")")]
    if re.search(r"==|!=|>=|<=|>|<", cond):
        return 1 + COMPARE_BONUS + 1      # 比较式条件固定 5（实测 G02/G04）
    return 1 + value_cost(cond, variables)


def statement_cost(line, variables=None):
    """一行动作或条件：本身 1 + 每个顶层参数 (成本-1)，最低 0。"""
    body = line.strip().rstrip(";")
    p = body.find("(")
    if p < 0:
        return 1
    params = [a for a in split_args(body[p + 1:body.rfind(")")]) if a.strip()]
    return 1 + sum(max(0, value_cost(a, variables) - 1) for a in params)


def estimate(path, sigs=None, labels=None):
    text = open(path, encoding="utf-8").read()
    rules = len(re.findall(r"^\s*规则\(", text, re.M))
    subs = 0
    variables = set(re.findall(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$", text, re.M))
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
        if block == "子程序" and re.match(r"^\d+\s*:\s*[A-Za-z_]\w*$", s):
            subs += 1
            continue
        if s in ("End;", "End"):
            continue
        if re.match(r"(While|If|Else If|For 全局变量|For 玩家变量)\(", s):
            inner_act += block_cost(s, variables)
            if s.startswith(("If(", "While(")):
                cond = s[s.find("(") + 1: s.rfind(")")]
                has_call = bool(re.search(r"[\u4e00-\u9fa5\w]+\(", cond))
                inner_act += IF_CALL_BONUS if has_call else IF_LITERAL_BONUS
            elif s.startswith("For "):
                inner_act += FOR_BONUS
            elif s.startswith("Else If("):
                inner_act += ELSEIF_BONUS
            continue
        if block == "条件":
            conds += 1
            # 条件里的数字字面量比动作里贵 2（实测 E4：`1 == 1` 记 3，`真 == 真` 记 1）
            inner_cond += statement_cost(s, variables) + 1 * len(re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", s))
        elif block == "动作":
            acts += 1
            cost = statement_cost(s, variables)
            if s.startswith("大字体信息(") and "所有玩家(" in s.split(",")[0]:
                cost = max(0, cost - BIGTEXT_ALLPLAYERS_DISCOUNT)
            inner_act += cost
    total = rules + inner_cond + inner_act
    detail = {"规则": rules, "子程序": subs, "条件": conds, "动作": acts,
              "条件内部": inner_cond, "动作内部": inner_act}
    return total, detail


def describe(detail):
    return "规则 %d / 子程序 %d / 条件 %d(内部 %d) / 动作 %d(内部 %d)" % (
        detail["规则"], detail["子程序"], detail["条件"], detail["条件内部"],
        detail["动作"], detail["动作内部"])

