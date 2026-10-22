#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实模式语料回归：改校验器后跑一遍，确认没新增误报、没漏掉已知问题。

语料放在私有仓（默认 workshop-lite-re/corpus/real），不在公开仓库里。
首次运行会生成 expected.json 作为基线；之后跑就对比。

用法：
    python tools/corpus_check.py [语料目录] [--update]
"""
import argparse
import json
import os
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import core  # noqa: E402

DATA = os.path.join(SKILL, "data")
DEFAULT = r"E:\工作内容\11_vibe-coding项目\workshop-lite-re\corpus\real"


def summarize(path):
    probs = core.full_lint(path, DATA)
    errs = [p for p in probs if p[1] == "error"]
    warns = [p for p in probs if p[1] == "warning"]
    return {
        "errors": len(errs),
        "warnings": len(warns),
        "error_kinds": sorted({_kind(p[2]) for p in errs}),
        "warning_kinds": sorted({_kind(p[2]) for p in warns}),
    }


def _kind(msg):
    """把报错压成「类型」，避免行号/名字变化导致整份基线失效。"""
    for sep in ("：", "；"):
        if sep in msg:
            msg = msg.split(sep)[0]
    return msg[:40]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=os.environ.get("WS_CORPUS", DEFAULT))
    ap.add_argument("--update", action="store_true", help="重写基线")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(a.dir, "*.ow")) + glob.glob(os.path.join(a.dir, "*.txt")))
    if not files:
        print("语料目录里没有 .ow/.txt：%s" % a.dir)
        return 2
    baseline_path = os.path.join(a.dir, "..", "expected.json")
    baseline = {}
    if os.path.isfile(baseline_path) and not a.update:
        baseline = json.load(open(baseline_path, encoding="utf-8"))

    cur, bad = {}, 0
    for f in files:
        name = os.path.basename(f)
        cur[name] = summarize(f)

    if a.update or not baseline:
        json.dump(cur, open(baseline_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("已写基线：%s（%d 个文件）" % (baseline_path, len(cur)))
        for k, v in cur.items():
            print("  %-22s error %d / warning %d" % (k, v["errors"], v["warnings"]))
        return 0

    print("%-24s %-18s %s" % ("文件", "error", "warning"))
    for name in sorted(cur):
        c, b = cur[name], baseline.get(name)
        if b is None:
            print("  %-22s 新增文件（基线里没有）" % name)
            bad += 1
            continue
        new_err = set(c["error_kinds"]) - set(b["error_kinds"])
        gone_err = set(b["error_kinds"]) - set(c["error_kinds"])
        flag = ""
        if c["errors"] > b["errors"] or new_err:
            flag = " ✗ 变差"
            bad += 1
        elif c["errors"] < b["errors"] or gone_err:
            flag = " (有减少)"
        print("  %-22s %2d → %2d          %2d → %2d%s"
              % (name, b["errors"], c["errors"], b["warnings"], c["warnings"], flag))
        for k in sorted(new_err):
            print("      新增 error：%s" % k)
        for k in sorted(gone_err):
            print("      消失 error：%s" % k)
        new_warn = set(c["warning_kinds"]) - set(b["warning_kinds"])
        for k in sorted(new_warn):
            print("      新增 warning：%s" % k)

    print("\n结论：%s" % ("通过（没有新增 error）" if bad == 0 else "%d 个文件变差" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
