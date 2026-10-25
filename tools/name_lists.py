# -*- coding: utf-8 -*-
"""名单 ⇄ 元素表 的自动差集（v16 战役 B）。

为什么要这个东西：`check_var_slot_bare` 的动作名是手抄的，漏了 4 个名字，
结果整族写法放行、游戏直接拒导入（E-90，踩过两次）。名单靠人抄就一定会再漏。

做法：
1. 用 AST 从 `core.py` 里把「字面量名字集合」全抓出来（模块级常量 + 函数内局部变量）。
2. `tools/name-list-scopes.tsv` 里登记「哪处清单对应哪张表的哪个子族」。
3. 差集非空就报；「故意不收」的名字逐行写进 `tools/name-list-whitelist.tsv`（带理由与依据）。
4. 没登记、但一眼是「表里名字」的清单 → 也算失败：逼下一个人登记或改成查表。

跑法：`python tools/ws.py selftest`（会调本模块）。也可以单独跑 `python tools/name_lists.py`。
"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
SCOPES = os.path.join(HERE, "name-list-scopes.tsv")
WHITELIST = os.path.join(HERE, "name-list-whitelist.tsv")

_CJK = re.compile(r"[\u4e00-\u9fa5]")


# ---------------------------------------------------------------- 表
def _read_tsv(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        head = None
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            cols = line.split("\t")
            if head is None:
                head = cols
                continue
            rows.append(dict(zip(head, cols)))
    return rows


def table_names(table, family=None):
    """返回 (名字集合, 名字->族)。族过滤在调用方用 regex。"""
    path = os.path.join(DATA, table)
    names = {}
    if not os.path.isfile(path):
        return set(), names
    if table == "element-kinds.tsv":
        for r in _read_tsv(path):
            names[r.get("name", "")] = r.get("kind", "")
    elif table == "mode-list.tsv":
        for r in _read_tsv(path):
            ow = (r.get("ow_name") or "").strip()
            if ow:
                names[ow] = r.get("base", "")
    elif table == "settings.tsv":
        for r in _read_tsv(path):
            k = (r.get("key") or r.get("name") or "").strip()
            if k:
                names[k] = r.get("layer", "")
    elif table == "heroes.tsv" or table == "maps.tsv":
        for r in _read_tsv(path):
            v = (r.get("name") or list(r.values())[0] or "").strip()
            if v:
                names[v] = ""
    return set(names), names


# ---------------------------------------------------------------- 扫代码
def _strs(node):
    out = []
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append(n.value)
    return out


def scan_code(path=None):
    """返回 [(label, lineno, {名字})]，label 形如 `MIN_ARGS` / `check_x.names` / `check_x#2`。"""
    _seen = set()   # (行号, 名字集合) 去重：`x = (...)` 会同时命中赋值节点和字面量节点
    path = path or os.path.join(HERE, "core.py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    found = []

    def consider(label, node, line):
        vals = {v for v in _strs(node) if v and _CJK.search(v) and len(v) <= 24}
        # 只有「几乎全是名字」的集合才算：至少 3 个，且没有句子（含空格/冒号/逗号的长串）
        vals = {v for v in vals if not re.search(r"[：，,。；;！!？?\s]", v)}
        key = (line, frozenset(vals))
        if len(vals) >= 2 and key not in _seen:
            _seen.add(key)
            found.append((label, line, vals))

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consider(t.id, node.value, node.lineno)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            consider(node.target.id, node.value, node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = node.name
            i = 0
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assign) and len(sub.targets) == 1 and isinstance(sub.targets[0], ast.Name):
                    consider("%s.%s" % (fn, sub.targets[0].id), sub.value, sub.lineno)
                elif isinstance(sub, (ast.Set, ast.List, ast.Tuple)):
                    consider("%s#%d" % (fn, i), sub, sub.lineno)
                    i += 1
    return found


# ---------------------------------------------------------------- 比
def _family_filter(names_map, regex):
    if not regex or regex == "-":
        return set(names_map)
    pat = re.compile(regex)
    return {n for n in names_map if pat.search(n)}


def _whitelist():
    wl = {}
    for r in _read_tsv(WHITELIST):
        wl.setdefault((r.get("check", ""), r.get("name", "*")), r)
    return wl


def _run_scopes(code):
    """只按 scope 表比差集。返回 (失败列表, 已登记标签集合)。"""
    scopes = _read_tsv(SCOPES)
    wl = _whitelist()
    fails, registered = [], set()
    for sc in scopes:
        check_name, var = sc.get("check", ""), sc.get("var", "")
        labels = [v.strip() for v in var.split(",") if v.strip()]
        hard, line = set(), 0
        for lb in labels:
            registered.add(lb)
            if lb in code:
                line = line or code[lb][0]
                hard |= code[lb][1]
            else:
                fails.append("%s：登记的清单 %s 在 core.py 里找不到（改了名要同步 %s）"
                             % (check_name, lb, os.path.basename(SCOPES)))
        _, tmap = table_names(sc.get("table", ""))
        fam = _family_filter(tmap, sc.get("filter"))
        if not fam:
            fails.append("%s：表 %s 用过滤条件 %s 取不到任何名字（过滤写坏了？）"
                         % (check_name, sc.get("table"), sc.get("filter")))
            continue
        if sc.get("semantics", "exact") == "coverage":
            def _norm(x):
                return re.sub(r"[（）()\s]", "", x)
            nfam = {m: _norm(m) for m in fam}
            nhard = [_norm(h) for h in hard]
            missing = {m for m, nm in nfam.items() if not any(nm.startswith(h) for h in nhard)}
            extra = {h for h, nh in zip(hard, nhard)
                     if not any(nm.startswith(nh) for nm in nfam.values())}
        else:
            missing, extra = fam - hard, hard - fam
        for name in sorted(missing):
            if (check_name, name) in wl or (check_name, "*") in wl:
                continue
            fails.append("%s：表里有、代码里没有「%s」（清单 %s，第 %d 行）—— 漏名 = 该报没报"
                         % (check_name, name, var, line))
        for name in sorted(extra):
            if (check_name, name) in wl or (check_name, "*") in wl:
                continue
            fails.append("%s：代码里有、表里没有「%s」（清单 %s，第 %d 行）—— 疑似拼错或已废弃"
                         % (check_name, name, var, line))
    return fails, registered


def self_control(code):
    """阳性对照：把「设置全局变量」从 specs 挖掉，差集必须报出来（E-90 的原位回归）。

    没有这条对照，「差集 0 条」和「扫描器坏了」看起来一模一样。
    """
    label, expected = "check_var_slot_bare.specs", "设置全局变量"
    if label not in code:
        return "阳性对照失败：找不到清单 %s，扫描器坏了（不是「名单齐了」）" % label
    line, vals = code[label]
    if expected not in vals:
        return "阳性对照失败：%s 里本来就没有「%s」，对照失效" % (label, expected)
    doctored = dict(code)
    doctored[label] = (line, vals - {expected})
    fails, _ = _run_scopes(doctored)
    if not any(expected in f for f in fails):
        return "阳性对照失败：挖掉「%s」后差集没报（比对逻辑坏了）" % expected
    return None


def check(verbose=False):
    """返回 (失败列表, 概要行)。失败列表为空 = 通过。"""
    code = {label: (line, vals) for (label, line, vals) in scan_code()}
    fails, registered = _run_scopes(code)

    # 未登记的清单：一眼看出是「表里的名字」就要求登记，否则以后又会多出一份手抄名单
    _, ek = table_names("element-kinds.tsv")
    _, hz = table_names("heroes.tsv")
    known = set(ek) | set(hz)
    wl = _whitelist()
    for label, (line, vals) in code.items():
        if label in registered:
            continue
        hit = vals & known
        if len(hit) >= 3:
            if ("*", label) in wl or ("*", "*") in wl:
                continue
            fails.append("清单 %s（第 %d 行）没在 %s 里登记：含 %d 个表里的名字（如 %s）——"
                         "登记它，或改成查表"
                         % (label, line, os.path.basename(SCOPES), len(hit),
                            "、".join(sorted(hit)[:3])))

    ctl = self_control(code)
    if ctl:
        fails.append(ctl)
    summary = ("名单差集：登记 %d 处，扫到清单 %d 处，白名单 %d 行"
               % (len(_read_tsv(SCOPES)), len(code), len(_whitelist())))
    return fails, summary


if __name__ == "__main__":
    fails, summary = check()
    print(summary)
    for f in fails:
        print("✗", f)
    print("结论：%s" % ("通过" if not fails else "失败 %d 条" % len(fails)))
    sys.exit(1 if fails else 0)
