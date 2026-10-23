# -*- coding: utf-8 -*-
"""判定表（docs/rules.tsv）的读取与检索。

这张表是"实测结论"的唯一可查入口：一条一行，字段固定。
文档可以从它渲染，校验器也可以按 等级=提示 + 检查=已接 的条目接静态检查。

用法（由 ws.py rule 转调）：
  ws.py rule 每名玩家     按关键词查
  ws.py rule --list       列出全部场景
"""
import csv
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(ROOT, "docs", "rules.tsv")
COLS = ["场景", "关键词", "禁止", "正确", "依据", "等级", "检查"]

_CACHE = {"rows": None, "path": None}


def load(path=None):
    path = os.path.abspath(path or DEFAULT)
    if _CACHE["rows"] is not None and _CACHE["path"] == path:
        return _CACHE["rows"]
    rows = []
    if os.path.isfile(path):
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if not (row.get("场景") or "").strip():
                    continue
                rows.append({c: (row.get(c) or "").strip() for c in COLS})
    _CACHE["rows"], _CACHE["path"] = rows, path
    return rows


def search(rows, query):
    """空格分隔多词，全部命中才算（在每个字段里找子串）。"""
    terms = [t.lower() for t in query.split() if t.strip()]
    if not terms:
        return []
    hits = []
    for r in rows:
        blob = " ".join(r.values()).lower()
        if all(t in blob for t in terms):
            hits.append(r)
    return hits


def render(r):
    out = ["[%s]  %s  （依据 %s）" % (r["场景"], r["等级"], r["依据"])]
    out.append("  别这么写：%s" % r["禁止"])
    out.append("  这么写：  %s" % r["正确"])
    if r["检查"] and r["检查"] != "不接":
        out.append("  检查状态：%s" % r["检查"])
    return "\n".join(out)


def run(args):
    rows = load()
    if not rows:
        print("判定表是空的或不存在：%s" % DEFAULT)
        return 2
    if getattr(args, "list", False):
        print("判定表 %d 条（docs/rules.tsv）：" % len(rows))
        for r in rows:
            print("  %-18s %-4s %s" % (r["场景"], r["等级"], r["依据"]))
        return 0
    q = getattr(args, "query", None) or ""
    if isinstance(q, (list, tuple)):
        q = " ".join(q)
    q = q.strip()
    if not q:
        print("给个关键词，例如：ws.py rule 每名玩家")
        print("或 --list 看全部 %d 条" % len(rows))
        return 2
    hits = search(rows, q)
    if not hits:
        print("没查到「%s」。换个词试试，或 --list 看全部场景。" % q)
        return 1
    for i, r in enumerate(hits):
        if i:
            print("")
        print(render(r))
    if len(hits) > 1:
        print("\n（%d 条命中）" % len(hits))
    return 0
