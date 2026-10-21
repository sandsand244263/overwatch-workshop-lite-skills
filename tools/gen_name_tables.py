#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 data/ 里已有的导出表生成「名字存在性」检查用的名字表。

生成：
  data/heroes.tsv        英雄名（54）
  data/abilities.tsv     技能名 + 所属英雄
  data/buttons.tsv       按钮名（主要攻击模式 / 技能1 …）
  data/setting-keys.tsv  设置键全集（模式 / 大厅 / 主程序 / 英雄页）

一次生成，之后由 core.py 直接读 tsv；游戏更新后重跑本脚本即可。
  python tools/gen_name_tables.py
"""
import csv
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
DATA = os.path.join(ROOT, "data")

BUTTON_DROPDOWN = "000000004A39.01C"     # param-docs 里按钮参数的 ButtonConstant 选项表


def rows(name):
    path = os.path.join(DATA, name)
    if not os.path.isfile(path):
        return []
    return list(csv.DictReader(open(path, encoding="utf-8-sig"), delimiter="\t"))


def write(name, header, data):
    path = os.path.join(DATA, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(header) + "\n")
        for r in data:
            f.write("\t".join(str(x).replace("\t", " ") for x in r) + "\n")
    print("%-22s %d 行" % (name, len(data)))


def gen_heroes():
    out, seen = [], set()
    for r in rows("hero-setting-names.tsv"):
        h = (r.get("英雄") or "").strip()
        if h and h not in seen:
            seen.add(h)
            out.append((h, "英雄设定页"))
    for f in ("hero-stats.tsv", "ability-stats.tsv"):
        for r in rows(f):
            h = (r.get("hero") or "").strip()
            if h and h not in seen:
                seen.add(h)
                out.append((h, f))
    write("heroes.tsv", ("name", "source"), out)


def gen_abilities():
    out, seen = [], set()
    for r in rows("hero-setting-names.tsv"):
        a = (r.get("技能名") or "").strip()
        h = (r.get("英雄") or "").strip()
        if not a or not h:
            continue
        if "未确认" in a or "候选" in a or "%1$s" in a:
            continue
        if (a, h) in seen:
            continue
        seen.add((a, h))
        out.append((a, h, "英雄设定页"))
    for r in rows("ability-stats.tsv"):
        a = (r.get("ability") or "").strip()
        h = (r.get("hero") or "").strip()
        if not a or not h or (a, h) in seen:
            continue
        seen.add((a, h))
        out.append((a, h, "客户端 STU"))
    write("abilities.tsv", ("name", "hero", "source"), out)


def gen_buttons():
    out = [(r["option"].strip(), BUTTON_DROPDOWN)
           for r in rows("dropdown-options.tsv")
           if r.get("dropdown") == BUTTON_DROPDOWN and (r.get("option") or "").strip()]
    write("buttons.tsv", ("name", "dropdown"), out)


def gen_setting_keys():
    """设置键全集：只要在任一导出表里出现过就算合法。

    宁可多留不许少留——漏一个就是真文件上的误报。
    """
    out, seen = [], set()

    def add(key, owner, src):
        key = (key or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        out.append((key, owner or "", src))

    for r in rows("settings.tsv"):
        add(r.get("key"), r.get("schema"), "settings")
    for r in rows("setting-ranges.tsv"):
        add(r.get("key"), "", "ranges")
    for r in rows("mode-pages.tsv"):
        add(r.get("key"), r.get("owner"), "mode-pages")
    for r in rows("settings-pages.tsv"):
        add(r.get("key"), r.get("owner"), "settings-pages")
    for r in rows("schema-keys.tsv"):
        add(r.get("key"), r.get("schema_name"), "schema-keys")
    for r in rows("lobby-keys.tsv"):
        add(r.get("key"), "大厅", "lobby-keys")
    for r in rows("lobby-values.tsv"):
        add(r.get("键名"), "大厅", "lobby-values")
    for r in rows("verified-keys.tsv"):
        add(r.get("key"), "实测", "verified-keys")
    for r in rows("hero-setting-names.tsv"):
        add(r.get("键名"), r.get("英雄"), "英雄设定页")
    for r in rows("hero-official-keys.tsv"):
        add(r.get("key"), r.get("hero"), "英雄官方键")
    for r in rows("hero-visible-keys.tsv"):
        add(r.get("key"), r.get("hero"), "英雄可见键")
    # 主程序块里只有这两个键（描述 / 模式名称），导出表里未必有
    add("描述", "主程序", "实测")
    add("模式名称", "主程序", "实测")
    write("setting-keys.tsv", ("key", "owner", "source"), out)


def main():
    if not os.path.isdir(DATA):
        sys.exit("找不到 data/：%s" % DATA)
    gen_heroes()
    gen_abilities()
    gen_buttons()
    gen_setting_keys()
    return 0


if __name__ == "__main__":
    sys.exit(main())
