#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Overwatch.exe 里定位「工坊元素计数 / 诊断」相关代码的常量扫描（静态只读）。

思路：诊断面板的几句原文给出三个可交叉验证的常量
    元素上限 32768        -> 0x8000
    单条规则文本上限 98KB -> 0x18800 (100352) / 0x18000 (98304)
    英雄皮肤组合上限 12   -> 0xC
同时满足「同一个函数里既出现 0x8000 又出现 98KB」的函数，基本就是诊断/校验函数。

用法：
    python tools/re/element_scan.py            # 全量扫描并打印结论
    python tools/re/element_scan.py --top 40   # 多打印几条候选

结论（2026-10-22 实测于 2.25 版客户端）见文件末尾 main() 的输出与
docs/element-reverse.md 的「二进制搜索结果」一节：没有找到唯一候选，
原因也一并写在文档里（常量噪声大 / 字符串不在 exe 里）。
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import disasm_cache as dc

TARGETS = {
    0x8000: "32768 元素上限",
    0x18800: "100352 = 98KB",
    0x18000: "98304 = 96KB",
    0x7FFF: "32767 = 上限-1",
}
PAD = 0x60          # 命中点前后多少字节内找指令边界
FUNC_GAP = 0x400    # 两个命中点相距多远以内算同一函数（粗略）


def imm_hits(exe=dc.EXE):
    """扫 .text 原始字节里所有 imm32 命中点。"""
    va_base, ptr, text = dc.read_section(".text", exe)
    out = {}
    for val in TARGETS:
        pat = struct.pack("<I", val)
        idx, i = [], 0
        while True:
            j = text.find(pat, i)
            if j < 0:
                break
            idx.append(va_base + j)
            i = j + 1
        out[val] = idx
    return out


def imm_is_real_operand(va, val):
    """命中点是否落在一条指令的立即数位置（而不是别的指令的位移/数据里）。"""
    recs = dc.range_disasm(va - PAD, va + PAD)
    for r_va, size, mn, ops, imm, imm2 in recs:
        if r_va <= va < r_va + size and (imm == val or imm2 == val):
            return (r_va, mn, ops)
    return None


def clusters(addrs, gap=FUNC_GAP):
    """把地址分组，近似函数归属。"""
    out = []
    for a in sorted(addrs):
        if out and a - out[-1][-1] <= gap:
            out[-1].append(a)
        else:
            out.append([a])
    return out


def functions(exe=dc.EXE):
    """.pdata 异常表 -> [(begin, end)]，这是拿准确函数边界唯一不依赖 IDA 的办法。

    RUNTIME_FUNCTION 是 12 字节：BeginAddress / EndAddress / UnwindInfoAddress（都是 RVA）。
    """
    _, _, data = dc.read_section(".pdata", exe)
    out = []
    for i in range(len(data) // 12):
        b, e, _u = struct.unpack_from("<III", data, i * 12)
        if b and e > b:
            out.append((b, e))
    out.sort()
    return out


def owner(funcs, addr):
    """地址属于哪个函数（返回下标或 None）。"""
    import bisect
    starts = [f[0] for f in funcs]
    i = bisect.bisect_right(starts, addr) - 1
    if i >= 0 and funcs[i][0] <= addr < funcs[i][1]:
        return i
    return None


def scan_rdata_strings(exe=dc.EXE):
    """在 .rdata 里找 UTF-16 / ASCII 的工坊相关英文串。"""
    _, _, rdata = dc.read_section(".rdata", exe)
    words = ["element", "Element", "workshop", "Workshop", "exceeded", "limit"]
    found = {}
    for w in words:
        for enc in ("utf-16-le", "ascii"):
            b = w.encode(enc)
            n = rdata.count(b)
            if n:
                found.setdefault(w, {})[enc] = n
    return found


def main():
    top = 40
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])
    dc.init()
    hits = imm_hits()
    print("=== 常量命中总数（.text 原始字节）")
    for val, desc in TARGETS.items():
        print("  0x%-6x %-22s %5d 处" % (val, desc, len(hits[val])))

    print("\n=== 过滤：只保留真正作为指令立即数出现的命中")
    real = {}
    for val in TARGETS:
        keep = []
        for va in hits[val][:4000]:
            got = imm_is_real_operand(va, val)
            if got:
                keep.append((va, got))
        real[val] = keep
        print("  0x%-6x 真立即数 %4d / %4d" % (val, len(keep), len(hits[val])))

    print("\n=== 交叉定位：同一函数里同时出现 0x8000 与 98KB")
    big = [va for va, _ in real[0x18800]] + [va for va, _ in real[0x18000]]
    limit = [va for va, _ in real[0x8000]]
    pairs = []
    for a in limit:
        for b in big:
            if abs(a - b) <= 0x800:
                pairs.append((a, b, abs(a - b)))
    pairs.sort(key=lambda x: x[2])
    if not pairs:
        print("  没有找到相距 0x800 以内的组合")
    for a, b, d in pairs[:top]:
        print("  0x%x <-> 0x%x  距离 0x%x" % (a, b, d))

    print("\n=== 按 .pdata 函数表归类（准确函数边界）")
    funcs = functions()
    print("  函数总数 %d" % len(funcs))
    by_func = {}
    for val in TARGETS:
        for va, _got in real[val]:
            i = owner(funcs, va)
            if i is not None:
                by_func.setdefault(i, set()).add(val)
    both = 0
    thirty = 0
    for i, vals in by_func.items():
        if 0x8000 in vals:
            thirty += 1
            if 0x18800 in vals or 0x18000 in vals:
                both += 1
    print("  含 32768 立即数的函数 %d 个" % thirty)
    print("  其中同时含 98KB 的   %d 个" % both)

    print("\n=== .rdata 字符串检查（工坊名字表是否在 exe 里）")
    found = scan_rdata_strings()
    if not found:
        print("  没有找到 element / workshop / limit 之类的串")
    else:
        for w, d in found.items():
            print("  %-10s %s" % (w, d))

    print("\n=== 结论")
    print("  见 docs/element-reverse.md：常量噪声太大、字符串不在 exe 内，")
    print("  本轮没有锁定唯一的计数函数；element_count2.py 的算法是探针实测拟合的。")


if __name__ == "__main__":
    main()
