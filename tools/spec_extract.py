#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从真实语料 + 探针里抽取 `.ow` 的「写法形态」，用来补规范、校准校验器。

为什么不用逆向解决这一层：
    块层级和值格式是**导出器/导入器自己套的壳**，游戏数据表里没有。
    例：settings-page-entries.tsv 只有 section=英雄 / owner=路霸 / page=战斗设置，
    没有「综合」这一层；而 .ow 里必须写成 英雄 { 综合 { 路霸 { … } } }。
    所以这一层只能靠「语料里出现过什么」来定 —— 语料就是规范。

输出：
    data/format-spec-corpus.tsv
        kind     block_parent | setting_value | action_arg
        subject  子块名 / 设置键 / 动作名
        context  父块名 / 值形态 / 参数形态
        count    出现次数
        where    corpus | probes

用法：
    python tools/spec_extract.py                 # 语料 + 探针
    python tools/spec_extract.py --probes-only   # 只扫探针（公开仓也能跑）
"""
import argparse
import collections
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import core          # noqa: E402
import local_paths   # noqa: E402

OUT = os.path.join(SKILL, "data", "format-spec-corpus.tsv")

BOOL_WORDS = {"开启", "关闭", "是", "否", "启用", "禁用", "真", "假"}


def _value_shape(v):
    """一个设置值的「形态」：数字 / 数字+% / 布尔词 / 带引号 / 其他词。"""
    v = v.strip()
    if not v:
        return "空"
    if v.startswith('"'):
        return "带引号字符串"
    try:
        float(v)
        return "数字"
    except ValueError:
        pass
    if v.endswith("%"):
        try:
            float(v[:-1].strip())
            return "数字+%"
        except ValueError:
            pass
    if v in BOOL_WORDS:
        return "布尔词"
    if "(" in v:
        return "表达式"
    return "词"


BOOL_VALUES = {"开启", "关闭", "是", "否", "启用", "禁用", "真", "假"}


def _scan(path, source, block_parent, setting_value, action_arg, bool_seen):
    text, _enc = core.read_text(path)
    stack, pending = [], None
    for line in text.replace("\r\n", "\n").split("\n"):
        s = core.strip_noise(line).strip()
        if not s:
            continue
        if s == "{":
            child = pending or (stack[-1] if stack else None)
            parent = stack[-1] if stack else "顶层"
            # 只记有意义的层级：设置树里的块（规则体里的 事件/动作/条件 不算「块层级」）
            if child and (parent in core.SETTINGS_BLOCKS or parent == "顶层"
                          or parent in ("综合", "队伍1", "队伍2")):
                block_parent[(child, parent, source)] += 1
            stack.append(child)
            pending = None
            continue
        if s.startswith("}"):
            if stack:
                stack.pop()
            pending = None
            continue
        if s.endswith("{"):
            pending = s[:-1].strip()
            continue
        in_settings = any(b in core.SETTINGS_BLOCKS for b in stack)
        if in_settings and (":" in s or "：" in s):
            key, _, val = s.replace("：", ":").partition(":")
            setting_value[(key.strip(), _value_shape(val), source)] += 1
            if val.strip() in BOOL_VALUES:
                bool_seen[(key.strip(), val.strip(), source)] += 1
        if "动作" in stack:
            head = s.split("(", 1)[0].strip()
            if "(" in s and head and " " not in head:
                args = s.split("(", 1)[1]
                shape = "含%" if "%" in args else ("含表达式" if any(c in args for c in "+-*/") else "字面量")
                action_arg[(head, shape, source)] += 1
        if ":" not in s and "：" not in s and "(" not in s:
            pending = s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probes-only", action="store_true", help="只扫探针（公开仓可用）")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--noise", action="store_true", help="跑校验器，统计语料上的提示/报错类别（看误报面）")
    a = ap.parse_args()

    block_parent, setting_value, action_arg, bool_seen = (collections.Counter() for _ in range(4))

    if not a.probes_only:
        corpus = local_paths.corpus_dir()
        files = sorted(glob.glob(os.path.join(corpus, "*.ow"))) if corpus else []
        if not files:
            print("没找到语料：%s" % (local_paths.hint() if not corpus else corpus))
        for p in files:
            _scan(p, "corpus", block_parent, setting_value, action_arg, bool_seen)
        print("语料 %d 个文件" % len(files))

    probes = sorted(glob.glob(os.path.join(SKILL, "tools", "probes", "**", "*.ow"), recursive=True))
    for p in probes:
        _scan(p, "probes", block_parent, setting_value, action_arg, bool_seen)
    print("探针 %d 个文件" % len(probes))

    rows = []
    for (subject, context, source), n in block_parent.items():
        rows.append(("block_parent", subject, context, n, source))
    for (subject, context, source), n in setting_value.items():
        rows.append(("setting_value", subject, context, n, source))
    for (subject, context, source), n in action_arg.items():
        rows.append(("action_arg", subject, context, n, source))
    if a.probes_only:
        print("\n--probes-only：只打印，不写 data/ 下的表（覆盖会把语料派生的数据清空）")
        print("块层级组合 %d 种，值形态 %d 种，动作参数形态 %d 种"
              % (len(block_parent), len(set((k, s) for k, s, _ in setting_value)),
                 len(set((k, s) for k, s, _ in action_arg))))
        return 0

    # 注意：不要用「语料里出现过 禁用」来推断「禁用 合法」。
    # 语料是**导出产物**：导出把布尔项写成显示词（启用/禁用），导入只认 开启/关闭。
    # 详见 docs/settings-map.md 第二节、EVIDENCE.md E-22。

    rows.sort(key=lambda r: (r[0], -r[3]))

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write("kind\tsubject\tcontext\tcount\twhere\n")
        for r in rows:
            f.write("%s\t%s\t%s\t%d\t%s\n" % r)
    print("已写 %s（%d 行）" % (os.path.basename(OUT), len(rows)))

    print("\n=== 块层级 top（同一子块出现在几个父亲下，最值得注意）===")
    by_child = collections.defaultdict(list)
    for (subject, context, source), n in block_parent.items():
        by_child[subject].append((context, n, source))
    multi = [(c, v) for c, v in by_child.items() if len({x[0] for x in v}) > 1]
    for child, parents in sorted(multi, key=lambda kv: -sum(x[1] for x in kv[1]))[:a.top // 2]:
        detail = "，".join("%s×%d(%s)" % (p, n, s) for p, n, s in sorted(parents, key=lambda x: -x[1]))
        print("  %-14s ← %s" % (child, detail))

    print("\n=== 值形态 top ===")
    for (key, shape, source), n in setting_value.most_common(a.top // 2):
        print("  %-22s %-10s ×%d（%s）" % (key, shape, n, source))

    if a.noise:
        noise = collections.Counter()
        samples = {}
        targets = ([] if a.probes_only else sorted(glob.glob(os.path.join(local_paths.corpus_dir() or "", "*.ow"))))
        for p in targets:
            for ln, level, msg in core.full_lint(p, os.path.join(SKILL, "data")):
                head = msg.split("：")[0][:40]
                noise[(level, head)] += 1
                samples.setdefault((level, head), (os.path.basename(p), ln, msg[:90]))
        print("\n=== 语料上的校验器噪声（按类别）===")
        for (level, head), n in noise.most_common(15):
            f, ln, msg = samples[(level, head)]
            print("  %-7s ×%-4d %s" % (level, n, head))
            print("          例：%s:%s %s" % (f, ln, msg))

    print("\n=== 动作参数里出现 % 的动作 ===")
    pct = [((k, s, src), n) for (k, s, src), n in action_arg.items() if s == "含%"]
    for (name, shape, source), n in sorted(pct, key=lambda x: -x[1])[:15]:
        print("  %-24s ×%d（%s）" % (name, n, source))
    return 0


if __name__ == "__main__":
    sys.exit(main())
