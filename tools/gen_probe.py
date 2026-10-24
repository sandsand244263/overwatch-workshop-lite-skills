# -*- coding: utf-8 -*-
"""探针骨架生成器：一格一计数器 + 对照组 + 每秒打点 + 明确截止。

  python tools/gen_probe.py --cells 8 --out X.ow
  python tools/ws.py probe-template --cells 8 --out X.ow
  python tools/ws.py probe-template --cells 6 --structures 无条件,If真,If假,条件块真,条件块假,每名玩家 --out Y.ow

产出的硬约定（生成器会自查，不满足就不写文件）：

- 一格一个计数器变量（`c1`…），一个计数器只服务一个结构
- 单文件最多 20 格
- 必须带对照组：对照组是「结构相同、只有条件不可能成立」的格子
- 每秒打点一次，格式固定 `[cN] cN=<值>`，只走 `记入查看器`
- 每个循环都带退出条件（`While(全局.t < 秒数)`），不用 `While(真)`；万一出现 `While(真)`，
  后面 30 行内必须有 `中断`，否则报错
- 持续类规则开头先 `等待直到(正在设置 == 假, 60)` + `等待(6, 无视条件)` 避开开局倒计时
- 屏幕隐蔽（隐藏英雄HUD / 隐藏游戏模式HUD / 开始镜头）写在「每名玩家」规则里，且在等待之前

同时生成配套 expect.tsv 骨架（格号 / 结构说明 / 期望 / 容差 / 依据 / 备注）。
模板约定与判读流程见 docs/probe-spec.md。
"""
import argparse
import os
import sys

MAX_CELLS = 20
DEFAULT_SECONDS = 12
GUARD_WAIT = 6          # 避开开场倒计时（实测约 5 秒）
LOOP_MARGIN = 2         # expect.tsv 默认容差

# 结构表：每项 = 一格能长成什么样子。
#   event:  全局 / 每名玩家
#   cond:   条件块里的表达式（None = 不写条件块）
#   body:   每秒循环体里的语句，%INC% %LOG% %AUX% 会被替换
#   per_tick: 每轮打点预期增加多少（None 表示不靠推算，用 want 字面量）
#   want:   直接写死的期望（覆盖 per_tick），如 "未出现"
#   aux:    需要一格私有的辅助变量（同一结构跑两格不会互相踩）
#   control_of / control: 对照关系
STRUCTURES = {
    "无条件": {
        "event": "全局", "cond": None,
        "body": ["%INC%", "%LOG%"],
        "per_tick": 1,
        "note": "基线：循环体内无条件 +1，读数应约等于跑秒数",
    },
    "等待0": {
        "event": "全局", "cond": None,
        "body": ["等待(0, 无视条件);", "%INC%", "%LOG%"],
        "per_tick": 1,
        "note": "循环体里插一句 等待(0)：验证零等待不会把循环卡住或加速",
    },
    "If真": {
        "event": "全局", "cond": None,
        "body": ["If(1 == 1);", "\t%INC%", "End;", "%LOG%"],
        "per_tick": 1, "control": "If假",
        "note": "循环体内 If(恒真) 包住计数器：应与「无条件」一致",
    },
    "If假": {
        "event": "全局", "cond": None,
        "body": ["If(1 == 2);", "\t%INC%", "End;", "%LOG%"],
        "per_tick": 0, "control_of": "If真",
        "note": "对照组：结构与 If真 完全一样，只有条件恒假 → 每轮都打点但值恒为 0",
    },
    "条件块真": {
        "event": "全局", "cond": "1 == 1",
        "body": ["%INC%", "%LOG%"],
        "per_tick": 1,
        "note": "条件写进「条件」块且恒真：只在上升沿跑一次，这一轮循环跑完即停",
    },
    "条件块假": {
        "event": "全局", "cond": "1 == 2",
        "body": ["%INC%", "%LOG%"],
        "want": "未出现", "control_of": "条件块真",
        "note": "对照组：结构与 条件块真 一样，条件恒假 → 整条规则不执行，日志里不该有它的键",
    },
    "While上限": {
        "event": "全局", "cond": None,
        "body": ["全局.%AUX% = 0;",
                 "While(全局.%AUX% < 3);",
                 "\t全局.%AUX% = 全局.%AUX% + 1;",
                 "\t%INC%",
                 "End;",
                 "%LOG%"],
        "per_tick": 3, "aux": True, "control": "While假",
        "note": "内层 While(aux<3) 有硬上限：每轮 +3（同时验证内层循环能正常退出）",
    },
    "While假": {
        "event": "全局", "cond": None,
        "body": ["While(1 == 2);", "\t%INC%", "End;", "%LOG%"],
        "per_tick": 0, "control_of": "While上限",
        "note": "对照组：结构与 While上限 一样，条件恒假 → 内层循环一次都不进，值恒为 0",
    },
    "For循环": {
        "event": "全局", "cond": None,
        "body": ["For 全局变量(%AUXN%, 1, 4, 1);", "\t%INC%", "End;", "%LOG%"],
        "per_tick": 3, "aux": True, "control": "For循环0",
        "note": "For 1→4 不包含终止值 = 3 次：每轮 +3",
    },
    "For循环0": {
        "event": "全局", "cond": None,
        "body": ["For 全局变量(%AUXN%, 1, 1, 1);", "\t%INC%", "End;", "%LOG%"],
        "per_tick": 0, "aux": True, "control_of": "For循环",
        "note": "对照组：结构与 For循环 一样，区间为空 → 0 次，值恒为 0",
    },
    "每名玩家": {
        "event": "每名玩家", "cond": None,
        "body": ["%INC%", "%LOG%"],
        "per_tick": 1, "ge": True, "control": "每名玩家If假",
        "note": "每名玩家 = 每人一个实例：两人在场时读数约为单人两倍",
    },
    "每名玩家If假": {
        "event": "每名玩家", "cond": None,
        "body": ["If(1 == 2);", "\t%INC%", "End;", "%LOG%"],
        "per_tick": 0, "control_of": "每名玩家",
        "note": "对照组：结构与 每名玩家 一样，条件恒假 → 每人每轮打点但值恒为 0",
    },
}

