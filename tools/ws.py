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
        problems = core.lint(path, sigs, labels, settings,
                             event_params=core.load_event_params(os.path.join(DATA, "event-params.tsv")),
                             bare_ok=core.load_bare_ok(os.path.join(DATA, "bare-ok.tsv")),
                             kinds=core.load_element_kinds(os.path.join(DATA, "element-kinds.tsv")),
                             event_param_words=core.load_event_param_words(os.path.join(DATA, "event-param-words.tsv")),
                             setting_ranges=core.load_setting_ranges(os.path.join(DATA, "setting-ranges.tsv")))
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
    rc = cmd_check(type("A", (), {"files": files})())

    # 反向用例：坏文件必须报出预期错误，没报出来就是校验器退化
    neg_dir = os.path.join(ROOT, "tools", "probes", "negative")
    manifest = os.path.join(neg_dir, "expect.tsv")
    if os.path.isfile(manifest):
        print("\n反向用例（应当报错）：")
        import csv as _csv
        bad_count = 0
        for r in _csv.DictReader(open(manifest, encoding="utf-8"), delimiter="\t"):
            path = os.path.join(neg_dir, r["file"])
            sigs, labels, settings = load()
            probs = core.lint(path, sigs, labels, settings,
                              event_params=core.load_event_params(os.path.join(DATA, "event-params.tsv")),
                             bare_ok=core.load_bare_ok(os.path.join(DATA, "bare-ok.tsv")),
                             kinds=core.load_element_kinds(os.path.join(DATA, "element-kinds.tsv")),
                             event_param_words=core.load_event_param_words(os.path.join(DATA, "event-param-words.tsv")),
                             setting_ranges=core.load_setting_ranges(os.path.join(DATA, "setting-ranges.tsv")))
            errs = [p[2] for p in probs if p[1] == "error"]
            hit = any(r["expect"] in e for e in errs)
            print("%s %s：%s" % ("✓" if hit else "✗", r["file"],
                                "已报出预期错误" if hit else "没报出「%s」（实际：%s）" % (r["expect"], errs[:2])))
            if not hit:
                bad_count += 1
                rc = 1
        print("反向用例通过 %d 个，失败 %d 个" % (len(list(_csv.DictReader(open(manifest, encoding="utf-8"), delimiter="\t"))) - bad_count, bad_count))
    return rc


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


def cmd_doc(a):
    """查官方说明：元素说明 + 参数说明 + 下拉选项说明。"""
    import csv

    def load(name):
        path = os.path.join(DATA, name)
        if not os.path.isfile(path):
            sys.exit("缺少 %s，先跑 python tools/extract_docs.py --export <导出目录>" % path)
        return list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))

    docs = load("element-docs.tsv")
    params = load("param-docs.tsv")
    options = load("dropdown-options.tsv")

    if a.search:
        kw = a.search
        hits = [d for d in docs if kw in d["name"] or kw in d["description"]]
        if not hits:
            print("没有匹配「%s」的元素" % kw)
            return 1
        for d in hits[: a.limit]:
            print("[%s] %s" % (d["kind"], d["name"]))
            if d["description"]:
                print("     %s" % d["description"])
        if len(hits) > a.limit:
            print("\n… 还有 %d 条，用 --limit 调大" % (len(hits) - a.limit))
        return 0

    name = a.name
    hit = [d for d in docs if d["name"] == name]
    if not hit:
        cands = sorted({d["name"] for d in docs if name in d["name"]})[:10]
        print("没有元素叫「%s」%s" % (name, "，相近的有：" + "、".join(cands) if cands else ""))
        return 1

    for d in hit:
        print("=== [%s] %s ===" % (d["kind"], d["name"]))
        print(d["description"] or "（无官方说明）")
        ps = [p for p in params if p["element"] == d["name"] and p["kind"] == d["kind"]]
        if ps:
            print("\n参数：")
        for p in ps:
            flags = []
            if p["default"]:
                flags.append("默认 %s" % p["default"])
            if p["input_type"]:
                flags.append(p["input_type"])
            if p["min"] not in ("", "0.0") or p["max"] not in ("", "0.0"):
                flags.append("范围 %s~%s" % (p["min"], p["max"]))
            print("  %d. %s（%s）" % (int(p["index"]) + 1, p["name"], "，".join(flags)))
            if p["description"]:
                print("       %s" % p["description"])
            if p["options"]:
                opts = p["options"].split("|")
                shown = "、".join(opts[:12]) + ("…" if len(opts) > 12 else "")
                print("       可选：%s" % shown)
                described = [o for o in options if o["dropdown"] == p["dropdown"] and o["description"]]
                for o in described[:4]:
                    print("         - %s：%s" % (o["option"], o["description"]))
        print()
    return 0


