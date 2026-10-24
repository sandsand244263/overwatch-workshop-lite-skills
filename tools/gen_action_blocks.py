#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「元素 × 块位置」矩阵和「元素清单完备性差集」两张表。

输出（都由本脚本生成，禁止手改）：
    data/action-blocks.tsv
        每个元素能出现在哪些块（事件块 / 持续-全局 / 持续-每名玩家 / 条件块 / 子程序体）
    data/element-completeness.tsv
        现有表 ⇄ 语料的三类差集（动作 / 值 / 设置键）

数据来源：
    data/element-kinds.tsv      元素清单与类型（动作 / 值 / 事件 / 扩展）
    data/element-docs.tsv       官方说明
    data/signatures.md          参数签名（本脚本自己按「名字(…)$」解析，
                                因为 core.load_signatures 会跳过名字里带空格的元素）
    data/param-docs.tsv         每个元素的参数文档条数
    data/arg-counts-from-corpus.tsv  语料里实际写的参数个数（语料派生）
    data/events.tsv             事件清单
    data/settings.tsv           模式/综合 设置键（类型与可写值）
    data/setting-keys.tsv       设置键全集（含英雄页 / 大厅，用来判定「键在哪张表里有」）
    真实语料 <corpus>/*.ow      只在本机读，表里只留出现次数 / 文件个数，不留文件名与内容

块位置的判定（观测，不是推断）：
    事件块         该元素作为某条规则的「事件行」出现（只有事件类元素可能）
    持续-全局      该元素出现在 event = 持续 - 全局 的规则体内（条件区或动作区）
    持续-每名玩家  该元素出现在 event = 持续 - 每名玩家 的规则体内
    条件块         该元素出现在某条规则的 条件 区
    子程序体       该元素出现在 event = 子程序 的规则体内（即子程序体）
    标记为「禁用 」的规则整条跳过（等于注释掉的代码）；「禁用 」开头的单条语句照常计数。

单元格取值：
    是                  语料里观测到（结构证据 L1）
    否(数据:kind=X)     数据侧类型禁止（动作不能进条件区、事件不能当调用……）
    未验证              语料里没观测到，数据侧也没有禁止依据 —— 不能写成「否」

元素类型列：
    动作 / 值 / 事件   取自 data/element-kinds.tsv 的 kind
    条件               值的子集：语料里**只在条件区出现**的布尔值（5 个）。
                       这是位置派生的标签，不是数据类型 —— element-kinds.tsv 里只有「值」。
    扩展（11 个）不进这张表：它们是参数取值组（光束效果 / 弹道……），不是可调用元素，
    只活在参数里；本脚本不解析参数内取值，放进来只会得到一行行「未验证」。

证据等级：
    L1       至少一个位置列是「是」（结构成立，语料里真的这么写过）
    未验证   一个位置都没观测到；元素存在本身是 L0（数据里有），但位置结论不能下

用法：
    python tools/gen_action_blocks.py                       # 语料目录取 local_paths.json
    python tools/gen_action_blocks.py <语料目录>
    python tools/gen_action_blocks.py --check               # 只比对，不写盘；不一致退出 1
    python tools/gen_action_blocks.py --out-dir data/derived
"""
import argparse
import collections
import csv
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import core  # noqa: E402

try:
    import local_paths  # noqa: E402
except Exception:            # 公开仓里可能没有本机路径配置
    local_paths = None

REGIONS = ("事件", "条件", "动作")
DISABLE = "禁用 "                 # 导出文件里「禁用」前缀 = 编辑器里关掉的规则 / 语句
SCOPE_GLOBAL = "持续 - 全局"
SCOPE_PLAYER = "持续 - 每名玩家"
SCOPE_SUB = "子程序"
SETTINGS_ROOT = "设置"
SETTINGS_FAMILY = "模式"          # settings.tsv 覆盖的是 模式/综合 这一层

AB_HEADER = ["元素名", "元素类型", "事件块", "持续-全局", "持续-每名玩家",
             "条件块", "子程序体", "语料出现次数", "数据侧证据", "冲突", "证据等级"]
EC_HEADER = ["类别", "元素名", "差集类型", "出处", "备注"]

DIFF_BOTH = "现有表有·语料有"
DIFF_TABLE_ONLY = "现有表有·语料没有"
DIFF_CORPUS_ONLY = "语料有·现有表没有"
DIFF_ORDER = {DIFF_BOTH: 0, DIFF_TABLE_ONLY: 1, DIFF_CORPUS_ONLY: 2}
CAT_ORDER = {"动作": 0, "值": 1, "条件": 2, "事件": 3, "扩展": 4}


# ---------------------------------------------------------------- 读表

def read_tsv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def read_sig_counts(path):
    """签名里的参数个数：名字允许带空格 / 数字（core.load_signatures 会跳过这种名字）。"""
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line.startswith("<!--") or "(" not in line or not line.endswith(")"):
                continue
            name, rest = line.split("(", 1)
            name = name.strip()
            if not name or name.startswith("#"):
                continue
            inner = rest[:-1].strip()
            out[name] = len(core.split_args(inner)) if inner else 0
    return out


# ---------------------------------------------------------------- 语料扫描

def prep_text(path):
    """复用 core 的解析链：去注释 → 接回跨行字符串 → 合并跨行语句（行号不变）。"""
    text, _enc = core.read_text(path)
    text = core.strip_comments(text.replace("\r\n", "\n"))
    text = core.join_multiline_strings(text)
    return core.merge_continuations(text)


def innermost_region(stack):
    for name in reversed(stack):
        if name in REGIONS:
            return name
    return None


class CorpusScan(object):
    """按块栈扫语料，统计 (元素, 区, 作用域) 的出现次数。

    块栈完全靠「行 → 语句」的栈式归约：名字行在下一行的 `{` 前挂起（pending），
    同一行 `名字 {` 直接入栈；`}` 出栈。这里不重写解析器，字符串与注释交给
    core.strip_noise / core.mask_text 处理（自己写的合并会把字符串抹空、行号错位）。
    """

    def __init__(self, kinds, sig_counts):
        self.kinds = kinds
        self.sig_counts = sig_counts
        zero = sorted([n for n, c in sig_counts.items() if c == 0 and n in kinds],
                      key=len, reverse=True)
        self.bare_re = re.compile(
            r"(?<![\w\u4e00-\u9fa5.])(%s)(?![\w\u4e00-\u9fa5(])"
            % "|".join(map(re.escape, zero))) if zero else None
        self.occ = collections.Counter()          # (元素, 区, 作用域) -> 次数
        self.occ_files = collections.defaultdict(set)   # 元素 -> 出现过的语料文件
        self.event_occ = collections.Counter()    # 事件名 -> 事件行次数
        self.event_files = collections.defaultdict(set)
        self.unknown = collections.Counter()      # (名字, 区) -> 次数：语料里有、表里没有的调用名
        self.unknown_files = collections.defaultdict(set)
        self.keys = collections.Counter()         # 设置键 -> 次数
        self.key_files = collections.defaultdict(set)
        self.key_section = {}                     # 设置键 -> 顶层分区（模式/英雄/大厅…）
        self.rules = 0
        self.disabled_rules = 0
        self.statements = 0
        self.disabled_statements = 0
        self.files = []

    # -- 工具
    def _token_before(self, masked, pos):
        seg = masked[:pos].rstrip()               # `等待直到 (` 这种名字与括号之间有空格
        m = re.search(r"([\u4e00-\u9fa5A-Za-z_][\u4e00-\u9fa5\w]*)$", seg)
        return (m.group(1), m.start(1)) if m else (None, None)

    def _resolve_call(self, masked, pos):
        """( 前面那个名字 → 元素名 / None。支持 For 全局变量、Else If、设置启用技能 1。"""
        tok, tpos = self._token_before(masked, pos)
        if not tok:
            return None
        if tok in self.kinds:
            return tok
        pre = masked[:tpos].rstrip()
        m = re.search(r"([\u4e00-\u9fa5A-Za-z_][\u4e00-\u9fa5\w]*)$", pre)
        if m:
            joined = m.group(1) + " " + tok
            if joined in self.kinds:
                return joined
        return None

    # -- 单个文件
    def scan_file(self, path):
        base = os.path.basename(path)
        self.files.append(base)
        lines = prep_text(path).split("\n")
        stack, pending, rule = [], None, None
        sub_name_next = False
        for raw in lines:
            s = core.strip_noise(raw).strip()
            if not s:
                continue
            if s == "{":
                stack.append(pending if pending else "块")
                pending = None
                continue
            if s.startswith("}"):
                if stack:
                    stack.pop()
                pending = None
                continue
            if s.endswith("{"):
                stack.append(s[:-1].strip())
                pending = None
                continue
            disabled = False
            if s.startswith(DISABLE):
                disabled, s = True, s[len(DISABLE):].strip()
            region = innermost_region(stack)

            if s.startswith("规则(") or s.startswith("规则（"):
                self.rules += 1
                if disabled:
                    self.disabled_rules += 1
                rule = {"events": [], "disabled": disabled}
                pending = "规则"
                continue

            if region is None:
                # 设置树：`键: 值`（启用地图/禁用地图 里是「地图名：变体」，不是设置键）
                if (stack and stack[0] == SETTINGS_ROOT and (":" in s or "：" in s)
                        and "启用地图" not in stack and "禁用地图" not in stack):
                    key = s.replace("：", ":").partition(":")[0].strip()
                    if key:
                        self.keys[key] += 1
                        self.key_files[key].add(base)
                        self.key_section.setdefault(key, stack[1] if len(stack) > 1 else "")
                pending = None if (s.endswith(";") or ":" in s) else s
                continue

            if rule is not None and rule["disabled"]:
                continue

            if region == "事件":
                if sub_name_next:                  # `子程序;` 的下一行是子程序名
                    sub_name_next = False
                    continue
                if rule is not None and not rule["events"]:
                    name = s.rstrip(";").strip()
                    rule["events"].append(name)
                    self.event_occ[name] += 1
                    self.event_files[name].add(base)
                    self.occ_files[name].add(base)
                    if name == SCOPE_SUB:
                        sub_name_next = True
                continue

            # 条件区 / 动作区
            self.statements += 1
            if disabled:
                self.disabled_statements += 1
            if rule and SCOPE_SUB in rule["events"]:
                scope = SCOPE_SUB
            elif rule and rule["events"]:
                scope = rule["events"][0]
            else:
                scope = "无事件"

            masked = core.mask_text(s)
            for m in re.finditer(r"\(", masked):
                name = self._resolve_call(masked, m.start())
                if name:
                    self.occ[(name, region, scope)] += 1
                    self.occ_files[name].add(base)
                else:
                    tok, _ = self._token_before(masked, m.start())
                    if tok and not re.match(r"^\d+$", tok):
                        self.unknown[(tok, region)] += 1
                        self.unknown_files[tok].add(base)
            if self.bare_re is not None:
                for m in self.bare_re.finditer(masked):
                    self.occ[(m.group(1), region, scope)] += 1
                    self.occ_files[m.group(1)].add(base)


def scan_corpus(corpus_dir, kinds, sig_counts, quiet=False):
    scan = CorpusScan(kinds, sig_counts)
    files = sorted(glob.glob(os.path.join(corpus_dir, "*.ow"))) if corpus_dir else []
    for path in files:
        scan.scan_file(path)
    if not quiet:
        print("语料：%d 个 .ow，规则 %d 条（禁用 %d），条件/动作语句 %d 条（禁用 %d）"
              % (len(files), scan.rules, scan.disabled_rules,
                 scan.statements, scan.disabled_statements))
    return scan


# ---------------------------------------------------------------- 表 1：元素 × 块

def _cell(observed, forbidden_reason):
    if observed:
        return "是"
    if forbidden_reason:
        return "否(数据:%s)" % forbidden_reason
    return "未验证"


def build_action_blocks(scan, kinds, docs, sig_counts, core_sigs, param_docs,
                        arg_counts, event_names):
    """元素 × 块矩阵。

    只收 动作 / 值 / 事件 三类。扩展（11 个）是「参数取值组」而不是可调用元素：
    它们只出现在参数位置上，本脚本不解析参数内取值，放进来只会是一行行「未验证」。
    """
    per_element = collections.Counter()
    regions = collections.defaultdict(set)
    scopes = collections.defaultdict(set)
    for (name, region, scope), n in scan.occ.items():
        per_element[name] += n
        regions[name].add(region)
        scopes[name].add(scope)
    for name, n in scan.event_occ.items():
        per_element[name] += n
        regions[name].add("事件")
        scopes[name].add(name)          # 事件行本身就活在这种作用的规则里

    rows = []
    for name in sorted(kinds, key=lambda n: (CAT_ORDER.get(kinds[n], 9), n)):
        kind = kinds[name]
        if kind == "扩展":
            continue
        n = per_element.get(name, 0)
        r = regions.get(name, set())
        sc = scopes.get(name, set())
        n_body = sum(v for (nm, _rg, _s), v in scan.occ.items() if nm == name)

        # 元素类型：值里「语料只在条件区出现」的布尔值单独标成 条件（位置派生，不是数据类型）
        etype = kind
        if kind == "值" and n_body and r == {"条件"}:
            etype = "条件"

        # 「否」只在数据侧类型能定死时写；其余没观测到的一律「未验证」
        cell_event = _cell("事件" in r, None if kind == "事件" else "kind=%s，不是事件" % etype)
        cell_cond = _cell("条件" in r, None if kind == "值" else "kind=%s，条件区只收值" % etype)
        cell_global = _cell(SCOPE_GLOBAL in sc, None)
        cell_player = _cell(SCOPE_PLAYER in sc, None)
        cell_sub = _cell(SCOPE_SUB in sc, None)

        # 数据侧证据
        bits = ["kind=%s" % kind]
        if name in sig_counts:
            bits.append("签名=%d" % sig_counts[name])
        else:
            bits.append("签名=无")
        if name in param_docs:
            bits.append("参数文档=%d" % param_docs[name])
        else:
            bits.append("参数文档=无")
        if name in docs and docs[name].get("description", "").strip():
            bits.append("官方说明=有")
        else:
            bits.append("官方说明=无")
        if name in arg_counts:
            lo, hi, occ = arg_counts[name]
            bits.append("语料参数=%d~%d" % (lo, hi))
        if name in event_names:
            bits.append("events.tsv=有")
        if n:
            bits.append("语料区=%s" % "、".join(sorted(r)))
            if sc:
                scope_list = sorted(sc)
                bits.append("语料作用域=%s%s" % ("、".join(scope_list[:6]),
                                               "…共%d种" % len(scope_list) if len(scope_list) > 6 else ""))
        evidence = "; ".join(bits)

        # 冲突：语料与数据不一致 / 数据内部矛盾
        conflicts = []
        if kind == "动作" and "条件" in r:
            conflicts.append("语料在条件块出现 %d 次，数据标 动作"
                             % sum(v for (nm, rg, _s), v in scan.occ.items()
                                   if nm == name and rg == "条件"))
        if kind == "事件" and n_body:
            conflicts.append("事件类元素出现在条件/动作区 %d 次" % n_body)
        if kind == "扩展" and n:
            conflicts.append("扩展项被当函数调用 %d 次" % n)
        if name in sig_counts and name not in core_sigs:
            conflicts.append("signatures.md 有签名（%d 个参数），core.load_signatures 因名字含空格跳过，"
                             "参数个数/类型检查对该元素失效" % sig_counts[name])
        if name in sig_counts and name in arg_counts and arg_counts[name][0] < sig_counts[name]:
            conflicts.append("语料最少写 %d 个参数 < 签名下限 %d"
                             % (arg_counts[name][0], sig_counts[name]))

        level = "L1" if "是" in (cell_event, cell_cond, cell_global, cell_player, cell_sub) else "未验证"
        rows.append([name, etype, cell_event, cell_global, cell_player, cell_cond,
                     cell_sub, str(n), evidence, "；".join(conflicts) or "-", level])
    return rows


# ---------------------------------------------------------------- 表 2：完备性差集

def build_completeness(scan, kinds, settings_keys, other_key_tables):
    """三类差集：动作 / 值（现有表 = element-kinds.tsv）+ 设置键（现有表 = settings.tsv）。"""
    per_element = collections.Counter()
    for (name, _region, _scope), n in scan.occ.items():
        per_element[name] += n
    # 事件行也算「语料里出现过」
    for name, n in scan.event_occ.items():
        per_element[name] += n

    def nfiles(name):
        return len(scan.occ_files.get(name, ()))

    rows = []

    def add(cat, name, which, source, note=""):
        rows.append([cat, name, which, source, note or "-"])

    # --- 动作 / 值：事件/扩展 不进这张表（另在报告里给数）
    for kind in ("动作", "值"):
        table = sorted(n for n in kinds if kinds[n] == kind)
        for name in table:
            if per_element.get(name, 0):
                add(kind, name, DIFF_BOTH,
                    "element-kinds.tsv；语料 %d 次 / %d 个文件" % (per_element[name], nfiles(name)))
            else:
                add(kind, name, DIFF_TABLE_ONLY, "element-kinds.tsv",
                    "这 %d 份语料里没出现过；不等于元素不存在" % len(scan.files))

    # 语料里有、element-kinds.tsv 里完全没有的调用名（按出现的位置猜类型：进过条件区算值）
    unknown_name = collections.defaultdict(collections.Counter)
    for (name, region), n in scan.unknown.items():
        unknown_name[name][region] += n
    for name in sorted(unknown_name):
        total = sum(unknown_name[name].values())
        cat = "值" if unknown_name[name].get("条件") else "动作"
        add(cat, name, DIFF_CORPUS_ONLY,
            "语料 %d 次 / %d 个文件" % (total, len(scan.unknown_files.get(name, ()))),
            "调用名在 element-kinds.tsv 里没有（区：%s）"
            % "、".join(sorted(unknown_name[name])))

    # --- 设置键：settings.tsv（模式/综合）⇄ 语料 设置/模式 区
    keys_mode = {k for k, sec in scan.key_section.items() if sec == SETTINGS_FAMILY}
    for key in sorted(settings_keys):
        if key in keys_mode:
            add("设置键", key, DIFF_BOTH,
                "settings.tsv；语料 %d 次 / %d 个文件" % (scan.keys[key], len(scan.key_files[key])))
        else:
            add("设置键", key, DIFF_TABLE_ONLY, "settings.tsv",
                "这 %d 份语料只在 设置/模式 下用到 %d 个键，其余模式专属键没被用到"
                % (len(scan.files), len(keys_mode)))
    for key in sorted(keys_mode - settings_keys):
        where = other_key_tables.get(key)
        add("设置键", key, DIFF_CORPUS_ONLY,
            "语料 %d 次 / %d 个文件" % (scan.keys[key], len(scan.key_files[key])),
            ("settings.tsv 无此键；%s 里有" % where) if where else "settings.tsv 与 setting-keys.tsv 都没有")

    rows.sort(key=lambda r: (CAT_ORDER.get(r[0], 9), DIFF_ORDER.get(r[2], 9), r[1]))
    return rows


# ---------------------------------------------------------------- 输出

def dump_tsv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join(x.replace("\t", " ") for x in row) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="生成元素×块矩阵与元素清单完备性差集")
    ap.add_argument("corpus", nargs="?", default=None, help="真实语料目录（*.ow）")
    ap.add_argument("--data", default=os.path.join(ROOT, "data"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "data"))
    ap.add_argument("--check", action="store_true", help="只比对已生成的表，不一致退出 1")
    ap.add_argument("--no-corpus", action="store_true", help="没有语料时只出数据侧（位置列全为未验证）")
    a = ap.parse_args(argv)

    corpus = a.corpus
    if corpus is None and local_paths is not None and not a.no_corpus:
        corpus = local_paths.corpus_dir()
    if corpus and not os.path.isdir(corpus):
        print("语料目录不存在：%s" % corpus)
        return 2
    if not corpus and not a.no_corpus:
        print("没给语料目录，也没有 local_paths.json 的 corpus 配置。\n"
              "块位置只能靠语料观测，没有语料请加 --no-corpus（位置列会全是「未验证」）。")
        return 2

    kinds = {r["name"]: r["kind"] for r in read_tsv(os.path.join(a.data, "element-kinds.tsv"))}
    docs = {r["name"]: r for r in read_tsv(os.path.join(a.data, "element-docs.tsv"))}
    sig_counts = read_sig_counts(os.path.join(a.data, "signatures.md"))
    core_sigs, _labels, _opts = core.load_signatures(os.path.join(a.data, "signatures.md"))
    param_docs = collections.Counter(r["element"] for r in read_tsv(os.path.join(a.data, "param-docs.tsv")))
    arg_counts = {}
    for r in read_tsv(os.path.join(a.data, "arg-counts-from-corpus.tsv")):
        arg_counts[r["element"]] = (int(r["min_args"]), int(r["max_args"]), int(r["occurrences"]))
    event_names = {r["event"] for r in read_tsv(os.path.join(a.data, "events.tsv"))}
    setting_rows = read_tsv(os.path.join(a.data, "settings.tsv"))
    settings_keys = {r["key"].strip() for r in setting_rows if r["key"].strip()}
    empty_setting_keys = len(setting_rows) - sum(1 for r in setting_rows if r["key"].strip())
    other_key_tables = {}
    for r in read_tsv(os.path.join(a.data, "setting-keys.tsv")):
        src = "setting-keys.tsv(source=%s)" % r.get("source", "?")
        if r["key"] not in other_key_tables or src < other_key_tables[r["key"]]:
            other_key_tables[r["key"]] = src

    scan = scan_corpus(corpus, kinds, sig_counts, quiet=a.check)
    if not corpus:
        print("！--no-corpus：没有任何语料，位置列会全是「未验证」，"
              "差集里的「现有表有·语料没有」只是「没查过」，不代表表缺东西。"
              "这种输出别写进共享的 data/。")

    ab_rows = build_action_blocks(scan, kinds, docs, sig_counts, core_sigs,
                                 param_docs, arg_counts, event_names)
    ec_rows = build_completeness(scan, kinds, settings_keys, other_key_tables)

    ab_path = os.path.join(a.out_dir, "action-blocks.tsv")
    ec_path = os.path.join(a.out_dir, "element-completeness.tsv")

    if a.check:
        import io
        buf = io.StringIO()
        buf.write("\t".join(AB_HEADER) + "\n")
        for row in ab_rows:
            buf.write("\t".join(row) + "\n")
        want_ab = buf.getvalue()
        buf = io.StringIO()
        buf.write("\t".join(EC_HEADER) + "\n")
        for row in ec_rows:
            buf.write("\t".join(row) + "\n")
        want_ec = buf.getvalue()
        bad = 0
        for path, want in ((ab_path, want_ab), (ec_path, want_ec)):
            if not os.path.isfile(path):
                print("✗ 缺表：%s" % os.path.basename(path))
                bad += 1
                continue
            with open(path, encoding="utf-8", newline="") as f:
                got = f.read().replace("\r\n", "\n")
            if got != want:
                print("✗ 与重新生成的结果不一致：%s" % os.path.basename(path))
                bad += 1
            else:
                print("✓ %s 与重新生成的结果一致" % os.path.basename(path))
        print("表核对：%s" % ("通过" if not bad else "%d 张不一致" % bad))
        return 0 if not bad else 1

    if not os.path.isdir(a.out_dir):
        os.makedirs(a.out_dir)
    dump_tsv(ab_path, AB_HEADER, ab_rows)
    dump_tsv(ec_path, EC_HEADER, ec_rows)

    # ---- 汇报用的关键数字
    covered = {name for (name, _r, _s) in scan.occ}
    covered |= set(scan.event_occ)
    by_kind = collections.Counter(kinds[n] for n in kinds)
    print("写入 %s（%d 行）、%s（%d 行）" % (ab_path, len(ab_rows), ec_path, len(ec_rows)))
    if empty_setting_keys:
        print("注意：settings.tsv 有 %d 行键名为空（生成器丢了键名），已从设置键对比里跳过"
              % empty_setting_keys)
    print("现有表元素：动作 %d / 值 %d / 事件 %d / 扩展 %d（合计 %d）"
          % (by_kind["动作"], by_kind["值"], by_kind["事件"], by_kind["扩展"], len(kinds)))
    print("语料覆盖元素 %d 个；从未出现 %d 个" % (len(covered), len(kinds) - len(covered)))
    print("语料里调用名不在表中的元素：%d 个" % len(scan.unknown_files))
    for name in sorted(scan.unknown_files, key=lambda n: -sum(v for (nm, _r), v in scan.unknown.items() if nm == n))[:10]:
        print("    %s ×%d" % (name, sum(v for (nm, _r), v in scan.unknown.items() if nm == name)))
    cnt = collections.Counter((r[0], r[2]) for r in ec_rows)
    print("差集条数：")
    for cat in ("动作", "值", "设置键"):
        print("    %-4s 现有表有·语料有 %3d / 现有表有·语料没有 %3d / 语料有·现有表没有 %3d"
              % (cat, cnt[(cat, DIFF_BOTH)], cnt[(cat, DIFF_TABLE_ONLY)], cnt[(cat, DIFF_CORPUS_ONLY)]))
    only_corpus = [r for r in ec_rows if r[2] == DIFF_CORPUS_ONLY]
    print("只在语料里出现的元素 %d 个：%s"
          % (len(only_corpus), "、".join(r[1] for r in only_corpus) or "无"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
