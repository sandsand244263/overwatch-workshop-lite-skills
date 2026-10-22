"""从 DataTool 的 list-maps 导出生成 data/map-variants.tsv。

地图编号 = (0xD8 << 52) | 变体编号
  972777519512068154 = 0xD8000000000A03A → 变体 0xA03A（早晨）
实测依据：用户手动导出的「占领要点 6v6」文件里的编号，与本表 100% 吻合。

用法：
    python tools/gen_map_variants.py --src C:/owdump/wslist/maps_new.json --out data/map-variants.tsv
"""
import argparse, collections, json, os

PREFIX = 0xD8 << 52


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="list-maps --json 的输出")
    ap.add_argument("--out", default="data/map-variants.tsv")
    a = ap.parse_args()

    data = json.load(open(a.src, encoding="utf-8"))
    table = collections.OrderedDict()
    for v in data.values():
        for name in {v.get("Name"), v.get("VariantName")}:
            if not name:
                continue
            ids = table.setdefault(name, [])
            for var in (v.get("Variations") or []):
                gid = PREFIX | int(var["GUID"].split(".")[0], 16)
                if gid not in [x for x, _ in ids]:
                    ids.append((gid, var.get("Name") or "默认"))

    rows = ["zh\tvariant\tid\tverified"]
    for name, ids in table.items():
        for gid, vname in ids:
            rows.append("%s\t%s\t%d\tno" % (name, vname, gid))
    open(a.out, "w", encoding="utf-8", newline="\n").write("\n".join(rows) + "\n")
    print("%s：%d 张图 / %d 条时段（verified 全为 no）" % (a.out, len(table), len(rows) - 1))
    print("提示：`Variations` 里混着季节/天气等**不能写进 .ow** 的变体；")
    print("      只有实测导出确认过的时段才能写编号，其余一律只写地图名。")


if __name__ == "__main__":
    main()
