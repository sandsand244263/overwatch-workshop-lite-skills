#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 workshop_zhCN.json 生成 data/bare-ok.tsv —— 裸词白名单。

为什么要有这张表：`check_unknown_value_names` / `check_bare_functions` 靠它判断
「这个不加括号直接写在代码里的词，游戏认不认」。表以前是人工攒的（707 条），
游戏更新出新词就得人工补 —— 漏一个就把合法写法判红，是漏报的源头之一。

词的来源（全部来自游戏导出，不手抄）：
  1. Actions / Values 参数里 `InferredType == Dropdown` 的槽 —— Dropdowns[Id].Options[].DisplayName
  2. 参数的 DefaultValue.DisplayName（事件玩家 / 所有玩家 / 数字 …）
  3. Extensions[].UnlockedValues[].DisplayName（扩展解锁的光束 / 声音 / 效果名）
名字槽（InferredType 是 Variable / SubroutineThing 之类）一律不收：那是用户自己起的名字。

**新表必须 ⊇ 旧表**：导出里推不出来的那些（数值区间说明、文本选项、0 参数函数名…）
原样留在 `tools/bare-ok-src.tsv`（人工词），生成时合并进来。删词要在这里写清理由。

用法：
    python tools/gen_bare_ok.py --src <导出目录 或 workshop_zhCN.json>   # 写 data/bare-ok.tsv
    python tools/gen_bare_ok.py --check --src <…>                        # 只比对：漂移退出 1
    （源路径也可以用环境变量 WS_EXPORT 给；两者都没有 → 退出 2，devcheck 按「找不到输入」跳过）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, HERE)
import core  # noqa: E402
OUT = os.path.join(DATA, "bare-ok.tsv")
MANUAL = os.path.join(HERE, "bare-ok-src.tsv")

# 用户自己起名字的槽，不能当「合法裸词」——否则任何名字都会被放行
NAME_SLOTS = {"Variable", "SubroutineThing", "VariableOrSubroutine", "Index"}


def src_from_paths():
    """本机装机份的 local_paths.json 里可以写 `"export": "<导出目录>"`；公开仓没有这个文件。"""
    path = os.path.join(ROOT, "local_paths.json")
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("export") or ""
    except Exception:
        return ""


def find_json(src):
    """--src 可以是导出目录，也可以直接是 json 文件。"""
    if not src:
        return ""
    if os.path.isfile(src):
        return src
    cand = os.path.join(src, "workshop_zhCN.json")
    return cand if os.path.isfile(cand) else ""


def load_json(src):
    with open(src, encoding="utf-8") as f:
        return json.load(f)


def load_funcs():
    """签名表：{函数名: 参数个数}。参数个数 > 0 的函数名不能当裸词（`所有玩家` 必须带括号）。"""
    try:
        sigs, _labels, _opts = core.load_signatures(os.path.join(DATA, "signatures.md"))
        return sigs or {}
    except Exception:
        return {}


def derive_words(doc, funcs=None):
    """从导出里推裸词，返回 (词集合, 三类来源各多少)。"""
    funcs = funcs if funcs is not None else load_funcs()
    drop = {}
    for d in doc.get("Dropdowns") or []:
        opts = [o.get("DisplayName") for o in (d.get("Options") or []) if o.get("DisplayName")]
        drop[d.get("Id")] = opts

    words, n_dd, n_def = set(), 0, 0
    for kind in ("Actions", "Values"):
        for elem in doc.get(kind) or []:
            for p in elem.get("Parameters") or []:
                itype = p.get("InferredType") or ""
                if itype in NAME_SLOTS:
                    continue
                did = p.get("DropdownId")
                if did:
                    for w in drop.get(did, []):
                        w = (w or "").strip()      # 导出里有带尾空格的显示名，代码里不会带
                        if not w:
                            continue
                        if w not in words:
                            n_dd += 1
                        words.add(w)
                dv = p.get("DefaultValue")
                if isinstance(dv, dict):
                    name = (dv.get("DisplayName") or "").strip()
                    if name and name not in words:
                        # 默认值名有两种：0 参数的值函数（`事件玩家`，可以裸写）和
                        # 要带参数的函数（`所有玩家` / `数组`）——后一种是函数名，裸写就是错，
                        # 收进来会把「裸写函数名」这条反例放行（check-all 当场红）。
                        if funcs.get(name, 0) > 0:
                            continue
                        words.add(name)
                        n_def += 1

    n_ext = 0
    for e in doc.get("Extensions") or []:
        for uv in e.get("UnlockedValues") or []:
            name = (uv.get("DisplayName") or "").strip()
            if name and name not in words:
                words.add(name)
                n_ext += 1
    return words, {"下拉选项": n_dd, "默认值名": n_def, "扩展解锁": n_ext}


def load_manual():
    """人工词表：第一列是词，第二列是来源说明。"""
    out = {}
    if not os.path.isfile(MANUAL):
        return out
    with open(MANUAL, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.rstrip("\n")
            if not line.strip() or (i == 0 and line.startswith("token")):
                continue
            cols = line.split("\t")
            out[cols[0]] = cols[1] if len(cols) > 1 else ""
    return out


def read_disk():
    if not os.path.isfile(OUT):
        return set()
    with open(OUT, encoding="utf-8") as f:
        rows = [ln.rstrip("\n") for ln in f]
    return {r for r in rows[1:] if r.strip()}


def build(doc):
    derived, stats = derive_words(doc)
    manual = load_manual()
    merged = sorted(derived | set(manual))
    return merged, derived, manual, stats


def main():
    args = sys.argv[1:]
    check = "--check" in args
    src = ""
    for i, a in enumerate(args):
        if a == "--src" and i + 1 < len(args):
            src = args[i + 1]
        elif a.startswith("--src="):
            src = a.split("=", 1)[1]
    if not src:
        src = os.environ.get("WS_EXPORT", "") or src_from_paths()
    path = find_json(src)
    if not path:
        print("找不到输入：%s（用 --src 或 WS_EXPORT 指到导出目录 / workshop_zhCN.json）"
              % (src or "未指定"))
        return 2

    merged, derived, manual, stats = build(load_json(path))
    disk = read_disk()
    added = [w for w in merged if w not in disk]
    removed = [w for w in disk if w not in merged]

    if check:
        if not added and not removed:
            print("无漂移（%d 行）：%s" % (len(merged), os.path.basename(path)))
            return 0
        print("≠ data/bare-ok.tsv 有漂移：新增 %d 条 / 消失 %d 条" % (len(added), len(removed)))
        for w in added[:15]:
            print("   + %s" % w)
        for w in removed[:15]:
            print("   - %s" % w)
        print("  修：python tools/gen_bare_ok.py --src <导出>")
        return 1

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("token\n")
        for w in merged:
            f.write(w + "\n")
    print("写出 %s：%d 条（导出派生 %d：下拉 %d / 默认值 %d / 扩展 %d；人工 %d）"
          % (OUT, len(merged), len(derived), stats["下拉选项"], stats["默认值名"], stats["扩展解锁"],
             len(manual)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
