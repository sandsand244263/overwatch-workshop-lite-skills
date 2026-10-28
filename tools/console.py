#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控制台输出加固：让 ✓ / ✗ / ─ 这类符号在被管道捕获时也不炸。

为什么需要它：Windows 上 python 的 stdout 一旦不是真控制台（agent 抓输出、CI、
`for` 循环里重定向、devcheck 里 subprocess 捕获），编码就退回 locale（国服机器是
cp936/GBK），而 GBK 表示不了 ✓ (U+2713) / ✗ (U+2717)。结果是 `ws.py check`
在打印第一行时就 `UnicodeEncodeError: 'gbk' codec can't encode character '\\u2713'`
—— 命令本身没错，输出层先死了。2026-10-28 实测：默认控制台下 `check` / `devcheck`
都这样；而且 devcheck 是拿 utf-8 读子进程输出的，子进程崩了就会误报「生成器有漂移」。

做法：非 UTF-8 的流统一改成 UTF-8 + errors=replace。
- 真控制台（WindowsConsoleIO）本来就是 utf-8，不动；
- 管道/重定向：所有消费方（devcheck 的 subprocess、Claude Code / DSH 这类 agent、
  PowerShell 7、CI）都按 UTF-8 解码，写 utf-8 才对得上；
- 万一 reconfigure 不可用，退到当前编码 + errors=replace，宁可印 '?' 也不抛。

用法（入口脚本 import 后调一次；core.py 已在 import 时调过，import core 的脚本自动生效）：

    import console
    console.harden()
"""
import sys

_UTF8_NAMES = ("utf-8", "utf8", "utf-8-sig", "utf8sig")


def harden():
    """把 stdout/stderr 拉到 UTF-8。幂等，可重复调。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        enc = (getattr(stream, "encoding", "") or "").lower()
        if enc in _UTF8_NAMES:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            try:
                stream.reconfigure(errors="replace")
            except Exception:
                pass
