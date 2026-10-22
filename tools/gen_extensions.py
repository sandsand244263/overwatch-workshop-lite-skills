"""从 workshop_zhCN.json 生成扩展数据表。

输出：
  data/extensions.tsv        扩展名、成本、解锁项数
  data/extension-values.tsv  扩展名、下拉 ID、解锁的选项名
"""
import json
import os
import sys

SRC_DEFAULT = r"C:/owdump/export-154504/workshop_zhCN.json"
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def main(src=SRC_DEFAULT):
    doc = json.load(open(src, encoding="utf-8"))
    exts = doc.get("Extensions") or []
    rows, vals = [], []
    for e in exts:
        name = (e.get("DisplayName") or "").strip()
        if not name:
            continue
        cost = int(e.get("Cost") or 0)
        unlocked = e.get("UnlockedValues") or []
        rows.append((name, cost, len(unlocked)))
        for v in unlocked:
            vals.append((name, (v.get("DropdownId") or "").strip(), (v.get("DisplayName") or "").strip()))

    p1 = os.path.join(DATA, "extensions.tsv")
    with open(p1, "w", encoding="utf-8", newline="\n") as f:
        f.write("extension\tcost\tunlocked\n")
        for r in sorted(rows, key=lambda x: (x[1], x[0])):
            f.write("%s\t%d\t%d\n" % r)
    p2 = os.path.join(DATA, "extension-values.tsv")
    with open(p2, "w", encoding="utf-8", newline="\n") as f:
        f.write("extension\tdropdown\tvalue\n")
        for r in vals:
            f.write("%s\t%s\t%s\n" % r)
    print("扩展 %d 个（总成本 %d），解锁选项 %d 条" % (len(rows), sum(r[1] for r in rows), len(vals)))
    print("→", p1)
    print("→", p2)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else SRC_DEFAULT)
