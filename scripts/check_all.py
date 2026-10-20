#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前自检：对 references 下的回归样本跑一遍校验，必须 0 error。

用法：
  python scripts/check_all.py

样本包括：
  references/verified/*.ow  实测导入通过的写法
  references/golden*.ow     真实模式样本

改完 lint_ow.py 或 references 后必须跑这个；有 error 就别发版。
"""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lint_ow  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REFS = os.path.normpath(os.path.join(HERE, "..", "references"))


def main():
    samples = sorted(glob.glob(os.path.join(REFS, "verified", "*.ow")))
    samples += sorted(glob.glob(os.path.join(REFS, "golden*.ow")))

    if not samples:
        print("[错误] 没找到回归样本")
        return 2

    sigs, labels = lint_ow.load_signatures(os.path.join(REFS, "signatures.md"))
    settings = lint_ow.load_settings_schema(os.path.join(REFS, "settings-schema.tsv"))

    failed = 0
    for path in samples:
        problems = lint_ow.lint(path, sigs, labels, settings)
        errors = [p for p in problems if p[1] == "error"]
        name = os.path.basename(path)
        if errors:
            failed += 1
            print("✗ %s：%d 个 error" % (name, len(errors)))
            for ln, _level, msg in errors[:8]:
                print("    第 %s 行：%s" % (ln or "?", msg))
        else:
            print("✓ %s（warning %d）" % (name, len(problems)))

    print("\n回归样本 %d 个，失败 %d 个" % (len(samples), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
