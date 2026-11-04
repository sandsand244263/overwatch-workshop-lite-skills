#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""拉取 overwatch.weirdgloop.org 的英雄页 / 补丁页 wikitext，抽成结构化参数表。

用途：**第三方对照**。它是社区 MediaWiki，数字写在模板参数里（`| health = 250`），
不像普通百科那样只有给人看的表格——所以能机器抽取、能按修订号判断新旧。

它是**推定级**来源（人工转录，不是引擎导出）：
  - 字段值是编辑逐条抄的（编辑摘要里能看到「according to advanced info panel」）
  - 正文散文会过期，字段通常已更新 → **只信字段，不信正文**
  - 生命/护甲是 5v5 开放职责口径，我们表是 5v5 预设（重装差 +150，见 D-101）

用法：
    python tools/fetch_weirdgloop.py --kind heroes  --out <目录>
    python tools/fetch_weirdgloop.py --kind patches --out <目录> [--limit 0=全部]
    python tools/fetch_weirdgloop.py --kind all     --out <目录> --refresh

产物（都在 --out 下）：
    raw/<页面名>.wiki     原始 wikitext（有缓存就跳过，--refresh 强制重拉）
    index.tsv             页面 / 修订时间 / 字节 / 缓存文件 / 是否本次新拉
    params.tsv            page  kind  block  field_en  value_raw  value_num  unit  抽取结果
    fetch.log             每次运行的摘要（条数、耗时、失败页）

退出码：0 成功；1 有页面失败（明细见 fetch.log）。
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://overwatch.weirdgloop.org/api.php"
UA = "WorkshopLite/hero-numbers (local data cross-check; contact: repo issues)"
CATS = {"heroes": "Category:Heroes", "patches": "Category:Patches"}

# {{tt|显示值|实际值}} → 取显示值；<br> 拆行；[[]] 去链接；<ref> 去掉
RE_TT = re.compile(r"\{\{tt\|([^|}]*)(?:\|([^}]*))?\}\}", re.I)
RE_REF = re.compile(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", re.I | re.S)
RE_LINK = re.compile(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]")
RE_COMMENT = re.compile(r"<!--.*?-->", re.S)
RE_PARAM = re.compile(r"^\s*\|\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")
RE_ABILITY = re.compile(r"^\s*\|\s*(ability_name|name)\s*=\s*(.+?)\s*$")
RE_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def get(params, retries=3):
    url = API + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # 网络抖动/限流：退避重试
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("请求失败：%s（%s）" % (url[:120], last))


def pages_in_category(cat, limit=0):
    out, cont = [], None
    while True:
        p = {"action": "query", "list": "categorymembers", "cmtitle": cat,
             "cmlimit": "500", "format": "json", "formatversion": "2"}
        if cont:
            p["cmcontinue"] = cont
        d = get(p)
        out += [m["title"] for m in d["query"]["categorymembers"]]
        cont = d.get("continue", {}).get("cmcontinue")
        if not cont or (limit and len(out) >= limit):
            break
        time.sleep(0.5)
    return out[:limit] if limit else out


def fetch_pages(titles, cache_dir, refresh=False):
    """批量取 wikitext（50 个一批），有缓存就跳过。返回 [(title, rev_ts, size, fresh)]。"""
    meta, todo = [], []
    for t in titles:
        f = os.path.join(cache_dir, safe(t) + ".wiki")
        if os.path.isfile(f) and not refresh and os.path.getsize(f) > 0:
            meta.append((t, "", os.path.getsize(f), False))
        else:
            todo.append(t)
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        d = get({"action": "query", "prop": "revisions", "rvprop": "content|timestamp|size",
                 "rvslots": "main", "titles": "|".join(batch),
                 "format": "json", "formatversion": "2"})
        for pg in d["query"]["pages"]:
            if pg.get("missing"):
                meta.append((pg["title"], "MISSING", 0, True))
                continue
            rev = pg["revisions"][0]
            text = rev["slots"]["main"].get("content", "")
            with io.open(os.path.join(cache_dir, safe(pg["title"]) + ".wiki"), "w",
                         encoding="utf-8", newline="\n") as f:
                f.write(text)
            meta.append((pg["title"], rev["timestamp"], rev["size"], True))
        time.sleep(0.5)
    return meta


def safe(title):
    return re.sub(r'[\\/:*?"<>|]', "_", title)


def clean(v):
    v = RE_COMMENT.sub("", v)
    v = RE_REF.sub("", v)
    m = RE_TT.search(v)
    if m:
        return m.group(1).strip()
    v = RE_LINK.sub(r"\1", v)
    return v.strip()


def unit_of(v):
    m = re.search(r"(shots?/s|per second|/s\b|seconds?|sec\b|meters?|m\b|%|points?|HP|rounds?)", v, re.I)
    return m.group(1) if m else ""


def extract(title, text):
    """一页 → 参数行。block 用来区分「英雄层」与各技能（以 ability_name 切块）。"""
    rows, block, blabel = [], 0, ""
    for raw in text.split("\n"):
        line = clean(raw)
        am = RE_ABILITY.match(line)
        if am:
            block += 1
            blabel = clean(am.group(2))
            continue
        pm = RE_PARAM.match(line)
        if not pm:
            continue
        key, val = pm.group(1), pm.group(2)
        if not val or val.lower() in ("none", "n/a", "tbd", "?", ""):
            continue
        v = clean(val)
        if not v or len(v) > 200:
            continue
        nums = RE_NUM.findall(v)
        rows.append({
            "page": title,
            "block": block,
            "ability": blabel if block else "",
            "field_en": key,
            "value_raw": v,
            "value_num": nums[0] if nums else "",
            "unit": unit_of(v),
        })
    return rows


RE_PS = re.compile(r"\{\{ps\|([^}|]+)")
RE_AL = re.compile(r"\{\{al\|([^}|]+)\}\s*(\([^)]*\))?")
RE_HEAD = re.compile(r"^(={2,5})\s*(.+?)\s*\1\s*$")
RE_FROMTO = re.compile(r"from\s+(-?\d+(?:\.\d+)?)\s*[^\d.]{0,24}?\s+(?:to|→)\s+(-?\d+(?:\.\d+)?)")
RE_ARROW = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:->|→|=>)\s*(-?\d+(?:\.\d+)?)")
RE_SRC = re.compile(r"^\s*\|\s*source\s*=\s*(\S+)")
MONTHS = "%B %d, %Y"


