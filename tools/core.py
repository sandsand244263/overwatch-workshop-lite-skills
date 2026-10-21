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

# 实测验证过的「只能写 全部禁用，不能写 无」位置（来源：插件修复清单 + 用户实测导入）
VERIFIED_NO_SLOTS = {
    "创建地图文本": {"slots": {-2}},
    "创建HUD文本": {"slots": {-2}},
    "创建进度条地图文本": {"slots": {-2}},
    "创建进度条HUD文本": {"slots": {-2}},
    "追踪全局变量频率": {"slots": {-1}},
    "追踪玩家变量频率": {"slots": {-1}},
    "持续追踪全局变量": {"slots": {-1}},
    "持续追踪玩家变量": {"slots": {-1}},
    "开始治疗调整": {"slots": {-1}},
    "设置不可见": {"slots": {-1}},
}

# 模式 > 综合 块里实测能导入的键（其余报「综合 { 之后应有一个游戏模式设置」）。
# 数据里的设置分类（技能/武器/决斗先锋…）跟 .ow 的块结构不是一回事，推不出来，只能靠实测。
GENERAL_KEYS = ("允许切换英雄", "复生时间", "急救包刷新", "游戏模式开始", "英雄限制",
                "重装职责被动生命值加成", "随机英雄复生")


def check_mode_general(text, problems):
    """检查 `模式 { ... 综合 { ... } }` 里的键是否在实测白名单内。"""
    idx = text.find("模式")
    while idx != -1:
        brace = text.find("{", idx)
        if brace == -1:
            break
        depth, j = 1, brace + 1
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        block = text[brace:j]
        start = block.find("综合")
        while start != -1:
            ob = block.find("{", start)
            depth2, k = 1, ob + 1
            while k < len(block) and depth2:
                if block[k] == "{":
                    depth2 += 1
                elif block[k] == "}":
                    depth2 -= 1
                k += 1
            inner = block[ob:k]
            for m in re.finditer(r"^\s*([^\s:]+)\s*:", inner, re.M):
                key = m.group(1)
                if key not in GENERAL_KEYS:
                    line = text.count(chr(10), 0, brace) + 1
                    problems.append((line, "warning",
                                     "综合 块里的键 %s 未在实测样本中出现；实测有效：%s"
                                     % (key, " / ".join(GENERAL_KEYS))))
            start = block.find("综合", k)
        idx = text.find("模式", j)



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
    """返回 (sigs, labels, options)。

    sigs[name]    = 参数个数
    labels[name]  = ["参数名:类型", ...]
    options[name][idx] = {"选项1", "选项2", ...}   # 只有下拉参数才有
    """
    sigs, labels, options = {}, {}, {}
    if not os.path.isfile(path):
        return sigs, labels, options
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("<!--") or "(" not in line or not line.endswith(")"):
                continue
            name, rest = line.split("(", 1)
            name = name.strip()
            if not name or " " in name:
                continue
            inner = rest[:-1].strip()
            args = split_args(inner) if inner else []
            sigs[name] = len(args)
            labels[name] = [re.sub(r"\[[^\]]*\]$", "", a).strip() for a in args]
            per_param = {}
            for idx, arg in enumerate(args):
                m = re.search(r"\[([^\]]*)\]\s*$", arg)
                if m:
                    opts = {x for x in m.group(1).split("|") if x and not x.startswith("…共")}
                    if opts:
                        per_param[idx] = opts
            if per_param:
                options[name] = per_param
    return sigs, labels, options


def load_full_options(path):
    """从 data/dropdowns.tsv 读完整选项 {函数: {参数序号: {选项…}}}。"""
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("	")
            if len(parts) < 4 or parts[0] == "func":
                continue
            func, idx, _pname, opts = parts[0], parts[1], parts[2], parts[3]
            if opts == "UNKNOWN":
                continue
            try:
                i = int(idx)
            except ValueError:
                continue
            out.setdefault(func, {})[i] = {x for x in opts.split("|") if x}
    return out


