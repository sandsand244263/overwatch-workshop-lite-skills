#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工坊 .ow 解析器（元素计数专用，保留完整表达式树）。

只做计数需要的解析，不校验语法、不改写文本。产出：
    parse_file(path) -> Program(rules=[Rule(...)], vars=..., subs=...)
    collect(program) -> 特征字典（各类节点数量）

表达式节点用 tuple 表示，便于快速统计：
    ('num', text)            数字字面量（含小数、负数）
    ('str', text, n_interp)  字符串字面量
    ('call', name, [args])   值函数/动作调用
    ('var', name, [idx])     变量访问 全局.X / 事件玩家.Y[1]
    ('const', name)          裸常量（真/空/白色/顶部/所有队伍…）
    ('bin', op, l, r)        二元运算 + - * / % == != > < >= <= && ||
    ('un', op, x)            一元 ! / -
"""
import re

SEP = "，,"
COMMENT = "//"

# 语句块关键字（行首去空白后匹配）
BLOCK_START = re.compile(r"^(If|Else If|Else|While|For 全局变量|For 玩家变量|For 数组元素)\s*\(")
KEYWORDS = {"设置", "变量", "子程序", "规则", "事件", "条件", "动作"}


BLOCK_HDR = re.compile(r"^(If|Else If|Else|While|For 全局变量|For 玩家变量|For 数组元素)\s*(\(.*\))?$", re.S)


def norm(text):
    """去 BOM、统一换行。注释剥离放在扫描阶段做（要区分字符串内部）。"""
    if text.startswith("\ufeff"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def scan_units(s, i=0):
    """字符扫描：返回 (units, next_index)。

    unit = ('block', header, [sub_units]) 或 ('stmt', text)
    处理三件 line-based 拆分搞不定的事：
      - 跨行字符串（字符串内可以换行，里面有 // 也不能当注释）
      - 跨行块头（While( 换行 条件 )）
      - 行内 // 注释
    """
    units = []
    buf = []
    paren = 0
    in_str = False
    n = len(s)
    while i < n:
        ch = s[i]
        if in_str:
            buf.append(ch)
            if ch == '"' and s[i - 1] != "\\":
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            buf.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and s[i + 1] == "/":
            while i < n and s[i] != "\n":
                i += 1
            continue
        if ch == "{":
            header = "".join(buf).strip()
            buf = []
            sub, i = scan_units(s, i + 1)
            units.append(("block", header, sub))
            continue
        if ch == "}":
            if buf:
                st = "".join(buf).strip()
                if st:
                    units.append(("stmt", st))
            return units, i + 1
        if ch in "([":
            paren += 1
        elif ch in ")]":
            paren -= 1
        elif ch == ";" and paren == 0:
            st = "".join(buf).strip()
            if st:
                units.append(("stmt", st))
            buf = []
            i += 1
            continue
        buf.append(ch)
        if paren == 0:
            st = "".join(buf).strip()
            if st == "Else":
                units.append(("stmt", st))
                buf = []
            elif ch == ")" and BLOCK_HDR.match(st):
                units.append(("stmt", st))
                buf = []
        i += 1
    if buf:
        st = "".join(buf).strip()
        if st:
            units.append(("stmt", st))
    return units, i


def parse_file(path):
    """-> {'rules': [{'name','cond':[stmt..],'acts':[stmt..]}], 'name': ...}"""
    text = norm(open(path, encoding="utf-8").read())
    units, _ = scan_units(text)
    prog = {"rules": [], "name": "", "vars": 0, "subs": 0}
    for u in units:
        if u[0] != "block":
            continue
        head, body = u[1], u[2]
        if head.startswith("规则"):
            m = re.search(r'规则\("(.*)"\)', head, re.S)
            rule = {"name": m.group(1) if m else "", "cond": [], "acts": []}
            for b in body:
                if b[0] == "block" and b[1] == "条件":
                    rule["cond"] = [x[1] for x in b[2] if x[0] == "stmt"]
                elif b[0] == "block" and b[1] == "动作":
                    rule["acts"] = [x[1] for x in b[2] if x[0] == "stmt"]
            prog["rules"].append(rule)
        elif head == "子程序":
            prog["subs"] = len([x for x in body if x[0] == "stmt"])
        elif head.startswith("设置"):
            m = re.search(r'模式名称:\s*"(.*)"', "".join(str(x) for x in body))
            if m:
                prog["name"] = m.group(1)
    return prog


# ---------------------------------------------------------------- 表达式解析
class P:
    def __init__(self, s):
        self.s = s
        self.i = 0

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t\n":
            self.i += 1

    def peek(self):
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def eat(self, t):
        self.ws()
        if self.s.startswith(t, self.i):
            self.i += len(t)
            return True
        return False

    def parse(self):
        node = self.expr()
        self.ws()
        # 三元： 条件 ? 值1 : 值2 （.ow 里可以跨行写）
        while self.i < len(self.s) and self.s[self.i] == "?":
            self.i += 1
            a = self.expr()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] in ":：":
                self.i += 1
            b = self.expr()
            node = ("tern", node, a, b)
            self.ws()
        return node

    # 二元：优先级从低到高
    LEVELS = [("||",), ("&&",), ("==", "!="), (">=", "<=", ">", "<"), ("+", "-"), ("*", "/", "%")]

    def expr(self, lv=0):
        if lv >= len(self.LEVELS):
            return self.unary()
        left = self.expr(lv + 1)
        while True:
            self.ws()
            op = None
            for cand in self.LEVELS[lv]:
                if self.s.startswith(cand, self.i):
                    op = cand
                    break
            if op is None:
                return left
            self.i += len(op)
            right = self.expr(lv + 1)
            left = ("bin", op, left, right)

    def unary(self):
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "!":
            self.i += 1
            return ("un", "!", self.unary())
        if self.i < len(self.s) and self.s[self.i] == "-":
            # 负数字面量优先当作数字
            m = re.match(r"-(\d+(?:\.\d+)?)", self.s[self.i:])
            if m:
                self.i += m.end()
                return ("num", "-" + m.group(1))
            self.i += 1
            return ("un", "-", self.unary())
        return self.primary()

    def primary(self):
        self.ws()
        if self.i >= len(self.s):
            return ("const", "")
        ch = self.s[self.i]
        if ch == "(":
            self.i += 1
            node = self.expr()
            self.eat(")")
            return ("paren", node)
        if ch == '"':
            self.i += 1
            start = self.i
            while self.i < len(self.s) and self.s[self.i] != '"':
                if self.s[self.i] == "\\":
                    self.i += 2
                    continue
                self.i += 1
            raw = self.s[start:self.i]
            self.i += 1
            return ("str", raw, len(re.findall(r"\{\d+\}", raw)))
        m = re.match(r"(\d+(?:\.\d+)?)", self.s[self.i:])
        if m:
            self.i += m.end()
            return ("num", m.group(1))
        # 标识符：中文名 / 英文名，可能带 .成员 和 [索引]
        m = re.match(r"([^\s(),\[\]=<>!&|+\-*/%;]+)", self.s[self.i:])
        if not m:
            self.i += 1
            return ("const", "")
        name = m.group(1)
        self.i += len(name)
        # 调用
        if self.peek() == "(":
            self.i += 1
            args = self.arglist()
            return ("call", name, args)
        # 变量：全局.X / 事件玩家.X 已被上面的正则整体吃掉（含点号）
        idx = []
        while self.peek() == "[":
            self.i += 1
            idx.append(self.expr())
            self.eat("]")
        if "." in name or idx:
            return ("var", name, idx)
        return ("const", name)

    def arglist(self):
        args = []
        while True:
            self.ws()
            if self.i >= len(self.s):
                break
            if self.s[self.i] == ")":
                self.i += 1
                break
            if self.s[self.i] in SEP:
                args.append(("const", ""))
                self.i += 1
                continue
            args.append(self.parse())      # 参数里也要认三元
            self.ws()
            if self.i < len(self.s) and self.s[self.i] in SEP:
                self.i += 1
                continue
            if self.peek() == ")":
                self.i += 1
                break
        return [a for a in args if not (a[0] == "const" and a[1] == "")]


def parse_expr(s):
    s = s.strip().rstrip(";").strip()
    if not s:
        return ("const", "")
    return P(s).parse()


# ---------------------------------------------------------------- 语句拆分
def split_top(s):
    """按顶层逗号切参数（保留原文片段）。"""
    out, depth, cur, in_str = [], 0, [], False
    for ch in s:
        if ch == '"':
            in_str = not in_str
        if not in_str:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch in SEP and depth == 0:
                out.append("".join(cur))
                cur = []
                continue
        cur.append(ch)
    out.append("".join(cur))
    return [x.strip() for x in out]


def parse_statement(st):
    """语句 -> (kind, payload)。kind: act/cond/block/assign/callstmt/end"""
    s = st.strip()
    if s in ("End;", "End"):
        return ("end", None)
    m = re.match(r"^(Else If|If|While|For 全局变量|For 玩家变量|For 数组元素|Else)\s*(\(.*\))?\s*;?$", s, re.S)
    if m:
        head = m.group(1)
        inner = m.group(2)
        args = []
        if inner:
            args = [parse_expr(a) for a in split_top(inner[1:-1]) if a.strip()]
        return ("block", (head, args))
    body = s.rstrip(";").strip()
    depth = 0
    in_str = False
    for i, ch in enumerate(body):
        if ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            elif ch == "=" and depth == 0:
                prev = body[i - 1] if i else ""
                nxt = body[i + 1] if i + 1 < len(body) else ""
                if nxt == "=" or prev in "=!<>":
                    continue
                return ("assign", (parse_expr(body[:i]), parse_expr(body[i + 1:])))
    return ("callstmt", parse_expr(body))


# ---------------------------------------------------------------- 成本模型
# 全部权重由探针实测反推，逐项来源见 docs/element-reverse.md 的标定表。
# 记号：一个"值"节点 = 一个元素；语句（动作/条件）= 1 个元素 + 各值参数。
W = {
    "rule": 1,           # 规则
    "stmt": 1,           # 一条动作 / 条件语句
    "num": 1,            # 数字字面量（值位置）
    "str": 3,            # 字符串字面量本体
    "interp": 1,         # 每个 {n} 插值
    "call": 1,           # 值函数本体
    "var": 1,            # 变量取值 全局.X / 事件玩家.Y
    "const_value": 1,    # 玩家/队伍这类"集合常量"当值
    "const_inline": 0,   # 枚举 / 布尔 / 空 / 效果名 等内联常量
    "array": 1,          # 数组本体
    "array_slot": 1,     # 数组每个元素槽位（+ 元素本身）
    "bin": 1,            # 二元运算符（数组项里记 2，见 bin_item）
    "bin_item": 2,       # 乘法/加法出现在数组项里时
    "break": 1,          # 中断 / 继续 / 返回
    "blk_If": 5,         # 块结构本体（If / While / For 都是 5）
    "blk_ElseIf": 5,
    "blk_Else": 3,
    "blk_While": 5,
    "blk_For": 5,
    "tern": 5,           # 三元表达式本体（实测 G3=1101 反推）
    "var_player": 2,
    "var_index": 2,      # 每个下标多算 2（实测 H1=501 反推）     # 事件玩家 / 本地玩家 取值比 全局 贵 1（实测 G2=301）
}

# 少数值函数的本体成本不是 1（实测 自定义颜色 = 4，相当于"四分量向量"另计）
CALL_BASE = {
    "自定义颜色": 4,
}
# 这些值函数的参数是"内联字面量"，不再逐个计元素（实测 自定义字符串 的插值参数）
FREE_ARGS = {
    "自定义字符串",
}
# 玩家/队伍/英雄这类"集合"常量当值用时计 1；其余裸常量（枚举、布尔、空、效果名）计 0
CONST_VALUE = {
    "所有队伍", "双方", "队伍1", "队伍2", "所有玩家", "全部队伍", "全部玩家",
    "所有英雄", "全部英雄", "主机玩家", "本地玩家", "事件玩家", "当前玩家",
    "攻击方", "被攻击方", "空数组",
}

# 写操作：第 0 个参数是变量目标，不计元素（目标若带下标，下标表达式照常计）
WRITE_TARGET = {
    "设置全局变量", "设置玩家变量", "修改全局变量", "修改玩家变量",
    "设置数组元素", "修改数组元素",
}


def cost(node, in_item=False):
    """一个值节点的元素成本。in_item=True 表示处在数组槽位里（数字/运算符按 2 计）。"""
    t = node[0]
    if t == "num":
        return W["num"]          # 数组里那多出来的 1 由 array_slot 提供
    if t == "str":
        return W["str"] + W["interp"] * node[2]
    if t == "call":
        name, args = node[1], node[2]
        if name == "数组":
            return W["array"] + sum(W["array_slot"] + cost(a, True) for a in args)
        total = CALL_BASE.get(name, W["call"])
        if name in FREE_ARGS:
            # 只算字符串本体；插值参数不逐个计
            if args:
                total += cost(args[0], True)
            return total
        for a in args:
            total += cost(a, False)
        return total
    if t == "var":
        owner = node[1].split(".")[0]
        base = W["var_player"] if owner in ("事件玩家", "本地玩家") else W["var"]
        return base + W["var_index"] * len(node[2]) + sum(cost(a) for a in node[2])
    if t == "const":
        return W["const_value"] if node[1] in CONST_VALUE else W["const_inline"]
    if t == "bin":
        base = W["bin_item"] if in_item else W["bin"]
        return base + cost(node[2], in_item) + cost(node[3], in_item)
    if t == "un":
        return W["bin"] + cost(node[2], in_item)
    if t == "paren":
        return cost(node[1], in_item)
    if t == "tern":
        # 条件 ? 值1 : 值2 —— 一个三元元素 + 三部分
        return W["tern"] + cost(node[1]) + cost(node[2]) + cost(node[3])
    return 0


def stmt_cost(kind, payload):
    if kind == "end":
        return 0
    if kind == "block":
        head, args = payload
        key = "blk_For" if head.startswith("For") else "blk_" + head
        total = W.get(key, 5)
        for a in args:
            total += cost(a)
        return total
    if kind == "assign":
        tgt, val = payload
        total = W["stmt"]
        if tgt[0] == "var" and tgt[2]:
            total += W["array_slot"]          # 带下标的赋值目标多一个槽位
            for a in tgt[2]:
                total += cost(a)
        return total + cost(val)
    if kind == "callstmt":
        node = payload
        if node[0] == "bin":
            # 条件行：语句 1 + 两侧操作数（比较符本身不计，实测 E4）
            return W["stmt"] + cost(node[2]) + cost(node[3])
        if node[0] == "call":
            name, args = node[1], node[2]
            total = W["stmt"]
            for i, a in enumerate(args):
                if i == 0 and name in WRITE_TARGET:
                    continue
                total += cost(a)
            return total
        return W["stmt"] + cost(node)
    return 0


def estimate2(path, detail=False):
    """返回整份 .ow 的元素数（复刻游戏"总计元素数量"的算法）。"""
    prog = parse_file(path)
    total = W["rule"] * len(prog["rules"])
    parts = {"规则": total}
    for rule in prog["rules"]:
        for st in rule["cond"]:
            kind, payload = parse_statement(st)
            c = stmt_cost(kind, payload)
            parts["条件"] = parts.get("条件", 0) + c
            total += c
        for st in rule["acts"]:
            kind, payload = parse_statement(st)
            c = stmt_cost(kind, payload)
            parts["动作"] = parts.get("动作", 0) + c
            total += c
    return (total, parts) if detail else total
