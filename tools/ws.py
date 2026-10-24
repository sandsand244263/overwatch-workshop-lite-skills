#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkshopLite 唯一入口。

  python tools/ws.py check  模式.ow [更多文件...]     校验
  python tools/ws.py count  模式.ow                   元素数估算
  python tools/ws.py 知道 创建HUD文本                查一个元素的六段事实（身份/参数/能出现在哪/取值/已知坑/出处）
  python tools/ws.py defaults 创建HUD文本              查参数默认值（省略时游戏用什么）
  python tools/ws.py publish 模式.ow --outdir out [--obf numbers,vars]
  python tools/ws.py readlog [--list|--raw|--expect c1=2]  读工坊日志（游戏自己落盘）
  python tools/ws.py gen --src 导出目录                 重新生成 data/
  python tools/ws.py diff --prev 旧导出 --cur 新导出     全量对照

数据永远从 data/ 读；docs/ 里是数据里没有的规则。
"""
import argparse
import csv
import os
import sys
import tempfile
import json
import re

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
DATA = os.path.join(ROOT, "data")
REPO = "sandsand244263/overwatch-workshop-lite-skills"
sys.path.insert(0, TOOLS)

import core  # noqa: E402
import local_paths  # noqa: E402


def load():
    sigs, labels, _opts = core.load_signatures(os.path.join(DATA, "signatures.md"))
    settings = core.load_settings_schema(os.path.join(DATA, "settings.tsv"))
    return sigs, labels, settings


def _ext():
    """扩展成本表 + 解锁选项表（缓存，避免每次 check 重读）。"""
    global _EXT_CACHE
    try:
        return _EXT_CACHE
    except NameError:
        pass
    _EXT_CACHE = core.load_extensions(os.path.join(DATA, "extensions.tsv"),
                                      os.path.join(DATA, "extension-values.tsv"))
    return _EXT_CACHE


def _base_options():
    global _OPT_CACHE
    try:
        return _OPT_CACHE
    except NameError:
        pass
    _OPT_CACHE = set()
    p = os.path.join(DATA, "dropdown-options.tsv")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            next(f, None)
            for line in f:
                c = line.rstrip("\n").split("\t")
                if len(c) > 1:
                    _OPT_CACHE.add(c[1].strip())
    return _OPT_CACHE


LAST_CHECK = {}   # cmd_check 最近一次统计，供 check-all 打正样本汇总


def cmd_check(args):
    """校验。默认输出分两段：必改（会挡导入）/ 提示（多数可忽略）。

    --json 时只输出结构化结果，供编辑器与 CI 使用。
    """
    global LAST_CHECK
    sigs, labels, settings = load()
    failed = 0
    seen = 0
    report = []
    for path in args.files:
        seen += 1
        name = os.path.basename(path)
        if not os.path.isfile(path):
            if getattr(args, "json", False):
                report.append({"file": path, "error": "找不到文件"})
            else:
                print("[错误] 找不到 %s" % path)
            failed += 1
            continue
        problems = core.full_lint(path, DATA, strict=getattr(args, "strict", False))
        errors = [p for p in problems if p[1] == "error"]
        warns = [p for p in problems if p[1] != "error"]
        if errors:
            failed += 1

        if getattr(args, "json", False):
            report.append({
                "file": path,
                "ok": not errors,
                "errors": [{"line": p[0], "level": p[1], "message": p[2],
                            "fix": core.suggest(p[2])} for p in errors],
                "warnings": [{"line": p[0], "level": p[1], "message": p[2],
                              "fix": core.suggest(p[2])} for p in warns],
            })
            continue

        if errors:
            print("✗ %s：%d 个问题会导致导入失败（另有 %d 条提示，可以先不管）"
                  % (name, len(errors), len(warns)))
            print("\n  ── 必改 ──")
            for ln, level, msg in errors:
                print("  第 %s 行：%s" % (ln if ln else "?", msg))
                tip = core.suggest(msg)
                if tip:
                    print("      → %s" % tip)
            if warns:
                print("\n  ── 提示（多半不用改） ──")
                for ln, level, msg in warns[:args.max_warn]:
                    print("  第 %s 行：%s" % (ln if ln else "?", msg))
                if len(warns) > args.max_warn:
                    print("  …还有 %d 条，用 --max-warn 调大或 --json 看全部" % (len(warns) - args.max_warn))
        else:
            print("✓ %s：可以导入%s"
                  % (name, "" if not warns else "（%d 条提示，不影响导入）" % len(warns)))
            for ln, level, msg in warns[:args.max_warn]:
                print("  第 %s 行：%s" % (ln if ln else "?", msg))
                tip = core.suggest(msg)
                if tip:
                    print("      → %s" % tip)
            if len(warns) > args.max_warn:
                print("  …还有 %d 条提示" % (len(warns) - args.max_warn))
        _print_update_hint()

    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    LAST_CHECK = {"total": seen, "failed": failed}
    return 1 if failed else 0


def cmd_check_all(args):
    import glob
    files = sorted(glob.glob(os.path.join(ROOT, "tools", "probes", "*.ow"))) + \
            sorted(glob.glob(os.path.join(ROOT, "tools", "probes", "calib", "*.ow"))) + \
            sorted(glob.glob(os.path.join(ROOT, "tools", "probes", "samples", "*.ow")))
    rc = cmd_check(type("A", (), {"files": files, "max_warn": 20, "json": False})())
    # 正样本汇总必须打出来：以前只有每个文件的 ✓/✗ 和最后的反向用例统计，
    # 正样本失败时结论行看不出问题（2026-10-23 golden.ow 就因此漏过一次）
    st = LAST_CHECK or {}
    print("\n正样本 %d 个：%d 通过 / %d 失败"
          % (st.get("total", 0), st.get("total", 0) - st.get("failed", 0), st.get("failed", 0)))
    if st.get("failed"):
        rc = 1

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
                             setting_ranges=core.load_setting_ranges(os.path.join(DATA, "setting-ranges.tsv")),
                             map_names=core.load_map_names(os.path.join(DATA, "maps.tsv")),
                             dropdowns=core.load_dropdowns(os.path.join(DATA, "param-options.tsv")),
                             strict=getattr(args, "strict", False),
                             extensions=_ext()[0], extension_values=_ext()[1],
                             base_options=_base_options())
            # 反向用例只关心「能不能发现」，error 或 warning 都算
            errs = [p[2] for p in probs]
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


# 用 235 KB 真实模式反推：实测 16918 / 估 7668
REAL_WORLD_FACTOR = 2.12

def cmd_map_code(args):
    """查地图的工坊编号（写进 .ow 用）：等于 0xD8<<52 | 变体编号。"""
    rows = []
    for fn in ("map-codes.tsv", "map-codes-derived.tsv"):
        fp = os.path.join(DATA, fn)
        if os.path.isfile(fp):
            with open(fp, encoding="utf-8-sig") as f:
                rows += [x for x in csv.DictReader(f, delimiter="\t")]
    kw = (args.name or "").strip()
    hit = [x for x in rows if kw in x["name"]] if kw else rows
    if not hit:
        print("map-codes.tsv 里没有包含「%s」的地图（目前只收了真实文件里出现过的）" % kw); return 1
    seen = set()
    for x in hit:
        if x["name"] in seen: continue
        seen.add(x["name"])
        print("%-22s %s" % (x["name"], x["code"]))
    return 0


def cmd_count(args):
    """元素数估算：探针级给精确值，真实规模给区间。

    实测依据（43 个标定探针 + 私有仓 corpus/real-totals.tsv 的 5 个真实模式）：
      · 探针级（<2000 元素）：模型偏差 ≤6 个元素，可以直接用
      · 真实模式（6千~3.3万）：模型仍**偏低**，实测倍率 1.006 ~ 1.216
        （−0.6% / −5.3% / −10.8% / −17.8% / −2.8%；S2b 修掉 4 类「整条语句被吞」后
        合计 −9.2% → −5.3%，3/5 进 ±5%，两个离群文件归因不到具体构造）
    所以区间只向上给（×1.00 ~ ×1.23，下界＝实测最低倍率、上界＝实测最高 + 1% 余量），判上限按上界判。
    """
    from element_count2 import estimate2
    from element_count import estimate, describe
    CAP, SMALL = 32768, 2000
    RATIO_LO, RATIO_HI = 1.00, 1.23
    for path in args.files:
        name = os.path.basename(path)
        if getattr(args, "legacy", False):
            est, detail = estimate(path, load()[0], load()[1])
            print("%s：预计 %d 个元素（%s）" % (name, est, describe(detail)))
            continue
        est = estimate2(path)
        if est < SMALL:
            print("%s：约 %d 个元素（探针级规模，实测偏差 ≤6 个）" % (name, est))
            print("  离 32768 还很远，估算误差不影响。")
            continue
        lo, hi = int(est * RATIO_LO), int(est * RATIO_HI) + 1
        print("%s：模型估 %d，真实值多半在 %d ~ %d" % (name, est, lo, hi))
        print("  （真实模式模型一律偏低，上界按最坏情况算；最终数字以游戏「显示诊断结果 → 总计元素数量」为准）")
        if lo > CAP:
            print("  ✗ 必定超上限：按最低增幅也算到 %d，已过 32768，先压元素（见 docs/cost-patterns.md）" % lo)
        elif hi > CAP:
            print("  ⚠ 可能超上限：最坏情况 %d（超 %d），真实值只要落在 32768 以上就导不进去，别赌"
                  % (hi, hi - CAP))
        else:
            print("  上限 32768，按最坏情况还余 %d 个。" % (CAP - hi))
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
    "\t\t\t获胜得分: 20",
    "\t\t}",
    # 综合 层：即时开赛 + 随机英雄复生，省掉「英雄集结」那一屏手动确认
    "\t\t综合", "\t\t{", "\t\t\t游戏模式开始: 即时", "\t\t\t随机英雄复生: 开启", "\t\t}",
    "\t}", "}",
]


def cmd_scaffold(a):
    """生成最小测试骨架。

    默认死斗 + 地图工坊室内；其它模式默认**不写地图**——工坊室内是空房、没有目标点，
    需要目标的模式（占领要点/机动推进/攻防阵线）用它会被游戏判为「无效的地图设置」。
    需要指定时用 --map。
    """
    mode = getattr(a, "mode", "死斗") or "死斗"
    want_map = getattr(a, "map", None)
    if mode == "死斗" and not want_map:
        want_map = "地图工坊室内 972777519512064577"
    if mode == "死斗" and want_map == "地图工坊室内 972777519512064577":
        lines = list(SCAFFOLD_SETTINGS)
    else:
        block = build_settings_block(mode, hero=None, lobby=False, allow_all=False)
        lines = block.replace("\r\n", "\n").rstrip("\n").split("\n")
        if want_map:
            for i, ln in enumerate(lines):
                if ln.strip() == mode:
                    j = i + 1
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1
                    at = (j + 1) if (j < len(lines) and lines[j].strip() == "{") else (i + 1)
                    lines[at:at] = ["\t\t\t启用地图", "\t\t\t{",
                                    "\t\t\t\t" + want_map, "\t\t\t}"]
                    break

    lines += ["", '规则("%s")' % a.rule, "{", "\t事件", "\t{",
              "\t\t持续 - 每名玩家;", "\t\t双方;", "\t\t全部;", "\t}", "",
              "\t动作", "\t{",
              "\t\t隐藏英雄HUD(事件玩家);",
              "\t\t隐藏游戏模式HUD(事件玩家);",
              "\t\t开始镜头(事件玩家, 矢量(0, 50, 0), 矢量(0, 200, 0), 100);   // 工位隐蔽：镜头移到空白处，画面里没有角色",
              '\t\t记入查看器(自定义字符串("[%s] 开始"));' % a.rule,
              "\t}", "}", ""]
    text = "\r\n".join(lines) + "\r\n"
    if a.out:
        open(a.out, "w", encoding="utf-8", newline="").write(text)
        print("已写入 %s（%d 行，模式 %s，地图 %s）"
              % (a.out, text.count("\n"), mode, want_map or "未指定"))
    else:
        print(text)
    return 0



def cmd_selftest(args):
    """工具自身的体检：同名函数重复定义会让旧版本静默生效（已踩过一次）。

    同时检查版本号一致性：SKILL.md / VERSION / marketplace.json 三处不一致，
    会让自更新判断错乱（升不上去或反复提示）。
    """
    import ast, collections, glob, os
    here = os.path.dirname(os.path.abspath(__file__))
    bad = 0
    for f in sorted(glob.glob(os.path.join(here, "*.py"))):
        src = open(f, encoding="utf-8").read()
        try:
            tree = ast.parse(src)
        except SyntaxError as e:
            print("✗ %s 语法错误：%s" % (os.path.basename(f), e))
            bad += 1
            continue
        names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        dup = {k: v for k, v in collections.Counter(names).items() if v > 1}
        if dup:
            print("✗ %s 重复定义（后定义的会静默生效）：%s" % (os.path.basename(f), dup))
            bad += 1
    # 判定表 ⇄ 表驱动检查 的漂移：表说已接但没实现，或实现了但表里没写（等于静默关闭）
    try:
        import rules as _rules
        names = set()
        for r in _rules.load():
            for tok in (r.get("检查", "") or "").split(","):
                tok = tok.strip()
                if tok in ("", "不接", "已接(内建)"):
                    continue
                names.add(tok[3:] if tok.startswith("停用:") else tok)
        reg = set(core.RULE_CHECKS)
        ghost = names - reg
        silent = reg - names
        if ghost:
            print("✗ 判定表写了检查名但代码里没有：%s" % ", ".join(sorted(ghost)))
            bad += 1
        if silent:
            print("✗ 代码里有检查但判定表没写（等于静默关闭）：%s" % ", ".join(sorted(silent)))
            bad += 1
    except Exception as e:
        print("✗ 判定表读不到，表驱动检查的开关无法核对：%s" % e)
        bad += 1
    # 「知道」六段回归：每类型 10 个固定名字（写死，不随机），六段全在 + 退出码 0
    try:
        import know as _know
        problems, summary = _know.selftest_check()
        if problems:
            print("✗ %s" % summary)
            for p in problems:
                print("    %s" % p)
            bad += 1
        else:
            print(summary)
    except Exception as e:
        print("✗ 「知道」六段回归跑不起来：%s: %s" % (type(e).__name__, e))
        bad += 1
    # 报错定位回归：真实报错原文 → 模板 → 行号（PLAN v5 A1 的判据）
    try:
        import locate_selftest as _loc
        lt_problems, lt_summary = _loc.selftest_check()
        if lt_problems:
            print("✗ %s" % lt_summary)
            for p in lt_problems:
                print("    %s" % p)
            bad += 1
        else:
            print(lt_summary)
    except Exception as e:
        print("✗ 报错定位回归跑不起来：%s: %s" % (type(e).__name__, e))
        bad += 1
    # 版本号三处一致性
    ver_file = ""
    vp = os.path.join(ROOT, "VERSION")
    if os.path.isfile(vp):
        ver_file = open(vp, encoding="utf-8").read().strip()
    ver_skill = _skill_version() or ""
    ver_mk = ""
    mp = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
    if os.path.isfile(mp):
        try:
            ver_mk = (json.load(open(mp, encoding="utf-8")) or {}).get("version", "")
        except (OSError, ValueError):
            ver_mk = "读取失败"
    versions = {"VERSION": ver_file, "SKILL.md": ver_skill, "marketplace.json": ver_mk}
    uniq = {v for v in versions.values() if v}
    if len(uniq) > 1:
        print("✗ 版本号不一致：%s" % versions)
        bad += 1
    else:
        print("版本号一致：v%s" % (ver_file or "?"))

    print("工具自检：%s" % ("通过" if bad == 0 else "%d 个文件有问题" % bad))
    return 0 if bad == 0 else 1





def cmd_fuzz(args):
    import subprocess as sp
    cmd = [sys.executable, os.path.join(ROOT, "tools", "fuzz_check.py")]
    if args.file:
        cmd.append(args.file)
    if args.corpus:
        cmd.append("--corpus")
    cmd += ["--rounds", str(args.rounds)]
    if args.verbose:
        cmd.append("-v")
    return sp.call(cmd)

def cmd_corpus(args):
    """转调 tools/corpus_check.py。"""
    import subprocess as sp
    cmd = [sys.executable, os.path.join(ROOT, "tools", "corpus_check.py")]
    if getattr(args, "dir", None):
        cmd.append(args.dir)
    if getattr(args, "update", False):
        cmd.append("--update")
    return sp.call(cmd)


def cmd_readlog(args):
    """转调 tools/logread.py：读游戏自动落盘的工坊查看器日志。"""
    import logread
    return logread.run(args)


def cmd_probe_template(args):
    """转调 tools/gen_probe.py：生成探针骨架 .ow + 配套 expect.tsv。"""
    import gen_probe
    return gen_probe.main_with_args(args)



def _mask_strings(line):
    """脱敏：把长字符串内容换成 …，保留键名和结构。"""
    def rep(m):
        body = m.group(1)
        return '"%s"' % ("…" if len(body) > 8 else body)
    return re.sub(r'"([^"\\]*(?:\\.[^"\\]*)*)"', rep, line)


def cmd_report(args):
    """生成误报/漏报的最小复现片段，方便贴到 issue。"""
    if not os.path.isfile(args.src):
        print("[错误] 找不到 %s" % args.src)
        return 1
    text, enc = core.read_text(args.src)
    problems = core.full_lint(args.src, DATA, strict=getattr(args, "strict", False))
    if not problems:
        print("没发现问题，不需要上报。")
        return 0
    errs = [p for p in problems if p[1] == "error"]
    ln, level, msg = (errs or problems)[0][:3]

    all_lines = text.replace("\r\n", "\n").split("\n")
    total = len(all_lines)

    # 优先取问题所在的规则/子程序块；不在块里就取问题行附近
    head = None
    for i in range(ln - 1, -1, -1):
        if re.match(r"^\s*(规则\(|子程序)", all_lines[i]):
            head = i
            break
    if head is not None:
        depth, tail = 0, head
        for i in range(head, total):
            depth += all_lines[i].count("{") - all_lines[i].count("}")
            if depth <= 0 and i > head:
                tail = i
                break
        tail = min(tail, head + args.max_lines)
        lo, hi = head, tail
    else:
        lo = max(0, ln - 1 - 12)
        hi = min(total - 1, ln - 1 + 8)
    snippet = "\n".join(_mask_strings(x) for x in all_lines[lo:hi + 1])

    import platform
    meta = {}
    try:
        meta = json.load(open(os.path.join(DATA, "meta.json"), encoding="utf-8"))
    except Exception:
        pass
    ver = "?"
    try:
        ver = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip() or "?"
    except Exception:
        pass
    for cand in ("CHANGELOG.md", "SKILL.md", "README.md", os.path.join("..", "README.md")):
        p = os.path.join(ROOT, cand)
        if not os.path.isfile(p):
            continue
        try:
            m = re.search(r"(v\d+\.\d+\.\d+)", open(p, encoding="utf-8").read()[:2000])
            if m:
                ver = m.group(1)
                break
        except Exception:
            continue

    out = []
    out.append("## 环境")
    out.append("- WorkshopLite %s，数据基线 %s" % (ver, meta.get("build", "未知")))
    out.append("- %s / Python %s" % (platform.platform(), platform.python_version()))
    out.append("- 文件编码 %s，%d 行，%d KB" % (enc, total, os.path.getsize(args.src) // 1024))
    out.append("")
    out.append("## 我认为有问题的地方")
    out.append("第 %d 行（%s）：%s" % (ln, level, msg))
    tip = core.suggest(msg)
    if tip:
        out.append("校验器给的改法：%s" % tip)
    out.append("")
    out.append("## 最小片段（字符串内容已脱敏；⚠ 是问题行）")
    out.append("```ow")
    for i in range(lo, hi + 1):
        mark = "⚠ " if i == ln - 1 else "  "
        out.append(mark + _mask_strings(all_lines[i]))
    out.append("```")
    out.append("")
    out.append("## 我的判断")
    out.append(args.note or "（导入时报什么错 / 为什么觉得这是误报）")
    body = "\n".join(out)

    path = args.out or (os.path.splitext(args.src)[0] + ".report.txt")
    open(path, "w", encoding="utf-8", newline="\n").write(body)
    print(body)
    print("\n已保存：%s（可直接贴到 issue）" % path)
    return 0


def cmd_doctor(args):
    """环境自检：出问题时先分清是「环境问题」还是「文件问题」。"""
    import platform
    ok, bad = [], []

    def line(state, text):
        print("%s %s" % ("✔" if state else "✗", text))
        (ok if state else bad).append(text)

    print("WorkshopLite 环境自检\n")
    v = sys.version_info
    line(v >= (3, 8), "Python %d.%d.%d（需要 3.8 以上）" % (v[0], v[1], v[2]))
    line(sys.maxsize > 2**32, "64 位 Python（32 位也能用，但大文件慢）")

    need = ["signatures.md", "settings.tsv", "maps.tsv", "heroes.tsv", "setting-keys.tsv",
            "param-options.tsv", "setting-schemas.tsv", "event-params.tsv",
            "setting-values.tsv", "setting-aliases.tsv"]
    missing = [f for f in need if not os.path.isfile(os.path.join(DATA, f))]
    n_data = len([f for f in os.listdir(DATA) if f.endswith((".tsv", ".md", ".json"))]) if os.path.isdir(DATA) else 0
    line(not missing, "数据表 %d 个%s" % (n_data, "" if not missing else "，缺：" + "、".join(missing)))

    meta = {}
    try:
        meta = json.load(open(os.path.join(DATA, "meta.json"), encoding="utf-8"))
    except Exception as e:
        print("   （读 meta.json 失败：%s）" % e)
    line(bool(meta.get("build")), "数据基线：%s（导出于 %s）" % (meta.get("build", "未知"), meta.get("exported", "未知")))

    probe = os.path.join(tempfile.gettempdir(), "ws_doctor_probe.txt")
    try:
        open(probe, "w", encoding="utf-8").write("ok")
        os.remove(probe)
        line(True, "临时目录可写")
    except OSError as e:
        line(False, "临时目录不可写：%s" % e)

    try:
        import locale
        enc = locale.getpreferredencoding(False)
        line(True, "系统默认编码 %s（文件读取会自动识别 UTF-8 / GBK）" % enc)
    except Exception:
        pass

    corpus = local_paths.corpus_dir()
    n_corpus = len([f for f in os.listdir(corpus) if f.endswith((".ow", ".txt"))]) if corpus and os.path.isdir(corpus) else 0
    if n_corpus:
        line(True, "真实语料 %d 个（维护者用）" % n_corpus)

    print("\n结论：%s" % ("环境正常，可以直接用" if not bad else "有 %d 项异常，先解决再校验文件" % len(bad)))
    return 0 if not bad else 1



def cmd_fix(args):
    """检查 + 自动修：修出能导入的版本，再复校一遍。"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import normalize as nz
    text, _enc = core.read_text(args.src)
    before = core.full_lint(args.src, DATA)
    b_err = sum(1 for p in before if p[1] == "error")
    b_warn = len(before) - b_err

    new_text, merged, none_fixed, bool_fixed = nz.normalize_text(
        text, fix_bools=args.fix_bools, drop_empty=not args.keep_empty)

    out = args.out or (os.path.splitext(args.src)[0] + ".fixed.ow")
    open(out, "w", encoding="utf-8", newline="\n").write(new_text)

    after = core.full_lint(out, DATA)
    a_err = sum(1 for p in after if p[1] == "error")
    a_warn = len(after) - a_err

    print("修复：合并折行 %d 处，「无」→「全部禁用」%d 处，删空值行%s，布尔词%s"
          % (merged, none_fixed,
             "已删" if not args.keep_empty else "未动",
             ("%d 处" % bool_fixed) if args.fix_bools else "未动"))
    print("校验：error %d → %d，warning %d → %d" % (b_err, a_err, b_warn, a_warn))
    print("输出：%s" % out)
    left = [p for p in after if p[1] == "error"]
    if left:
        print("\n还剩 %d 个 error（无法自动修）：" % len(left))
        for ln, lv, msg in left[:10]:
            print("   第 %s 行：%s" % (ln, msg))
        tip = core.suggest(left[0][2])
        if tip:
            print("   第一条的改法：%s" % tip)
    return 0 if a_err == 0 else 1

