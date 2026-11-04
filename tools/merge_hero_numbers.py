#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把「补丁表」合并进英雄数值表 —— 让每次数据更新都能复算，而不是一次性脚本。

背景：这张表的数据来自四五条线（面板导出 / 0x130 变量节点 / 第三方对照 / 实机读数），
每条线各自产出小批行。以前的做法是每次临时写一个 merge_vN.py 放在 C:\\owdump 里，
下次更新就找不到了、也没法复算。这个工具把那些一次性脚本的规则固定下来。

三种动作（补丁表可以带 `action` 列逐行指定，也可以用 --mode 统一给）：

    fill  只填空值（原来「缺失/未解析」的行被补上真值）——**默认**
    set   强制覆盖（实机裁决、纠错用；旧值会写进 note）
    add   只新增（表里没有这个 (英雄,技能,字段) 才加）

补丁表格式（TSV，UTF-8）：至少 hero / field / value 三列，可选
    ability（留空=英雄级）、unit、confidence、note、action

用法：
    python tools/merge_hero_numbers.py --base C:/owdump/hero-numbers-v9.tsv \\
        --patch C:/owdump/fills.tsv --patch C:/owdump/recovered.tsv \\
        --out C:/owdump/hero-numbers-v10.tsv
    python tools/merge_hero_numbers.py --base data/hero-numbers.tsv --patch 实机读数.tsv \\
        --mode set --out /tmp/new.tsv --dry-run

规则（写死，别绕开）：
  - 去重键 = (hero, ability, field)；ability 为空的行走「英雄属性」口径
  - `confidence` 只允许 已解析 / 推定 / 存疑 / 缺失 / 未解析，非法值直接报错退出
  - `fill` 不动已有值；`set` 覆盖但把旧值留在 note 里（可追溯）
  - 不猜：补丁表里 value 为空的 fill/set 行会被跳过并计数
  - 输出按 (hero, scope, ability, field, value) 排序，保证可复算（同样的输入必得同样的文件）
"""
import argparse
import collections
import csv
import io
import os
import sys

COLS = ["hero", "scope", "ability", "field", "alias", "value", "unit", "confidence", "note"]
CONF = ("已解析", "推定", "存疑", "缺失", "未解析")
PATCH_COLS = ("hero", "ability", "field", "value", "unit", "confidence", "note", "action")


def read_tsv(path):
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def key_of(r):
    return ((r.get("hero") or "").strip(), (r.get("ability") or "").strip(),
            (r.get("field") or "").strip())


def norm(row):
    """英雄级行（ability 为空）统一 scope，避免下游按 scope 过滤时漏行。"""
    if not row["ability"]:
        row["scope"] = "英雄属性"
    row["scope"] = row.get("scope") or ("英雄属性" if not row["ability"] else "技能")
    return row


def main():
    ap = argparse.ArgumentParser(description="把补丁表合并进英雄数值表（fill / set / add）")
    ap.add_argument("--base", required=True, help="现有表（hero-numbers-vN.tsv）")
    ap.add_argument("--patch", action="append", default=[], required=True,
                    help="补丁表，可多次给")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=["fill", "set", "add"], default="fill",
                    help="补丁表没有 action 列时的默认动作")
    ap.add_argument("--dry-run", action="store_true", help="只报统计，不写文件")
    a = ap.parse_args()

    rows = [norm({c: (r.get(c) or "").strip() for c in COLS}) for r in read_tsv(a.base)]
    idx = {key_of(r): r for r in rows}
    stat = collections.Counter()

    for path in a.patch:
        if not os.path.isfile(path):
            sys.exit("补丁表不存在：%s" % path)
        for p in read_tsv(path):
            action = (p.get("action") or a.mode).strip().lower()
            if action not in ("fill", "set", "add"):
                sys.exit("非法 action %r（%s）" % (action, path))
            hero = (p.get("hero") or "").strip()
            ability = (p.get("ability") or "").strip()
            field = (p.get("field") or "").strip()
            if not hero or not field:
                stat["跳过（缺 hero/field）"] += 1
                continue
            conf = (p.get("confidence") or "").strip() or "推定"
            if conf not in CONF:
                sys.exit("confidence 非法 %r（%s 的 %s/%s）" % (conf, path, hero, field))
            value = (p.get("value") or "").strip()
            unit = (p.get("unit") or "").strip()
            note = (p.get("note") or "").strip()

            k = (hero, ability, field)
            cur = idx.get(k)

            if action == "add":
                if cur:
                    stat["add 跳过（已存在）"] += 1
                    continue
                row = norm({"hero": hero, "scope": p.get("scope", ""), "ability": ability,
                            "field": field, "alias": p.get("alias", "") or field,
                            "value": value, "unit": unit, "confidence": conf, "note": note})
                idx[k] = row
                rows.append(row)
                stat["add 新增"] += 1
                continue

            if not cur:
                stat["%s 跳过（表里没这行）" % action] += 1
                continue
            if not value:
                stat["%s 跳过（补丁无值）" % action] += 1
                continue
            if action == "fill":
                if (cur["value"] or "").strip():
                    stat["fill 跳过（已有值）"] += 1
                    continue
            old = (cur["value"] or "").strip()
            cur["value"] = value
            if unit:
                cur["unit"] = unit
            cur["confidence"] = conf
            if note:
                if action == "set":
                    # set 是"裁决/纠错"：note 以补丁为准（旧值留档），不叠加历史噪音
                    if old and old != value:
                        note += "（旧值 %s）" % old
                    cur["note"] = note
                elif note not in (cur["note"] or ""):
                    # fill 是"补缺"：保留原有出处，再接上新的
                    cur["note"] = note if not cur["note"] else cur["note"] + "｜" + note
            stat["%s 写入" % action] += 1

    rows.sort(key=lambda r: (r["hero"], r["scope"], r["ability"], r["field"], r["value"]))
    if not a.dry_run:
        with io.open(a.out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, delimiter="\t", lineterminator="\n",
                               extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    print("%s：%d 行（补丁 %d 个）" % ("[dry-run] " if a.dry_run else a.out, len(rows), len(a.patch)))
    for k, v in stat.most_common():
        print("  %-20s %d" % (k, v))
    print("confidence:", dict(collections.Counter(r["confidence"] for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