def cmd_stats(a):
    """查英雄/技能数值（来自客户端 STU 数据）。"""
    import csv

    def load(name):
        path = os.path.join(DATA, name)
        if not os.path.isfile(path):
            sys.exit("缺少 %s" % path)
        return list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))

    heroes = load("hero-stats.tsv")
    abilities = load("ability-stats.tsv")
    dmg = load("ability-values.tsv") if os.path.isfile(os.path.join(DATA, "ability-values.tsv")) else (load("ability-damage.tsv") if os.path.isfile(os.path.join(DATA, "ability-damage.tsv")) else [])
    kw = a.name

    hh = [r for r in heroes if r["hero"] == kw] or [r for r in heroes if kw in r["hero"]]
    aa = [r for r in abilities if r["hero"] == kw] or [r for r in abilities if kw in r["hero"] or kw in r["ability"]]
    dd = [r for r in dmg if r["hero"] == kw and r["ability"] != "英雄属性" and r["value"].strip()] or \
         [r for r in dmg if (kw in r["hero"] or kw in r["ability"]) and r["ability"] != "英雄属性" and r["value"].strip()]
    if not hh and not aa:
        # 退化为全局搜索：技能名 / 字段名
        hits = [r for r in dmg if kw in r["ability"] or kw in r["field"]]
        if hits:
            print("=== 含「%s」的数值（%d 条）===" % (kw, len(hits)))
            cur = None
            for r in sorted(hits, key=lambda x: (x["hero"], x["ability"]))[: a.limit]:
                key = "%s / %s" % (r["hero"], r["ability"])
                if key != cur:
                    cur = key
                    print("  [%s]" % key)
                print("    %-22s %s %s" % (r["field"], r["value"], r["unit"]))
            if len(hits) > a.limit:
                print("  … 还有 %d 条，用 --limit 调大" % (len(hits) - a.limit))
            return 0
        print("没有「%s」的数值。可查英雄：%s" % (kw, "、".join(sorted({r["hero"] for r in heroes}))))
        return 1

    if hh:
        print("=== %s 英雄属性 ===" % hh[0]["hero"])
        for r in hh:
            ev = r.get("evidence", "")
            mark = "（推定）" if ("推定" in ev and "面板校准" not in ev) else ""
            print("  %-8s %s %s%s" % (r["field"], r["value"], r["unit"], mark))
        print()
    if dd:
        print("=== %s 技能数值（技能面板行）===" % dd[0]["hero"])
        cur = None
        for r in sorted(dd, key=lambda x: (x["ability"], x["field"])):
            if r["ability"] != cur:
                cur = r["ability"]
                print("  [%s]" % cur)
            raw = r["value"].strip()
            unit = r["unit"]
            if raw == "-0.5":
                val, unit = "不适用（哨兵值 -0.5）", ""
            else:
                val = raw
                try:
                    fv = float(raw)
                    ratio_field = any(k in r["field"] for k in ("加成", "减免", "抗性", "倍率", "转化比例", "惩罚"))
                    if "%" in unit and abs(fv) <= 1 and fv != 0 and ratio_field:
                        val = "%s（= %g%%）" % (raw, fv * 100)
                except ValueError:
                    pass
            print("    %-24s %s %s" % (r["field"], val, unit))
        print()
    if aa:
        hero = aa[0]["hero"]
        print("=== %s 技能数值 ===" % hero)
        cur = None
        for r in sorted(aa, key=lambda x: x["ability"]):
            if r["ability"] != cur:
                cur = r["ability"]
                print("  [%s]" % cur)
            print("    %-26s %s %s" % (r["field"], r["value"], r["unit"]))
        print()
    gp = os.path.join(DATA, "global-passives.tsv")
    if os.path.isfile(gp):
        import csv as _csv
        seen = []
        for r in _csv.DictReader(open(gp, encoding="utf-8"), delimiter="\t"):
            if r["value"].strip() and r["field"] not in seen:
                seen.append(r["field"])
                print("全局被动：%s %s%s（所有英雄）" % (r["field"], r["value"], r["unit"]))
        if seen:
            print()
    print("数据来源：客户端 STU 数据（health/cooldown/magazine 等）；伤害类字段覆盖不全，见 docs/hero-stats.md")
    return 0


