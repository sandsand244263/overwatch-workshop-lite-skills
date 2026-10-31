# -*- coding: utf-8 -*-
"""生成四张「元素事实表」——默认值 / 下拉别名 / 参数例外 / 上限互斥。

为什么需要：这四类事实以前散在 docs/*.md 的散文里，agent 只能靠读文档记，
查不了、也没法被脚本消费。这里把「能机器判定的部分」全部从数据表 + 语料重新算出来，
把「只能靠实机的地方」按证据等级显式标注，让下游（校验器/写作）知道哪条能当结论。

用法：
  python tools/gen_element_facts.py                # 全量重算，写 data/ 四张表
  python tools/gen_element_facts.py --no-corpus    # 没有语料也能跑（语料相关列留空、反向例外降为 0）
  python tools/gen_element_facts.py --check        # 只算不写，和磁盘上的表比对是否漂移
                                                  # 没语料时 defaults-full / dropdown-aliases 自动跳过（语料列复算不了）

产物（全部本脚本生成，禁止手改）：
  data/defaults-full.tsv      元素参数默认值全集（官方文档 ⇄ defaults.tsv ⇄ 语料对账）
  data/dropdown-aliases.tsv   下拉/布尔/队伍/英雄槽的规范取值、别名、扩展独占
  data/param-exceptions.tsv   签名可省但引擎要写（含反向：签名要写但引擎收少写）
  data/limits-mutex.tsv       硬上限、百分比语义、合法写法、互斥对

证据等级（沿用 SKILL.md 的 L0~L3，本表只用到低三档）：
  L2 = 有过实机（导入被拒/导入成功/有读数）
  L1 = 两源一致（数据表 + 语料同向，或数据表 + 结构推断），未实机
  L0 = 单源（只有文档、只有数据、只有语料），不能当结论

语料只在本机读，路径从 local_paths.json 取。语料内容不进表：出去的只有计数和
「游戏固定词表里的取值」（真/假/球体/事件玩家 这类）；字符串字面量统一显示成 `"…"`，
变量名等自定义标识显示成「已隐去」。
"""
import argparse
import collections
import csv
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, HERE)
import core  # noqa: E402

# ----------------------------------------------------------------- 基础工具