# 默认拼装顺序：先基线/pair，再对照组多的结构。
PLAN_UNITS = [
    ["无条件"],
    ["If真", "If假"],
    ["条件块真", "条件块假"],
    ["While上限", "While假"],
    ["每名玩家", "每名玩家If假"],
    ["For循环", "For循环0"],
    ["等待0"],
]

SETTINGS_BLOCK = """设置
{{
	主程序
	{{
		描述: "{desc}"
		模式名称: "{name}"
	}}

	模式
	{{
		死斗
		{{
			启用地图
			{{
				地图工坊室内 972777519512064577
			}}
		}}

		综合
		{{
			游戏模式开始: 即时
			随机英雄复生: 开启
		}}
	}}
}}
"""


def default_plan(n):
    """按 PLAN_UNITS 拼出 n 格：先按「测试 + 对照」成对装，剩下的空位用单格结构补。

    成对优先是刻意的——小格数（n=2）也要能凑出「1 测试 + 1 对照」。
    """
    pairs = [u for u in PLAN_UNITS if len(u) == 2]
    singles = [u[0] for u in PLAN_UNITS if len(u) == 1]
    plan, si = [], 0
    for unit in pairs:
        if len(plan) + 2 <= n:
            plan += unit
    while len(plan) < n and si < len(singles):
        plan.append(singles[si])
        si += 1
    return plan