SCAFFOLD_SETTINGS = [
    "设置", "{",
    "\t模式", "\t{", "\t\t死斗", "\t\t{",
    "\t\t\t启用地图", "\t\t\t{", "\t\t\t\t地图工坊室内 972777519512064577", "\t\t\t}",
    "\t\t\t随机英雄复生: 开启", "\t\t\t获胜得分: 20",
    "\t\t}", "\t}", "}",
]


def cmd_scaffold(a):
    """生成最小测试骨架：死斗 + 随机英雄复生 + 地图工坊室内 + 空规则。"""
    lines = list(SCAFFOLD_SETTINGS) + ["", "变量", "{", "\t全局:", "\t\t0: g", "}", ""]
    lines += ['规则("%s")' % a.rule, "{", "\t事件", "\t{", "\t\t持续 - 全局;", "\t}", "",
              "\t动作", "\t{",
              '\t\t记入查看器("[%s] 开始");' % a.rule,
              "\t}", "}", ""]
    text = "\r\n".join(lines) + "\r\n"
    if a.out:
        open(a.out, "w", encoding="utf-8", newline="").write(text)
        print("已写入 %s（%d 行）" % (a.out, text.count("\n")))
    else:
        print(text)
    return 0


def cmd_calib(a):
    """元素估算标定回归：全部实测样本必须精确命中。"""
    import csv as _csv
    import glob as _glob
    calib_dir = os.path.join(ROOT, "tools", "probes", "calib")
    files = {os.path.basename(p).split("_")[0]: p for p in _glob.glob(os.path.join(calib_dir, "*.ow"))}
    from element_count import estimate
    total = bad = 0
    for manifest in ("measurements.csv", "measurements-k.csv"):
        path = os.path.join(calib_dir, manifest)
        if not os.path.isfile(path):
            continue
        print("== %s ==" % manifest)
        for r in _csv.DictReader(open(path, encoding="utf-8-sig")):
            key = (r["probe"] or "").strip()
            if not key:
                continue
            f = files.get(key)
            if not f:
                print("  ? %s 找不到探针文件" % key)
                continue
            est = estimate(f)[0]
            real = int(r["元素数"])
            total += 1
            if est != real:
                bad += 1
                print("  ✗ %-4s 实测 %d 估算 %d（差 %+d）" % (key, real, est, est - real))
    print("\n标定样本 %d 个，偏差 %d 个" % (total, bad))
    return 0 if bad == 0 else 1


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
    p.add_argument("--all", action="store_true", help="（默认已是全量，此参数保留兼容）")
    p.add_argument("--safe", action="store_true", help="只写实测导入通过过的键")
    p.add_argument("--teams", action="store_true", help="英雄块用 队伍1/队伍2 形式（含队伍级键）")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_settings)

    p = sub.add_parser("modes", help="列出全部模式")
    p.set_defaults(func=cmd_modes)

    p = sub.add_parser("explain", help="按关键词查工坊报错文案")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("doc", help="查官方说明（元素/参数/下拉选项）")
    p.add_argument("name", nargs="?", default=None, help="元素名，如 创建HUD文本")
    p.add_argument("--search", default=None, help="按关键词搜索说明")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_doc)

    p = sub.add_parser("scaffold", help="生成最小测试骨架（死斗+随机复生+地图工坊室内）")
    p.add_argument("--rule", default="测试", help="规则名")
    p.add_argument("--out", default=None, help="输出文件，不给则打印")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("stats", help="查英雄/技能数值（生命值/冷却/弹匣）")
    p.add_argument("name", help="英雄名、技能名或字段名，如 半藏 / 岚 / 屏障生命值")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_stats)

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

    p = sub.add_parser("calib", help="元素估算标定回归（全部实测样本）")
    p.set_defaults(func=cmd_calib)

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
# 实测（2026-10-21，三次导入失败）：这两个键在死斗模式的 .ow 块里被拒，
# 报错「第N行的"开启"之后应有一个游戏模式设置」。数据里有、页面里也有，但 .ow 不收。
NOT_WRITABLE = {"威能充能速度", "追赶等级时造成消灭威能加值"}


