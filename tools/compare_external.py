#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对照：我们的英雄数值表 vs 第三方（weirdgloop / overlab）拉下来的参数。

性质：**只出报告，不改表**。发现的分歧要人裁决（D-098 裁决顺序：
实机读数 > 本次导出资产 > 官方补丁记录 > 第三方），所以这里只负责"把分歧摊开"。

先决条件：`python tools/fetch_weirdgloop.py --kind all --out <缓存目录>` 已跑过。

比对规则（英雄层，最确定的一层）：
  我们表：生命值 / 护甲 / 护盾（缺失行已判 0）相加 = 总生命
  他们页：`| health` / `| armor` / `| shield`，**口径是 5v5 开放职责**
  口径换算：5v5 预设 = 开放 + 重装被动 150 → 所以 重装 期望 theirs = ours - 150，其它职责期望相等
  判定：
    一致        数值相等（或重装正好差 150）
    冲突        不能用户口差解释（需要人裁决，脚本会把最近一次相关补丁翻出来）
    我们缺      他们有我们没有的英雄/字段
    他们缺      我们有他们没有（例：血律没有 wiki 页）

用法：
    python tools/compare_external.py --cache C:/owdump/wg-cache --out C:/owdump/wg-compare
    python tools/compare_external.py --cache … --out … --hero 莱因哈特   # 只看一个