def validate(plan, seconds):
    """生成前的硬约定检查。返回错误列表（空 = 可生成）。"""
    errs = []
    if not plan:
        errs.append("一格都没有")
    if len(plan) > MAX_CELLS:
        errs.append("要 %d 格，超过单文件上限 %d 格" % (len(plan), MAX_CELLS))
    if seconds < 5:
        errs.append("跑 %d 秒太短：开局倒计时约 5 秒，读数还没稳就结束了（最少 5，建议 12）" % seconds)
    unknown = [s for s in plan if s not in STRUCTURES]
    if unknown:
        errs.append("没有这些结构：%s（可选：%s）"
                    % ("、".join(unknown), "、".join(STRUCTURES)))
        return errs
    if len(set(plan)) != len(plan):
        dup = sorted({s for s in plan if plan.count(s) > 1})
        errs.append("结构重复用了：%s（一格一结构，重复要各配一个计数器变量，先把结构表补上）"
                    % "、".join(dup))
        return errs
    controls = [s for s in plan if STRUCTURES[s].get("control_of")]
    if not controls:
        errs.append("没有对照组：必须至少一格「结构相同但不该触发」（If假 / 条件块假 / While假 / "
                    "For循环0 / 每名玩家If假）")
    for s in plan:
        if STRUCTURES[s].get("control_of") and STRUCTURES[s]["control_of"] not in plan:
            errs.append("对照组 %s 的配对测试格 %s 不在文件里：对照组必须有结构相同的测试格才成立"
                        % (s, STRUCTURES[s]["control_of"]))
    for s in plan:
        pair = STRUCTURES[s].get("control")
        if pair and pair not in plan:
            errs.append("测试格 %s 缺少对照组 %s（结构相同、条件恒假）" % (s, pair))
    return errs


def _cell_vars(plan):
    """-> (变量名列表, {格序: 计数器}, {格序: 辅助变量})；辅助变量统一排在计数器后面。"""
    counters, auxes = {}, {}
    for i, s in enumerate(plan, 1):
        counters[i] = "c%d" % i
        if STRUCTURES[s].get("aux"):
            auxes[i] = "i%d" % i
    names = ["t"] + [counters[i] for i in range(1, len(plan) + 1)]
    names += [auxes[i] for i in sorted(auxes)]
    return names, counters, auxes


def build_rule(index, struct, key, aux, seconds):
    """"一条规则 = 一格。"""
    st = STRUCTURES[struct]
    player = st["event"] == "每名玩家"
    lines = ['规则("格%02d %s %s")' % (index, key, struct), "{", "\t事件", "\t{"]
    if player:
        lines += ["\t\t持续 - 每名玩家;", "\t\t双方;", "\t\t全部;"]
    else:
        lines += ["\t\t持续 - 全局;"]
    lines += ["\t}"]
    if st["cond"]:
        lines += ["", "\t条件", "\t{", "\t\t%s;" % st["cond"], "\t}"]
    lines += ["", "\t动作", "\t{"]
    lines += ['\t\t// 结构：%s —— %s' % (struct, st["note"])]
    if player:
        lines += ["\t\t// 每名玩家 = 每人一个实例，计数器是全局的，读数会按人数放大"]
    lines += ["\t\t等待直到(正在设置 == 假, 60);",
              "\t\t等待(%d, 无视条件);" % GUARD_WAIT,
              "\t\tWhile(全局.t < %d);          // 退出条件：时钟走完就停" % seconds,
              "\t\t\t等待(1, 无视条件);"]

    # 结构里手写的缩进（\t 开头）要再降一级
    for line in st["body"]:
        lead = 1 if line.startswith("\t") else 0
        body = (line.lstrip("\t").replace("%INC%", "全局.%s = 全局.%s + 1;" % (key, key))
                .replace("%LOG%", '记入查看器(自定义字符串("[%s] %s={0}", 全局.%s));'
                          % (key, key, key))
                .replace("%AUXN%", aux or "")
                .replace("%AUX%", aux or ""))
        lines.append("\t\t\t" + ("\t" * lead) + body)
    lines += ["\t\tEnd;", "\t}", "}", ""]
    return lines