def patch_date(title):
    m = re.match(r"(.+?)\s+Patch$", title)
    if not m:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.strptime(m.group(1), MONTHS))
    except ValueError:
        return ""


def extract_changes(title, text, heroes):
    """补丁页 → 改动行。结构化来源：`{{ps|英雄}}` / `{{al|技能}}` + `* … from A to B`。"""
    rows, part, hero, ability, src = [], "", "", "", ""
    date = patch_date(title)
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = RE_SRC.match(line)
        if m and not src:
            src = m.group(1)
            continue
        h = RE_HEAD.match(line)
        if h:
            level, name = len(h.group(1)), clean(h.group(2))
            name = RE_LINK.sub(r"\1", name)
            if level <= 3:
                part = name
            if name in heroes:
                hero, ability = name, ""
            elif level >= 4:
                ability = name
            continue
        m = RE_PS.search(line)
        if m:
            hero, ability = clean(m.group(1)), ""
            continue
        m = RE_AL.search(line)
        if m:
            ability = clean(m.group(1)) + (" " + m.group(2) if m.group(2) else "")
            continue
        if not line.startswith("*"):
            continue
        body = clean(line.lstrip("*").strip())
        if len(body) < 8:
            continue
        ft = RE_FROMTO.search(body) or RE_ARROW.search(body)
        frm, to = (ft.group(1), ft.group(2)) if ft else ("", "")
        low = body.lower()
        if re.search(r"reduced|decreased|lowered|nerf|no longer|removed", low):
            kind = "降低/移除"
        elif re.search(r"increased|raised|buffed|gained|added", low):
            kind = "提高/新增"
        elif frm:
            kind = "更改"
        else:
            kind = "其他"
        rows.append({"patch": title, "date": date, "part": part, "hero": hero,
                     "ability": ability, "kind": kind, "from_val": frm, "to_val": to,
                     "text": body[:300], "source": src})
    return rows


