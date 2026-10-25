# -*- coding: utf-8 -*-
"""事实表 ⇄ 校验器 的对账（只读，不改任何数据）。

为什么要有它：同一批知识存在三个地方——`docs/rules.tsv` 的「检查」列、`core.py` 的 71 个
`check_*`、`docs/` 的散文。三处各自演化就会漂：2026-10-25 抓到一次真的（`变量声明` 表里写
「不接」，代码里 `check_var_letter_index` 早就在管）。人肉发现一次是运气，所以放进回归。

「检查」列只允许四种写法（`PLAN-v11-AL` 战役 A1）：
- `不接`                    —— 只写在文档里，校验器不管
- `已接:check_xxx`          —— 由 `core.py` 里那个函数管（必须真有这个 `def`）
- `反例:xxx.ow`            —— 由表驱动提示管，`xxx` 必须等于 `core.RULE_CHECKS` 里的检查名，
                               且 `tools/probes/negative/xxx.ow` 与 `expect.tsv` 那一行都要在
- `已接:未定`               —— 已确认代码在管，但没落到具体函数（单列出来，不算失败）

四类检查（任一失败 → 退出码 1）：
1. 写法/悬空：`已接:check_x` 在 core.py 里没有对应 `def` → 错误
2. 反例：`反例:x.ow` 的文件缺失、或 `expect.tsv` 没这一行 → 错误（否则反向用例静默不跑）
3. 疑似：标着「不接」的行，其「场景+关键词」有 ≥2 个**有区分度**的词命中同一个 check_* 的
   docstring → 疑似「代码其实在管、表没记」（阈值靠文档频率压，太常见的词不算）
4. 反向：71 个 `check_*` 里从没在「检查」列出现过的 → 列为信息（补事实表的候选）

「疑似」命中可以是假阳性（比如 条件块 那条撞上 `check_element_kind`）。复核过的假阳性写进
`tools/rules-audit-ack.tsv`（场景/命中函数/结论/理由/日期），脚本就不再当失败报，只在 `-v`
里列一行——留痕，但不天天吵。

用法：
  python tools/audit_rules.py        一行摘要（devcheck 用）
  python tools/audit_rules.py -v     明细
"""
import collections
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RULES = os.path.join(ROOT, "docs", "rules.tsv")
CORE = os.path.join(HERE, "core.py")
NEG_DIR = os.path.join(HERE, "probes", "negative")
EXPECT = os.path.join(NEG_DIR, "expect.tsv")
ACK = os.path.join(HERE, "rules-audit-ack.tsv")

MAX_DF = 3          # 文档频率上限：出现在超过这么多 docstring 里的词太常见，不算证据
MIN_HITS = 2        # 同一 docstring 里至少命中这么多个「有区分度」的词才算疑似


def _split_tokens(raw):
    """把「检查」列拆成 [tok]（逗号/分号/顿号都认）。"""
    return [t.strip() for t in re.split(r"[,，;；]", raw or "") if t.strip()]


def load_funcs(path=CORE):
    """core.py 里的 check_* -> docstring（首段）。"""
    out = {}
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"def (check_\w+)\(", ln)
        if not m:
            continue
        doc = ""
        for j in range(i + 1, min(i + 8, len(lines))):
            s = lines[j].strip()
            if not s:
                continue
            if s.startswith('"""'):
                doc = s.strip('"').strip()
                if not doc and j + 1 < len(lines):
                    doc = lines[j + 1].strip().strip('"').strip()
            break
        out[m.group(1)] = doc
    return out


def load_rows(path=RULES):
    with open(path, encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f, delimiter="\t") if (r.get("场景") or "").strip()]


def load_expect_files(path=EXPECT):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8-sig") as f:
        return {(r.get("file") or "").strip() for r in csv.DictReader(f, delimiter="\t")}


def load_ack(path=ACK):
    """复核过的假阳性 -> {(场景, 函数): (结论, 理由)}。"""
    out = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            scene = (r.get("场景") or "").strip()
            fn = (r.get("命中函数") or "").strip()
            if scene and fn:
                out[(scene, fn)] = ((r.get("结论") or "").strip(), (r.get("理由") or "").strip())
    return out


def _rule_checks():
    """表驱动提示的检查名（唯一真源在 core.RULE_CHECKS）。"""
    import core
    return set(core.RULE_CHECKS)


def _keywords(row):
    """场景 + 关键词列拆词（两字以上，去掉纯符号）。"""
    raw = (row.get("场景") or "") + " " + (row.get("关键词") or "")
    out = []
    for t in re.split(r"[\s、／/,()（）：:]+", raw):
        t = t.strip()
        if len(t) >= 2 and not all(not ch.isalnum() for ch in t):
            out.append(t)
    return out