def parse_build_info(path):
    """从 .build.info 读出形如 2.25.0.1.154504N 的版本串；读不到返回 None。"""
    if not os.path.isfile(path):
        return None
    raw = open(path, "rb").read()
    cands = re.findall(rb"(\d+(?:\.\d+){2,5}N)", raw)
    return max((c.decode() for c in cands), key=len) if cands else None


def load_required_args(path):
    """{函数: 最少参数}；只用于 warning，避免误报。"""
    out = {}
    if not os.path.isfile(path):
        return out
    for line in open(path, encoding="utf-8"):
        parts = line.rstrip(chr(10)).split(chr(9))
        if len(parts) < 2 or parts[0] == "func":
            continue
        try:
            out[parts[0]] = int(parts[1])
        except ValueError:
            continue
    return out


def load_settings_schema(path):
    """返回 {设置键: (类型, 允许值集合或 None)}，来源 data/settings.tsv。"""
    schema = {}
    if not os.path.isfile(path):
        return schema
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("schema	") or not line.strip():
                continue
            parts = line.rstrip("\n").split("	")
            if len(parts) < 4:
                continue
            _schema_name, key, kind, allowed = parts[0], parts[1], parts[2], parts[3]

            if kind == "BOOL":
                schema[key] = ("BOOL", {"开启", "关闭"})
            elif "ENUM" in kind:
                schema[key] = ("ENUM", {x.strip() for x in allowed.split("|") if x.strip()})
            else:
                schema[key] = (kind, None)
    return schema


FOR_PREFIX = re.compile(r"For\s+$")


def scan_calls(text, sigs, labels, problems, options=None):
    options = options or {}
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
                arg_list = split_args(inner) if inner.strip() else []

                for slot in (VERIFIED_NO_SLOTS.get(name) or {}).get("slots", ()):
                    if len(arg_list) >= abs(slot) and arg_list[slot].strip() == "无":
                        problems.append((line, "error",
                                         "%s 这个位置要写 全部禁用，写 无 导入会失败" % name))
                if name in ("全局变量", "玩家变量") and "For" in text[max(0, start - 30):start]:
                    continue
                if sigs and name not in sigs:
                    problems.append((line, "error", "未知函数名：%s（签名表里没有）" % name))
                elif sigs:
                    total = sigs[name]
                    got = len(arg_list)
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


def load_event_params(path):
    """事件名 -> 需要的参数个数（data/event-params.tsv）。"""
    import csv as _csv
    out = {}
    if not os.path.isfile(path):
        return out
    for r in _csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
        try:
            out[r["event"]] = int(r["param_count"])
        except (KeyError, ValueError):
            continue
    return out


def load_bare_ok(path):
    """可以裸写的记号（0 参数函数、下拉/枚举选项、常量）。"""
    import csv as _csv
    out = set()
    if os.path.isfile(path):
        for r in _csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
            if r.get("token"):
                out.add(r["token"].strip())
    return out


def _top_level_args(s):
    """按深度 0 的逗号切分参数。"""
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    if cur.strip():
        out.append(cur)
    return out


def load_event_param_words(path):
    """事件参数的已知取值（data/event-param-words.tsv）。"""
    import csv as _csv
    out = set()
    if os.path.isfile(path):
        for r in _csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
            if r.get("word"):
                out.add(r["word"].strip())
    return out


def load_element_kinds(path):
    """元素名 -> 动作 / 值 / 事件 / 扩展。"""
    import csv as _csv
    out = {}
    if os.path.isfile(path):
        for r in _csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
            if r.get("name"):
                out[r["name"]] = r["kind"]
    return out


