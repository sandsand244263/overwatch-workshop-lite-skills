#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 v13 那套手工探针工具化：一条 check_* 的「读哪一行」自动出读数。

它只回答一个问题：**这条检查会不会被字符串 / 注释 / 规则名骗到**（误报），
以及**豁免词写在字符串 / 注释里会不会把真问题压掉**（漏报）。

做法（和 v13-re/S2-string-scan.md 的手工流程一一对应）：
  ① 用一份模板生成 7 个变体文件，把目标词分别放进 6 个位置（描述×2、记入查看器、
     自定义字符串、规则名、// 注释、/* */）；
  ② 每个变体**只调这一条检查**（不是跑全量 lint），所以读数天然归属它，不会混进别的检查；
  ③ 再跑一个阳性对照（真语句），对照不成立 → 全部结论标「未验证」。

只读：除 `--keep` 指定的目录（默认系统临时目录）外不写任何文件。

用法：
  python tools/audit_stringscan.py --list
  python tools/audit_stringscan.py --check check_game_end_actions \\
      --word 宣告队伍胜利 --stmt "宣告队伍胜利(队伍1);"
  python tools/audit_stringscan.py --check check_victory_in_loop \\
      --word 宣告玩家胜利 --stmt "宣告玩家胜利(事件玩家);" --exempt 中断
  python tools/audit_stringscan.py --check check_bare_strings --raw-by-design \\
      --word 裸字符串 --stmt '记入查看器("裸字符串");'

退出码：0 = 读数完整；2 = 阳性对照失败（结论作废）；3 = 这条检查不能单独调用。
"""
from __future__ import annotations

import argparse
import inspect
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402

DATA_DIR = os.path.join(HERE, "..", "data")
if not os.path.isdir(DATA_DIR):
    DATA_DIR = core.DATA_DIR

MARK = "@@INSERT@@"

# 模板：一份最小可导入的死斗文件。动作块里的 @@INSERT@@ 会被换成本次要测的语句。
BASE_TMPL = """设置
{
\t主程序
\t{
\t\t描述: "audit 探针"
\t\t模式名称: "audit"
\t}

\t大厅
\t{
\t\t地图轮换: 完成比赛后
\t\t比赛结束后转换队伍: 否
\t\t玩家上限 队伍1: 6
\t\t玩家上限 队伍2: 0
\t\t观战者人数上限: 0
\t\t返回大厅: 从不
\t\t队列中的玩家可以加入: 是
\t}

\t模式
\t{
\t\t死斗
\t\t{
\t\t\t启用地图
\t\t\t{
\t\t\t\t地图工坊室内 972777519512064577
\t\t\t}
\t\t\t随机英雄复生: 开启
\t\t\t获胜得分: 20
\t\t}

\t\t综合
\t\t{
\t\t\t游戏模式开始: 即时
\t\t\t复生时间: 5%
\t\t}
\t}
}

变量
{
\t全局:
\t\t0: b
\t\t1: tick
}

