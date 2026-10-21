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
        _print_update_hint()
    return 1 if failed else 0


def cmd_check_all(args):
    import glob
    files = sorted(glob.glob(os.path.join(ROOT, "tools", "probes", "*.ow"))) + \
            sorted(glob.glob(os.path.join(ROOT, "tools", "probes", "calib", "*.ow")))
    return cmd_check(type("A", (), {"files": files})())


def cmd_baseline(args):
    """比较 data/meta.json 的 build 与游戏当前 build。"""
    import json
    meta_path = os.path.join(DATA, "meta.json")
    data_build = None
    if os.path.isfile(meta_path):
        data_build = json.load(open(meta_path, encoding="utf-8")).get("build")
    game_dir = args.game_dir or os.environ.get("OW_GAME_DIR") or "E:/Overwatch"
    game_build = core.parse_build_info(os.path.join(game_dir, ".build.info"))
    print("数据基线：%s" % (data_build or "未知"))
    print("游戏版本：%s" % (game_build or "读不到（%s/.build.info）" % game_dir))
    if not game_build:
        return 0
    if data_build and game_build != data_build:
        print("→ 版本不一致，建议更新数据（见 workshop-data-update 技能步骤 0）")
        return 1
    print("→ 一致")
    return 0


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

    p = sub.add_parser("settings", help="按模式生成设置块")
    p.add_argument("--mode", required=True)
    p.add_argument("--hero", default=None, help="额外生成某个英雄的设置块")
    p.add_argument("--lobby", action="store_true", help="额外生成大厅块")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_settings)

    p = sub.add_parser("modes", help="列出全部模式")
    p.set_defaults(func=cmd_modes)

    p = sub.add_parser("explain", help="按关键词查工坊报错文案")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("update-check", help="查技能是否有新版本")
    p.set_defaults(func=cmd_update_check)

    p = sub.add_parser("baseline", help="比较数据基线与游戏版本")
    p.add_argument("--game-dir", default=None)
    p.set_defaults(func=cmd_baseline)

    p = sub.add_parser("check-all", help="回归：probes 与 calib 全部样本")
    p.set_defaults(func=cmd_check_all)

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

# ---------------- settings: 按模式生成设置块 ----------------
VALUE_WORD_MAP = {"启用": "开启", "禁用": "关闭", "是": "开启", "否": "关闭"}

# 实测：这些键在游戏数据里有，但写进 .ow 的对应模式块会被判定为非法（"之后应有一个游戏模式设置"）
# 加进来之前必须实机导入验证过，不要凭感觉加。
NOT_WRITABLE = {"威能充能速度", "追赶等级时造成消灭威能加值"}


def _load_settings_values():
    """settings.tsv -> {(schema, key): 第一个合法值}"""
    import csv
    path = os.path.join(DATA, "settings.tsv")
    out = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            raw = (row.get("values") or "").strip()
            if not raw:
                if (row.get("type") or "").upper() == "BOOL":   # 布尔项数据里没有选项，默认开
                    out[(row.get("schema", ""), row.get("key", ""))] = {"value": "开启", "raw": "BOOL", "kind": "BOOL"}
                continue
            opts = [x.strip() for x in raw.split("|") if x.strip()]
            concrete = [x for x in opts if not x.startswith("默认")] or opts
            first = concrete[0]
            if "~" in first:                              # 范围 1~5000 / 0.1~5 → 取下界
                first = first.split("~")[0].strip()
            first = VALUE_WORD_MAP.get(first, first)
            out[(row.get("schema", ""), row.get("key", ""))] = {"value": first, "raw": raw, "kind": row.get("type", "")}
    return out


def _load_pages(name):
    import csv
    path = os.path.join(DATA, name)
    rows = list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))
    return rows


def build_settings_block(mode, hero=None, lobby=False):
    """按 game 数据里的页序 / 键序，生成「设置」块的文本。"""
    pages = _load_pages("mode-pages.tsv")
    vals = _load_settings_values()
    grouped = {}
    for r in pages:
        if r["owner"] != mode:
            continue
        page = r["page"] or "(未命名)"
        grouped.setdefault(page, []).append(r)

    if not grouped:
        known = sorted({r["owner"] for r in pages})
        raise SystemExit("没有这个模式：%s\n可用的有：%s" % (mode, "、".join(known[:20]) + (" …" if len(known) > 20 else "")))

    lines = ["设置", "{"]
    if lobby:
        lines += build_lobby_block(vals)
    hero_lines = build_hero_block(hero, vals) if hero else None
    lines += ["\t模式", "\t{"]
    for page, rows in grouped.items():
        lines.append("\t\t%s" % page)
        lines.append("\t\t{")
        for r in sorted(rows, key=lambda x: x["key"]):      # .ow 块内键序 = Unicode 码位升序
            key = r["key"]
            if not key:
                continue
            meta = vals.get((r["schema_guid"], key)) or vals.get((page, key))
            if not meta:
                continue                                  # 没有合法值可填，宁可不写
            lines.append("\t\t\t%s: %s" % (key, meta["value"]))
        lines.append("\t\t}")
    lines += ["\t}"]
    if hero_lines:
        lines += hero_lines
    lines += ["}", ""]
    return "\n".join(lines)


