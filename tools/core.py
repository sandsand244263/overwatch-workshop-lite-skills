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

三层检查的分工（2026-10 升级）：
  格式层：上面 1-13，只跟语法有关，不查数据表。
  数据 ID 层：地图 / 英雄 / 技能 / 按钮 / 设置键 / 事件名 必须存在于 data/ 的当前版本表
              （check_map_names / check_hero_names / check_ability_names /
               check_button_names / check_setting_keys / check_event_names），
              文案统一为「X「Y」不在当前版本数据表里（可能已改名或移除）」。
  类型层：参数槽类型硬冲突（玩家槽塞数字、数值槽塞玩家表达式）、
          变量与子程序完整性、单条规则 98KB 上限、元素数上限。
行号：跨行语句会合并到起始行，报错统一按 SegMap 换算回原文行号。

退出码：0 无问题，1 有错误。
"""
import argparse
import csv
import os
import re
import sys

PLACEHOLDER = re.compile(r"\{(\d)\}")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COMPARISON = re.compile(r"==|!=|>=|<=|>|<")
# 玩家变量赋值：所有玩家(所有队伍).X = … / 事件玩家.X = …
ASSIGNMENT = re.compile(r"^.+?\.[A-Za-z_]\w*(?:\[[^\]]*\])?\s*=(?!=)")
VAR_REF = re.compile(r"(全局|本地玩家|事件玩家|攻击方|被攻击方|主机玩家|本市玩家)\.([A-Za-z_][A-Za-z0-9_]*)")

BLOCK_KEYWORDS = ("设置", "主程序", "大厅", "模式", "英雄", "地图工坊", "扩展",
                  "变量", "子程序", "规则", "事件", "条件", "动作", "禁用地图", "启用地图")
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

# 语料实测：写在任意模式块下都能导入的「通用模式键」（不受层检查约束）。
# 依据：塔萨达练枪房 / 暴打大锤3 等真实模式在 占领要点、团队死斗、攻防作战… 下都写了这些键且能导入。
COMMON_MODE_KEYS = {"复生时间", "英雄限制"}

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
    # 先去掉同行内的 /* ... */ 块注释（插件会往动作里插 @SKIP_OBFUSCATE_STRING 标记）
    line = re.sub(r"/\*.*?\*/", "", line)
    if "/*" in line and "*/" not in line:
        line = line.split("/*")[0]
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
            if not name:
                continue
            # 名字里允许有空格：`Else If`、`For 全局变量`、`设置启用技能 1`、`正在使用技能 1`
            # 这些是**多词元素名**，不是「名字 + 参数」。以前这里 skip 掉，导致
            # 7 个元素的参数个数 / 类型检查全部失效（scan_calls 见 _multiword_names）。
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

# 可变参数：签名表里只能写出前几个占位，实际能一直往里塞
VARIADIC = {"数组", "自定义字符串", "字符串"}

# 多词元素名（名字里带空格）——参数个数必须**正好**对上签名。
# 为什么单列：scan_calls 的取词器按「连续标识符字符」读名字，空格天然是分隔符，
# 所以 `设置启用技能 1(事件玩家)` 以前根本不会进参数检查（`load_signatures` 里也
# 直接 skip 了这 7 个名字）。修好取词后，这 7 个元素的参数个数是固定的、没有一个
# 可选尾参，少写/多写都是引擎不接受，故按「正好」判，而不是只判上限。
# 实测：9 份真实语料里这 7 个元素共 1738 次调用，参数个数 100% 与签名一致
# （Else If 1×1208 / For 全局变量 4×159 / For 玩家变量 5×111 /
#  设置启用技能1 2×4 / 设置启用技能2 2×6 / 正在使用技能1 1×160 / 正在使用技能2 1×90）。
EXACT_ARITY = {
    "Else If": 1,
    "For 全局变量": 4,
    "For 玩家变量": 5,
    "设置启用技能 1": 2,
    "设置启用技能 2": 2,
    "正在使用技能 1": 1,
    "正在使用技能 2": 1,
}


def _multiword_names(sigs):
    """签名表里名字带空格的元素，按长度倒序（长名先匹配）。"""
    return sorted((k for k in sigs if " " in k), key=len, reverse=True)


def _is_word_char(c):
    return c.isalnum() or c == "_" or "\u4e00" <= c <= "\u9fff"


def scan_calls(text, sigs, labels, problems, options=None, dropdowns=None, legal_words=None):
    options = options or {}
    multiword = _multiword_names(sigs)
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
            # 多词元素名：`For 玩家变量(...)`、`Else If(...)`、`正在使用技能 1(...)`。
            # 只在「名字 + 空格 + 词」正好接上签名里的全名、且后面紧跟 `(` 时才认，
            # 不动 `For 全局变量` 以外那些普通写法。
            if multiword:
                for cand in multiword:
                    if not cand.startswith(name) or len(cand) <= len(name):
                        continue
                    if not text.startswith(cand, start):
                        continue
                    after = start + len(cand)
                    if after < n and _is_word_char(text[after]):
                        continue
                    k = after
                    while k < n and text[k] in " \t":
                        k += 1
                    if k < n and text[k] == "(":
                        name, i = cand, k
                        break
            if i < n and text[i] == "(" and name not in BLOCK_KEYWORDS and \
                    (name not in CONTROL or name in EXACT_ARITY):
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
                arg_pos = split_args_pos(inner, i + 1) if inner.strip() else []
                arg_list = [a.strip() for a, _p in arg_pos]

                # 数据驱动：这个槽的选项里只要有「全部禁用」，「无」就是导出噪声 → 必改
                _dd_slots = {}
                for (_elem, _idx), _opts in (dropdowns or {}).items():
                    if _elem == name:
                        _dd_slots[_idx] = _opts
                for _slot, _opts in _dd_slots.items():
                    if len(arg_list) > _slot and arg_list[_slot] == "无" and "全部禁用" in _opts:
                        if (name, "无") in (legal_words or ()):
                            continue      # data/limits-mutex.tsv「合法写法」：这个槽写「无」是对的
                        problems.append((line, "error",
                                         "%s 第 %d 个参数要选项，导出把「全部禁用」写成了「无」；"
                                         "改成 全部禁用（ws.py fix 文件 --fix-bools 可自动改）"
                                         % (name, _slot + 1)))

                for slot in (VERIFIED_NO_SLOTS.get(name) or {}).get("slots", ()):
                    if len(arg_list) >= abs(slot) and arg_list[slot] == "无":
                        # 导出文本会把这个位置写成 无，编辑器里是 全部禁用
                        problems.append((line, "warning",
                                         "%s 这个位置导出后写作「无」，编辑器里是「全部禁用」；"
                                         "手写或改导出文件时改成 全部禁用" % name))
                if name in ("全局变量", "玩家变量") and "For" in text[max(0, start - 30):start]:
                    continue
                if sigs and name not in sigs:
                    problems.append((line, "error", "未知函数名：%s（签名表里没有）" % name))
                elif sigs:
                    total = sigs[name]
                    got = len(arg_list)
                    if total == 0 and got:
                        problems.append((line, "error", "%s 不接受参数，实际给了 %d 个" % (name, got)))
                    elif got > total and name not in VARIADIC:
                        problems.append((line, "error", "%s 参数过多：最多 %d 个，实际 %d 个"
                                         % (name, total, got)))
                    elif got == 0 and total > 0:
                        problems.append((line, "error", "%s 至少需要 1 个参数" % name))
                    elif got < total and name in EXACT_ARITY:
                        # 多词元素名（`设置启用技能 1`、`For 全局变量`…）没有可选尾参，
                        # 少写就是缺值，游戏会报「之后应有一个值」。修好取词前这一支不生效。
                        _need = "、".join(a.replace(":", "：") for a in (labels.get(name) or []))
                        problems.append((line, "error",
                                         "%s 参数不够：签名要 %d 个（%s），实际写了 %d 个"
                                         % (name, total, _need or "见签名", got)))
                    params = labels.get(name) or []
                    if params and params[0].endswith(":玩家") and inner.strip():
                        first = arg_list[0]
                        if first in ("真", "假", "True", "False"):
                            problems.append((line, "error",
                                             "%s 第 1 个参数是「可见」（玩家或玩家列表），不能填 %s"
                                             % (name, first)))
                    for idx, label in enumerate(params):
                        if idx >= len(arg_pos):
                            break
                        _check_arg_type(name, idx, label, arg_pos[idx][0],
                                        arg_pos[idx][1], problems, text)

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



def _opt_float(s):
    """空串 / None -> None（表示「这一侧边界没有证据」），否则 float。"""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load_setting_ranges(path):
    """设置键 -> (min, max, level)。同名键以后读到的为准。

    两张表合并：`setting-ranges.tsv`（游戏数据里的 min/max，error 级）+
    `setting-ranges-lobby.tsv`（大厅页只能在界面里看滑杆，warning 级）。
    边界可以只有一侧：没证据的那一侧留空，宁可只查单边，也不凭空编一个
    上下限去误报（见 DECISIONS D-042）。
    """
    import csv as _csv
    out = {}
    for fp in (path, os.path.join(os.path.dirname(path), "setting-ranges-lobby.tsv")):
        if not os.path.isfile(fp):
            continue
        for r in _csv.DictReader(open(fp, encoding="utf-8"), delimiter="\t"):
            key = (r.get("key") or "").strip()
            if not key:
                continue
            lo, hi = _opt_float(r.get("min")), _opt_float(r.get("max"))
            if lo is None and hi is None:
                continue
            level = (r.get("level") or "error").strip() or "error"
            out[key] = (lo, hi, level)
    return out


def load_setting_values(path):
    """{键: {"type","allowed","schemas"}} —— 来自 `data/setting-values.tsv`。

    只收「值是一组词」的键（当前 13 个 Enum 键）。数值范围不在这张表，走
    `setting-ranges.tsv`；布尔词表是类型级规则，走 `setting-aliases.tsv`。
    """
    out = {}
    if not path or not os.path.isfile(path):
        return out
    import csv as _csv
    for r in _csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
        key = (r.get("key") or "").strip()
        if not key:
            continue
        allowed = {v.strip() for v in (r.get("allowed") or "").split("|") if v.strip()}
        if not allowed:
            continue
        out[key] = {"type": (r.get("type") or "").strip(),
                    "allowed": allowed,
                    "schemas": (r.get("schemas") or "").strip()}
    return out


ILLEGAL_BOOL_WORDS = {"禁用": "关闭", "启用": "开启", "是": "开启", "否": "关闭"}


def load_setting_aliases(path):
    """(改写表, 例外集) —— 来自 `data/setting-aliases.tsv`。

    改写表 `{写的词: 正确的词}`：导出把布尔项写成界面词，导入器只认 开启/关闭。
    例外集 `{(键, 写的词)}`：标了 `kind=legal` 的组合不许改写 —— Enum 键上的「禁用」
    是合法选项（重装职责被动生命值加成），全局替换会把它改坏。
    """
    noise, legal = {}, set()
    if not path or not os.path.isfile(path):
        return noise, legal
    import csv as _csv
    for r in _csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
        written = (r.get("written") or "").strip()
        canonical = (r.get("canonical") or "").strip()
        kind = (r.get("kind") or "").strip()
        key = (r.get("key") or "").strip()
        if not written or not canonical:
            continue
        if kind == "export-noise":
            noise[written] = canonical
        elif kind == "legal":
            legal.add((key, written))
    return noise, legal


def check_setting_enum_values(text, values, problems):
    """词类设置键只能写权威表列出的取值（`游戏模式开始: 即时/手动/比赛人满后`）。

    只对 `data/setting-values.tsv` 里「有明确 allowed」的键生效；表里没有的键一律不管
    —— 宁可漏报不误报（上一轮硬接没证据的键，8 份语料炸出误报整批撤回）。
    多 schema 的选项在生成时取并集，所以最多跨模式放行，不会误报。
    空值（`键:` 后面什么都没有）不在这里管，由 `check_empty_setting_values` 单独处理。
    """
    if not values:
        return
    for i, raw in enumerate(text.split("\n"), 1):
        st = strip_noise(raw).strip()
        m = re.match(r"^([^:：{}\t]{1,40})\s*[:：]\s*(.+?)\s*$", st)
        if not m:
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        info = values.get(key)
        if not info or val in info["allowed"]:
            continue
        problems.append((i, "error",
                         "「%s」只能写 %s（这里写的是「%s」）。取值来自游戏数据：%s"
                         % (key, " / ".join(sorted(info["allowed"])), val,
                            info["schemas"] or "权威表")))


def check_event_player_scope(text, problems):
    """「持续 - 全局」这类规则里不能用 事件玩家（没有事件上下文）。

    游戏报：「"事件玩家"值在"持续-全局"的规则中不被允许」。
    """
    lines = text.split("\n")
    starts = [i for i, l in enumerate(lines) if l.strip().startswith("规则(")]
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        chunk = lines[start:end]
        joined = "\n".join(chunk)
        # 找事件块里的第一行事件名
        event_line = None
        in_ev = False
        for l in chunk:
            t = l.strip()
            if t == "事件":
                in_ev = True
                continue
            if in_ev and t and t not in ("{", "}") and t.endswith(";"):
                event_line = t[:-1].strip()
                break
        if event_line == "持续 - 全局":
            for off, l in enumerate(chunk):
                if "事件玩家" in l:
                    problems.append((start + off + 1, "error",
                                     "「%s」规则里不能用 事件玩家（没有事件上下文）；"
                                     "改用 玩家变量(玩家, …) / 本地玩家 / 所有玩家(所有队伍)" % event_line))


GLOBAL_LOCAL_ACTIONS = ("伤害", "隐藏英雄HUD", "开始镜头")


def check_local_player_in_global(text, problems):
    """`持续 - 全局` 里把「动身体/视角」的动作指向 `本地玩家` → 无效（提示级）。

    2026-10-24 实机（E-50 五）：`伤害` / `隐藏英雄HUD` / `开始镜头` 写在全局规则里、
    目标写 `本地玩家` 时不起作用。注意**不是**「本地玩家不能用」——同批语料里
    197 处 `创建HUD文本(本地玩家, …)` 正常工作，所以只判这三个动作。
    写死检查前在 9 份真实语料 + 170 个回归样本上量过：0 命中。
    """
    for name, body in _iter_rule_blocks(text):
        ev = _rule_event_lines(body)
        if not ev or ev[0].rstrip(";").strip() != "持续 - 全局":
            continue
        hit = []
        for ln, raw in body:
            for act in GLOBAL_LOCAL_ACTIONS:
                if re.search(re.escape(act) + r"\s*\(\s*本地玩家\s*[,)]", raw):
                    hit.append((ln, act))
        if not hit:
            continue
        acts = "、".join(sorted({a for _l, a in hit}))
        problems.append((hit[0][0], "warning",
                         "「%s」是「持续 - 全局」规则，里面 %d 处把 %s 的目标写成「本地玩家」；"
                         "这类动作对 本地玩家 无效（不动身体、不改视角）。"
                         "改用「持续 - 每名玩家」+ 事件玩家，或显式写 所有玩家(所有队伍)"
                         % (name, len(hit), acts)))


_LOOP_OPEN = re.compile(r"(?m)^[ \t]*(While|For|For 全局变量|For 玩家变量)\s*\(")
_END_STMT = re.compile(r"(?m)^[ \t]*End\s*;")


def check_loop_missing_end(text, problems):
    """循环少了 `End;` → 导入不报错，但那条循环只执行一次（提示级）。

    2026-10-24 实机（E-61）：`While(真); …` 省掉 End; 照常导入，行为变成「做一次」。
    只判「循环个数 > End 个数」这个必要条件，不逐层配对：真实语料里
    `If … Else` 省 End; 的有 22 处（作者就是这么写的，语义确实是「条件成立时做一下」），
    按 If 一起计数就会误报。宁可漏报不误报。
    """
    for name, body in _iter_rule_blocks(text):
        joined = "\n".join(ln for _l, ln in body)
        opens = len(_LOOP_OPEN.findall(joined))
        ends = len(_END_STMT.findall(joined))
        if opens <= ends:
            continue
        line = next((l for l, ln in body if _LOOP_OPEN.match(ln)), 0)
        problems.append((line, "warning",
                         "「%s」里 While/For 共 %d 个，End; 只有 %d 个：至少一处循环少了 End;；"
                         "省掉不报错，但那条循环只会执行一次" % (name, opens, ends)))


def check_setting_range(text, ranges, problems):
    """设置块的数值不能超出已知边界（如 获胜得分 是 1-9）。

    边界可能只有一侧（大厅页只能看到滑杆最大值）；只有一侧有证据时就只查那一侧。
    level 跟着数据来源走：游戏数据里的 min/max 是 error，实机看到的滑杆边界是 warning。
    """
    if not ranges:
        return
    for idx, line in enumerate(text.split("\n"), 1):
        m = re.match(r"^\s*([^:：{}\t][^:：]*?)\s*[:：]\s*(-?\d+(?:\.\d+)?)\s*(%?)\s*$", line)
        if not m:
            continue
        key, val = m.group(1).strip(), float(m.group(2))
        shown = m.group(2)                      # 报错里回显用户写的原文
        if m.group(3) == "%":
            # 编辑器与导出把 FLOAT 写成百分比（150% = 1.5），范围表里存的是倍数。
            # 不换算的话这类行根本不进检查 —— 9 份语料里有 945 处百分比写法。
            val = val / 100.0
            shown = "%s%%（= %g）" % (m.group(2), val)
        if key not in ranges:
            continue
        lo, hi, level = ranges[key]
        if lo is None and hi is None:
            continue
        if not ((hi is not None and val > hi) or (lo is not None and val < lo)):
            continue
        if lo is None:
            msg = "%s 的值 %s 超过上限 %g" % (key, shown, hi)
        elif hi is None:
            msg = "%s 的值 %s 低于下限 %g" % (key, shown, lo)
        else:
            msg = "%s 的值 %s 超出范围（%g~%g）" % (key, shown, lo, hi)
        if key in LOBBY_LIMIT_KEYS:
            msg += LOBBY_ERR
        problems.append((idx, level, msg))


LOBBY_TEAM_SLOTS = 12      # 大厅总栏位：队伍1 + 队伍2 之和的上限（实机确认）
LOBBY_TEAM_DEFAULT = 5     # 新建房间时两队默认各 5 人（2026-10-23 实机）

# 大厅里带滑杆的数值键：越界时游戏统一报「无效的队伍设置」（errors.tsv 65729）
LOBBY_LIMIT_KEYS = ("玩家上限 队伍1", "玩家上限 队伍2",
                    "观战者人数上限", "自由混战人数上限")
LOBBY_ERR = "；游戏导入会报「无效的队伍设置」"


def check_lobby_team_sum(text, problems):
    """大厅栏位：两队玩家上限之和要落在 1~12 之间。

    2026-10-23 用户实机确认：
      - 队伍1 + 队伍2 加起来最多 12 人，所以 6+6、8+4、12+0 都行，7+6 不行
        （逐键单看都没超，只有加起来才露陷）；
      - 最少 1 人才能开局，所以 0+0 不行，但 12+0、6+0 这种「一队空」是合法的。

    等级：超过 12 报必改（2026-10-23 实机：外部写超界值，导入报错）；
    「两队都是 0」只报提示——那多半不是导入失败，而是开不了局，未实测不敢升。
    栏位还跟扩展点数挂钩（可用点数 = 4 × 空栏位数，见 docs/extensions.md 第七节），
    但因为大厅键在真实文件里常被整段省略，这里不按栏位去推算扩展点数。
    """
    vals = {}
    for idx, line in enumerate(text.split("\n"), 1):
        m = re.match(r"^\s*玩家上限\s*队伍([12])\s*[:：]\s*(-?\d+(?:\.\d+)?)\s*$", line)
        if m:
            vals[m.group(1)] = (idx, float(m.group(2)))
    if not vals:
        return
    if len(vals) == 1:
        # 只写了一队：另一队保持大厅默认 5 人，所以单队最多写到 7（5+7=12）
        team, (idx, v) = next(iter(vals.items()))
        if v + LOBBY_TEAM_DEFAULT > LOBBY_TEAM_SLOTS:
            problems.append((idx, "error",
                             "只写了 玩家上限 队伍%s = %g，另一队没写、按大厅默认 %d 人算，"
                             "合计 %g 超过 %d 个栏位（游戏导入会报「无效的队伍设置」）；"
                             "要么把另一队显式写出来，要么单队不超过 %d"
                             % (team, v, LOBBY_TEAM_DEFAULT, v + LOBBY_TEAM_DEFAULT,
                                LOBBY_TEAM_SLOTS, LOBBY_TEAM_SLOTS - LOBBY_TEAM_DEFAULT)))
        return
    total = vals["1"][1] + vals["2"][1]
    idx = max(vals["1"][0], vals["2"][0])
    if vals["1"][1] > LOBBY_TEAM_SLOTS or vals["2"][1] > LOBBY_TEAM_SLOTS:
        return          # 单键已经超了，逐键的「超出范围」会报，别重复提示
    if total > LOBBY_TEAM_SLOTS:
        problems.append((idx, "error",
                         "玩家上限 队伍1 + 队伍2 合计 %g 人，超过大厅总共 %d 个栏位%s"
                         % (total, LOBBY_TEAM_SLOTS, LOBBY_ERR)))
    elif total < 1:
        problems.append((idx, "warning",
                         "玩家上限 队伍1 + 队伍2 合计 0 人，大厅至少要留 1 个栏位才能开局"))


FFA_MODES = ("死斗", "赏金猎手")          # 自由混战类（mode-list.tsv 里的模式，README 亦注明赏金猎手为 FFA）
TEAM_MODES = ("占领要点", "攻击护送", "攻防作战", "攻防阵线", "机动推进",
              "运载目标", "闪点作战", "决斗先锋", "勇夺锦旗", "团队死斗")


def _mode_block_names(text):
    """取 `设置 > 模式` 里列出的模式名（块内第一层的非键行）。

    样本里两种写法都有：`死斗` 单独一行（没有花括号），或 `死斗` + `{ … }`。
    认不出结构就返回空表，让调用方放弃判断（宁可漏报不误报）。
    """
    lines = text.split("\n")
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "模式")
    except StopIteration:
        return []
    names, depth, started = [], 0, False
    for l in lines[start + 1:]:
        s = l.strip()
        if not started:
            if s == "{":
                started, depth = True, 1
            elif s:
                return []
            continue
        if not s:
            continue
        if s == "{":
            depth += 1
            continue
        if s.startswith("}"):
            depth -= 1
            if depth <= 0:
                break
            continue
        if depth == 1 and ":" not in s and "：" not in s:
            names.append(s)
        depth += s.count("{") - s.count("}")
        if depth <= 0:
            break
    return names


def check_lobby_ffa_slots(text, problems):
    """`自由混战人数上限` 要看模式：团队模式必须 0，死斗类至少 1。

    2026-10-23 用户实机：团队模式下自然混战栏位必须为 0（占着栏位大厅设置无效）；
    死斗这类自由混战模式最低 1。认不出的模式、两种模式混写，一律不判。
    """
    names = [n for n in _mode_block_names(text) if n not in ("综合", "英雄", "地图工坊")]
    if not names:
        return
    val = None
    for idx, line in enumerate(text.split("\n"), 1):
        m = re.match(r"^\s*自由混战人数上限\s*[:：]\s*(-?\d+(?:\.\d+)?)\s*$", line)
        if m:
            val = (idx, float(m.group(1)))
            break
    if val is None:
        return
    idx, v = val
    ffa = [n for n in names if n.startswith(FFA_MODES)]
    team = [n for n in names if n.startswith(TEAM_MODES)]
    if len(ffa) + len(team) != len(names):
        return                    # 有认不出的模式，不猜
    if ffa and not team:
        if v < 1:
            problems.append((idx, "error",
                             "死斗类模式里 自由混战人数上限 至少 1，这里写的是 %g"
                             "（界面会提示「大厅设置无效」%s）" % (v, LOBBY_ERR)))
    elif team and not ffa:
        if v > 0:
            problems.append((idx, "error",
                             "团队模式下 自由混战人数上限 必须写 0，这里写的是 %g"
                             "（界面会提示「大厅设置无效」%s）" % (v, LOBBY_ERR)))



def check_hero_rule_multiplier(text, problems):
    """英雄页的「受到伤害量」和规则里的 `设置受到伤害` 是**相乘**，不是覆盖。

    2026-10-23 实机（T15，E-20）：
      英雄 200% + 规则不动 → 打 100 掉 200
      英雄 200% + 规则 50%  → 打 100 掉 100（100 × 0.5 × 2.0）
    所以两边都写时实际倍率是两个数相乘，作者常以为是后者覆盖前者，只报提示不报错。
    """
    hero = None
    for m in re.finditer(r"(?m)^[ \t]*受到伤害量\s*[:：]\s*(-?\d+(?:\.\d+)?)\s*%", text):
        hero = float(m.group(1))
        break
    if hero is None or abs(hero - 100) < 1e-9:
        return
    for m in re.finditer(r"设置受到伤害\(([^;\n]*)\)", text):
        args = m.group(1).split(",")
        if len(args) < 2:
            continue
        try:
            rule = float(args[-1].strip().rstrip("%").strip())
        except ValueError:
            continue          # 写成表达式（如 较大(20, 事件玩家.x)）就不猜
        if abs(rule - 100) < 1e-9:
            continue
        ln = text.count("\n", 0, m.start()) + 1
        problems.append((ln, "warning",
                         "英雄页 受到伤害量 %g%% × 规则 设置受到伤害 %g%% = 实际 %g%%（两者相乘，不是覆盖）；"
                         "只想留一个就把另一个改回 100%%" % (hero, rule, hero * rule / 100)))


def check_reassign_create(text, problems):
    """`重新赋值` 选「字符串」= 只改已有文本，不会创建 → 屏幕上永远没有东西。

    2026-10-23 实机：HUD 规则里用 `创建HUD文本(…, 字符串, 默认可见度)` 每 0.5 秒调一次，
    游戏里完全看不到 HUD。要出现，首次必须带可见性：`可见` 或 `可见和字符串`。
    """
    # 文件里只要有一处用「可见 / 可见和字符串」创建过，就说明文本会出现，
    # 后续用「字符串」原地更新是正确套路，不该报。
    creates = any("创建HUD文本(" in strip_noise(l) and
                  ("可见和字符串" in l or re.search(r",\s*可见\s*,", l))
                  for l in text.split("\n"))
    if creates:
        return
    for ln, line in enumerate(text.split("\n"), 1):
        s = strip_noise(line).strip()
        if not s:
            continue
        if "创建HUD文本(" in s and re.search(r",\s*字符串\s*,\s*默认可见度\s*\)", s):
            problems.append((ln, "warning",
                             "创建HUD文本 的「重新赋值: 字符串」只改已有文本，不会创建；"
                             "第一次要用「可见和字符串」，否则屏幕上什么都看不到"))


def check_health_percent_param(text, problems):
    """`设置最大生命值` 的参数是**百分比**（100 = 原值），不是绝对血量。

    2026-10-23 实机踩过：写 `设置最大生命值(事件玩家, 300)` 以为给 300 血，
    实际是 300%（3 倍）。想给 600 血的路霸一半血，要写 50。
    """
    for m in re.finditer(r"设置最大生命值\(([^,，]*)[,，]\s*(\d+(?:\.\d+)?)\s*\)", text):
        val = float(m.group(2))
        if val >= 250:
            ln = text.count("\n", 0, m.start()) + 1
            problems.append((ln, "warning",
                             "设置最大生命值 的参数是百分比（100 = 原值），%g 表示 %g 倍；"
                             "想给具体血量就换算成百分比（例如 600 血的英雄要 300 点 = 50）" % (val, val / 100)))


def check_speed_percent_param(text, problems):
    """`设置移动速度` 的参数是**百分比**（100 = 原值），不是绝对速度。

    limits-mutex.tsv「百分比 / 设置移动速度的参数」L3（2026-10-23 实测，与
    设置最大生命值 同一条读数）：想要 1.5 倍就写 150；写 1000 是 10 倍，几乎不可能是本意。
    阈值放在 250：9 份真实语料里这个参数的字面量最大 200（100×5 / 110×4 / 200×3 / 150 / 140…），
    250 上命中 0 条，82 个正样本同样 0 条。
    """
    for pos, n, args in _iter_calls(text, "设置移动速度"):
        if n < 2:
            continue
        v = args[1].strip()
        if not re.fullmatch(r"\d+(?:\.\d+)?", v):
            continue
        val = float(v)
        if val >= 250:
            line = text.count("\n", 0, pos) + 1
            problems.append((line, "warning",
                             "设置移动速度 的参数是百分比（100 = 原值），%g 表示 %g 倍；"
                             "想要 1.5 倍就写 150" % (val, val / 100)))


WAIT_BEHAVIOUR_WORDS = ("无视条件", "当为“假”时中止", "当为“真”时重新开始")


def check_wait_behaviour(masked, problems):
    """`等待(时长, X)` 的 X 只能是三个词，写别的会被游戏拒。

    依据（E-68）：exe 里这个槽位的校验函数 `0x140C41860` 就是把这三条文案的句柄
    （`0x787C/0x787D/0x787E`）拿去比较，三条都不中 → 报 51155「…之后应有一个选项」。
    9 份真实语料 1948 处第二参数全部落在这三个词里（0 例外）；
    2026-10-24 实机三种各写一次导入成功、等待都正常返回（A=2/B=2/C=2）。

    为什么要这条检查：第三个词「当为“真”时重新开始」长期不在我们文档里，
    以前写它没人管（要到导入才被游戏拒），写条件表达式也一样。现在离线就报。
    """
    for pos, n, args in _iter_calls(masked, "等待"):
        if n < 2:
            continue
        v = args[1].strip()
        if not v or v in WAIT_BEHAVIOUR_WORDS:
            continue
        line = masked.count("\n", 0, pos) + 1
        problems.append((line, "error",
                         "等待 的第二参数只能写 无视条件 / 当为“假”时中止 / 当为“真”时重新开始，"
                         "写的是「%s」；游戏会报「之后应有一个选项」" % v))


def check_team_word(masked, problems):
    """`队伍N` 里的 N 只能是 1 或 2：合法写法是 双方 / 队伍1 / 队伍2 / 全部。

    依据（E-70）：exe 里队伍槽位的比较函数 `0x140C3C830` 只比这四条文案的句柄
    （30724 双方 / 46194 队伍1 / 46193 队伍2 / 30718 全部），不中 → 报 51148「之后应有一个队伍」。
    语料侧：9 份真实文件里 `队伍N` 共 2273 处，N 只出现 1（1293）和 2（980），**0 例外**。
    """
    for m in re.finditer(r"队伍(\d+)", masked):
        n = int(m.group(1))
        if n in (1, 2):
            continue
        line = masked.count("\n", 0, m.start()) + 1
        problems.append((line, "error",
                         "队伍只有 队伍1 / 队伍2（另有 双方 / 全部），写的是「队伍%d」；"
                         "游戏会报「之后应有一个队伍」" % n))


def check_percent_operator(text, problems):
    """规则里的 `%` 是**取余运算符**，不是百分号。

    2026-10-23 实机：`设置受到伤害(事件玩家, 50%)` 报「第64行的"50%"之后应有一个值」——
    游戏把 `50 %` 当成「50 取余 …」，缺右操作数。
    语料实证：`总计消耗时间 * 60 % 360`（9 处）说明 `%` 确实存在且是取余。
    百分比在工坊里就是普通数字：要 50% 就写 `50`。
    """
    stack, pending = [], None
    for ln, line in enumerate(text.split("\n"), 1):
        s = strip_noise(line).strip()
        if not s:
            continue
        if s == "{":
            stack.append(pending or (stack[-1] if stack else None))
            pending = None
            continue
        if s.startswith("}"):
            if stack:
                stack.pop()
            pending = None
            continue
        if s.endswith("{"):
            pending = s[:-1].strip()
            continue
        if ("动作" in stack or "条件" in stack) and re.search(r"\d\s*%\s*(?:[)\]},;]|$)", s):
            problems.append((ln, "error",
                             "「%」在工坊里是取余运算符，后面必须跟数值；游戏报「…之后应有一个值」。"
                             "要写百分比就用纯数字：50 就是 50%"))
        if ":" not in s and "：" not in s and "(" not in s:
            pending = s


def check_hero_enable_layer(text, problems):
    """`启用英雄` 必须写在 `英雄 > 综合` 里，挂在 `英雄` 直属层导入会失败。

    2026-10-23 实机：写成 英雄 { 启用英雄 { 路霸 } } 报
    「第38行的"200% })"之后应有一个队伍设置」——报错文案完全不提「启用英雄」，容易查错方向。
    合法父级：`综合`（猪猪钩钩乐·原版）或 `队伍1` / `队伍2`（找蛋躲猫猫，两个都是能玩的真实模式）。
    只有直接挂在 `英雄` 下才是错的——游戏那句报错「之后应有一个队伍设置」就是这么来的。
    """
    stack, pending = [], None
    for ln, line in enumerate(text.split("\n"), 1):
        s = strip_noise(line).strip()
        if not s:
            continue
        if s == "启用英雄":
            parent = stack[-1] if stack else "顶层"
            if parent not in ("综合", "队伍1", "队伍2"):
                problems.append((ln, "error",
                                 "「启用英雄」要写在 英雄 > 综合 里面，现在挂在「%s」下；"
                                 "导入会报「之后应有一个队伍设置」" % parent))
            pending = "启用英雄"
            continue
        if s == "{":
            stack.append(pending or (stack[-1] if stack else None))
            pending = None
            continue
        if s.startswith("}"):
            if stack:
                stack.pop()
            pending = None
            continue
        if s.endswith("{"):
            pending = s[:-1].strip()
            continue
        if ":" not in s and "：" not in s and "(" not in s and not s.startswith("禁用地图"):
            pending = s


_CORPUS_PARENTS = {"map": None}


def load_corpus_block_parents(path=None):
    """{子块: {语料里出现过的父块}} —— 来自 data/format-spec-corpus.tsv（kind=block_parent）。

    这一层游戏数据里没有（导出器自己套的壳），只能用真实语料定。
    注意边界：语料只证明**结构**，不证明值合法（见 E-22）。
    """
    path = os.path.abspath(path or os.path.join(DATA_DIR, "format-spec-corpus.tsv"))
    if _CORPUS_PARENTS["map"] is not None:
        return _CORPUS_PARENTS["map"]
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if (row.get("kind") or "") != "block_parent":
                    continue
                child = (row.get("subject") or "").strip()
                parent = (row.get("context") or "").strip()
                if child and parent:
                    out.setdefault(child, set()).add(parent)
    _CORPUS_PARENTS["map"] = out
    return out


def load_mode_name_set():
    """{模式名 / ow_name} —— 来自 data/mode-list.tsv。"""
    out = set()
    path = os.path.join(DATA_DIR, "mode-list.tsv")
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                for col in ("mode", "ow_name"):
                    v = (row.get(col) or "").strip()
                    if v and v != "全部":
                        out.add(v)
    return out


def load_maps_not_in_editor(path=None):
    """{地图名: (主图, 说明)} —— 数据表里有、但编辑器「启用地图」里选不到的名字。

    来源：data/map-not-in-editor.tsv（用户实机核对，2026-10-23：釜山系只有「釜山」一个入口）。
    """
    path = os.path.abspath(path or os.path.join(DATA_DIR, "map-not-in-editor.tsv"))
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            name = (row.get("name") or "").strip()
            if name:
                out[name] = ((row.get("base") or "").strip(), (row.get("reason") or "").strip())
    return out


TOKEN_SPLIT = re.compile(r"[\s(),;:：，；（）\[\]{}]+")


def check_maps_not_in_editor(text, problems):
    """写了编辑器里选不到的地图变体 → 提示改用主图名。

    游戏侧表现通常是「无效的地图设置」，而玩家在编辑器里根本找不到这个名字，很难自己想到。

    按**整词**匹配，不做子串匹配：`春节釜山寺院` 是池子里真实存在的条目（勇夺锦旗有），
    用子串匹配会把它误判成「釜山寺院」（2026-10-23 实测到的误报）。
    """
    table = load_maps_not_in_editor()
    if not table:
        return
    for ln, line in enumerate(text.split("\n"), 1):
        s = strip_noise(line).strip()
        if not s:
            continue
        tokens = set(t for t in TOKEN_SPLIT.split(s) if t)
        for name, (base, reason) in table.items():
            if name in tokens:
                problems.append((ln, "warning",
                                 "「%s」不能单独写（%s）；写成「%s」即可"
                                 % (name, reason or "它属于主图", base or name)))
                break


_KEY_PARENT_LAYERS = {"t": None}


def load_key_parent_layers(path=None):
    """{设置键: 禁止写入的父级块集合} —— data/key-parent-layers.tsv。

    只收**已经有实机证据**的组合，而且是「键 × 具体模式」的否定式：
      · 随机英雄复生 / 允许切换英雄 写在「决斗先锋」块内被拒（W1/W2），
        但写在「死斗」块内通过（T1）、写在「模式 > 综合」通过（X2）
      · 机制：该模式的 schema 列表里只有 Category=None 的别名，真条目在 008 英雄；
        挂了 008 的模式（死斗）就能在模式块里写
    所以**不要**把它当成「这些键只能挂综合」——那是早期误判。
    """
    if _KEY_PARENT_LAYERS["t"] is not None:
        return _KEY_PARENT_LAYERS["t"]
    path = os.path.abspath(path or os.path.join(DATA_DIR, "key-parent-layers.tsv"))
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                k = (row.get("key") or "").strip()
                bad = (row.get("forbidden_parents") or "").strip()
                if k and bad:
                    out[k] = set(x.strip() for x in bad.split("|") if x.strip())
    _KEY_PARENT_LAYERS["t"] = out
    return out


def check_setting_key_layers(text, problems):
    """设置键写进了实测会拒它的那个「模式块」。

    只报**实机验证过的组合**（`data/key-parent-layers.tsv` 的 forbidden_parents）：
      · 随机英雄复生 / 允许切换英雄 写进「模式 > 决斗先锋」→ 被拒（W1/W2）
      · 同样两个键写进「模式 > 综合」→ 通过（X2）；写进「模式 > 死斗」→ 通过（V1）

    为什么不做通用规则：曾经按「该模式挂载的 schema 里有没有这个键」整表判（schema-keys +
    mode-schemas 交叉），模型在 6 个实机点上只错 1 个（别名条目那条），但一放到真实语料上
    就 5 个文件误报——因为 schema 归属不等于导入器接受集（别名/Category 那一层数据还没拿到）。
    按 D-006「误报比漏报更伤」，先只保留硬证据，等拿到 per-(schema,key) 的 Category 再扩。
    """
    layers = load_key_parent_layers()
    if not layers:
        return
    modes = load_mode_name_set()
    stack, pending = [], None
    for ln, line in enumerate(text.split("\n"), 1):
        s = strip_noise(line).strip()
        if not s:
            continue
        if s == "{":
            stack.append(pending or (stack[-1] if stack else None))
            pending = None
            continue
        if s.startswith("}"):
            if stack:
                stack.pop()
            pending = None
            continue
        if s.endswith("{"):
            pending = s[:-1].strip()
            continue
        if ":" in s or "：" in s:
            m = re.match(r"^([^:：]{1,40})\s*[:：]\s*\S", s)
            if not m or not stack:
                continue
            key = m.group(1).strip()
            bad = layers.get(key) or set()
            parent = stack[-1]
            if parent in modes and parent in bad:
                problems.append((ln, "error",
                                 "「%s」不能写在「%s」块里——这个组合实测被拒（导入报"
                                 "「之后应有一个游戏模式设置」）。改写进「模式 > 综合」，"
                                 "或换一个挂了它所属 schema 的模式" % (key, parent)))
            continue
        pending = s


def load_workshop_modes(path=None):
    """工坊「设置 → 模式」里**真能选到**的模式名（`data/mode-list.tsv` 的 ow_name + base）。

    2026-10-24 用户实测反馈：动感斗球 / 温斯顿的沙滩排球这类模式在工坊界面里选不到。
    它们只存在于内部 schema 表（`mode-pages.tsv` 有 55 个），和「能选的 21 个」不是一回事。
    写这些名字进 `.ow`，导入时哪一步都过不去。
    """
    if getattr(load_workshop_modes, "_cache", None) is not None:
        return load_workshop_modes._cache
    path = path or os.path.join(DATA_DIR, "mode-list.tsv")
    names = set()
    if os.path.isfile(path):
        import csv as _csv
        for r in _csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
            for col in ("ow_name", "base", "mode"):
                v = (r.get(col) or "").strip()
                if v and v != "全部":
                    names.add(v)
    load_workshop_modes._cache = names
    return names


# 设置块里除模式名之外，合法出现的子块名
EXTRA_SETTING_BLOCKS = ("综合", "英雄", "地图工坊")


def check_mode_names(text, problems, modes=None):
    """`设置 > 模式` 下的块名必须是工坊里真能选到的模式（`data/mode-list.tsv`：21 条 = 14 个基础模式 + 6v6 变体）。

    依据不是猜的：`acceptance-lab/map-pools/全地图池_21模式_314条.ow` 用这 21 个模式块
    一个块列全该模式的 314 条地图，2026-10-23 **实机导入成功** —— 这 21 个名字游戏真认。
    反之，内部数据里的 55 个模式里剩下的那批（动感斗球 / 怪鼠复仇 / 雪球攻势 / 剧情任务 /
    英雄精通 / 镜影守望* / 幻变交锋* …）界面里选不到，写进 `.ow` 一步都过不去。

    两个合法形态：
      · 块头：`死斗 { … }`（名字也可能带全角冒号，比如 `星际守望：银河救兵`）
      · 清单行 / 块头：`禁用 勇夺锦旗`（语料实测写法，前缀是开关词）
    """
    modes = modes if modes is not None else load_workshop_modes()
    if not modes:
        return
    lines = text.split("\n")
    stack, pending = [], None
    for idx, raw in enumerate(lines):
        st = strip_noise(raw).strip()
        if not st:
            continue
        if st == "设置":
            pending = "设置"
            continue
        if st.startswith("{"):
            stack.append(pending if pending else (stack[-1] if stack else None))
            pending = None
            continue
        if st.startswith("}"):
            if stack:
                stack.pop()
            pending = None
            continue
        if st.endswith("{"):
            name = st[:-1].strip()
            if stack and stack[-1] == "模式":
                _check_mode_name(name, idx + 1, problems, modes)
            pending = name
            continue
        # 名字和 `{` 分两行的写法：下一行是 `{` 才算块头
        nxt = ""
        for j in range(idx + 1, len(lines)):
            if lines[j].strip():
                nxt = lines[j].strip()
                break
        if stack and stack[-1] == "模式":
            if nxt.startswith("{"):
                pending = st
                _check_mode_name(st, idx + 1, problems, modes)
                continue
            if st.startswith(("禁用 ", "启用 ")):
                target = st[3:].strip()
                _check_mode_name(target, idx + 1, problems, modes)
                continue
        pending = st


def _check_mode_name(name, line_no, problems, modes):
    # 语料实测：`禁用 勇夺锦旗 { … }` 是合法的块头（禁用模式下挂的设置），名字前带开关词
    for prefix in ("禁用 ", "启用 "):
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
            break
    if not name or name in EXTRA_SETTING_BLOCKS or name in modes:
        return
    problems.append((line_no, "error",
                     "「%s」不是工坊里能选到的模式（内部数据里有，界面模式列表里没有，写了导不进来）。"
                     "能用的模式：%s —— 完整清单见 data/mode-list.tsv"
                     % (name, _short_mode_list())))


def _short_mode_list(limit=12):
    """给报错用的短清单：只要基础模式名，不把 6v6 变体和 ow_name 全铺开。"""
    path = os.path.join(DATA_DIR, "mode-list.tsv")
    names = []
    if os.path.isfile(path):
        import csv as _csv
        for r in _csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
            base = (r.get("base") or "").strip()
            if base and base != "全部" and base not in names:
                names.append(base)
    names.sort()
    if len(names) > limit:
        return "、".join(names[:limit]) + " 等 %d 个" % len(names)
    return "、".join(names)


def check_block_layers(text, problems):
    """块套错层：父级从来不在语料里出现过 → 导入基本必失败。

    规则来源（都由数据/语料给，不硬编码）：
      英雄名      → 父级 ∈ 综合 / 队伍1 / 队伍2
      模式名      → 父级 = 模式
      其它块      → 父级 ∈ format-spec-corpus.tsv 里该块出现过的父级
    只对 `设置` 树生效；规则体里的 事件/动作/条件 不参与。
    """
    parents = load_corpus_block_parents()
    if not parents:
        return
    heroes = load_hero_names()
    modes = load_mode_name_set()
    stack, pending = [], None
    for ln, line in enumerate(text.split("\n"), 1):
        s = strip_noise(line).strip()
        if not s:
            continue
        if s == "{":
            child = pending or (stack[-1] if stack else None)
            parent = (stack[-1] if stack else None) or "顶层"
            if child:
                if child in heroes:
                    allowed = {"综合", "队伍1", "队伍2"}
                elif child in modes:
                    allowed = {"模式"}
                else:
                    allowed = parents.get(child)
                inside = (parent in SETTINGS_BLOCKS or parent in ("综合", "队伍1", "队伍2")
                          or parent in modes)
                if allowed and inside and parent not in allowed:
                    problems.append((ln, "warning",
                                     "「%s」不该直接挂在「%s」下；语料里它只出现在：%s"
                                     % (child, parent, "、".join(sorted(allowed)))))
            stack.append(child)
            pending = None
            continue
        if s.startswith("}"):
            if stack:
                stack.pop()
            pending = None
            continue
        if s.endswith("{"):
            pending = s[:-1].strip()
            continue
        if ":" not in s and "：" not in s and "(" not in s:
            pending = s


def check_probe_invisible(path, text, problems):
    """lab 里的验收探针要让屏幕干净（用户 2026-10-23 要求）。

    正确工具是 `隐藏英雄HUD` / `隐藏游戏模式HUD`（隐藏游戏自带 HUD），不是 `设置不可见`
    ——后者只让别人看不见你，自己屏幕上照样持枪。两条都放规则最前面（开赛前就生效）。
    """
    p = (path or "").replace("\\", "/")
    if "probes/lab/" not in p:
        return
    if "开始镜头" not in text:
        problems.append((0, "warning",
                         "验收探针没做工位隐蔽：加 隐藏英雄HUD / 隐藏游戏模式HUD / "
                         "开始镜头(事件玩家, 矢量(0, 50, 0), 矢量(0, 200, 0), 100)，"
                         "画面里就不会有角色（见 docs/acceptance-flow.md）"))
        return
    i_hide = text.find("开始镜头")
    i_wait = text.find("等待直到(游戏正在进行中()")
    i_while = text.find("While(")
    if i_while != -1 and i_while < i_hide:
        return          # 写在循环里＝每秒重设，防重生把镜头冲掉
    if i_wait != -1 and i_hide > i_wait:
        problems.append((0, "warning",
                         "开始镜头 写在「等待直到(游戏正在进行中())」之后了：开赛前那段仍能看到角色，"
                         "要挪到规则最前面（等待之前）"))


def check_probe_output(path, text, problems):
    """实验探针（`tools/probes/lab/`）的读数必须走 `记入查看器`。

    2026-10-23 教训：给用户实机跑的文件如果用 `大字体信息` 显示结果，用户只能手抄或截图；
    查看器面板能一键「将当前记录复制到剪贴板」。这条本来是 SKILL.md 的生成纪律，
    但写探针时没加载 SKILL.md 就会漏 —— 所以放到校验器里守门。
    只对 lab/ 目录生效，不动历史探针（那 13 个用 HUD 的是故意测 HUD 本身）。
    """
    p = (path or "").replace("\\", "/")
    if "/probes/lab/" not in p:
        return
    if "记入查看器" not in text:
        problems.append((0, "warning",
                         "实验探针里没有任何 记入查看器：用户拿不到结果，别用屏幕文字"))
        return
    for i, line in enumerate(text.split("\n"), 1):
        if "大字体信息" in line or "小字体信息" in line:
            problems.append((i, "warning",
                             "实验探针用 大字体信息/小字体信息 显示结果：屏幕字只能手抄或截图，"
                             "改用 记入查看器（面板一键复制）"))
            break


def load_element_kinds(path):
    """元素名 -> 动作 / 值 / 事件 / 扩展。"""
    import csv as _csv
    out = {}
    if os.path.isfile(path):
        for r in _csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"):
            if r.get("name"):
                out[r["name"]] = r["kind"]
    return out


def check_action_as_value(text, kinds, problems):
    """赋值右边直接写了一个「动作」函数 → 游戏报「"="之后应有一个值」。

    实机：`事件玩家.hudId = 创建HUD文本(…)` 报「第111行的"="之后应有一个值」。
    正确写法是先调动作，再用值函数取结果：`创建HUD文本(…); 事件玩家.hudId = 上一个文本ID;`
    """
    for ln, line in enumerate(text.split("\n"), 1):
        s = strip_noise(line).strip()
        if not s or s.startswith("//"):
            continue
        m = re.search(r"[-+*/]?=(?!=)\s*([\u4e00-\u9fa5A-Za-z_][\w\u4e00-\u9fa5]*)\s*\(", s)
        if m and kinds.get(m.group(1)) == "动作":
            problems.append((ln, "error",
                             "「%s」是动作，不能写在等号右边取值；先单独调用它，再用对应的值函数取结果"
                             "（如 上一个文本ID / 上一个效果ID）。游戏会报「\"=\"之后应有一个值」" % m.group(1)))


def check_element_kind(text, kinds, problems):
    """动作块里不能放值函数；条件块里不能放动作。

    典型错误：把「比赛结束()」当动作写（它是值，表示"比赛是否已结束"）。
    游戏报「"比赛结束()"之后应有一个赋值运算符」。
    """
    if not kinds:
        return
    lines = text.split("\n")
    offs = _line_offsets(lines)
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
            if ASSIGNMENT.match(s):          # 玩家变量赋值：所有玩家(所有队伍).X = …
                continue
            # 任何 `.变量 = / += …` 都是赋值目标，不是「值函数当动作」
            if re.search(r"\.\w+(?:\[[^\]]*\])*\s*[-+*/]?=(?!=)", s):
                continue
            # 折行续行（上一行没写完）
            if _prev_continues(lines, idx) or _line_continues(lines[idx]):
                continue
            m = re.match(r"^([\u4e00-\u9fa5A-Za-z_][\w\u4e00-\u9fa5]*)\s*\(", s)
            if m and kinds.get(m.group(1)) == "值":
                _add(problems, text, offs[idx] + m.start(), "error",
                     "「%s」是值函数（返回一个值），不能单独当动作写；"
                     "要判断它请写进条件/If" % m.group(1))
        elif block == "条件" and depth == 1:
            for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z_][\w\u4e00-\u9fa5]*)\s*\(", s):
                if kinds.get(m.group(1)) == "动作":
                    _add(problems, text, offs[idx] + m.start(), "error",
                         "「%s」是动作，不能写在条件里" % m.group(1))
                    break



def check_string_interp(text, problems):
    """自定义字符串 / 字符串 的 {N} 数量必须与实参数量匹配（按括号配对取实参）。"""
    for m in re.finditer(r"(自定义字符串|字符串)\(", text):
        fn = m.group(1)
        i = m.end()
        depth, in_str, escaped = 1, False, False
        while i < len(text) and depth > 0:
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        body = text[m.end():i - 1]
        if "\n" in body:      # 跨行调用：括号配对容易被嵌套字符串干扰，宁可不判
            continue
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
            _add(problems, text, m.start(), "warning",
                 "%s 的模板里有 {%d}，但只给了 %d 个值（需要 %d 个）" % (fn, max(idx), have, need))



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
    for m in re.finditer(r"(?<![\w.\u4e00-\u9fa5])([\u4e00-\u9fa5A-Za-z_][\w\u4e00-\u9fa5]*)(?![\w\u4e00-\u9fa5])(?!\s*\()", text):
        name = m.group(1)
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.start())
        line_text = text[line_start: line_end if line_end >= 0 else len(text)]
        # 只检查处在表达式里的行（块标题行没有括号/逗号，跳过）
        if "(" not in line_text and "," not in line_text:
            continue
        # 下拉选项是整串中文短语（用全角逗号分隔），不是裸函数名
        if re.match(r"\s*[，、；]", text[m.end():m.end() + 2]) or \
                re.search(r"[，、；]\s*$", text[max(0, m.start() - 3):m.start()]):
            continue
        if name in needs_arg and name not in allowed:
            _add(problems, text, m.start(), "error",
                 "「%s」是函数，必须写成 %s(...)；只写名字游戏会报「之后应有 (」" % (name, name))



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
            if name == "子程序":
                i += 2                  # 子程序; 名字;  第二行是子程序名，不是事件参数
                continue
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
                        # 第 3 段是英雄限制：可以写 全部 / 某个英雄名（实测「卢西奥」「黑影」）
                        if v in event_param_words or v in _hero_names():
                            continue
                        if True:
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


# ---------------------------------------------------------------- 数据 ID 层
# 名字表全部来自 data/ 下的导出表（tools/gen_name_tables.py 可重新生成）。
# 表里没有 = 游戏当前版本没有这个名字；这里是唯一允许把「名字」判成 error 的地方。
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "data")
_CACHE = {}


def _name_set(fname, col, path=None):
    """读 data/ 下某个 tsv 的一列，返回名字集合（带缓存，缺文件返回空集合）。"""
    path = os.path.abspath(path or os.path.join(DATA_DIR, fname))
    key = ("set", path, col)
    if key in _CACHE:
        return _CACHE[key]
    out = set()
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                v = (row.get(col) or "").strip()
                if v:
                    out.add(v)
    _CACHE[key] = out
    return out


def load_hero_names(path=None):
    """英雄名集合（data/heroes.tsv）。"""
    return _name_set("heroes.tsv", "name", path)


def load_button_names(path=None):
    """按钮名集合（data/buttons.tsv）。"""
    return _name_set("buttons.tsv", "name", path)


def load_setting_keys(path=None):
    """设置键全集（data/setting-keys.tsv：模式/大厅/主程序/英雄页 的并集）。"""
    return _name_set("setting-keys.tsv", "key", path)


def load_event_names(path=None):
    """事件名集合（data/events.tsv）。"""
    return _name_set("events.tsv", "event", path)


def load_extra_ability_names(path=None):
    """从 data/ability-values.tsv 补一批名字：技能全名 + 括号里的形态/武器名。

    例：「锯齿利刃（格雷西）」→ 补 锯齿利刃（格雷西） 与 格雷西。
    真实语料里 hero 设置键写成「锯齿利刃（格雷西）冷却时间」，只查 abilities.tsv 会误报缺项。
    """
    path = os.path.abspath(path or os.path.join(DATA_DIR, "ability-values.tsv"))
    out = set()
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            name = (row.get("ability") or row.get("技能") or "").strip()
            if not name:
                continue
            out.add(name)
            for inner in re.findall(r"[（(]([^（）()]{1,20})[）)]", name):
                out.add(inner.strip())
    return out


def load_ability_names(path=None):
    """{技能名: {英雄…}}（data/abilities.tsv）。"""
    path = os.path.abspath(path or os.path.join(DATA_DIR, "abilities.tsv"))
    key = ("abilities", path)
    if key in _CACHE:
        return _CACHE[key]
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                a = (row.get("name") or "").strip()
                if a:
                    out.setdefault(a, set()).add((row.get("hero") or "").strip())
    _CACHE[key] = out
    return out


def _pos(text, pos):
    """字符偏移 -> (1 基行号, 行内列偏移)。"""
    return text.count("\n", 0, pos) + 1, pos - (text.rfind("\n", 0, pos) + 1)


def _add(problems, text, pos, level, msg):
    """带列的报错入口：列用于把合并行的行号换算回原文行号。"""
    ln, col = _pos(text, pos)
    problems.append((ln, level, msg, col))


PLAYER_WORDS = ("事件玩家", "本地玩家", "攻击方", "被攻击方", "主机玩家", "本市玩家",
                "玩家", "全部玩家", "真", "假", "True", "False", "无", "_", "空数组",
                "全部", "双方", "队伍1", "队伍2", "所有队伍", "全部队伍")


def _looks_like_name(arg):
    """参数看起来是「裸名字常量」而不是表达式/变量引用/数字。

    只对裸名字做存在性检查：带括号的是函数调用，带 . 的是变量或字段访问，
    带运算符的是表达式，数字/真假是字面量——这些都不是名字。
    """
    a = arg.strip()
    if not a or len(a) > 40:
        return False
    if "." in a or "(" in a or ")" in a or "," in a or "，" in a:
        return False
    if any(ch in a for ch in "[]{}|=<>+*/\"'!?"):
        return False
    if a in PLAYER_WORDS:
        return False
    if re.fullmatch(r"-?\d+(?:\.\d+)?%?", a):
        return False
    return bool(re.match(r"^[\u4e00-\u9fffA-Za-z_][\u4e00-\u9fff\w·：:＋\- ]*$", a))


def _unknown_name(kind, name, pos, problems, text, hint="", level="error"):
    _add(problems, text, pos, level,
         "%s「%s」不在当前版本数据表里（可能已改名或移除）%s" % (kind, name, hint))


def check_hero_names(text, problems, hero_names, declared=None):
    """英雄(名字) 里的英雄名必须还在当前版本英雄表里。

    游戏只报「"英雄("之后应有一个英雄名」，指不到「这个英雄没了」。
    """
    if not hero_names:
        return
    declared = declared or set()
    for m in re.finditer(r"(?<![\w\u4e00-\u9fff])英雄\(([^()]*)\)", text):
        arg = m.group(1).strip()
        if not _looks_like_name(arg) or arg in declared or arg in hero_names:
            continue
        _unknown_name("英雄名", arg, m.start(), problems, text,
                      "；用 ws.py doc --search 英雄 查有效名")


def check_button_names(text, problems, button_names):
    """按钮(名字) 里的按钮名必须还在当前版本按钮表里。"""
    if not button_names:
        return
    for m in re.finditer(r"(?<![\w\u4e00-\u9fff])按钮\(([^()]*)\)", text):
        arg = m.group(1).strip()
        if not _looks_like_name(arg) or arg in button_names or arg == "按钮":
            continue
        _unknown_name("按钮名", arg, m.start(), problems, text,
                      "；可选：%s" % " / ".join(sorted(button_names)))


# 技能名在 .ow 里只出现在英雄设置键里，两种形态：
#   终极技能充能速度（鸡飞狗跳）     括号里
#   战斗时终极技能充能速度 鸡飞狗跳   空格后（前面是 …速度/倍率/冷却时间 …）
ABILITY_SPACE_PREFIX = re.compile(r"(速度|倍率|冷却时间|最长时间|持续时间|充能)$")


def _ability_candidates(key):
    out = []
    for m in re.finditer(r"[（(]\s*([^（）()]+?)\s*[）)]", key):
        out.append(m.group(1))
    if " " in key:
        head, tail = key.rsplit(" ", 1)
        if ABILITY_SPACE_PREFIX.search(head.strip()):
            out.append(tail.strip())
    return [x for x in out if x and not re.fullmatch(r"-?\d+(?:\.\d+)?%?", x)]


def _line_offsets(lines):
    """每行起始字符偏移，用于把「第几行」换算回字符位置。"""
    offs = [0]
    for line in lines:
        offs.append(offs[-1] + len(line) + 1)
    return offs


_OFFICIAL_KEYS = {"set": None}


_EXT_CACHE = {"set": None}


def _extension_values():
    """所有扩展解锁的下拉选项（data/extension-values.tsv 里的选项名）。"""
    if _EXT_CACHE["set"] is None:
        vals = set()
        path = os.path.join(DATA_DIR, "extension-values.tsv")
        if os.path.isfile(path):
            with open(path, encoding="utf-8-sig") as f:
                r = csv.DictReader(f, delimiter="\t")
                for row in r:
                    v = (row.get("option") or row.get("value") or "").strip()
                    if v:
                        vals.add(v)
        _EXT_CACHE["set"] = vals
    return _EXT_CACHE["set"]


def _official_hero_keys():
    """data/hero-official-keys.tsv 里的英雄设置键（游戏自带的键名，最权威）。"""
    if _OFFICIAL_KEYS["set"] is None:
        path = os.path.join(DATA_DIR, "hero-official-keys.tsv")
        keys = set()
        if os.path.isfile(path):
            with open(path, encoding="utf-8-sig") as f:
                r = csv.DictReader(f, delimiter="\t")
                for row in r:
                    k = (row.get("key") or "").strip()
                    if k:
                        keys.add(k)
        _OFFICIAL_KEYS["set"] = keys
    return _OFFICIAL_KEYS["set"]


def check_ability_names(text, problems, abilities, hero_names):
    """英雄设置块里的技能名必须还在当前版本技能表里。

    游戏更新会改技能中文名；写错了只会报「之后应有一个…」这类看不懂的话。
    """
    if not abilities:
        return
    lines = text.split("\n")
    offs = _line_offsets(lines)
    stack, pending, hero = [], None, None
    for idx, raw in enumerate(lines):
        s = strip_noise(raw).strip()
        if not s:
            continue
        if s in BLOCK_KEYWORDS:
            pending = s
            continue
        if s.endswith("{"):
            label = s[:-1].strip() or pending or (stack[-1] if stack else "")
            stack.append(label)
            pending = None
            if "英雄" in stack and label in hero_names:
                hero = label
            continue
        if s.startswith("{"):
            stack.append(pending or (stack[-1] if stack else None))
            pending = None
            continue
        if s.startswith("}"):
            while stack and s:
                stack.pop()
                s = s.lstrip("}").strip()
            hero = next((x for x in reversed(stack) if x in hero_names), None)
            continue
        m = re.match(r"^([^:：]{1,60}?)\s*[:：]\s*\S", s)
        if not m:
            pending = s                 # 裸标签行（英雄名 / 队伍1 …）后面跟的就是 {
            continue
        if hero is None or "英雄" not in stack:
            continue
        key = m.group(1).strip()
        if key in _official_hero_keys():      # 官方导出的英雄键，括号里的词不一定是技能名
            continue
        for cand in _ability_candidates(key):
            if cand in abilities:
                continue
            pos = offs[idx] + raw.find(cand)
            _unknown_name("技能名", cand, pos, problems, text,
                          "；英雄 %s 的设置键「%s」用到了它（技能形态/武器名也会出现在括号里，可能是数据表缺项）"
                          % (hero, key), level="warning")



SETTING_KEY_WHITELIST = {"鸣谢"}


def check_setting_keys(text, problems, setting_keys, hero_names=None):
    """设置块里的键必须还在当前版本设置键表里。

    键改名（比如「急救包刷新时间」→「急救包刷新」）导入时只报
    「之后应有一个游戏模式设置」，看不出是键没了。
    """
    if not setting_keys:
        return
    lines = text.split("\n")
    offs = _line_offsets(lines)
    stack, pending = [], None
    for idx, raw in enumerate(lines):
        s = strip_noise(raw).strip()
        if not s:
            continue
        if s in BLOCK_KEYWORDS or s.startswith("规则("):
            pending = "规则" if s.startswith("规则(") else s
            if s.endswith("{"):
                stack.append(pending)
                pending = None
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
        if block not in SETTINGS_BLOCKS:
            continue
        if "地图工坊" in stack:             # 地图工坊块 = 作者自定义设置，键名随便起
            continue
        if "禁用地图" in stack or "启用地图" in stack:
            continue          # 这两个块里是地图名列表，不是 键: 值
        if "英雄" in stack:                 # 英雄块里的键走 check_ability_names
            continue
        m = re.match(r"^([^\s:：]{1,40})\s*[:：]\s*\S", s)
        if not m:
            continue
        # 名字里带全角冒号的块头会被上面这个正则当成「键: 值」。
        # 例：`星际守望：银河救兵` 下面跟一个 `{`，实际是模式块名，不是设置键。
        # 判据只看下一行是不是 `{` —— 是块头就跳过（2026-10-24 自查 55 个模式时发现）。
        nxt = ""
        for j in range(idx + 1, len(lines)):
            if lines[j].strip():
                nxt = lines[j].strip()
                break
        if nxt.startswith("{"):
            pending = s
            continue
        key = m.group(1)
        if key in setting_keys or key in SETTING_KEY_WHITELIST:
            continue
        level = "warning" if "大厅" in stack else "error"
        _unknown_name("设置键", key, offs[idx] + raw.find(key), problems, text,
                      "；用 ws.py settings --mode <模式> 生成合法的键", level=level)


_HERO_CACHE = {"names": None}


def _line_continues(line):
    """这一行是否「还没写完」：以运算符 / 逗号 / 问号 等结尾。"""
    s = strip_noise(line).strip()
    if not s:
        return False
    return bool(re.search(r"(==|!=|&&|\|\||=|\?|\+|-|\*|/|,|!)$", s))


def _prev_continues(lines, i):
    """往上看第一条非空行，是否以运算符结尾（跨行语句）。"""
    j = i - 1
    while j >= 0:
        if strip_noise(lines[j]).strip():
            return _line_continues(lines[j])
        j -= 1
    return False


def _next_continues(lines, i):
    """往下看第一条非空行，是否以运算符开头（跨行语句的下半截）。

    真实语料里的写法（8 个模式实测）：
        相距距离(事件玩家, 目标) > 20
        && 事件玩家.生命值 < 50;
    上一行结尾没有运算符，靠下一行开头的 `&&` / `||` / `);` 接着写。
    """
    j = i
    while j < len(lines):
        s = strip_noise(lines[j]).strip()
        if s:
            return bool(re.match(r"^(&&|\|\||==|!=|>=|<=|=|>|<|\+|-|\*|/|\?|,|\.|\)|:)", s))
        j += 1
    return False


def _is_default_var(name):
    """工坊内置变量：全局/玩家的 A~Z 共 26 个（索引 0~25），不声明也存在。"""
    return len(name) == 1 and "A" <= name <= "Z"


def _is_default_sub(name):
    """工坊内置子程序：Sub0~Sub7 共 8 个（索引 0~7）。"""
    return bool(re.fullmatch(r"Sub[0-7]", name or ""))


def _hero_names():
    """读 data/heroes.tsv 的英雄名（事件第 3 段可写英雄名）。"""
    if _HERO_CACHE["names"] is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "heroes.tsv")
        names = set()
        try:
            with open(path, encoding="utf-8") as f:
                next(f, None)
                for line in f:
                    c = line.split("\t")
                    if c and c[0].strip():
                        names.add(c[0].strip())
        except OSError:
            pass
        _HERO_CACHE["names"] = names
    return _HERO_CACHE["names"]


def check_event_names(text, problems, event_names):
    """事件块第一行的事件名必须还在当前版本事件表里。"""
    if not event_names:
        return
    lines = text.split("\n")
    offs = _line_offsets(lines)
    in_events, depth, i = False, 0, 0
    while i < len(lines):
        s = strip_noise(lines[i]).strip()
        if s == "事件":
            in_events, depth = True, 0
            i += 1
            continue
        if not in_events:
            i += 1
            continue
        if s.startswith("{"):
            depth += 1
        elif s.startswith("}"):
            depth -= 1
            if depth <= 0:
                in_events = False
        elif depth == 1 and s.endswith(";") and "(" not in s:
            name = s[:-1].strip()
            if name and name not in event_names:
                _add(problems, text, offs[i], "error",
                     "事件名「%s」不在当前版本数据表里（可能已改名或移除）；"
                     "用 ws.py explain 查事件相关报错文案" % name)
            if name == "子程序":
                i += 1                    # 下一行是子程序名，不是事件名
                while i < len(lines) and not strip_noise(lines[i]).strip():
                    i += 1
                i += 1
                continue
            # 事件参数行跟着事件名，不再当名字检查
            i += 1
            while i < len(lines):
                nxt = strip_noise(lines[i]).strip()
                if not nxt or nxt.startswith(("}", "{")) or "(" in nxt:
                    break
                i += 1
            continue
        i += 1


def check_subroutines(text, problems, subroutines):
    """子程序完整性：调用必存在（error）、声明必被调用（warning）。"""
    if not isinstance(subroutines, dict):
        subroutines = {n: 0 for n in subroutines}
    called = {}
    for m in re.finditer(r"调用子程序\(\s*([A-Za-z_]\w*)\s*\)", text):
        called.setdefault(m.group(1), m.start())
        if m.group(1) not in subroutines:
            _add(problems, text, m.start(), "error",
                 "调用子程序(%s) 找不到对应的子程序声明；游戏会报「未知的子程序」" % m.group(1))
    for m in re.finditer(r"子程序\s*;\s*([A-Za-z_]\w*)\s*;", text):
        called.setdefault(m.group(1), m.start())
        if m.group(1) not in subroutines:
            _add(problems, text, m.start(), "error",
                 "事件里的子程序 %s 找不到对应的子程序声明" % m.group(1))
    for name, line in sorted(subroutines.items(), key=lambda x: (x[1] or 0, x[0])):
        if name and name not in called:
            problems.append((line or 0, "warning",
                             "子程序 %s 声明了但从未被调用（调用子程序 / 子程序事件里都没有）" % name))


RULE_BYTE_LIMIT = 100352          # 98KB：游戏诊断面板「每条规则长度不得超过98KB」
ELEMENT_LIMIT = 32768
ELEMENT_WARN = 16384          # 保留：旧档位，不再单独触发提示（见下方 hi 判定）
ELEMENT_HI_RATIO = 1.23       # 与 ws.py cmd_count 的 RATIO_HI 同步（S2b 实测倍率上界）


def check_limits(path, text, problems, sigs=None, labels=None):
    """单条规则字节数上限 + 元素数上限。"""
    for m in re.finditer(r"^\s*规则\(", text, re.M):
        ob = text.find("{", m.end())
        if ob < 0:
            continue
        depth, i = 1, ob + 1
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        size = len(text[m.start():i].encode("utf-8"))
        if size > RULE_BYTE_LIMIT:
            nm = re.search(r'规则\(\s*"([^"]*)"', text[m.start():m.start() + 80])
            _add(problems, text, m.start(), "error",
                 "规则「%s」有 %d 字节，超过单条规则 98KB（%d 字节）上限；"
                 "游戏会报「每条规则长度不得超过98KB」，拆成多条规则"
                 % (nm.group(1) if nm else "?", size, RULE_BYTE_LIMIT))
    try:
        import element_count2 as _ec2          # 实测推导模型：真实文件精度 -3%，旧模型会漏报
        est = _ec2.estimate2(path)
    except Exception:
        try:
            import element_count
            est = element_count.estimate(path, sigs, labels)[0]
        except Exception:
            return
    # 判上限按「最坏上界」判，与 count 的 ⚠ 口径一致（下界/上界见 ws.py cmd_count）。
    # 只按估算值过半就提示，会在 1.6 万元素这种「离上限还远」的文件上误报（S2b 实测：
    # 猪猪钩钩乐 16811 个元素被判「已接近 32768」，纯噪声）。
    hi = int(est * ELEMENT_HI_RATIO) + 1
    if est > ELEMENT_LIMIT:
        problems.append((0, "error",
                         "预计元素数约 %d，超过 32768 上限（估算偏保守，按低估的值算也已经超了）；"
                         "以游戏「显示诊断结果 → 总计元素数量」为准" % est))
    elif hi > ELEMENT_LIMIT:
        problems.append((0, "warning",
                         "预计元素数约 %d，按最坏上界 %d 可能超过 32768（真实值落在上限两侧，只能进游戏核对）；"
                         "以游戏「显示诊断结果 → 总计元素数量」为准" % (est, hi)))


# ---------------------------------------------------------------- 类型层
MIN_ARGS = {"修改全局变量": 3, "修改玩家变量": 4, "设置全局变量": 2, "设置玩家变量": 3}


def _param_type(label):
    """签名里的 `参数名:类型` -> 类型；没有类型标注返回空串。"""
    if ":" in label:
        return label.rsplit(":", 1)[1].strip()
    return ""


PLAYER_EXPR = re.compile(
    r"^(事件玩家|本地玩家|攻击方|被攻击方|主机玩家|本市玩家|玩家|全部玩家|全部|双方|"
    r"队伍1|队伍2|所有队伍|全部队伍)$"
    r"|^(所有玩家|玩家|随机玩家|随机英雄|所有支援英雄|所有输出英雄|所有重装英雄)\(.*\)$")


def _check_arg_type(name, idx, label, arg, pos, problems, text):
    """参数类型硬冲突：只报「玩家槽塞数字」「数值槽塞玩家表达式」这两种。

    其余组合（布尔、选择、变量、向量…）一律不报——数据里的类型标注不全，
    历史上按「必填参数个数」硬查过一次，噪声 71 条，整条撤回了。
    """
    a = arg.strip()
    if not a:
        return
    ptype = _param_type(label)
    slot = "第 %d 个参数" % (idx + 1)
    if ptype == "玩家":
        if re.fullmatch(r"-?\d+(?:\.\d+)?", a) or a in ("真", "假", "True", "False"):
            _add(problems, text, pos, "error",
                 "%s %s 要的是「玩家」（玩家 / 玩家列表），这里填的是 %s；"
                 "游戏会报「之后应有一个玩家」" % (name, slot, a))
        elif a in ("双方", "所有队伍", "全部队伍", "队伍1", "队伍2"):
            _add(problems, text, pos, "error",
                 "%s %s 要的是「玩家」，这里填的是队伍筛选词「%s」——那只用在事件行；"
                 "换成 所有玩家(所有队伍)。游戏会报「之后应有一个值」" % (name, slot, a))
    elif ptype == "数值":
        if PLAYER_EXPR.match(a):
            _add(problems, text, pos, "error",
                 "%s %s 要的是「数值」，这里填的是玩家表达式 %s" % (name, slot, a))


def split_args_pos(s, base=0):
    """按顶层逗号切分参数，同时给出每个参数在原文里的起始偏移。"""
    out, depth, cur, start = [], 0, "", None
    in_str, escaped = False, False
    for idx, ch in enumerate(s):
        if in_str:
            cur += ch
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append((cur, base + (start if start is not None else idx)))
            cur, start = "", None
            continue
        else:
            cur += ch
        if start is None and not ch.isspace():
            start = idx
    if cur.strip() or out:
        out.append((cur, base + (start if start is not None else base)))
    return out


def _var_block_span(text):
    """变量块的 (起, 止) 字符偏移；没有变量块返回 None。"""
    m = re.search(r"^\s*变量\s*$", text, re.M)
    if not m:
        return None
    ob = text.find("{", m.end())
    if ob < 0:
        return None
    depth, i = 1, ob + 1
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return ob, i




STRING_WRAPPERS = {"自定义字符串", "字符串"}


TEAM_VALUES = {"所有队伍", "队伍1", "队伍2"}
# 宽松集：这些词「看着像队伍词」，出现在 Team 参数里要报错。
# 实测（2026-10-23）：`玩家数量(全部)` 游戏报「之后应有一个值」——`全部` / `双方`
# 只在事件块的选择器行里合法，不是队伍值。
TEAM_WORDS = TEAM_VALUES | {"双方", "全部", "队伍"}


_PARAM_TYPES = {"map": None}


def load_param_types(path=None):
    """{元素: {参数序号: 输入类型}}，来自 data/param-options.tsv（权威顺序）。"""
    path = os.path.abspath(path or os.path.join(DATA_DIR, "param-options.tsv"))
    if _PARAM_TYPES["map"] is not None:
        return _PARAM_TYPES["map"]
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                el = (row.get("element") or "").strip()
                if not el:
                    continue
                try:
                    idx = int(row.get("index") or -1)
                except ValueError:
                    continue
                out.setdefault(el, {})[idx] = (row.get("input_type") or "").strip()
    _PARAM_TYPES["map"] = out
    return out


def check_team_slots(text, problems, types=None):
    """类型是 Team 的参数只能填队伍值：所有队伍 / 队伍1 / 队伍2。

    实测两处（2026-10-23）：
      - `玩家数量(全部)` → 游戏报「第48行的"玩家数量("之后应有一个值」
      - `范围内玩家(…, 8, 双方, 关闭)` → 「第 44 行的"8,"之后应有一个值」
    `全部` / `双方` 只在事件块的选择器行里合法，不是队伍值。
    参数类型来自 data/param-options.tsv（signatures 里很多元素只存了参数个数）。
    """
    types = types or load_param_types()
    if not types:
        return
    for fn, imap in types.items():
        slots = [i for i, t in imap.items() if t == "Team"]
        if not slots:
            continue
        for m in re.finditer(r"(?<![\w\u4e00-\u9fa5])" + re.escape(fn) + r"\(", text):
            depth, j = 0, m.end() - 1
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            args = _top_level_args(text[m.end():j])
            for i in slots:
                if i >= len(args):
                    continue
                val = args[i].strip()
                if val in TEAM_VALUES:
                    continue
                # 只抓「裸词写成队伍词的样子」；表达式（对方队伍(…)）是合法的
                if any(ch in val for ch in "()[]. "):
                    continue
                if not (("队伍" in val) or val.startswith(("全部", "双方"))):
                    continue
                line = text.count("\n", 0, m.start()) + 1
                problems.append((line, "error",
                                 "%s 第 %d 个参数是队伍，只能写 所有队伍 / 队伍1 / 队伍2；这里写的是「%s」"
                                 "（`全部` / `双方` 只在事件块的选择器行里用）"
                                 % (fn, i + 1, val)))


def check_hero_slots(text, problems, types=None, heroes=None):
    """类型是 Hero 的参数必须写成 英雄(名字)。

    实测（2026-10-23）：`生成机器人(死神, 队伍1, …)` 游戏报
    「第49行的"生成机器人("之后应有一个值」——裸写英雄名不认，
    语料里一律是 `生成机器人(英雄(破坏球), …)`。
    """
    types = types or load_param_types()
    heroes = heroes if heroes is not None else load_hero_names()
    if not types or not heroes:
        return
    for fn, imap in types.items():
        slots = [i for i, t in imap.items() if t == "Hero"]
        if not slots:
            continue
        for m in re.finditer(r"(?<![\w\u4e00-\u9fa5])" + re.escape(fn) + r"\(", text):
            depth, j = 0, m.end() - 1
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            args = _top_level_args(text[m.end():j])
            for i in slots:
                if i >= len(args):
                    continue
                val = args[i].strip()
                if val not in heroes:
                    continue
                line = text.count("\n", 0, m.start()) + 1
                problems.append((line, "error",
                                 "%s 第 %d 个参数是英雄，要写成 英雄(%s)；裸写英雄名游戏报"
                                 "「\"%s(\"之后应有一个值」" % (fn, i + 1, val, fn)))


def check_bare_var_assign(text, problems):
    """裸变量名赋值：`i = 1;` 应为 `事件玩家.i = 1;` 或 `全局.i = 1;`。

    实测：写成裸名字游戏报「'1);' 之后应有一个值」，指不到真正原因。
    """
    span = _var_block_span(text)
    names = set()
    if span:
        body = text[span[0]:span[1]]
        names = set(re.findall(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*(?://.*)?$", body, re.M))
    for i, raw in enumerate(text.split("\n"), 1):
        st = strip_noise(raw).strip()
        if not st or st.startswith("//"):
            continue
        m = re.match(r"^([A-Za-z_]\w*)\s*[-+*/]?=(?!=)", st)
        if not m:
            continue
        name = m.group(1)
        if name in ("真", "假") or name in names:
            problems.append((i, "error",
                             "变量 %s 不能裸写赋值；要写 事件玩家.%s = …（玩家变量）或 全局.%s = …（全局变量）"
                             % (name, name, name)))


def check_var_slot_bare(text, problems):
    """修改/设置变量类动作的变量槽必须写**裸名**（不带 `全局.` / `事件玩家.` 前缀）。

    实测（E-59，2026-10-24 用户实机）：`修改全局变量(全局.A, 添加至数组, 3)` → 导入报错；
    改成 `修改全局变量(A, 添加至数组, 3)` → 正常。九份真实语料里全部是裸名写法。
    注意跟赋值相反：`全局.A = 3` 才带前缀。
    """
    specs = (("修改全局变量", 0), ("在索引处设置全局变量", 0),
             ("修改玩家变量", 1), ("在索引处设置玩家变量", 1))
    for name, idx in specs:
        for pos, n, args in _iter_calls(text, name):
            if n <= idx:
                continue
            slot = args[idx].strip()
            m = re.match(r"^(全局|玩家|事件玩家|本地玩家|攻击方|被攻击方|所有玩家)\s*[.。]", slot)
            if not m:
                continue
            bare = re.split(r"[.。]", slot, 1)[1] if re.split(r"[.。]", slot, 1)[1:] else slot
            ln = text.count("\n", 0, pos) + 1
            problems.append((ln, "error",
                             "%s 的变量槽要写裸名 `%s`，不能写 `%s`（游戏会拒绝导入，"
                             "报「之后应有一个值」一类）；注意跟赋值相反：`全局.%s = …` 才带前缀"
                             % (name, bare, slot, bare)))


def check_bare_strings(text, problems):
    """字符串作参数时必须包在 自定义字符串(...) 里；裸写 "文本" 游戏不认。

    实测：`记入查看器("[测试] 开始")` 报「"记入查看器("之后应有一个值」。
    单独成行的 "注释" 是合法写法，不受影响（那种行不以 ; 结尾）。
    """
    for line_no, raw in enumerate(text.split("\n"), 1):
        s = raw.strip()
        if not s or s.startswith("//") or not s.endswith(";"):
            continue
        # 先把 自定义字符串("…") 里的字符串摘掉，否则内层引号会被当成裸字符串
        for _ in range(3):
            s2 = re.sub(r'(自定义字符串\()\s*"(?:[^"\\]|\\.)*"', r"\1", s)
            if s2 == s:
                break
            s = s2
        if '"' not in s:
            continue
        for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z_][\w\u4e00-\u9fa5]*)\(", s):
            name = m.group(1)
            if name in STRING_WRAPPERS:
                continue
            i = m.end(); depth = 1
            while i < len(s) and depth > 0:
                if s[i] == "(":
                    depth += 1
                elif s[i] == ")":
                    depth -= 1
                i += 1
            body = s[m.end():i - 1]
            if re.search(r"(^|,)\s*\"", body):
                problems.append((line_no, "error",
                                 "%s 的参数里不能直接写字符串，要包成 自定义字符串(\"…\")" % name))
                break


VICTORY_ACTIONS = ("宣告玩家胜利", "宣告队伍胜利", "宣布比赛为平局")


_SETTING_TYPES = {"map": None}


_MODE_SCHEMAS = {"map": None}


def _load_mode_schemas(path=None):
    """{模式: {schema 名}} —— data/mode-schemas.tsv（21 模式的 schema 组合）。

    用途：判断「某个键写在某个模式块里」是否可能合法——该模式挂载的 schema 里
    只要包含这个键就合法。2026-10-23 T1 实测：死斗挂 008 英雄，英雄页的键写在死斗块内导入通过。
    """
    if _MODE_SCHEMAS["map"] is not None:
        return _MODE_SCHEMAS["map"]
    path = os.path.abspath(path or os.path.join(DATA_DIR, "mode-schemas.tsv"))
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                mode = (row.get("mode") or "").strip()
                raw = (row.get("schemas") or "").strip()
                if not mode or not raw:
                    continue
                names = set()
                for part in raw.split("|"):
                    p = part.strip()
                    if not p:
                        continue
                    if re.fullmatch(r"[0-9A-Fa-f]{12}\.[0-9A-Fa-f]{3}", p):
                        continue      # 少数行写的是 guid，没有名字就跳过（宁可不判）
                    names.add(p)
                # mode-schemas 里的 ow_name 用的是「攻击/护送」这类显示名，统一成块名
                out[mode] = names
    _MODE_SCHEMAS["map"] = out
    return out


def load_setting_types(path=None):
    """{键: {type, on, off, schemas}} —— 来自 data/setting-schemas.tsv。"""
    path = os.path.abspath(path or os.path.join(DATA_DIR, "setting-schemas.tsv"))
    if _SETTING_TYPES["map"] is not None:
        return _SETTING_TYPES["map"]
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r:
                key = (row.get("key") or "").strip()
                if not key:
                    continue
                info = out.setdefault(key, {"type": set(), "schemas": set()})
                info["type"].add((row.get("type") or "").strip())
                info["schemas"].add((row.get("schema") or "").strip())
    _SETTING_TYPES["map"] = out
    return out


_COMPAT = {"set": None}


def load_setting_compat(path=None):
    """实测可用的 (层, 键) 组合，来自 data/setting-compat.tsv。

    归属表是从 schema 推的，会缺；这里记「真实导入验证过」的组合，避免误报。
    """
    path = os.path.abspath(path or os.path.join(DATA_DIR, "setting-compat.tsv"))
    if _COMPAT["set"] is not None:
        return _COMPAT["set"]
    out = set()
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            r = csv.DictReader(f, delimiter="\t")
            for row in r:
                lv = (row.get("层") or "").strip()
                k = (row.get("key") or "").strip()
                if lv and k:
                    out.add((lv, k))
    _COMPAT["set"] = out
    return out


_MAP_TRAITS = {"map": None}

# 这些模式必须有目标点（占领 / 推车 / 攻防 / 推进 / 闪点 / 竞速）
OBJECTIVE_MODES = ("占领要点", "运载目标", "攻击护送", "攻击/护送", "攻防作战", "攻防阵线",
                   "机动推进", "闪点作战", "运载竞速", "勇夺锦旗",
                   "占领要点 6v6", "运载目标 6v6", "攻击护送 6v6", "攻防阵线 6v6",
                   "机动推进 6v6", "闪点作战 6v6")


def load_map_traits(path=None):
    """{地图名: '有'|'无'} —— 来自 data/map-traits.tsv（只收已确认的）。"""
    path = os.path.abspath(path or os.path.join(DATA_DIR, "map-traits.tsv"))
    if _MAP_TRAITS["map"] is not None:
        return _MAP_TRAITS["map"]
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                name = (row.get("map") or "").strip()
                obj = (row.get("objective") or "").strip()
                if name and obj:
                    out[name] = obj
    _MAP_TRAITS["map"] = out
    return out


def load_map_pools(path=None):
    """{模式名: set(地图名)} —— 来自 data/map-pools.tsv（游戏「设置/地图」页截图整理）。"""
    path = os.path.abspath(path or os.path.join(DATA_DIR, "map-pools.tsv"))
    if _MAP_POOLS["map"] is not None:
        return _MAP_POOLS["map"]
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                m = (row.get("mode") or "").strip()
                mp = (row.get("map") or "").strip()
                if m and mp:
                    out.setdefault(m, set()).add(mp)
    _MAP_POOLS["map"] = out
    return out


_MAP_VARIANTS = {"map": None}


def load_map_variants(path=None):
    """{地图名: {编号: 时段名}} —— 来自 data/map-variants.tsv。"""
    path = os.path.abspath(path or os.path.join(DATA_DIR, "map-variants.tsv"))
    if _MAP_VARIANTS["map"] is not None:
        return _MAP_VARIANTS["map"]
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                zh = (row.get("zh") or "").strip()
                vid = (row.get("id") or "").strip()
                if zh and vid:
                    out.setdefault(zh, {})[vid] = (row.get("variant") or "").strip()
    _MAP_VARIANTS["map"] = out
    return out


_KNOWN_CODES = {"codes": None}


def load_known_map_codes():
    """所有“见过”的地图编号：map-codes.tsv + map-codes-derived.tsv + map-variants.tsv。"""
    if _KNOWN_CODES["codes"] is not None:
        return _KNOWN_CODES["codes"]
    out = set()
    for fn in ("map-codes.tsv", "map-codes-derived.tsv"):
        p = os.path.join(DATA_DIR, fn)
        if os.path.isfile(p):
            with open(p, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f, delimiter="\t"):
                    code = (row.get("code") or "").strip()
                    if code:
                        out.add(code)
    p = os.path.join(DATA_DIR, "map-variants.tsv")
    if os.path.isfile(p):
        with open(p, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                vid = (row.get("id") or "").strip()
                if vid:
                    out.add(vid)
    _KNOWN_CODES["codes"] = out
    return out


def check_map_codes(text, problems, strict=False):
    """`启用地图` 每行：`地图名 [时段编号 ...]`（一行一张图，写几个编号 = 开几个时段）。

    实测（2026-10-22 用户手动导出确认）：
        绿洲城 972777519512068154 972777519512068153                      ← 早晨 + 夜晚
        绿洲城 972777519512068292 972777519512068154 972777519512068153   ← 全开

    只写名字 = 用默认时段，一定能导入。
    查两件事，都不看“编号属不属于这张图”（各图时段表不完整，按表判归属会误报：
    真实文件里出现过表里没有的编号，艾兴瓦尔德 972777519512094292）：
    1. 前缀必须是 9727775195…（error 级思路，warning 输出）
    2. 前缀对、但三张编号表里都查不到 → 多半手抄错一位（warning）
       实测（2026-10-23）：8 个真实模式 + 104 个回归样本，除故意的反例外零命中
    """
    known = load_known_map_codes()
    for i, raw in enumerate(text.split("\n"), 1):
        m = re.match(r"^\s*(\S+)((?:\s+\d{10,})+)\s*$", raw)
        if not m:
            continue
        codes = re.findall(r"\d{10,}", m.group(2))
        bad = [x for x in codes if (int(x) >> 52) != 0xD8]
        if bad:
            problems.append((i, "warning",
                             "地图编号 %s 不像工坊编号（应以 9727775195 开头）；"
                             "不确定就只写地图名「%s」" % ("、".join(bad), m.group(1))))
            continue
        unknown = [x for x in codes if known and x not in known]
        if unknown:
            problems.append((i, "warning",
                             "地图编号 %s 不在已知编号表里（可能抄错一位，游戏会拒绝导入）；"
                             "不确定就只写地图名「%s」" % ("、".join(unknown), m.group(1))))

_MAP_POOLS = {"map": None}


def _judge_map(i, mp, mode, problems, traits, pools, strict):
    """单张地图 × 单个模式的判定（check_map_mode 的实际逻辑）。"""
    # 已验证的硬规则优先：无目标点的图 + 目标类模式 = 一定失败（实测报「无效的地图设置」）
    if traits.get(mp) == "无" and mode in OBJECTIVE_MODES:
        problems.append((i, "error",
                         "「%s」没有目标点，不能用于「%s」（游戏会报「无效的地图设置」）；"
                         "改用该模式的默认地图，或换一张有目标点的图" % (mp, mode)))
        return
    if mode in pools and not _in_pool(mp, pools[mode]):
        shown = "、".join(sorted(pools[mode])[:6])
        more = "…" if len(pools[mode]) > 6 else ""
        sev = "error" if strict else "warning"
        problems.append((i, sev,
                         "「%s」在「%s」下选不到（导入会报「尚未选择地图」）；"
                         "该模式可用：%s%s" % (mp, mode, shown, more)))


def _in_pool(mp, pool):
    """地图是否在该模式的池子里——**必须精确命中**。

    池子里的写法就是该模式的唯一合法写法：同一个地区在有的模式里以「整图」出现（突击模式 → 伊利奥斯），
    在有的模式里以「场景」出现（死斗 → 伊利奥斯废墟）。两者不能互相替代：
    2026-10-23 实机，突击模式写 伊利奥斯废墟、死斗写 伊利奥斯，都被游戏拒掉（报「尚未选择地图」）。
    所以不做前缀匹配，否则会把这类真错误静默成通过。
    """
    return mp in pool


def check_map_mode(text, problems, traits=None, pools=None, strict=False):
    """地图是否属于该模式的地图池。

    数据来源：游戏「设置 / 地图」页，每个模式一组，列出该模式可用的图（用户逐组截图）。
    有池子 → 不在池子里：默认 warning（截图可能漏行），`--strict` 升 error。
    没池子 → 退回已验证的硬规则：无目标点的图（工坊空图/训练靶场）不能配目标类模式（error）。

    模式必须按「块栈」跟踪：`禁用 占领要点 { }` 不是当前模式；裸标签行（模式名、`启用地图`）
    与 `{` 分两行，需要 pending 缓冲。

    2026-10-23 修：以前只有「名字 + 时段编号」的行会被检查，**只写地图名（文档推荐的写法）
    会被当成裸标签行缓冲掉**，池子数据实际上从未生效。现在 `启用地图` 块里的一行就是地图，
    不论带不带编号都查。
    """
    traits = traits if traits is not None else load_map_traits()
    pools = pools if pools is not None else load_map_pools()
    if not traits and not pools:
        return
    stack = []
    pending = None
    for i, raw in enumerate(text.split("\n"), 1):
        st = strip_noise(raw).strip()
        if not st or st.startswith("//"):
            continue
        if st.startswith("}"):
            if stack:
                stack.pop()
            continue
        if st.endswith("{") or st.startswith("{"):
            label = st.rstrip("{").strip()
            if not label:
                label = pending or (stack[-1][0] if stack else "")
            parent = stack[-1][0] if stack else None
            is_mode = bool(parent == "模式" and label and not label.startswith("禁用"))
            stack.append((label, is_mode))
            pending = None
            continue
        labels = [l for l, _m in stack]
        modes = [l for l, m in stack if m]
        # 启用地图 块里的一行 = 一张地图（可能带时段编号），只写名字也必须查
        if labels and labels[-1] == "启用地图" and modes:
            _judge_map(i, st.split()[0], modes[-1], problems, traits, pools, strict)
            continue
        if (":" not in st and "：" not in st and ";" not in st and "(" not in st
                and not re.search(r"\s[0-9A-Fa-f]{4,}\.[0-9A-Fa-f]{2,}$", st)
                and not re.search(r"\s\d{3,}$", st)):
            pending = st
            continue
        if "启用地图" not in labels:
            continue
        if not modes:
            continue
        mode = modes[-1]
        m = re.match(r"^([^\s]+)(?:\s+(?:[0-9A-Fa-f]{4,}\.[0-9A-Fa-f]{2,}|\d{6,}))?$", st)
        if not m:
            continue
        _judge_map(i, m.group(1).strip(), mode, problems, traits, pools, strict)



def load_importer_verified(path=None):
    """{ (key, layer): 拒绝理由 } —— 实机确认过「这个键写在这层会被游戏拒绝」。

    数据表 data/importer-verified.tsv：key / layer / mode / result / note / source
    只认 result=rejected 的行；ok 与 unknown 都不动校验。
    """
    path = os.path.abspath(path or os.path.join(DATA_DIR, "importer-verified.tsv"))
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if (row.get("result") or "").strip().lower() != "rejected":
                continue
            key = (row.get("key") or "").strip()
            layer = (row.get("layer") or "").strip()
            if key:
                out[(key, layer)] = (row.get("note") or "").strip()
    return out


def check_importer_verified(text, problems, types=None):
    """实机确认被拒的「键 + 层」组合 → 必改，不再让用户重新试一遍。"""
    table = load_importer_verified()
    if not table:
        return
    types = types or load_setting_types()
    lines = text.split("\n")
    stack, pending = [], None
    for i, raw in enumerate(lines, 1):
        st = strip_noise(raw).strip()
        if not st:
            continue
        if st in BLOCK_KEYWORDS or st.startswith("规则("):
            pending = "规则" if st.startswith("规则(") else st
            if st.endswith("{"):
                stack.append(pending)
                pending = None
            continue
        if st.startswith("{"):
            stack.append(pending if pending else (stack[-1] if stack else None))
            pending = None
            continue
        if st.startswith("}"):
            if stack:
                stack.pop()
            continue
        m = re.match(r"^([^:：]{1,40})\s*[:：]\s*\S", st)
        if not m:
            if st not in BLOCK_KEYWORDS:
                pending = st
            continue
        key = m.group(1).strip()
        layer = stack[-1] if stack else None
        note = table.get((key, layer))
        if note:
            problems.append((i, "error",
                             "「%s」写在「%s」里会被游戏拒绝（实机确认）：%s"
                             % (key, layer, note)))


def check_setting_belongs(text, problems, types=None):
    """设置键必须写在它所属的层里（模式名块 / 综合 / 英雄 / 武器）。

    实测：复生时间属于「英雄」层，丧尸把 复生时间 写进「决斗先锋」块 → 导入报
    「之后应有一个游戏模式设置」。决斗先锋里对应的是「复生时间倍率」。
    """
    types = types or load_setting_types()
    if not types:
        return
    all_schemas = {sc for info in types.values() for sc in info["schemas"] if sc}
    lines = text.split("\n")
    stack, pending = [], None
    for i, raw in enumerate(lines, 1):
        st = strip_noise(raw).strip()
        if not st:
            continue
        if st in BLOCK_KEYWORDS or st.startswith("规则("):
            pending = "规则" if st.startswith("规则(") else st
            if st.endswith("{"):
                stack.append(pending)
                pending = None
            continue
        if st.startswith("{"):
            stack.append(pending if pending else (stack[-1] if stack else None))
            pending = None
            continue
        if st.startswith("}"):
            if stack:
                stack.pop()
            continue
        m = re.match(r"^([^:：]{1,40})\s*[:：]\s*\S", st)
        if not m:
            if st not in BLOCK_KEYWORDS and not st.startswith("{"):
                pending = st
            continue
        key = m.group(1).strip()
        info = types.get(key)
        if not info:
            continue
        layer = stack[-1] if stack else None
        if layer not in all_schemas:
            continue
        if layer == "综合":
            continue          # 综合是通用层：实测 复生时间/随机英雄复生 写在 综合 都合法
        if "综合" in (info.get("schemas") or ()):
            continue          # 属于「综合」的通用键，写在任意模式块里都合法
        if key in COMMON_MODE_KEYS:
            continue          # 语料实测写在任意模式块都能导入（复生时间 / 英雄限制 等）
                              # （真实语料：急救包刷新 / 游戏模式开始 写在 决斗先锋 里能导入）
        if (layer, key) in load_setting_compat():
            continue          # 真实导入验证过的组合
        if layer in info["schemas"]:
            continue
        # 挂在具体模式块下：该模式挂载的 schema 里只要有这个键，就合法
        # （2026-10-23 T1 实测：死斗挂了 008 英雄，英雄页的键写在死斗块内导入通过）
        if layer in _load_mode_schemas():
            if {s for s in info["schemas"] if s} & _load_mode_schemas()[layer]:
                continue
        where = "、".join(sorted(x for x in info["schemas"] if x))
        problems.append((i, "warning",
                         "「%s」属于「%s」层，这里写在「%s」里；语料里没见过这个组合，"
                         "不确定就当它会报「之后应有一个游戏模式设置」"
                         % (key, where, layer)))



EXPORT_NOISE_MARKS = ("导出后写作「无」", "是布尔项，这里写的是")
EXPORT_SUMMARY_MIN = 8      # 攒够这么多条，基本就是整份导出文件，不必逐条刷屏


def collapse_export_noise(problems, path=None):
    """整份文件像「游戏导出的」时，把导出声明的噪声合成一条，并指向 fix。

    导出会改两处：布尔项写显示词（启用/禁用）、某些槽位写「无」。
    逐条报没有意义——用户要做的是先跑 `ws.py fix`，不是手改几十行。
    判定用条数阈值：少量命中仍逐条报（手写文件改起来需要行号）。
    """
    # 布尔项写「禁用/启用」现在是必改（实机确认会整块被拒），不再并进这条提示，
    # 否则 3 处布尔 + 22 处「无」会被合成一条 warning，真正的拦路问题就被藏起来了。
    marks = [m for m in EXPORT_NOISE_MARKS if m not in ("是布尔项",)]
    hits = [p for p in problems if any(m in p[2] for m in marks) and "是布尔项" not in p[2]]
    if len(hits) < EXPORT_SUMMARY_MIN:
        return problems
    rest = [p for p in problems if not (any(m in p[2] for m in marks) and "是布尔项" not in p[2])]
    tip = ("这份文件像是游戏导出的（%d 处槽位写成「无」）："
           "导入前先跑 python tools/ws.py fix 文件 --fix-bools，别手改这 %d 行"
           % (len(hits), len(hits)))
    rest.append((hits[0][0], "warning", tip))
    rest.sort(key=lambda p: (p[0] or 0))
    return rest


_LOBBY_KEYS = {"set": None}


def load_lobby_keys(path=None):
    """大厅键集合（data/lobby-keys.tsv 的 key 列）。大厅键在 .ow 里确实写 是/否。"""
    if _LOBBY_KEYS["set"] is not None:
        return _LOBBY_KEYS["set"]
    path = os.path.abspath(path or os.path.join(DATA_DIR, "lobby-keys.tsv"))
    out = set()
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                k = (row.get("key") or "").strip()
                if k:
                    out.add(k)
    _LOBBY_KEYS["set"] = out
    return out


def check_setting_bools(text, problems, types=None, lobby_keys=None, aliases=None):
    """布尔项在 .ow 里只能写 开启 / 关闭；「禁用/启用」是界面词，「是/否」也不认。

    实测（2026-10-23，一次性探针 W3/W4、W5/W6、W7/W8）：
      · 竞技比赛规则 / 控制点A 写 启用 → 整块被拒；写 开启 → 通过
      · 得分需我方旗帜在基地中 / 闪电赛旗帜位置 写 是 → 被拒；写 开启 → 通过
    大厅键例外：`队列中的玩家可以加入: 是` 是导出原文，大厅块用 是/否。

    该改哪些词由 `data/setting-aliases.tsv` 决定：`kind=export-noise` 是导出显示词（必改），
    `kind=legal` 是「这个词在这个键上合法」（Enum 键上的 禁用），命中就直接放行。
    """
    types = types or load_setting_types()
    if not types:
        return
    lobby_keys = lobby_keys if lobby_keys is not None else load_lobby_keys()
    noise, legal = aliases if aliases else load_setting_aliases(None)
    if not noise:
        noise = dict(ILLEGAL_BOOL_WORDS)
    for i, raw in enumerate(text.split("\n"), 1):
        st = strip_noise(raw).strip()
        m = re.match(r"^([^:：]{1,40})\s*[:：]\s*([^\s]+)\s*$", st)
        if not m:
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        info = types.get(key)
        if not info or "Bool" not in info["type"]:
            continue
        if (key, val) in legal:
            continue          # 例外表：这个词在这个键上是合法选项，不许当成导出噪声
        if val in noise and val not in ("是", "否"):
            # 注意：语料里到处都是 禁用，那是**导出产物**（导出写显示词，导入只认 开启/关闭），
            # 不能拿语料证明「禁用 合法」。详见 docs/settings-map.md 第二节、E-22。

            problems.append((i, "error",
                             "「%s」是布尔项，这里写的是「%s」——导入只认 开启/关闭。"
                             "导出文件里到处都是这类显示词，导入前先跑 ws.py fix 文件 --fix-bools"
                             "（实测 2026-10-23：队伍界面/阵亡镜头 写 禁用 整块被拒，改成 关闭 就通过）"
                             % (key, val)))
        elif val in noise and key not in lobby_keys:
            problems.append((i, "error",
                             "「%s」是布尔项，这里写的是「%s」——导入只认 开启/关闭。"
                             "（实测 2026-10-23：勇夺锦旗的 得分需我方旗帜在基地中 / 闪电赛旗帜位置 "
                             "写「是」被拒，改成 开启 通过；大厅块是另一套，那里可以用 是/否）"
                             % (key, val)))
        elif val not in ("开启", "关闭") and key not in lobby_keys:
            # 既不是合法词也不是已知导出词 —— 布尔项只认两个词，别的写法一定导不进去
            problems.append((i, "error",
                             "「%s」是布尔项，只能写 开启 / 关闭，这里写的是「%s」"
                             "（游戏会报「之后应有一个设置选项」）" % (key, val)))


# 已知「导出会把值吞掉」的键（behavior-notes.tsv 有记录）
KNOWN_SWALLOWED_VALUES = {"招架姿态恢复倍率", "飞空斩击距离"}


def check_empty_setting_values(text, problems):
    """设置行写成 `键:` 但值为空——游戏会报「之后应有一个数字/选项」。

    实测：导出会把某些值吞掉（招架姿态恢复倍率:）。这类键报提示而不是必改：
    文件本身是导出产物，值是被导出弄丢的，补上真实数值即可。
    """
    in_settings = False
    depth = 0
    for i, raw in enumerate(text.split("\n"), 1):
        st = strip_noise(raw).strip()
        if not st:
            continue
        if st == "设置":
            in_settings = True
            depth = 0
            continue
        if not in_settings:
            continue
        if st == "{":
            depth += 1
            continue
        if st == "}":
            depth -= 1
            if depth <= 0:
                in_settings = False
            continue
        if st in ("全局:", "玩家:"):
            continue
        m = re.match(r"^([^:：]{1,40})\s*[:：]\s*$", st)
        if m:
            key = m.group(1).strip()
            if key in KNOWN_SWALLOWED_VALUES:
                problems.append((i, "warning",
                                 "设置项「%s」没有值——导出已知会把它吞掉（behavior-notes 有记录）；"
                                 "补上真实数值即可" % key))
            else:
                problems.append((i, "error",
                                 "设置项「%s」没有值（导出会把某些值吞掉）；游戏会报「之后应有一个数字 / 一个设置选项」"
                                 % key))


def check_balance(text, problems, strict=False, raw_masked=None):
    """全局括号配对（只查括号；`If/While/For` 与 `End;` 的配对检查已撤回）。

    实测：删掉一个右括号，绝大多数校验器抓不到，但游戏直接报错。

    括号数必须在**合并折行之前**的原文上统计：语料里有 `…)),//【点位1】` 这种
    行内注释，合并之后 `//` 会把同行后面的代码一起吃掉，导致少一个括号（假警报）。

    **为什么不再查 End; 配对**（2026-10-24 撤回，E-61）：
      1. 动作块**末尾**的 `End;` 可以合法省略，用结尾的 `}` 代替 —— 9 份真实语料里
         5 份这么写（《暴打大锤3》《猪猪钩钩乐·原版》等，都是能正常玩的模式）。
      2. 旧实现按「行内出现 `While(` / `If(` 的次数」跟 `End;` 数量对账，
         两个方向都会数错（既有「开头 1 个、End 0 个」，也有「开头 2 个、End 3 个」），
         在真实语料上 5/9 误报，超 D-006 门槛。
      3. 真正该记的是行为不是语法：末尾省 `End;` 后，`While` 实测**只执行一次**
         （探针 `probes/lab/endcheck/`，读数 `[e1] A=1` 仅一行）。
         这条写进 `docs/pitfalls-runtime.md`，不再由校验器判。
    """
    masked = raw_masked if raw_masked is not None else mask_text(text)
    opens, closes = masked.count("("), masked.count(")")
    if opens != closes:
        problems.append((0, "error",
                         "括号不配对：左括号 %d 个、右括号 %d 个（删掉一个就会这样）" % (opens, closes)))


def check_victory_in_loop(text, problems):
    """循环里宣告胜利后没有退出（中断/返回），会每秒重复宣告。

    实测：抱团得分模式到 30 分后，日志里每秒都记一条「触发胜利」。
    认可的收尾写法（limits-mutex.tsv「运行时 / 循环里宣告胜负」L3，E-38）：
      1. 宣告后面紧跟 中断 / 返回；
      2. 宣告后把守卫变量置「真」，而循环条件里用的就是那个变量（`循环条件带 全局.ended`）；
      3. 宣告后 等待直到(游戏正在进行中() == 假)（再 中断）。
    块配对要连 `If` 一起记：只记 While/For 的话，循环体里一个 If 的 `End;` 会把
    「在循环里」这个标记提前弹掉，后面的宣告就漏了。
    """
    stack = []          # [("loop", 循环条件原文) | ("block", None)]
    lines = text.split("\n")
    for i, raw in enumerate(lines):
        s = strip_noise(raw).strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("While(") or s.startswith("For(") or re.match(r"^For\s", s):
            stack.append(("loop", s))
        elif s.startswith("If("):
            stack.append(("block", None))
        elif s.startswith("End;"):
            if stack:
                stack.pop()
            continue
        if not any(kind == "loop" for kind, _c in stack):
            continue
        if any(a in s for a in VICTORY_ACTIONS):
            ahead_lines = lines[i + 1:i + 7]
            ahead = "\n".join(ahead_lines)
            if ("中断" in ahead) or ("返回" in ahead) or ("等待直到" in ahead):
                continue
            cond = ""
            for kind, c in reversed(stack):
                if kind == "loop":
                    cond = c or ""
                    break
            guarded = False
            if cond:
                for ga in ahead_lines[:3]:
                    m = re.search(r"([\w\u4e00-\u9fff.]+)\s*=\s*真", strip_noise(ga))
                    if m and m.group(1).split(".")[-1] in cond:
                        guarded = True
                        break
            if not guarded:
                problems.append((i + 1, "warning",
                                 "循环里宣告胜负后没有 中断 / 返回，会每秒重复宣告一次"))


def _iter_rule_blocks(text):
    """-> [(规则名, [(行号, 行)])]；不进入子程序块，够这几条提示用。"""
    out, cur, name = [], None, None
    for i, ln in enumerate(text.split("\n"), 1):
        m = re.match(r'^\s*(?:禁用\s*)?规则\("([^"]*)"\)', ln)
        if m:
            if cur is not None:
                out.append((name, cur))
            name, cur = m.group(1), []
            continue
        if cur is not None:
            cur.append((i, ln))
    if cur is not None:
        out.append((name, cur))
    return out


def _rule_event_lines(body):
    ev, inside = [], False
    for _ln, ln in body:
        s = ln.strip()
        if not inside and s == "事件":
            inside = True
            continue
        if inside:
            if s.startswith("{") or not s:
                continue
            if s.startswith("}"):
                break
            ev.append(s)
    return ev


def _is_ffa_mode(text):
    """模式块里是否是自由混战（死斗）；团队死斗不算。"""
    lines = [(i, ln) for i, ln in enumerate(text.split("\n"))
             if not ln.strip().startswith("//")]
    try:
        k = next(i for i, ln in lines if ln.strip() == "模式")
    except StopIteration:
        return False
    depth, modes = 0, []
    for i, ln in lines:
        if i <= k:
            continue
        t = ln.strip()
        if t == "{":
            depth += 1
            continue
        if t == "}":
            depth -= 1
            if depth <= 0:
                break
            continue
        if depth == 1 and t and ":" not in t and "：" not in t:
            modes.append(t)
    return any(("死斗" in m) and ("团队" not in m) for m in modes)


def check_rule_hints(text, problems):
    """判定表里能给静态提示的三条（E-50 / E-32 / E-49）。

    只报 warning（提示级），不判错。
    **开关在 docs/rules.tsv 的「检查」列**：写 `反例:<检查名>.ow` 就启用，写「不接」就不跑。
    表是开关、这里只有内容——所以改表不用改代码，反过来 selftest 会查漂移。
    误报门槛 D-006：8 份真实语料合计 ≤3 条。
    """
    on = enabled_rule_checks()
    ffa = _is_ffa_mode(text)
    for rname, body in _iter_rule_blocks(text):
        ev = _rule_event_lines(body)
        is_event_rule = bool(ev) and not any(e.startswith("持续") for e in ev) \
            and not any(e.startswith("子程序") for e in ev)
        for ln_no, ln in body:
            s = ln.strip()
            if "event-long-loop" in on and is_event_rule and s.startswith("While(真)"):
                problems.append((ln_no, "warning",
                                 "事件规则「%s」里写了 While(真)：事件规则同一时刻只有一份执行，"
                                 "循环期间来的同类事件会被直接丢弃（E-50）；"
                                 "改成事件里只记标记，循环放到另一条 持续 - 全局 里轮询" % rname))
            if "ffa-bot-team" in on and ffa and "生成机器人(" in s and ("队伍1" in s or "队伍2" in s):
                problems.append((ln_no, "warning",
                                 "死斗里 队伍1/队伍2 没有栏位（栏位数 0），生成机器人会静默失败（E-49）；"
                                 "队伍参数写 所有队伍，位置/方向可写 空"))
        # 循环里只建 HUD 不删：会撞 128 条并存上限
        stack = []
        for ln_no, ln in body:
            s = ln.strip()
            if s.startswith("While(") or s.startswith("For "):
                stack.append([ln_no, []])
                continue
            if s.startswith("End;"):
                if stack:
                    l0, items = stack.pop()
                    blob = " ".join(items)
                    if "hud-rebuild" in on and "创建HUD文本" in blob and "消除HUD文本" not in blob:
                        problems.append((l0, "warning",
                                         "循环里只 创建HUD文本、没先 消除HUD文本：每次创建都新建一条，"
                                         "约 64 秒撞 128 条并存上限后 HUD 停更（E-32）；先删后建"))
                continue
            for fr in stack:
                fr[1].append(s)


def _first_action_stmt(body):
    """规则块里「动作」块的第一条语句 -> (行号, 文本)；没有就 None。"""
    inside = False
    for ln_no, ln in body:
        s = ln.strip()
        if not inside:
            if s == "动作":
                inside = True
            continue
        if not s or s.startswith("{") or s.startswith("//"):
            continue
        if s.startswith("}"):
            return None
        return (ln_no, s)
    return None


def _hud_text_blank(arg):
    """HUD 文本参数是不是「没写东西」：空 / 空 字面量 / 纯空白字符串（含 \\n 占位）。"""
    s = arg.strip()
    if s in ("", "空"):
        return True
    if s.startswith("自定义字符串(") and s.endswith(")"):
        inner = s[len("自定义字符串("):-1]
        for esc in ("\\n", "\\t", "\\r"):
            inner = inner.replace(esc, "")
        return inner.replace('"', "").strip() == ""
    return False


def check_hud_no_text_slots(text, problems):
    """`创建HUD文本` 三个颜色参数都写 `空` → 建出来屏幕上什么都没有（E-34，提示级）。

    为什么要先判「文本是不是空的」：语料里三槽全空的 7 处，标题/副标题/正文都是空、空格或
    一串 \\n 占位（先建成一行、回头再填），报它就是噪声。加上这条后 9 份语料 0 命中
    （S1 打分 + 2026-10-25 本机 corpus 实跑：修前 3 处误报，修后 0）。
    判据只碰结构，不猜类型：第 7/8/9 个参数（标题色/副标题色/文本色）是否都是 `空`。
    """
    for m in re.finditer(r"(?<![\w\u4e00-\u9fa5])创建HUD文本\(", text):
        depth, j = 0, m.end() - 1
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        args = _top_level_args(text[m.end():j])
        if len(args) < 9:
            continue
        if [a.strip() for a in args[6:9]] != ["空", "空", "空"]:
            continue
        if _hud_text_blank(args[3]):
            continue                      # 占位建行：正文没写东西，颜色无所谓
        ln = text.count("\n", 0, m.start()) + 1
        problems.append((ln, "warning",
                         "创建HUD文本 的三个颜色参数都写 空：HUD 建出来屏幕上什么都没有（E-34）；"
                         "颜色显式写 颜色(白色) 之类"))


def check_prestart_damage(text, problems):
    """`持续 - 全局` 规则第一条动作就是 `伤害(...)` → 开赛前打的伤害是 0（E-16，提示级）。

    判定钉死「持续 - 全局」：`持续 - 每名玩家` 在角色出生时重跑，开赛前打 0 血是常见写法
    （语料 5 处），放宽就会误报；再放宽到「持续规则里有伤害且没有门」是 112 处纯噪声（S1 实测）。
    规则里已有 `等待直到(游戏正在进行中` 就算加了门，不报。
    """
    for rname, body in _iter_rule_blocks(text):
        ev = _rule_event_lines(body)
        if not any(e.startswith("持续") and "全局" in e for e in ev):
            continue
        if "等待直到(游戏正在进行中" in "\n".join(ln for _n, ln in body):
            continue
        first = _first_action_stmt(body)
        if first is None:
            continue
        ln_no, stmt = first
        if re.match(r"^伤害\(", stmt):
            problems.append((ln_no, "warning",
                             "规则「%s」是 持续 - 全局，第一条动作就 伤害(...)：比赛开始前伤害无效"
                             "（掉血 0，日志却照打，E-16）；开头加 等待直到(游戏正在进行中(), 999)" % rname))


RULE_CHECKS = {"event-long-loop", "hud-rebuild", "ffa-bot-team"}


def enabled_rule_checks(path=None):
    """从 docs/rules.tsv 的「检查」列读出要跑哪几条表驱动提示。

    - 写 `反例:<检查名>.ow` → 启用那条提示（**文件名就是开关**，反例文件也叫这个名字，
      这样「表说接了」和「反例真的在跑」是同一件事）
    - 写 `停用:反例:<…>` → 已声明但故意关掉（selftest 不会当成漂移）
    - 写 `不接` / `已接:check_xxx` → 跟表驱动提示无关
    `已接(内建)` / 裸检查名是旧写法，`audit_rules.py` 会报错，这里认不出就是关着。
    读不到表时按全开处理（宁可多提示，也不静默失守）。
    """
    try:
        import rules as _rules
        rows = _rules.load(path)
    except Exception:
        return set(RULE_CHECKS)
    if not rows:
        return set(RULE_CHECKS)
    on = set()
    for r in rows:
        for tok in (r.get("检查", "") or "").replace("，", ",").split(","):
            tok = tok.strip()
            if not tok.startswith("反例:"):
                continue
            name = tok[3:].strip()
            if name.endswith(".ow"):
                name = name[:-3]
            if name in RULE_CHECKS:
                on.add(name)
    return on


_ARG_COUNTS = {"map": None}


def load_arg_counts(path=None):
    """语料里每个元素实际写几个参数 -> {元素: (min, max, common)}（E-55）"""
    if _ARG_COUNTS["map"] is not None:
        return _ARG_COUNTS["map"]
    path = os.path.abspath(path or os.path.join(DATA_DIR, "arg-counts-from-corpus.tsv"))
    out = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                el = (row.get("element") or "").strip()
                if not el:
                    continue
                try:
                    out[el] = (int(row["min_args"]), int(row["max_args"]), int(row["most_common_args"]))
                except (KeyError, ValueError):
                    continue
    _ARG_COUNTS["map"] = out
    return out


def _iter_calls(text, name):
    """遍历 name( … ) 调用，产出 (起始位置, 参数个数, 参数列表)。"""
    for m in re.finditer(r"(?<![\w\u4e00-\u9fa5])" + re.escape(name) + r"\(", text):
        depth, j = 0, m.end() - 1
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        args = _top_level_args(text[m.end():j])
        yield m.start(), len(args), args


# 只有「实机验过『签名能省、引擎不收』」的元素才按语料最少参数当约束（E-55）。
# 其他元素只用语料统计当参考，不报（2026-10-24 实测：全量套用会在真实语料上误报 创建地图文本）。
# 这张表是兜底：真值来自 data/param-exceptions.tsv（见 _measured_min_args）。
MEASURED_MIN_ARGS = {"创建效果": 6}


def load_param_exceptions(path=None):
    """data/param-exceptions.tsv → {元素: {"floor": N|None, "optional": [槽位…], "level": "L2"}}。

    只把「引擎实际要求写」里写明 `必须写到 N 个`、且证据等级 L2 的行转成参数个数**下限**（floor）；
    证据等级 L1 的行（语料里省了尾参）只记成「尾参可省」的豁免记录——语料能省不代表别处能省，
    更不能反过来拿它当「必须写这么多」的依据去报错（E-55 就是这么误伤过一次）。
    """
    path = os.path.abspath(path or os.path.join(DATA_DIR, "param-exceptions.tsv"))
    key = ("param-exceptions", path)
    if key in _CACHE:
        return _CACHE[key]
    out = {}
    if os.path.isfile(path):
        for r in csv.DictReader(open(path, encoding="utf-8-sig"), delimiter="\t"):
            el = (r.get("元素") or "").strip()
            if not el:
                continue
            level = (r.get("证据等级") or "").strip()
            required = (r.get("引擎实际要求写") or "").strip()
            entry = out.setdefault(el, {"floor": None, "optional": [], "level": level})
            m = re.search(r"必须写到\s*(\d+)\s*个", required)
            if m and level == "L2":
                entry["floor"] = int(m.group(1))
            elif level == "L1":
                slot = re.search(r"第\s*(\d+)\s*个参数", (r.get("参数") or ""))
                if slot:
                    entry["optional"].append(int(slot.group(1)))
    _CACHE[key] = out
    return out


def _measured_min_args():
    """参数个数下限：真值走 data/param-exceptions.tsv 的 L2 行，读不到用内置兜底。"""
    ex = load_param_exceptions()
    floors = {el: v["floor"] for el, v in ex.items() if v.get("floor")}
    return floors or dict(MEASURED_MIN_ARGS)


def load_legal_words(path=None):
    """data/limits-mutex.tsv 里「类别 = 合法写法」的行 → {(元素, 词)}。

    这些词在**对应槽位**是合法取值，别当成导出噪声去报错：
    `创建效果(…, 无)` 的「无」就是惯用写法（语义是「不覆盖已有效果」），
    而 `创建地图文本` / `创建HUD文本` 的「重新赋值」写「全部禁用」才对。
    表里写的是「`创建效果的「重新赋值: 无」`」这种自然语言，这里按它能解析的部分抽。
    """
    path = os.path.abspath(path or os.path.join(DATA_DIR, "limits-mutex.tsv"))
    key = ("legal-words", path)
    if key in _CACHE:
        return _CACHE[key]
    out = set()
    if os.path.isfile(path):
        for r in csv.DictReader(open(path, encoding="utf-8-sig"), delimiter="\t"):
            if (r.get("类别") or "").strip() != "合法写法":
                continue
            item = (r.get("限制项") or "").strip()
            m = re.match(r"^(?P<els>.+?)\s*的「(?P<param>[^:：]+)[:：]\s*(?P<word>[^」]+)」$", item)
            if not m:
                continue
            word = m.group("word").strip()
            for el in re.split(r"\s*/\s*|\s*、\s*", m.group("els")):
                el = el.strip()
                if el:
                    out.add((el, word))
    _CACHE[key] = out
    return out


def check_arg_counts(text, problems, counts=None):
    """参数个数比实测下限还少的调用 → 提示。

    实测（2026-10-24）：`创建效果(…, 球体, 颜色, 位置, 5)` 只有 5 个参数，
    签名里第 6 个「可以省略」，但游戏报「第113行的"50"之后应有';'」；语料里同一动作全是 6 个。
    只对表里给了硬下限的元素生效（当前只有 `创建效果`）——语料统计只是参考，不当约束用。
    """
    counts = counts if counts is not None else load_arg_counts()
    exceptions = load_param_exceptions()
    optional = {el for el, v in exceptions.items() if v.get("optional")}
    for el, floor in _measured_min_args().items():
        if el in optional:
            continue      # 表里标了「尾参可省」，绝不能因为语料少写就报错（E-55 的反面）
        lo, _hi, common = counts.get(el, (floor, floor, floor))
        lo = max(lo, floor)
        for pos, n, _args in _iter_calls(text, el):
            if n < lo:
                line = text.count("\n", 0, pos) + 1
                problems.append((line, "warning",
                                 "%s 这里写了 %d 个参数，语料里最少写 %d 个（最常见 %d 个）："
                                 "签名允许多省，引擎不一定接受（E-55）" % (el, n, lo, common)))


_ZERO_ARG = {"set": None}


def load_zero_arg_funcs(path=None):
    """无参值函数名单（`上一个文本ID`、`最后创建的实体()` 这类），来自 data/signatures.md。"""
    if _ZERO_ARG["set"] is not None:
        return _ZERO_ARG["set"]
    path = os.path.abspath(path or os.path.join(DATA_DIR, "signatures.md"))
    out = set()
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for line in f:
                m = re.match(r"^([\w\u4e00-\u9fa5“”\"：:]+)\(\)\s*$", line.strip())
                if m:
                    out.add(m.group(1))
    _ZERO_ARG["set"] = out
    return out


BARE_VALUE_HINT = re.compile(r"(?<![\w\u4e00-\u9fa5“”\"])(上一个|最后|当前|首个|随机)[\w\u4e00-\u9fa5]*")


def check_bare_value_names(text, problems, zero=None):
    """裸写的值函数名必须在数据表里存在，且不能带调用括号。

    实测（2026-10-24）：`全局.g4 = 上一个效果ID;` —— 这个函数根本不存在（只有 上一个文本ID /
    上一个伤害调整ID / 最后创建的实体() 等），游戏报「第114行的"上"之后应有';'」，而 check 放过。
    边界处理：前面不能紧贴中文/字母（`玩家造成最后一击` 不算），后面接 `:` 的是设置键（`随机英雄复生:`）。
    """
    zero = zero if zero is not None else load_zero_arg_funcs()
    if not zero:
        return
    for i, raw in enumerate(text.split("\n"), 1):
        s = strip_noise(raw)
        if not s.strip() or s.strip().startswith("//"):
            continue
        if re.match(r"^\s*[\w\u4e00-\u9fa5“”\"]+\s*:", s):   # 设置块的行：键: 值
            continue
        for m in BARE_VALUE_HINT.finditer(s):
            name = m.group(0)
            if name in zero:
                continue
            after = s[m.end():m.end() + 1]
            if after in ("(", ".", "_", ":", "："):          # 调用 / 成员 / 设置键
                continue
            before = s[:m.start()].rstrip()
            if before and before[-1] not in "=,([空 ":
                continue
            problems.append((i, "error",
                             "值函数「%s」不存在（数据表里没有这个名字）；相近的有：%s"
                             % (name, "、".join(sorted(n for n in zero if n.startswith(name[:2]))[:5]) or "（同前缀的也没有）")))


def check_game_end_actions(text, problems):
    """结束比赛的动作要跟模式匹配（官方说明里写死了适用范围）。

    - 宣告玩家胜利：只在自由混战（死斗）生效
    - 宣告队伍胜利 / 宣布比赛为平局：在自由混战无效

    模式名必须取「模式」块里的第一个子块，不能取文件开头任意一行——
    真实文件的 `设置` 里第一个块是「主程序」，曾经因此把模式误判成「主程序」。
    """
    lines = text.split("\n")
    code_lines = [(i, ln) for i, ln in enumerate(lines) if not ln.strip().startswith("//")]
    names = ("宣告玩家胜利", "宣告队伍胜利", "宣布比赛为平局")
    if not any(n in ln for _i, ln in code_lines for n in names):
        return
    modes = []
    try:
        k = next(i for i, ln in code_lines if ln.strip() == "模式")
    except StopIteration:
        return
    depth = 0
    for i, ln in code_lines:
        if i <= k:
            continue
        t = ln.strip()
        if t == "{":
            depth += 1
            continue
        if t == "}":
            depth -= 1
            if depth <= 0:
                break
            continue
        if depth == 1 and t and ":" not in t and "：" not in t:
            modes.append(t)
    ffa = any(("死斗" in m) and ("团队" not in m) for m in modes)
    mode_txt = "、".join(modes) or "该模式"
    bad = ("宣布比赛为平局", "宣告队伍胜利") if ffa else ("宣告玩家胜利",)
    for i, ln in code_lines:
        for name in bad:
            if name in ln:
                problems.append((i + 1, "error",
                                 "「%s」在%s里无效（官方：%s）；%s" % (
                                     name, mode_txt,
                                     "此动作在自由混战模式中无效" if ffa else "此动作只在自由混战模式中生效",
                                     "死斗只能「宣告玩家胜利(某玩家)」" if ffa else "请改用「宣告队伍胜利(队伍)」或「宣布比赛为平局()」")))




def check_rule_semantics(text, problems):
    """两条实测行为：`持续` 规则只跑一次（要循环必须 While + 等待）；While(真) 必须有退出手段。"""
    for m in re.finditer(r"^\s*规则\(\s*\"([^\"]*)\"\)", text, re.M):
        name = m.group(1)
        ob = text.find("{", m.end())
        if ob < 0:
            continue
        depth, i = 1, ob + 1
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body = text[m.start():i]
        ev = re.search(r"事件\s*\{([^}]*)\}", body, re.S)
        acts = body[body.find("动作"):] if "动作" in body else ""
        if ev and "持续" in ev.group(1) and "While(" not in acts.replace(" ", ""):
            line = text.count("\n", 0, m.start()) + 1
            problems.append((line, "warning",
                             "规则「%s」是「持续」事件，但动作里没有 While——持续规则只触发一次，"
                             "要循环必须 While(真) + 等待" % name))
        for w in re.finditer(r"While\(\s*(真|1\s*==\s*1)\s*\)", acts):
            seg = acts[w.start():w.start() + 3000]
            if not re.search(r"(等待|中断|继续|返回|中止)", seg):
                line = text.count("\n", 0, text.find(acts) + w.start()) + 1
                problems.append((line, "warning",
                                 "While(%s) 里没有 等待 / 中断 / 返回，会死循环" % w.group(1)))


def load_dropdowns(path):
    """(元素名, 参数序号) -> 合法选项列表；选项被截断（含「…共」）的不收。"""
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("\t")
        try:
            ie, ii = head.index("element"), head.index("index")
            it, io = head.index("input_type"), head.index("options")
        except ValueError:
            return out
        for line in f:
            c = line.rstrip("\n").split("\t")
            if len(c) <= max(ie, ii, it, io):
                continue
            if c[it].strip() != "Dropdown" or not c[ie].strip():
                continue
            opts = [x.strip() for x in c[io].split("|") if x.strip()]
            if not opts or any("共" in o for o in opts):
                continue
            try:
                out[(c[ie].strip(), int(c[ii]))] = opts
            except ValueError:
                continue
    return out


BARE_WORD = re.compile(r"^[\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5\w]*$")


def load_extensions(path, values_path=None):
    """扩展名 -> 成本；以及 扩展名 -> 解锁的选项集合。"""
    costs, unlocked = {}, {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) >= 2 and c[0].strip():
                    try:
                        costs[c[0].strip()] = int(c[1])
                    except ValueError:
                        pass
    if values_path and os.path.isfile(values_path):
        with open(values_path, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) >= 3 and c[2].strip():
                    unlocked.setdefault(c[2].strip(), set()).add(c[0].strip())
    return costs, unlocked


def check_extensions(text, problems, costs, unlocked=None, base_options=None):
    """扩展块：名字合法性、点数合计、派生上限；以及「用了扩展效果却没开扩展」。"""
    if not costs:
        return
    m = re.search(r"^\s*扩展\s*\n\s*\{", text, re.M)
    enabled = []
    if m:
        ob = text.find("{", m.start())
        cb = text.find("}", ob)
        for raw in text[ob + 1:cb].split("\n"):
            nm = raw.strip()
            if not nm or nm.startswith("//"):
                continue
            if nm not in costs:
                _add(problems, text, text.find(nm, ob), "error",
                     "扩展「%s」不存在；可选：%s" % (nm, "、".join(sorted(costs))))
                continue
            enabled.append(nm)
        used = sum(costs[n] for n in enabled)
        line = text.count("\n", 0, m.start()) + 1
        problems.append((line, "warning",
                         "已用扩展点数 %d（可用点数取决于大厅设置：模式数、地图数、玩家栏位，"
                         "单模式+单地图曾见 16，多模式多地图为 8）；"
                         "皮肤组合上限与机器人上限同样随大厅变化，请以面板「编辑扩展」为准" % used))
    if not unlocked or base_options is None:
        return
    for val, exts in unlocked.items():
        if val in base_options:
            continue                          # 基础游戏也有同名选项，不判
        pos = text.find(val + ")")
        if pos < 0:
            continue
        missing = [e for e in exts if e not in enabled]
        if missing and len(missing) == len(exts):
            line = text.count("\n", 0, pos) + 1
            problems.append((line, "error",
                             "用到「%s」，但它属于扩展「%s」，未在「扩展」块里启用"
                             % (val, "、".join(sorted(exts)))))


def check_dropdown_values(text, problems, dropdowns):
    """下拉参数的取值必须在该参数的可选项里（数据来自 param-docs.tsv）。"""
    if not dropdowns:
        return
    text = strip_comments(text)
    by_elem = {}
    for (elem, idx), opts in dropdowns.items():
        by_elem.setdefault(elem, {})[idx] = opts
    for elem, idx_map in by_elem.items():
        for m in re.finditer(r"(?<![\w\u4e00-\u9fa5])" + re.escape(elem) + r"\(", text):
            depth, j = 0, m.end() - 1
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            body = text[m.end():j]
            args, cur, d, ins = [], "", 0, False
            k = 0
            while k < len(body):
                ch = body[k]
                if ins:
                    cur += ch
                    if ch == '"' and body[k - 1] != "\\":
                        ins = False
                    k += 1
                    continue
                if ch == '"':
                    ins = True
                    cur += ch
                elif ch == "(":
                    d += 1
                    cur += ch
                elif ch == ")":
                    d -= 1
                    cur += ch
                elif ch == "," and d == 0:
                    args.append(cur.strip())
                    cur = ""
                else:
                    cur += ch
                k += 1
            if cur.strip():
                args.append(cur.strip())
            for idx, opts in idx_map.items():
                if idx >= len(args):
                    continue
                val = args[idx]
                if not BARE_WORD.fullmatch(val):
                    continue
                if val in ("真", "假", "空", "无") or val in opts or val in _extension_values():
                    continue
                line = text.count("\n", 0, m.start()) + 1
                problems.append((line, "error",
                                 "%s 第 %d 个参数只能填 %s；这里写的是「%s」"
                                 % (elem, idx + 1, " / ".join(opts), val)))


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
            args = [a for a in text[m.end():j].split(",") if a.strip()]
            if len(args) < need:
                line = text.count(chr(10), 0, m.start()) + 1
                problems.append((line, "error",
                                 "%s 至少要 %d 个参数，这里只有 %d 个" % (name, need, len(args))))


def load_map_names(path):
    """地图名集合（取 maps.tsv 第一列）。"""
    names = set()
    if not os.path.isfile(path):
        return names
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0:
                continue
            col = line.split("\t")[0].strip()
            if col and col.lower() != "unknown":
                names.add(col)
    return names


HUD_ACTIONS = {
    "创建HUD文本", "创建HUD图标", "创建HUD进度条", "大字体信息", "小字体信息",
    "创建地图文本", "创建地图图标", "创建地图进度条", "设置HUD文本", "设置HUD图标",
    "创建效果", "播放效果", "创建光束效果", "创建图标效果", "创建进度条HUD文本",
}


def check_local_values(text, problems):
    """全局变量不能存局部值（本地玩家相关），游戏报「局部值只能用于视觉效果或HUD动作」。

    两种写法都要查：函数式 `设置全局变量(x, …本地玩家…)`，以及裸赋值 `全局.x = …本地玩家…;`
    （2026-10-23 实机：探针里写 `全局.hpBefore = 生命值(本地玩家);` 就是栽在裸赋值这种写法上——
    当时只查了函数式，这行没被拦住，游戏直接报错）。
    """
    seen = set()
    for m in re.finditer(r"(?:设置|修改)全局变量\(([^;\n]*)\)", text):
        body = m.group(1)
        if "本地玩家" not in body:
            continue
        seen.add(m.start())
        _add(problems, text, m.start(), "error",
             "全局变量不能存局部值（含「本地玩家」）；游戏会报"
             "「局部值只能用于视觉效果或HUD动作」，改用玩家变量或 事件玩家")
    for m in re.finditer(r"(?m)^[ \t]*全局\.[A-Za-z_]\w*(?:\[[^\]\n]*\])?\s*=\s*([^;\n]*)", text):
        if "本地玩家" not in m.group(1):
            continue
        if any(abs(m.start() - s) < 3 for s in seen):
            continue
        _add(problems, text, m.start(), "error",
             "全局变量不能存局部值（含「本地玩家」）；游戏会报"
             "「局部值只能用于视觉效果或HUD动作」，改用玩家变量（玩家.xxx）或 事件玩家")



def check_map_names(text, problems, map_names):
    """地图(名) / 启用地图 { 名 GUID } 里的地图必须存在于当前版本地图表。

    游戏更新会删改地图，旧模式里的地图名会失效；游戏只报
    「"地图("之后应有一个地图名称」，指不到根本原因。
    """
    if not map_names:
        return
    for m in re.finditer(r"地图\(\s*([^()\s,;]+)\s*\)", text):
        name = m.group(1)
        if name in map_names or re.fullmatch(r"[\d.]+", name):
            continue
        _add(problems, text, m.start(), "error",
             "地图「%s」不在当前版本地图表里（可能已改名/移除，或是数据表未收录的变体）；"
             "游戏会报「\"地图(\"之后应有一个地图名称」。用 ws.py maps 查有效名" % name)



def check_missing_settings_block(text, problems):
    """只有工坊内容、没有「设置」块 —— 多半是从编辑器「全选复制」拿的。

    房间设置页的「复制设置」才会连 设置块（模式/地图/英雄/大厅）一起导出。
    少了设置块，导入后房间配置会丢，模式可能跑不起来。
    """
    if not re.search(r"^\s*规则\s*\(", text, re.M):
        return
    if re.search(r"^\s*设置\s*$", text, re.M) or re.search(r"^\s*设置\s*\{", text, re.M):
        return
    problems.append((1, "warning",
                     "这份文件只有工坊内容、没有「设置」块——大概是从编辑器「全选复制」拿的；"
                     "要完整模式请回「房间设置」点「复制设置」重新导出"))


def check_missing_var_block(text, problems):
    """用了 全局.X / 玩家.X，但整个文件没有 变量 块。

    **A~Z 是内置变量（全局 / 玩家各 26 个，索引 0~25），不声明也存在。**
    2026-10-24 实机：把 `变量 { 全局: 0: V }` 整段删掉，游戏照样导入成功——
    以前这条对内置字母也报「必改」，把合法文件拦下来了（误报，已修）。
    只有 A~Z 之外的名字才要求声明。
    """
    if re.search(r"^\s*变量\s*$", text, re.M):
        return
    for m in re.finditer(r"(全局|事件玩家|本地玩家|玩家)\.([A-Za-z_]\w*)", text):
        if _is_default_var(m.group(2)):
            continue          # 内置字母变量，不需要声明
        line = text.count("\n", 0, m.start()) + 1
        problems.append((line, "error",
                         "文件里没有「变量」块，但用到了 %s.%s" % (m.group(1), m.group(2))))
        return
    for m in re.finditer(r"(?:设置|修改)(?:全局|玩家)变量\(\s*(?:[^,，]+[,，]\s*)?([A-Za-z_]\w*)", text):
        if _is_default_var(m.group(1)):
            continue
        line = text.count("\n", 0, m.start()) + 1
        problems.append((line, "error",
                         "文件里没有「变量」块，但用到了变量 %s" % m.group(1)))
        return


# 内置字母变量：A=0、B=1 … Z=25（全局 / 玩家各一套）
_BUILTIN_VAR_INDEX = {chr(ord("A") + i): i for i in range(26)}


def check_var_letter_index(text, problems):
    """变量块把内置字母变量绑到别的索引 → 游戏报「变量与另一个变量冲突」。

    2026-10-24 实机：`变量 { 全局: 0: V }` 导入报
    「错误：全局变量“V”与另一个变量冲突」（CASC 原文：全局变量“%1$s”与另一个变量冲突）；
    把这一行删掉照样导入成功。A~Z 内置变量钉在 0~25 号位，名字必须和位号对上
    （A=0、B=1 … V=21），塞到别的位号就撞了。

    索引 ≥26 的字母名不判：真实语料里有 `玩家: 77: S` / `78: E`，那是游戏自己导出来的，
    能导入（见 2026-10-24 语料读数），按「索引不在一等区」放过。
    """
    span = _var_block_span(text)
    if not span:
        return
    body = text[span[0]:span[1]]
    section = None
    for m in re.finditer(r"^[ \t]*(?:(全局|玩家)\s*:|(\d+)\s*:\s*(\w+)\s*$)", body, re.M):
        if m.group(1):
            section = m.group(1)
            continue
        idx_s, name = m.group(2), m.group(3)
        if section not in ("全局", "玩家") or not _is_default_var(name):
            continue
        idx = int(idx_s)
        want = _BUILTIN_VAR_INDEX[name]
        if idx >= len(_BUILTIN_VAR_INDEX) or idx == want:
            continue
        line = text.count("\n", 0, span[0] + m.start()) + 1
        problems.append((line, "error",
                         "%s变量「%s」写在了 %d 号位，但 A~Z 内置变量占 0~25 号位（%s 是 %d）；"
                         "游戏会报「%s变量“%s”与另一个变量冲突」——改成 %d: %s，"
                         "或者直接删掉这一行（A~Z 本来就在）"
                         % (section, name, idx, name, want, section, name, want, name)))


def check_var_refs(text, problems):
    """全局.X / 事件玩家.X 引用的变量必须在变量块对应段落声明过（容忍空行、跳号）。"""
    span = _var_block_span(text)
    if not span:
        return
    body = text[span[0]:span[1]]
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
    # 未声明变量由调用方统一报 warning（这里不再重复报 error）
    for m in re.finditer(r"(?:事件玩家|本地玩家)\.(\w+)", text):
        if _is_default_var(m.group(1)):
            continue          # A~Z 内置变量
        if m.group(1) not in pl:
            _add(problems, text, m.start(), "error",
                 "%s.%s 没有在变量块「玩家:」段声明（A~Z 之外的变量必须先声明）"
                 % (m.group(0).split(".")[0], m.group(1)))


def check_unassigned(text, problems):
    """声明了但从未赋值的变量（会静默保持 0）。warning。"""
    span = _var_block_span(text)
    if not span:
        return
    body = text[span[0]:span[1]]
    decl = {}
    for m in re.finditer(r"^[ \t]*\d+\s*:\s*([A-Za-z_]\w*)\s*$", body, re.M):
        decl.setdefault(m.group(1), span[0] + m.start(1))
    if not decl:
        return
    written = set()
    for pat in (r"(?:设置|修改)全局变量\(\s*(\w+)", r"(?:设置|修改)玩家变量\([^,，]+[,，]\s*(\w+)"):
        written |= set(re.findall(pat, text))
    # 直接赋值写法：全局.X = … / 事件玩家.X += 1 / 所有玩家(所有队伍).X[2] = …
    # 任何 `.变量 = …` 都算赋值——包括间接引用：全局.某玩家.变量 = …（实测真实模式因此误报过两条）
    written |= set(re.findall(r"\.(\w+)(?:\[[^\]]*\])*\s*[-+*/]?=(?!=)", text))
    # For 循环的控制变量由循环本身赋值
    written |= set(re.findall(r"For\s+(?:全局变量|玩家变量)\(\s*(\w+)", text))

    for name, pos in sorted(decl.items(), key=lambda x: x[1]):
        if name not in written:
            _add(problems, text, pos, "warning", "变量 %s 声明了但从未赋值，会一直是 0" % name)



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


def check_types(text, problems, labels=None):
    """按参数类型校验（类型来自 data/signatures.md）。

    覆盖两类高频错：For 控制变量必须先声明；变量当值要写 全局.X。
    """
    declared = set(re.findall(r"^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*(?://.*)?$", text, re.M))
    if not declared:
        return
    # 这些函数的某个参数类型是「变量」，本来就要裸写变量名，不算「当值用」
    var_slot_funcs = {n for n, ls in (labels or {}).items()
                      if any(_param_type(x) == "变量" for x in ls)}
    # For 全局变量 / For 玩家变量：第一个参数必须是已声明的变量
    for m in re.finditer(r"For\s+(全局变量|玩家变量)\(\s*([A-Za-z_]\w*)", text):
        if _is_default_var(m.group(2)):
            continue          # A~Z 内置变量，不需要声明
        if m.group(2) not in declared:
            _add(problems, text, m.start(), "error",
                 "For 循环的控制变量 %s 没有在变量块里声明" % m.group(2))
    # 变量当值：出现在值位置（逗号后）的裸变量名
    for m in re.finditer(r"[，,]\s*([A-Za-z_]\w*)\s*(?=[，,)]|$)", text):
        name = m.group(1)
        if name not in declared:
            continue
        before = text[max(0, m.start() - 60):m.start()]
        if re.search(r"(设置|修改)(全局|玩家)变量\([^,，]*$", before):
            continue                      # 变量目标位，合法
        if re.search(r"For\s+(全局变量|玩家变量)\([^,，]*$", before):
            continue                      # For 的控制变量，本来就是裸写
        fn = re.search(r"([\u4e00-\u9fffA-Za-z_][\w\u4e00-\u9fff]*)\([^()]*$", before)
        if fn and fn.group(1) in var_slot_funcs:
            continue                      # 追踪变量 / 设置变量 这类槽位本来就裸写
        _add(problems, text, m.start(), "error",
             "变量 %s 当值用要写 全局.%s 或 事件玩家.%s" % (name, name, name))



def check_misc(text, problems):
    """吸收自 workshop.codes linter 的其余规则。"""
    # 1) 块结尾 } 后多余分号
    for m in re.finditer(r"\}\s*;", text):
        _add(problems, text, m.start(), "error", "块结尾的 } 后面不能加分号")

    # 2) 地图 id 不能是 0（会导致导入失败）
    lines = text.split("\n")
    offs = _line_offsets(lines)
    for idx, line in enumerate(lines):
        if " 0" not in line:             # 快速排除，别让长行上去回溯
            continue
        m = re.fullmatch(r"[ \t]*([^\s:][^\n:]*?)[ \t]+0[ \t]*", line)
        if not m:
            continue
        if re.search(r"[=()<>!+\-*/]", m.group(0)):
            continue                     # 是表达式/赋值，不是「地图名 id」行
        _add(problems, text, offs[idx], "error", "地图 id 不能是 0：%s" % m.group(1).strip())


    # 3) 变量名只差大小写
    span = _var_block_span(text)
    if span:
        names = re.findall(r"^[ \t]*\d+\s*:\s*([A-Za-z_]\w*)\s*$",
                           text[span[0]:span[1]], re.M)
        groups = {}
        for n in names:
            groups.setdefault(n.lower(), set()).add(n)
        for group in groups.values():
            if len(group) > 1:
                problems.append((0, "warning", "变量名只差大小写，工坊会当成同一个：%s"
                                 % " / ".join(sorted(group))))



def strip_comments(text):
    """去掉 // 行注释与 /* */ 块注释、纯字符串注释行，保留行号与列位置感。

    真实代码里常见：
      /* @SKIP_OBFUSCATE_STRING */      ← 插件注释
      "普通模式"                         ← 字符串注释（写在条件/动作上方）
    """
    # 块注释（可跨行）→ 等长空白
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    text = re.sub(r"/\*.*?\*/", blank, text, flags=re.S)
    out = []
    for line in text.split("\n"):
        idx = line.find("//")
        if idx >= 0:
            line = line[:idx]
        if re.fullmatch(r'\s*"[^"]*"\s*', line):
            line = ""                      # 纯字符串注释行
        out.append(line)
    return "\n".join(out)


def _ends_in_string(line, in_str=False):
    """扫描一行，返回行末是否仍在字符串内（处理 \\ 转义）。"""
    i, escaped = 0, False
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
        i += 1
    return in_str


class SegMap:
    """合并后的 (行, 列) -> 上一层原文的 (行, 列)。

    跨行语句/跨行字符串都是把后续行的内容挪到前面的行上，行号本身不变，
    但报错必须指到内容真正所在的那一行，所以合并时要记下每段的起始列。
    """

    def __init__(self):
        self.segs = {}          # 行号(1 基) -> [(起始列, 源行号, 源行内列偏移)]

    def add(self, line_no, col_start, src_line, src_col=0):
        self.segs.setdefault(line_no, []).append((col_start, src_line, src_col))

    def drop(self, line_no):
        self.segs.pop(line_no, None)

    def locate(self, line_no, col):
        """合并文本的 (行, 列) -> 上一层的 (行, 列)。"""
        segs = self.segs.get(line_no)
        if not segs or col is None:
            return line_no, col
        pick = None
        for seg in segs:                     # segs 按列递增
            if col >= seg[0]:
                pick = seg
            else:
                break
        if pick is None:                     # 列在第一个续行之前 = 起始行自己的内容
            return line_no, col
        return pick[1], col - pick[0] + pick[2]



def join_multiline_strings_mapped(text):
    """把跨行的字符串字面量接回一行（.ow 允许字符串内直接换行）。

    返回 (接好的文本, SegMap)。接好的文本行数与原文一致（续行留空）。
    """
    lines = text.split("\n")
    out, in_str = [], False
    smap = SegMap()
    for idx, line in enumerate(lines):
        if out and in_str:
            col_start = len(out[-1]) + 1                 # 空格之后
            indent = len(line) - len(line.lstrip())
            out[-1] += " " + line.strip()
            smap.add(len(out), col_start, idx + 1, indent)
            out.append("")                               # 原行留空，保持行号
            in_str = _ends_in_string(line, True)
            continue
        out.append(line)
        in_str = _ends_in_string(line, False)
    return "\n".join(out), smap


def join_multiline_strings(text):
    """把跨行的字符串字面量接回一行（.ow 允许字符串内直接换行）。"""
    return join_multiline_strings_mapped(text)[0]


def merge_continuations_mapped(text, max_lines=60):
    """把跨行语句合并到起始行（括号未闭合时继续拼接），后续行留空以保持行号。

    只合并、不改写原文。超过 max_lines 仍未闭合时**放弃合并并还原**——
    宁可让这一处退回逐行检查，也不能把后面整个文件吞进一条语句。
    返回 (合并后的文本, SegMap)，SegMap 用来把报错换算回原文行号。
    """
    lines = text.split("\n")
    out, smap = [], SegMap()
    buf, depth, start, group = None, 0, -1, []
    for idx, line in enumerate(lines):
        code = strip_noise(line)
        if buf is not None:
            group.append(line)
            col_start = len(buf) + 1
            indent = len(line) - len(line.lstrip())
            buf += " " + line.strip()
            smap.add(start + 1, col_start, idx + 1, indent)
            depth += code.count("(") - code.count(")")
            out.append("")
            if depth <= 0 and code.strip().endswith(";"):
                out[start] = buf
                buf, depth, start, group = None, 0, -1, []
            elif len(group) > max_lines:
                smap.drop(start + 1)
                for k, orig in enumerate(group[:max_lines + 1]):
                    if start + k < len(out):
                        out[start + k] = orig
                buf, depth, start, group = None, 0, -1, []
            continue
        d = code.count("(") - code.count(")")
        if d > 0 and not code.strip().endswith(";"):
            buf, depth, start, group = line.strip(), d, len(out), [line]
            out.append("")
        else:
            out.append(line)
    if buf is not None and start >= 0:
        out[start] = buf
    return "\n".join(out), smap


def merge_continuations(text, max_lines=60):
    """把跨行语句合并到起始行（括号未闭合时继续拼接），后续行留空以保持行号。

    只合并、不改写原文。超过 max_lines 仍未闭合时**放弃合并并还原**——
    宁可让这一处退回逐行检查，也不能把后面整个文件吞进一条语句。
    """
    return merge_continuations_mapped(text, max_lines)[0]


def mask_text(text):
    """和 strip_noise 同样的语义，但**保持长度不变**。

    字符串内容、行注释、块注释都替换成等长空格，换行原样保留。
    这样各处报错算出来的列偏移能直接拿去查 SegMap。
    """
    out = []
    i, n = 0, len(text)
    in_str = in_block = in_line = False
    escaped = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
                out.append(ch)
            else:
                out.append(" ")
            i += 1
            continue
        if in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                out.append("  ")
                i += 2
                continue
            out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if in_str:
            if escaped:
                escaped = False
                out.append(" ")
            elif ch == "\\":
                escaped = True
                out.append(" ")
            elif ch == '"':
                in_str = False
                out.append('"')
            else:
                out.append("\n" if ch == "\n" else " ")
            i += 1
            continue
        if ch == "/" and nxt == "/":
            in_line = True
            out.append("  ")
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block = True
            out.append("  ")
            i += 2
            continue
        if ch == '"':
            in_str = True
            out.append('"')
        else:
            out.append(ch)
        i += 1
    return "".join(out)



SUGGESTIONS = [
    (r"第 \d+ 个参数只能填 (.+?)；这里写的是「(.+?)」",
     "把「{1}」换成列表里的一个合法值"),
    (r"个参数是队伍，只能写",
     "队伍值只认 所有队伍 / 队伍1 / 队伍2；「双方」「全部」只能用在事件行"),
    (r"个参数是英雄，要写成 英雄\(", "包一层：英雄(名字)。.ow 里没有裸英雄名"),
    (r"参数里不能直接写字符串",
     "包一层：自定义字符串(\"你的文字\")。注意 .ow 里没有裸字符串"),
    (r"是动作，不能写在条件里",
     "条件里只能写值函数；用 ws.py doc --search 关键词 找对应的值"),
    (r"是值函数（返回一个值），不能单独当动作写",
     "要么赋值给变量（全局.X = 它;），要么套进某个动作里用"),
    (r"在.+里无效（官方",
     "死斗用 宣告玩家胜利(玩家)；团队模式用 宣告队伍胜利(队伍) 或 宣布比赛为平局()"),
    (r"While\(.+\) 里没有 等待",
     "循环体第一行加 等待(0.016, 无视条件); 或 等待(1, 无视条件);，否则每帧空转"),
    (r"声明了但从未赋值",
     "给个初值（规则开头赋一次），或者删掉这个变量"),
    (r"未声明（应在",
     "在 `变量` 块对应段里加一行：`0: 变量名`，索引连续、不要跳号"),
    (r"不在当前版本数据表里",
     "先跑 python tools/ws.py baseline 看数据是否过期；确实改名了就换成本版本的等价名字"),
    (r"变量名只差大小写",
     "改名，工坊把大小写不同的名字当成同一个变量"),
    (r"变量名超过 32 字符",
     "缩短到 32 个字符以内"),
    (r"变量最多 128 个",
     "复用变量：把只在一个规则里用的临时变量合并"),
    (r"^(玩家上限 队伍[12]|观战者人数上限|自由混战人数上限) 的值 \S+ (超出范围|超过上限)",
     "大厅滑杆最右就是 12；外部写更大，导入会报错。两队上限也要合计 ≤ 12（6+6、8+4、12+0）"),
    (r"超出范围（",
     "改成范围内的值；默认值用 python tools/ws.py defaults 设置键名 查"),
    (r"超过上限 ",
     "游戏里滑杆最右就是这个数；外部写更大，导入时会报错"),
    (r"团队模式下 自由混战人数上限 必须写 0",
     "写 0；团队模式不占自由混战栏位，写了数值大厅设置就无效"),
    (r"死斗类模式里 自由混战人数上限 至少 1",
     "死斗写 1 以上（少人数死斗也留 1 个自由混战栏位），或者干脆不写这个键"),
    (r"只写了 玩家上限",
     "另一队也显式写出来（12+0、6+6）；只写一队时另一队按默认 5 人算，单队最多写 7"),
    (r"超过大厅总共",
     "两队上限加起来不能超过 12：6+6、8+4、12+0 都行，7+6 不行；单人模式写 12+0"),
    (r"至少要留 1 个栏位",
     "至少给一队留 1 人；只开一队的话写 12+0 或 1+0，两队都 0 开不了局"),
    (r"是布尔项，只能写 开启 / 关闭",
     "写成 开启 或 关闭，不要写 是/否/true"),
    (r"这个位置要写 全部禁用",
     "写 全部禁用；写「无」导入会失败"),
    (r"至少要 \d+ 个参数|至少需要 1 个参数",
     "参数不够；签名查 python tools/ws.py doc 函数名"),
    (r"参数过多：最多 \d+ 个",
     "删掉多余的参数；下拉类参数通常只有 1-3 个"),
    (r"不接受参数",
     "删掉括号里的内容，写成 函数名()"),
    (r"需要 \d+ 个参数",
     "事件行固定三段：事件名; 队伍; 英雄限制;（全局事件只有一段）"),
    (r"模板里有 \{\d+\}，但只给了",
     "补齐 自定义字符串 后面的值，或者删掉多余的 {n}"),
    (r"没有声明为玩家变量",
     "在 `玩家:` 段声明它，或者改用 全局.变量名"),
    (r"但它属于扩展",
     "在 `设置` 里加一个扩展块：扩展 { 扩展名 }，一行一个、不带冒号"),
    (r"循环里宣告胜负后没有",
     "在宣告动作的下一行加 中断;"),
    (r"要的是「数值」，这里填的是玩家",
     "换成数值表达式，例如 事件玩家.生命值、总计消耗时间、数量(玩家列表)"),
    (r"要的是「玩家」",
     "换成玩家表达式：事件玩家 / 本地玩家 / 所有玩家(所有队伍) / 空"),
    (r"是函数，必须写成",
     "补上括号：名字(...)"),
    (r"超过上限|元素",
     "省元素：publish --obf all 压缩，或把重复写法换成数组 + 循环"),
    (r"规则里不能用 事件玩家",
     "这条规则没有事件上下文：想按玩家算就换成「持续 - 每名玩家」；只想引用某个玩家就用 所有玩家(所有队伍) 或 本地玩家"),
    (r"文件里没有「变量」块", "在文件里加一段：变量 { 全局: 0: 名字 }（A~Z 内置变量不用加）"),
    (r"与另一个变量冲突", "内置 A~Z 占 0~25 号位：把索引改成字母对应的位号，或删掉这行声明"),
    (r"不在当前版本地图表里", "用 python tools/ws.py maps 查现行地图名，或跑 baseline 看数据是否过期"),
    (r"超过单条规则 98KB", "拆成多条规则：每条负责一件事，状态用全局变量传递"),
    (r"找不到对应的子程序声明", "在 子程序 块里定义它：子程序 { 名字 { 动作 { … } } }"),
    (r"循环里宣告胜负后没有", "在宣告动作的下一行加 中断;"),
]


def suggest(msg):
    """给报错配一句「怎么改」。查不到就返回 None，不硬编。"""
    import re as _re
    for pat, tip in SUGGESTIONS:
        m = _re.search(pat, msg)
        if m:
            try:
                return tip.format(*m.groups()) if "{" in tip else tip
            except (IndexError, KeyError, ValueError):
                # 文案里本身带花括号（如 变量 { … }）时不要 format
                return tip
    return None


def _scan_line_quotes(line):
    """数一行里的双引号个数（跳过 // 注释、处理 \\" 转义）。返回 (个数, 是否仍未闭合)。"""
    n, in_str, escaped, i = 0, False, False, 0
    while i < len(line):
        ch = line[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
                n += 1
        else:
            if ch == '"':
                in_str = True
                n += 1
            elif ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                break
        i += 1
    return n, in_str


def check_odd_quotes_raw(raw, problems):
    """逐行双引号奇偶（按物理行，跳过注释）。

    依据：`52840`「文本字符串中出现了换行」——字符串不能跨行，所以单行引号为奇数就是没闭合。
    S7 在 138 个语料样本、19,263 行上实测 **0 行命中**（D-006 门槛内）。
    """
    for i, line in enumerate(raw.replace("\r\n", "\n").split("\n"), 1):
        n, open_str = _scan_line_quotes(line)
        if n % 2:
            problems.append((i, "error",
                             "这一行双引号是奇数（%d 个），字符串没闭合 —— 游戏会报「文本字符串中出现了换行」；"
                             "字符串必须写在一行内" % n))


def check_rule_missing_event_raw(raw, problems):
    """每条规则必须有 事件 块（`51160`「之后的规则没有以事件结尾」）。

    S7 实测：219 个规则块，0 个缺（含 9 份真实语料里能导入的 3 份）。
    """
    name, start, has_event, in_event = None, 0, False, False
    depth = 0
    msg = ("规则「%s」没有 事件 块 —— 游戏会报「…之后的规则没有以事件结尾」；"
           "每条规则都要 事件 { 事件名; 选择器; }")
    for i, line in enumerate(raw.replace("\r\n", "\n").split("\n"), 1):
        s = strip_noise(line).strip()
        if re.match(r'^\s*(?:禁用\s*)?规则\("', line):
            if name is not None and not has_event:
                problems.append((start, "error", msg % name))
            m = re.match(r'^\s*(?:禁用\s*)?规则\("([^"]*)"?', line)
            name, start, has_event, in_event, depth = (m.group(1) if m else "?"), i, False, False, 0
            continue
        if name is None:
            continue
        if s == "子程序" or re.match(r'^\s*子程序\("', line):
            continue
        if not in_event and s == "事件":
            in_event, has_event = True, True
            continue
        if in_event:
            if s.startswith("{"):
                depth += 1
                continue
            if s.startswith("}"):
                depth -= 1
                if depth <= 0:
                    in_event = False
            continue
    if name is not None and not has_event:
        problems.append((start, "error",
                         "规则「%s」没有 事件 块 —— 游戏会报「…之后的规则没有以事件结尾」；"
                         "每条规则都要 事件 { 事件名; 选择器; }" % name))


def check_name_too_long_raw(raw, problems, limit=32):
    """变量名 / 子程序名超过 32 个字符给提示。

    `60206` / `60282` 那族只说明「有过长的名称」，**上限值没测出来**，所以只能是 warning。
    只查变量名与子程序名（语料实测最长 17 / 10）；
    **规则名不查** —— 真实语料里规则名常带「## 」「———」这类排版前缀、动辄 40 字符，
    9 份语料上一查就 20+ 条误报（D-006 门槛 3 条），整条规则名判定撤回。
    """
    text = raw.replace("\r\n", "\n")
    for i, line in enumerate(text.split("\n"), 1):
        m = re.match(r'^\s*子程序\("([^"]*)"', line)
        if m and len(m.group(1)) > limit:
            problems.append((i, "warning",
                             "子程序名「%s」有 %d 个字符，超过 %d —— 引擎有名字长度上限（具体值未验证，"
                             "语料最长 10），建议缩到 20 内" % (m.group(1), len(m.group(1)), limit)))
            continue
        m = re.match(r'^\s*\d+\s*:\s*([A-Za-z_]\w*)\s*$', line)
        if m and len(m.group(1)) > limit:
            problems.append((i, "warning",
                             "变量名「%s」有 %d 个字符，超过 %d —— 见 60206/60282，上限值未验证"
                             % (m.group(1), len(m.group(1)), limit)))


_BOOL_WORDS_CACHE = {}


def load_word_list(checkpoint, data_dir=None):
    """读 data/word-lists.tsv 里某个校验点的合法词（E-71：这些词是从 exe 里读出来的）。

    读不到就返回空列表 —— 检查要**优雅退化**，不能因为缺表把整个 check 崩掉。
    """
    if checkpoint in _BOOL_WORDS_CACHE:
        return _BOOL_WORDS_CACHE[checkpoint]
    words = []
    paths = []
    if data_dir:
        paths.append(os.path.join(data_dir, "word-lists.tsv"))
    paths.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "word-lists.tsv"))
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                hdr = fh.readline().rstrip("\n").split("\t")
                for line in fh:
                    row = dict(zip(hdr, line.rstrip("\n").split("\t")))
                    if row.get("checkpoint") == checkpoint and row.get("words"):
                        words = [w for w in row["words"].split("|") if w]
                        break
        except OSError:
            continue
        if words:
            break
    _BOOL_WORDS_CACHE[checkpoint] = words
    return words


