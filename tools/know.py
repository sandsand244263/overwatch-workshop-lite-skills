#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ws.py 知道 <名字> 的实现：一条命令回答一个元素/设置键的全部已知事实。

规格（私有仓 stage1/INTEGRATION-CONTRACT.md）六段固定输出：
  1 身份 / 2 参数 / 3 能出现在哪 / 4 取值 / 5 已知坑 / 6 出处

硬纪律（照规格）：
  · 只回答事实，不判错、不给建议（判错在校验器里）
  · 证据等级不抬高：表里只有 L0/L1 就写 L0/L1；没读数写「未验证」，不许留空
  · 语料与数据表打架时两行都打出来并标「冲突」，不替读者选一个
  · 表只加载一次（模块级缓存），单次查询 <0.5 s

数据来源全部是 data/ 与 docs/rules.tsv 的现有表，不新增数据；本文件不改它们的生成方式。
"""
import csv
import difflib
import os
import re
import sys
import unicodedata

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
DATA = os.path.join(ROOT, "data")
DOCS = os.path.join(ROOT, "docs")

# 五个块位置：(显示名, action-blocks.tsv 列名)
BLOCK_SLOTS = [
    ("事件块", "事件块"),
    ("持续 - 全局", "持续-全局"),
    ("持续 - 每名玩家", "持续-每名玩家"),
    ("条件块", "条件块"),
    ("子程序体", "子程序体"),
]
# 设置键的块位置（与工坊元素不是同一个坐标系）
KEY_SLOTS = ["综合块", "模式块", "大厅块", "英雄页"]

HERO_PAGE_SCHEMAS = {"技能", "武器", "战斗设置"}

SECTIONS = ["身份", "参数", "能出现在哪", "取值", "已知坑", "出处"]

_CACHE = {}


# ---------------------------------------------------------------- 读表

def _rows(fname, sub="data"):
    """读一个 tsv，返回字典列表；文件不存在返回 []。结果进模块缓存（只读一次）。"""
    key = (sub, fname)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    base = DATA if sub == "data" else DOCS
    path = os.path.join(base, fname)
    rows = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig", newline="") as f:
            text = f.read()
        if '"' in text:
            # 字段带引号：先试 split + 逐格去引号；任一行列数不符就回退 csv
            lines = text.splitlines()
            head = lines[0].split("\t")
            n = len(head)
            rows, ok = [], True
            for ln in lines[1:]:
                if not ln.strip():
                    continue
                parts = ln.split("\t")
                if len(parts) != n:
                    ok = False
                    break
                rows.append(dict(zip(head, [_unquote(p) for p in parts])))
            if not ok:
                rows = list(csv.DictReader(text.splitlines(), delimiter="\t"))
        else:
            # 没有引号：split 比 csv.DictReader 快 5~30 倍（单文件实测 0.031 s → 0.001 s）
            lines = text.splitlines()
            if lines:
                head = lines[0].split("\t")
                n = len(head)
                for ln in lines[1:]:
                    if not ln.strip():
                        continue
                    parts = ln.split("\t")
                    if len(parts) < n:
                        parts += [""] * (n - len(parts))
                    rows.append(dict(zip(head, parts)))
    _CACHE[key] = rows
    return rows


def _unquote(v):
    """csv 风格的整格引号：去外引号、还原 "" → "。不做字段内换行以外的事。"""
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1].replace('""', '"')
    return v


def _col(r, *names):
    """按候选列名取第一个非空值（表头有几种写法）。"""
    for n in names:
        v = r.get(n)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return ""


def _int(v, default=-1):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


_ALIAS_FIELD = re.compile(r"^(?P<el>.+?)\s*第(?P<n>\d+)个参数")


def db():
    """把六张新表 + 老表建成一次性的查询索引。只在第一次调用时执行。"""
    d = _CACHE.get("db")
    if d is not None:
        return d

    d = {}

    # 元素类型（element-kinds.tsv）
    kinds, kind_of = {}, {}
    for r in _rows("element-kinds.tsv"):
        name = _col(r, "name").strip()
        kind = _col(r, "kind").strip()
        if name:
            kinds.setdefault(name, kind)
            kind_of.setdefault(name, []).append(kind)
    d["kinds"] = kinds

    # 官方说明（element-docs.tsv）
    desc = {}
    for r in _rows("element-docs.tsv"):
        name = _col(r, "name").strip()
        text = _col(r, "description")
        if name and text:
            desc.setdefault(name, text)
    d["desc"] = desc

    # 参数（param-docs.tsv）
    params = {}
    for r in _rows("param-docs.tsv"):
        el = _col(r, "element").strip()
        if el:
            params.setdefault(el, []).append(r)
    for v in params.values():
        v.sort(key=lambda x: _int(_col(x, "index"), 0))
    d["params"] = params

    # 默认值全表（defaults-full.tsv）
    dflt = {}
    for r in _rows("defaults-full.tsv"):
        el = _col(r, "元素").strip()
        idx = _int(_col(r, "参数序号"))
        if el and idx >= 0:
            dflt.setdefault(el, {})[idx] = r
    d["dflt"] = dflt

    # 块位置矩阵（action-blocks.tsv）
    d["blocks"] = {_col(r, "元素名").strip(): r for r in _rows("action-blocks.tsv") if _col(r, "元素名").strip()}

    # 取值完备性（element-completeness.tsv）：名字 → 上一行差集类型
    comp = {}
    for r in _rows("element-completeness.tsv"):
        el = _col(r, "元素名").strip()
        cat = _col(r, "类别").strip()
        if el:
            comp.setdefault((cat, el), r)      # 按「类别 + 名字」存：生命值 既是值也是设置键
    d["comp"] = comp

    # 下拉别名（dropdown-aliases.tsv）：按「元素 第N个参数」挂到参数位，通用行单独存
    aliases, generic = {}, []
    for r in _rows("dropdown-aliases.tsv"):
        field = _col(r, "字段").strip()
        m = _ALIAS_FIELD.match(field)
        if m:
            aliases.setdefault((m.group("el").strip(), int(m.group("n")) - 1), []).append(r)
        else:
            generic.append(r)
    d["aliases"] = aliases
    d["generic_aliases"] = generic

    # 参数例外（param-exceptions.tsv）
    exc = {}
    for r in _rows("param-exceptions.tsv"):
        el = _col(r, "元素").strip()
        if el:
            exc.setdefault(el, []).append(r)
    d["exc"] = exc

    # 上限 / 互斥（limits-mutex.tsv）
    d["limits"] = [r for r in _rows("limits-mutex.tsv") if any((v or "").strip() for v in r.values())]

    # 扩展成本（extensions.tsv）
    ext = {}
    for r in _rows("extensions.tsv"):
        name = _col(r, "extension").strip()
        if name:
            ext[name] = r
    d["ext"] = ext

    # 断言表（docs/rules.tsv）
    rules = []
    for r in _rows("rules.tsv", "docs"):
        toks = [t for t in re.split(r"[ ,，、]+", _col(r, "关键词")) if t]
        rules.append((r, toks))
    d["rules"] = rules

    _CACHE["db"] = d
    return d