def cmd_normalize(args):
    """把导出的 .ow 修成编辑器能接受的形式（去掉导出失真）。"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import normalize as nz
    text, _enc = core.read_text(args.src)
    new_text, merged, none_fixed, bool_fixed = nz.normalize_text(
        text, fix_bools=getattr(args, "fix_bools", False),
        drop_empty=getattr(args, "drop_empty", False))
    open(args.out, "w", encoding="utf-8", newline="\n").write(new_text)
    print("输入 %d 行 -> 输出 %d 行（合并折行 %d，改「无」%d，改布尔词 %d）"
          % (len(text.split("\n")), len(new_text.split("\n")), merged, none_fixed, bool_fixed))
    probs = core.full_lint(args.out, DATA)
    errs = [p for p in probs if p[1] == "error"]
    print("修复后校验：%d error / %d warning" % (len(errs), len(probs) - len(errs)))
    return 0


def cmd_totals(args):
    """对比「模型估算」与「游戏实测元素数」，用来定位系统性偏差。"""
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    from element_count2 import estimate2
    import csv as _csv
    path = args.table or local_paths.real_totals()
    if not path:
        print("没有实测表：%s" % local_paths.hint())
        return 2
    base = os.path.dirname(path)
    if not os.path.isfile(path):
        print("没有实测表：%s" % path)
        return 2
    rows = list(_csv.DictReader(open(path, encoding="utf-8-sig"), delimiter="\t"))
    print("%-26s %8s %8s %8s %8s" % ("文件", "实测", "估算", "偏差", "真实/估算"))
    tot_r = tot_e = 0
    ratios = []
    for r in rows:
        name = (r.get("file") or "").strip()
        if not name:
            continue
        try:
            real = int((r.get("实测元素数") or "0").strip())
        except ValueError:
            continue
        f = os.path.join(base, name)
        if not os.path.isfile(f):
            f = os.path.join(base, "real", name)
        if not os.path.isfile(f):
            print("%-26s %8d   找不到文件" % (name, real))
            continue
        est = estimate2(f)
        tot_r += real
        tot_e += est
        ratio = real / float(est) if est else 0
        ratios.append(ratio)
        print("%-26s %8d %8d %+8d (%+.1f%%) %8.3f"
              % (name, real, est, est - real, (est - real) * 100.0 / real, ratio))
    if tot_r:
        print("%-26s %8d %8d %+8d (%+.1f%%) %8.3f"
              % ("合计", tot_r, tot_e, tot_e - tot_r, (tot_e - tot_r) * 100.0 / tot_r,
                 tot_r / float(tot_e) if tot_e else 0))
    if ratios:
        # 判定用区间（count 的区间就来自这里：下界＝实测最低倍率，上界＝实测最高 + 1% 余量）
        print("实测「真实/估算」倍率 %.3f ~ %.3f → count 按 ×%.3f ~ ×%.3f 给区间"
              % (min(ratios), max(ratios), min(ratios), max(ratios) * 1.01))
    return 0

def cmd_calib(a):
    """元素估算标定回归：全部实测样本必须精确命中。"""
    import csv as _csv
    import glob as _glob
    calib_dir = os.path.join(ROOT, "tools", "probes", "calib")
    files = {}
    for p in _glob.glob(os.path.join(calib_dir, "*.ow")):
        stem = os.path.splitext(os.path.basename(p))[0]
        files[stem.split("_")[0]] = p
        files[stem] = p          # P1.ow 这种没有下划线的也要能查到
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
    # 新模型专用标定（P 系列）：必须精确命中
    v2 = os.path.join(calib_dir, "measurements-v2.csv")
    if os.path.isfile(v2):
        from element_count2 import estimate2
        print("== measurements-v2.csv ==")
        for r in _csv.DictReader(open(v2, encoding="utf-8-sig")):
            key = (r["probe"] or "").strip()
            f = files.get(key)
            if not f:
                print("  ? %s 找不到探针文件" % key)
                continue
            est = estimate2(f)
            real = int(r["元素数"])
            total += 1
            if est != real:
                bad += 1
                print("  ✗ %-4s 实测 %d 估算 %d（差 %+d）" % (key, real, est, est - real))

    # 新模型（element_count2）同批对照：小样本允许 ±6，大文件另见 docs/limits.md
    try:
        from element_count2 import estimate2
        _ok = _n = 0; _max = 0
        for manifest in ("measurements.csv", "measurements-k.csv"):
            path = os.path.join(calib_dir, manifest)
            if not os.path.isfile(path):
                continue
            for r in _csv.DictReader(open(path, encoding="utf-8-sig")):
                key = (r["probe"] or "").strip()
                f = files.get(key)
                if not f:
                    continue
                _n += 1
                d = estimate2(f) - int(r["元素数"])
                _max = max(_max, abs(d))
                _ok += (d == 0)
        print("元素计数新模型（实测推导版）：%d/%d 精确，最大偏差 %d" % (_ok, _n, _max))
    except Exception as e:
        print("新模型对照跳过：%s" % e)
    print("\n标定样本 %d 个，偏差 %d 个" % (total, bad))
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(prog="ws", description="WorkshopLite 工具入口")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="校验 .ow")
    p.add_argument("--strict", action="store_true", help="额外跑数据未验证的检查，会有误报")
    p.add_argument("--json", action="store_true", help="输出结构化结果（给编辑器/CI）")
    p.add_argument("--max-warn", type=int, default=5, help="最多显示几条提示（默认 5）")
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

    p = sub.add_parser("locate", help="游戏报错原文 → 模板 → 第几行 → 改法（报错闭环）")
    p.add_argument("error", help="游戏给的报错原文，整条粘进来")
    p.add_argument("--file", default=None, help="当时导入的 .ow 文件（给了才能指行）")
    p.add_argument("--context", type=int, default=2, help="报错行上下各显示几行")
    p.add_argument("--to-case", default=None, metavar="DIR",
                   help="把报错那一处抽成可单独导入的最小用例，写到 DIR（失败即回填）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_locate)

    p = sub.add_parser("知道", help="一条命令回答一个元素/设置键的全部已知事实（六段）")
    p.add_argument("name", nargs="?", default=None,
                   help="动作/值/事件/设置键/设置块名；可带参数（伤害(玩家, 玩家, 5)）")
    p.add_argument("--brief", action="store_true", help="只给身份 + 已知坑")
    p.add_argument("--json", action="store_true", help="机器读（六段结构）")
    p.add_argument("--audit", action="store_true", help="全量自查：0 崩溃 / 0 缺段 + 未答元素清单")
    p.add_argument("--as", dest="as_type", default=None,
                   help="同名时指定类型：动作/值/事件/扩展/设置键/设置块（如 生命值 既是值也是设置键）")
    p.add_argument("--out", default="", help="--audit 的清单输出路径")
    p.set_defaults(func=lambda a: __import__("know").run(a))

    p = sub.add_parser("doc", help="查官方说明（元素/参数/下拉选项）")
    p.add_argument("name", nargs="?", default=None, help="元素名，如 创建HUD文本")
    p.add_argument("--search", default=None, help="按关键词搜索说明")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_doc)

    p = sub.add_parser("scaffold", help="生成最小测试骨架（默认死斗，可用 --mode 换模式）")
    p.add_argument("--mode", default="死斗", help="模式名，见 ws.py modes")
    p.add_argument("--map", default=None, help="地图名 编号，例如「地图工坊室内 972777519512064577」；编号用 ws.py map-code 查；不给则死斗用工坊室内、其它模式不写地图")
    p.add_argument("--rule", default="测试", help="规则名")
    p.add_argument("--out", default=None, help="输出文件，不给则打印")
    p.set_defaults(func=cmd_scaffold)

    p = sub.add_parser("stats", help="查英雄/技能数值（生命值/冷却/弹匣）")
    p.add_argument("name", help="英雄名、技能名或字段名，如 半藏 / 岚 / 屏障生命值")
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("keyinfo", help="查一个设置键的全貌（页/类型/schema/模式/合法值/层限制）")
    p.add_argument("key")
    p.add_argument("--limit", type=int, default=12, help="模式列表最多显示几个")
    p.set_defaults(func=cmd_keyinfo)

    p = sub.add_parser("hero", help="列某英雄的设置页与可写键")
    p.add_argument("name")
    p.add_argument("--limit", type=int, default=15)
    p.set_defaults(func=cmd_hero)

    p = sub.add_parser("reveal", help="在文件管理器里选中某个文件（交付测试文件用）")
    p.add_argument("file")
    p.set_defaults(func=cmd_reveal)
    p = sub.add_parser("upgrade", help="从 GitHub 拉最新版本覆盖本技能（旧版自动备份）")
    p.add_argument("--check", action="store_true", help="只报告能不能升级，不动文件")
    p.add_argument("--force", action="store_true", help="版本相同也强制重装")
    p.add_argument("--tag", default="", help="指定 tag，如 v3.10.13")
    p.set_defaults(func=cmd_upgrade)
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

    p = sub.add_parser("report", help="生成误报/漏报的最小复现片段（脱敏）")
    p.add_argument("src")
    p.add_argument("-o", "--out")
    p.add_argument("--note", help="我为什么觉得这是误报")
    p.add_argument("--max-lines", type=int, default=40)
    p.add_argument("--strict", action="store_true")
    p.set_defaults(func=cmd_report)

    sub.add_parser("doctor", help="环境自检").set_defaults(func=cmd_doctor)

    p = sub.add_parser("fuzz", help="漏报率测试：随机改坏文件看能不能抓到")
    p.add_argument("file", nargs="?")
    p.add_argument("--corpus", action="store_true")
    p.add_argument("--rounds", type=int, default=10)
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_fuzz)

    p = sub.add_parser("corpus", help="跑真实模式语料回归（语料在私有仓）")
    p.add_argument("dir", nargs="?")
    p.add_argument("--update", action="store_true")
    p.set_defaults(func=cmd_corpus)

    p = sub.add_parser("fix", help="检查 + 自动修出可导入版本，再复校")
    p.add_argument("src")
    p.add_argument("-o", "--out")
    p.add_argument("--fix-bools", action="store_true", help="布尔项的 禁用/启用 改成 关闭/开启")
    p.add_argument("--keep-empty", action="store_true", help="保留「键:」后面没值的行（默认删掉）")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("normalize", help="修复导出失真：合并折行、把「无」改成「全部禁用」")
    p.add_argument("src")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--drop-empty", action="store_true", help="删掉「键:」后面没值的行（导出会把值吞掉）")
    p.add_argument("--fix-bools", action="store_true", help="把布尔项的 禁用/启用 改成 关闭/开启（实测对部分模式必要）")
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("selftest", help="工具自身体检（重复定义等）")
    p.set_defaults(func=cmd_selftest)
    p = sub.add_parser("totals", help="对比模型估算与游戏实测元素数（读私有实测表）")
    p.add_argument("--table")
    p.set_defaults(func=cmd_totals)

    p = sub.add_parser("calib", help="元素估算标定回归（全部实测样本）")
    p.set_defaults(func=cmd_calib)

    p = sub.add_parser("map-code", help="查地图的工坊编号（写进 .ow 用）")
    p.add_argument("name", nargs="?", default=None, help="地图名，支持部分匹配；不给则列全部")
    p.set_defaults(func=cmd_map_code)

    p = sub.add_parser("count", help="元素数估算")
    p.add_argument("--legacy", action="store_true", help="用旧的经验模型（小样本 37/37，大文件偏低一半）")
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

    p = sub.add_parser("readlog", help="读工坊查看器日志（游戏自动落盘，不用用户复制）")
    p.add_argument("--dir", help="日志目录，默认 %%USERPROFILE%%\\Documents\\Overwatch\\Workshop")
    p.add_argument("--file", help="指定日志文件（不给就取最新的那个）")
    p.add_argument("--list", action="store_true", help="列出最近 10 个日志文件")
    p.add_argument("--raw", action="store_true", help="全部记录原样打印")
    p.add_argument("--expect", help="对期望值，例如 c1=2,c2=2,c3=1")
    p.add_argument("--expect-file", dest="expect_file",
                   help="期望表 .tsv（格号/结构说明/期望/容差/依据/备注），出「预期|实际|结论」差异表")
    p.add_argument("-v", "--verbose", action="store_true", help="差异表逐格明细连通过的也列")
    p.set_defaults(func=cmd_readlog)

    p = sub.add_parser("probe-template", help="生成探针骨架 .ow + 配套 expect.tsv（一格一计数器 + 对照组）")
    p.add_argument("--cells", type=int, default=8, help="格数（1-20，默认 8）")
    p.add_argument("--structures", default="", help="显式指定结构，逗号分隔（如 无条件,If真,If假）")
    p.add_argument("--seconds", type=int, default=12, help="跑多少秒（默认 12）")
    p.add_argument("--name", default="探针", help="模式名称")
    p.add_argument("--out", default="probe.ow", help="输出的 .ow")
    p.add_argument("--expect-out", dest="expect_out", default="", help="输出的 expect.tsv（默认同名）")
    p.set_defaults(func=cmd_probe_template)

    p = sub.add_parser("rule", help="查判定表：实测结论怎么用（docs/rules.tsv）")
    p.add_argument("query", nargs="*", help="关键词，空格分隔多个词")
    p.add_argument("--list", action="store_true", help="列出全部场景")
    p.set_defaults(func=lambda a: __import__("rules").run(a))

    p = sub.add_parser("verify", help="断言表验证闭环：列待验 / 回填等级 / 生成验证探针")
    p.add_argument("query", nargs="*", help="关键词（不给就列出还没验的）")
    p.add_argument("--set", help="回填哪一条（场景关键词）")
    p.add_argument("--level", help="回填的证据等级：L1/L2/L3")
    p.add_argument("--evidence", help="依据编号，例如 E-54")
    p.add_argument("--date", help="验证日期，默认今天")
    p.add_argument("--stale", type=int, help="列出超过 N 天没复核的已验条目")
    p.add_argument("--scaffold", type=int, help="生成 N 格验证探针骨架")
    p.add_argument("--out", help="--scaffold 的输出文件")
    p.set_defaults(func=lambda a: __import__("facts").run(a))

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
    _fill_settings_values_gaps(out)
    return out


def _fill_settings_values_gaps(out):
    """settings.tsv 缺的 13 个键，用 setting-schemas.tsv + enum-values.tsv 补默认值。

    S8 报告 §6.1：`ws.py settings --mode X` 以前会**静默漏掉**这些键
    （英雄限制 / 急救包刷新 / 游戏模式开始 / 英雄池上限 …），生成出来的设置块不完整。
    """
    import csv as _csv
    schemas = os.path.join(DATA, "setting-schemas.tsv")
    if not os.path.isfile(schemas):
        return
    enums = {}
    ep = os.path.join(DATA, "enum-values.tsv")
    if os.path.isfile(ep):
        for r in _csv.DictReader(open(ep, encoding="utf-8"), delimiter="\t"):
            raw = (r.get("合法值原文") or "").strip()
            if raw:
                enums[r.get("键名", "")] = [x.strip() for x in raw.split("|") if x.strip()]
    for r in _csv.DictReader(open(schemas, encoding="utf-8"), delimiter="\t"):
        schema, key = (r.get("schema") or "").strip(), (r.get("key") or "").strip()
        if not key or (schema, key) in out:
            continue
        kind = (r.get("type") or "").strip().upper()
        default = (r.get("default") or "").strip()
        if kind.startswith("BOOL"):
            on = (r.get("on") or "").strip() or "开启"
            out[(schema, key)] = {"value": on, "raw": on, "kind": "BOOL", "default": on}
        elif "ENUM" in kind:
            opts = enums.get(key) or []
            val = opts[0] if opts else ""
            if not val:
                continue
            out[(schema, key)] = {"value": val, "raw": "|".join(opts), "kind": "ENUM", "default": val}
        else:
            v = default or "0"
            out[(schema, key)] = {"value": v, "raw": v, "kind": kind, "default": default}


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



def _http_get(url, timeout=30, binary=False):
    """下载：先直连，失败再走本机 Clash 代理（127.0.0.1:7897）。"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "workshop-lite"})
    last = None
    for proxies in (None, {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies or {}))
            with opener.open(req, timeout=timeout) as r:
                return r.read() if binary else r.read().decode("utf-8", "replace")
        except Exception as e:      # noqa: BLE001
            last = e
    raise last


