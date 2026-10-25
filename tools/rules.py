# -*- coding: utf-8 -*-
"""断言表（docs/rules.tsv）的读取与检索。

这张表是「实测结论」的唯一可查入口：一条一行，字段固定。
- 文档从这里渲染
- 校验器按「检查」列决定跑哪条静态提示（`不接` / `已接:函数名` / `反例:文件名`，
  写法和拼写由 `tools/audit_rules.py` 对账，接进 devcheck）
- `ws.py verify` 按「证据」等级列出还没验的条目

用法（由 ws.py rule 转调）：
  ws.py rule 每名玩家     按关键词查
  ws.py rule --list       列出全部场景
"""
import csv
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(ROOT, "docs", "rules.tsv")
COLS = ["场景", "关键词", "禁止", "正确", "依据", "级别", "证据", "怎么验", "检查", "验期"]
LEVELS = ("L0", "L1", "L2", "L3")
LEVEL_DESC = {
    "L0": "数据里有，只是候选",
    "L1": "结构成立、check 能过，但没跑过",
    "L2": "实机导入成功",
    "L3": "实机行为符合预期（有读数）",
}

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


def save(rows, path=None):
    path = os.path.abspath(path or DEFAULT)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(COLS) + "\n")
        for r in rows:
            f.write("\t".join(r.get(c, "") for c in COLS) + "\n")
    _CACHE["rows"], _CACHE["path"] = rows, path


def search(rows, query):
    """空格分隔多词，全部命中才算（在每个字段里找子串）。"""
    terms = [t.lower() for t in query.split() if t.strip()]
    if not terms:
        return []
    return [r for r in rows if all(t in " ".join(r.values()).lower() for t in terms)]


def render(r):
    ev = r.get("证据", "")
    out = ["[%s]  %s 证据  %s  （依据 %s）" % (r["场景"], r["级别"], ev or "未标", r["依据"])]
    out.append("  别这么写：%s" % r["禁止"])
    out.append("  这么写：  %s" % r["正确"])
    if ev and ev != "L3":
        out.append("  未完全验证（%s：%s）——别当定论用" % (ev, LEVEL_DESC.get(ev, "")))
    if r.get("怎么验"):
        out.append("  怎么验：  %s" % r["怎么验"])
    if r.get("检查") and r["检查"] != "不接":
        out.append("  检查状态：%s" % r["检查"])
    return "\n".join(out)


def run(args):
    rows = load()
    if not rows:
        print("断言表是空的或不存在：%s" % DEFAULT)
        return 2
    if getattr(args, "list", False):
        print("断言表 %d 条（docs/rules.tsv）：" % len(rows))
        for r in rows:
            print("  %-20s %-4s %-3s %s" % (r["场景"], r["级别"], r["证据"], r["依据"]))
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
