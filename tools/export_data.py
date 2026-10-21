#!/usr/bin/env python3
"""从 DataTool 导出四份 JSON（工坊/英雄/地图/设置 schema）。

用法：
  python tools/export_data.py --datatool "E:/.../DataTool.dll" --out C:/owdump/export-154504
  python tools/export_data.py --datatool ... --out ... --lang zhCN --game E:/Overwatch

设计要点：
- 路径必须传给 DataTool 的 `--out=` 参数（它不认相对路径里的反斜杠混用）
- 每份导出后校验文件存在且非空；失败立刻停止并打印该次完整输出
- 全部成功后打印 md5，供与上一版对比（md5 全同 = 官方没改数据）
"""
import argparse
import hashlib
import os
import subprocess
import sys

COMMANDS = [
    ("list-workshop", "workshop_{lang}"),
    ("list-heroes", "heroes"),
    ("list-maps", "maps"),
    ("list-game-ruleset-schemas", "ruleset_schemas"),
]


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datatool", required=True, help="DataTool.dll 路径")
    ap.add_argument("--game", default="E:/Overwatch", help="游戏安装目录")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--lang", default="zhCN")
    ap.add_argument("--dotnet", default="dotnet", help="dotnet 可执行文件")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    results = []
    for cmd, name_tpl in COMMANDS:
        out = os.path.join(args.out, name_tpl.format(lang=args.lang) + ".json")
        argv = [args.dotnet, args.datatool, args.game, cmd,
                "--language=" + args.lang, "--rcn", "--json", "--out=" + out.replace("\\", "/")]
        proc = subprocess.run(argv, capture_output=True, text=True, errors="replace")
        ok = os.path.isfile(out) and os.path.getsize(out) > 0
        if not ok:
            print("✗ %s 失败，退出码 %s" % (cmd, proc.returncode))
            print((proc.stdout or "")[-1500:])
            print((proc.stderr or "")[-1500:])
            return 1
        size = os.path.getsize(out)
        digest = md5(out)
        results.append((name_tpl.format(lang=args.lang), size, digest))
        print("✓ %-18s %9d 字节  %s" % (cmd, size, digest))

    print("\n对照上一版 md5，全同说明官方没改工坊数据，只需推数据基线号：")
    for name, size, digest in results:
        print("  %s  %s" % (digest, name + ".json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
