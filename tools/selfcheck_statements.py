#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语句切分器自检（M1 底座）：四条断言，全绿才说明 split_statements 能当底座用。

断言（计划 Task 1.2）：
  1. 逐字节还原：9 份真实语料 + tools/probes/**/*.ow，每个单元切片首尾相接 == 原文
  2. 每个 statement 单元去掉字符串/注释后必须以 `;` 结尾
  3. #17 那种跨行写法（记入查看器(自定义字符串("{0}\\n", 全局.X));）是**一个** statement，
     且 line_start != line_end
  4. 语料里每个 添加至数组(...) 的参数个数与 core._iter_calls 一致

跑法：
  python tools/selfcheck_statements.py [--verbose]
公开仓没有 local_paths.json，语料路径走 WS_CORPUS（默认私有仓那份）。

退出码：全绿 0；任一断言红 1。
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.environ.get("WS_CORPUS") or os.path.join(
    "E:\\工作内容\\11_vibe-coding项目", "workshop-lite-re", "corpus", "real")
PROBES = os.path.join(ROOT, "tools", "probes")
BS = chr(92)          # 反斜杠：不写字面转义，免得 CRLF/heredoc 把它吃掉
NL = chr(10)


def read(p):
    with open(p, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


def files():
    out = []
    if os.path.isdir(CORPUS):
        out += [(p, "corpus") for p in sorted(glob.glob(os.path.join(CORPUS, "*.ow")))]
    out += [(p, "probe") for p in sorted(glob.glob(os.path.join(PROBES, "**", "*.ow"),
                                                   recursive=True))]
    return out


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    if not hasattr(core, "split_statements"):
        print("[1/4] 逐字节还原          ✗ core.split_statements 还不存在"
              "（先写切句器，见计划 Task 1.1）")
        return 1

    bad = []
    n_corpus = n_probe = 0
    n_units = 0
    kinds = {}

    # 1) 逐字节还原
    for path, src in files():
        text = read(path)
        units = core.split_statements(text)
        n_units += len(units)
        for u in units:
            kinds[u["kind"]] = kinds.get(u["kind"], 0) + 1
        joined = "".join(text[u["start"]:u["end"]] for u in units)
        if joined != text:
            # 找第一处偏差，方便定位
            k = 0
            while k < min(len(joined), len(text)) and joined[k] == text[k]:
                k += 1
            bad.append("%s 还原不一致（第 %d 字符起，原 %r / 拼 %r）"
                       % (os.path.basename(path), k,
                          text[k:k + 30], joined[k:k + 30]))
        if src == "corpus":
            n_corpus += 1
        else:
            n_probe += 1
    if n_corpus < 9:
        bad.append("语料只找到 %d 份（应为 9 份，检查 WS_CORPUS）" % n_corpus)
    print("[1/4] 逐字节还原          %s（语料 %d 份 + 探针 %d 份，共 %d 单元）"
          % ("✓" if not bad else "✗", n_corpus, n_probe, n_units))

    # 2) statement 必须以 ; 结尾
    bad2 = []
    for path, _src in files():
        text = read(path)
        for u in core.split_statements(text):
            if u["kind"] != "statement":
                continue
            masked = core.mask_text(text[u["start"]:u["end"]]).strip()
            if not masked.endswith(";"):
                bad2.append("%s:%d %r" % (os.path.basename(path), u["line_start"],
                                          masked[-40:]))
    print("[2/4] statement 收尾 ;    %s（%d 条不合规）"
          % ("✓" if not bad2 else "✗", len(bad2)))

    # 3) #17 那种跨行写法是一个 statement
    sample = (NL.join([
        "设置", "{", "\t最大玩家数: 1", "}", "",
        '规则("切句自检")', "{", "\t动作", "\t{",
        '\t\t记入查看器(自定义字符串("{0}' + NL + '}", 全局.X));',
        "\t}", "}",
    ]) + NL)
    stmts = [u for u in core.split_statements(sample)
             if u["kind"] == "statement" and "记入查看器" in sample[u["start"]:u["end"]]]
    ok3 = (len(stmts) == 1 and stmts[0]["line_start"] != stmts[0]["line_end"])
    if stmts:
        print("[3/4] #17 跨行 = 1 语句   %s（%d 条，行 %d~%d）"
              % ("✓" if ok3 else "✗", len(stmts),
                 stmts[0]["line_start"], stmts[0]["line_end"]))
    else:
        print("[3/4] #17 跨行 = 1 语句   ✗（没切成语句）")

    # 4) 添加至数组 参数个数与 _iter_calls 一致
    bad4 = []
    n_call = 0
    for path in sorted(glob.glob(os.path.join(CORPUS, "*.ow"))):
        text = read(path)
        old = [cnt for _pos, cnt, _args in core._iter_calls(text, "添加至数组")]
        new = []
        for u in core.split_statements(text):
            if u["kind"] != "statement":
                continue
            seg = text[u["start"]:u["end"]]
            for _pos, cnt, _args in core._iter_calls(seg, "添加至数组"):
                new.append(cnt)
        n_call += len(old)
        if old != new:
            bad4.append("%s：旧 %r / 新 %r" % (os.path.basename(path), old, new))
    print("[4/4] 添加至数组 参数一致 %s（%d 处调用）"
          % ("✓" if not bad4 else "✗", n_call))

    if verbose:
        print("\n单元类型分布：%s" % "、".join("%s %d" % (k, v) for k, v in sorted(kinds.items())))
        for label, items in (("还原", bad), ("收尾", bad2), ("参数", bad4)):
            for it in items[:20]:
                print("  [%s] %s" % (label, it))

    fails = (not bad) and (not bad2) and ok3 and (not bad4)
    if fails:
        print("结论：全绿")
        return 0
    for label, items in (("还原", bad), ("收尾", bad2), ("参数", bad4)):
        for it in items[:8]:
            print("  ✗ [%s] %s" % (label, it))
    if not ok3:
        print("  ✗ [#17] 跨行写法没被切成一个 statement")
    print("结论：红（看看上面哪条）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