def _find_editor():
    """能打开纯文本的编辑器。用户要求用记事本，别动 VS Code（会抢焦点、加载整个工作区）。"""
    import shutil as _sh
    if os.name == "nt":
        nt = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "notepad.exe")
        if os.path.isfile(nt):
            return nt
        hit = _sh.which("notepad.exe")
        if hit:
            return hit
    return _sh.which("gedit") or _sh.which("xdg-open") or None


def cmd_reveal(args):
    """直接用编辑器打开文件（交付测试文件时用）。

    用户要的是「文件直接在我眼前打开」，不是开个文件夹去里面找。
    """
    import subprocess
    path = os.path.abspath(args.file)
    if not os.path.exists(path):
        print("[错误] 找不到 %s" % path)
        return 1
    ed = _find_editor()
    try:
        if ed:
            subprocess.Popen([ed, path], shell=ed.lower().endswith(".cmd"))
            print("已用 %s 打开：%s" % (os.path.basename(ed), path))
        elif os.name == "nt":
            os.startfile(path)      # 交给系统关联程序
            print("已用系统关联程序打开：%s" % path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:          # noqa: BLE001
        print("打开失败（%s）；文件在这里：%s" % (e, path))
        return 1
    return 0


def cmd_upgrade(args):
    """从 GitHub 拉最新版本覆盖本技能（旧 data/docs/tools 备份到 .backup-vX）。

    注意：会覆盖 tools/ 等目录，跑之前先确认本地改动已经发版，否则会被冲掉。
    """
    import io, shutil, tarfile, tempfile
    local = _skill_version() or "0"
    try:
        main = _http_get("https://raw.githubusercontent.com/%s/main/SKILL.md" % REPO, timeout=8)
    except Exception as e:          # noqa: BLE001
        print("查不到远端版本（%s）；先确认网络/代理。" % e)
        return 1
    remote = ""
    for line in main.splitlines():
        if line.startswith("version:"):
            remote = line.split(":", 1)[1].strip()
            break
    if not remote:
        print("远端 SKILL.md 里没有 version 行，放弃升级。")
        return 1
    print("本地 v%s → 远端 v%s" % (local, remote))
    if remote == local and not args.force:
        print("已是最新，无需升级。")
        return 0
    if args.check:
        print("可升级；去掉 --check 才会覆盖（旧 data/docs/tools 备份到 .backup-v%s）。" % local)
        print("注意：本地未发版的改动会被远端覆盖，先发版或先提交。")
        return 1
    url = "https://api.github.com/repos/%s/tarball/%s" % (REPO, args.tag or ("v" + remote))
    print("下载 %s …" % url)
    try:
        blob = _http_get(url, timeout=180, binary=True)
    except Exception as e:          # noqa: BLE001
        print("下载失败：%s" % e)
        return 1
    tmp = tempfile.mkdtemp(prefix="wslite-")
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tg:
            tg.extractall(tmp)
        src = None
        for root, _dirs, files in os.walk(tmp):
            if "SKILL.md" in files and os.path.isdir(os.path.join(root, "tools")):
                src = root
                break
        if not src:
            print("压缩包里没找到 SKILL.md + tools/，放弃。")
            return 1
        backup = os.path.join(ROOT, ".backup-v%s" % local)
        os.makedirs(backup, exist_ok=True)
        for name in ("data", "docs", "tools"):
            old = os.path.join(ROOT, name)
            if os.path.isdir(old):
                shutil.copytree(old, os.path.join(backup, name), dirs_exist_ok=True)
        changed = 0
        for name in ("SKILL.md", "VERSION", "data", "docs", "tools", "agents", "assets", "references", "scripts"):
            s = os.path.join(src, name)
            if not os.path.exists(s):
                continue
            d = os.path.join(ROOT, name)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
                changed += sum(len(f) for _r, _d2, f in os.walk(s))
            else:
                shutil.copy2(s, d)
                changed += 1
        for root, dirs, _f in os.walk(os.path.join(ROOT, "tools")):
            for x in list(dirs):
                if x == "__pycache__":
                    shutil.rmtree(os.path.join(root, x), ignore_errors=True)
        print("已升级到 v%s（覆盖 %d 个文件）。旧版备份：%s" % (remote, changed, backup))
        print("下一步：python tools/ws.py selftest && python tools/ws.py check-all")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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


def cmd_locate(args):
    """游戏报错原文 → 命中报错模板 → 文件第几行 → 一句话改法。

    主线 A1：本地只能提前拦 27% 的解析器级报错，剩下靠这条兜底。
    """
    import locate
    return locate.locate(args.error, DATA, file_path=args.file,
                         radius=args.context, as_json=args.json,
                         to_case=getattr(args, "to_case", None))


def _load_tsv(name):
    """读 data/ 下的 tsv，返回字典列表；文件不存在返回空列表。"""
    import csv as _csv
    path = os.path.join(DATA, name)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(_csv.DictReader(f, delimiter="\t"))


def cmd_keyinfo(a):
    """一个设置键的全貌：属于哪一页、什么类型、哪些 schema/模式、合法值、语料挂哪层。

    把以前几张贴不上线的手工表（key-map / enum-values / mode-schemas / schema-keys）
    汇到一个查询入口，回答「这个键该写在哪、能写什么」。
    """
    key = a.key.strip()
    rows = []
    km = [r for r in _load_tsv("key-map.tsv") if (r.get("键") or "").strip() == key]
    st = [r for r in _load_tsv("settings.tsv") if (r.get("key") or "").strip() == key]
    sk = [r for r in _load_tsv("schema-keys.tsv") if (r.get("key") or "").strip() == key]
    ev = [r for r in _load_tsv("enum-values.tsv") if (r.get("键名") or "").strip() == key]
    pl = [r for r in _load_tsv("key-parent-layers.tsv") if (r.get("key") or "").strip() == key]

    if not (km or st or sk):
        print("没有「%s」这个键。相似的有：" % key)
        import difflib
        pool = sorted({(r.get("键") or "") for r in _load_tsv("key-map.tsv")} |
                      {(r.get("key") or "") for r in _load_tsv("settings.tsv")})
        for c in difflib.get_close_matches(key, [p for p in pool if p], n=6):
            print("  ", c)
        return 1

    print("=== %s ===" % key)
    for r in km:
        print("页        %s（%s）第 %s 个" % (r.get("页名"), r.get("页GUID"), r.get("页内序")))
        print("类型      %s" % (r.get("类型") or "?"))
        if r.get("键名串ID"):
            print("串ID      %s" % r.get("键名串ID"))
    for r in st:
        print("数据表    %s / %s    显示词：%s" % (r.get("schema"), r.get("type"), r.get("values") or "（空）"))
    if sk:
        names = sorted({(r.get("schema_name") or "") + "(" + (r.get("schema_guid") or "") + ")" for r in sk})
        print("所属schema " + "、".join(names))
        sch_names = {(r.get("schema_name") or "").strip() for r in sk}
        modes = []
        for r in _load_tsv("mode-schemas.tsv"):
            if sch_names & {(s or "").strip() for s in (r.get("schemas") or "").split("|")}:
                m = (r.get("mode") or "").strip()
                if m and m not in modes:
                    modes.append(m)
        if modes:
            shown = modes[:a.limit]
            print("出现在的模式（%d 个）%s%s"
                  % (len(modes), "、".join(shown), " …" if len(modes) > len(shown) else ""))
    if ev:
        for r in ev:
            print("合法值    %s" % (r.get("合法值原文") or "")[:70])
            if r.get("依据"):
                print("          依据 %s" % (r.get("依据") or "")[:70])
    if pl:
        for r in pl:
            print("层限制    只能写在「%s」（%s）" % (r.get("allowed_parents"), r.get("source") or ""))
    if not pl:
        print("层限制    （没有实机结论；不确定就写在「模式 > 综合」或该模式块里，别嵌套过深）")
    return 0


def cmd_hero(a):
    """列某英雄的设置页与键（data/hero-pages.tsv，1919 行，之前没人读）。"""
    name = a.name.strip()
    rows = [r for r in _load_tsv("hero-pages.tsv") if (r.get("owner") or "").strip() == name]
    if not rows:
        print("没有「%s」的英雄页数据。可用：" % name)
        owners = sorted({(r.get("owner") or "").strip() for r in _load_tsv("hero-pages.tsv") if r.get("owner")})
        print("  " + "、".join(owners[:30]) + (" …" if len(owners) > 30 else ""))
        return 1
    pages = {}
    for r in rows:
        pages.setdefault((r.get("page_no") or "", r.get("page") or ""), []).append(r)
    print("=== %s：%d 个设置页 ===" % (name, len(pages)))
    for (no, page), items in sorted(pages.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        seen, keys = set(), []
        for r in items:
            k = (r.get("key") or "").strip()
            if not k or k in seen:
                continue
            seen.add(k)
            keys.append(k)
        tpl = [k for k in keys if "%1$s" in k or "%s" in k]
        real = [k for k in keys if k not in tpl]
        print("\n[%s] %s（%d 个可写键）" % (no, page, len(real)))
        for k in real[:a.limit]:
            print("   ", k)
        if len(real) > a.limit:
            print("    …还有 %d 个，用 --limit 调大" % (len(real) - a.limit))
        if tpl:
            print("    （另有 %d 个模板键，如 %s —— 每个技能各一份）" % (len(tpl), tpl[0]))
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


