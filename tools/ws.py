#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkshopLite 唯一入口。

  python tools/ws.py check  模式.ow [更多文件...]     校验
  python tools/ws.py count  模式.ow                   元素数估算
  python tools/ws.py defaults 创建HUD文本              查参数默认值（省略时游戏用什么）
  python tools/ws.py publish 模式.ow --outdir out [--obf numbers,vars]
  python tools/ws.py gen --src 导出目录                 重新生成 data/
  python tools/ws.py diff --prev 旧导出 --cur 新导出     全量对照

数据永远从 data/ 读；docs/ 里是数据里没有的规则。
"""
import argparse
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, TOOLS)

import core  # noqa: E402


def load():
    sigs, labels, _opts = core.load_signatures(os.path.join(DATA, "signatures.md"))
    settings = core.load_settings_schema(os.path.join(DATA, "settings.tsv"))
    return sigs, labels, settings


def cmd_check(args):
    sigs, labels, settings = load()
    failed = 0
    for path in args.files:
        if not os.path.isfile(path):
            print("[错误] 找不到 %s" % path)
            failed += 1
            continue
        problems = core.lint(path, sigs, labels, settings)
        errors = [p for p in problems if p[1] == "error"]
        name = os.path.basename(path)
        if errors:
            failed += 1
            print("✗ %s：%d 个 error，%d 个 warning" % (name, len(errors), len(problems) - len(errors)))
            for ln, level, msg in problems:
                print("   %s %s：%s" % ("第 %d 行" % ln if ln else "全文", level, msg))
        else:
            print("✓ %s：通过（warning %d）" % (name, len(problems)))
            for ln, level, msg in problems[:5]:
                print("   %s %s：%s" % ("第 %d 行" % ln if ln else "全文", level, msg))
    return 1 if failed else 0


def cmd_defaults(args):
    """查某函数每个参数的默认值（省略尾部参数时游戏用什么）。"""
    path = os.path.join(DATA, "defaults.tsv")
    if not os.path.isfile(path):
        print("缺少 data/defaults.tsv，先跑 ws.py gen")
        return 2
    rows = [l.rstrip(chr(10)).split("	") for l in open(path, encoding="utf-8") if not l.startswith("func	")]
    for name in args.funcs:
        hit = [r for r in rows if r[0] == name]
        if not hit:
            print("%s：数据里没有这个函数" % name)
            continue
        print("%s：" % name)
        for _f, idx, pname, val in hit:
            print("   第 %d 个参数 %-10s 默认 %s" % (int(idx) + 1, pname, val))
    return 0


def cmd_count(args):
    sigs, labels, settings = load()
    from element_count import estimate, describe
    for path in args.files:
        est, detail = estimate(path, sigs, labels)
        print("%s：预计 %d 个元素（%s）" % (os.path.basename(path), est, describe(detail)))
        print("  上限 32768。估算仅供预警，最终以游戏「显示诊断结果 → 总计元素数量」为准。")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="ws", description="WorkshopLite 工具入口")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="校验 .ow")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("defaults", help="查参数默认值")
    p.add_argument("funcs", nargs="+")
    p.set_defaults(func=cmd_defaults)

    p = sub.add_parser("count", help="元素数估算")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=cmd_count)

    p = sub.add_parser("publish", help="出发布文件（默认只出源码版）")
    p.add_argument("src")
    p.add_argument("--outdir", default=".")
    p.add_argument("--obf", default="", help="numbers,vars,rules,indexes,local-indexes")
    p.add_argument("--fix", action="store_true")
    p.set_defaults(func=lambda a: __import__("publish").main_with_args(a))

    p = sub.add_parser("gen", help="从导出重新生成 data/")
    p.add_argument("--src", required=True)
    p.add_argument("--out", default=DATA)
    p.set_defaults(func=lambda a: __import__("gen_data").main_with_args(a))

    p = sub.add_parser("diff", help="两个导出目录全量对照")
    p.add_argument("--prev", required=True)
    p.add_argument("--cur", required=True)
    p.set_defaults(func=lambda a: __import__("data_diff").main_with_args(a))

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