def load_tsv(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def cell(s):
    """单元格消毒：去换行与制表符，避免把表结构搞坏。"""
    if isinstance(s, int):
        s = str(s)
    return re.sub(r"[\t\r\n]+", " ", (s or "").strip())


def render_tsv(header, rows):
    """把表渲染成文本（不带 BOM、LF 换行，与其他 data/*.tsv 一致）。"""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow([cell(x) for x in r])
    return buf.getvalue()


def read_json(path):
    try:
        return json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ----------------------------------------------------------------- 语料扫描
# 只读语料做统计，不复制内容：出去的只有计数与游戏固定词表里的取值。

# 语料里「'最常见取值'」可能是别人模式里的自定义变量名（bothero_guolv 这种）——
# 语料一律不外传，所以含 ASCII 标识符的取值只报「已隐去」，不进表。
IDENT_RE = re.compile(r"[A-Za-z_\[\]]")


def safe_corpus_value(v):
    if not v:
        return ""
    if IDENT_RE.search(v):
        return "(含自定义标识，已隐去)"
    return v


def corpus_dir_from_paths():
    p = read_json(os.path.join(ROOT, "local_paths.json")).get("corpus") or ""
    return p if p and os.path.isdir(p) else ""


def scan_corpus(dirpath, names):
    """返回 {元素: {"calls": 调用数, "argc": Counter, "vals": {序号: Counter}}}。

    只在 mask_text 后的文本上扫描：字符串内容与注释被抹成空格，所以
    (1) 注释里的 `传送(12) —— 说明文字` 不会被当成真调用（未 mask 时 传送 会多出 1 条 1 参数假样本）；
    (2) 别人模式里的字符串字面量不会流进表（语料不外传，见 corpus/README.md）。
    参数取值也从 mask 文本取，因此字符串参数显示为 `"…"`，只有代码标识（变量/元素名）可见。
    """
    pat = re.compile(r"(?<![\w\u4e00-\u9fa5])(" +
                     "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) +
                     r")\(")
    out = collections.defaultdict(lambda: {"calls": 0, "argc": collections.Counter(),
                                           "vals": collections.defaultdict(collections.Counter)})
    files = [f for f in sorted(os.listdir(dirpath)) if f.endswith(".ow")]
    used = []
    for fn in files:
        text, _enc = core.read_text(os.path.join(dirpath, fn))
        text = text.replace("\r\n", "\n")
        # 只认 mask 文本：不依赖「等长」约定（转义序列会让长度变短，早期版本因此
        # 退回未抹除的原文，把别人的字符串字面量带进了表）——见 2026-10-24 自查。
        mask = core.mask_text(text)
        for m in pat.finditer(mask):
            name = m.group(1)
            depth, j = 1, m.end()
            while j < len(mask) and depth:
                c = mask[j]
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                j += 1
            body = mask[m.end():j - 1]
            args = core.split_args_pos(body, base=m.end())
            rec = out[name]
            rec["calls"] += 1
            rec["argc"][len(args)] += 1
            for idx, (raw, _off) in enumerate(args):
                # 取值一律从 mask 文本里取：字符串内容已被抹成空格，所以别人模式里的
                # HUD 文案 / 自定义字符串不会进表（语料不外传）。变量名等代码标识
                # 仍然可见，输出时再由 safe_corpus_value 隐去。
                tok = re.sub(r'"[ \t]*"', '"…"', raw.strip())
                tok = re.sub(r"\s+", " ", tok).strip()
                rec["vals"][idx][tok] += 1
        used.append(fn)
    return out, used


# ------------------------------------------------------- 1. 默认值全集
# 默认值性质分三档，反例数只对「字面值」有意义：
#   字面值    真/假/上一个文本ID/最后创建的实体 —— 语料里写别的值就是一次反例（覆盖）
#   类型占位  数字/矢量/事件玩家/空 —— 只是「这个槽要填什么类型」，写什么都不会是反例
#   下拉默认档 导出没记默认档，只能取选项表首项（推断，未验证）
LITERAL_EXACT = {"真", "假"}
LITERAL_PREFIX = ("上一个", "最后创建", "最后创建的生命池", "当前数组元素")

DEFAULT_SOURCE_DOC = "官方文档"
DEFAULT_SOURCE_CORPUS = "语料统计"
DEFAULT_SOURCE_NONE = "无"


def default_kind(d):
    if not d:
        return "无记录"
    if d in LITERAL_EXACT or d.startswith(LITERAL_PREFIX):
        return "字面值"
    return "类型占位"


def build_defaults_full(pdocs, dtsv, edocs, corpus):
    kinds = {}
    for r in edocs:
        nm = (r.get("name") or "").strip()
        kd = (r.get("kind") or "").strip()
        if nm and kd:
            kinds.setdefault(nm, kd)
    # 每个元素的参数个数（文档写「尾部参数可以省略」只对最后一位成立）
    total = {}
    for r in pdocs:
        try:
            i2 = int(r["index"])
        except (KeyError, ValueError):
            continue
        el2 = (r["element"] or "").strip()
        total[el2] = max(total.get(el2, 0), i2 + 1)

    alt = {}
    for r in dtsv:
        try:
            alt[(r["func"], int(r["param_index"]))] = (r["default"] or "").strip()
        except (KeyError, ValueError):
            continue
    rows = []
    stats = collections.Counter()
    for r in pdocs:
        el = (r["element"] or "").strip()
        try:
            idx = int(r["index"])
        except (KeyError, ValueError):
            continue
        pname = (r["name"] or "").strip() or "_(无参数名)"
        ptype = (r["input_type"] or "").strip()
        doc = (r["default"] or "").strip()
        first_opt = ""
        opts = [o.strip() for o in (r["options"] or "").split("|") if o.strip()]
        if opts:
            first_opt = opts[0]

        notes = []
        ekind = kinds.get(el, "")
        if ekind and (r["kind"] or "").strip() and ekind != (r["kind"] or "").strip():
            notes.append("element-docs 记为「%s」，param-docs 记为「%s」" % (ekind, r["kind"]))
        # defaults.tsv 对账：两边记法不同（""/（无）、""/（下拉默认档））算一致
        a = alt.get((el, idx), None)
        if a is not None:
            norm_a = "" if a == "（无）" else a
            norm_doc = "" if doc == "（无）" else doc
            if norm_a == "（下拉默认档）" and not norm_doc:
                pass
            elif norm_a != norm_doc:
                notes.append("defaults.tsv 记为「%s」，与 param-docs「%s」不一致" % (a, doc or "（空）"))
        else:
            notes.append("defaults.tsv 无此行")

        if not doc or doc == "（无）":
            if ptype == "Dropdown" and first_opt:
                value, kind, src = first_opt, "下拉默认档", DEFAULT_SOURCE_DOC
                notes.append("导出未记默认档，取选项表首项（推断，未验证）")
                level = "L0"
            else:
                value, kind, src, level = "(无记录)", "无记录", DEFAULT_SOURCE_NONE, "L0"
        elif doc == "（下拉默认档）":
            value, kind, src, level = (first_opt or "(无记录)"), "下拉默认档", DEFAULT_SOURCE_DOC, "L0"
            if first_opt:
                notes.append("导出未记默认档，取选项表首项（推断，未验证）")
        else:
            value, kind, src = doc, default_kind(doc), DEFAULT_SOURCE_DOC
            level = "L1" if kind == "字面值" else "L0"

        rec = corpus.get(el) if corpus else None
        written = 0
        top_val, top_n = "", 0
        if rec:
            written = sum(n for c, n in rec["argc"].items() if c > idx)
            cnt = rec["vals"].get(idx) or {}
            if cnt:
                top_val, top_n = max(cnt.items(), key=lambda kv: (kv[1], kv[0]))
        counter_ex = ""
        if kind == "字面值" and written:
            cnt = (rec["vals"].get(idx) or {})
            counter_ex = str(sum(n for v, n in cnt.items() if v != value))
            if counter_ex == "0":
                notes.append("语料 %d 处写的都是默认值本身（文档与语料一致）" % written)
            else:
                notes.append("语料 %d 处里 %s 处显式写了别的值——导出会把参数写满，属正常覆盖，"
                             "不构成对默认值的反驳" % (written, counter_ex))
        elif kind in ("类型占位", "下拉默认档", "无记录") and written:
            counter_ex = ""

        # 没有官方默认值 → 用语料众数兜底（只当参考，L0）
        if src == DEFAULT_SOURCE_NONE and written >= 3 and top_n:
            share = top_n / float(written)
            # 字符串字面量 / 含自定义标识的取值不能当默认值（也没必要记进表）
            usable = ('"…"' not in top_val and safe_corpus_value(top_val) == top_val)
            if share >= 0.9 and usable:
                value, kind, src, level = top_val, "语料众数", DEFAULT_SOURCE_CORPUS, "L0"
                notes.append("官方无记录；语料 %d 处里 %d 处写「%s」（%.0f%%），当参考不当结论"
                             % (written, top_n, top_val, share * 100))
            elif not usable:
                notes.append("官方无记录；语料 %d 处写的是自定义字符串/变量名（已隐去），定不出默认值"
                             % written)
            else:
                notes.append("官方无记录；语料 %d 处取值分散（最常见「%s」%d 处），定不出默认值"
                             % (written, top_val, top_n))
        if top_val and safe_corpus_value(top_val) != top_val:
            notes.append("语料最常见取值含玩家自定义标识，已隐去（语料不外传）")
        stats[(src, kind, level)] += 1
        tail = "是" if idx + 1 >= total.get(el, 0) else "否"
        rows.append([el, ekind or (r["kind"] or ""), idx, pname, ptype, value, kind, src, tail,
                     counter_ex if counter_ex != "" else "",
                     written if written else "", safe_corpus_value(top_val), level,
                     "；".join(notes)])
    rows.sort(key=lambda x: (x[0], x[2]))
    return rows, stats


# ------------------------------------------------- 2. 下拉全集与别名
BOOL_EXPORT_ROWS = [
    # (字段, 规范取值, 别名, 别名是否被接受, 是否导出显示词, 依据, 等级, 备注)
    ("布尔设置项", "开启", "启用", "否（游戏报错，改回开启才行）", "是",
     "normalize.py fix_bool_words「目标点决胜机制 / 推进背包 / 尖刺墙 写「禁用」导入失败」；"
     "data/value-words.tsv 资产 TrueText 统计 启用(12)", "L2",
     "实测被拒的键：目标点决胜机制 / 推进背包 / 尖刺墙；其余键逐键未验"),
    ("布尔设置项", "关闭", "禁用", "否（游戏报错，改回关闭才行）", "是",
     "同上 + HANDOFF「队伍界面 / 阵亡镜头的布尔关闭词是「关闭」，不是「禁用」」（P1 被拒 / P1c 通过）", "L2",
     "实测通过的键：队伍界面 / 阵亡镜头（写 关闭）；另有 36 个键资产没带真假词，未验"),
    ("布尔设置项", "开启", "是", "未验证", "是（资产词，2 个键用）",
     "data/value-words.tsv 资产 TrueText 统计 是(2)；引擎是否吃未验", "L0",
     "资产显示词不等于引擎接受词，别照抄"),
    ("布尔设置项", "关闭", "否", "未验证", "是（资产词，2 个键用）",
     "data/value-words.tsv 资产 FalseText 统计 否(2)；引擎是否吃未验", "L0",
     "同上"),
]


def build_dropdown_aliases(pdocs, popts, extvals, exts, corpus, sigs_labels):
    rows = []
    for f, canon, alias, acc, exp, ev, lv, note in BOOL_EXPORT_ROWS:
        rows.append([f, "(全部布尔设置项)", canon, alias, acc, exp, "否", ev, lv,
                     "布尔导出显示词，整块被拒的那一类；" + note])
    # 元素参数里的布尔槽（.ow 代码里）
    wrote = collections.Counter()
    if corpus:
        for el, rec in corpus.items():
            labels = sigs_labels.get(el) or []
            for idx, cnt in rec["vals"].items():
                if idx < len(labels) and "布尔" in labels[idx]:
                    wrote.update(cnt)
    code_vals = "|".join(v for v, _n in wrote.most_common(4)) or "(语料无样本)"
    rows.append(["元素参数", "(全部布尔参数)", "真|假", "开启|关闭|启用|禁用", "未验证", "否", "否",
                 "语料里布尔参数的实际取值：%s（共 %d 处）；界面词写进代码是否被接受未实测"
                 % (code_vals, sum(wrote.values())), "L0",
                 "别把设置项的词（开启/关闭）搬进 .ow 代码；布尔槽也接受比较表达式"
                 "（例：所在队伍(事件玩家) == 队伍2），这属于表达式不是词"])

    # 下拉槽：有「全部禁用」的槽 —— 导出会把它们写成「无」，必须改回
    hard = {("设置不可见", 1), ("追踪全局变量频率", 3), ("追踪玩家变量频率", 4),
            ("创建地图文本", 5), ("创建HUD文本", 9)}   # normalize.py 里硬编码过（E-37 实机三轮）
    n_dis, n_none = 0, 0
    for r in popts:
        el = (r["element"] or "").strip()
        try:
            idx = int(r["index"])
        except (KeyError, ValueError):
            continue
        opts = [o.strip() for o in (r["options"] or "").split("|") if o.strip()]
        if not opts:
            continue
        field = "%s 第%d个参数" % (el, idx + 1)
        if "全部禁用" in opts:
            n_dis += 1
            lv = "L2" if (el, idx) in hard else "L1"
            ev = ("normalize.py NO_TO_DISABLED + E-37 实机三轮（导出文件不能直导）"
                  if (el, idx) in hard else
                  "data/param-options.tsv 该槽选项含「全部禁用」；normalize 按数据自动修")
            rows.append(["下拉参数", field, "全部禁用", "无", "否（整块被拒）", "是", "否", ev, lv,
                         "导出写「无」，引擎要「全部禁用」；这是「会挡导入」的那一类"])
        if "无" in opts:
            n_none += 1
            lv = "L2" if el == "创建效果" else "L1"
            ev = ("data/param-options.tsv 该槽选项含「无」"
                  + ("；docs/pitfalls-runtime.md 实测：语料大量出现、能导入运行，曾报提示 → 8 份语料 3 个误报，已撤回"
                     if el == "创建效果" else ""))
            rows.append(["下拉参数", field, "无", "全部禁用", "否（该槽没有这个词）", "否", "否", ev, lv,
                         "这个槽的「无」是合法取值，禁止被 normalize 改成「全部禁用」"])
    # 队伍 / 英雄参数：位置相关的写法
    rows.append(["队伍参数", "(全部队伍型参数)", "所有队伍|队伍1|队伍2", "全部|双方",
                 "否（写在动作参数里被拒；只在事件块选择器行合法）", "否", "否",
                 "E-51 实机两连拒（玩家数量(全部) / 范围内玩家(…, 双方, …)）+ docs/rules.tsv 队伍参数", "L2",
                 "同一段文字在事件选择器行是合法的，位置决定对错"])
    rows.append(["英雄参数", "(全部英雄型参数)", "英雄(<英雄名>)", "裸英雄名",
                 "否（游戏报错）", "否", "否",
                 "E-51 实机两连拒（生成机器人(死神, …) 被拒）+ docs/rules.tsv 英雄参数", "L2",
                 "必须用 英雄(...) 包一层"])

    # 扩展独占取值：只有开了扩展才出现在下拉里
    ext_owner = collections.defaultdict(list)
    for r in pdocs:
        g = (r["dropdown"] or "").strip()
        if g:
            ext_owner[g].append(r)
    unlocked = {r["extension"]: r for r in exts}
    seen = set()
    for r in extvals:
        g, extn, val = r["dropdown"], r["extension"], r["value"]
        for pr in ext_owner.get(g, []):
            el = pr["element"]
            try:
                idx = int(pr["index"])
            except (KeyError, ValueError):
                idx = 0
            field = "%s 第%d个参数（%s）" % (el, idx + 1, (pr["name"] or "").strip() or "无参数名")
            key = (field, val)
            if key in seen:
                continue
            seen.add(key)
            info = unlocked.get(extn) or {}
            rows.append(["扩展下拉", field, val, "", "—", "否", "是",
                         "data/extension-values.tsv（扩展 %s：成本 %s 点、解锁 %s 项）+ data/extensions.tsv"
                         % (extn, info.get("cost", "?"), info.get("unlocked", "?")), "L1",
                         "扩展没开时该选项不在下拉里；写进 .ow 需要「扩展」块写上 %s" % extn])
    rows.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    return rows, n_dis, n_none


# --------------------------------------------------- 3. 参数个数例外
def build_param_exceptions(pdocs, sigs_labels, corpus, argcounts_path, n_files=0):
    rows = []
    # 正向：签名看起来能省，但引擎要求写满 —— 只收「实机拒收过」的元素。
    # 每条的 floor = 签名参数个数：写少一个就是缺参数，游戏当场报错。
    required_all = [
        ("创建效果", "只写 5 个 → 游戏报「第N行的“50”之后应有分号」",
         "E-55 一（实机拒收《创建效果(…, 球体, 颜色(白色), 矢量(0,3,0), 5)》）"),
        ("取整", "只写 1 个 → 游戏报「之后应有逗号」",
         "issue #2（2026-10-31 实机：《取整(5)》被拒）"),
        ("随机整数", "只写 1 个 → 游戏报「之后应有逗号」",
         "issue #2（2026-10-31 实机：《随机整数(1)》被拒）"),
    ]
    for el, symptom, evidence in required_all:
        labels = sigs_labels.get(el) or []
        if not labels:
            continue
        rec = (corpus or {}).get(el)
        min_a = max_a = None
        if rec and rec["argc"]:
            min_a, max_a = min(rec["argc"]), max(rec["argc"])
        else:
            for r in load_tsv(argcounts_path):
                if r.get("element") == el:
                    min_a, max_a = int(r["min_args"]), int(r["max_args"])
        rows.append([el, "第%d个参数（%s）" % (len(labels), labels[-1].split(":")[0]),
                     "是（签名尾参写着「可以省略」）" if el == "创建效果"
                     else "否（签名列了 %d 个，没有可选尾参）" % len(labels),
                     "是，必须写到 %d 个" % len(labels),
                     "任何时候都要求；" + symptom,
                     "%s；语料 %s 次调用里最少 %s 个、最多 %s 个"
                     % (evidence, rec["calls"] if rec else "?", min_a, max_a),
                     "L2", "实机确认的「少写尾参就导不进去」"])

    # 反向：签名列了参数，语料里一致的少写（引擎收得下）
    variadic = set(getattr(core, "VARIADIC", ()) or ())
    rev = 0
    for name in sorted(corpus or {}):
        rec = corpus[name]
        labels = sigs_labels.get(name) or []
        if not labels or name in variadic or not rec["argc"]:
            continue
        hi = max(rec["argc"])
        if hi < len(labels):
            rev += 1
            last = labels[hi].split(":")[0].strip() or "第%d个" % (hi + 1)
            rows.append([name, "第%d个参数（%s）" % (hi + 1, last),
                         "否（签名列了 %d 个）" % len(labels),
                         "否，语料 %d 次全写 %d 个" % (rec["calls"], hi),
                         "语料里省掉的是尾部「%s」；少写后语义未验，别推广到别的参数" % last,
                         "语料统计（%d 份语料，%d 次调用）——导出产物里有这种写法，说明引擎产生得出来"
                         % (n_files, rec["calls"]), "L1",
                         "反向例外：别再拿「签名有几个参数」当必须写几个"])
    # 元素数（真实存在的语料元素）里有多少个能这么判
    return rows, rev


# ------------------------------------------------------- 4. 上限与互斥
def build_limits_mutex():
    """数值能取自工具的取自工具常量，取不到的写明出处；拿不到出处的一律 L0/未验证。"""
    E = core.ELEMENT_LIMIT
    W = getattr(core, "ELEMENT_WARN", 0)
    B = core.RULE_BYTE_LIMIT
    SLOTS = getattr(core, "LOBBY_TEAM_SLOTS", 12)
    rows = [
        # 类别 / 限制项 / 数值或互斥对 / 来源 / 等级 / 依据 / 备注
        ["上限", "元素数（整个模式）", str(E), "官方",
         "L0", "core.ELEMENT_LIMIT；docs/limits.md「既有记载，未在 2.25.0.0 实测」",
         "以游戏「显示诊断结果 → 总计元素数量」为准；估算偏低 4~19%，按上界判"],
        ["上限", "元素数预警线", str(W), "官方", "L0",
         "core.ELEMENT_WARN（check 到此出提示，不是硬限）", "只是提示档位"],
        ["上限", "单条规则字节数", "%d（98KB）" % B, "官方", "L0",
         "core.RULE_BYTE_LIMIT = 98 × 1024；游戏报「每条规则长度不得超过98KB」", "长规则先撞这个"],
        ["上限", "全局变量数量 / 索引", "128 个（索引 0-127，可跳号）", "官方", "L1",
         "docs/limits.md + docs/syntax.md；check 已自动查", "与玩家变量分开计数"],
        ["上限", "玩家变量数量 / 索引", "128 个（索引 0-127，可跳号）", "官方", "L1",
         "同上", "与全局变量分开计数"],
        ["上限", "子程序数量 / 索引", "128 个（索引 0-127，可跳号）", "官方", "L1",
         "docs/limits.md；check 已自动查", ""],
        ["上限", "HUD 文本同时存活条数", "128 条（ID 本身不回收）", "实测", "L3",
         "docs/pitfalls-runtime.md A2/A3 + E-32：ID 涨到 128 后恒为 128、HUD 停更；先删后建时 ID 涨到 181 也无事",
         "限的是「同时存活」，不是 ID 上限；循环刷新必须 消除HUD文本 → 创建HUD文本"],
        ["上限", "大厅玩家栏位（队伍1 + 队伍2 合计）", "≤ %d" % SLOTS, "实测", "L2",
         "docs/limits.md 2026-10-23 实机确认；core.LOBBY_TEAM_SLOTS + check_lobby_team_sum",
         "合计 0 开不了局；界面输不进 >12，外部写进去导入报错"],
        ["上限", "单队栏位 / 观战者 / 自由混战", "各 %d" % SLOTS, "实测", "L2",
         "docs/limits.md 2026-10-23 实机；观战不占玩家栏位", ""],
        ["上限", "规则条数", "未确认（社区传 100，无确证）", "官方", "L0",
         "docs/limits.md「未确认，不写死」", "别拿 100 当结论"],
        ["合法写法", "创建效果的「重新赋值: 无」", "「无」不是错误，是常规写法", "实测", "L2",
         "docs/pitfalls-runtime.md：语料大量出现、游戏正常导入运行；曾报提示 → 8 份语料 3 个文件误报，已撤回（E-55 三）",
         "语义是「不覆盖已有效果」；这个槽的选项表里本来就有「无」"],
        ["合法写法", "创建地图文本 / 创建HUD文本 的「重新赋值: 全部禁用」", "「全部禁用」是合法取值", "官方", "L1",
         "data/param-options.tsv 该槽选项含「全部禁用」；导出会把它写成「无」（要改回来）",
         "与上一条互为镜像：同一个词在不同槽里合法性相反"],
        ["百分比", "设置最大生命值 的参数", "100 = 原值（百分比，不是绝对血量）", "实测", "L3",
         "E-56 格08：写 200，机器人 275 → 550；docs/pitfalls-runtime.md 2026-10-23 实测；core.check_health_percent_param",
         "想要 300 点血写 50；写 300 = 3 倍上限"],
        ["百分比", "设置移动速度 的参数", "100 = 原值（百分比）", "实测", "L3",
         "docs/pitfalls-runtime.md「设置最大生命值 / 设置移动速度 的参数是百分比（2026-10-23 实测）」", ""],
        ["百分比", "房间/英雄页的伤害量、受到伤害量、移动速度", "与规则里的系数相乘（不是覆盖）", "实测", "L3",
         "E-20 / T15 两组实机：英雄页 200% × 规则 50% = 100%", "补偿要乘 1/(a*b)"],
        ["运行时", "循环里宣告胜负", "宣告后必须 中断 / 置 ended 守卫", "实测", "L3",
         "E-38（A8 探针）+ docs/rules.tsv 宣告胜负后收尾：结算前后几秒规则还会跑，之后整场规则全停",
         "循环条件带 全局.ended，或 等待直到(游戏正在进行中() == 假) 后 中断"],
        ["互斥", "地图池写法（同一片地区）", "死斗/团队死斗/决斗先锋/勇夺锦旗 = 场景名（伊利奥斯废墟）× 占领要点/突击 = 整图名（伊利奥斯）",
         "实测", "L2", "M1/M3 实机：互换都报「尚未选择地图。你必须调整或撤销设置改动」；docs/pitfalls-map.md",
         "池子里写的那个名字就是该模式唯一合法写法，不做粗细换算"],
        ["互斥", "死斗模式的队伍参数", "队伍1 / 队伍2（空壳，玩家数与栏位都是 0）× 所有队伍（唯一有效）",
         "实测", "L2", "E-49 四：死斗里 生成机器人(…, 队伍1, …) 静默失败；docs/rules.tsv 死斗里加机器人",
         "死斗要塞机器人只能写 所有队伍，位置/方向写 空"],
        ["互斥", "队伍值的出现位置", "事件块选择器行的 全部 / 双方 × 动作参数里的 全部 / 双方（被拒）",
         "实测", "L2", "E-51 实机两连拒（P 探针前身）+ docs/rules.tsv 队伍参数",
         "同一段文字，位置决定合法性"],
        ["互斥", "设置键的块归属", "别名键（schema Category=5）只能写在对应模式块 × 综合块（被拒）",
         "实测", "L2", "F1 实机（决斗先锋 { 复生时间 } 被拒）+ E-47 二 + docs/rules.tsv 设置键的层级",
         "综合 只收模式系 schema 的键，英雄页的键写在英雄块里"],
        ["互斥", "可用扩展点数", "已用扩展点数 ≤ 可用点数（基础 8，移除栏位可加）",
         "实测", "L2", "docs/extensions.md 三：面板实测，超限确认按钮变灰；可用点数 = 4 × 空栏位数",
         "不能只按 8 判超限：真实模式里移除栏位后能开到 12 点"],
        ["互斥", "布尔设置项的词", "开启 / 关闭（唯一合法）× 启用 / 禁用（导出显示词，整块被拒）",
         "实测", "L2", "E-37 + P1/P1c 实机 + normalize.py fix_bool_words",
         "按类型判：Enum 项写「禁用」是合法的，只有 Bool 项不行"],
        ["互斥", "下拉槽「无」的词", "全部禁用（该槽选项含它时）× 无（导出显示词，整块被拒）",
         "实测", "L2", "E-37 导出文件不能直导 + normalize.py + data/param-options.tsv",
         "反过来：选项本来就含「无」的槽（创建效果 重新赋值 等）写「无」才对，别改"],
    ]
    return rows


# ----------------------------------------------------------------- 主流程
TABLES = {
    "defaults-full": ("data/defaults-full.tsv",
                      ["元素", "元素类别", "参数序号", "参数", "参数类型", "默认值", "默认值性质", "来源",
                       "尾参(文档口径可省)",
                       "语料反例数", "语料写出次数", "语料最常见取值", "证据等级", "备注"]),
    "dropdown-aliases": ("data/dropdown-aliases.tsv",
                         ["字段类型", "字段", "规范取值", "别名", "别名是否被接受", "是否导出显示词",
                          "是否只有扩展启用后才出现", "证据", "证据等级", "备注"]),
    "param-exceptions": ("data/param-exceptions.tsv",
                         ["元素", "参数", "文档说可省", "引擎实际要求写", "触发条件", "依据",
                          "证据等级", "备注"]),
    "limits-mutex": ("data/limits-mutex.tsv",
                     ["类别", "限制项", "数值或互斥对", "来源", "证据等级", "依据", "备注"]),
}

# 这三张表有「语料反例数 / 写出次数 / 众数 / 反向例外」列，没有语料就复算不出来。
# 没语料时 check 跳过它们而不是报漂移——CI 与公开仓永远没有语料，报漂移等于天天假红灯。
CORPUS_DEPENDENT = {"defaults-full", "dropdown-aliases", "param-exceptions"}


def main():
    ap = argparse.ArgumentParser(description="生成四张元素事实表")
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--corpus", default=None, help="语料目录（默认为 local_paths.json 里的 corpus）")
    ap.add_argument("--no-corpus", action="store_true")
    ap.add_argument("--check", action="store_true", help="只算不写，比对磁盘上的表是否漂移")
    a = ap.parse_args()

    D = a.data
    pdocs = load_tsv(os.path.join(D, "param-docs.tsv"))
    dtsv = load_tsv(os.path.join(D, "defaults.tsv"))
    popts = load_tsv(os.path.join(D, "param-options.tsv"))
    extvals = load_tsv(os.path.join(D, "extension-values.tsv"))
    exts = load_tsv(os.path.join(D, "extensions.tsv"))
    edocs = load_tsv(os.path.join(D, "element-docs.tsv"))
    sigs, labels, _opts = core.load_signatures(os.path.join(D, "signatures.md"))

    corpus_dir = "" if a.no_corpus else (a.corpus or corpus_dir_from_paths())
    corpus, files = ({}, [])
    if corpus_dir and os.path.isdir(corpus_dir):
        corpus, files = scan_corpus(corpus_dir, list(labels.keys()))
    else:
        print("! 没找到语料目录（%s）：语料列一律写空，来源只剩官方文档" % (corpus_dir or "未配置"))

    built = {}
    built["defaults-full"], dstats = build_defaults_full(pdocs, dtsv, edocs, corpus)
    built["dropdown-aliases"], n_dis, n_none = build_dropdown_aliases(
        pdocs, popts, extvals, exts, corpus, labels)
    built["param-exceptions"], n_rev = build_param_exceptions(
        pdocs, labels, corpus, os.path.join(D, "arg-counts-from-corpus.tsv"), len(files))
    built["limits-mutex"] = build_limits_mutex()

    drift = 0
    for key, (rel, header) in TABLES.items():
        path = os.path.join(ROOT, rel)
        text = render_tsv(header, built[key])
        old = ""
        if os.path.isfile(path):
            old = open(path, encoding="utf-8").read()
        same = (old == text)
        if a.check:
            if not files and key in CORPUS_DEPENDENT:
                # 没语料：这几列复算不出来，跳过而不是报漂移（否则每次都假红灯）
                print("- %-22s %4d 行  跳过（没语料，语料列无从复算）" % (rel, len(built[key])))
                continue
            print("%s %-22s %4d 行  %s" % ("=" if same else "≠", rel,
                                           len(built[key]), "无漂移" if same else "有漂移"))
            drift += 0 if same else 1
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print("写 %-22s %4d 行%s" % (rel, len(built[key]), "" if same else "（内容有变化）"))

    # 对账摘要：param-docs ⇄ defaults.tsv（ws.py defaults 读的就是 defaults.tsv，ws.py:209）
    pd_keys = {(r["element"], int(r["index"])) for r in pdocs if (r["index"] or "").isdigit()}
    dt_keys = {(r["func"], int(r["param_index"])) for r in dtsv
               if (r["param_index"] or "").isdigit() and (r["func"] or "").strip()}
    orphan = sorted(dt_keys - pd_keys)
    print("\n对账 param-docs ⇄ defaults.tsv：param-docs %d 行 / defaults.tsv %d 行 / "
          "param-docs 多出 %d（事件选择器行）/ defaults.tsv 多出 %d"
          % (len(pd_keys), len(dt_keys), len(pd_keys - dt_keys), len(orphan)))
    if orphan:
        print("  defaults.tsv 孤儿行（函数名对不上，数据侧产物，未在本表体现）：%s" % orphan[:6])
    blank = [r for r in dtsv if not (r["func"] or "").strip()]
    if blank:
        print("  defaults.tsv 里 %d 行函数名为空（数据侧残渣，%s…；不属本脚本可修范围）"
              % (len(blank), "/".join(r["default"] for r in blank[:3])))
    print("\n语料：%s（%d 份）" % (corpus_dir if files else "未使用", len(files)))
    print("默认值来源分布（来源/性质/等级 -> 行数）：")
    for k, v in sorted(dstats.items(), key=lambda kv: -kv[1]):
        print("  %-6s %-6s %-3s %4d" % (k[0], k[1], k[2], v))
    print("下拉别名：可选「全部禁用」的槽 %d 个 / 选项本来就含「无」的槽 %d 个 / 总行 %d"
          % (n_dis, n_none, len(built["dropdown-aliases"])))
    print("参数例外：正向（签名可省·引擎要写）1 例 + 反向（签名要写·语料少写）%d 例" % n_rev)
    if n_rev:
        for r in built["param-exceptions"][1:]:
            print("  %s：%s，%s" % (r[0], r[1], r[3]))
    if a.check and drift:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