def build_probe(plan, seconds, name="探针"):
    """-> .ow 文本（CRLF）。"""
    names, counters, auxes = _cell_vars(plan)
    desc = "探针模板：%d 格（%s），每秒打点一次，%d 秒后自停" % (
        len(plan), "、".join(plan), seconds)
    out = [SETTINGS_BLOCK.format(desc=desc, name=name).replace("\r\n", "\n")]

    out.append("变量\n{\n\t全局:")
    for i, v in enumerate(names):
        out.append("\t\t%d: %s" % (i, v))
    out.append("}\n")

    # 隐蔽：必须「每名玩家 + 事件玩家」，且写在等待之前
    out.append('规则("隐蔽 屏幕干净")\n{\n\t事件\n\t{\n\t\t持续 - 每名玩家;\n\t\t双方;\n\t\t全部;\n\t}\n\n'
               '\t动作\n\t{\n'
               '\t\t隐藏英雄HUD(事件玩家);\n'
               '\t\t隐藏游戏模式HUD(事件玩家);\n'
               '\t\t开始镜头(事件玩家, 矢量(0, 50, 0), 矢量(0, 200, 0), 100);\n'
               '\t\t等待直到(正在设置 == 假, 60);\n'
               '\t\t等待(%d, 无视条件);\n'
               '\t\tWhile(全局.t < %d);          // 退出条件：读数跑完就连隐蔽一起收\n'
               '\t\t\t等待(1, 无视条件);\n'
               '\t\t\t隐藏英雄HUD(事件玩家);\n'
               '\t\t\t隐藏游戏模式HUD(事件玩家);\n'
               '\t\t\t开始镜头(事件玩家, 矢量(0, 50, 0), 矢量(0, 200, 0), 100);\n'
               '\t\tEnd;\n\t}\n}\n' % (GUARD_WAIT, seconds))

    # 时钟：只有一个，所有格子读它决定何时收工
    out.append('规则("时钟 每秒一格")\n{\n\t事件\n\t{\n\t\t持续 - 全局;\n\t}\n\n'
               '\t动作\n\t{\n'
               '\t\t等待直到(正在设置 == 假, 60);\n'
               '\t\t等待(%d, 无视条件);\n'
               '\t\tWhile(全局.t < %d);          // 计时上限，走完就退出\n'
               '\t\t\t等待(1, 无视条件);\n'
               '\t\t\t全局.t = 全局.t + 1;\n'
               '\t\tEnd;\n'
               '\t\t记入查看器(自定义字符串("[clock] t={0}", 全局.t));\n'
               '\t}\n}\n' % (GUARD_WAIT, seconds))

    for i, struct in enumerate(plan, 1):
        out.extend(build_rule(i, struct, counters[i], auxes.get(i), seconds))
    return "\r\n".join("\n".join(out).split("\n")).rstrip("\r\n") + "\r\n"


def build_expect(plan, seconds, name="探针"):
    """-> expect.tsv 文本。期望/容差都按结构与秒数推算，依据留空待填。"""
    rows = ["# 期望表：%s（%d 格 / 跑 %d 秒）——可由 ws.py readlog --expect-file 直接判读"
            % (name, len(plan), seconds),
            "# 结论只有四档：通过 / 不符 / 未出现 / 超容差；容差三种写法 ±2、>=10、10..20",
            "\t".join(("格号", "结构说明", "期望", "容差", "依据", "备注"))]
    for i, struct in enumerate(plan, 1):
        st = STRUCTURES[struct]
        key = "c%d" % i
        if st.get("want"):
            want, tol = st["want"], ""
        elif st.get("ge"):
            want, tol = ">=%d" % seconds, ""
        elif st.get("per_tick") == 0:
            want, tol = "0", ""
        else:
            want = str(st["per_tick"] * seconds)
            tol = "±%d" % (LOOP_MARGIN * st["per_tick"])
        basis = "未验证"
        note = st["note"]
        if st.get("control_of"):
            note = "对照组（配对 %s）" % st["control_of"]
        rows.append("\t".join((key, struct, want, tol, basis, note)))
    return "\r\n".join(rows) + "\r\n"


