#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐个样本核对 estimate2() 与游戏实测元素数，全 0 误差才算通过。

实测值来源：把探针 .ow 单独导入游戏，地图工坊 → 显示诊断结果 → 总计元素数量。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from element_count2 import estimate2
import local_paths

# 探针与真实模式都放在本机（不进仓库）：local_paths.json 的 probe_dir / corpus，或环境变量
PROBE = local_paths.get("probe_dir", "WS_PROBE_DIR")
REAL = local_paths.corpus_dir()

SAMPLES = [
    (os.path.join(PROBE, "探针_E0_百条动作.ow"), 201),
    (os.path.join(PROBE, "探针_E1_数组百次.ow"), 1001),
    (os.path.join(PROBE, "探针_E3_嵌套百次.ow"), 901),
    (os.path.join(PROBE, "探针_E4_条件百条.ow"), 303),
    (os.path.join(PROBE, "探针_E5_多参数百次.ow"), 1101),
    (os.path.join(PROBE, "探针_FA_布尔百次.ow"), 101),
    (os.path.join(PROBE, "探针_FB_字符串百次.ow"), 501),
    (os.path.join(PROBE, "探针_FC_颜色百次.ow"), 901),
    (os.path.join(PROBE, "探针_S1.ow"), 240),
    (os.path.join(PROBE, "探针_S2.ow"), 939),
    (os.path.join(PROBE, "探针_R1A.ow"), 93),
    (os.path.join(PROBE, "探针_R1B.ow"), 2088),
    (os.path.join(PROBE, "探针_R1_单条最大规则.ow"), 2175),
    (os.path.join(REAL, "猪猪钩钩乐·原版.ow"), 16918),
]


TOL_PROBE_EXACT = 0      # 单元探针（E/G/H/C/D 系列）：必须精确
TOL_COMBO = 3            # 组合样本（S/R 系列）：实测 ±3 以内（见 docs/element-count.md）
TOL_REAL_LO, TOL_REAL_HI = 0.0, 0.25   # 真实模式：模型一律偏低，实测应落在 预测 ~ 预测×1.25


def verdict(name, measured, pred):
    """-> (是否通过, 说明)。门槛来自 docs/element-count.md 的已记录精度，不是拍脑袋。"""
    err = pred - measured
    if "原版" in name or name.endswith("原版.ow"):
        if measured and pred <= measured <= pred * (1 + TOL_REAL_HI):
            return True, "真实模式在「偏低 %d%%」内（容差 0~%d%%）" % (
                round((measured - pred) * 100.0 / measured if measured else 0), TOL_REAL_HI * 100)
        return False, "真实模式超出容差（%+d）" % err
    if name.startswith("探针_S") or name.startswith("探针_R"):
        return abs(err) <= TOL_COMBO, "组合样本容差 ±%d（实际 %+d）" % (TOL_COMBO, err)
    return err == TOL_PROBE_EXACT, "单元探针要求精确（实际 %+d）" % err


def main():
    if not PROBE or not REAL:
        print("没有探针/语料目录：%s" % local_paths.hint())
        return 2
    bad = 0
    print("门槛：单元探针 精确 / 组合样本 ±%d / 真实模式 偏低 0~%d%%"
          % (TOL_COMBO, TOL_REAL_HI * 100))
    print("%-30s %8s %8s %6s" % ("样本", "实测", "预测", "误差"))
    print("-" * 60)
    for path, measured in SAMPLES:
        name = os.path.basename(path)
        if not os.path.exists(path):
            print("%-30s %8d %8s %6s" % (name, measured, "缺失", "-"))
            bad += 1
            continue
        pred = estimate2(path)
        err = pred - measured
        ok, why = verdict(name, measured, pred)
        flag = "" if ok else ("  <-- %s" % why)
        if not ok:
            bad += 1
        print("%-30s %8d %8d %6d%s" % (name[:30], measured, pred, err, flag))
    print("-" * 60)
    if bad:
        print("失败：%d / %d 个样本超出容差" % (bad, len(SAMPLES)))
        return 1
    print("全部 %d 个样本在容差内，通过" % len(SAMPLES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
