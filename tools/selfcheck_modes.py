#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自检：把「工具自己生成的模式」全量生成一遍，再用自己的校验器检查。

为什么需要这个：工具内部两半会互相打架 —— 生成器写出的键位/默认值，
校验器不认。2026-10-24 第一次跑就抓到 16/55 个模式自相矛盾：
  · 斗球/排球推力倍率 权威范围 1~3，生成器写 0
  · 团队模式的大厅块写了 自由混战人数上限: 10（必须 0）
  · 允许切换英雄 / 随机英雄复生 写在 决斗先锋 块里（实测被拒，应进 模式 > 综合）
  · 检查器把名字带全角冒号的模式块头（星际守望：银河救兵）当成设置键

用法：
  python tools/selfcheck_modes.py            # 全部模式，只报结论
  python tools/selfcheck_modes.py -v         # 每个模式一行
  python tools/selfcheck_modes.py --mode 死斗
退出码：全过 0，有 error 1。
"""
import argparse
import csv
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, HERE)

import core            # noqa: E402
import ws              # noqa: E402


def all_modes():
    rows = list(csv.DictReader(open(os.path.join(DATA, "mode-pages.tsv"), encoding="utf-8"),
                               delimiter="\t"))
    return sorted({r["owner"] for r in rows if r["owner"]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", help="只查一个模式")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--keep", help="把生成的文件留在这个目录（默认用完就删）")
    args = ap.parse_args()

    modes = [args.mode] if args.mode else all_modes()
    # 55 个内部模式**全都跑**：斗球/排球那种模式专属键的 bug 只有跑它们才能抓到。
    # 但「这个模式工坊里选不到」那条 error 要忽略 —— 那是预期行为，不是生成器的问题。
    usable = core.load_workshop_modes()
    internal = [m for m in modes if m not in usable]
    outdir = args.keep or tempfile.mkdtemp(prefix="ws-modes-")
    if args.keep:
        os.makedirs(outdir, exist_ok=True)

    bad = []
    for mode in modes:
        try:
            text = ws.build_settings_block(mode, lobby=True)
        except SystemExit as e:
            bad.append((mode, "生成失败：%s" % e))
            continue
        safe = mode.replace("/", "_").replace(":", "_")
        path = os.path.join(outdir, safe + ".ow")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        errs = [p for p in core.full_lint(path, DATA)
                if p[1] == "error"
                and "不是工坊里能选到的模式" not in p[2]]
        if errs:
            bad.append((mode, "第 %s 行：%s" % (errs[0][0], errs[0][2][:70])))
        elif args.verbose:
            print("✓ %s" % mode)

    print("模式 %d 个：干净 %d / 有问题 %d" % (len(modes), len(modes) - len(bad), len(bad)))
    if internal:
        print("（其中 %d 个是工坊里选不到的内部模式，模式名那一条已按预期忽略）" % len(internal))
    for mode, msg in bad:
        print("  ✗ %s → %s" % (mode, msg))
    if args.keep:
        print("生成物留在：%s" % outdir)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
