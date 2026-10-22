#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两个导出目录的全量对照：动作 / 值函数 / 参数 / 下拉选项 / 字符串 / 英雄 / 地图。

用法：python tools/ws.py diff --prev 导出目录/export-旧 --cur 导出目录/export-新

有任何差异就以退出码 1 结束，方便挂进更新流程。
"""
import json
import os
import sys


def load(d, name):
    p = os.path.join(d, name)
    if not os.path.isfile(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def fn_map(ws, key):
    return {(e.get("DisplayName") or "").strip(): e for e in (ws.get(key) or []) if e.get("DisplayName")}


def params_of(entry):
    out = []
    for p in entry.get("Parameters") or []:
        out.append((p.get("Name") or "", p.get("InputType") or p.get("InferredType") or "",
                    p.get("DropdownId") or ""))
    return out


def cmp_names(label, old, new, out):
    add = sorted(set(new) - set(old))
    rem = sorted(set(old) - set(new))
    if add:
        out.append("  + %s 新增 %d：%s" % (label, len(add), "、".join(add[:12])))
    if rem:
        out.append("  - %s 移除 %d：%s" % (label, len(rem), "、".join(rem[:12])))


def cmp_params(label, old, new, out):
    changed = 0
    for name in sorted(set(old) & set(new)):
        po, pn = params_of(old[name]), params_of(new[name])
        if po != pn:
            changed += 1
            if changed <= 8:
                out.append("  ~ %s %s 参数变了\n      旧 %s\n      新 %s" % (label, name, po, pn))
    if changed:
        out.append("  ~ %s 共有 %d 个函数参数有变化" % (label, changed))


def cmp_dropdowns(ws_old, ws_new, out):
    def mapping(ws):
        return {d.get("Id"): [o.get("DisplayName") for o in (d.get("Options") or [])]
                for d in (ws.get("Dropdowns") or [])}
    om, nm = mapping(ws_old), mapping(ws_new)
    changed = 0
    for did in sorted(set(om) | set(nm)):
        if om.get(did) != nm.get(did):
            changed += 1
            if changed <= 8:
                out.append("  ~ 下拉 %s 选项变了：旧 %s → 新 %s" % (did, om.get(did), nm.get(did)))
    if changed:
        out.append("  ~ 下拉选项共 %d 处变化" % changed)


def cmp_list(label, old_list, new_list, out):
    add = sorted(set(new_list) - set(old_list))
    rem = sorted(set(old_list) - set(new_list))
    if add:
        out.append("  + %s 新增 %d：%s" % (label, len(add), "、".join(add[:15])))
    if rem:
        out.append("  - %s 移除 %d：%s" % (label, len(rem), "、".join(rem[:15])))


def main_with_args(args):
    out = []
    wso, wsn = load(args.prev, "workshop_zhCN.json"), load(args.cur, "workshop_zhCN.json")
    if not wso or not wsn:
        print("[错误] 两边都要有 workshop_zhCN.json")
        return 2

    for key, label in (("Actions", "动作"), ("Values", "值函数")):
        old, new = fn_map(wso, key), fn_map(wsn, key)
        out.append("%s：旧 %d / 新 %d" % (label, len(old), len(new)))
        cmp_names(label, old, new, out)
        cmp_params(label, old, new, out)

    cmp_dropdowns(wso, wsn, out)

    cmp_list("字符串", [s if isinstance(s, str) else (s.get("DisplayName") or "")
                     for s in (wso.get("TextOptions") or [])],
             [s if isinstance(s, str) else (s.get("DisplayName") or "")
              for s in (wsn.get("TextOptions") or [])], out)

    ho, hn = load(args.prev, "heroes.json"), load(args.cur, "heroes.json")
    if ho and hn:
        def hn_names(h):
            v = h.values() if isinstance(h, dict) else h
            return [x.get("Name") for x in v if x.get("IsHero") and x.get("Name")]
        cmp_list("英雄", hn_names(ho), hn_names(hn), out)

    mo, mn = load(args.prev, "maps.json"), load(args.cur, "maps.json")
    if mo and mn:
        def map_names(m):
            v = m.values() if isinstance(m, dict) else m
            return [x.get("Name") for x in v if x.get("Name")]
        cmp_list("地图", map_names(mo), map_names(mn), out)

    changed = any(x.startswith(("  +", "  -", "  ~")) for x in out)
    print("\n".join(out))
    print("\n结论：%s" % ("有变化，需要人工确认" if changed else "无任何差异"))
    return 1 if changed else 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and not sys.argv[1].startswith("-"):
        _prev, _cur = sys.argv[1], sys.argv[2]
    else:
        import argparse
        _ap = argparse.ArgumentParser(description="两版导出目录全量对照")
        _ap.add_argument("--prev", required=True)
        _ap.add_argument("--cur", required=True)
        _ns = _ap.parse_args()
        _prev, _cur = _ns.prev, _ns.cur
    sys.exit(main_with_args(type("A", (), {"prev": _prev, "cur": _cur})()))
