#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 ruleset_schemas.json 生成设置归属表 data/setting-schemas.tsv。

权威来源：游戏导出的每个 schema（综合 / 决斗先锋 / 英雄 / 武器 …）的 Entries。

输出列：
    schema  键所在层
    key     设置键
    type    BOOL / INT / FLOAT / ENUM …
    on/off  布尔项的真实用词（开启/禁用 或 启用/关闭 —— 各键不一样）
    default 默认值
    min/max 数值范围

用法：
    python tools/gen_setting_schemas.py [ruleset_schemas.json]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
DEFAULT_SRC = r"导出目录/export-154504/ruleset_schemas.json"


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    doc = json.load(open(src, encoding="utf-8"))

    rows = []
    for guid, sch in doc.items():
        sname = sch.get("Name")
        if not sname:
            continue
        for e in (sch.get("Entries") or []):
            if not isinstance(e, dict):
                continue
            key = (e.get("Name") or "").strip()
            if not key:
                continue
            val = e.get("Value") or {}
            vtype = (val.get("_Name") or "").replace("RulesetSchemaValue", "")
            on = (val.get("TrueText") or "").strip()
            off = (val.get("FalseText") or "").strip()
            dflt = val.get("DefaultValue")
            rows.append((sname, key, vtype, on, off,
                         "" if dflt is None else str(dflt),
                         "" if val.get("Min") is None else str(val.get("Min")),
                         "" if val.get("Max") is None else str(val.get("Max"))))

    out = os.path.join(DATA, "setting-schemas.tsv")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("schema\tkey\ttype\ton\toff\tdefault\tmin\tmax\n")
        for r in rows:
            f.write("\t".join(x.replace("\t", " ") for x in r) + "\n")

    schemas = len({r[0] for r in rows})
    keys = len({r[1] for r in rows})
    print("写出 %s：%d 个 schema / %d 行 / %d 个不同键" % (out, schemas, len(rows), keys))
    # 顺便报一下布尔词有几种
    words = {(r[3], r[4]) for r in rows if r[2] == "Bool"}
    print("布尔词组合：%s" % sorted(words))


if __name__ == "__main__":
    main()
