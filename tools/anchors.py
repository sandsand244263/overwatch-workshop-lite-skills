#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数 `check_*` 的 docstring 里有多少条带依据（尺子，只读，不改代码）。

依据的口径（与 PLAN-v17-BA §4 一致）：
  · `E-数字`，且这个编号在 `EVIDENCE.md` 里真有
  · `data/某张表`，且这张表在 `data/` 下真有
两条命中任意一条就算这个 check 带依据；只有文档里随口提到的表不算（文件不存在就不算）。
证据库找不到时直接报错退出，不悄悄放宽（确需降级才加 `--allow-missing-evidence`）。

用法：
  python tools/anchors.py --count              # 只打印数字，比如 27
  python tools/anchors.py --tsv                # 逐条：函数 / 有无依据 / 依据原文 / 行号
  python tools/anchors.py --logic-identical    # 跟 git HEAD 比：遮掉 docstring 后逐字节一致才通过
  python tools/anchors.py --positive-control   # 阳性对照：挖掉 E-68 应掉 1，写回恢复应回原值
  python tools/anchors.py --json               # 机器可读
"""

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHECKS_FILE = os.path.join(HERE, "core.py")
DATA_DIR = os.path.join(ROOT, "data")
EVIDENCE_FILE = os.path.join(os.path.dirname(ROOT), "workshop-lite-re", "EVIDENCE.md")

RE_E = re.compile(r"E-\d+")
RE_DATA = re.compile(r"data/[A-Za-z0-9_.\-]+")

# 阳性对照的靶子：PLAN-v17-BA 指定 check_wait_behaviour 的 E-68
CONTROL_FUNC = "check_wait_behaviour"
CONTROL_TOKEN = "E-68"

ALLOW_MISSING_EVIDENCE = False


class EvidenceMissing(RuntimeError):
    pass


def _read(path):
    with io.open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _evidence_ids():
    """EVIDENCE.md 里真有的 E 编号。

    文件不在就报错 —— 少了证据库，「E 编号是否存在」这半条判据会退化成只校验格式，
    编造的 E 编号也会被算成有依据。确需在没证据库的机器上出数，显式加
    `--allow-missing-evidence`，此时只认 `data/` 表。
    """
    if not os.path.isfile(EVIDENCE_FILE):
        if not ALLOW_MISSING_EVIDENCE:
            raise EvidenceMissing(
                "找不到证据库：%s\n"
                "  没有它就没法判 E 编号真假，拒绝出数。\n"
                "  确实要降级（只认 data/ 表）请加 --allow-missing-evidence。" % EVIDENCE_FILE)
        return None
    return set(RE_E.findall(_read(EVIDENCE_FILE)))


def _check_functions(source):
    """core.py 顶层 def check_* —— 顺序即文件顺序。"""
    tree = ast.parse(source)
    return [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name.startswith("check_")]


def _anchor_of(doc, ev_ids):
    """返回 (有效依据列表, 无效依据列表)。"""
    good, bad = [], []
    for e in sorted(set(RE_E.findall(doc))):
        if ev_ids is None or e in ev_ids:
            good.append(e)
        else:
            bad.append(e + "（EVIDENCE.md 里没有）")
    for d in sorted(set(RE_DATA.findall(doc))):
        fname = d[len("data/"):]
        if os.path.isfile(os.path.join(DATA_DIR, fname)):
            good.append(d)
        else:
            bad.append(d + "（data/ 下没有这个文件）")
    return good, bad


def scan(source=None, ev_ids="auto"):
    """逐条扫描；source 传字符串时扫这份文本。"""
    if source is None:
        source = _read(CHECKS_FILE)
    if ev_ids == "auto":
        ev_ids = _evidence_ids()
    rows = []
    for node in _check_functions(source):
        doc = ast.get_docstring(node) or ""
        good, bad = _anchor_of(doc, ev_ids)
        rows.append({
            "check": node.name,
            "line": node.lineno,
            "anchored": bool(good),
            "anchors": good,
            "invalid": bad,
        })
    return rows


def count(source=None):
    return sum(1 for r in scan(source) if r["anchored"])


# ------------------------------------------------------------ docstring 遮罩

def _docstring_spans(source):
    """每个 docstring 的 (起始行, 结束行)，行号 1 起算。"""
    spans = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            spans.append((first.lineno, first.end_lineno))
    return spans


def _mask_docstrings(source):
    """把 docstring 整段换成一行标记，其余一个字节都不动（行尾统一成 \\n 再比）。"""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for start, end in sorted(_docstring_spans(source), reverse=True):
        raw = lines[start - 1]
        indent = raw[:len(raw) - len(raw.lstrip())]
        lines[start - 1:end] = [indent + "<docstring>"]
    return "\n".join(lines)


def _first_line_diff(a, b):
    la, lb = a.split("\n"), b.split("\n")
    for i in range(min(len(la), len(lb))):
        if la[i] != lb[i]:
            return i + 1, la[i].strip()[:70], lb[i].strip()[:70]
    if len(la) != len(lb):
        return min(len(la), len(lb)) + 1, "（共 %d 行）" % len(la), "（共 %d 行）" % len(lb)
    return None, "", ""


def _changed_functions(head, cur):
    """哪些 check_* 的函数体（docstring 之外）真的变了 —— 只用来写人话提示。"""
    def masked_tree(src):
        tree = ast.parse(src)
        for sub in ast.walk(tree):
            body = getattr(sub, "body", None)
            if not body or not isinstance(sub, (ast.Module, ast.FunctionDef,
                                                ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                body[0] = ast.Expr(value=ast.Constant(value="<docstring>"))
        return tree

    h = {n.name: ast.dump(n) for n in masked_tree(head).body
         if isinstance(n, ast.FunctionDef)}
    c = {n.name: ast.dump(n) for n in masked_tree(cur).body
         if isinstance(n, ast.FunctionDef)}
    return [n for n in h if n in c and h[n] != c[n]]


def _head_source(rel):
    """git HEAD 里的版本；仓库不在或没提交过就返回 None。"""
    try:
        r = subprocess.run(["git", "-C", ROOT, "show", "HEAD:" + rel],
                           capture_output=True)
    except OSError:
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8")


def cmd_logic_identical(rel):
    """遮掉 docstring 后逐字节比对：多一个空格、改一个数字、加一条注释都算不一致。"""
    cur = _read(CHECKS_FILE)
    head = _head_source(rel)
    if head is None:
        print("不通过：拿不到 git HEAD:%s（仓库不在或还没提交）" % rel)
        return 1
    try:
        cur_masked = _mask_docstrings(cur)
    except SyntaxError as exc:
        print("不通过：当前 tools/core.py 解析失败（第 %s 行：%s）—— 先修语法"
              % (exc.lineno, exc.msg))
        return 1
    try:
        head_masked = _mask_docstrings(head)
    except SyntaxError as exc:
        print("不通过：HEAD 版本的 core.py 解析失败（第 %s 行：%s）" % (exc.lineno, exc.msg))
        return 1
    if cur_masked != head_masked:
        line, old, new = _first_line_diff(head_masked, cur_masked)
        print("不通过：除 docstring 外还有改动（遮掉 docstring 后逐字节比对不一致）")
        if line:
            print("  第一处不同在第 %d 行：HEAD「%s」→ 现在「%s」" % (line, old, new))
        for name in _changed_functions(head, cur):
            print("  · %s 的函数体变了" % name)
        return 1
    names = [n.name for n in _check_functions(cur)]
    print("通过：core.py 除 docstring 外与 git HEAD 逐字节一致（%d 个 check_*）"
          % len(names))
    return 0


# ------------------------------------------------------------ 阳性对照

def _mutated_text():
    """把 CONTROL_FUNC 的 docstring 里那一处 CONTROL_TOKEN 换成 E-?；返回 (原文, 改动后)。"""
    src = _read(CHECKS_FILE)
    target = next((n for n in _check_functions(src) if n.name == CONTROL_FUNC), None)
    if target is None:
        raise RuntimeError("%s 不在 core.py 里，阳性对照没有靶子" % CONTROL_FUNC)
    doc = ast.get_docstring(target) or ""
    if CONTROL_TOKEN not in doc:
        raise RuntimeError("%s 的 docstring 里没有 %s，阳性对照没有靶子"
                           % (CONTROL_FUNC, CONTROL_TOKEN))
    lines = src.split("\n")
    for i in range(target.lineno - 1, target.end_lineno):
        if CONTROL_TOKEN in lines[i]:
            lines[i] = lines[i].replace(CONTROL_TOKEN, "E-?")
            return src, "\n".join(lines)
    raise RuntimeError("定位不到 %s 所在行" % CONTROL_TOKEN)


def cmd_positive_control():
    """真写盘 → 数 → 原样写回 → 再数：两侧都读磁盘，不是同一份内存字符串自证。"""
    original, mutated = _mutated_text()
    base = count()
    try:
        with io.open(CHECKS_FILE, "w", encoding="utf-8", newline="") as fh:
            fh.write(mutated)
        after = count()
    finally:
        with io.open(CHECKS_FILE, "w", encoding="utf-8", newline="") as fh:
            fh.write(original)
    restored = count()
    intact = _read(CHECKS_FILE) == original
    ok = (after == base - 1) and (restored == base) and intact
    print("阳性对照：挖掉前 %d，挖掉 %s 后 %d，写回后 %d%s → %s"
          % (base, CONTROL_TOKEN, after, restored,
             "" if intact else "（文件没能原样写回！）",
             "通过（红过又回了）" if ok else "失败"))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="数 check_* 的 docstring 依据（只读）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--count", action="store_true", help="只打印带依据的 check_* 个数")
    g.add_argument("--tsv", action="store_true", help="逐条列出：函数 / 有无依据 / 依据原文 / 行号")
    g.add_argument("--logic-identical", action="store_true", help="跟 git HEAD 比：只许 docstring 变")
    g.add_argument("--positive-control", action="store_true", help="阳性对照：挖掉 E-68 应掉 1")
    g.add_argument("--json", action="store_true", help="机器可读")
    ap.add_argument("--file", default="tools/core.py",
                    help="--logic-identical 比对的文件（相对仓库根）")
    ap.add_argument("--allow-missing-evidence", action="store_true",
                    help="证据库不在时降级为只认 data/ 表（默认拒绝出数）")
    args = ap.parse_args(argv)

    global ALLOW_MISSING_EVIDENCE
    ALLOW_MISSING_EVIDENCE = args.allow_missing_evidence

    try:
        if args.count:
            print(count())
            return 0
        if args.tsv:
            rows = scan()
            print("check\tline\tanchored\tanchors\tinvalid")
            for r in rows:
                print("%s\t%d\t%s\t%s\t%s" % (
                    r["check"], r["line"], "Y" if r["anchored"] else "-",
                    " ".join(r["anchors"]), " ".join(r["invalid"])))
            return 0
        if args.logic_identical:
            return cmd_logic_identical(args.file)
        if args.positive_control:
            return cmd_positive_control()
        if args.json:
            rows = scan()
            print(json.dumps({"total": len(rows),
                              "anchored": sum(1 for r in rows if r["anchored"]),
                              "rows": rows}, ensure_ascii=False, indent=1))
            return 0
    except EvidenceMissing as exc:
        print("失败：%s" % exc)
        return 2
    except RuntimeError as exc:
        print("失败：%s" % exc)
        return 1
    return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
