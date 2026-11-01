#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish.py 的进阶混淆零件，逐项对齐 VS Code 插件 obfuscate.ts。

每个函数都只管一件事、返回 (新文本, 统计)，方便单测和排错：
  split_indices        索引混淆 / 本地索引混淆（插件里是两套算法，这里分开）
  strip_viewer_actions 删掉「记入查看器 / 启用查看器录制 / 禁用查看器录制」动作
  rebuild_tables       变量表和子程序表整表重建，填满 128 位假条目
  fill_rules           按元素预算填充假规则（查看器警告 + 篡改保护 + 1 元素空规则）
  obfuscate_strings    混淆字符串：字符位移到私用区码位（支持 @SKIP_OBFUSCATE_STRING）
"""
import random
import re

# 插件里「本地索引」只改这些客户端计算函数的下标，其余走服务端索引混淆
CLIENT_FUNCS = (
    "开始镜头", "小字体信息", "大字体信息", "创建光束效果", "创建效果", "播放效果",
    "创建图标", "创建地图文本", "创建进度条地图文本", "创建HUD文本", "创建进度条HUD文本",
    "创建弹道", "创建弹道效果", "创建追踪弹道", "设置目标点描述",
)

VIEWER_ACTIONS = ("禁用查看器录制", "启用查看器录制", "记入查看器")

MAX_RULES = 11500          # 实测约 12375 条会触发「自定游戏设置过大」，保守取 11500
PRIVATE_USE_SHIFT = 0xE0000


# ---------- 索引 ----------

INDEX_FACTORS = (3, 7, 9, 11, 13)


def index_expr(n, rng):
    """下标藏法：`(n * m / m)`，IEEE 下与 n 完全相等（issue #9）。

    旧写法 `[乘(10000000, 0.0000021)]` 有 12% 的整数算不回原值，下标会差一位。
    """
    m = rng.choice(INDEX_FACTORS)
    if (n * m) / m != n:
        return None
    return "[(%d * %d / %d)]" % (n, m, m)


def split_indices(text, do_server=True, do_local=True, seed=20261031):
    """条件区和服务端条目用 乘(...) 藏下标；客户端计算函数用小数抖动。

    本地抖动只往正方向偏 0~0.4：游戏不管是四舍五入还是截断，取回来都还是原下标。
    插件用的是 ±0.4，往负方向偏一截就有变成 n-1 的风险，这里收紧。
    """
    rng = random.Random(seed)
    out, s_hits, l_hits = [], 0, 0
    for line in text.split("\n"):
        stripped = line.strip()
        is_client = any(stripped.startswith(f + "(") for f in CLIENT_FUNCS)
        if is_client and do_local:
            def _local(m):
                return "[%.3f]" % (int(m.group(1)) + rng.uniform(0.0, 0.4))
            new, n = re.subn(r"\[(\d+)\]", _local, line)
            l_hits += n
            line = new
        elif (not is_client) and do_server:
            def _server(m):
                v = int(m.group(1))
                return index_expr(v, rng) or m.group(0)
            new, n = re.subn(r"\[(\d+)\]", _server, line)
            s_hits += n
            line = new
        out.append(line)
    return "\n".join(out), (s_hits, l_hits)


# ---------- 查看器条目 ----------

def strip_viewer_actions(text):
    """删掉查看器类动作，别人就不能靠查看器读你的逻辑（插件混淆时也会删）。"""
    out, removed = [], 0
    for line in text.split("\n"):
        s = line.strip()
        if any(s.startswith(name) for name in VIEWER_ACTIONS):
            removed += 1
            continue
        out.append(line)
    return "\n".join(out), removed


# ---------- 变量表 / 子程序表 ----------

def _block_span(lines, header):
    """找 `名字` 或 `名字 {` 开头的块，返回 (头行号, 尾行号, 块内行)。"""
    for i, line in enumerate(lines):
        s = line.strip()
        if s == header or s == header + "{" or s.startswith(header + " ") or s.startswith(header + "{"):
            depth, start = 0, None
            for j in range(i, len(lines)):
                depth += lines[j].count("{") - lines[j].count("}")
                if "{" in lines[j] and start is None and depth > 0:
                    start = j
                if start is not None and depth == 0:
                    return i, j, lines[start + 1:j]
            return None
    return None


def _decl_names(lines):
    """取出 `N: 名字` 形式的声明名，按出现顺序。"""
    names = []
    for line in lines:
        m = re.match(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$", line)
        if m:
            names.append(m.group(1))
    return names


def _split_by_group(body):
    """变量块按 `全局:` / `玩家:` 分组，返回 [(组名, [名字...])]。"""
    groups, cur = [], None
    for line in body:
        s = line.strip()
        if s in ("全局:", "玩家:"):
            cur = (s[:-1], [])
            groups.append(cur)
            continue
        m = re.match(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$", line)
        if m and cur is not None:
            cur[1].append(m.group(1))
    return groups


def _name_pool(rng, count, taken):
    """生成 count 个 8 位小写随机名，避开 taken 里已有的。"""
    out = set()
    while len(out) < count:
        name = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(8))
        if name not in taken and name not in out:
            out.add(name)
    return sorted(out)


def rebuild_tables(text, seed=20261031):
    """变量表 / 子程序表整表重建：真名保留，其余用假名填满 128 位。

    对齐插件「混淆变量」：插件直接把两张表重写成 128 条随机名（真名也在里面），
    所以别人看到的是满满两页无意义名字，分不清哪个在用。
    """
    lines = text.split("\n")
    rng = random.Random(seed)
    stats = {"全局": 0, "玩家": 0, "子程序": 0}

    span = _block_span(lines, "变量")
    if span:
        head, tail, body = span
        groups = dict(_split_by_group(body))
        real = {g: names for g, names in groups.items()}
        taken = set()
        for names in real.values():
            taken.update(names)
        blocks = ["变量", "{"]
        for gname in ("全局", "玩家"):
            names = list(real.get(gname, []))[:128]
            need = 128 - len(names)
            if need > 0:
                names += _name_pool(rng, need, taken)
            blocks.append("\t%s:" % gname)
            for i, name in enumerate(names):
                blocks.append("\t\t%d: %s" % (i, name))
            stats[gname] = len(names)
        blocks.append("}")
        lines[head:tail + 1] = blocks

    span = _block_span(lines, "子程序")
    if span:
        head, tail, body = span
        real = _decl_names(body)[:128]
        need = 128 - len(real)
        names = list(real)
        if need > 0:
            names += _name_pool(rng, need, set(real))
        blocks = ["子程序", "{"]
        for i, name in enumerate(names):
            blocks.append("\t%d: %s" % (i, name))
        blocks.append("}")
        lines[head:tail + 1] = blocks
        stats["子程序"] = len(names)

    return "\n".join(lines), stats


# ---------- 假规则填充 ----------

WARNING_RULE = """规则("代码受到保护，请尊重作者劳动成果。守望先锋® 工坊语言支持")
{
	事件
	{
		持续 - 全局;
	}

	动作
	{
		禁用查看器录制;
	}
}"""


def _tamper_rule(rng):
    frac = rng.randint(1, 4)
    return ("规则(\"\")\n{\n\t事件\n\t{\n\t\t持续 - 全局;\n\t}\n\n"
            "\t条件\n\t{\n\t\t0.000%d == 假;\n\t}\n\n"
            "\t动作\n\t{\n\t\tWhile(真);\n\t\tEnd;\n\t}\n}" % frac)


def fill_rules(text, budget, seed=20261031):
    """按元素预算填假规则：1 条查看器警告 + 最多 5 条篡改保护 + 1 元素空规则铺满。

    budget 是「原生代码的总元素数量」（游戏里看诊断结果），没给就用估算值。
    """
    rng = random.Random(seed)
    parts = re.split(r"(?m)^(?=规则\()", text)
    head, rules = parts[0], [p for p in parts[1:]]
    if not rules:
        return text, {"警告": 0, "篡改": 0, "空规则": 0, "剩余预算": budget}

    added = {"警告": 0, "篡改": 0, "空规则": 0}
    if budget >= 2:
        budget -= 2
        rules.insert(0, WARNING_RULE + "\n\n")
        added["警告"] = 1

    for _ in range(5):
        if budget < 5:
            break
        budget -= 5
        rules.insert(rng.randint(0, len(rules)), _tamper_rule(rng) + "\n\n")
        added["篡改"] += 1

    per_rule = budget // max(len(rules), 1)
    if per_rule > 0:
        out = []
        for rule in rules:
            out.append(rule)
            for _ in range(per_rule):
                if len(out) + len(rules) >= MAX_RULES:
                    break
                out.append('规则("")\n{\n\t事件\n\t{\n\t\t持续 - 全局;\n\t}\n}\n\n')
                budget -= 1
                added["空规则"] += 1
            if len(out) + len(rules) >= MAX_RULES:
                break
        rules = out

    added["剩余预算"] = budget
    return head + "".join(rules), added


# ---------- 字符串混淆 ----------

SKIP_ON = "/* @SKIP_OBFUSCATE_STRING */"
SKIP_OFF = "/* @SKIP_OBFUSCATE_STRING_END */"


def _shift(s):
    """字符串里每个普通字符挪到私用区（+0xE0000），控制字符和转义原样留着。"""
    out = []
    for ch in s:
        cp = ord(ch)
        if cp < 0x20 or 0x7F <= cp <= 0x9F or cp == 0xAD:
            out.append(ch)
        else:
            out.append(chr(cp + PRIVATE_USE_SHIFT))
    return "".join(out)


def obfuscate_strings(text, seed=20261031):
    """把 自定义字符串(...) / 字符串(...) 的内容换成不可读私用区字符。

    注意：换完之后字符串比较仍然成立（同一个字符串换两次结果一样），
    但和「玩家名」这类外部文本比较就对不上——插件自己也这么警告。
    `/* @SKIP_OBFUSCATE_STRING */` 到 `/* @SKIP_OBFUSCATE_STRING_END */` 之间的不动。
    """
    spans = []
    pos = 0
    while True:
        a = text.find(SKIP_ON, pos)
        if a == -1:
            break
        b = text.find(SKIP_OFF, a)
        if b == -1:
            spans.append((a, len(text)))
            break
        spans.append((a, b))
        pos = b + len(SKIP_OFF)

    def _in_skip(p):
        return any(a <= p < b for a, b in spans)

    out, i, n, hits = [], 0, len(text), 0
    while i < n:
        for fn in ("自定义字符串(", "字符串("):
            if text.startswith(fn, i):
                j = i + len(fn)
                while j < n and text[j] in " \t":
                    j += 1
                if j < n and text[j] == '"':
                    k = j + 1
                    while k < n:
                        if text[k] == "\\":
                            k += 2
                            continue
                        if text[k] == '"':
                            break
                        k += 1
                    content = text[j + 1:k]
                    if _in_skip(i):
                        out.append(text[i:k + 1])
                    else:
                        out.append(text[i:j + 1] + _shift(content) + '"')
                        hits += 1
                    i = k + 1
                    break
        else:
            out.append(text[i])
            i += 1
            continue
        continue

    result = "".join(out)
    if spans:
        result = result.replace(SKIP_ON, "").replace(SKIP_OFF, "")
    return result, hits
