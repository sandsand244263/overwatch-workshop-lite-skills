#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 `data/setting-values.tsv` —— 设置键的**取值词表**（只收有明确 allowed 的词类键）。

为什么不并进 `setting-ranges.tsv`：那张表只放数字上下界（key/min/max），
这张表只放「能写哪些词」。数值走范围，词类走词表，两张表不重叠，也不会有
「同一件事两处定义、改一处漏一处」的问题。

来源（都在 data/ 内，不依赖本机 C:\\owdump 的临时导出物）：
  data/setting-schemas.tsv   每 (schema, key) 的 type；Enum 键的清单来自这里
  data/enum-values.tsv       枚举键的合法值原文（列 `合法值原文`，| 分隔）
                             原始出处：CASC 0x0C6 RulesetSchemaValueEnum.Choices

口径（关键，别改错）：
  · 同一个键可能属于多个 schema，各 schema 的选项集不同 → 这里取**并集**。
    并集只会少报（跨模式放行），不会误报；按单个 schema 收紧需要块上下文，
    当前 lint 是按行扫的，拿不到「这行在哪个模式块里」。
  · BOOL 键**不进这张表**：布尔词表是类型级规则（只认 开启/关闭），
    已由 core.check_setting_bools 管，进表反而会被当成「每键不同」而重复。

用法：
  python tools/gen_setting_values.py                # 写文件
  python tools/gen_setting_values.py --check        # 只比对；有漂移退出码 1
  python tools/gen_setting_values.py --out 路径     # 换输出位置（测试用）
"""
import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
OUT_NAME = "setting-values.tsv"

HEADER = ["key", "type", "allowed", "schemas", "source"]


def _rows(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def build():
    """返回 (表文本, 统计 dict)。两次调用结果必须逐字节一致。"""
    schemas = _rows(os.path.join(DATA, "setting-schemas.tsv"))
    enums = _rows(os.path.join(DATA, "enum-values.tsv"))

    enum_keys = {}          # key -> set(schema)
    for r in schemas:
        key = (r.get("key") or "").strip()
        if not key or "Enum" not in (r.get("type") or ""):
            continue
        enum_keys.setdefault(key, set()).add((r.get("schema") or "").strip())

    allowed = {}            # key -> set(值)
    for r in enums:
        key = (r.get("键名") or "").strip()
        if key not in enum_keys:
            continue
        for v in (r.get("合法值原文") or "").split("|"):
            v = v.strip()
            if v:
                allowed.setdefault(key, set()).add(v)

    lines = ["\t".join(HEADER)]
    missing = []
    for key in sorted(enum_keys):
        vals = allowed.get(key) or set()
        if not vals:
            missing.append(key)
        lines.append("\t".join([
            key,
            "Enum",
            "|".join(sorted(vals)),
            "、".join(sorted(s for s in enum_keys[key] if s)),
            "data/enum-values.tsv（CASC 0x0C6 RulesetSchemaValueEnum.Choices 并集）",
        ]))
    stats = {"keys": len(enum_keys), "with_allowed": len(enum_keys) - len(missing),
             "missing": missing}
    return "\n".join(lines) + "\n", stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对，不写文件")
    ap.add_argument("--out", default=os.path.join(DATA, OUT_NAME))
    args = ap.parse_args()

    text, st = build()
    print("枚举键 %d 个：有合法值 %d / 缺 %d" % (st["keys"], st["with_allowed"], len(st["missing"])))
    if st["missing"]:
        print("  缺合法值的键（enum-values.tsv 里没写）：%s" % "、".join(st["missing"]))
    if args.check:
        path = args.out
        if not os.path.isfile(path):
            print("✗ 缺少 %s（先跑一次不带 --check）" % path)
            return 1
        old = open(path, encoding="utf-8").read()
        if old != text:
            print("✗ %s 与生成结果不一致（有漂移）" % os.path.basename(path))
            return 1
        print("✓ %s 无漂移（%d 行）" % (os.path.basename(path), text.count("\n")))
        return 0
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("✓ 写入 %s（%d 行）" % (args.out, text.count("\n")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