def check_element_kind(text, kinds, problems):
    """动作块里不能放值函数；条件块里不能放动作。

    典型错误：把「比赛结束()」当动作写（它是值，表示"比赛是否已结束"）。
    游戏报「"比赛结束()"之后应有一个赋值运算符」。
    """
    if not kinds:
        return
    lines = text.split("\n")
    block = None
    depth = 0
    for idx, raw in enumerate(lines):
        s = raw.strip()
        if s in ("动作", "条件", "事件"):
            block = s
            depth = 0
            continue
        if s.startswith("{"):
            depth += 1
            continue
        if s.startswith("}"):
            depth -= 1
            if depth <= 0:
                block = None
            continue
        if not s or s.startswith("//"):
            continue
        if block == "动作" and depth == 1 and s.endswith(";"):
            m = re.match(r"^([\u4e00-\u9fa5A-Za-z_][\w\u4e00-\u9fa5]*)\s*\(", s)
            if m and kinds.get(m.group(1)) == "值":
                problems.append((idx + 1, "error",
                                 "「%s」是值函数（返回一个值），不能单独当动作写；"
                                 "要判断它请写进条件/If" % m.group(1)))
        elif block == "条件" and depth == 1:
            for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z_][\w\u4e00-\u9fa5]*)\s*\(", s):
                if kinds.get(m.group(1)) == "动作":
                    problems.append((idx + 1, "error",
                                     "「%s」是动作，不能写在条件里" % m.group(1)))
                    break


def check_string_interp(text, problems):
    """自定义字符串 / 字符串 的 {N} 数量必须与实参数量匹配。"""
    for m in re.finditer(r"(自定义字符串|字符串)\(([^;\n]*)", text):
        fn, body = m.group(1), m.group(2)
        args = _top_level_args(body)
        if not args:
            continue
        tmpl = args[0]
        idx = [int(x) for x in re.findall(r"\{(\d)\}", tmpl)]
        if not idx:
            continue
        need = max(idx) + 1
        have = len(args) - 1
        if have < need:
            line = text.count("\n", 0, m.start()) + 1
            problems.append((line, "warning",
                             "%s 的模板里有 {%d}，但只给了 %d 个值（需要 %d 个）" % (fn, max(idx), have, need)))


def check_duplicate_rule_names(text, problems):
    """同名规则会互相覆盖/难以排查。"""
    seen = {}
    for m in re.finditer(r'规则\(\s*"([^"]+)"\s*\)', text):
        name = m.group(1)
        line = text.count("\n", 0, m.start()) + 1
        if name in seen:
            problems.append((line, "warning", "规则名「%s」重复（首次出现在第 %d 行）" % (name, seen[name])))
        else:
            seen[name] = line


def check_bare_functions(text, sigs, problems, bare_ok=None):
    """函数名写成裸名字（没有括号）。

    典型：大字体信息(所有玩家, …) 应为 大字体信息(所有玩家(所有队伍), …)。
    游戏报「"所有玩家"之后应有"("」。
    """
    if not sigs:
        return
    def _n(params):
        if isinstance(params, int):
            return params
        try:
            return len(params)
        except TypeError:
            return 0
    needs_arg = {name for name, params in sigs.items() if _n(params) >= 1}
    allowed = (bare_ok or set()) | {name for name, params in sigs.items() if _n(params) == 0}
    for m in re.finditer(r"(?<![\w.\u4e00-\u9fa5])([\u4e00-\u9fa5A-Za-z_][\w\u4e00-\u9fa5]*)(?!\s*\()", text):
        name = m.group(1)
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.start())
        line_text = text[line_start: line_end if line_end >= 0 else len(text)]
        # 只检查处在表达式里的行（块标题行没有括号/逗号，跳过）
        if "(" not in line_text and "," not in line_text:
            continue
        if name in needs_arg and name not in allowed:
            line = text.count("\n", 0, m.start()) + 1
            problems.append((line, "error",
                             "「%s」是函数，必须写成 %s(...)；只写名字游戏会报「之后应有 (」" % (name, name)))


