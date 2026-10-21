#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Overwatch.exe 反汇编缓存工具（静态只读，不启动游戏）。

用法（在 WorkshopLite 目录下）：
    python tools/re/disasm_cache.py build          # 全量 .text 反汇编 -> out/disasm.pkl（慢，一次就够）
    python tools/re/disasm_cache.py range 0x8c2000 0x8cb000   # 打印某区间的反汇编（不自建缓存）

设计要点：
  - PE 段信息来自 pefile，.text 的 VirtualAddress / PointerToRawData 固定偏移换算：
        VA = file_off - PointerToRawData + VirtualAddress
  - 线性反汇编（capstone CS_ARCH_X86 / CS_MODE_64），每条记录
        (va, size, mnemonic, op_str, imm, imm2)
    只保留需要的字段，pkl 体积可控。
  - 结构化数据（跳转表、字节数组）会被线性扫成垃圾指令，这是已知代价；
    找函数边界时用「密集 ret / int3 填充」来近似。
"""
import os
import pickle
import struct
import sys

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64, CS_OP_IMM

EXE = r"E:\Overwatch\_retail_\Overwatch.exe"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(os.path.dirname(HERE)), "out")
CACHE = os.path.join(OUT, "disasm.pkl")


def sections(exe=EXE):
    pe = pefile.PE(exe, fast_load=True)
    info = {}
    for s in pe.sections:
        name = s.Name.rstrip(b"\0").decode("latin1")
        info[name] = (s.VirtualAddress, s.PointerToRawData, s.SizeOfRawData)
    return info


def read_section(name, exe=EXE):
    va_base, ptr, size = sections(exe)[name]
    with open(exe, "rb") as f:
        f.seek(ptr)
        return va_base, ptr, f.read(size)


def off2va(off, sec=".text", exe=EXE):
    va_base, ptr, _ = sections(exe)[sec]
    return off - ptr + va_base


def va2off(va, sec=".text", exe=EXE):
    va_base, ptr, _ = sections(exe)[sec]
    return va - va_base + ptr


def _insn_record(ins):
    imm = None
    imm2 = None
    for op in ins.operands:
        if op.type == CS_OP_IMM:
            if imm is None:
                imm = op.imm
            elif imm2 is None:
                imm2 = op.imm
    return (ins.address, ins.size, ins.mnemonic, ins.op_str, imm, imm2)


def build(exe=EXE, cache=CACHE):
    """全量线性反汇编 .text 并写 pkl。返回记录条数。"""
    va_base, _, text = read_section(".text", exe)
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    recs = [_insn_record(i) for i in md.disasm(text, va_base)]
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with open(cache, "wb") as f:
        pickle.dump(recs, f, protocol=4)
    return len(recs)


def load(cache=CACHE):
    with open(cache, "rb") as f:
        return pickle.load(f)


def range_disasm(start_va, end_va=None, n=200, exe=EXE, as_off=False):
    """现场反汇编 [start_va, end_va)。默认按 .text 虚拟地址解释；as_off=True 时按文件偏移。"""
    va_base, _, text = read_section(".text", exe)
    if as_off:
        start_va = off2va(start_va)
        if end_va is not None:
            end_va = off2va(end_va)
    start = start_va - va_base
    if end_va is None:
        end = start + n * 8
    else:
        end = end_va - va_base
    md = Cs(CS_ARCH_X86, CS_MODE_64)
    md.detail = True
    return [_insn_record(i) for i in md.disasm(text[start:end], start_va)]


def fmt(recs):
    out = []
    for va, size, mn, ops, imm, imm2 in recs:
        extra = ""
        if imm is not None:
            extra = "  ; 0x%x" % imm if imm >= 0 else "  ; %d" % imm
            if imm2 is not None:
                extra += " / 0x%x" % imm2
        byts = " ".join("%02x" % b for b in _read(va, size))
        out.append("%016x  %-22s %-7s %s%s" % (va, byts, mn, ops, extra))
    return "\n".join(out)


def _read(va, size):
    va_base, ptr, text = _TEXT
    o = va - va_base
    return text[o:o + size]


_TEXT = None


def init():
    global _TEXT
    if _TEXT is None:
        _TEXT = read_section(".text")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "build":
        n = build()
        print("cached %d instructions -> %s" % (n, CACHE))
    elif cmd == "range":
        s = int(sys.argv[2], 0)
        e = int(sys.argv[3], 0) if len(sys.argv) > 3 else None
        init()
        print(fmt(range_disasm(s, e)))
    else:
        print(__doc__)