def sdb():
    """设置键侧的表（键 / schema / 枚举 / 范围 / 实测 / 大厅 / 层 / 块分区）。

    元素查询用不到这一半，所以从 db() 里拆出来按需加载——这是「单次查询 <0.5 s」的一半，
    另一半是 _rows() 的快速解析。两边都只加载一次。
    """
    d = db()
    if d.get("_settings_ready"):
        return d

    # ---------------- 设置键
    km, st, ss, ev, rng, ver, lob, lay, compat = {}, {}, {}, {}, {}, {}, {}, {}, {}
    for r in _rows("key-map.tsv"):
        k = _col(r, "键")
        if k:
            km.setdefault(k, []).append(r)
    for r in _rows("settings.tsv"):
        k = _col(r, "key")
        if k:
            st.setdefault(k, []).append(r)
    for r in _rows("setting-schemas.tsv"):
        k = _col(r, "key")
        if k:
            ss.setdefault(k, []).append(r)
    for r in _rows("enum-values.tsv"):
        k = _col(r, "键名")
        if k:
            ev.setdefault(k, []).append(r)
    for r in _rows("setting-ranges.tsv"):
        k = _col(r, "key")
        if k:
            rng.setdefault(k, []).append(r)
    for r in _rows("verified-keys.tsv"):
        k = _col(r, "key")
        if k:
            ver.setdefault(k, []).append(r)
    for r in _rows("lobby-keys.tsv"):
        k = _col(r, "key")
        if k:
            lob.setdefault(k, []).append(r)
    for r in _rows("key-parent-layers.tsv"):
        k = _col(r, "key")
        if k:
            lay.setdefault(k, []).append(r)
    for r in _rows("setting-compat.tsv"):
        k = _col(r, "key")
        if k:
            compat.setdefault(k, []).append(r)
    d.update(km=km, st=st, ss=ss, ev=ev, rng=rng, ver=ver, lob=lob,
             lay=lay, compat=compat)

    # 模式 ⇄ schema
    schema_modes, modes = {}, set()
    for r in _rows("mode-schemas.tsv"):
        mode = _col(r, "mode")
        if not mode:
            continue
        modes.add(mode)
        for s in _col(r, "schemas").split("|"):
            s = s.strip()
            if s:
                schema_modes.setdefault(s, []).append(mode)
    d["schema_modes"] = schema_modes
    d["mode_names"] = modes

    # 英雄设置键（hero-setting-names.tsv）：只有名字，参数/范围没有读数
    hero = {}
    for r in _rows("hero-setting-names.tsv"):
        k = _col(r, "键名")
        if k:
            hero.setdefault(k, []).append(r)
    d["hero_keys"] = hero

    # 设置块分区（settings-sections.tsv）
    blocks = {}
    for r in _rows("settings-sections.tsv"):
        blocks[_col(r, "块名")] = r
    d["sections"] = blocks

    # 名字总表（用于「找不到 → 列相近 3 个」）
    universe = set(d["kinds"]) | set(st) | set(ss) | set(km) | set(hero)
    for r in _rows("settings-sections.tsv"):
        b = _col(r, "块名")
        if b:
            universe.add(b.split()[-1] if ">" in b else b)
    universe |= {"启用地图", "禁用地图"}
    d["universe"] = sorted(n for n in universe if n and "%" not in n and "$" not in n)

    d["_settings_ready"] = True
    return d


# ---------------------------------------------------------------- 解析名字