def check_event_params(text, event_params, problems, event_param_words=None):
    """事件块里的参数个数校验。

    .ow 里的写法是「事件名;」后面跟 N 行裸值（队伍 / 玩家筛选），
    例如 玩家造成最后一击 要跟 双方; 全部;。少写会报「之后应有一个队伍」。
    """
    if not event_params:
        return
    lines = text.split("\n")
    in_events = False
    depth = 0
    i = 0
    while i < len(lines):
        raw = lines[i].strip()
        if raw == "事件":
            in_events = True
            depth = 0
            i += 1
            continue
        if not in_events:
            i += 1
            continue
        if raw.startswith("{"):
            depth += 1
        elif raw.startswith("}"):
            depth -= 1
            if depth <= 0:
                in_events = False
        elif depth == 1 and raw.endswith(";") and "(" not in raw:
            name = raw[:-1].strip()
            need = event_params.get(name)
            if need is not None:
                got = 0
                j = i + 1
                while j < len(lines):
                    nxt = lines[j].strip()
                    if not nxt or nxt.startswith("}") or nxt.startswith("{") or "(" in nxt:
                        break
                    if nxt.endswith(";"):
                        got += 1
                        j += 1
                        continue
                    break
                # 取值合法性（只警告，因为合法值表可能不全）
                j2 = i + 1
                seen_vals = []
                while j2 < len(lines) and len(seen_vals) < need:
                    v = lines[j2].strip()
                    if not v or v.startswith("}") or "(" in v:
                        break
                    if v.endswith(";"):
                        seen_vals.append(v[:-1].strip())
                        j2 += 1
                        continue
                    break
                if event_param_words:
                    for v in seen_vals:
                        if v not in event_param_words:
                            problems.append((j2, "warning",
                                             "事件参数「%s」不在已知取值里（已知：%s）"
                                             % (v, " / ".join(sorted(event_param_words)))))
                if got < need:
                    problems.append((i + 1, "error",
                                     "事件「%s」需要 %d 个参数（队伍 / 玩家筛选），这里只有 %d 个"
                                     % (name, need, got)))
        i += 1


def check_duplicate_blocks(text, problems):
    """顶层的 设置 / 变量 / 子程序 块只能各出现一次，重复会报「未知的变量」这类错。"""
    for kw in ("设置", "变量", "子程序"):
        hits = [m.start() for m in re.finditer(r"^%s\s*$" % kw, text, re.M)]
        if len(hits) > 1:
            lines = [text.count(chr(10), 0, h) + 1 for h in hits[1:]]
            problems.append((lines[0], "error",
                             "顶层 `%s` 块出现了 %d 次，只能有一个（多余的从第 %s 行开始）"
                             % (kw, len(hits), "、".join(str(x) for x in lines))))


MIN_ARGS = {"修改全局变量": 3, "修改玩家变量": 4, "设置全局变量": 2, "设置玩家变量": 3}


def check_arg_count(text, problems):
    """少数函数的参数不可省略，少给会报「之后应有一个选项」。"""
    for name, need in MIN_ARGS.items():
        for m in re.finditer(re.escape(name) + r"\(", text):
            depth, j = 0, m.end() - 1
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            args = [a for a in re.split(r"[，,]", text[m.end():j]) if a.strip()]
            if len(args) < need:
                line = text.count(chr(10), 0, m.start()) + 1
                problems.append((line, "error",
                                 "%s 至少要 %d 个参数，这里只有 %d 个" % (name, need, len(args))))


def check_var_refs(text, problems):
    """全局.X / 事件玩家.X 引用的变量必须在变量块对应段落声明过（容忍空行、跳号）。"""
    vi = text.find("变量")
    if vi < 0:
        return
    body = text[vi:]
    gi = body.find("全局:")
    pi = body.find("玩家:")
    gl, pl = set(), set()
    if gi >= 0:
        seg = body[gi + 3: pi if pi > gi else len(body)]
        gl = set(re.findall(r"\d+\s*:\s*(\w+)", seg))
    if pi >= 0:
        seg = body[pi + 3:]
        pl = set(re.findall(r"\d+\s*:\s*(\w+)", seg))
    if not gl and not pl:
        return
    for m in re.finditer(r"全局\.(\w+)", text):
        if m.group(1) not in gl:
            line = text.count(chr(10), 0, m.start()) + 1
            problems.append((line, "error", "全局.%s 没有在变量块里声明" % m.group(1)))
    for m in re.finditer(r"(?:事件玩家|本地玩家)\.(\w+)", text):
        if m.group(1) not in pl:
            line = text.count(chr(10), 0, m.start()) + 1
            problems.append((line, "error", "%s.%s 没有声明为玩家变量" % (m.group(0).split(".")[0], m.group(1))))