def _value_of(vals, schema, key):
    meta = vals.get((schema, key))
    if not meta:
        for (sc, k), m in vals.items():
            if k == key:
                return m["value"]
        return None
    return meta["value"]


def build_lobby_block(vals):
    import csv
    path = os.path.join(DATA, "lobby-keys.tsv")
    rows = list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))
    lines = ["\t大厅", "\t{"]
    for r in sorted(rows, key=lambda x: x["key"]):
        v = r.get("default_value") or _value_of(vals, "", r["key"])
        if v:
            lines.append("\t\t%s: %s" % (r["key"], v))
    lines.append("\t}")
    return lines


def build_hero_block(hero, vals):
    import csv
    path = os.path.join(DATA, "hero-pages.tsv")
    rows = [r for r in csv.DictReader(open(path, encoding="utf-8"), delimiter="\t") if r["owner"] == hero]
    if not rows:
        return None
    grouped = {}
    for r in rows:
        grouped.setdefault(r["page"] or "(未命名)", []).append(r)
    lines = ["\t英雄", "\t{"]
    for page, rs in grouped.items():
        lines.append("\t\t%s" % page)
        lines.append("\t\t{")
        for r in sorted(rs, key=lambda x: x["key"]):
            key = r["key"]
            if not key:
                continue
            v = _value_of(vals, page, key)
            if v is None:
                continue
            lines.append("\t\t\t%s: %s" % (key, v))
        lines.append("\t\t}")
    lines.append("\t}")
    return lines


# ---------------- 版本检查（缓存 + 静默失败） ----------------
REPO = "sandsand244263/overwatch-workshop-lite-skills"


def _skill_version():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "SKILL.md")
    try:
        for line in open(path, encoding="utf-8"):
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def check_update(quiet=True, force=False):
    """查 GitHub 最新 release。缓存 24 小时；任何失败都静默。"""
    import json, time, urllib.request
    cache = os.path.join(DATA, ".update-cache.json")
    now = time.time()
    info = None
    if not force and os.path.isfile(cache):
        try:
            c = json.load(open(cache, encoding="utf-8"))
            if now - c.get("t", 0) < 86400:
                info = c
        except (OSError, ValueError):
            pass
    if info is None:
        tag = None
        # 首选 raw 文件（不限流）；API 有 60 次/小时的匿名限额，会 403
        try:
            url = "https://raw.githubusercontent.com/%s/main/SKILL.md" % REPO
            req = urllib.request.Request(url, headers={"User-Agent": "workshop-lite"})
            with urllib.request.urlopen(req, timeout=2.0) as r:
                for line in r.read(4000).decode("utf-8", "replace").splitlines():
                    if line.startswith("version:"):
                        tag = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass
        if not tag:
            try:
                req = urllib.request.Request(
                    "https://api.github.com/repos/%s/releases/latest" % REPO,
                    headers={"User-Agent": "workshop-lite", "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=2.0) as r:
                    tag = json.load(r).get("tag_name", "").lstrip("v")
            except Exception:
                return None                  # 没网 / 超时 / 限流：静默
        if not tag:
            return None
        info = {"t": now, "latest": tag}
        try:
            json.dump(info, open(cache, "w", encoding="utf-8"))
        except OSError:
            pass
    cur, latest = _skill_version(), info.get("latest")
    if cur and latest and cur != latest:
        return (cur, latest)
    return None


def _print_update_hint():
    try:
        hit = check_update()
    except Exception:
        return
    if hit:
        cur, latest = hit
        print("  提示：技能有新版本 v%s（当前 v%s）" % (latest, cur))
        print("        升级：npx skills add %s" % REPO)


def cmd_update_check(args):
    hit = check_update(quiet=False, force=True)
    if hit:
        print("有新版本：当前 v%s → 最新 v%s" % hit)
        print("升级：npx skills add %s" % REPO)
        return 1
    if _skill_version():
        print("已是最新（v%s）" % _skill_version())
    else:
        print("查不到最新版本（没网 / 超时 / 限流）")
    return 0


def cmd_explain(args):
    """按关键词搜工坊报错文案（数据来自游戏内的报错字符串）。"""
    import csv
    path = os.path.join(DATA, "errors.tsv")
    rows = list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))
    kw = args.keyword.lower()
    hits = [r for r in rows if kw in r["text"].lower() or kw in r["group"].lower()]
    if not hits:
        print("没有匹配“%s”的报错文案（共 %d 条）" % (args.keyword, len(rows)))
        return 1
    for r in hits[: args.limit]:
        print("[%s%s] %s" % (r["layer"], " " + r["group"] if r["group"] else "", r["text"]))
    if len(hits) > args.limit:
        print("…共 %d 条，用 --limit 调整" % len(hits))
    return 0


def cmd_settings(args):
    text = build_settings_block(args.mode, hero=args.hero, lobby=args.lobby)
    if args.out:
        open(args.out, "w", encoding="utf-8", newline="").write(text.replace("\n", "\r\n"))
        print("已写入 %s" % args.out)
    else:
        print(text)
    return 0


def cmd_modes(args):
    pages = _load_pages("mode-pages.tsv")
    cnt = {}
    for r in pages:
        cnt[r["owner"]] = cnt.get(r["owner"], 0) + 1
    for name, n in sorted(cnt.items(), key=lambda x: -x[1]):
        print("%-16s %4d 条" % (name, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())


