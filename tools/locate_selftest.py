#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报错定位回归：拿写死的用例跑（用例和样例文件都在 tools/probes/lab/locate/）。

判据来自 PLAN v5 A1：每条真实报错都能指到正确那一行、并给出改法。
用例表列 = 名称 / 报错原文 / 期望模板 / 期望行（数字 / 越界 / 无行号）/ 说明
"""
import csv
import os


def _paths():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    lab = os.path.join(root, "tools", "probes", "lab", "locate")
    return os.path.join(root, "data"), os.path.join(lab, "cases.tsv"), os.path.join(lab, "sample.ow")


def selftest_check():
    import locate
    data_dir, cases_path, sample = _paths()
    if not (os.path.isfile(cases_path) and os.path.isfile(sample)):
        return ["用例或样例文件缺失：%s" % cases_path], "报错定位回归：跳过（缺用例文件）"
    rows = locate.load_templates(data_dir)
    with open(cases_path, encoding="utf-8-sig") as f:
        cases = list(csv.DictReader(f, delimiter="\t"))
    with open(sample, encoding="utf-8-sig") as f:
        n_lines = len(f.read().split("\n"))

    problems = []
    for c in cases:
        name = (c.get("名称") or "").strip()
        text = (c.get("报错原文") or "").strip()
        want_t = (c.get("期望模板") or "").strip()
        want_l = (c.get("期望行") or "").strip()
        hits = locate.match_error(text, rows)
        got_t = hits[0][1].get("编号") if hits else None
        if got_t != want_t:
            problems.append("%s：模板期望 %s，实际 %s" % (name, want_t, got_t))
            continue
        if not want_l:
            continue
        loc = locate._locate_in_file(sample, data_dir, text, hits, 2)
        if want_l == "无行号":
            if loc.get("line") is not None:
                problems.append("%s：这条不该有行号，实际指到第 %s 行" % (name, loc["line"]))
        elif want_l == "越界":
            if loc.get("line") is not None:
                problems.append("%s：应当判越界（文件 %d 行），实际指到第 %s 行"
                                % (name, n_lines, loc["line"]))
            elif "超出" not in (loc.get("note") or ""):
                problems.append("%s：越界没被识别，提示是「%s」" % (name, loc.get("note")))
        else:
            if loc.get("line") != int(want_l):
                problems.append("%s：期望行 %s，实际 %s（%s）"
                                % (name, want_l, loc.get("line"), loc.get("note") or ""))
    if problems:
        return problems, "报错定位回归失败 %d / %d 条" % (len(problems), len(cases))
    return [], "报错定位回归：%d 条用例全部通过" % len(cases)