def clean_name(query):
    """`伤害(玩家, 玩家, 5)` → `伤害`；全角括号同样处理；多余空白压成一个。"""
    s = (query or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    if "(" in s:
        s = s[: s.index("(")]
    s = re.sub(r"\s+", " ", s).strip()
    return s


def key_names(d):
    """设置键的全部名字来源（几张小表合起来）。"""
    return set(d["st"]) | set(d["ss"]) | set(d["km"]) | set(d["lob"]) | set(d["ver"]) | set(d["ev"])


def collisions(name, kind):
    """同名但类型不同的那些东西（生命值 / 返回大厅 / 技能冷却时间 三个）。"""
    d = sdb()
    out = []
    if kind not in ("动作", "值", "事件", "扩展") and name in d["kinds"]:
        out.append(d["kinds"][name])
    if kind in ("动作", "值", "事件", "扩展") and name in key_names(d):
        out.append("设置键")
    return out


def resolve(query, force=None):
    """返回 (类型, 规范名) 或 (None, 候选列表)。元素先查（不碰设置键侧的表）。

    force 给 --as 用：在两种类型同名时指定按哪种回答（生命值既是值函数也是设置键）。
    """
    d = db()
    raw = (query or "").strip()
    name = clean_name(raw)
    cands = [name, raw]
    if force:
        d2 = sdb()
        for cand in cands:
            if not cand:
                continue
            if force in ("动作", "值", "事件", "扩展") and d["kinds"].get(cand) == force:
                return force, cand
            if force == "设置键" and cand in key_names(d2):
                return "设置键", cand
            if force == "设置块" and (cand in d2["sections"] or cand in ("启用地图", "禁用地图")):
                return "设置块", cand
        return None, []
    for cand in cands:
        if not cand:
            continue
        if cand in d["kinds"]:
            return d["kinds"][cand], cand
    # 元素查不到才加载设置键侧
    d = sdb()
    for cand in cands:
        if not cand:
            continue
        if (cand in d["st"] or cand in d["ss"] or cand in d["km"]
                or cand in d["ev"] or cand in d["lob"] or cand in d["ver"]
                or cand in d["lay"] or cand in d["compat"]):
            return "设置键", cand
        if cand in d["sections"]:
            return "设置块", cand
        if cand in ("启用地图", "禁用地图"):
            return "设置块", cand
        if cand in d["hero_keys"]:
            return "设置键", cand
    # 大小写 / 空白不敏感
    low = name.lower()
    for nm, k in d["kinds"].items():
        if nm.lower() == low:
            return k, nm
    for nm in list(d["st"]) + list(d["ss"]):
        if nm.lower() == low:
            return "设置键", nm
    pool = d["universe"]
    close = difflib.get_close_matches(name, pool, n=3, cutoff=0.3)
    if not close:
        close = [p for p in pool if name and name in p][:3]
    if not close:
        close = [p for p in pool if p[:1] == name[:1]][:3]
    return None, close


# ---------------------------------------------------------------- 小工具

def _pad(s, width):
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in "WF" else 1
    return s + " " * max(0, width - w)


def _split_values(vals):
    """"1~3|默认2" → ("1~3", "2")；拆不出范围就返回 ("", "")。"""
    parts = [p.strip() for p in (vals or "").split("|")]
    rng = ""
    dflt = ""
    if parts and re.search(r"\d", parts[0]) and "~" in parts[0]:
        rng = parts[0]
    for p in parts[1:]:
        if p.startswith("默认"):
            dflt = p[2:].strip()
    return rng, dflt


def _first_sentence(text, limit=110):
    t = (text or "").strip().replace("\n", " ")
    if not t:
        return ""
    m = re.search(r"[。！？]", t)
    out = t[: m.end()] if m else t
    if len(out) > limit:
        out = out[:limit].rstrip() + "…"
    return out


def _ev(items, what, source, level):
    items.append({"项": what, "凭据": source, "等级": level or "未验证"})


def _has_reading(state):
    """块位置单元格算不算「有读数」：是 / 否(...) 都算，未验证不算。"""
    s = (state or "").strip()
    return s.startswith("是") or s.startswith("否")


def _state_of(cell):
    s = (cell or "").strip()
    if s.startswith("是"):
        return "可以", ""
    if s.startswith("否"):
        reason = ""
        m = re.search(r"[（(](.*)[）)]", s)
        if m:
            reason = m.group(1)
        return "不可以", reason
    return "未验证", ""


def _level_of_blocks(row):
    return _col(row, "证据等级") or "未验证"


# ---------------------------------------------------------------- 元素六段

def _element_sections(name, kind, ev):
    d = db()
    blk = d["blocks"].get(name)
    out = {}

    # ---- 1 身份
    lines = []
    lines.append("%s类型             %s" % ("", kind))
    _ev(ev, "类型=%s" % kind, "data/element-kinds.tsv", "L0")
    description = d["desc"].get(name, "")
    first = _first_sentence(description)
    if first:
        lines.append("官方说明         %s" % first)
        _ev(ev, "官方说明", "data/element-docs.tsv", "L0")
        if len(description) > len(first) + 2:
            lines.append("                （全文见 python tools/ws.py doc %s）" % name)
    else:
        lines.append("官方说明         未验证（element-docs.tsv 里这一行是空的）")

    if kind == "扩展":
        e = d["ext"].get(name)
        if e:
            lines.append("只有开扩展才出现   是（扩展「%s」，成本 %s 点，解锁 %s 项）"
                         % (name, _col(e, "cost"), _col(e, "unlocked")))
            _ev(ev, "扩展成本/解锁项", "data/extensions.tsv", "L0")
        else:
            lines.append("只有开扩展才出现   是（类型=扩展）")
            _ev(ev, "类型=扩展", "data/element-kinds.tsv", "L0")
    else:
        lines.append("只有开扩展才出现   未验证（数据表没有元素级的扩展开关列）")

    if blk is not None:
        cnt = _col(blk, "语料出现次数")
        if cnt:
            lines.append("语料出现次数       %s 次%s" % (cnt, "（0 = 语料里没出现过，不代表不能用）" if cnt == "0" else ""))
            _ev(ev, "语料出现 %s 次" % cnt, "data/action-blocks.tsv", _level_of_blocks(blk))
        # 类型口径差异（值 / 条件）：action-blocks 单列了 5 个「条件」型值
        ab_kind = _col(blk, "元素类型")
        if ab_kind and ab_kind != kind:
            lines.append("口径差异         action-blocks.tsv 把该元素标为「%s」（element-kinds.tsv 是「%s」；两个口径都能对上，"
                         "261 值 + 5 条件 = 266）" % (ab_kind, kind))
            _ev(ev, "action-blocks 元素类型=%s" % ab_kind, "data/action-blocks.tsv", "L0")
    else:
        lines.append("语料出现次数       未验证（action-blocks.tsv 没有这一行）")
        if kind == "扩展":
            lines.append("                （扩展不是调用，结构上不会作为元素出现；它只活在参数位置上）")
    out["身份"] = lines

    # ---- 2 参数
    lines = []
    ps = d["params"].get(name, [])
    df = d["dflt"].get(name, {})
    sig0 = blk is not None and "签名=0" in _col(blk, "数据侧证据")
    if not ps:
        if sig0:
            lines.append("无参数（签名 0 个）：省略值不适用")
            _ev(ev, "签名 0 个参数", "data/action-blocks.tsv", _level_of_blocks(blk))
        elif blk is not None:
            lines.append("未验证（param-docs.tsv 没有该元素的参数行；action-blocks.tsv 数据侧证据：%s）"
                         % (_col(blk, "数据侧证据") or "空"))
        else:
            lines.append("未验证（param-docs.tsv / action-blocks.tsv 都没有该元素）")
    else:
        lines.append("%s | %s | %s | %s | %s" % (_pad("序号 名称", 24), _pad("类型", 12),
                                                 _pad("能否省", 8), _pad("默认值", 40), "等级"))
        for r in ps:
            idx = _int(_col(r, "index"), 0)
            pname = _col(r, "name") or "（无参数名）"
            ptype = _col(r, "input_type") or "（无类型）"
            row = df.get(idx)
            if row is None:
                can_omit, val, nature, lvl = "未验证", "未验证", "", "未验证"
            else:
                can_omit = "可以" if _col(row, "尾参(文档口径可省)") == "是" else "不能省"
                val = _col(row, "默认值") or "未验证"
                nature = _col(row, "默认值性质")
                lvl = _col(row, "证据等级") or "未验证"
            vtxt = val
            if val in ("(无记录)", "无记录", ""):
                vtxt = "未验证（defaults-full.tsv 记为无记录）"
                lvl = "未验证"
            elif nature and nature not in ("", "无记录"):
                if nature == "类型占位":
                    vtxt = "%s（类型占位：写的是这个槽要填什么，不是省略时的取值）" % val
                elif nature == "下拉默认档":
                    vtxt = "%s（下拉首项推断，未验证）" % val
                elif nature == "字面值":
                    vtxt = "%s（字面值，可当默认值用）" % val
            lines.append("%s | %s | %s | %s | [%s]"
                         % (_pad("%d %s" % (idx + 1, pname), 24), _pad(ptype, 12),
                            _pad(can_omit, 8), vtxt, lvl))
            _ev(ev, "第%d个参数 %s 默认值" % (idx + 1, pname),
                "data/defaults-full.tsv", lvl)
        # 引擎实测与文档口径打架（param-exceptions.tsv 正向）
        for r in d["exc"].get(name, []):
            if "必须写到" in _col(r, "引擎实际要求写"):
                lines.append("冲突            数据表（签名/文档口径）：%s「%s」——%s  [L0]"
                             % ("", _col(r, "参数"), _col(r, "文档说可省")))
                lines.append("                引擎实测：%s（%s）  [%s]"
                             % (_col(r, "引擎实际要求写"), _col(r, "触发条件"),
                                _col(r, "证据等级") or "未验证"))
                _ev(ev, "参数要求冲突", "data/param-exceptions.tsv", _col(r, "证据等级"))

    # 冲突：语料参数个数 vs 签名（action-blocks.tsv 冲突列）
    if blk is not None:
        conflict = _col(blk, "冲突")
        if conflict and conflict != "-":
            lines.append("冲突            %s" % conflict)
            m = re.search(r"语料最少写\s*(\d+)\s*个参数\s*<\s*签名下限\s*(\d+)", conflict)
            if m:
                lines.append("                数据表（签名口径）：该元素最少要写 %s 个参数  [L1 signatures.md]"
                             % m.group(2))
                lines.append("                语料（导出产物）：最少只写 %s 个参数，游戏收得下  [L1 语料统计]"
                             % m.group(1))
            _ev(ev, "参数个数冲突：%s" % conflict, "data/action-blocks.tsv 冲突列", "L1")
    out["参数"] = lines

    # ---- 3 能出现在哪
    lines = []
    if blk is None:
        for disp, _colname in BLOCK_SLOTS:
            lines.append("%s 未验证（action-blocks.tsv 没有这一行）" % _pad(disp, 14))
        if kind == "扩展":
            lines.append("说明            扩展元素只出现在参数位置上，不是可调用的元素")
    else:
        any_yes = False
        for disp, colname in BLOCK_SLOTS:
            cell = _col(blk, colname)
            state, reason = _state_of(cell)
            lvl = _level_of_blocks(blk)
            if state == "可以":
                any_yes = True
                lines.append("%s 可以（仅语料）  [%s]" % (_pad(disp, 14), lvl))
            elif state == "不可以":
                lines.append("%s 不可以%s  [L0 数据侧]" % (_pad(disp, 14), "（%s）" % reason if reason else ""))
            else:
                lines.append("%s 未验证（语料没观测到，数据侧也没有禁止依据）" % _pad(disp, 14))
        _ev(ev, "五个块位置", "data/action-blocks.tsv", _level_of_blocks(blk))
        if not any_yes:
            lines.append("说明            五格都是「未验证」或「不可以」→ 这个元素的位置结论下不了，别当结论用")
    out["能出现在哪"] = lines

    # ---- 4 取值
    lines = []
    gen = d["generic_aliases"]
    bool_row = next((r for r in gen if _col(r, "字段类型") == "元素参数"), None)
    team_row = next((r for r in gen if _col(r, "字段类型") == "队伍参数"), None)
    hero_row = next((r for r in gen if _col(r, "字段类型") == "英雄参数"), None)
    got = False
    for r in ps:
        idx = _int(_col(r, "index"), 0)
        pname = _col(r, "name") or "（无参数名）"
        ptype = _col(r, "input_type")
        opts = [o for o in _col(r, "options").split("|") if o]
        al = d["aliases"].get((name, idx), [])
        ext_al = [a for a in al if _col(a, "字段类型") == "扩展下拉"]
        head = "%s %s" % (_pad("%d" % (idx + 1), 3), _pad(pname, 12))
        if opts:
            got = True
            shown = "、".join(opts[:10]) + ("…" if len(opts) > 10 else "")
            lines.append("%s %s 下拉全集 %d 项：%s  [L1 data/param-docs.tsv]" % (head, _pad(ptype, 10), len(opts), shown))
            if len(opts) > 10:
                lines.append("                （全集用 --json 看；text 只显示前 10 项）")
            if ext_al:
                lines.append("                其中 %d 项只有开扩展才出现（见扩展成本表）  [L1 data/dropdown-aliases.tsv]"
                             % len(ext_al))
        elif ptype == "Boolean":
            got = True
            canon = _col(bool_row, "规范取值") if bool_row else "真|假"
            alias = _col(bool_row, "别名") if bool_row else "开启|关闭|启用|禁用"
            lines.append("%s %s 布尔槽：规范词 %s；界面/导出词 %s 未验证被接受  [L0 data/dropdown-aliases.tsv]"
                         % (head, _pad(ptype, 10), canon, alias))
            lines.append("                布尔槽也接受比较表达式（如 所在队伍(事件玩家) == 队伍2），那是表达式不是词")
        elif ptype == "Team":
            got = True
            lines.append("%s %s 队伍槽：规范词 %s；别名 %s 写在动作参数里被拒（只在事件块选择器行合法）  [L2 E-51]"
                         % (head, _pad(ptype, 10),
                            _col(team_row, "规范取值") if team_row else "所有队伍|队伍1|队伍2",
                            _col(team_row, "别名") if team_row else "全部|双方"))
        elif ptype == "Hero":
            got = True
            lines.append("%s %s 英雄槽：必须写 英雄(<英雄名>)，裸英雄名被拒  [L2 E-51]"
                         % (head, _pad(ptype, 10)))
        else:
            lines.append("%s %s 无下拉（自由槽：%s），合法取值未验证"
                         % (head, _pad(ptype or "?", 10), ptype or "未知类型"))
        for a in al:
            if _col(a, "字段类型") != "下拉参数":
                continue
            got = True
            canon_v, alias_v = _col(a, "规范取值"), _col(a, "别名")
            accepted = _col(a, "别名是否被接受")
            if opts and canon_v and canon_v not in opts:
                lines.append("                冲突 下拉选项表（param-docs.tsv）：该槽没有「%s」  [L1]" % canon_v)
                lines.append("                     别名表（dropdown-aliases.tsv）：规范取值就是「%s」，别名「%s」%s  [%s]"
                             % (canon_v, alias_v, accepted, _col(a, "证据等级")))
                _ev(ev, "取值冲突：%s 是否含「%s」" % ("第%d个参数" % (idx + 1), canon_v),
                    "data/param-docs.tsv × data/dropdown-aliases.tsv", _col(a, "证据等级") or "L1")
            else:
                lines.append("                规范「%s」× 别名「%s」%s  [%s]"
                             % (canon_v, alias_v, accepted, _col(a, "证据等级")))
            _ev(ev, "第%d个参数 取值口径" % (idx + 1), "data/dropdown-aliases.tsv", _col(a, "证据等级"))
    # 布尔导出词 vs 下拉「无」：只在元素真有布尔槽时才挂这两条通用口径
    has_bool = any(_col(r, "input_type") == "Boolean" for r in ps)
    if has_bool:
        for a in gen:
            if _col(a, "字段类型") == "布尔设置项" and _col(a, "别名是否被接受").startswith("否"):
                got = True
                lines.append("布尔项写法的坑  规范「%s」× 导出显示词「%s」%s  [%s]"
                             % (_col(a, "规范取值"), _col(a, "别名"), _col(a, "别名是否被接受"),
                                _col(a, "证据等级")))
                _ev(ev, "布尔项词口径", "data/dropdown-aliases.tsv", _col(a, "证据等级"))
    if not got and not ps:
        lines.append("未验证（param-docs.tsv 没有该元素的参数行，取值无从谈起）")
    if has_bool and not any(_col(r, "options") for r in ps):
        lines.append("提示            下拉「无」与布尔导出词是两回事：布尔项写 开启/关闭；"
                     "选项里本来就有「无」的槽写「无」才对，选项含「全部禁用」的槽写「无」会整块被拒  [L2]")
    out["取值"] = lines

    # ---- 5 已知坑
    lines = []
    # 5.1 参数例外
    for r in d["exc"].get(name, []):
        lines.append("参数例外        %s：文档说可省=%s；引擎=%s；%s  [%s]"
                     % (_col(r, "参数"), _col(r, "文档说可省"), _col(r, "引擎实际要求写"),
                        _col(r, "触发条件"), _col(r, "证据等级") or "未验证"))
        _ev(ev, "参数例外（%s）" % _col(r, "参数"), "data/param-exceptions.tsv", _col(r, "证据等级"))
    # 5.2 上限 / 互斥：只收提到该元素名的行
    hits = []
    for r in d["limits"]:
        blob = _col(r, "限制项")
        if len(name) >= 3:
            blob += _col(r, "数值或互斥对") + _col(r, "备注")
        if name and name in blob:
            hits.append(r)
    for r in hits:
        lines.append("%s        %s：%s%s  [%s %s]"
                     % (_pad(_col(r, "类别"), 10), _col(r, "限制项"), _col(r, "数值或互斥对"),
                        "（%s）" % _col(r, "备注") if _col(r, "备注") else "",
                        _col(r, "证据等级") or "未验证", _col(r, "依据")))
        _ev(ev, "%s：%s" % (_col(r, "类别"), _col(r, "限制项")), "data/limits-mutex.tsv", _col(r, "证据等级"))
    # 5.3 断言表命中（docs/rules.tsv：关键词整词命中）
    rule_hits = []
    for r, toks in d["rules"]:
        if name in toks or name in _col(r, "场景"):
            rule_hits.append(r)
    for r in rule_hits[:6]:
        lines.append("断言表          【%s】禁止：%s" % (_col(r, "场景"), _col(r, "禁止")))
        lines.append("                正确：%s  [%s · %s · %s]"
                     % (_col(r, "正确"), _col(r, "证据"), _col(r, "级别"), _col(r, "依据")))
        _ev(ev, "断言表：%s" % _col(r, "场景"), "docs/rules.tsv", _col(r, "证据"))
    if len(rule_hits) > 6:
        lines.append("                …另有 %d 条提到该元素：python tools/ws.py rule %s"
                     % (len(rule_hits) - 6, name))
    if not lines:
        lines.append("未验证（param-exceptions / limits-mutex / rules.tsv 都没有点名该元素）")
    out["已知坑"] = lines
    return out


# ---------------------------------------------------------------- 设置键六段

def _setting_sections(name, ev):
    d = sdb()
    out = {}
    km = d["km"].get(name, [])
    st = d["st"].get(name, [])
    ss = d["ss"].get(name, [])
    hero = d["hero_keys"].get(name, [])
    is_hero = not (km or st or ss) and bool(hero)
    section_hit = ""

    # ---- 1 身份
    lines = []
    ktype = ""
    for r in km:
        ktype = ktype or _col(r, "类型")
    for r in ss:
        ktype = ktype or _col(r, "type")
    for r in st:
        ktype = ktype or _col(r, "type")
    lines.append("类型             设置键%s" % ("（%s）" % ktype if ktype else "（类型未验证）"))
    _ev(ev, "设置键 类型=%s" % (ktype or "未验证"),
        "data/key-map.tsv × data/setting-schemas.tsv" if km or ss else "data/settings.tsv", "L0")
    if km:
        pages = []
        for r in km:
            p = _col(r, "页名")
            if p and p not in pages:
                pages.append(p)
        lines.append("所属页面         %s%s" % ("、".join(pages[:6]), "…" if len(pages) > 6 else ""))
        cats = []
        for r in km:
            c = _col(r, "分类")
            if c and c not in cats:
                cats.append(c)
        if cats:
            lines.append("资产分类         %s" % "、".join(cats))
        _ev(ev, "所属页 %d 个 / 分类" % len(pages), "data/key-map.tsv", "L0")
    elif is_hero:
        pages = sorted({_col(r, "页") for r in hero if _col(r, "页")})
        lines.append("所属页面         英雄页：%s" % "、".join(pages))
        _ev(ev, "英雄页", "data/hero-setting-names.tsv", "L0")
    else:
        lines.append("所属页面         未验证（key-map.tsv 没有这个键）")
        for _b, _row in d["sections"].items():
            _note = _col(_row, "备注")
            if name and name in _note:
                lines.append("分区线索         该键在 settings-sections.tsv 的「%s」分区备注里被点名：%s  [L2]"
                             % (_col(_row, "分区"), _note))
                _ev(ev, "分区线索（%s）" % _col(_row, "分区"), "data/settings-sections.tsv", "L2")
                section_hit = _col(_row, "分区")
                break
    if ("设置键", name) in d["comp"]:
        row = d["comp"][("设置键", name)]
        lines.append("完备性           %s（%s）" % (_col(row, "差集类型"), _col(row, "出处")))
        _ev(ev, _col(row, "差集类型"), "data/element-completeness.tsv", "L1")
    lines.append("官方说明         未验证（数据表里设置键没有说明文本）")
    lines.append("只有开扩展才出现   未验证（数据表没有键级的扩展开关列）")
    out["身份"] = lines

    # ---- 2 参数（一个值槽；不同 schema 下范围可能不同）
    lines = []
    variants = []          # (来源, schema, 类型, 显示文本, 范围文本或 "")
    seen = set()
    for r in ss:
        schema, typ = _col(r, "schema"), _col(r, "type")
        lo, hi, dflt_id = _col(r, "min"), _col(r, "max"), _col(r, "default")
        parts = []
        if dflt_id:
            parts.append("默认档 %s（串ID，未解析成文字）" % dflt_id)
        rng_txt = "%s~%s" % (lo or "?", hi or "?") if (lo or hi) else ""
        if rng_txt:
            parts.append("范围 %s" % rng_txt)
        txt = "；".join(parts) or "未验证"
        key = (schema, txt)
        if key not in seen:
            seen.add(key)
            variants.append(("setting-schemas.tsv", schema or "?", typ or "?", txt, rng_txt))
    for r in st:
        schema, typ = _col(r, "schema"), _col(r, "type")
        vals = _col(r, "values")
        rng_txt, dflt = _split_values(vals)
        txt = "值表 %s%s" % (vals or "（空）", "（默认 %s）" % dflt if dflt else "")
        key = (schema, txt)
        if key not in seen:
            seen.add(key)
            variants.append(("settings.tsv", schema or "?", typ or "?", txt, rng_txt))
    rng = d["rng"].get(name, [])
    if not variants and not rng:
        lines.append("未验证（setting-schemas.tsv / settings.tsv / setting-ranges.tsv 都没有值口径）")
    else:
        lines.append("%s | %s | %s | %s" % (_pad("序号 名称", 18), _pad("类型", 10), _pad("能否省", 8),
                                            "默认值 / 范围"))
        for src, schema, typ, txt, _rng in variants[:4]:
            lines.append("%s | %s | %s | %s  [L0 %s · %s]"
                         % (_pad("1 值（%s）" % schema, 18), _pad(typ, 10),
                            _pad("不能省", 8), txt, src, schema))
        if len(variants) > 4:
            lines.append("…另有 %d 套 schema 值口径（同一个键按页不同），全集见 --json"
                         % (len(variants) - 4))
        _ev(ev, "值槽类型/范围/默认", "data/setting-schemas.tsv × data/settings.tsv", "L0")
        for r in rng:
            lines.append("全局范围         %s ~ %s  [L0 data/setting-ranges.tsv]"
                         % (_col(r, "min"), _col(r, "max")))
            _ev(ev, "范围 %s~%s" % (_col(r, "min"), _col(r, "max")), "data/setting-ranges.tsv", "L0")
        # 范围口径不唯一 → 冲突全打（同一个键名，按页不同）
        by_range = {}
        for _src, schema, _typ, _txt, rng_txt in variants:
            if rng_txt:
                by_range.setdefault(rng_txt, set()).add(schema)
        if len(by_range) > 1:
            lines.append("冲突            同一个键在不同页范围不同，写之前先确认是哪一页：")
            for rng_txt in sorted(by_range):
                schemas = sorted(by_range[rng_txt])
                lines.append("                %s（%s）  [L0 setting-schemas.tsv / settings.tsv]"
                             % (rng_txt, "、".join(schemas[:4]) + ("…" if len(schemas) > 4 else "")))
            _ev(ev, "跨页范围不一致（%d 套）" % len(by_range),
                "data/setting-schemas.tsv × data/settings.tsv", "L0")
            # 同一页两套范围：数据表自己打架，也要打出来
            per_schema = {}
            for _src, schema, _typ, _txt, rng_txt in variants:
                if rng_txt:
                    per_schema.setdefault(schema, set()).add(rng_txt)
            same_page = {k: v for k, v in per_schema.items() if len(v) > 1}
            for k, vs in list(same_page.items())[:4]:
                lines.append("冲突            同一页「%s」有两套范围：%s  [L0 两张表/两行自相矛盾]"
                             % (k, "、".join(sorted(vs))))
    out["参数"] = lines

    # ---- 3 能出现在哪
    lines = []
    schemas = []
    for r in km:
        s = _col(r, "页名")
        if s and s not in schemas:
            schemas.append(s)
    for r in st:
        s = _col(r, "schema")
        if s and s not in schemas:
            schemas.append(s)
    for r in ss:
        s = _col(r, "schema")
        if s and s not in schemas:
            schemas.append(s)
    modes = []
    for s in schemas:
        for m in d["schema_modes"].get(s, []):
            if m not in modes:
                modes.append(m)
    if "综合" in schemas:
        lines.append("%s 可以（该键的 schema 就是「综合」）  [L0]" % _pad("综合块", 10))
        _ev(ev, "综合块", "data/setting-schemas.tsv", "L0")
    else:
        lines.append("%s 未验证（schema 里没有「综合」，综合块收不收未验）" % _pad("综合块", 10))
    if modes:
        lines.append("%s 可以：%s%s  [L0 data/mode-schemas.tsv]"
                     % (_pad("模式块", 10), "、".join(modes[:8]), "…（共 %d 个模式）" % len(modes) if len(modes) > 8 else ""))
        _ev(ev, "模式块 %d 个模式" % len(modes), "data/mode-schemas.tsv", "L0")
    else:
        lines.append("%s 未验证" % _pad("模式块", 10))
    if name in d["lob"]:
        lines.append("%s 可以（在数据/lobby-keys.tsv 里，in_stu_schema=%s）  [L0]"
                     % (_pad("大厅块", 10), _col(d["lob"][name][0], "in_stu_schema")))
        _ev(ev, "大厅块", "data/lobby-keys.tsv", "L0")
    else:
        lines.append("%s 未验证（不在 lobby-keys.tsv，不能据此判否）" % _pad("大厅块", 10))
    hero_schemas = [s for s in schemas if s in HERO_PAGE_SCHEMAS]
    if is_hero or hero_schemas:
        lines.append("%s 可以（%s）  [L0]"
                     % (_pad("英雄页", 10), "、".join(hero_schemas) if hero_schemas else "hero-setting-names.tsv"))
        _ev(ev, "英雄页", "data/hero-setting-names.tsv", "L0")
    else:
        lines.append("%s 未验证" % _pad("英雄页", 10))
    if section_hit:
        lines.append("%s 可以（settings-sections.tsv「%s」分区里点名了这个键，可写性=%s）  [L2]"
                     % (_pad(section_hit + "块", 10), section_hit,
                        _col(next((r for r in d["sections"].values() if _col(r, "分区") == section_hit), {}),
                             "可写性") or "未验证"))
        _ev(ev, "%s块" % section_hit, "data/settings-sections.tsv", "L2")
    for r in d["lay"].get(name, []):
        lines.append("层限制           只能写在「%s」（%s）  [L0 data/key-parent-layers.tsv]"
                     % (_col(r, "allowed_parents"), _col(r, "source")))
        _ev(ev, "层限制", "data/key-parent-layers.tsv", "L0")
    for r in d["compat"].get(name, []):
        lines.append("实测层级         %s：%s  [L2 data/setting-compat.tsv]"
                     % (_col(r, "层"), _col(r, "证据")))
        _ev(ev, "实测层级", "data/setting-compat.tsv", "L2")
    out["能出现在哪"] = lines

    # ---- 4 取值
    lines = []
    got = False
    for r in d["ev"].get(name, []):
        got = True
        vals = [v for v in _col(r, "合法值原文").split("|") if v]
        lines.append("合法值           %d 个：%s  [L1 data/enum-values.tsv]"
                     % (len(vals), "、".join(vals[:12]) + ("…" if len(vals) > 12 else "")))
        if _col(r, "依据"):
            lines.append("                依据 %s" % _col(r, "依据"))
        if _col(r, "备注"):
            lines.append("                备注 %s" % _col(r, "备注"))
        _ev(ev, "合法值 %d 个" % len(vals), "data/enum-values.tsv", "L1")
    types = {_col(r, "type") for r in ss if _col(r, "type")}
    if "Bool" in types:
        got = True
        lines.append("布尔项          写 开启 / 关闭（L2 实测）；导出显示词 禁用 / 启用 会被整块拒（L2）；"
                     "另有 2 个键的资产词是 是 / 否，引擎吃不吃未验（L0）  [data/dropdown-aliases.tsv]")
        _ev(ev, "布尔项词口径", "data/dropdown-aliases.tsv", "L2")
    for r in ss:
        if _col(r, "on") or _col(r, "off"):
            lines.append("schema 词对     %s：on=%s / off=%s  [L0 setting-schemas.tsv]"
                         % (_col(r, "schema"), _col(r, "on"), _col(r, "off")))
            got = True
    if not got:
        shown = 0
        for r in st:
            if _col(r, "values"):
                got = True
                if shown < 6:
                    lines.append("值表口径         %s（%s）：%s  [L0 data/settings.tsv]"
                                 % (_col(r, "schema"), _col(r, "type"), _col(r, "values")))
                shown += 1
        if shown > 6:
            lines.append("…另有 %d 个 schema 的值表口径，见 --json（该键按页不同，别跨页照抄）"
                         % (shown - 6))
        if not got:
            lines.append("未验证（没有枚举值、没有布尔词对、值表也没有可写值）")
    out["取值"] = lines

    # ---- 5 已知坑
    lines = []
    for r in d["ver"].get(name, []):
        lines.append("实测结论         %s  [L2 data/verified-keys.tsv]" % _col(r, "evidence"))
        _ev(ev, "实测 %s" % _col(r, "evidence"), "data/verified-keys.tsv", "L2")
    for r in d["lay"].get(name, []):
        lines.append("层级             只能写在「%s」，换个块会被拒  [L0 %s]"
                     % (_col(r, "allowed_parents"), _col(r, "source") or "key-parent-layers.tsv"))
    hits = []
    for r in d["limits"]:
        blob = _col(r, "限制项")
        if len(name) >= 3:
            blob += _col(r, "数值或互斥对") + _col(r, "备注")
        if name and name in blob:
            hits.append(r)
    for r in hits:
        lines.append("%s        %s：%s  [%s %s]"
                     % (_pad(_col(r, "类别"), 10), _col(r, "限制项"), _col(r, "数值或互斥对"),
                        _col(r, "证据等级") or "未验证", _col(r, "依据")))
        _ev(ev, "%s：%s" % (_col(r, "类别"), _col(r, "限制项")), "data/limits-mutex.tsv",
            _col(r, "证据等级"))
    rule_hits = [r for r, toks in d["rules"] if name in toks]
    for r in rule_hits[:4]:
        lines.append("断言表          【%s】禁止：%s；正确：%s  [%s · %s · %s]"
                     % (_col(r, "场景"), _col(r, "禁止"), _col(r, "正确"),
                        _col(r, "证据"), _col(r, "级别"), _col(r, "依据")))
        _ev(ev, "断言表：%s" % _col(r, "场景"), "docs/rules.tsv", _col(r, "证据"))
    if name in d["st"] and len(d["st"][name]) > 1:
        schemas = {_col(r, "schema") for r in d["st"][name]}
        lines.append("同名多页         该键在 %d 个 schema 下都有条目（%s），值/范围按页不同，别跨页照抄  [L0]"
                     % (len(schemas), "、".join(sorted(schemas)[:6])))
    if not lines:
        lines.append("未验证（verified-keys / limits-mutex / rules.tsv 都没有点名该键）")
    out["已知坑"] = lines
    return out


# ---------------------------------------------------------------- 设置块六段

def _block_sections(name, ev):
    d = sdb()
    row = d["sections"].get(name)
    out = {}
    lines = ["类型             设置块（不是元素，也不是设置键）"]
    sub = {"启用地图": "模式 > <模式名> > 启用地图", "禁用地图": "模式 > <模式名> > 禁用地图"}.get(name)
    if row is not None:
        lines.append("分区             %s" % _col(row, "分区"))
        lines.append("可写性           %s" % _col(row, "可写性"))
        lines.append("键来源           %s" % _col(row, "键来源"))
        _ev(ev, "分区/可写性/键来源", "data/settings-sections.tsv", "L2")
    elif sub:
        lines.append("分区             地图")
        lines.append("可写性           可写（实测）")
        lines.append("块写法           %s" % sub)
        _ev(ev, "地图子块写法（golden2.ow 实测）", "data/settings-sections.tsv", "L2")
    else:
        lines.append("分区             未验证")
    lines.append("官方说明         未验证（设置块没有说明文本）")
    lines.append("只有开扩展才出现   未验证")
    out["身份"] = lines

    out["参数"] = ["未验证（设置块里不是「键: 值」，是名字列表 / 子块；格式见 docs/format-spec.md）"]
    lines = []
    if sub:
        lines.append("%s 可以（写在模式块之下）  [L2 golden2.ow]" % _pad("模式块", 10))
        for s in ("综合块", "大厅块", "英雄页"):
            lines.append("%s 未验证（数据只说明它挂在模式块下，别处没测过）" % _pad(s, 10))
        _ev(ev, "地图子块位置", "data/settings-sections.tsv", "L2")
    else:
        for s in KEY_SLOTS:
            lines.append("%s 未验证" % _pad(s, 10))
    out["能出现在哪"] = lines
    if sub:
        out["取值"] = ["地图名 + 编号（每行一个）：地图名查 python tools/ws.py map-code <关键词>  [L2 docs/format-spec.md]"]
    else:
        out["取值"] = ["未验证（该分区在数据表里没有取值口径）"]
    out["已知坑"] = ["未验证（param-exceptions / limits-mutex / rules.tsv 都没有点名该块）"]
    return out


# ---------------------------------------------------------------- 组装

def _struct(name, kind, ev):
    """给 --json 的结构化视图：和六段正文同源（表 → 结构），不额外推断。"""
    d = db()
    out = {}
    if kind in ("动作", "值", "事件", "扩展"):
        ps = d["params"].get(name, [])
        df = d["dflt"].get(name, {})
        params = []
        for r in ps:
            idx = _int(_col(r, "index"), 0)
            row = df.get(idx, {})
            params.append({
                "序号": idx + 1,
                "名称": _col(r, "name") or "",
                "类型": _col(r, "input_type") or "",
                "可省": "是" if _col(row, "尾参(文档口径可省)") == "是" else ("否" if row else "未验证"),
                "默认值": _col(row, "默认值") or "",
                "默认值性质": _col(row, "默认值性质") or "",
                "来源": _col(row, "来源") or "",
                "证据等级": _col(row, "证据等级") or "未验证",
                "下拉": [o for o in _col(r, "options").split("|") if o],
            })
        blk = d["blocks"].get(name)
        slots = {}
        for disp, colname in BLOCK_SLOTS:
            st, reason = _state_of(_col(blk, colname)) if blk is not None else ("未验证", "")
            slots[disp] = {"状态": st, "说明": reason,
                           "证据等级": _level_of_blocks(blk) if blk is not None else "未验证"}
        out["参数结构"] = params
        out["块位置"] = slots
        out["取值结构"] = [
            {"序号": p["序号"], "名称": p["名称"], "类型": p["类型"], "下拉全集": p["下拉"],
             "别名": [{"规范": _col(a, "规范取值"), "别名": _col(a, "别名"),
                       "接受": _col(a, "别名是否被接受"), "导出显示词": _col(a, "是否导出显示词"),
                       "证据等级": _col(a, "证据等级")}
                      for a in d["aliases"].get((name, p["序号"] - 1), [])]}
            for p in params]
    else:
        s = sdb()
        params = []
        for r in s["ss"].get(name, []):
            params.append({"序号": 1, "名称": "值（%s）" % (_col(r, "schema") or "?"),
                           "类型": _col(r, "type"), "可省": "否",
                           "范围": "%s~%s" % (_col(r, "min") or "?", _col(r, "max") or "?"),
                           "默认档": _col(r, "default"), "证据等级": "L0",
                           "来源": "setting-schemas.tsv"})
        for r in s["st"].get(name, []):
            rng, dflt = _split_values(_col(r, "values"))
            params.append({"序号": 1, "名称": "值（%s）" % (_col(r, "schema") or "?"),
                           "类型": _col(r, "type"), "可省": "否",
                           "范围": rng, "默认": dflt, "值表原文": _col(r, "values"),
                           "证据等级": "L0", "来源": "settings.tsv"})
        out["参数结构"] = params
        out["取值结构"] = [{"合法值": [v for v in _col(r, "合法值原文").split("|") if v],
                            "依据": _col(r, "依据"), "证据等级": "L1"}
                           for r in s["ev"].get(name, [])]
        out["块位置"] = {"适用": False,
                         "说明": "设置键不是工坊元素，五格（事件块/持续/条件/子程序）不适用；"
                                 "位置口径见正文的 综合块 / 模式块 / 大厅块 / 英雄页"}
    out["已知坑结构"] = [e for e in ev if e["凭据"] in
                         ("data/param-exceptions.tsv", "data/limits-mutex.tsv", "docs/rules.tsv",
                          "data/setting-compat.tsv", "data/verified-keys.tsv")]
    out["出处结构"] = ev
    return out


def build(query, force=None):
    """返回 (dict, exit_code)。dict 六段齐全；找不到时 dict 只有错误信息。"""
    d = db()
    kind, name = resolve(query, force=force)
    if kind is None:
        return {"查询": query, "命中": None, "候选": name,
                "错误": "没有叫「%s」的元素 / 设置键 / 设置块" % clean_name(query)}, 2
    ev = []
    if kind in ("动作", "值", "事件", "扩展"):
        secs = _element_sections(name, kind, ev)
    elif kind == "设置块":
        secs = _block_sections(name, ev)
    else:
        secs = _setting_sections(name, ev)

    others = collisions(name, kind)
    if others:
        secs["身份"].append("同名的另一个   %s（本条按「%s」回答；要看另一个加 --as %s）"
                            % ("、".join(others), kind, others[0]))

    # 六段兜底：任何一段空了都写「未验证」，不许省略
    for s in SECTIONS:
        if not secs.get(s):
            secs[s] = ["未验证（该段没有可用读数）"]

    # 6 出处
    seen, src = set(), []
    for e in ev:
        k = (e["项"], e["凭据"], e["等级"])
        if k in seen:
            continue
        seen.add(k)
        src.append(e)
    secs["出处"] = ["%s ← %s  [%s]" % (_pad(e["项"], 34), e["凭据"], e["等级"]) for e in src] or \
                   ["未验证（没有任何读数）"]

    # 完整度（阶段 1 完成度指标用）：从结构化视图算，不从正文措辞猜
    st = _struct(name, kind, ev)
    is_elem = kind in ("动作", "值", "事件", "扩展")
    params_struct = st.get("参数结构") or []
    has_param = bool(params_struct) or ("无参数" in " ".join(secs["参数"]))
    if is_elem:
        slots = st.get("块位置") or {}
        has_block = any(v.get("状态") in ("可以", "不可以") for v in slots.values())
    else:
        has_block = any(("可以" in ln and "未验证" not in ln) for ln in secs["能出现在哪"])
    literal = any(p.get("默认值性质") == "字面值" for p in params_struct)
    if is_elem:
        can_go = any(v.get("状态") == "可以" for v in (st.get("块位置") or {}).values())
    else:
        can_go = any(("可以" in ln and "未验证" not in ln) for ln in secs["能出现在哪"])

    doc = {
        "查询": query,
        "命中": name,
        "类型": kind,
        "身份": secs["身份"],
        "参数": secs["参数"],
        "能出现在哪": secs["能出现在哪"],
        "取值": secs["取值"],
        "已知坑": secs["已知坑"],
        "出处": secs["出处"],
        "状态": {
            "缺段": [s for s in SECTIONS if not secs.get(s)],
            "参数段有读数": has_param,
            "参数段有字面值默认": literal,
            "块/位置段有读数": has_block,
            "有可以出现的位置": can_go,
        },
    }
    doc.update(st)
    return doc, 0


def render(doc, brief=False):
    if doc.get("命中") is None:
        lines = [doc["错误"]]
        if doc.get("候选"):
            lines.append("相近的有：" + "、".join(doc["候选"]))
        lines.append("（名字接受 动作 / 值 / 事件 / 设置键 / 设置块；带参数写法如「伤害(玩家, 玩家, 5)」只取名字）")
        return "\n".join(lines)
    head = "=== %s（%s） ===" % (doc["命中"], doc["类型"])
    lines = [head]
    show = ["身份", "已知坑"] if brief else SECTIONS
    for i, s in enumerate(SECTIONS):
        if s not in show:
            continue
        lines.append("[%d] %s" % (SECTIONS.index(s) + 1, s))
        for ln in doc[s]:
            lines.append("  " + ln)
    if brief:
        lines.append("（--brief 只给身份 + 已知坑；全量见 `知道 %s`，机器读加 --json）" % doc["命中"])
    return "\n".join(lines)


# ---------------------------------------------------------------- 固定名单回归（selftest 用）

# 每类型 10 个，写死不随机（含带空格名、0 参元素、同名要 --as 的、缺数据的）。
# 换名单必须同时能解释为什么换；禁止改成 random.sample。
KNOW_SELFTEST = {
    "动作": ["伤害", "传送", "创建HUD文本", "设置最大生命值", "等待",
             "End", "If", "Else If", "For 全局变量", "生成机器人"],
    "值": ["生命值", "事件玩家", "真", "玩家数量", "正在使用技能 1",
           "正在装填", "全局变量", "矢量", "自定义字符串", "射线命中玩家"],
    "设置键": ["获胜得分", "游戏模式开始", ("生命值", "设置键"), "技能冷却时间",
               "返回大厅", "地图轮换", "复生时间", "英雄限制", "描述", "模式名称"],
}


def selftest_check(cli_samples=3):
    """固定名单回归：六段全在 + 退出码 0。返回 (问题列表, 统计行)。

    走的是 CLI 调用的同一套函数（build/run 的返回值就是 sys.exit 的码），
    另外对三种类型各真跑一次子进程，确认 argparse 到 exit 这段也通。
    """
    import subprocess
    from types import SimpleNamespace
    problems = []
    total = 0
    for kind, names in KNOW_SELFTEST.items():
        for item in names:
            name, force = (item, None) if isinstance(item, str) else item
            total += 1
            args = SimpleNamespace(name=name, brief=False, json=True, audit=False,
                                   out="", as_type=force)
            try:
                doc, code = build(name, force=force)
            except Exception as e:  # noqa: BLE001
                problems.append("%s / %s 崩溃：%s: %s" % (kind, name, type(e).__name__, e))
                continue
            if code != 0:
                problems.append("%s / %s 退出码 %d" % (kind, name, code))
                continue
            missing = [x for x in SECTIONS if not doc.get(x)]
            if missing:
                problems.append("%s / %s 缺段：%s" % (kind, name, "、".join(missing)))
    # 真子进程抽样：确认 argparse → 退出码 这段没断
    ws = os.path.join(TOOLS, "ws.py")
    tried = 0
    for kind, names in KNOW_SELFTEST.items():
        if tried >= cli_samples:
            break
        item = names[0]
        name, force = (item, None) if isinstance(item, str) else item
        cmd = [sys.executable, ws, "知道", name, "--json"]
        if force:
            cmd += ["--as", force]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        tried += 1
        if r.returncode != 0:
            problems.append("%s / %s 子进程退出码 %d" % (kind, name, r.returncode))
        elif '"命中"' not in (r.stdout or ""):
            problems.append("%s / %s 子进程没吐出 JSON" % (kind, name))
    return problems, ("「知道」六段回归：%d 个固定名字%s" %
                      (total, "全部通过" if not problems else "有问题"))


# ---------------------------------------------------------------- 全量验收

def _universes():
    d = sdb()
    acts = sorted(n for n, k in d["kinds"].items() if k == "动作")
    vals = sorted(n for n, k in d["kinds"].items() if k == "值")
    evts = sorted(n for n, k in d["kinds"].items() if k == "事件")
    exts = sorted(n for n, k in d["kinds"].items() if k == "扩展")
    keys = set(d["st"]) | set(d["ss"]) | set(d["ver"]) | set(d["lob"]) | \
        set(d["lay"]) | set(d["compat"]) | set(d["ev"])
    keys = sorted(k for k in keys if k and "%" not in k and "$" not in k)
    return acts, vals, keys, evts, exts


def audit(out_path="", verbose=True):
    """全量跑一遍：0 崩溃 / 0 缺段 + unanswered.tsv（阶段 1 完成度指标）。

    两套口径都算，不挑好看的那个：
      宽松：参数段没有任何读数 且 位置段没有任何读数（连「不可以」都没有）
      严格：没有字面值默认（类型占位不算默认值）且 位置段一格「可以」都没有
    """
    acts, vals, keys, evts, exts = _universes()
    groups = [("动作", acts), ("值", vals), ("设置键", keys),
              ("事件", evts), ("扩展", exts)]
    rows, strict, crash, missing = [], [], [], []
    per_group = {}
    for label, names in groups:
        stat = {"总数": len(names), "有参数读数": 0, "有位置读数": 0, "严格未答": 0}
        for n in names:
            try:
                doc, code = build(n)
            except Exception as e:  # noqa: BLE001  —— 崩溃必须计数，不能静默
                crash.append((label, n, "%s: %s" % (type(e).__name__, e)))
                continue
            if code != 0 or "状态" not in doc:
                crash.append((label, n, "退出码 %s" % code))
                continue
            st = doc["状态"]
            stat["有参数读数"] += 1 if st["参数段有读数"] else 0
            stat["有位置读数"] += 1 if st["块/位置段有读数"] else 0
            if st["缺段"]:
                missing.append((label, n, "、".join(st["缺段"])))
            if not (st["参数段有读数"] or st["块/位置段有读数"]):
                rows.append(("宽松", label, n, "参数段无读数；位置段无读数"))
            if not st["参数段有字面值默认"] and not st["有可以出现的位置"]:
                stat["严格未答"] += 1
                strict.append(("严格", label, n,
                               "无字面值默认（只有类型占位/无记录）；位置段没有一格「可以」"))
        per_group[label] = stat

    if out_path:
        TAB, NL = chr(9), chr(10)
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(TAB.join(["口径", "类别", "元素名", "原因"]) + NL)
            for r in strict + rows:
                f.write(TAB.join(r) + NL)
    if verbose:
        total = sum(len(n) for _l, n in groups)
        print("全量：%s = %d 个" % (" / ".join("%s %d" % (l, len(n)) for l, n in groups), total))
        print("契约口径（动作/值/设置键）：%d 个" % (len(acts) + len(vals) + len(keys)))
        print("崩溃 %d 个%s" % (len(crash),
                              "：" + "；".join("%s/%s(%s)" % c for c in crash[:8]) if crash else "（0 = 没有一个崩）"))
        print("缺段 %d 个%s" % (len(missing),
                              "：" + "；".join("%s/%s(%s)" % m for m in missing[:8]) if missing else "（0 = 六段都齐）"))
        for label, stat in per_group.items():
            print("  %-4s %4d 个｜参数段有读数 %4d｜位置段有读数 %4d｜严格未答 %4d"
                  % (label, stat["总数"], stat["有参数读数"], stat["有位置读数"], stat["严格未答"]))
        print("未答计数（宽松）%d 个；未答计数（严格）%d 个" % (len(rows), len(strict)))
        for r in (strict + rows)[:15]:
            print("   - [%s] %s / %s（%s）" % r)
        if out_path:
            print("已写入 %s（%d 行）" % (out_path, len(strict) + len(rows)))
    return 0 if not crash and not missing else 1


# ---------------------------------------------------------------- 入口

def run(args):
    """ws.py 知道 <名字> [--brief] [--json] / 知道 --audit [--out]"""
    name = getattr(args, "name", None)
    if getattr(args, "audit", False):
        return audit(getattr(args, "out", "") or "")
    if not name:
        print("用法：python tools/ws.py 知道 <名字> [--brief|--json]")
        print("      python tools/ws.py 知道 --audit [--out stage1/unanswered.tsv]")
        return 2
    doc, code = build(name, force=getattr(args, "as_type", None))
    if getattr(args, "json", False):
        import json as _json
        print(_json.dumps(doc, ensure_ascii=False, indent=1))
        return code
    print(render(doc, brief=getattr(args, "brief", False)))
    return code


if __name__ == "__main__":
    sys.exit(run(type("A", (), {"name": sys.argv[1] if len(sys.argv) > 1 else None,
                                "brief": "--brief" in sys.argv,
                                "json": "--json" in sys.argv,
                                "audit": "--audit" in sys.argv,
                                "out": ""})()))
