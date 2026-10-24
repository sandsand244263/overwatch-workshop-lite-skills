#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把游戏导出的 .ow 文本修成「编辑器能接受」的形式。

导出会失真（已知）：
1. 长语句被折成多行 —— 编辑器按行解析，折行会断句
2. 某些「全部禁用」位置被写成「无」
3. 变量声明可能丢失（无法自动补，只报告）

用法：
    python tools/normalize.py 输入.ow -o 输出.ow [--report]
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core  # noqa: E402

NO_TO_DISABLED = {
    "设置不可见": (1,),
    "追踪全局变量频率": (3,),
    "追踪玩家变量频率": (4,),
    "创建地图文本": (5,),
    "创建HUD文本": (9,),
}
SKIP_BLOCKS = ("变量", "子程序")


def _quote_odd(s):
    n, i, esc = 0, 0, False
    while i < len(s):
        c = s[i]
        if esc:
            esc = False
        elif c == "\\":
            esc = True
        elif c == '"':
            n += 1
        i += 1
    return n % 2 == 1


def _paren_delta(s):
    masked = core.mask_text(core.strip_comments(s))
    return masked.count("(") - masked.count(")")


def _needs_join(line):
    st = line.strip()
    if not st or st.startswith("//") or st.startswith("/*"):
        return False
    if st.endswith((";", "{", "}")):
        return False
    return _quote_odd(line) or _paren_delta(line) > 0 or core._line_continues(line)


def join_folded_lines(lines):
    out, buf, merged, skip = [], None, 0, 0
    for raw in lines:
        st = raw.strip()
        if skip == 0 and st in SKIP_BLOCKS:
            skip = 1
            out.append(raw)
            continue
        if skip:
            if st.endswith("{"):
                skip += 1
            elif st.startswith("}"):
                skip -= 1
            out.append(raw)
            continue
        if buf is None:
            if _needs_join(raw):
                buf = raw
            else:
                out.append(raw)
            continue
        if _quote_odd(buf):
            buf = buf + chr(10) + raw
        else:
            merged += 1
            buf = buf.rstrip() + " " + raw.strip()
        if not _quote_odd(buf) and _paren_delta(buf) <= 0 and not core._line_continues(buf):
            out.append(buf)
            buf = None
    if buf is not None:
        out.append(buf)
    return out, merged


def _iter_calls(text, name):
    """逐个找出 name(...) 的调用：返回 (起点, 括号内起点, 括号内终点, 右括号位置)。"""
    for m in re.finditer(r"(?<![\w\u4e00-\u9fa5])" + re.escape(name) + r"\(", text):
        i = m.end()
        depth = 1
        while i < len(text) and depth:
            c = text[i]
            if c == '"':
                i += 1
                while i < len(text):
                    if text[i] == chr(92):
                        i += 2
                        continue
                    if text[i] == '"':
                        i += 1
                        break
                    i += 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        yield m.start(), m.end(), i - 1


def _no_slots_from_data():
    """从数据里找「选项里有 全部禁用」的参数位：{(函数名, 参数序)} → 排序元组。

    比硬编码表靠谱：导出会在任何 dropdown 槽写「无」，游戏只认「全部禁用」。
    """
    import csv as _csv
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "param-options.tsv")
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        with open(path, encoding="utf-8-sig") as f:
            for row in _csv.DictReader(f, delimiter="\t"):
                elem = (row.get("element") or row.get("元素") or "").strip()
                idx = (row.get("index") or row.get("序号") or "").strip()
                opts = (row.get("options") or row.get("选项") or "")
                if not elem or not idx.isdigit():
                    continue
                if "全部禁用" in opts:
                    out.setdefault(elem, set()).add(int(idx))
    except (OSError, ValueError):
        return out
    return out


def fix_none_args(text):
    """导出写「无」、编辑器要「全部禁用」的位置。返回 (新文本, 修改处数)。

    要点：必须用括号配对找实参，不能靠正则——实参里常有 数组(颜色(...)) 这种嵌套。
    """
    changes = 0
    table = dict(NO_TO_DISABLED)
    for name, idxs in _no_slots_from_data().items():
        table[name] = tuple(sorted(set(table.get(name, ())) | idxs))
    for name, slots in table.items():
        while True:
            hit = None
            for start, body_start, close in _iter_calls(text, name):
                body = text[body_start:close]
                if any("(" in a or ")" in a for a in core._top_level_args(body)):
                    parts = core._top_level_args(body)
                else:
                    parts = core._top_level_args(body)
                changed = False
                for s in slots:
                    if len(parts) > s and parts[s].strip() == "无":
                        parts[s] = parts[s].replace("无", "全部禁用")
                        changed = True
                if changed:
                    hit = (start, body_start, close, ",".join(parts))
                    break
            if not hit:
                break
            s0, b0, c0, new_body = hit
            text = text[:b0] + new_body + text[c0:]
            changes += 1
    return text, changes


def fix_bool_words(text):
    """布尔项里的 禁用/启用/是/否 改成 关闭/开启（词表来自 data/setting-aliases.tsv）。

    实测：目标点决胜机制 / 推进背包 / 尖刺墙 写「禁用」导入失败；
    而 Enum 项（重装职责被动生命值加成）写「禁用」是合法的 —— 所以必须按类型判断，
    并且要尊重别名表里 kind=legal 的例外（那些词在这个键上不许改）。
    """
    types = core.load_setting_types()
    noise, legal = core.load_setting_aliases(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "setting-aliases.tsv"))
    if not noise:
        noise = dict(core.ILLEGAL_BOOL_WORDS)
    changes = 0
    out = []
    for line in text.split(chr(10)):
        st = line.strip()
        m = re.match(r"^([^:：]{1,40})\s*[:：]\s*([^\s]+)\s*$", st)
        if m and types:
            key, val = m.group(1).strip(), m.group(2).strip()
            info = types.get(key)
            if (info and "Bool" in info["type"] and val in noise
                    and (key, val) not in legal):
                newval = noise[val]
                line = line.replace(": " + val, ": " + newval).replace("：" + val, "：" + newval)
                changes += 1
        out.append(line)
    return chr(10).join(out), changes


def normalize_text(text, fix_bools=False, drop_empty=False):
    joined, merged = join_folded_lines(text.split(chr(10)))
    out = chr(10).join(joined)
    out, none_fixed = fix_none_args(out)
    bool_fixed = 0
    if fix_bools:
        out, bool_fixed = fix_bool_words(out)
    if drop_empty:
        keep = []
        for line in out.split(chr(10)):
            st = line.strip()
            if re.match(r"^[^:：]+:\s*$", st) and st not in ("全局:", "玩家:"):
                continue
            keep.append(line)
        out = chr(10).join(keep)
    return out, merged, none_fixed, bool_fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    text, _enc = core.read_text(a.src)
    new_text, merged, none_fixed = normalize_text(text)
    open(a.out, "w", encoding="utf-8", newline=chr(10)).write(new_text)
    print("输入 %d 行 -> 输出 %d 行（合并折行 %d 处，改「无」%d 处）"
          % (len(text.split(chr(10))), len(new_text.split(chr(10))), merged, none_fixed))
    if a.report:
        probs = core.full_lint(a.out, os.path.join(os.path.dirname(HERE), "data"))
        errs = [p for p in probs if p[1] == "error"]
        print("修复后校验：%d error / %d warning" % (len(errs), len(probs) - len(errs)))
        for ln, lv, msg in errs[:8]:
            print("  第 %s 行 %s：%s" % (ln, lv, msg))


if __name__ == "__main__":
    main()
