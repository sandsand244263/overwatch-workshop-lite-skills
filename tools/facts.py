# -*- coding: utf-8 -*-
"""断言表的验证闭环：列出待验、回填等级、生成批量验证探针。

设计口径（2026-10-24）：
- 表里每条断言带证据等级 L0~L3，只有 L2/L3 能当结论说
- 一次导入验 8~12 条，靠 readlog 自动读读数 —— 人力只花在"导入"上
- 没验过的条目在 ws.py rule 里会显式标「未完全验证」

命令（由 ws.py verify 转调）：
  ws.py verify                      列出还没验到 L3 的条目
  ws.py verify 关键词                看某条 + 怎么验
  ws.py verify --stale 30           超过 30 天没复核的 L3
  ws.py verify --set 关键词 --level L3 --evidence E-54
  ws.py verify --scaffold 10 --out X.ow   生成 10 格验证探针骨架
"""
import datetime
import os

import rules

SKELETON_SETTINGS = """设置
{
\t模式
\t{
\t\t死斗
\t\t{
\t\t\t启用地图
\t\t\t{
\t\t\t\t地图工坊室内
\t\t\t}
\t\t}
\t\t综合
\t\t{
\t\t\t游戏模式开始: 即时
\t\t\t随机英雄复生: 开启
\t\t}
\t}
}

变量
{
\t全局:
\t\t0: t
}

规则("隐蔽")
{
\t事件
\t{
\t\t持续 - 每名玩家;
\t\t双方;
\t\t全部;
\t}

\t动作
\t{
\t\tWhile(真);
\t\t隐藏英雄HUD(事件玩家);
\t\t隐藏游戏模式HUD(事件玩家);
\t\t开始镜头(事件玩家, 矢量(0, 50, 0), 矢量(0, 200, 0), 100);
\t\t等待(0.5, 无视条件);
\t\tEnd;
\t}
}

规则("打点")
{
\t事件
\t{
\t\t持续 - 全局;
\t}

\t动作
\t{
\t\t等待直到(游戏正在进行中() == 真, 60);
\t\tWhile(真);
\t\t等待(1, 无视条件);
\t\t全局.t = 全局.t + 1;
\t\t记入查看器(自定义字符串("[{0}s] 格 t={1}", 全局.t, 全局.t));
\t\tIf(全局.t >= 12);
\t\t中断;
\t\tEnd;
\t\tEnd;
\t}
}
"""


def _today():
    return datetime.date.today().isoformat()


def _days_since(s):
    try:
        d = datetime.date.fromisoformat(s.strip())
    except Exception:
        return None
    return (datetime.date.today() - d).days


def todo(rows):
    return [r for r in rows if r.get("证据", "") not in ("L2", "L3")]


def run(args):
    rows = rules.load()
    if not rows:
        print("断言表读不到：%s" % rules.DEFAULT)
        return 2

    if getattr(args, "set", None):
        return _do_set(rows, args)

    if getattr(args, "stale", None):
        n = int(args.stale)
        old = [(r, _days_since(r.get("验期", ""))) for r in rows if r.get("证据") in ("L2", "L3")]
        old = [(r, d) for r, d in old if d is None or d >= n]
        if not old:
            print("没有超过 %d 天没复核的已验条目。" % n)
            return 0
        print("超过 %d 天没复核（%d 条）：" % (n, len(old)))
        for r, d in old:
            print("  %-22s %s  %s" % (r["场景"], r["证据"], "从未标日期" if d is None else "%d 天前" % d))
        return 0

    if getattr(args, "scaffold", None):
        return _do_scaffold(rows, args)

    q = getattr(args, "query", None) or ""
    if isinstance(q, (list, tuple)):
        q = " ".join(q)
    q = q.strip()
    if q:
        hits = rules.search(rows, q)
        if not hits:
            print("没查到「%s」。" % q)
            return 1
        for i, r in enumerate(hits):
            if i:
                print("")
            print(rules.render(r))
        return 0

    rest = todo(rows)
    if not rest:
        print("全部 %d 条都已验到 L2/L3。" % len(rows))
        return 0
    print("还没验到 L2/L3 的 %d 条（共 %d 条）：" % (len(rest), len(rows)))
    for r in rest:
        print("  [%s] %-22s 怎么验：%s" % (r["证据"], r["场景"], r.get("怎么验") or "待写"))
    print("\n验完回填：ws.py verify --set <场景关键词> --level L3 --evidence E-54")
    print("一次验多条：ws.py verify --scaffold %d --out 验证.ow" % min(12, max(8, len(rest))))
    return 0


def _do_set(rows, args):
    key = args.set
    hits = rules.search(rows, key)
    if not hits:
        print("表里没有匹配「%s」的条目。" % key)
        return 1
    if len(hits) > 1:
        print("「%s」匹配到 %d 条，请说得更具体：" % (key, len(hits)))
        for r in hits:
            print("  " + r["场景"])
        return 1
    r = hits[0]
    before = (r.get("证据"), r.get("依据"), r.get("验期"))
    if args.level:
        r["证据"] = args.level.upper()
    if args.evidence:
        r["依据"] = args.evidence
    r["验期"] = args.date or _today()
    rules.save(rows)
    print("已回填：%s" % r["场景"])
    print("  证据：%s → %s" % (before[0], r["证据"]))
    print("  依据：%s → %s" % (before[1], r["依据"]))
    print("  验期：%s → %s" % (before[2], r["验期"]))
    return 0


def _do_scaffold(rows, args):
    n = int(args.scaffold)
    out = args.out or "verify_probe.ow"
    rest = todo(rows)[:n]
    parts = [SKELETON_SETTINGS]
    for i, r in enumerate(rest, 1):
        parts.append(
            '规则("格%02d %s")\n{\n\t事件\n\t{\n\t\t持续 - 全局;\n\t}\n\n'
            '\t动作\n\t{\n\t\t// 断言：%s\n\t\t// 怎么验：%s\n\t\t// 把这条断言写成一行读数，例如：\n'
            '\t\t// 记入查看器(自定义字符串("[格%02d] 键=值"));\n\t}\n}\n'
            % (i, r["场景"], r["场景"], r.get("怎么验") or "待写", i))
    text = "\n".join(parts)
    with open(out, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(text)
    print("已生成 %s：%d 个空格子（骨架 + 隐蔽 + 打点已就绪）" % (out, len(rest)))
    print("下一步：把每个格子的断言写成一行读数，跑 ws.py check，再交给用户导入一次")
    for i, r in enumerate(rest, 1):
        print("  格%02d  %s" % (i, r["场景"]))
    return 0