def lint_probe_text(text):
    """生成后的自查：这一份必须满足的写作约定。返回问题列表。"""
    problems, lines = [], text.split("\n")
    for token in ("%INC%", "%LOG%", "%AUX%", "%AUXN%"):
        if token in text:
            problems.append("模板占位符 %s 没被替换掉（结构表写错了）" % token)
    for n in range(1, MAX_CELLS + 1):
        if "全局变量(," in text or "全局变量()" in text:
            problems.append("For 循环的变量名是空的：一格一计数器，缺辅助变量")
            break
    if "记入查看器" not in text:
        problems.append("没有任何 记入查看器：读数拿不到")
    if "开始镜头" not in text:
        problems.append("没有 开始镜头：屏幕不隐蔽")
    else:
        hide = text.find("开始镜头")
        wait = text.find("等待直到(正在设置")
        if wait != -1 and hide > wait:
            problems.append("开始镜头 写在等待之后：开赛前那段仍能看到角色")
    for i, line in enumerate(lines):
        code = line.split("//")[0] if "//" in line else line
        if "While(真)" in code.replace(" ", ""):
            tail = "\n".join(lines[i:i + 30])
            if "中断" not in tail:
                problems.append("第 %d 行 While(真) 后面 30 行内没有 中断：可能死循环" % (i + 1))
        if "While(" in code and "全局.t <" not in code and "While(真)" not in code.replace(" ", ""):
            if "全局.i" not in code and "1 == 2" not in code:
                problems.append("第 %d 行 While 条件不是明确的计时上限：%s" % (i + 1, code.strip()))
    for n in range(1, MAX_CELLS + 1):
        key = "c%d" % n
        if "[%s] %s=" % (key, key) in text:
            if text.count("全局.%s = 全局.%s + 1" % (key, key)) != 1:
                problems.append("%s 的计数器没有唯一的 +1 语句（一格一计数器）" % key)
    return problems


def main_with_args(args):
    cells = getattr(args, "cells", None) or 8
    seconds = getattr(args, "seconds", None) or DEFAULT_SECONDS
    name = getattr(args, "name", None) or "探针"
    if getattr(args, "structures", None):
        plan = [s.strip() for s in args.structures.split(",") if s.strip()]
    else:
        if cells > MAX_CELLS:
            print("[错误] 单文件最多 %d 格，要了 %d 格。拆成两个探针跑，读数按次归并。"
                  % (MAX_CELLS, cells))
            return 2
        plan = default_plan(cells)
        if len(plan) < cells:
            print("[错误] 内置结构只能拼出 %d 格，够不到 %d 格。"
                  "要么减少 --cells，要么用 --structures 显式列出（现有 %d 种结构：%s）"
                  % (len(plan), cells, len(STRUCTURES), "、".join(STRUCTURES)))
            return 2
    errs = validate(plan, seconds)
    if errs:
        print("[错误] 模板约定不满足，没有生成文件：")
        for e in errs:
            print("  - %s" % e)
        return 2

    text = build_probe(plan, seconds, name)
    problems = lint_probe_text(text)
    if problems:
        print("[错误] 生成结果自查没过（生成器有 bug，或结构表写错了）：")
        for p in problems:
            print("  - %s" % p)
        return 2

    out = getattr(args, "out", None) or "probe.ow"
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    exp_path = getattr(args, "expect_out", None) or (os.path.splitext(out)[0] + ".expect.tsv")
    with open(exp_path, "w", encoding="utf-8", newline="") as f:
        f.write(build_expect(plan, seconds, os.path.basename(out)))

    print("已生成 %s：%d 格 / 跑 %d 秒 / 每秒打点一次" % (out, len(plan), seconds))
    for i, struct in enumerate(plan, 1):
        st = STRUCTURES[struct]
        tag = "对照" if st.get("control_of") else "测试"
        print("  c%-2d %-2s %-10s %s" % (i, tag, struct, st["note"]))
    print("已生成 %s：期望/容差已按结构和秒数推算好，依据列留「未验证」待回填" % exp_path)
    print("\n下一步：")
    print("  1) python tools/ws.py check %s        必须 0 error" % out)
    print("  2) 导入游戏跑一次（跑完退到大厅再退游戏，日志才会落盘）")
    print("  3) python tools/ws.py readlog --expect-file %s" % exp_path)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="gen_probe", description="生成探针骨架 .ow + expect.tsv")
    ap.add_argument("--cells", type=int, default=8, help="格数（1-20，默认 8）")
    ap.add_argument("--structures", default="", help="显式指定结构，逗号分隔（见模块内 STRUCTURES）")
    ap.add_argument("--seconds", type=int, default=DEFAULT_SECONDS, help="跑多少秒（默认 12）")
    ap.add_argument("--name", default="探针", help="模式名称")
    ap.add_argument("--out", default="probe.ow", help="输出的 .ow")
    ap.add_argument("--expect-out", dest="expect_out", default="", help="输出的 expect.tsv（默认同名）")
    return main_with_args(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
