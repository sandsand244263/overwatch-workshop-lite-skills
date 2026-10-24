#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_word_lists.py —— 生成 data/word-lists.tsv（从 exe 里读出来的「合法词校验点」表）。

数据来源（唯一）：`tools/word-lists-src.tsv`（人工整理的证据表，每行一个校验点）

一行为一个「解析器校验点」：
    checkpoint   槽位名（人读）
    func_va      exe 里做这个校验的函数（VA）
    slot         这个槽位是什么
    n_words      词数
    words        合法词，`|` 分隔
    key_indexes  对应的 CASC 0x07C key_index，`|` 分隔，与 words 一一对应
    comparator   比较器（一个或多个）
    level        证据等级（L1 = 代码结构成立、未本机实测；L2 = 实机导入过）
    source       出处（EVIDENCE 编号）

纪律：
- 原文一字不改；只做排序与校验（words 与 key_indexes 必须等长、词不能重复）
- 两次运行输出必须字节一致（按 func_va, checkpoint 排序，无时间戳）
- **不许手改 `data/word-lists.tsv`**——改 `tools/word-lists-src.tsv` 再跑本脚本

用法：
    python tools/gen_word_lists.py            # 生成 data/word-lists.tsv 并打印统计
    python tools/gen_word_lists.py --check    # 只比对不写盘（漂移退出 1）
    python tools/gen_word_lists.py --stats    # 只打印统计
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "word-lists-src.tsv"
OUT = ROOT / "data" / "word-lists.tsv"
COLS = ["checkpoint", "func_va", "slot", "n_words", "words",
        "key_indexes", "comparator", "level", "source"]


def load_src() -> list[dict]:
    lines = [l.rstrip("\n") for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
    hdr = lines[0].split("\t")
    if hdr != COLS:
        sys.exit(f"源表表头不对：{hdr}\n应为：{COLS}")
    rows = []
    for i, line in enumerate(lines[1:], 2):
        p = line.split("\t")
        if len(p) != len(COLS):
            sys.exit(f"第 {i} 行列数 {len(p)} != {len(COLS)}")
        r = dict(zip(COLS, p))
        words = [w for w in r["words"].split("|") if w]
        idxs = [x for x in r["key_indexes"].split("|") if x]
        if len(words) != len(idxs):
            sys.exit(f"第 {i} 行 words 与 key_indexes 不等长（{len(words)} vs {len(idxs)}）：{r['checkpoint']}")
        if len(set(words)) != len(words):
            sys.exit(f"第 {i} 行有重复词：{r['checkpoint']}")
        if int(r["n_words"]) != len(words):
            sys.exit(f"第 {i} 行 n_words={r['n_words']} 与实际 {len(words)} 不符")
        for x in idxs:
            if not x.isdigit():
                sys.exit(f"第 {i} 行 key_index 不是数字：{x}")
        rows.append(r)
    return rows


def render(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: (int(r["func_va"], 16), r["checkpoint"]))
    out = ["\t".join(COLS)]
    for r in rows:
        out.append("\t".join(r[c] for c in COLS))
    return "\n".join(out) + "\n"


def stats(rows: list[dict]) -> str:
    words = set()
    for r in rows:
        words.update(w for w in r["words"].split("|") if w)
    lv = {}
    for r in rows:
        lv[r["level"]] = lv.get(r["level"], 0) + 1
    lines = [f"校验点 {len(rows)} 个，去重词 {len(words)} 条",
             "证据等级：" + " / ".join(f"{k} {v}" for k, v in sorted(lv.items()))]
    by_n = {}
    for r in rows:
        by_n[int(r["n_words"])] = by_n.get(int(r["n_words"]), 0) + 1
    lines.append("按词数：" + " / ".join(f"{k} 词 {v} 个" for k, v in sorted(by_n.items())))
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    rows = load_src()
    text = render(rows)
    if a.stats:
        print(stats(rows))
        return 0
    md5 = hashlib.md5(text.encode("utf-8")).hexdigest()
    if a.check:
        if not OUT.exists():
            print("× data/word-lists.tsv 不存在")
            return 1
        cur = OUT.read_text(encoding="utf-8")
        if cur != text:
            print("× data/word-lists.tsv 有漂移，跑 python tools/gen_word_lists.py 重生成")
            return 1
        print(f"✓ word-lists.tsv 无漂移（{len(rows)} 行，md5 {md5}）")
        print(stats(rows))
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"已写 {OUT.relative_to(ROOT)}（{len(rows)} 行，md5 {md5}）")
    print(stats(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
