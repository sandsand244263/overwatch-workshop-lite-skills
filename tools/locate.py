#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""游戏报错 → 报错模板 → 文件行号 → 改法（主线 A1：报错闭环）。

为什么单开一个模块：报错匹配是纯字符串活，和校验器（core）无关；
校验器只说「我发现的问题」，这里说的是「游戏报的话是什么意思、指向哪一行」。

判据（PLAN v5 A1）：拿真实报错原文跑，每条都能指到正确那一行、并给出改法。
"""
import csv
import os
import re

QUOTES = {
    "“": '"', "”": '"', "「": '"', "」": '"', "『": '"', "』": '"',
    "‘": "'", "’": "'", "｢": '"', "｣": '"',
}


def norm(s):
    """把各种引号、全角空格、连续空白统一，便于模板比对。"""
    s = s.replace("\u00a0", " ").replace("　", " ")
    for a, b in QUOTES.items():
        s = s.replace(a, b)
    s = re.sub(r"\s+", " ", s).strip()
    # 游戏文案里行号是数字；模板里是 %N$s，不动
    return s


def load_templates(data_dir):
    path = os.path.join(data_dir, "errors-full.tsv")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def slot_meta(row):
    """把「1=期望的记号;2=实际写到的记号;3=行号」解析成 {1: '期望的记号', ...}"""
    out = {}
    for part in (row.get("槽位含义") or "").split(";"):
        part = part.strip()
        m = re.match(r"^(\d)\s*=\s*(.+)$", part)
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def tmpl_regex(tmpl):
    """模板 → 正则。%N$s 变成捕获组；同一槽位重复出现时用反向引用保持一致。"""
    out, seen = [], set()
    i = 0
    while i < len(tmpl):
        m = re.match(r"%(\d)\$s", tmpl[i:])
        if m:
            n = int(m.group(1))
            if n in seen:
                out.append("(?P=g%d)" % n)
            else:
                out.append("(?P<g%d>.+?)" % n)
                seen.add(n)
            i += 4
            continue
        out.append(re.escape(tmpl[i]))
        i += 1
    return "".join(out), seen


def skel(s):
    """比对用的骨架：去掉各种引号、去掉「的」——它们不携带信息，却常被抄错抄漏。"""
    s = norm(s)
    for q in "\"'":
        s = s.replace(q, " ")
    s = s.replace("的", "")
    s = re.sub(r"\s+", " ", s).strip()
    if s.startswith("错误："):
        s = s[3:].strip()
    return s


def match_error(text, rows):
    """返回 (row, slots, score) 列表，按可信度排序。

    比对在「骨架」上做：剥掉「错误：」前缀、引号、「的」。
    纯槽位模板（如「错误：%1$s」）是万能兜底，压到最后。
    """
    t = skel(text)
    hits = []
    for row in rows:
        tmpl = (row.get("报错原文") or "").strip()
        if not tmpl:
            continue
        tmpl_n = skel(tmpl)
        if "%" not in tmpl_n:
            literal = len(tmpl_n)
            if tmpl_n == t:
                hits.append((3, row, {}, literal + 200))
            elif tmpl_n and tmpl_n in t:
                hits.append((1, row, {}, literal))
            continue
        rx, _ = tmpl_regex(tmpl_n)
        m = re.fullmatch(rx, t) or re.fullmatch(rx, t.rstrip("。"))
        exact = 1
        if not m:
            m = re.match(rx, t)
            exact = 0
        if not m:
            continue
        slots = {int(k[1:]): v for k, v in m.groupdict().items() if v is not None}
        # 行号槽必须是数字，否则这款模板不算命中
        meta = slot_meta(row)
        bad = False
        for n, meaning in meta.items():
            if "行号" in meaning and n in slots and not re.fullmatch(r"\d+", slots[n].strip()):
                bad = True
        if bad:
            continue
        # 纯槽位模板（「%1$s」这类万能兜底）排到最后，别抢具体模板的位置
        literal = len(re.sub(r"%\d\$s", "", tmpl_n))
        score = literal + (100 if exact else 0) + 10 * len(slots)
        if literal == 0:
            score -= 1000
        hits.append((2 if exact else 1, row, slots, score))
    hits.sort(key=lambda h: (-h[3], h[0]))
    return hits


def line_of(row, slots):
    meta = slot_meta(row)
    for n, meaning in meta.items():
        if "行号" in meaning:
            v = slots.get(n, "")
            if re.fullmatch(r"\d+", v.strip()):
                return int(v.strip())
    return None


def found_token(row, slots):
    """报错里「实际写到的记号」——用来判断行号有没有错位。"""
    meta = slot_meta(row)
    for n, meaning in meta.items():
        if "实际" in meaning or "读到的" in meaning:
            return slots.get(n, "").strip()
    # 槽位含义没写清楚时，取非行号的第一个槽
    for n in sorted(slots):
        if "行号" not in meta.get(n, ""):
            return slots[n].strip()
    return ""


def classify_line(line):
    s = line.strip()
    if not s:
        return "空行"
    if s.startswith("//"):
        return "注释"
    if s == "}" or s == "};":
        return "块尾"
    if "{" in s:
        return "块头"
    if re.search(r"[:：]", s) and not s.startswith("If("):
        return "设置/键值行"
    if s.endswith(";") or s == ";":
        return "语句"
    return "其它"


def local_problems(path, data_dir, strict=False):
    """跑本地校验器，拿它自己报的问题（用于交叉核对）。"""
    sys_path = os.path.dirname(os.path.abspath(__file__))
    import sys
    if sys_path not in sys.path:
        sys.path.insert(0, sys_path)
    import core
    try:
        return core.full_lint(path, data_dir, strict=strict)
    except Exception as e:      # 校验器崩了不能拖垮报错定位
        return [(-1, "error", "本地校验器跑失败：%s" % e)]


def _ctx(lines, center, radius=2):
    lo = max(1, center - radius)
    hi = min(len(lines), center + radius)
    return [(i, lines[i - 1]) for i in range(lo, hi + 1)]


def _next_meaningful(lines, start, stop=8):
    """从 start 往后找第一行有内容的（块头报错的真错常在下一行）。"""
    n = 0
    for i in range(start + 1, min(len(lines), start + stop) + 1):
        s = lines[i - 1].strip()
        if s and not s.startswith("//"):
            return i
        n += 1
    return None


def locate(error_text, data_dir, file_path=None, radius=2, as_json=False):
    rows = load_templates(data_dir)
    hits = match_error(error_text, rows)
    out = {"input": error_text, "matched": bool(hits), "template": None, "file": None}

    if hits:
        row, slots, _score = hits[0][1], hits[0][2], hits[0][3]
        meta = slot_meta(row)
        out["template"] = {
            "id": row.get("编号"), "layer": row.get("层"), "group": row.get("归属"),
            "text": row.get("报错原文"), "slots": {str(k): v for k, v in slots.items()},
            "slot_meanings": {str(k): v for k, v in meta.items()},
            "cause": row.get("真因"), "fix": row.get("改法"),
            "catchable": row.get("能提前报"), "evidence": row.get("证据等级"),
            "others": [{"id": h[1].get("编号"), "text": h[1].get("报错原文")} for h in hits[1:4]],
        }

    if not as_json:
        _print_template(out, hits)

    if file_path:
        loc = _locate_in_file(file_path, data_dir, error_text, hits, radius)
        out["file"] = loc
        if not as_json:
            _print_file(loc, radius)

    if as_json:
        import json
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if hits else 2


def _print_template(out, hits):
    t = out["template"]
    if not t:
        print("没有命中任何报错模板。原文：%s" % out["input"])
        print("（先用 `ws.py explain <关键词>` 模糊搜；命中不了说明这条不在 136 条全集里，"
              "按 docs/errors.md 的两步法人工判断）")
        return
    print("命中模板 %s（层 %s · %s）" % (t["id"], t["layer"], t["group"]))
    print("  原文  %s" % t["text"])
    if t["slots"]:
        parts = []
        for k in sorted(t["slots"], key=lambda x: int(x)):
            parts.append("%s=%s" % (t["slot_meanings"].get(k, "槽" + k), t["slots"][k]))
        print("  槽值  " + " · ".join(parts))
    print("  真因  %s" % (t["cause"] or "—"))
    print("  改法  %s" % (t["fix"] or "—"))
    print("  拦没拦住  本地能提前报 = %s（证据 %s）" % (t["catchable"] or "?", t["evidence"] or "?"))
    if t["others"]:
        print("  别的候选  " + "；".join("%s %s" % (o["id"], o["text"]) for o in t["others"]))


def _locate_in_file(path, data_dir, error_text, hits, radius):
    res = {"path": path, "line": None, "adjusted": None, "context": [], "kind": None,
           "anchor": None, "anchor_context": [], "local": [], "note": ""}
    row = slots = None
    if hits:
        row, slots = hits[0][1], hits[0][2]
        n = line_of(row, slots)
    else:
        m = re.search(r"第\s*(\d+)\s*行", norm(error_text))
        n = int(m.group(1)) if m else None
        res["note"] = "没命中模板，只按报错里的行号硬指"
    if n is None:
        res["note"] = (res["note"] + "；" if res["note"] else "") + \
            "这条报错不带行号，只能给改法，指不了行"
        return res
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().split("\n")
    except OSError as e:
        res["note"] = "读不到文件：%s" % e
        return res
    res["line"] = n
    res["total_lines"] = len(lines)
    if n < 1 or n > len(lines):
        res["note"] = "报错行号 %d 超出文件行数 %d —— 你导入的不是这个文件，或文件改过" % (n, len(lines))
        res["line"] = None
        return res
    token = found_token(row, slots) if row else ""
    # 报错里的「实际写到的记号」一般就在报错行上；找不到说明两种情况：
    #   ① 文件在导入后被改过（行号漂了）② 记号是跨行写的（块头名字 + 下一行的 {）
    # 两种都只记下来提示，不擅自改指向 —— 游戏报的行号本身就是「解析卡住的那一行」。
    if token and token[:6] and token[:6] not in lines[n - 1]:
        for d in range(1, 13):
            for cand in (n - d, n + d):
                if 1 <= cand <= len(lines) and token[:6] in lines[cand - 1]:
                    res["token_at"] = cand
                    break
            if res.get("token_at"):
                break
        if not res.get("token_at"):
            name = re.split(r"[{(,:：\s]", token)[0]
            if name and len(name) >= 2:
                for d in range(0, 13):
                    for cand in (n - d, n + d):
                        if 1 <= cand <= len(lines) and name in lines[cand - 1]:
                            res["token_at"] = cand
                            res["token_split"] = True
                            break
                    if res.get("token_at"):
                        break
    anchor = n
    res["anchor"] = anchor
    res["kind"] = classify_line(lines[anchor - 1])
    res["context"] = _ctx(lines, anchor, radius)
    # 只有「报错停在块头上」这类才往后找一行：游戏读到块头就要求键，
    # 报错行是块头时，真错在下一个有内容的行；报错行本身是键值行时，错就在这一行。
    tmpl_text = (row.get("报错原文") or "") if row else error_text
    if res["kind"] == "块头" or (res["kind"] in ("空行", "块尾") and "设置" in tmpl_text):
        cands = []
        for i in range(anchor + 1, min(len(lines), anchor + 8) + 1):
            s = lines[i - 1].strip()
            if not s or s.startswith("//"):
                continue
            cands.append((i, lines[i - 1]))
            if len(cands) >= 3:
                break
        if cands:
            res["block_candidates"] = cands
    probs = local_problems(path, data_dir)
    near = [p for p in probs if p[0] and abs(p[0] - anchor) <= 3]
    res["local"] = [{"line": p[0], "level": p[1], "message": p[2]} for p in near]
    res["local_total"] = len(probs)
    return res


def _print_file(loc, radius):
    print("")
    if loc.get("note"):
        print("  ⚠ " + loc["note"])
        if not loc.get("line"):
            return
    n = loc["line"]
    print("文件定位：%s 第 %d 行（共 %d 行）" % (os.path.basename(loc["path"]), n, loc["total_lines"]))
    if loc.get("token_at"):
        if loc.get("token_split"):
            print("  · 报错里那段文字是跨行写的，名字起始在第 %d 行（游戏按合并后的行报" % loc["token_at"]
                  + "）")
        else:
            print("  ⚠ 报错里那段文字其实在第 %d 行 —— 文件在导入后被改过？先按这一行核对" % loc["token_at"])
    anchor = loc["anchor"]
    for i, text in loc["context"]:
        mark = ">" if i == anchor else " "
        print("  %s %4d | %s" % (mark, i, text[:160]))
    if loc.get("block_candidates"):
        print("  ↓ 报错停在块头上：真错在块里第一个不被接受的键，就在下面几行里挑：")
        for i, text in loc["block_candidates"]:
            print("      %4d | %s" % (i, (text or "").strip()[:160]))
    if loc["local"]:
        print("  本地校验器也报了同一处：")
        for p in loc["local"]:
            print("      第 %s 行 [%s] %s" % (p["line"], p["level"], p["message"]))
    else:
        print("  本地校验器这一处没报（这类报错本地拦不住，占 73%）——按上面的真因人工核对该行及下一行")