def check_bool_literal_raw(raw, problems, data_dir=None):
    """真假字面量只能写 `真` / `假`。

    依据：exe `0x140C3A760` 只比两条句柄（44089 真 / 44090 假，E-70/E-71），
    合法词表在 `data/word-lists.tsv` 的「真假字面量」行。
    只抓**裸**的 ASCII 真假词（`True` / `False` / `true` / `false`），
    字符串与 `//` 注释已被 `strip_noise` 遮掉，所以不会误报文案里的英文。
    9 份真实语料实测 **0 条**命中。
    """
    legal = load_word_list("真假字面量", data_dir) or ["真", "假"]
    text = raw.replace("\r\n", "\n")
    pat = re.compile(r"(?<![A-Za-z0-9_])(True|False|TRUE|FALSE|true|false)(?![A-Za-z0-9_])")
    for ln, line in enumerate(text.split("\n"), 1):
        code = strip_noise(line)
        for m in pat.finditer(code):
            problems.append((ln, "error",
                             "真假只写 %s，这里写的是「%s」（工坊没有 True/False）"
                             % (" / ".join(legal), m.group(1))))


def full_lint(path, data_dir, strict=False):
    """统一的完整校验入口：加载全部数据表后跑 lint。

    ws.py check 与 publish 都走这里，避免两处检查强度不一致
    （历史上 publish 只传了 event_params，比 check 弱一大截）。
    """
    sigs, labels, settings = load_signatures(os.path.join(data_dir, "signatures.md"))
    # 注：settings.tsv 缺 13 个键，值不校验 —— 试过用 setting-schemas/enum-values 回落，
    # 8 份真实语料新增 3 条误报（例：`首先激活的控制点: 随机` 是合法别名，被当成错），
    # 超 D-006 门槛，已撤回。要接这条得先补别名表（见 docs/limits.md 的已知缺口）。
    return lint(path, sigs, labels, settings,
                event_params=load_event_params(os.path.join(data_dir, "event-params.tsv")),
                bare_ok=load_bare_ok(os.path.join(data_dir, "bare-ok.tsv")),
                kinds=load_element_kinds(os.path.join(data_dir, "element-kinds.tsv")),
                event_param_words=load_event_param_words(os.path.join(data_dir, "event-param-words.tsv")),
                setting_ranges=load_setting_ranges(os.path.join(data_dir, "setting-ranges.tsv")),
                setting_values=load_setting_values(os.path.join(data_dir, "setting-values.tsv")),
                setting_aliases=load_setting_aliases(os.path.join(data_dir, "setting-aliases.tsv")),
                map_names=load_map_names(os.path.join(data_dir, "maps.tsv")),
                dropdowns=load_dropdowns(os.path.join(data_dir, "param-options.tsv")),
                extensions=load_extensions(os.path.join(data_dir, "extensions.tsv"),
                                           os.path.join(data_dir, "extension-values.tsv"))[0],
                extension_values=load_extensions(os.path.join(data_dir, "extensions.tsv"),
                                                 os.path.join(data_dir, "extension-values.tsv"))[1],
                legal_words=load_legal_words(os.path.join(data_dir, "limits-mutex.tsv")),
                strict=strict)


