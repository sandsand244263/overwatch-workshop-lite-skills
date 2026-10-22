"""从工坊导出 JSON 抽取官方说明文字（Description）。

数据源：`<export>/workshop_zhCN.json`（由 mini-extract export-all 生成）
产出（写入 data/）：
  - element-docs.tsv      元素说明：kind / name / description
  - param-docs.tsv        参数说明：element / index / name / input_type / description / default / min / max / dropdown
  - dropdown-options.tsv  下拉选项说明：dropdown / option / description

用法：
  python tools/extract_docs.py --export 导出目录/export-154504
  python tools/extract_docs.py --export 导出目录/export-154504 --data-dir data
"""
import argparse
import ast
import csv
import json
import os
import sys

KINDS = (("Events", "事件"), ("Actions", "动作"), ("Values", "值"), ("Extensions", "扩展"))


def parse_literal(value):
    """Parameters / Options 在 JSON 里是 Python 字面量字符串。"""
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return []
    return value if isinstance(value, list) else []


def default_label(param):
    dv = param.get("DefaultValue")
    if isinstance(dv, dict):
        return dv.get("DisplayName") or ""
    if isinstance(dv, str) and dv not in ("None", ""):
        sel = parse_literal(dv)
        if isinstance(sel, list) and sel and isinstance(sel[0], dict):
            return sel[0].get("DisplayName") or ""
        return dv
    num = param.get("DefaultNumberValue")
    if num not in (None, "", "0.0", 0.0):
        return str(num)
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, help="导出目录，含 workshop_zhCN.json")
    ap.add_argument("--data-dir", default=None, help="默认取本仓库 data/")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = args.data_dir or os.path.join(root, "data")
    src = os.path.join(args.export, "workshop_zhCN.json")
    if not os.path.isfile(src):
        sys.exit("找不到 %s" % src)
    j = json.load(open(src, encoding="utf-8"))

    docs, params, options = [], [], []
    for key, label in KINDS:
        for item in j.get(key, []):
            name = (item.get("DisplayName") or "").strip()
            if not name:
                continue
            desc = (item.get("Description") or "").strip()
            docs.append({"kind": label, "name": name, "description": desc})

            dd_id = item.get("GUID") or item.get("Id") or ""
            for idx, p in enumerate(parse_literal(item.get("Parameters")) or []):
                if not isinstance(p, dict):
                    continue
                params.append({
                    "element": name,
                    "kind": label,
                    "index": idx,
                    "name": (p.get("Name") or "").strip(),
                    "input_type": (p.get("InputType") or p.get("InferredType") or "").strip(),
                    "description": (p.get("Description") or "").strip(),
                    "default": default_label(p),
                    "min": str(p.get("Min") or ""),
                    "max": str(p.get("Max") or ""),
                    "dropdown": (p.get("DropdownId") or "").strip(),
                    "owner_id": dd_id,
                })

    # 下拉选项：按 owner_id + dropdown id 双索引，供参数按 DropdownId 关联
    by_dd = {}
    for dd in j.get("Dropdowns", []):
        dd_id = (dd.get("Id") or "").strip()
        opts = parse_literal(dd.get("Options")) or []
        by_dd[dd_id] = opts
        for o in opts:
            if not isinstance(o, dict):
                continue
            options.append({
                "dropdown": dd_id,
                "option": (o.get("DisplayName") or "").strip(),
                "description": (o.get("Description") or "").strip(),
            })
    # 扩展里也带下拉选项
    for ext in j.get("Extensions", []):
        for o in parse_literal(ext.get("UnlockedValues")) or []:
            if not isinstance(o, dict):
                continue
            options.append({
                "dropdown": (o.get("Dropdown") or ext.get("GUID") or "").strip(),
                "option": (o.get("DisplayName") or "").strip(),
                "description": (o.get("Description") or "").strip(),
            })

    # 参数补一列「下拉有哪些选项」
    opt_names = {}
    for o in options:
        opt_names.setdefault(o["dropdown"], []).append(o["option"])
    for p in params:
        p["options"] = "|".join(opt_names.get(p["dropdown"], [])) if p["dropdown"] else ""

    def dump(fname, fields, rows):
        path = os.path.join(data_dir, fname)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        print("%-24s %d 行" % (fname, len(rows)))

    dump("element-docs.tsv", ["kind", "name", "description"], docs)
    dump("param-docs.tsv",
         ["element", "kind", "index", "name", "input_type", "description", "default", "min", "max", "dropdown", "options", "owner_id"],
         params)
    dump("dropdown-options.tsv", ["dropdown", "option", "description"], options)

    filled = sum(1 for d in docs if d["description"])
    pfilled = sum(1 for p in params if p["description"])
    print("\n元素 %d 条，有说明 %d 条（%.0f%%）" % (len(docs), filled, 100.0 * filled / max(1, len(docs))))
    print("参数 %d 条，有说明 %d 条（%.0f%%）" % (len(params), pfilled, 100.0 * pfilled / max(1, len(params))))
    print("下拉选项 %d 条，有说明 %d 条" % (len(options), sum(1 for o in options if o["description"])))


if __name__ == "__main__":
    main()
