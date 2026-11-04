#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 data/hero-numbers.tsv —— 英雄默认数值参考表（只管查，不参与校验）。

这张表回答一个具体问题：**设计模式时，这个英雄的原值是多少？**
（改血量前知道基础值、算 DPS 要知道射速、调冷却前知道默认几秒。）

数据来源与置信度（`confidence` 列只有五档）：
  已解析  客户端 154905 导出（面板行 / loadout 级 0x130），或实机面板读数
  推定    公式推算，或第三方（overlab.cn，带原始串与判据）
  存疑    值读到了但归行判不了，或与补丁记录冲突未裁决
  缺失    面板有这一行但行内没有取值槽（游戏不显示数字）
  未解析  槽位是占位节点（-0.5），值在运行时表达式里

判据顺序（D-098，冲突时按这个裁决）：
  实机读数 > 本次导出资产 > 官方补丁记录 > 第三方

**这张表不进 lint()**：它不产生任何检查、不影响校验结果，只在 `ws.py stats/nums` 里被查。
空的 `value` 是合法状态 —— agent 读到空就该知道「这个数我们不知道」，而不是当成 0（D-088）。

用法：
    python tools/gen_hero_numbers.py --src <hero-numbers 源 TSV>
    python tools/gen_hero_numbers.py --check [--src …]      # 只比对，漂移退出 1
    （源路径也可以用环境变量 WS_HERO_NUMBERS 给；都没有 → 退出 2，devcheck 按「找不到输入」跳过）
"""
import argparse
import csv
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "hero-numbers.tsv")
FIELDS = ["hero", "scope", "ability", "field", "alias", "value", "unit", "confidence", "note"]
CONF = ("已解析", "推定", "存疑", "缺失", "未解析")


def src_from_paths():
    """装机份的 local_paths.json 里可以写 "hero_numbers": "<源 TSV>"；公开仓没有这个文件。"""
    p = os.path.join(ROOT, "local_paths.json")
    if os.path.isfile(p):
        try:
            return json.load(io.open(p, encoding="utf-8")).get("hero_numbers")
        except Exception:
            return None
    return None


def resolve_src(explicit):
    for cand in (explicit, os.environ.get("WS_HERO_NUMBERS"), src_from_paths()):
        if cand and os.path.isfile(cand):
            return cand
    return None


def read_rows(src):
    with io.open(src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    bad = [r for r in rows if (r.get("confidence") or "") not in CONF]
    if bad:
        sys.exit("源表里有 %d 行 confidence 非法（只允许 %s），例：%r"
                 % (len(bad), "/".join(CONF), bad[0]))
    for r in rows:
        for k in ("value", "unit", "note", "ability", "alias"):
            r[k] = (r.get(k) or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
        # 没有技能名 = 英雄级（属性/角色被动），口径统一，免得下游按 scope 过滤时漏行
        if not r["ability"]:
            r["scope"] = "英雄属性"
    rows.sort(key=lambda r: (r["hero"], r["scope"], r["ability"], r["field"], r["value"]))
    return rows


def render(rows):
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=FIELDS, delimiter="\t", lineterminator="\n",
                       extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return out.getvalue()


def main():
    ap = argparse.ArgumentParser(description="生成 data/hero-numbers.tsv（英雄默认数值参考表）")
    ap.add_argument("--src", default=None, help="源 TSV（hero-numbers 导出）")
    ap.add_argument("--check", action="store_true", help="只比对，漂移退出 1")
    a = ap.parse_args()

    src = resolve_src(a.src)
    if not src:
        print("找不到输入（源 TSV）：用 --src、WS_HERO_NUMBERS 或 local_paths.json 的 hero_numbers 指定")
        return 2

    text = render(read_rows(src))
    if a.check:
        if not os.path.isfile(OUT):
            print("≠ 缺少 %s" % OUT)
            return 1
        cur = io.open(OUT, encoding="utf-8-sig", newline="").read()
        if cur.replace("\r\n", "\n") == text:
            print("= 无漂移（%d 行）" % (text.count("\n") - 1))
            return 0
        old_lines = set(cur.replace("\r\n", "\n").splitlines())
        new_lines = set(text.splitlines())
        add = len(new_lines - old_lines)
        rm = len(old_lines - new_lines)
        print("≠ data/hero-numbers.tsv 有漂移：新增 %d 条 / 消失 %d 条" % (add, rm))
        for line in list(new_lines - old_lines)[:3]:
            print("   + " + line[:110])
        for line in list(old_lines - new_lines)[:3]:
            print("   - " + line[:110])
        print("修：python tools/gen_hero_numbers.py --src <源 TSV>")
        return 1

    with io.open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        f.write(text)
    rows = text.count("\n") - 1
    heroes = len({l.split("\t")[0] for l in text.splitlines()[1:]})
    print("写出 %s：%d 行 / %d 英雄" % (OUT, rows, heroes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
