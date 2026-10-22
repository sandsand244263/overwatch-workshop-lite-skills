#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 .ow 按规则切成两份（奇偶轮转），用于二分定位元素数偏差。

用法：
    python tools/split_rules.py 输入.ow --outdir 输出目录
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402


def split(text):
    """-> (head, [rule_text...])  head 是第一条规则之前的所有内容。"""
    lines = text.split("\n")
    start = None
    for i, l in enumerate(lines):
        if re.match(r"^\s*规则\(", l):
            start = i
            break
    if start is None:
        return text, []
    head = "\n".join(lines[:start])
    rules, cur, depth, seen = [], [], 0, False
    for l in lines[start:]:
        cur.append(l)
        d = l.count("{") - l.count("}")
        if "{" in l:
            seen = True
        depth += d
        if seen and depth <= 0:
            rules.append("\n".join(cur))
            cur = []
            seen = False
    if cur:
        rules.append("\n".join(cur))
    return head, rules


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()
    text, _enc = core.read_text(a.src)
    head, rules = split(text)
    os.makedirs(a.outdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.src))[0]
    parts = {0: [], 1: []}
    for i, r in enumerate(rules):
        parts[i % 2].append(r)
    for k in (0, 1):
        if not parts[k]:
            continue
        out = os.path.join(a.outdir, "%s_%s.ow" % (stem, "AB"[k]))
        open(out, "w", encoding="utf-8", newline="\n").write(head + "\n" + "\n\n".join(parts[k]) + "\n")
        print("%s：%d 条规则" % (os.path.basename(out), len(parts[k])))
    print("合计 %d 条" % len(rules))


if __name__ == "__main__":
    main()
