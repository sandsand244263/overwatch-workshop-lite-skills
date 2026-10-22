#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 workshop_zhCN.json 生成 data/param-options.tsv（参数顺序 + 下拉选项）。

权威来源：每个元素自带的 Parameters 数组，顺序即真实参数位置；
InputType == Dropdown 的参数带 DropdownId，指向 Dropdowns 表的选项列表。

用法：
    python tools/gen_param_options.py [workshop_zhCN.json 路径]
默认读 C:/owdump/export-154504/workshop_zhCN.json。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
DEFAULT_SRC = r"C:/owdump/export-154504/workshop_zhCN.json"


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    with open(src, encoding="utf-8") as f:
        doc = json.load(f)

    drop_opts = {}
    for d in doc.get("Dropdowns", []):
        opts = [o.get("DisplayName") for o in (d.get("Options") or []) if o.get("DisplayName")]
        drop_opts[d.get("Id")] = opts

    rows = []
    for kind in ("Events", "Actions", "Values"):
        for elem in doc.get(kind, []):
            name = elem.get("DisplayName")
            if not name:
                continue
            for i, p in enumerate(elem.get("Parameters") or []):
                itype = p.get("InputType") or p.get("InferredType") or ""
                pname = p.get("Name") or ""
                opts = []
                if p.get("DropdownId"):
                    opts = drop_opts.get(p["DropdownId"], [])
                # Team / Boolean 等由语法层管，不在这里判选项
                rows.append((name, kind, str(i), pname, itype, "|".join(opts)))

    out = os.path.join(DATA, "param-options.tsv")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("element\tkind\tindex\tname\tinput_type\toptions\n")
        for r in rows:
            f.write("\t".join(r) + "\n")

    with_opts = sum(1 for r in rows if r[5])
    elems = len({r[0] for r in rows})
    print("写出 %s：%d 个元素 / %d 个参数 / %d 个带选项" % (out, elems, len(rows), with_opts))


if __name__ == "__main__":
    main()