def main():
    ap = argparse.ArgumentParser(description="拉取 weirdgloop 英雄/补丁页并抽参数（第三方对照用）")
    ap.add_argument("--kind", choices=["heroes", "patches", "all"], default="heroes")
    ap.add_argument("--out", required=True, help="输出目录（会建 raw/ 子目录）")
    ap.add_argument("--refresh", action="store_true", help="忽略缓存，全部重拉")
    ap.add_argument("--limit", type=int, default=0, help="每类最多取几页（0=全部）")
    a = ap.parse_args()

    out = os.path.abspath(a.out)
    cache = os.path.join(out, "raw")
    os.makedirs(cache, exist_ok=True)
    kinds = ["heroes", "patches"] if a.kind == "all" else [a.kind]

    # 先把已有 index.tsv 读进来：params.tsv 是「全缓存重建」，不是「本次覆盖」，
    # 这样 heroes / patches 可以分几次跑而不互相冲掉。
    all_meta, log = [], []
    idx_path = os.path.join(out, "index.tsv")
    if os.path.isfile(idx_path):
        for r in csv.DictReader(io.open(idx_path, encoding="utf-8-sig"), delimiter="\t"):
            all_meta.append((r["page"], r["rev_ts"], int(r["size"] or 0), False, r["kind"]))

    for kind in kinds:
        titles = [t for t in pages_in_category(CATS[kind], a.limit) if "/" not in t]
        log.append("%s：分类 %s 下 %d 页" % (kind, CATS[kind], len(titles)))
        meta = fetch_pages(titles, cache, a.refresh)
        fresh = set()
        for t, ts, sz, fr in meta:
            fresh.add(t)
            all_meta = [m for m in all_meta if m[0] != t]
            all_meta.append((t, ts, sz, fr, kind))
            if ts == "MISSING":
                continue
        log.append("%s：缓存命中 %d，本次新拉 %d" % (
            kind, sum(1 for m in meta if not m[3]), sum(1 for m in meta if m[3])))

    # 从全部缓存重建 params.tsv
    all_rows = []
    for t, ts, sz, fr, kind in all_meta:
        if ts == "MISSING":
            continue
        p = os.path.join(cache, safe(t) + ".wiki")
        if not os.path.isfile(p):
            continue
        for r in extract(t, io.open(p, encoding="utf-8").read()):
            r["kind"] = kind
            all_rows.append(r)

    with io.open(os.path.join(out, "index.tsv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["page", "kind", "rev_ts", "size", "fresh"])
        for t, ts, sz, fr, kind in all_meta:
            w.writerow([t, kind, ts, sz, "new" if fr else "cached"])

    cols = ["page", "kind", "block", "ability", "field_en", "value_raw", "value_num", "unit"]
    with io.open(os.path.join(out, "params.tsv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter="\t", lineterminator="\n",
                           extrasaction="ignore")
        w.writeheader()
        for r in all_rows:
            w.writerow(r)

    # 补丁页 → 结构化改动清单（hero/ability/from→to），给「补丁审计」用
    heroes = {t for (t, ts, sz, fr, kind) in all_meta if kind == "heroes" and ts != "MISSING"}
    changes = []
    for t, ts, sz, fr, kind in all_meta:
        if kind != "patches" or ts == "MISSING":
            continue
        p = os.path.join(cache, safe(t) + ".wiki")
        if os.path.isfile(p):
            changes += extract_changes(t, io.open(p, encoding="utf-8").read(), heroes)
    changes.sort(key=lambda r: (r["date"], r["patch"], r["hero"]))
    ccols = ["date", "patch", "part", "hero", "ability", "kind", "from_val", "to_val", "text", "source"]
    with io.open(os.path.join(out, "changes.tsv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=ccols, delimiter="\t", lineterminator="\n",
                           extrasaction="ignore")
        w.writeheader()
        for r in changes:
            w.writerow(r)
    log.append("补丁改动行 %d（补丁页 %d）" % (
        len(changes), len({r["patch"] for r in changes})))

    missing = [m[0] for m in all_meta if m[1] == "MISSING"]
    log.append("参数行 %d（页 %d）；缺失页 %d" % (len(all_rows), len(all_meta), len(missing)))
    with io.open(os.path.join(out, "fetch.log"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(log) + "\n")
    print("\n".join(log))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