def check_unassigned(text, problems):
    """声明了但从未赋值的变量（会静默保持 0）。warning。"""
    names = set(re.findall(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$", text, re.M))
    if not names:
        return
    written = set()
    for pat in (r"(?:设置|修改)全局变量\(\s*(\w+)", r"(?:设置|修改)玩家变量\([^,，]+[,，]\s*(\w+)"):
        written |= set(re.findall(pat, text))
    used = set(re.findall(r"(?:全局|事件玩家|本地玩家)\.(\w+)", text))
    for n in sorted((used & names) - written):
        problems.append((0, "warning", "变量 %s 声明了但从未赋值，会一直是 0" % n))


def check_lazy_display(text, problems):
    """大字体信息/记入查看器 里引用的变量若在同一规则内随后被改写，提示用快照。warning。"""
    for m in re.finditer(r'大字体信息\([^\n]*', text):
        seg = text[m.start(): m.start() + 400]
        for var in set(re.findall(r"全局\.(\w+)", seg[:200])):
            if re.search(r"(?:设置|修改)全局变量\(\s*%s" % re.escape(var), seg[200:400]):
                line = text.count(chr(10), 0, m.start()) + 1
                problems.append((line, "warning",
                                 "大字体信息 里的 全局.%s 是延迟取值，同一规则内随后被改写——"
                                 "先用临时变量快照再显示" % var))


def check_types(text, problems):
    """按参数类型校验（类型来自 data/signatures.md）。

    覆盖两类高频错：For 控制变量必须先声明；变量当值要写 全局.X。
    """
    declared = set(re.findall(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$", text, re.M))
    if not declared:
        return
    # For 全局变量 / For 玩家变量：第一个参数必须是已声明的变量
    for m in re.finditer(r"For\s+(全局变量|玩家变量)\(\s*([A-Za-z_]\w*)", text):
        if m.group(2) not in declared:
            line = text.count(chr(10), 0, m.start()) + 1
            problems.append((line, "error",
                             "For 循环的控制变量 %s 没有在变量块里声明" % m.group(2)))
    # 变量当值：出现在值位置（逗号后）的裸变量名
    for m in re.finditer(r"[，,]\s*([A-Za-z_]\w*)\s*(?=[，,)])", text):
        name = m.group(1)
        if name not in declared:
            continue
        before = text[max(0, m.start() - 40):m.start()]
        if re.search(r"(设置|修改)(全局|玩家)变量\([^,，]*$", before):
            continue                      # 变量目标位，合法
        line = text.count(chr(10), 0, m.start()) + 1
        problems.append((line, "error",
                         "变量 %s 当值用要写 全局.%s 或 事件玩家.%s" % (name, name, name)))


def check_misc(text, problems):
    """吸收自 workshop.codes linter 的其余规则。"""
    # 1) 块结尾 } 后多余分号
    for m in re.finditer(r"\}\s*;", text):
        line = text.count(chr(10), 0, m.start()) + 1
        problems.append((line, "error", "块结尾的 } 后面不能加分号"))

    # 2) 子程序必须已声明
    declared = set(re.findall(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$", text, re.M))
    for m in re.finditer(r"调用子程序\(\s*([A-Za-z_]\w*)\s*\)", text):
        if m.group(1) not in declared:
            line = text.count(chr(10), 0, m.start()) + 1
            problems.append((line, "error", "调用子程序(%s) 找不到对应的子程序声明" % m.group(1)))

    # 3) 地图 id 不能是 0（会导致导入失败）
    for m in re.finditer(r"^\s*([^\s:][^\n:]*?)\s+0\s*$", text, re.M):
        line = text.count(chr(10), 0, m.start()) + 1
        problems.append((line, "error", "地图 id 不能是 0：%s" % m.group(1).strip()))

    # 4) 变量名只差大小写
    names = re.findall(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$", text, re.M)
    groups = {}
    for n in names:
        groups.setdefault(n.lower(), set()).add(n)
    for group in groups.values():
        if len(group) > 1:
            problems.append((0, "warning", "变量名只差大小写，工坊会当成同一个：%s"
                             % " / ".join(sorted(group))))


def lint(path, sigs, labels, settings=None, options=None, required=None, event_params=None, bare_ok=None, kinds=None, event_param_words=None):
    problems = []
    settings = settings or {}
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    text = raw.replace("\r\n", "\n")
    lines = text.split("\n")

    stack, pending = [], None
    paren_depth = 0
    var_section = None
    declared = {"全局": set(), "玩家": set()}
    subroutines = set()
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
            if re.match(r"^\d+\s*:\s*([A-Za-z_]\w*)", stripped):
                sidx = int(stripped.split(":", 1)[0])
                if sidx > 127:
                    problems.append((ln, "error", "子程序索引最大 127，这里是 %d" % sidx))
                subroutines.add(stripped.split(":", 1)[1].strip())
            if not re.match(r"^\d+\s*:", stripped):
                problems.append((ln, "error", "子程序块里只能写 `索引: 子程序名`：%s" % stripped))
            else:
                name = stripped.split(":", 1)[1].strip()
                if not IDENT.match(name):
                    problems.append((ln, "error", "子程序名只能用英文字母/数字/下划线：%s" % name))
            continue

        if block == "变量":
            if re.match(r"^\d+\s*:", stripped):
                idx = int(stripped.split(":", 1)[0])
                if idx > 127:
                    problems.append((ln, "error", "变量索引最大 127，这里是 %d" % idx))
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
            m = re.match(r"^([^\s:]+)\s*:\s*(.+)$", stripped)
            if m:
                key, value = m.group(1), m.group(2).strip()
                info = settings.get(key)
                if info is None:
                    pass   # 大厅项/英雄专属项来自另外的数据源，表里没有不代表错
                elif info[0] == "BOOL" and value not in info[1]:
                    problems.append((ln, "warning",
                                     "%s 是布尔项，只能写 开启 / 关闭；导出器的「%s」导入会报错"
                                     % (key, value)))
                elif info[0] == "ENUM" and info[1] and value not in info[1]:
                    problems.append((ln, "error",
                                     "%s 的值「%s」不是合法选项，可选：%s"
                                     % (key, value, " / ".join(sorted(info[1])))))
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
        first = chunk.strip().split(";")[0].strip()
        if count == 2 and first == "子程序":
            continue          # 子程序事件固定两行：子程序; 名字;
        if count not in (0, 1, 3):
            problems.append((0, "error",
                             "事件块只能是 1 行（全局事件）或 3 行（事件; 队伍; 英雄;），这里是 %d 行" % count))

    masked = strip_noise(text)
    if len(subroutines) > 128:
        problems.append((0, "error", "子程序最多 128 个，现在 %d 个" % len(subroutines)))
    for section, names in declared.items():
        if len(names) > 128:
            problems.append((0, "error", "%s变量最多 128 个，现在 %d 个" % (section, len(names))))

    for m in VAR_REF.finditer(masked):
        owner, name = m.group(1), m.group(2)
        section = "全局" if owner == "全局" else "玩家"
        if name not in declared[section]:
            problems.append((0, "warning", "变量 %s.%s 未声明（应在 `%s:` 段里）" % (owner, name, section)))

    scan_calls(masked, sigs, labels, problems, options)
    check_event_params(masked, event_params or {}, problems, event_param_words)
    check_bare_functions(masked, sigs, problems, bare_ok)
    check_element_kind(masked, kinds or {}, problems)
    check_string_interp(text, problems)
    check_duplicate_rule_names(text, problems)
    check_arg_count(masked, problems)
    check_types(masked, problems)
    check_unassigned(masked, problems)
    check_lazy_display(masked, problems)
    check_var_refs(masked, problems)
    check_misc(masked, problems)
    check_duplicate_blocks(masked, problems)

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
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "signatures.md"))
    ap.add_argument("--settings", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "settings.tsv"))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    sigs, labels, options = load_signatures(args.signatures)
    settings = load_settings_schema(args.settings)
    if not sigs and not args.quiet:
        print("[提示] 没读到签名表 %s，只做结构检查" % args.signatures)

    failed = 0
    for path in args.files:
        if not os.path.isfile(path):
            print("[错误] 找不到 %s" % path)
            failed += 1
            continue
        problems = lint(path, sigs, labels, settings, options)
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
