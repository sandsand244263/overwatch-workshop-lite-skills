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
    "追踪全局变量频率": (1,),
    "追踪玩家变量频率": (1,),
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


def fix_none_args(text):
    """导出写「无」、编辑器要「全部禁用」的位置。返回 (新文本, 修改处数)。"""
    changes = 0

    def make(name, slots):
        def fix_one(m):
            nonlocal changes
            body = m.group(1)
            parts = core._top_level_args(body)
            touched = False
            for s in slots:
                if len(parts) > s and parts[s].strip() == "无":
                    parts[s] = parts[s].replace("无", "全部禁用")
                    touched = True
            if not touched:
                return name + "(" + body + ")"
            changes += 1
            return name + "(" + ",".join(parts) + ")"
        return fix_one

    for name, slots in NO_TO_DISABLED.items():
        pat = r"(?<![\w\u4e00-\u9fa5])" + name + r"\(((?:[^()]|\([^()]*\))*)\)"
        text = re.sub(pat, make(name, slots), text)
    return text, changes


def normalize_text(text):
    joined, merged = join_folded_lines(text.split(chr(10)))
    new_text, none_fixed = fix_none_args(chr(10).join(joined))
    return new_text, merged, none_fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    text = open(a.src, encoding="utf-8-sig", errors="replace").read()
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