"""
import argparse
import csv
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TANK_BONUS = 150          # 5v5 预设职责给重装的额外生命（D-093）
FIELDS = [("生命值", "health"), ("护甲", "armor"), ("护盾", "shield")]


def load_ours(path):
    rows = list(csv.DictReader(io.open(path, encoding="utf-8-sig"), delimiter="\t"))
    by = {}
    for r in rows:
        if r["scope"] != "英雄属性":
            continue
        by.setdefault(r["hero"], {})[r["field"]] = r
    return rows, by


def load_names():
    p = os.path.join(DATA, "hero-names.tsv")
    return {r["hero_zh"]: r["hero_en"] for r in csv.DictReader(io.open(p, encoding="utf-8-sig"), delimiter="\t")}


def load_theirs(cache):
    p = os.path.join(cache, "params.tsv")
    if not os.path.isfile(p):
        sys.exit("缺少 %s（先跑 fetch_weirdgloop.py）" % p)
    by = {}
    for r in csv.DictReader(io.open(p, encoding="utf-8-sig"), delimiter="\t"):
        if r["kind"] != "heroes" or r["block"] != "1":
            continue
        by.setdefault(r["page"], {})[r["field_en"]] = r["value_num"]
    return by


def roles_of(cache):
    """页 → 职责（Tank / Damage / Support），来自英雄页模板的 `| role =`。"""
    p = os.path.join(cache, "params.tsv")
    out = {}
    for r in csv.DictReader(io.open(p, encoding="utf-8-sig"), delimiter="\t"):
        if r["kind"] == "heroes" and r["block"] == "1" and r["field_en"] == "role":
            out[r["page"]] = r["value_raw"].strip()
    return out


def load_changes(cache):
    p = os.path.join(cache, "changes.tsv")
    if not os.path.isfile(p):
        return []
    return list(csv.DictReader(io.open(p, encoding="utf-8-sig"), delimiter="\t"))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def latest_change(changes, hero_en, field_en):
    """最近一次提到该英雄 + 关键字的补丁改动（给「为什么冲突」提供线索）。"""
    kw = {"health": ("health", "hp", "life"), "armor": ("armor",),
          "shield": ("shield", "barrier")}.get(field_en, (field_en,))
    hits = [c for c in changes if c["hero"] == hero_en
            and any(k in (c["text"] or "").lower() for k in kw)]
    return hits[-1] if hits else None


def main():
    ap = argparse.ArgumentParser(description="我们 vs 第三方的英雄层数值对照（只出报告）")
    ap.add_argument("--ours", default=os.path.join(DATA, "hero-numbers.tsv"))
    ap.add_argument("--cache", required=True, help="fetch_weirdgloop.py 的输出目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--hero", default="", help="只看一个英雄（中文名，子串匹配）")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    rows, ours = load_ours(a.ours)
    names = load_names()
    theirs = load_theirs(a.cache)
    roles = roles_of(a.cache)
    changes = load_changes(a.cache)

    out_rows, stat = [], {"一致": 0, "口径差": 0, "他们滞后": 0, "冲突": 0, "他们缺": 0, "我们缺": 0}
    for zh, en in sorted(names.items()):
        if a.hero and a.hero not in zh:
            continue
        o = ours.get(zh, {})
        t = theirs.get(en, {}) if en else {}
        if not en or not t:
            stat["他们缺"] += 1
            out_rows.append([zh, en, "", "", "", "", "", "", "他们缺", "第三方没有该英雄页"])
            continue

        ov = {fz: num((o.get(fz, {}) or {}).get("value")) for fz, _ in FIELDS}
        tv = {fe: num(t.get(fe, "") or 0) or 0 for _, fe in FIELDS}
        osum = sum(v for v in ov.values() if v)
        tsum = sum(tv.values())
        if not osum and not tsum:
            continue
        diff = osum - tsum
        if not osum:
            stat["我们缺"] += 1
            out_rows.append([zh, en, "", osum, tsum, "", diff, "", "我们缺", "他表有值而我们缺"])
            continue
        if diff == 0:
            verdict, note = "一致", ""
            stat["一致"] += 1
        else:
            notes = []
            ch, bad_fz = None, None
            for fz, fe in FIELDS:
                if ov[fz] is not None and (tv[fe] or 0) != ov[fz]:
                    bad_fz = fz
                    ch = latest_change(changes, en, fe)
                    if ch:
                        break
            if diff == 150 and roles.get(en) == "Tank":
                # 我们的表是 5v5 预设职责，wiki 是 5v5 开放职责，重装正好差被动 150
                verdict = "口径差"
                notes.append("差 150 = 重装被动（预设 vs 开放）")
            elif ch and bad_fz and num(ch["to_val"]) == (ov.get(bad_fz) or 0) and ch["from_val"]:
                # 补丁已经把值改成了我们表里的数，页面字段还停在旧值 → 第三方滞后（D-095/D-096 那类）
                verdict = "他们滞后"
                notes.append("补丁 %s 已改为 %s（页面仍 %s）" % (ch["date"], ch["to_val"], ch["from_val"]))
            else:
                verdict = "冲突"
            if ch:
                notes.append("最近补丁 %s：%s（%s→%s）" % (
                    ch["date"], (ch["text"] or "")[:70], ch["from_val"] or "?", ch["to_val"] or "?"))
            note = "；".join(dict.fromkeys(notes))
            stat[verdict] = stat.get(verdict, 0) + 1
        per = "生命 %s/%s 护甲 %s/%s 护盾 %s/%s" % (
            "" if ov["生命值"] is None else int(ov["生命值"]), int(tv["health"] or 0),
            "" if ov["护甲"] is None else int(ov["护甲"]), int(tv["armor"] or 0),
            "" if ov["护盾"] is None else int(ov["护盾"]), int(tv["shield"] or 0))
        out_rows.append([zh, en, int(osum), int(tsum), int(diff), per, verdict, note])

    path = os.path.join(a.out, "hero-compare.tsv")
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["hero_zh", "hero_en", "ours_total", "theirs_total", "diff", "per_field", "verdict", "note"])
        w.writerows(out_rows)

    print("=== 英雄层对照（%s）===" % (a.hero or "全部"))
    for k in ("一致", "口径差", "他们滞后", "冲突", "我们缺", "他们缺"):
        print("  %-6s %d" % (k, stat[k]))
    bad = [r for r in out_rows if r[6] == "冲突"]
    if bad:
        print("\n=== 冲突 %d 条（需裁决）===" % len(bad))
        for r in bad:
            print("  %-6s 我们 %-5s 他 %-5s 差 %-5s | %s | %s"
                  % (r[0], r[2], r[3], r[4], r[5], (r[7] or "")[:82]))
    print("\n明细：%s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
