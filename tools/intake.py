#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""任务路由：把用户的原话映射成「跑什么 / 读什么 / 查什么 / 别做什么」。

为什么要有它：路由表原来只在 SKILL.md 里，靠 agent 每会话读一遍再自己归类——
读到哪行、归对哪类全凭注意力。这里把同一张表变成代码，一次调用出结构化结果。

只做一层映射，不做推理：命中不了就退回「其他」并让你去读 SKILL.md，不许硬猜。

用法：
    python tools/ws.py intake "这个模式导不进去，游戏说缺少分号"
    python tools/ws.py intake --json "帮我做个躲猫猫"
    python tools/ws.py intake --list          # 列出全部类型与关键词
"""
import re
import sys
import json

# 每类：类型 / 关键词（话术里常见的说法）/ 该跑 / 该读 / 该查 / 别做
# 文档路径都相对技能根，且必须在 docs/ 里真实存在（selftest 会对账）
ROUTES = [
    dict(
        key="导不进去",
        kw=["导不进去", "导入失败", "导入不了", "无法导入", "被拒", "拒绝了", "报错了",
            "报错", "提示错误", "游戏说", "缺少分号", "之后应有", "不允许", "invalid"],
        run=["python tools/ws.py locate \"<游戏报错原文>\" --file 模式.ow",
             "python tools/ws.py check 模式.ow"],
        read=["docs/errors.md"],
        query=["ws.py explain <关键词>"],
        avoid=["别猜原因：先拿报错原文走 locate，它会给出模板 + 第几行 + 改法",
               "别把导出文件直接导入（先 fix --fix-bools）"],
    ),
    dict(
        key="能导入但行为不对",
        kw=["行为不对", "不生效", "没反应", "不触发", "没跑", "不跑", "不对头", "效果不对",
            "一直重复", "只执行一次", "循环不", "次数不对", "数值不对", "不动", "不涨",
            "没涨", "不变", "卡住", "无效", "计分", "没效果", "不动了",
            "不显示", "跑了一次", "只跑了一次"],
        run=["python tools/ws.py readlog --expect \"c1=2\"", "python tools/ws.py rule <关键词>"],
        read=["docs/pitfalls-runtime.md", "docs/diagnostics.md"],
        query=["ws.py rule <关键词>（断言表，带证据等级）"],
        avoid=["别靠看屏幕判断：要验的东西必须变成查看器里的一行数字",
               "没有读数的结论不许写进文档"],
    ),
    dict(
        key="写模式",
        kw=["写个", "写一个", "做一个", "做个", "帮我做", "设计一个", "新做一个",
            "小游戏", "玩法实现", "实现这个玩法"],
        run=["python tools/ws.py scaffold --mode <模式> --out 模式.ow",
             "python tools/ws.py check 模式.ow", "python tools/ws.py deliver 模式.ow"],
        read=["docs/patterns.md", "docs/pitfalls.md"],
        query=["ws.py doc <动作>", "ws.py 知道 <名字>"],
        avoid=["别给创意建议：玩法好不好玩由用户判定，技能只管能不能导入、跑得对不对、元素够不够省",
               "别凭记忆写语法：动作签名用 doc 查"],
    ),
    dict(
        key="写动作/语法",
        kw=["怎么写", "写法", "动作怎么写", "函数", "字符串", "变量", "数组", "子程序",
            "参数", "表达式", "语法"],
        run=["python tools/ws.py doc <动作>", "python tools/ws.py check 模式.ow"],
        read=["docs/pitfalls-syntax.md", "docs/syntax.md", "docs/format-spec.md"],
        query=["ws.py 知道 <名字>（六段：身份/参数/能出现在哪/取值/坑/出处）"],
        avoid=["别读 data/ 里的表：那是工具的数据源，用命令查",
               "条件块别写整行 !(A && B)"],
    ),
    dict(
        key="查元素",
        kw=["能出现在哪", "默认值", "有什么坑", "这个元素", "查一下这个", "知道一下",
            "参数是什么", "可选值", "怎么填"],
        run=["python tools/ws.py 知道 <名字>"],
        read=[],
        query=["ws.py doc <动作>", "ws.py defaults <名字>"],
        avoid=["别翻 data/ 表：六段答案都在 知道 这一条命令里"],
    ),
    dict(
        key="地图/时段/模式名",
        kw=["地图", "时段", "釜山", "伊利奥斯", "模式名", "地图池", "换图"],
        run=["python tools/ws.py map-code <地图名>"],
        read=["docs/pitfalls-map.md"],
        query=["ws.py map-code <地图名>"],
        avoid=["别自己拼地图编号：池子里记的写法就是该模式唯一合法写法",
               "别给没进池子的组合（会被判「尚未选择地图」）"],
    ),
    dict(
        key="设置块",
        kw=["设置块", "设置", "键值", "大厅设置", "模式设置", "英雄设置", "选项值", "开启禁用"],
        run=["python tools/ws.py settings --mode <模式>"],
        read=["docs/settings-map.md"],
        query=["ws.py keyinfo <键名>"],
        avoid=["别把键挂错层（模式块的键写进英雄块会被拒）",
               "导出文件里的「禁用/启用」「无」必须先 fix 再导"],
    ),
    dict(
        key="元素快超了",
        kw=["元素", "超了", "上限", "32768", "省元素", "成本", "预算", "太多了", "装不下"],
        run=["python tools/ws.py count 模式.ow"],
        read=["docs/limits.md", "docs/cost-patterns.md"],
        query=["ws.py count 模式.ow"],
        avoid=["别把估算当实测：真实模式偏低 4%~19%，靠近上限按上界判、要求进游戏核对",
               "别赌：超过上界就让用户导入看游戏界面显示的数字"],
    ),
    dict(
        key="要开扩展",
        kw=["扩展", "extension", "英雄池扩展", "无重力", "自定义游戏设置"],
        run=["python tools/ws.py settings --mode <模式>"],
        read=["docs/extensions.md"],
        query=["ws.py keyinfo <扩展名>"],
        avoid=["别一次开一堆扩展：每个都有副作用，逐条记读数"],
    ),
    dict(
        key="导出失真",
        kw=["导出失真", "导出后", "导出文件", "布尔", "值被吞", "乱码", "导出再导入",
            "导出后导入", "导出之后再导入", "导出后再导入", "导出就坏"],
        run=["python tools/ws.py fix 模式.ow --fix-bools", "python tools/ws.py check 模式.ow"],
        read=["docs/pitfalls-export.md"],
        query=["ws.py normalize 模式.ow"],
        avoid=["别手改导出文件：布尔词、下拉「无」这两类会挡导入，用 fix",
               "别把导出产物降成提示级"],
    ),
    dict(
        key="不会导入导出",
        kw=["怎么导入", "怎么导出", "不会用", "新手", "怎么开始", "第一次", "怎么分享",
            "导入到哪里", "在游戏里怎么", "导入到游戏", "导入游戏里", "把文件导入", "怎么装"],
        run=[],
        read=["docs/quickstart.md", "docs/ui-workflow.md"],
        query=[],
        avoid=["别让用户复制粘贴日志：日志用 readlog 自己读"],
    ),
    dict(
        key="加探针/发版",
        kw=["探针", "验证一下", "实测", "发版", "发布", "上线", "tag", "回归"],
        run=["python tools/ws.py verify --scaffold 10 --out 验证.ow",
             "python tools/ws.py devcheck"],
        read=["docs/acceptance-flow.md"],
        query=["ws.py verify", "ws.py rule <关键词>"],
        avoid=["别一条一条问用户验：一次导入验 8~12 条",
               "发版前 devcheck 必须全绿，且把版本号/改动清单/回归数字贴给用户过目"],
    ),
    dict(
        key="改校验器/判断可信度",
        kw=["校验器", "检查规则", "误报", "漏报", "validator", "检查函数", "加了检查",
            "报错太多"],
        run=["python tools/ws.py check-all", "WS_CORPUS=<私有语料> python tools/ws.py corpus",
             "python tools/ws.py devcheck"],
        read=["docs/validator-coverage.md", "docs/pitfalls-export.md"],
        query=["ws.py check --json 文件（看每条的 fix 建议）"],
        avoid=["误报比漏报更伤：加检查先在 8 份真实语料上量，出 3 条误报就撤",
               "B/C 档报错只做翻译，不做判据；检查只许引用 A 档"],
    ),
    dict(
        key="调英雄数值",
        kw=["英雄数值", "生命值", "血量", "冷却", "伤害值", "弹匣", "技能数值", "面板"],
        run=["python tools/ws.py stats <英雄>"],
        read=["docs/hero-stats.md", "docs/hero-quickref.md"],
        query=["ws.py stats <英雄>"],
        avoid=["别凭印象报数值：表里是实测面板，改数值前先查"],
    ),
    dict(
        key="玩法问题",
        kw=["好玩吗", "好不好玩", "怎么设计才好玩", "平衡性", "创意", "点子", "有意思吗",
            "玩家会喜欢", "难度设计", "更有意思", "有意思一点", "怎么设计才好", "会不会太无聊",
            "更好玩", "好玩"],
        run=[],
        read=[],
        query=[],
        avoid=["这类问题技能不掺和：玩法好不好玩由用户判定，agent 只负责把它实现成能导入、跑得对、元素够省",
               "如果用户其实是要实现，请把需求转成「写模式」再走那条路"],
    ),
]

FALLBACK = dict(
    key="其他",
    kw=[],
    run=["python tools/ws.py doctor"],
    read=["SKILL.md", "docs/INDEX.md"],
    query=[],
    avoid=["命中不了就先读 SKILL.md 的路由表，别硬套模板"],
)


def classify(text):
    """按关键词加权打分，返回 (路由, 命中词列表, 得分)。权重＝关键词长度，长词更具体。"""
    best, best_hits, best_score = None, [], 0
    for r in ROUTES:
        hits = [k for k in r["kw"] if k in text]
        score = sum(len(k) for k in hits)
        if score > best_score:
            best, best_hits, best_score = r, hits, score
    if best is None:
        return FALLBACK, [], 0
    return best, best_hits, best_score


def render(r, hits, score):
    out = ["任务类型：%s" % r["key"]]
    out.append("该跑：%s" % ("；".join(r["run"]) if r["run"] else "无（这类不用跑命令）"))
    out.append("该读：%s" % ("、".join(r["read"]) if r["read"] else "无（答案在命令里）"))
    if r["query"]:
        out.append("该查：%s" % "；".join(r["query"]))
    out.append("别做：%s" % "；".join(r["avoid"]))
    if hits:
        out.append("（命中词：%s）" % "、".join(hits))
    return "\n".join(out)


def run(a):
    if getattr(a, "list", False):
        for r in ROUTES + [FALLBACK]:
            print("%-14s %s" % (r["key"], "、".join(r["kw"][:6]) + ("…" if len(r["kw"]) > 6 else "")))
        return 0
    text = " ".join(a.phrases).strip()
    if not text:
        print("给一句用户原话，例如：ws.py intake \"这个模式导不进去\"")
        return 2
    r, hits, score = classify(text)
    if getattr(a, "json", False):
        print(json.dumps({
            "input": text,
            "type": r["key"],
            "run": r["run"],
            "read": r["read"],
            "query": r["query"],
            "avoid": r["avoid"],
            "matched": hits,
            "score": score,
        }, ensure_ascii=False, indent=2))
        return 0
    print(render(r, hits, score))
    return 0


if __name__ == "__main__":
    print("用 python tools/ws.py intake \"<原话>\" 调用", file=sys.stderr)
    sys.exit(2)