def read_text(path):
    """读文本文件并自动识别编码。返回 (文本, 编码名)。

    中文用户常把文件存成 ANSI(GBK)，按 UTF-8 读会崩或报一堆乱码错。
    gb18030 是 GBK 的超集，优先用它。
    """
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", "replace"), "utf-8(有损坏字符)"


def lint(path, sigs, labels, settings=None, options=None, required=None, event_params=None, bare_ok=None, kinds=None, event_param_words=None, setting_ranges=None, map_names=None, dropdowns=None, strict=False,
              extensions=None, extension_values=None, base_options=None, legal_words=None,
              setting_values=None, setting_aliases=None):
    problems = []
    if legal_words is None:
        legal_words = load_legal_words()
    if setting_values is None:
        setting_values = load_setting_values(os.path.join(DATA_DIR, "setting-values.tsv"))
    if setting_aliases is None:
        setting_aliases = load_setting_aliases(os.path.join(DATA_DIR, "setting-aliases.tsv"))
    settings = settings or {}
    raw, _enc = read_text(path)
    lint.encoding = _enc
    text = raw.replace("\r\n", "\n")
    # 按物理行做的三条（引号奇偶 / 规则缺事件块 / 名字超长）必须看**原始行**，
    # 因为后面会把跨行字符串和跨行语句合并，行号会移位；它们的行号不参与 orig_line 换算。
    raw_probs = []
    check_odd_quotes_raw(text, raw_probs)
    check_rule_missing_event_raw(text, raw_probs)
    check_name_too_long_raw(text, raw_probs)
    check_bool_literal_raw(text, raw_probs, DATA_DIR)
    # 跨行字符串 + 跨行语句都会把内容挪到前一行；两张 SegMap 用来把报错换算回原文行号
    text, s_str = join_multiline_strings_mapped(text)
    text, s_merge = merge_continuations_mapped(text)
    lines = text.split("\n")

    def orig_line(line_no, col=None):
        """合并文本的 (行, 列) -> 原文行号。"""
        if not line_no:
            return line_no
        ln, c = s_merge.locate(line_no, col)
        ln, _c = s_str.locate(ln, c)
        return ln

    stack, pending = [], None
    paren_depth = 0
    var_section = None
    declared = {"全局": set(), "玩家": set()}
    subroutines = {}
    global_rule = False
    in_comment = False

    cond_buf = []
    for ln, line in enumerate(lines, 1):
        code = strip_noise(line)
        stripped = code.strip()
        if stripped in ('""', ''):
            continue                      # 字符串注释行 / 空行

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
                subroutines[stripped.split(":", 1)[1].strip()] = ln
            if not re.match(r"^\d+\s*:", stripped):
                problems.append((ln, "error",
                                 "子程序块里只能写 `索引: 子程序名`（函数体写在规则里，事件用 `子程序;`）：%s"
                                 % stripped))
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
            # 跨行条件：把语句拼完整再判（实测「相距距离(…) > 20」会被折成多行）
            if not stripped.endswith(";"):
                # 2026-10-23 补：括号平衡、本身是个完整条件、上下行都没接着写 → 就是漏了分号
                if (opens <= 0 and COMPARISON.search(stripped)
                        and not _line_continues(stripped)
                        and not _prev_continues(lines, ln - 1)
                        and not _next_continues(lines, ln)):
                    problems.append((ln, "error", "条件行缺少分号"))
                cond_buf.append(stripped)
                continue
            full = " ".join(cond_buf + [stripped]) if cond_buf else stripped
            cond_buf = []
            body = full.rstrip(";").strip()
            if body and not COMPARISON.search(body):
                problems.append((ln, "error", "条件缺少比较运算（== != > < >= <=）"))
            continue

        if stripped.startswith('"') and stripped.endswith('"'):   # 动作块里的纯字符串行 = 注释
            continue

        if block in ("动作", "子程序"):
            # 跨行语句：本行以运算符结尾，或上一行是以运算符结尾（实测真实模式大量使用）
            # 2026-10-23 修：这里原来自带一份正则，转义写坏后变成「匹配任何行尾」，
            # 于是这条检查长期空转（fuzz 里「删掉一个分号」只有 40% 命中率，全靠别的检查兜到）。
            # 现在统一用 _line_continues，并补「下一行以运算符开头」的跨行写法。
            cont_end = _line_continues(stripped)
            prev_cont = _prev_continues(lines, ln - 1)
            next_cont = _next_continues(lines, ln)
            if (not stripped.endswith(";") and not stripped.endswith("{") and opens <= 0
                    and not cont_end and not prev_cont and not next_cont):
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

    masked = mask_text(text)                 # 与 text 等长，列偏移可直接查 SegMap
    if len(subroutines) > 128:
        problems.append((0, "error", "子程序最多 128 个，现在 %d 个" % len(subroutines)))
    for section, names in declared.items():
        if len(names) > 128:
            problems.append((0, "error", "%s变量最多 128 个，现在 %d 个" % (section, len(names))))

    for m in VAR_REF.finditer(masked):
        owner, name = m.group(1), m.group(2)
        section = "全局" if owner == "全局" else "玩家"
        if _is_default_var(name):
            continue          # A~Z 是内置的 26 个变量（索引 0~25），不需要声明
        if name not in declared[section]:
            pos = text.find("%s.%s" % (owner, name))
            line_no = text.count("\n", 0, pos) + 1 if pos >= 0 else 0
            problems.append((line_no, "error",
                             "变量 %s.%s 未声明（应在 `%s:` 段里）" % (owner, name, section)))

    all_vars = declared["全局"] | declared["玩家"]
    hero_names = load_hero_names()
    scan_calls(masked, sigs, labels, problems, options, dropdowns, legal_words)
    check_event_params(masked, event_params or {}, problems, event_param_words)
    check_bare_functions(masked, sigs, problems, bare_ok)
    check_setting_range(text, setting_ranges or {}, problems)
    check_setting_enum_values(text, setting_values or {}, problems)
    check_lobby_team_sum(text, problems)
    check_lobby_ffa_slots(text, problems)
    check_reassign_create(text, problems)
    check_hud_no_text_slots(text, problems)
    check_health_percent_param(text, problems)
    check_speed_percent_param(text, problems)
    check_hero_rule_multiplier(text, problems)
    check_percent_operator(text, problems)
    check_wait_behaviour(masked, problems)
    check_team_word(masked, problems)
    check_hero_enable_layer(text, problems)
    check_maps_not_in_editor(text, problems)
    check_block_layers(text, problems)
    check_mode_names(text, problems)
    check_setting_key_layers(text, problems)
    check_probe_output(path, text, problems)
    check_probe_invisible(path, text, problems)
    check_event_player_scope(text, problems)
    check_local_player_in_global(text, problems)
    check_element_kind(masked, kinds or {}, problems)
    check_action_as_value(masked, kinds or {}, problems)
    check_string_interp(text, problems)
    check_arg_count(masked, problems)
    check_types(masked, problems, labels)
    check_unassigned(masked, problems)
    check_lazy_display(masked, problems)
    check_local_values(text, problems)
    check_dropdown_values(text, problems, dropdowns)
    check_team_slots(text, problems)
    check_hero_slots(text, problems)
    check_bare_var_assign(text, problems)
    check_var_slot_bare(text, problems)
    check_bare_strings(text, problems)
    check_map_codes(text, problems, strict=strict)
    check_map_mode(text, problems, strict=strict)
    check_setting_belongs(text, problems)
    check_importer_verified(text, problems)
    check_setting_bools(text, problems, aliases=setting_aliases)
    check_empty_setting_values(text, problems)
    check_balance(text, problems, strict=strict, raw_masked=mask_text(raw.replace("\\r\\n", "\\n")))
    check_victory_in_loop(text, problems)
    check_prestart_damage(text, problems)
    check_loop_missing_end(text, problems)
    check_rule_hints(text, problems)
    check_arg_counts(text, problems)
    check_bare_value_names(text, problems)
    check_game_end_actions(text, problems)
    if strict:                            # 语义类噪声大（原版 165 条规则命中 94 条），默认关
        check_rule_semantics(text, problems)
    check_extensions(text, problems, extensions, extension_values, base_options)
    check_map_names(text, problems, map_names)
    check_missing_settings_block(text, problems)
    check_missing_var_block(masked, problems)
    check_var_letter_index(text, problems)
    check_var_refs(masked, problems)
    check_misc(masked, problems)
    check_duplicate_blocks(masked, problems)
    # 数据 ID 层：名字必须还在当前版本表里
    check_hero_names(masked, problems, hero_names, all_vars)
    check_button_names(masked, problems, load_button_names())
    check_ability_names(text, problems, set(load_ability_names()) | load_extra_ability_names(), hero_names)
    check_setting_keys(text, problems, load_setting_keys())
    check_event_names(masked, problems, load_event_names())
    # 类型层：完整性 + 上限
    check_subroutines(masked, problems, subroutines)
    check_limits(path, text, problems, sigs, labels)

    if raw.count('"') % 2:
        problems.append((0, "error", "双引号数量是奇数，有字符串没闭合"))

    # 同类提示合并：同一个文件里「英雄页 × 规则 相乘」和「导出吞值」重复三五条时，
    # 逐条报会把真正要注意的东西淹掉（暴打大锤3 一次 7 条、找蛋躲猫猫 2 条同键）。
    def _group(kind, match, summary):
        hit = [p for p in problems if match(p[2])]
        if len(hit) < 3:
            return
        lines = [p[0] for p in hit if p[0]]
        for p in hit:
            problems.remove(p)
        problems.append((lines[0] if lines else 0, "warning",
                         summary % (len(hit), ", ".join(str(x) for x in lines[:8]))))

    _group("mult", lambda m: m.startswith("英雄页") and "× 规则" in m,
           "%d 处「英雄页设置 × 规则设置」同时存在（见第 %s 行）：两者相乘，"
           "只想留一个就把另一边改回 100%%")
    _group("swallow", lambda m: "导出已知会把它吞掉" in m,
           "%d 处设置项没有值（第 %s 行），都是导出吞值的已知缺陷：补上真实数值即可")

    seen, unique = set(), []
    for item in problems:
        line_no, level, msg = item[0], item[1], item[2]
        col = item[3] if len(item) > 3 else None
        if line_no:
            line_no = orig_line(line_no, col)      # 换算回原文行号
        key = (line_no, msg)
        if key in seen:
            continue
        seen.add(key)
        unique.append((line_no, level, msg))
    # 物理行的三条：行号已经是原文行号，不再换算
    for line_no, level, msg in raw_probs:
        key = (line_no, msg)
        if key in seen:
            continue
        seen.add(key)
        unique.append((line_no, level, msg))
    return collapse_export_noise(unique, path)



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