def audit(rules_path=RULES, core_path=CORE, neg_dir=NEG_DIR, expect_path=EXPECT, ack_path=ACK):
    rows = load_rows(rules_path)
    funcs = load_funcs(core_path)
    expect = load_expect_files(expect_path)
    ack = load_ack(ack_path)
    known = _rule_checks()

    errors, suspects, infos, undecided = [], [], [], []
    seen_funcs = set()
    seen_neg = set()
    stats = collections.Counter()

    # 1) 写法 + 悬空 + 反例 三类别
    for r in rows:
        scene = (r.get("场景") or "").strip()
        if (r.get("检查") or "").strip() == "":
            errors.append("%s：检查列是空的（要么 不接，要么写清谁在管）" % scene)
            continue
        for tok in _split_tokens(r.get("检查")):
            if tok == "不接":
                stats["不接"] += 1
            elif tok.startswith("已接:"):
                fn = tok[3:].strip()
                stats["已接"] += 1
                if fn == "未定":
                    undecided.append("%s：已接:未定（确认代码在管，但没落到函数名）" % scene)
                    continue
                if fn not in funcs:
                    errors.append("%s：写了 已接:%s，但 core.py 里没有 def %s(" % (scene, fn, fn))
                else:
                    seen_funcs.add(fn)
            elif tok.startswith("反例:"):
                f = tok[3:].strip()
                stats["反例"] += 1
                stem = f[:-3] if f.endswith(".ow") else f
                if not f.endswith(".ow"):
                    errors.append("%s：反例要写文件名（反例:xxx.ow），现在是 反例:%s" % (scene, f))
                elif stem not in known:
                    errors.append("%s：反例:%s 的名字不在表驱动检查里（core.RULE_CHECKS=%s）"
                                  "——文件名就是开关，改名字等于静默关掉提示"
                                  % (scene, f, "/".join(sorted(known))))
                if not os.path.isfile(os.path.join(neg_dir, f)):
                    errors.append("%s：反例:%s 指向的文件不在 tools/probes/negative/" % (scene, f))
                elif expect is not None and f not in expect:
                    errors.append("%s：反例:%s 没有 expect.tsv 那一行 → check-all 不会跑它"
                                  % (scene, f))
                seen_neg.add(f)
            elif tok in ("已接(内建)", "已接"):
                errors.append("%s：旧写法「%s」要落成 已接:<函数名>（落不下来写 已接:未定）"
                              % (scene, tok))
            elif tok.endswith(".ow"):
                errors.append("%s：旧写法「%s」要写成 反例:%s" % (scene, tok, tok))
            else:
                errors.append("%s：「%s」不是合法写法（不接 / 已接:函数名 / 反例:文件名）"
                              % (scene, tok))

    # 2) 每个反例文件都要有 expect 行（没有就静默不跑）
    if expect is not None and os.path.isdir(neg_dir):
        for name in sorted(os.listdir(neg_dir)):
            if name.endswith(".ow") and name not in expect:
                errors.append("tools/probes/negative/%s 没有 expect.tsv 那一行 → check-all 不会跑它"
                              % name)

    # 3) 疑似「代码其实在管、表写不接」
    df = collections.Counter()
    all_toks = set()
    for r in rows:
        all_toks.update(_keywords(r))
    for t in all_toks:
        df[t] = sum(1 for d in funcs.values() if t in d)
    for r in rows:
        if "不接" not in [t for t in _split_tokens(r.get("检查"))]:
            continue
        if len(_split_tokens(r.get("检查"))) > 1:
            continue                      # 同时接了别的检查，不当疑似
        scene = (r.get("场景") or "").strip()
        hits = collections.defaultdict(set)
        for t in set(_keywords(r)):
            if df[t] == 0 or df[t] > MAX_DF:
                continue                  # 没出现 / 太常见
            for fn, doc in funcs.items():
                if t in doc:
                    hits[fn].add(t)
        for fn, toks in sorted(hits.items(), key=lambda kv: -len(kv[1])):
            if len(toks) < MIN_HITS:
                continue
            if (scene, fn) in ack:
                infos.append("已复核（%s）：%s × %s → %s"
                             % (ack[(scene, fn)][0] or "假阳性", scene, fn, ack[(scene, fn)][1]))
            else:
                suspects.append("%s：表写「不接」，但 %s 的说明命中 %s → 疑似已接"
                                % (scene, fn, "、".join(sorted(set(toks)))))

    # 4) 反向：从来没被点名过的 check_*
    unused = [fn for fn in funcs if fn not in seen_funcs]

    return {
        "rows": len(rows), "funcs": len(funcs), "stats": stats,
        "errors": errors, "suspects": suspects, "infos": infos,
        "undecided": undecided, "unused": sorted(unused),
    }


def main(argv):
    verbose = any(a in ("-v", "--verbose") for a in argv[1:])
    res = audit()
    st = res["stats"]
    ok = not res["errors"] and not res["suspects"]
    if verbose:
        for label, key in (("错误", "errors"), ("疑似已接", "suspects"),
                           ("已接:未定", "undecided"), ("已复核", "infos")):
            for line in res[key]:
                print("[%s] %s" % (label, line))
        print("[信息] 没被「检查」列点过名的 check_*：%d 个" % len(res["unused"]))
        if verbose:
            for fn in res["unused"]:
                print("    - %s" % fn)
    tag = "对账" if ok else "对账 ✗"
    print("%s %d 行（不接 %d / 已接 %d / 反例 %d）：错误 %d、疑似 %d、未定 %d、已复核 %d、未点名函数 %d"
          % (tag, res["rows"], st["不接"], st["已接"], st["反例"],
             len(res["errors"]), len(res["suspects"]), len(res["undecided"]),
             len(res["infos"]), len(res["unused"])))
    if not ok:
        print("下一步：python tools/audit_rules.py -v")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