def _load_verified():
    """实测导入过的键（data/verified-keys.tsv）；文件不存在时返回 None 表示不过滤。"""
    import csv
    path = os.path.join(DATA, "verified-keys.tsv")
    if not os.path.isfile(path):
        return None
    return {r["key"] for r in csv.DictReader(open(path, encoding="utf-8"), delimiter="\t")}


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
            default = None
            concrete = []
            for o in opts:
                if o.startswith("默认"):
                    default = o[2:].strip()
                else:
                    concrete.append(o)
            first = (concrete or ["0"])[0]
            if "~" in first:
                first = first.split("~")[0].strip()
            kind = (row.get("type") or "").upper()

            # FLOAT：.ow 里用百分比表示（1.0 → 100%，0.15 → 15%）
            def as_pct(x):
                try:
                    v = float(x)
                except ValueError:
                    return None
                pct = v * 100
                return ("%d%%" % round(pct)) if abs(pct - round(pct)) < 0.01 else ("%.1f%%" % pct)

            if kind == "FLOAT":
                shown = as_pct(default if default is not None else first) or first
            else:
                shown = VALUE_WORD_MAP.get(first, first)
            out[(row.get("schema", ""), row.get("key", ""))] = {
                "value": shown, "raw": raw, "kind": kind, "default": default}
    return out


def _load_pages(name):
    import csv
    path = os.path.join(DATA, name)
    rows = list(csv.DictReader(open(path, encoding="utf-8"), delimiter="\t"))
    return rows


def build_settings_block(mode, hero=None, lobby=False, allow_all=True, teams=False):
    """生成「设置」块。

    实测结论（2026-10-21，实机导入成功）：
    - 模式下面**只需要一个块**装完所有键；不要 综合 / 英雄 子块
    - 块归属自由：只要键属于该模式的 schema 并集即可
    - FLOAT 用百分比表示（1.0 → 100%）
    """
    pages = _load_pages("mode-pages.tsv")
    vals = _load_settings_values()
    rows = [r for r in pages if r["owner"] == mode]
    if not rows:
        known = sorted({r["owner"] for r in pages})
        raise SystemExit("没有这个模式：%s\n可用的有：%s" % (mode, "、".join(known[:20]) + (" …" if len(known) > 20 else "")))

    allow = None if allow_all else _load_verified()
    seen, body = set(), []
    for r in sorted(rows, key=lambda x: x["key"]):
        key = r["key"]
        if not key or key in seen:
            continue
        seen.add(key)
        if allow is not None and key not in allow:
            continue
        meta = vals.get((r["schema_guid"], key)) or vals.get((mode, key)) or vals.get((r["page"], key))
        if not meta:
            continue
        body.append("\t\t\t%s: %s" % (key, meta["value"]))
    if not body:
        raise SystemExit("模式 %s 没有可写的键" % mode)

    lines = ["设置", "{"]
    if lobby:
        lines += build_lobby_block(vals)
    lines += ["\t模式", "\t{", "\t\t%s" % mode, "\t\t{"]
    lines += body
    lines += ["\t\t}", "\t}"]
    if hero:
        hb = build_hero_block(hero, vals, teams=teams)
        if hb:
            lines += hb
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