规则("audit 规则")
{
\t事件
\t{
\t\t持续 - 全局;
\t}

\t动作
\t{
@@INSERT@@
\t}
}
"""

POSITIONS = ["描述(主)", "描述(内)", "记入查看器", "自定义字符串", "规则名", "// 注释", "/* */"]


# ---------------------------------------------------------------- 数据装载
def load_all():
    """按 full_lint() 的方式装一遍数据表，供单检查调用。"""
    d = DATA_DIR
    sigs, labels, settings = core.load_signatures(os.path.join(d, "signatures.md"))
    ext, ext_values = core.load_extensions(os.path.join(d, "extensions.tsv"),
                                           os.path.join(d, "extension-values.tsv"))
    return {
        "sigs": sigs,
        "labels": labels,
        "settings": settings,
        "values": core.load_setting_values(os.path.join(d, "setting-values.tsv")),
        "ranges": core.load_setting_ranges(os.path.join(d, "setting-ranges.tsv")),
        "event_params": core.load_event_params(os.path.join(d, "event-params.tsv")),
        "event_param_words": core.load_event_param_words(os.path.join(d, "event-param-words.tsv")),
        "bare_ok": core.load_bare_ok(os.path.join(d, "bare-ok.tsv")),
        "kinds": core.load_element_kinds(os.path.join(d, "element-kinds.tsv")),
        "dropdowns": core.load_dropdowns(os.path.join(d, "param-options.tsv")),
        "map_names": core.load_map_names(os.path.join(d, "maps.tsv")),
        "setting_keys": core.load_setting_keys(),
        "hero_names": core.load_hero_names(),
        "button_names": core.load_button_names(),
        "event_names": core.load_event_names(),
        "aliases": core.load_setting_aliases(os.path.join(d, "setting-aliases.tsv")),
        "costs": ext,
        "base_options": ext_values,
        "raw_masked": None,   # 逐文件算
    }


def declared_and_subroutines(text):
    """够用就行的变量/子程序解析（只服务 check_var_refs / check_subroutines 这类）。"""
    declared = {"全局": set(), "玩家": set()}
    subs = {}
    section = None
    block = None
    for line in text.split("\n"):
        s = core.strip_noise(line).strip()
        if not s:
            continue
        if s in ("变量", "子程序"):
            block = s
            continue
        if s in ("}",):
            if block:
                block = None
                section = None
            continue
        if block == "变量" and s in ("全局:", "玩家:"):
            section = s.rstrip(":")
            continue
        if block == "变量" and section and ":" in s:
            name = s.split(":", 1)[1].strip()
            if name:
                declared[section].add(name)
            continue
        if block == "子程序" and ":" in s:
            name = s.split(":", 1)[1].strip()
            if name:
                subs[name] = 1
    return declared, subs


# ---------------------------------------------------------------- 调一条检查
def check_names():
    return sorted(n for n, f in vars(core).items()
                  if n.startswith("check_") and callable(f))


def run_one(name, text, path, data):
    """只跑这一条检查，返回 problems 列表。参数按签名名填。"""
    fn = getattr(core, name, None)
    if fn is None:
        raise KeyError("没有这条检查：%s" % name)
    sig = inspect.signature(fn)
    raw_text = text
    text_pp = core.merge_continuations(core.join_multiline_strings(text))
    masked = core.mask_text(text_pp)
    declared, subs = declared_and_subroutines(text_pp)

    pool = {
        "text": text_pp,
        "raw": raw_text,
        "masked": masked,
        "path": path,
        "data_dir": DATA_DIR,
        "values": data["values"],
        "ranges": data["ranges"],
        "modes": None,
        "kinds": data["kinds"],
        "sigs": data["sigs"],
        "labels": data["labels"],
        "bare_ok": data["bare_ok"],
        "event_params": data["event_params"],
        "event_param_words": data["event_param_words"],
        "hero_names": data["hero_names"],
        "declared": declared,
        "button_names": data["button_names"],
        "abilities": set(core.load_ability_names()) | core.load_extra_ability_names(),
        "setting_keys": data["setting_keys"],
        "event_names": data["event_names"],
        "subroutines": subs,
        "types": core.load_param_types(),
        "heroes": None,
        "traits": None,
        "pools": None,
        "lobby_keys": None,
        "aliases": data["aliases"],
        "counts": None,
        "zero": None,
        "costs": data["costs"],
        "unlocked": None,
        "base_options": data["base_options"],
        "dropdowns": data["dropdowns"],
        "map_names": data["map_names"],
        "strict": True,
        "raw_masked": core.mask_text(raw_text),
        "limit": 32,
    }

    args = []
    problems = []
    for pname, p in sig.parameters.items():
        if pname == "problems":
            args.append(problems)
            continue
        if pname in pool:
            val = pool[pname]
            if val is None and p.default is inspect.Parameter.empty:
                raise KeyError("这条检查需要参数 %s，工具还没有对照表" % pname)
            args.append(val)
        elif p.default is not inspect.Parameter.empty:
            args.append(p.default)
        else:
            raise KeyError("这条检查需要参数 %s，工具还没有对照表" % pname)
    fn(*args)
    return problems


# ---------------------------------------------------------------- 造探针
def build(base_text, pos, payload, extra_stmt=None):
    """payload 放到 pos 位置；extra_stmt（真语句）放到动作块标记处。"""
    ins = []
    if pos == "描述(主)":
        base_text = base_text.replace('描述: "audit 探针"', '描述: "%s"' % (payload or ""), 1)
    elif pos == "描述(内)":
        ins.append('\t\t描述: "%s"' % payload)
    elif pos == "记入查看器":
        ins.append('\t\t记入查看器(自定义字符串("%s"));' % payload)
    elif pos == "自定义字符串":
        ins.append('\t\t创建HUD文本(所有玩家, 自定义字符串("t"), 自定义字符串("s"), '
                   '自定义字符串("%s"), 顶部, 0, 白色, 白色, 白色);' % payload)
    elif pos == "规则名":
        base_text = base_text.replace('规则("audit 规则")', '规则("%s")' % (payload or ""), 1)
    elif pos == "// 注释":
        ins.append('\t\t// %s' % payload)
    elif pos == "/* */":
        ins.append('\t\t/* %s */' % payload)
    elif pos is None:
        pass
    else:
        raise KeyError(pos)

    out = []
    for ln in base_text.split("\n"):
        if MARK in ln:
            if extra_stmt:
                out.append("\t\t" + extra_stmt)
            out.extend(ins)
            continue
        out.append(ln)
    return "\n".join(x for x in out if x.strip() or True)


# ---------------------------------------------------------------- 主流程
def scan(check, word, stmt, exempts, base_text, keep, raw_by_design=False):
    data = load_all()
    os.makedirs(keep, exist_ok=True)
    rows = []

    def _slug(s):
        out = []
        for ch in s:
            out.append(ch if (ch.isalnum() or ch == "_") else "_")
        return "".join(out)

    def run(tag, text):
        path = os.path.join(keep, "%s__%s.ow" % (_slug(check.replace("check_", "")), _slug(tag)))
        with io.open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        try:
            return run_one(check, text, path, data)
        except KeyError as e:
            raise SystemExit("[!] %s" % e)

    # ① 基线：模板本身（有些检查本来就会命中模板里的东西，读数一律减掉基线）
    base_probs = run("基线_模板本身", base_text)
    nb = len(base_probs)

    def rec(direction, pos, probs, note=""):
        d = len(probs) - nb
        rows.append((direction, pos, d,
                     "%d 条（基线 %d）" % (len(probs), nb),
                     note or (probs[0][2][:60] if probs else "")))
        return d

    # ② 阳性对照
    if stmt:
        d_ctrl = rec("阳性对照", "真语句", run("正例_真语句", build(base_text, None, None, extra_stmt=stmt)))
    else:
        rows.append(("阳性对照", "—", 0, "没给 --stmt", "跳过（无法判「该响时会响」）"))
        d_ctrl = 0
    ok_control = nb > 0 or (bool(stmt) and d_ctrl > 0)

    # ③ 误报方向：只有目标词，没有真语句
    if word:
        for pos in POSITIONS:
            rec("误报扫描", pos, run("误报_%s" % pos, build(base_text, pos, word)))

    # ④ 漏报方向：真语句 + 豁免词写在某位置，对比「同位置写中性字」
    if exempts and stmt:
        if isinstance(exempts, str):
            exempts = [exempts]
        for pos in POSITIONS:
            d_ne = rec("对照(中性)", pos,
                       run("对照_%s_中性" % pos, build(base_text, pos, "中性文本", extra_stmt=stmt)))
            for ex in exempts:
                d_ex = rec("漏报扫描", "%s（豁免词「%s」）" % (pos, ex),
                           run("漏报_%s_%s" % (pos, ex),
                               build(base_text, pos, ex, extra_stmt=stmt)))
                rows.append(("漏报判定", "%s（豁免词「%s」）" % (pos, ex),
                             d_ne - d_ex,
                             "对照增量 %d → 豁免增量 %d" % (d_ne, d_ex),
                             "压掉了" if d_ne > 0 and d_ex < d_ne else "没压掉"))

    # ⑤ 结论
    fp = [r for r in rows if r[0] == "误报扫描" and r[2] > 0]
    fn = [r for r in rows if r[0] == "漏报判定" and r[2] > 0]
    if stmt and not ok_control:
        verdict = "未验证（阳性对照没有增量：这条检查在本模板下不触发）"
    elif not stmt and nb == 0 and not fp:
        verdict = "未验证（没给 --stmt，模板也没触发这条检查）"
    else:
        parts = []
        if fp:
            parts.append("有误报（%s）" % "、".join(r[1] for r in fp))
        if fn:
            parts.append("有漏报（%s）" % "、".join(r[1] for r in fn))
        if not parts:
            parts.append("无缺陷")
        if fp and not stmt:
            parts.append("未做阳性对照：误报读数成立，但要确认触发形态跟真语句一致")
        if raw_by_design and fp:
            parts.append("注：本检查按设计要读字符串内容，误报列需人工判")
        verdict = "；".join(parts)

    return rows, verdict, len(rows), nb


def main(argv=None):
    ap = argparse.ArgumentParser(description="检查「读哪一行」的自动读数工具")
    ap.add_argument("--check", help="要审的 check_* 函数名")
    ap.add_argument("--word", help="目标词（写进 6 个位置，看会不会被骗）")
    ap.add_argument("--stmt", help="真语句（阳性对照用，例：'宣告队伍胜利(队伍1);'）")
    ap.add_argument("--exempt", action="append", help="豁免词（漏报方向，可多次）")
    ap.add_argument("--base", help="自定义模板文件（必须含 @@INSERT@@ 行）")
    ap.add_argument("--sub", action="append", metavar="旧=>新",
                    help="在生成探针前做一次文本替换（改结构用，可多次），例：'972777519512064577=>972777519512069999'")
    ap.add_argument("--keep", help="探针落地目录（默认系统临时目录）")
    ap.add_argument("--out", help="把读数写成 tsv")
    ap.add_argument("--raw-by-design", action="store_true",
                    help="这条检查按设计就要看得见字符串内容（结果需人工判）")
    ap.add_argument("--list", action="store_true", help="列出全部 check_*")
    a = ap.parse_args(argv)

    if a.list:
        for n in check_names():
            print(n)
        return 0
    if not a.check:
        ap.error("要么 --list，要么给 --check")

    base_text = io.open(a.base, encoding="utf-8").read() if a.base else BASE_TMPL
    if MARK not in base_text:
        raise SystemExit("[!] 模板里没有 %s 标记行" % MARK)
    for pair in (a.sub or []):
        if "=>" not in pair:
            raise SystemExit("[!] --sub 要写成 '旧=>新'：%s" % pair)
        old, new = pair.split("=>", 1)
        if old not in base_text:
            raise SystemExit("[!] --sub 的旧文本在模板里找不到：%s" % old)
        base_text = base_text.replace(old, new)
    keep = a.keep or tempfile.mkdtemp(prefix="stringscan-")

    rows, verdict, _n, nb = scan(a.check, a.word, a.stmt, a.exempt, base_text, keep,
                                 raw_by_design=a.raw_by_design)

    print("检查：%s" % a.check)
    print("模板：%s（基线命中 %d 条）" % (a.base or "<内置死斗模板>", nb))
    print("%-10s %-24s %-4s %-16s %s" % ("方向", "位置", "增量", "条数", "首条文案"))
    for r in rows:
        print("%-10s %-24s %-4d %-16s %s" % (r[0], r[1], r[2], r[3], r[4]))
    print("结论：%s" % verdict)
    print("探针目录：%s" % keep)

    if a.out:
        with io.open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write("检查\t方向\t位置\t增量\t条数\t首条文案\t结论\n")
            for r in rows:
                f.write("%s\t%s\t%s\t%d\t%s\t%s\t%s\n" % (a.check, r[0], r[1], r[2], r[3], r[4], verdict))
        print("已写：%s" % a.out)

    return 0 if verdict.startswith(("无缺陷", "有误报", "有漏报")) else 2


if __name__ == "__main__":
    sys.exit(main())
