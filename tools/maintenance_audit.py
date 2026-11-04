#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""维护层自洽检查：清单 ↔ 技能 ↔ 仓库 三边一致，防止"新工具没人记得用"。

为什么需要它：SOP 是手写文档，维护层每加一个工具/一步流程，就得有人记得回来同步技能。
人一定会漏。所以把「登记」变成硬门槛，漏了 devcheck 就红：

  ① `maintenance/pipeline.tsv` 里登记的 assets 必须存在（登记了但文件没了 = 红）
  ② 每个 step 必须在技能 `workshop-data-update` 的 SOP 表里出现（清单有、技能没写 = 红）
  ③ 近 14 天新增的 `tools/*.py` / `data/*.tsv` 必须登记，或写进 `maintenance/ignore.tsv`（新增未登记 = 红）

用法：
    python tools/maintenance_audit.py            # 人读摘要
    python tools/maintenance_audit.py --quiet     # 只出结论行（devcheck 用）
    python tools/maintenance_audit.py --days 30   # 改"最近新增"的窗口

退出码：0 一致；1 有缺口（缺口逐条打印，带修法）。
"""
import argparse
import re
import csv
import io
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "maintenance", "pipeline.tsv")
IGNORE = os.path.join(ROOT, "maintenance", "ignore.tsv")
SKILL = os.environ.get(
    "WS_UPDATE_SKILL",
    os.path.join(os.path.expanduser("~"), "AppData", "Local", "hermes", "skills",
                 "tools", "workshop-data-update", "SKILL.md"))


def read_pipeline():
    if not os.path.isfile(PIPE):
        return []
    with io.open(PIPE, encoding="utf-8-sig", newline="") as f:
        lines = [l for l in f if not l.lstrip().startswith("#")]
    return [r for r in csv.DictReader(lines, delimiter="\t") if r.get("step")]


def read_ignore():
    if not os.path.isfile(IGNORE):
        return set()
    with io.open(IGNORE, encoding="utf-8-sig", newline="") as f:
        lines = [l for l in f if not l.lstrip().startswith("#")]
    return {(r.get("path") or "").strip() for r in csv.DictReader(lines, delimiter="\t")
            if (r.get("path") or "").strip()}


def resolve(asset):
    """assets 里可能是仓库相对路径，也可能是本机绝对路径（C:\\owdump\\...）。"""
    if os.path.isabs(asset) or (len(asset) > 1 and asset[1] == ":"):
        return os.path.isfile(asset)
    return os.path.isfile(os.path.join(ROOT, asset))


def skill_text():
    if not os.path.isfile(SKILL):
        return ""
    with io.open(SKILL, encoding="utf-8", errors="replace") as f:
        return f.read()


def last_tag():
    try:
        return subprocess.run(["git", "-C", ROOT, "describe", "--tags", "--abbrev=0"],
                              capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def new_files(days):
    """自上次发版以来新增的 tools/*.py 与 data/*.tsv（只看新增，改名/修改不算）。
    没有 tag 时退回「最近 N 天」。"""
    tag = last_tag()
    if not tag:
        # 装机份是 skills 仓的子目录，没有版本 tag：这个扫描只在发布仓有意义
        return []
    rng = ["%s..HEAD" % tag]
    try:
        out = subprocess.run(
            ["git", "-C", ROOT, "-c", "core.quotepath=false", "log", "--diff-filter=A",
             "--name-only", "--pretty=format:"] + rng + ["--", "tools/*.py", "data/*.tsv"],
            capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return []
    return sorted({l.strip() for l in out.split("\n") if l.strip()})


def main():
    ap = argparse.ArgumentParser(description="维护层自洽检查（清单↔技能↔仓库）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()

    steps = read_pipeline()
    problems = []
    if not steps:
        problems.append("清单读不到：%s（维护流程没有唯一源头了）" % PIPE)

    # ① 登记的资产存在
    for r in steps:
        for asset in [x.strip() for x in (r.get("assets") or "").split(";") if x.strip()]:
            if not resolve(asset):
                problems.append("登记了但文件不存在：%s（step %s）" % (asset, r["step"]))

    # ② 每个 step 在技能 SOP 里出现
    st = skill_text()
    if not st:
        problems.append("读不到技能文件：%s（用 WS_UPDATE_SKILL 指定）" % SKILL)
    else:
        for r in steps:
            sid = r["step"].strip()
            if ("| %s |" % sid) not in st and ("|%s|" % sid) not in st:
                problems.append("清单有 step %s（%s），技能 SOP 里没有 → 下次更新会漏掉它"
                                % (sid, r["name"]))

    # ③ 新增文件：软提示（要求发版前逐个归位，但不拦构建——否则一有运行时工具就红，检查会被关掉）
    registered = set()
    for r in steps:
        for asset in [x.strip() for x in (r.get("assets") or "").split(";") if x.strip()]:
            registered.add(asset.replace("\\", "/"))
    ignore = read_ignore()
    hints = []
    for f in new_files(a.days):
        key = f.replace("\\", "/")
        if key in registered or key in ignore:
            continue
        hints.append(key)

    # ④ 技能里点名的 tools/*.py 必须存在（文档指向已删/改名的文件 = 硬缺口）
    if st:
        for m in re.finditer(r"tools/([A-Za-z0-9_\-]+\.py)", st):
            rel = "tools/" + m.group(1)
            if not os.path.isfile(os.path.join(ROOT, rel)):
                problems.append("技能里引用了不存在的文件：%s → 改技能或补文件" % rel)

    if a.quiet:
        print("维护层自洽：%s（%d 步%s）" % (
            "通过" if not problems else "%d 处缺口" % len(problems), len(steps),
            "，%d 个新文件待归类" % len(hints) if hints else ""))
    else:
        print("=== 维护层自洽检查 ===")
        print("清单：%s（%d 步）" % (PIPE, len(steps)))
        for r in steps:
            print("  %-3s %-14s %s" % (r["step"], r["name"], (r["command"] or "")[:70]))
        print("技能：%s" % SKILL)
        if not last_tag():
            print("\n（无版本 tag：跳过「新增文件」扫描，该检查在发布仓做）")
        if hints:
            print("\n待归类的新文件 %d 个（自上次发版以来新增，没登记进流程）：" % len(hints))
            for h in hints:
                print("  · " + h)
            print("  → 属于更新流程的：加到 pipeline.tsv 对应 step 的 assets；不属于的：写进 maintenance/ignore.tsv")
        if problems:
            print("\n硬缺口 %d 处：" % len(problems))
            for p in problems:
                print("  ✗ " + p)
        elif not hints:
            print("\n结论：三边一致。")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