def _load_hero_safe():
    import csv
    path = os.path.join(DATA, "hero-safe-keys.tsv")
    if not os.path.isfile(path):
        return None
    return {r["key"] for r in csv.DictReader(open(path, encoding="utf-8"), delimiter="\t")}


PERCENT_HINTS = ("冷却时间", "充能速度", "倍率", "持续时间", "最长时间", "生命值", "伤害量",
                  "治疗量", "移动速度", "重力", "弹道速度", "垂直跳跃", "复活时间", "复生时间")
BOOL_SUFFIX_EXCEPTIONS = ("无限", "充能完毕")


BOOL_OFF_DEFAULT = ("被动生命值恢复",)


def _guess_value(key):
    """按键名猜默认值：百分比类写 100%，布尔类写 开启（这两类实测都被接受）。"""
    if key in BOOL_OFF_DEFAULT:
        return "关闭"
    if key.endswith(BOOL_SUFFIX_EXCEPTIONS):
        return "开启"
    if any(h in key for h in PERCENT_HINTS):
        return "100%"
    return "开启"


def _load_visible_keys(hero):
    """data/hero-visible-keys.tsv：游戏页实际显示的键（截图/导出为证）。"""
    import csv
    off = os.path.join(DATA, "hero-official-keys.tsv")
    path = off if os.path.isfile(off) else os.path.join(DATA, "hero-visible-keys.tsv")
    if not os.path.isfile(path):
        return None
    rows = [r["key"] for r in csv.DictReader(open(path, encoding="utf-8"), delimiter="\t") if r["hero"] == hero]
    return rows or None


TEAM_LEVEL_KEYS = ("技能冷却时间",)


def build_hero_block(hero, vals, teams=False):
    """英雄级设置块。

    键名优先用「游戏页实际显示的键」(data/hero-visible-keys.tsv)；
    该英雄还没建立可见键集时返回 None —— 宁可不出，也不瞎拼。
    """
    keys = _load_visible_keys(hero)
    if not keys:
        import sys
        print("  跳过英雄 %s：还没有可见键集（data/hero-visible-keys.tsv）" % hero, file=sys.stderr)
        return None
    body = []
    for key in sorted(set(keys)):
        body.append("\t\t\t\t%s: %s" % (key, _guess_value(key)))
    if not teams:
        return (["\t英雄", "\t{", "\t\t综合", "\t\t{", "\t\t\t%s" % hero, "\t\t\t{"]
                + body + ["\t\t\t}", "\t\t}", "\t}"])
    out = ["\t英雄", "\t{"]
    for team in ("队伍1", "队伍2"):
        out += ["\t\t%s" % team, "\t\t{"]
        out += ["\t\t\t%s: 100%%" % k for k in TEAM_LEVEL_KEYS]
        out += ["\t\t\t%s" % hero, "\t\t\t{"] + ["\t" + b for b in body] + ["\t\t\t}"]
        out += ["\t\t}"]
    out += ["\t}"]
    return out


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

    def vt(v):
        try:
            return tuple(int(x) for x in str(v).lstrip("v").split("."))
        except ValueError:
            return (0,)

    if cur and latest and vt(latest) > vt(cur):      # 只有线上更新才提示
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
    text = build_settings_block(args.mode, hero=args.hero, lobby=args.lobby, allow_all=not args.safe, teams=args.teams)
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


