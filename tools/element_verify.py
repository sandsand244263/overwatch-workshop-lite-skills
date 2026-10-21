#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐个样本核对 estimate2() 与游戏实测元素数，全 0 误差才算通过。

实测值来源：把探针 .ow 单独导入游戏，地图工坊 → 显示诊断结果 → 总计元素数量。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from element_count2 import estimate2

PROBE = r"C:\Users\Administrator\Desktop\工坊测试\探针"
REAL = r"C:\Users\Administrator\Desktop\工坊测试\真实模式"

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


def main():
    bad = 0
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
        flag = "" if err == 0 else ("  <-- 差 %+d" % err)
        if err:
            bad += 1
        print("%-30s %8d %8d %6d%s" % (name[:30], measured, pred, err, flag))
    print("-" * 60)
    if bad:
        print("失败：%d / %d 个样本误差非 0" % (bad, len(SAMPLES)))
        return 1
    print("全部 %d 个样本误差 0，通过" % len(SAMPLES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
