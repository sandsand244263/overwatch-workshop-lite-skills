#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一处改版本：SKILL.md / marketplace.json / README.md 同时更新，并校验一致性。

用法：
  python tools/bump.py 2.13.0            # 改版本号
  python tools/bump.py --check           # 只检查三处是否一致
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = "VERSION"
FILES = {
    "SKILL.md": (r"^version: .*$", "version: %s"),
    ".claude-plugin/marketplace.json": (r'"version": "[0-9.]+"', '"version": "%s"'),
    "README.md": (r"当前版本 \*\*v?[0-9.]+\*\*", "当前版本 **v%s**"),
}


def current():
    out = {}
    for rel, (pat, _fmt) in FILES.items():
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            out[rel] = None
            continue
        m = re.search(pat, open(p, encoding="utf-8").read(), re.M)
        out[rel] = re.search(r"[0-9]+\.[0-9]+\.[0-9]+", m.group(0)).group(0) if m else None
    return out


def main():
    args = sys.argv[1:]
    if not args or args[0] == "--check":
        cur = current()
        vals = set(v for v in cur.values() if v)
        for k, v in cur.items():
            print("%-34s %s" % (k, v))
        if len(vals) == 1:
            print("一致：%s" % vals.pop())
            return 0
        print("不一致，需要 bump")
        return 1
    version = args[0]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        sys.exit("版本号格式应为 X.Y.Z")
    vp = os.path.join(ROOT, VERSION_FILE)
    with open(vp, "w", encoding="utf-8", newline="\n") as f:
        f.write(version + "\n")

    for rel, (pat, fmt) in FILES.items():
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            continue
        s = open(p, encoding="utf-8").read()
        s2 = re.sub(pat, fmt % version, s, count=1, flags=re.M)
        open(p, "w", encoding="utf-8").write(s2)
    print("已写到 %s：" % version)
    for k, v in current().items():
        print("  %-32s %s" % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
