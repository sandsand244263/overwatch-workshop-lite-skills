# -*- coding: utf-8 -*-
"""从真实语料统计「每个动作/值函数实际写几个参数」，生成 data/arg-counts-from-corpus.tsv。

为什么需要：签名里尾部参数「可以省略」，但引擎不这么认为——
`创建效果(…, 球体, 颜色, 位置, 5)` 5 个参数被游戏拒，语料里同一动作全是 6 个。
统计语料里的实际写法，就能对「比语料还少」的调用出提示。

用法：
  python tools/gen_argcounts.py <语料目录> [--out data/arg-counts-from-corpus.tsv]
只统计出现过的元素，输出：元素 / 最少参数 / 最多参数 / 出现次数 / 最常见参数个数。
"""
import argparse
import collections
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import core  # noqa: E402


def top_level_count(body):
    """数顶层逗号 +1，跳过括号与字符串内部。"""
    if not body.strip():
        return 0
    depth, ins, n = 0, False, 1
    i = 0
    while i < len(body):
        ch = body[i]
        if ins:
            if ch == '"' and body[i - 1] != "\\":
                ins = False
        elif ch == '"':
            ins = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            n += 1
        i += 1
    return n


def scan(text, sigs):
    names = sorted(sigs.keys(), key=len, reverse=True)
    out = collections.defaultdict(list)
    for name in names:
        for m in re.finditer(re.escape(name) + r"\(", text):
            # 前面不能是字母/中文（避免匹配到更长的名字）
            if m.start() > 0 and re.match(r"[\w\u4e00-\u9fa5]", text[m.start() - 1]):
                continue
            depth, j = 0, m.end() - 1
            while j < len(text):
                if text[j] == "(":
                    depth += 1
                elif text[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out[name].append(top_level_count(text[m.end():j]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "arg-counts-from-corpus.tsv"))
    a = ap.parse_args()

    sigs, _labels, _opts = core.load_signatures(os.path.join(ROOT, "data", "signatures.md"))
    total = collections.defaultdict(list)
    files = [f for f in sorted(os.listdir(a.corpus)) if f.endswith(".ow")]
    for fn in files:
        text, _enc = core.read_text(os.path.join(a.corpus, fn))
        text = core.strip_comments(text).replace("\r\n", "\n")
        for name, counts in scan(text, sigs).items():
            total[name].extend(counts)

    rows = []
    for name, counts in total.items():
        c = collections.Counter(counts)
        common, freq = c.most_common(1)[0]
        rows.append((name, min(counts), max(counts), len(counts), common))
    rows.sort(key=lambda r: -r[3])
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["element", "min_args", "max_args", "occurrences", "most_common_args"])
        for r in rows:
            w.writerow(r)
    print("扫了 %d 份语料，%d 个元素有用法，写入 %s" % (len(files), len(rows), a.out))
    # 举几个「语料最少参数 > 签名最少参数」的例子
    print("\n典型（语料里从没少写过）：")
    for name, lo, hi, n, common in rows[:8]:
        print("  %-14s 语料写 %d~%d 个参数，最常见 %d（出现 %d 次）" % (name, lo, hi, common, n))


if __name__ == "__main__":
    main()
