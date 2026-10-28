#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实模式语料回归：改校验器后跑一遍，确认没新增误报、没漏掉已知问题。

语料目录不在本仓库（他人作品，不公开）：用参数、环境变量 WS_CORPUS 或技能根的 local_paths.json 指定。
首次运行会生成 expected.json 作为基线；之后跑就对比。

顺带跑「被拒样本」回归（如果配了目录）：那批文件是游戏真的拒过的原字节，判据写在
manifest.tsv 的「必须命中」列。它锁的是另一件事——**这条检查有没有断**，
而语料锁的是「有没有新增误报」。两件事都要有，否则「0 必改但游戏全拒」（E-94）还会重来。

用法：
    python tools/corpus_check.py [语料目录] [--update] [--rejected-only]
"""
import argparse
import csv
import json
import os
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import console  # noqa: E402

console.harden()
import core  # noqa: E402
import local_paths  # noqa: E402

DATA = os.path.join(SKILL, "data")


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


def check_rejected(dirpath):
    """被拒样本回归：游戏拒过的必须仍被拦下，对照样本必须仍然干净。

    返回 (失败数, 说明)。判据在 manifest.tsv：判定=被拒 → 必须报出「必须命中」那句；
    判定=通过 → 必须 0 error（谁把检查写宽了，这一行先掉）。
    """
    manifest = os.path.join(dirpath, "manifest.tsv")
    if not os.path.isfile(manifest):
        print("被拒样本：没有 manifest.tsv → %s" % manifest)
        return 1, "缺 manifest"
    with open(manifest, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f, delimiter="\t") if (r.get("文件") or "").strip()]

    miss, passed, bad = [], 0, 0
    print("%-32s %-6s %s" % ("被拒样本", "判定", "结果"))
    for r in rows:
        name = r["文件"].strip()
        want = (r.get("必须命中") or "").strip()
        verdict = (r.get("判定") or "").strip()
        path = os.path.join(dirpath, name)
        if not os.path.isfile(path):
            print("  %-30s %-6s ✗ 文件不见了" % (name, verdict))
            miss.append("%s（文件不见了）" % name)
            bad += 1
            continue
        probs = core.full_lint(path, DATA)
        errs = [p[2] for p in probs if p[1] == "error"]
        if verdict == "通过":
            if errs:
                print("  %-30s %-6s ✗ 对照组被拦（%s）" % (name, verdict, errs[0][:40]))
                miss.append("%s（对照被误报）" % name)
                bad += 1
            else:
                print("  %-30s %-6s 干净" % (name, verdict))
                passed += 1
            continue
        hit = [e for e in errs if want and want in e]
        if hit:
            print("  %-30s %-6s 抓到：%s" % (name, verdict, want))
        else:
            print("  %-30s %-6s ✗ 没报出「%s」（现在 %d error）"
                  % (name, verdict, want or "?", len(errs)))
            miss.append("%s（漏检）" % name)
            bad += 1

    note = "被拒 %d/%d 抓到" % (len(rows) - len(miss), len(rows) - passed)
    if passed:
        note += "、对照 %d 干净" % passed
    return bad, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", nargs="?", default=local_paths.corpus_dir())
    ap.add_argument("--update", action="store_true", help="重写基线")
    ap.add_argument("--rejected-only", action="store_true", help="只跑被拒样本（不跑语料）")
    a = ap.parse_args()

    rejected = local_paths.rejected_dir()
    notes, bad = [], 0

    if a.rejected_only:
        if not rejected:
            print("没有被拒样本目录：%s" % local_paths.hint())
            return 2
        bad += check_rejected(rejected)[0]
        print("\n结论：%s" % ("通过（被拒样本全部仍被拦下）" if bad == 0 else "%d 条被拒样本失守" % bad))
        return 0 if bad == 0 else 1

    if not a.dir:
        if rejected:
            bad += check_rejected(rejected)[0]
            print("\n结论：%s" % ("通过（没配语料，只跑了被拒样本）" if bad == 0 else "有失守"))
            return 0 if bad == 0 else 1
        print("没有语料目录：%s" % local_paths.hint())
        return 2

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

    if rejected:
        print()
        bad += check_rejected(rejected)[0]
        notes.append("被拒样本已跑")

    verdict = "通过（没有新增 error）" if bad == 0 else "%d 处变差" % bad
    print("\n结论：%s" % verdict)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
