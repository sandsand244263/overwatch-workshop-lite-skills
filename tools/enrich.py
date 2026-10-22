import os
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""派生数据生成器：从已有导出产出 data/ 下的增强表。

用法：
  python tools/enrich.py events       --src 导出目录/export-20261020 --out data/events.tsv
  python tools/enrich.py maps         --src 导出目录/export-20261020 --out data/maps.tsv

所有产物都是 TSV，UTF-8 无 BOM，\\n 换行，首行表头。禁止手改。
"""
import argparse
import json
import os
import re
import sys


def load_json(path):
    if not os.path.isfile(path):
        sys.exit("找不到 %s" % path)
    return json.load(open(path, encoding="utf-8"))


def write_tsv(path, header, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for r in rows:
            f.write("\t".join("" if x is None else str(x) for x in r) + "\n")
    print("wrote %s (%d rows)" % (path, len(rows)))


# ---------- settings-tree ----------
def value_info(val):
    """返回 (类型, 可选值串)。"""
    if not isinstance(val, dict):
        return ("", "")
    kind = (val.get("_Name") or "").replace("RulesetSchemaValue", "")
    choices = val.get("Choices") or []
    if choices:
        vals = [c.get("DisplayText") or "" for c in choices if c.get("DisplayText")]
        return (kind or "Enum", "|".join(vals))
    if kind.lower() == "bool" or val.get("TrueText"):
        t, f = val.get("TrueText") or "", val.get("FalseText") or ""
        return ("Bool", "|".join([x for x in (t, f) if x]))
    return (kind, "")


def build_settings_tree(src, out):
    data = load_json(os.path.join(src, "ruleset_schemas.json"))
    rows = []
    for guid, schema in (data.items() if isinstance(data, dict) else []):
        sname = (schema.get("Name") or "").strip() or "(未命名)"
        for e in schema.get("Entries") or []:
            key = (e.get("Name") or "").strip()
            if not key:
                continue
            kind, vals = value_info(e.get("Value"))
            rows.append([sname, guid, key, e.get("Category") or "", kind, vals])
    rows.sort(key=lambda r: (r[0], r[2]))
    write_tsv(out, ["schema", "schema_guid", "key", "category", "type", "values"], rows)


# ---------- events ----------
def build_events(src, out):
    ws = load_json(os.path.join(src, "workshop_zhCN.json"))
    rows = []
    for ev in ws.get("Events") or []:
        name = (ev.get("DisplayName") or "").strip()
        if not name:
            continue
        params = [(p.get("Name") or "-").strip() or "-" for p in (ev.get("Parameters") or [])]
        params += ["-"] * (3 - len(params))
        rows.append([name] + params[:3])
    rows.sort()
    write_tsv(out, ["event", "param1", "param2", "param3"], rows)


# ---------- strings ----------
def build_strings(src_md, out):
    if not os.path.isfile(src_md):
        sys.exit("找不到 %s" % src_md)
    rows, inside = [], False
    for line in open(src_md, encoding="utf-8"):
        s = line.strip()
        if s.startswith("```"):
            inside = not inside
            continue
        if not inside or not s or s.startswith("#"):
            continue
        if s in ("text",) or s.startswith("<!--"):
            continue
        nums = [int(x) for x in re.findall(r"\{(\d)\}", s)]
        rows.append([s, (max(nums) + 1) if nums else 0])
    write_tsv(out, ["text", "placeholders"], rows)


# ---------- maps ----------
TAG_RULES = [
    ("流程", ("If", "Else", "End", "While", "For", "中断", "中止", "等待", "调用子程序", "开始规则")),
    ("HUD", ("HUD", "文本", "信息", "进度条", "准星", "字幕")),
    ("特效", ("效果", "声音", "光束", "图标", "标记", "轮廓", "动画")),
    ("移动", ("传送", "推力", "速度", "碰撞", "位置", "朝向", "跳跃", "重力", "飞行", "停止")),
    ("状态", ("状态", "生命", "护盾", "无敌", "治疗", "伤害调整", "复活", "重生", "阵亡")),
    ("变量", ("变量", "数组", "分数", "计分")),
    ("伤害", ("伤害", "击杀", "助攻", "消灭")),
    ("英雄", ("英雄", "技能", "终极技能", "弹夹", "装弹", "按钮", "武器")),
]


def tag_of(name):
    tags = [t for t, kws in TAG_RULES if any(k in name for k in kws)]
    return "|".join(tags) if tags else "其他"


def build_action_tags(sig_md, out):
    if not os.path.isfile(sig_md):
        sys.exit("找不到 %s" % sig_md)
    rows = []
    for line in open(sig_md, encoding="utf-8"):
        line = line.strip()
        if "(" not in line or not line.endswith(")") or line.startswith("<!--"):
            continue
        name = line.split("(", 1)[0].strip()
        if not name or " " in name:
            continue
        rows.append([name, tag_of(name)])
    rows.sort()
    write_tsv(out, ["func", "tags"], rows)


def build_required_args(sig_md, out):
    """参数必填表：参数个数 N，末位为 _ 则 N-1，否则 N；手工覆盖优先。"""
    if not os.path.isfile(sig_md):
        sys.exit("找不到 %s" % sig_md)
    manual = {"修改全局变量": 3, "修改玩家变量": 4, "设置全局变量": 2, "设置玩家变量": 3}
    rows = []
    for line in open(sig_md, encoding="utf-8"):
        line = line.strip()
        if "(" not in line or not line.endswith(")") or line.startswith("<!--"):
            continue
        name, rest = line.split("(", 1)
        name = name.strip()
        if not name or " " in name:
            continue
        inner = rest[:-1].strip()
        args = [a for a in re.split(r"[，,](?![^\[\]]*\])", inner)] if inner else []
        n = len(args)
        min_args = manual.get(name, n - 1 if args and args[-1].strip().startswith("_") else n)
        if min_args <= 0:
            continue
        rows.append([name, min_args])
    rows.sort()
    write_tsv(out, ["func", "min_args"], rows)


def build_maps(src, out):
    data = load_json(os.path.join(src, "maps.json"))
    vals = list(data.values()) if isinstance(data, dict) else data
    rows, seen = [], set()
    for m in vals:
        name, guid = (m.get("Name") or "").strip(), m.get("GUID")
        if not name or not guid or guid in seen:
            continue
        seen.add(guid)
        variant = 1 if (m.get("VariantName") or "").strip() else 0
        # 可用性：数据里无权威标志位，统一标 unknown，不猜
        rows.append([name, guid, variant, "unknown"])
    rows.sort()
    write_tsv(out, ["name", "guid", "variant", "usable"], rows)


def main():
    ap = argparse.ArgumentParser(description="派生数据生成")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("events")
    p.add_argument("--src", required=True)
    p.add_argument("--out", required=True)

    p = sub.add_parser("action-tags")
    p.add_argument("--md", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "signatures.md"))
    p.add_argument("--out", required=True)

    p = sub.add_parser("all", help="依次生成全部派生表")
    p.add_argument("--src", default=None)

    p = sub.add_parser("maps")
    p.add_argument("--src", required=True)
    p.add_argument("--out", required=True)

    a = ap.parse_args()
    if a.cmd == "all":
        return run_all(a)
    if a.cmd == "events":
        build_events(a.src, a.out)
    elif a.cmd == "action-tags":
        build_action_tags(a.md, a.out)
    else:
        build_maps(a.src, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

def run_all(args):
    """依次生成 events / action-tags / maps。"""
    import sys as _sys
    for name in ("events", "action-tags", "maps"):
        _sys.argv = [_sys.argv[0], name] + (["--src", args.src] if getattr(args, "src", None) else [])
        main()
    return 0

