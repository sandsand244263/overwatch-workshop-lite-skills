#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从游戏导出生成 data/ 下的全部数据表。禁止手改产物。

用法：
  python gen_data.py --src 导出目录/export-20261020 --out ../data

产物（每个文件头都带 build / 导出时间 / 生成脚本）：
  signatures.md   动作 + 值函数参数，下拉参数直接标出可选值
  dropdowns.tsv   每个下拉参数的完整选项（找不到选项的标 UNKNOWN）
  settings.tsv    设置项：schema / 键 / 类型 / 可选值
  enums.md        英雄 / 地图 / 下拉选项全集
  strings.md      文本选项（自定义字符串可用的常量文本）
"""
import argparse
import datetime
import json
import os
import re
import sys

TYPE_HINTS = {
    "Player": "玩家",
    "Team": "队伍",
    "Float": "数值",
    "Number": "数值",
    "Vector": "向量",
    "Boolean": "布尔",
    "String": "字符串",
    "Hero": "英雄",
    "Map": "地图",
    "Dropdown": "选择",
    "GenericInput": "通用",
    "Variable": "变量",
    "Button": "按键",
}


def type_of(param):
    raw = param.get("InputType") or param.get("InferredType") or ""
    return TYPE_HINTS.get(raw, "")


def load_build(src, settings_words=None):
    for cand in (settings_words or "", os.path.join(src, "export.log"), os.path.join(src, "settings_words.txt")):
        if cand and os.path.exists(cand):
            txt = open(cand, encoding="utf-8", errors="ignore").read()
            m = re.search(r"Overwatch build ([\w.]+)", txt)
            if m:
                return m.group(1)
    return "unknown"


def dropdown_map(ws):
    """DropdownId -> [选项名...]"""
    out = {}
    for d in ws.get("Dropdowns") or []:
        did = d.get("Id")
        opts = [o.get("DisplayName") for o in (d.get("Options") or []) if o.get("DisplayName")]
        if did:
            out[did] = opts
    return out


def render_signatures(ws, dd, build, stamp):
    lines = [
        "<!-- 自动生成，禁止手改：%s -->" % stamp,
        "# 参数签名（动作 %d / 值函数 %d）" % (len(ws.get("Actions") or []), len(ws.get("Values") or [])),
        "",
        "格式：`函数(参数名:类型)`。类型为 `选择` 的参数，方括号里就是**唯一合法的取值**，"
        "按括号里的词写，别自造。",
        "",
        "## 动作",
        "",
        "```text",
    ]
    unknown = []
    for kind, key in (("动作", "Actions"), ("值函数", "Values")):
        if kind == "值函数":
            lines += ["```", "", "## 值函数", "", "```text"]
        for entry in sorted(ws.get(key) or [], key=lambda e: e.get("DisplayName") or ""):
            name = (entry.get("DisplayName") or "").strip()
            if not name:
                continue
            parts = []
            for idx, p in enumerate(entry.get("Parameters") or []):
                pname = (p.get("Name") or "").strip() or "_"
                hint = type_of(p)
                label = "%s:%s" % (pname, hint) if hint else pname
                if p.get("InferredType") == "Dropdown":
                    opts = dd.get(p.get("DropdownId") or "", [])
                    if not opts:
                        unknown.append((name, idx, pname))
                    elif len(opts) <= 8:
                        label += "[" + "|".join(opts) + "]"
                    else:
                        label += "[%s|…共%d项]" % ("|".join(opts[:4]), len(opts))
                parts.append(label)
            lines.append("%s(%s)" % (name, ", ".join(parts)))
    lines += ["```", ""]
    if unknown:
        lines += ["## 选项未知的参数（%d 个）" % len(unknown), "",
                  "数据里查不到对应下拉表，生成时保守处理：不要写这些位置，或先跑探针确认。", ""]
        for name, idx, pname in unknown[:40]:
            lines.append("- %s 第 %d 个参数 `%s`" % (name, idx + 1, pname))
        lines.append("")
    return "\n".join(lines)


def render_dropdowns(ws, dd):
    rows = ["func\tparam_index\tparam_name\toptions"]
    for key in ("Actions", "Values"):
        for entry in ws.get(key) or []:
            name = (entry.get("DisplayName") or "").strip()
            for idx, p in enumerate(entry.get("Parameters") or []):
                if p.get("InferredType") != "Dropdown":
                    continue
                opts = dd.get(p.get("DropdownId") or "", [])
                rows.append("%s\t%d\t%s\t%s" % (name, idx, (p.get("Name") or "_").strip(),
                                             "|".join(opts) if opts else "UNKNOWN"))
    return "\n".join(rows)


def render_defaults(ws):
    """每个参数的默认值：省略尾部参数时游戏实际用什么。"""
    rows = ["func	param_index	param_name	default"]
    for key in ("Actions", "Values"):
        for entry in ws.get(key) or []:
            name = (entry.get("DisplayName") or "").strip()
            for idx, p in enumerate(entry.get("Parameters") or []):
                dv = p.get("DefaultValue")
                if isinstance(dv, dict):
                    val = dv.get("DisplayName") or str(dv.get("Value") or "")
                elif dv is not None:
                    val = str(dv)
                elif p.get("InferredType") == "Dropdown":
                    val = "（下拉默认档）"
                else:
                    val = "（无）"
                rows.append("%s	%d	%s	%s" % (name, idx, (p.get("Name") or "_").strip(), val))
    return chr(10).join(rows)


def render_settings(settings_path):
    rows = ["schema\tkey\ttype\tvalues"]
    if not os.path.exists(settings_path):
        return "\n".join(rows)
    seen = set()
    for line in open(settings_path, encoding="utf-8", errors="ignore"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 5 or line.startswith("["):
            continue
        schema, key, typ = parts[0], parts[1], parts[2]
        vals = [p for p in parts[3:5] if p and p not in ("-", "无")]
        rec = (schema, key, typ, "|".join(vals))
        if rec in seen:
            continue
        seen.add(rec)
        rows.append("\t".join(rec))
    return "\n".join(rows)


def render_enums(ws, heroes, maps, dd):
    lines = ["<!-- 自动生成，禁止手改 -->", "# 枚举全集", ""]
    hero_list = list(heroes.values()) if isinstance(heroes, dict) else heroes
    hs = sorted({h.get("Name") for h in hero_list if h.get("IsHero") and h.get("Name")})
    lines += ["## 英雄（%d）" % len(hs), "", "```text"] + hs + ["```", ""]

    base, variants = [], []
    map_list = list(maps.values()) if isinstance(maps, dict) else maps
    for m in map_list:
        nm = (m.get("Name") or "").strip()
        if nm:
            base.append(nm)
        for v in m.get("CelebrationVariants") or []:
            vn = ((v.get("MapInfo") or {}).get("VariantName") or "").strip()
            if vn:
                variants.append(vn)
    lines += ["## 地图（基版 %d / 节日变体 %d）" % (len(set(base)), len(set(variants))), "", "```text"]
    lines += sorted(set(base))
    lines += ["```", "", "### 节日变体", "", "```text"] + sorted(set(variants)) + ["```", ""]

    lines += ["## 下拉选项全集", "", "每个下拉参数的可选值，完整清单见 `dropdowns.tsv`；"
              "这里按选项去重列出高频项，便于生成时直接抄。", ""]
    counter = {}
    for opts in dd.values():
        for o in opts:
            counter[o] = counter.get(o, 0) + 1
    lines += ["| 选项 | 出现的参数数 |", "|---|---:|"]
    for opt, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:80]:
        lines.append("| %s | %d |" % (opt, n))
    lines.append("")
    return "\n".join(lines)


def render_strings(ws):
    texts = ws.get("TextOptions") or []
    raw = [t if isinstance(t, str) else (t.get("DisplayName") or t.get("Text") or "") for t in texts]
    names = sorted({x for x in raw if x})
    names = [re.sub(r"%%.", "%", n) for n in names]
    lines = ["<!-- 自动生成，禁止手改 -->", "# 文本选项（%d 条）" % len(names), "",
             "`自定义字符串` 里可以直接用的常量文本。占位符最多 `{2}`。", "", "```text"]
    lines += names + ["```", ""]
    return "\n".join(lines)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.rstrip("\n") + "\n")
    print("  %-22s %6d 行" % (os.path.basename(path), text.count("\n") + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="导出目录")
    ap.add_argument("--out", required=True, help="data 输出目录")
    ap.add_argument("--settings-words", default=None,
                    help="设置项词表；默认取 --src 目录下的 settings_words.txt")
    args = ap.parse_args()

    ws = json.load(open(os.path.join(args.src, "workshop_zhCN.json"), encoding="utf-8"))
    heroes = json.load(open(os.path.join(args.src, "heroes.json"), encoding="utf-8"))
    maps = json.load(open(os.path.join(args.src, "maps.json"), encoding="utf-8"))
    dd = dropdown_map(ws)

    sw = args.settings_words or os.path.join(args.src, "settings_words.txt")
    build = load_build(args.src, sw)
    stamp = "build %s | 导出 %s | gen_data.py" % (build, datetime.date.today().isoformat())
    print("数据基线：%s" % stamp)

    write(os.path.join(args.out, "signatures.md"), render_signatures(ws, dd, build, stamp))
    write(os.path.join(args.out, "dropdowns.tsv"), render_dropdowns(ws, dd))
    write(os.path.join(args.out, "settings.tsv"), render_settings(sw))
    write(os.path.join(args.out, "defaults.tsv"), render_defaults(ws))
    write(os.path.join(args.out, "enums.md"), render_enums(ws, heroes, maps, dd))
    write(os.path.join(args.out, "strings.md"), render_strings(ws))

    meta = {"build": build, "exported": datetime.date.today().isoformat(),
            "actions": len(ws.get("Actions") or []), "values": len(ws.get("Values") or []),
            "dropdowns": len(dd),
            "heroes": sum(1 for h in (heroes.values() if isinstance(heroes, dict) else heroes) if h.get("IsHero")),
            "maps": len(maps.values() if isinstance(maps, dict) else maps), "generator": "gen_data.py"}
    write(os.path.join(args.out, "meta.json"), json.dumps(meta, ensure_ascii=False, indent=2))
    return 0


def main_with_args(args):
    argv = ["gen_data.py", "--src", args.src, "--out", args.out]
    old = sys.argv
    sys.argv = argv
    try:
        return main()
    finally:
        sys.argv = old


if __name__ == "__main__":
    sys.exit(main())
