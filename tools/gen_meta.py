#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重算 `data/meta.json` 里的计数（只读各表，不碰数据内容）。

为什么要有它：`meta.json` 的 build/导出日期来自游戏导出（`gen_data.py` 写），
但 actions / values / dropdowns / heroes / maps 这几个**计数**是各表自己的行数——
表被别的生成器更新（如 `enrich.py` 重写 maps.tsv）后，计数就悄悄对不上了
（2026-10-26 实测：maps 写 305，表里 306 行）。

用法：
  python tools/gen_meta.py            # 重算并写回 data/meta.json
  python tools/gen_meta.py --check    # 只比对，漂移退出 1（接进 devcheck 用）
"""
import argparse
import csv
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import console  # noqa: E402

console.harden()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
META = os.path.join(DATA, "meta.json")


def _rows(name):
    path = os.path.join(DATA, name)
    if not os.path.isfile(path):
        return []
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _signature_counts():
    """从 signatures.md 的标题行取「动作 N / 值函数 M」。"""
    path = os.path.join(DATA, "signatures.md")
    if not os.path.isfile(path):
        return None, None
    head = io.open(path, encoding="utf-8").read(400)
    m = re.search(r"动作\s*(\d+)\s*/\s*值函数\s*(\d+)", head)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def compute():
    meta = {}
    if os.path.isfile(META):
        meta = json.load(io.open(META, encoding="utf-8"))
    actions, values = _signature_counts()
    heroes = _rows("heroes.tsv")
    out = dict(meta)
    if actions is not None:
        out["actions"] = actions
    if values is not None:
        out["values"] = values
    out["dropdowns"] = len(_rows("dropdowns.tsv"))
    out["heroes"] = len({(r.get("name") or "").strip() for r in heroes if (r.get("name") or "").strip()})
    out["maps"] = len(_rows("maps.tsv"))
    out.setdefault("generator", "gen_data.py")
    return meta, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对不写盘；漂移退出 1")
    a = ap.parse_args()
    old, new = compute()
    diffs = [(k, old.get(k), new[k]) for k in ("actions", "values", "dropdowns", "heroes", "maps")
             if old.get(k) != new[k]]
    if a.check:
        if diffs:
            for k, o, n in diffs:
                print("✗ meta.json 的 %s 是 %s，表里实际 %s" % (k, o, n))
            return 1
        print("· meta.json 计数与表一致（actions %s / values %s / dropdowns %s / heroes %s / maps %s）"
              % (new["actions"], new["values"], new["dropdowns"], new["heroes"], new["maps"]))
        return 0
    if not diffs:
        print("· meta.json 已是最新，无需改")
        return 0
    for k, o, n in diffs:
        print("  %s: %s → %s" % (k, o, n))
    with io.open(META, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(new, ensure_ascii=False, indent=2) + "\n")
    print("wrote %s" % META)
    return 0


if __name__ == "__main__":
    sys.exit(main())
