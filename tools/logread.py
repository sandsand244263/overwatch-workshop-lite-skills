# -*- coding: utf-8 -*-
"""读工坊查看器日志。

游戏会把 `记入查看器` 的每一条落盘成：

    %USERPROFILE%\\Documents\\Overwatch\\Workshop\\Log-<年-月-日-时-分-秒>.txt

**前提是游戏设置里开着开关**：设置 → 游戏 → 综合 → 自定游戏-地图工坊 →
「启用地图工坊查看器日志文件」（同页「启用地图工坊查看器」也要开）。关掉时一局也不生成——
2026-10-24 之后连续几天没有文件，查到最后就是这两个被关了（排查见私有仓
`v16-re/viewer-log-analysis.md`）。

`--watch`：盯目录，出现新文件且大小稳定 `--settle` 秒后自动判读。纯文件轮询，不碰键鼠，
所以用户自己导入、自己玩也能用。

拿不到文件时，让用户从查看器点「复制记录到剪贴板」，存成 `records.txt` 再用 `--file` 判读（同格式）。

对外只有 `run(args)`：由 `ws.py readlog` 转调。
"""
import glob
import os
import re
import sys

LINE_RE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\]\s*(.*)$")
TAG_RE = re.compile(r"^\[([^\]]+)\]\s*(.*)$")
# `c1=2` / `分数=6` 都能抓（键允许中文）
KV_RE = re.compile(r"([\w\u4e00-\u9fa5]+)=(-?\d+(?:\.\d+)?)")


def default_dir():
    return os.path.join(os.path.expanduser("~"), "Documents", "Overwatch", "Workshop")


def _sort_key(path):
    m = re.search(r"Log-(\d{4})-(\d\d)-(\d\d)-(\d\d)-(\d\d)-(\d\d)", os.path.basename(path))
    return m.groups() if m else ("0", "0", "0", "0", "0", "0")


def list_logs(folder):
    """按时间升序返回全部 Log-*.txt 路径。"""
    return sorted(glob.glob(os.path.join(folder, "Log-*.txt")), key=_sort_key)


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", "replace")


def parse(text):
    """-> [{'sec': 秒数, 'ts': '00:00:08', 'body': 内容, 'tag': 标签或'', 'rest': 去标签后的内容}]"""
    out = []
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        m = LINE_RE.match(line)
        if not m:
            continue
        h, mi, s = (int(x) for x in m.group(1, 2, 3))
        body = m.group(4).strip()
        tm = TAG_RE.match(body)
        tag, rest = (tm.group(1), tm.group(2).strip()) if tm else ("", body)
        out.append({"sec": h * 3600 + mi * 60 + s, "ts": "%02d:%02d:%02d" % (h, mi, s),
                    "body": body, "tag": tag, "rest": rest})
    return out


def last_values(entries):
    """抓所有 `键=值`（也认 `键:值`），同名键取最后一次出现 -> {键: (值, 秒数)}"""
    got = {}
    for e in entries:
        for k, v in KV_RE.findall(e["body"]):
            got[k] = (v, e["sec"])
    return got


def find_value(entries, key):
    """按优先级找某个键的最后一次取值：`键=值` → `键:值` → `键 值`。

    老探针写的是「分数 6」这种空格写法，新探针写 `c1=2`，两种都要认。
    """
    pats = [r"\s*[=:：]\s*(-?\d+(?:\.\d+)?)", r"\s+(-?\d+(?:\.\d+)?)"]
    for tail in pats:
        rx = re.compile(re.escape(key) + tail)
        hit = None
        for e in entries:
            for m in rx.finditer(e["body"]):
                hit = (m.group(1), e["sec"])
        if hit:
            return hit
    return None


def _num(x):
    return float(x) if ("." in x) else int(x)


# ---------------------------------------------------------------- 期望表 (.tsv)
# 列：格号 / 结构说明 / 期望 / 容差 / 依据 / 备注
# 判读结论只有四档：通过 / 不符 / 未出现 / 超容差。
EXPECT_COLS = ("格号", "结构说明", "期望", "容差", "依据", "备注")
ABSENT_WORDS = ("未出现", "缺席", "none", "absent")
_NUM_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_PM_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)±([+-]?\d+(?:\.\d+)?)$")
_TOL_RE = re.compile(r"^(?:±|\+/-)([+]?\d+(?:\.\d+)?)$")
_CMP_RE = re.compile(r"^(>=|<=|==|=|>|<|≥|≤)([+-]?\d+(?:\.\d+)?)$")
_RANGE_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\.\.([+-]?\d+(?:\.\d+)?)$")
_OP_MAP = {"≥": ">=", "≤": "<=", "=": "=="}


def _as_num(s):
    """把一段文本变成数字；不是数字返回 None（绝不默认成 0）。"""
    s = (s or "").strip()
    return float(s) if _NUM_RE.match(s) else None


def parse_constraint(raw, where, errors, allow_absent=False):
    """解析一个判定条件。看不懂就记 error 并返回 None——不静默跳过。

    支持：空 / *（不判）、未出现（只用于「期望」列）、12、12.5、
         12±2、>=10、>10、<=10、<10、==10、10..20
    """
    s = (raw or "").strip().replace(" ", "")
    if s in ("", "*"):
        return {"kind": "any"}
    if s in ABSENT_WORDS:
        if allow_absent:
            return {"kind": "absent"}
        errors.append("%s：「%s」只能写在期望列（意思是这个格子的键不该出现在日志里）" % (where, raw))
        return None
    m = _PM_RE.match(s)
    if m:
        v, t = float(m.group(1)), abs(float(m.group(2)))
        return {"kind": "num", "v": v, "tol": t}
    m = _TOL_RE.match(s)
    if m:
        return {"kind": "tol", "t": abs(float(m.group(1)))}
    m = _CMP_RE.match(s)
    if m:
        op = _OP_MAP.get(m.group(1), m.group(1))
        return {"kind": "cmp", "op": op, "v": float(m.group(2))}
    m = _RANGE_RE.match(s)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo > hi:
            errors.append("%s：区间写反了（%s 大于 %s）" % (where, m.group(1), m.group(2)))
            return None
        return {"kind": "range", "lo": lo, "hi": hi}
    v = _as_num(s)
    if v is not None:
        return {"kind": "num", "v": v}
    errors.append("%s：看不懂「%s」。能写的写法：12 / 12.5 / 12±2 / >=10 / <=10 / 10..20"
                  "（期望列还能写「未出现」）" % (where, raw))
    return None


def _match(actual, spec):
    """实际值是否满足一个条件。"""
    kind = spec["kind"]
    if kind in ("any", "absent"):
        return True
    if kind == "num":
        tol = spec.get("tol", 0.0)
        return abs(actual - spec["v"]) <= tol + 1e-9
    if kind == "range":
        return spec["lo"] - 1e-9 <= actual <= spec["hi"] + 1e-9
    if kind == "cmp":
        op, v = spec["op"], spec["v"]
        return {">=": actual >= v - 1e-9, "<=": actual <= v + 1e-9,
                ">": actual > v, "<": actual < v, "==": abs(actual - v) <= 1e-9}[op]
    return False


def parse_expect_file(path):
    """读期望表 -> (rows, errors)。rows 里每项带 want/tol 的解析结果。"""
    errors, rows = [], []
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return [], ["读不到期望表：%s（%s）" % (path, e)]
    text = None
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return [], ["期望表编码认不出来（试过 utf-8 / gb18030）：%s" % path]

    header_seen, colmap = False, None
    for lineno, line in enumerate(text.split("\n"), 1):
        line = line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = [c.strip() for c in line.split("\t")]
        where = "%s 第 %d 行" % (os.path.basename(path), lineno)
        if not header_seen:
            header_seen = True
            if cells[0] in ("格号", "格", "key", "变量"):
                colmap = {name: (cells.index(name) if name in cells else None)
                          for name in EXPECT_COLS}
                if colmap["期望"] is None:
                    errors.append("%s：表头里没有「期望」列（表头应是：%s）"
                                  % (where, " / ".join(EXPECT_COLS)))
                    return [], errors
                continue
            colmap = {"格号": 0, "结构说明": 1, "期望": 2, "容差": 3, "依据": 4, "备注": 5}
        if len(cells) < 3 or not cells[0]:
            errors.append("%s：列数不够（至少要 格号/结构说明/期望 三列，实际 %d 列）"
                          % (where, len(cells)))
            continue

        def pick(name):
            idx = colmap.get(name)
            return cells[idx] if idx is not None and idx < len(cells) else ""

        row = {"line": lineno, "key": pick("格号"), "desc": pick("结构说明"),
               "want_raw": pick("期望"), "tol_raw": pick("容差"),
               "basis": pick("依据"), "note": pick("备注")}
        row["want"] = parse_constraint(row["want_raw"], where + " 期望", errors, allow_absent=True)
        row["tol"] = parse_constraint(row["tol_raw"], where + " 容差", errors) if row["tol_raw"] else None
        if row["tol"] and row["tol"]["kind"] == "num":
            errors.append("%s 容差：单个数字没有意义，写 ±2 / >=10 / 10..20" % where)
            row["tol"] = None
        if row["want"] is not None and row["tol"] is not None:
            if row["want"]["kind"] != "num" and row["tol"]["kind"] == "tol":
                errors.append("%s：容差写 ±T 时，期望必须是数字（现在是「%s」）"
                              % (where, row["want_raw"]))
                row["tol"] = None
        if row["want"] is None or (row["tol_raw"] and row["tol"] is None):
            continue
        if any(r["key"] == row["key"] for r in rows):
            errors.append("%s：格号「%s」重复了，一格只能有一行" % (where, row["key"]))
            continue
        rows.append(row)
    if not rows and not errors:
        errors.append("期望表里没有任何数据行：%s" % path)
    return rows, errors


def series(entries, key):
    """抓某个键的整条读数序列 -> [(秒, 值)]。键按词边界匹配，c1 不会吃掉 c10。"""
    rx = re.compile(r"(?<![\w\u4e00-\u9fa5])" + re.escape(key) + r"\s*[=:：]\s*(-?\d+(?:\.\d+)?)")
    out = []
    for e in entries:
        for m in rx.finditer(e["body"]):
            out.append((e["sec"], float(m.group(1))))
    return out


def judge(row, actual, count):
    """-> (结论, 说明)。四档：通过 / 不符 / 未出现 / 超容差。"""
    want, tol = row["want"], row["tol"]
    if want["kind"] == "absent":
        return ("通过", "按预期没出现") if actual is None else ("不符", "不该出现却出现了")
    if actual is None:
        return "未出现", "日志里找不到 %s=" % row["key"]
    if tol is not None and tol["kind"] == "tol":          # ±T：把期望当中心
        if want["kind"] != "num":
            return "不符", "容差 ±%g 没有可用的期望中心" % tol["t"]
        if abs(actual - want["v"]) <= tol["t"] + 1e-9:
            return "通过", "在 %g±%g 内" % (want["v"], tol["t"])
        return "超容差", "离期望 %g 差了 %g（容差 ±%g）" % (want["v"], abs(actual - want["v"]), tol["t"])
    if not _match(actual, want):
        return "不符", "期望 %s，实际 %g" % (row["want_raw"] or "*", actual)
    if tol is not None and not _match(actual, tol):
        return "超容差", "不满足容差 %s" % row["tol_raw"]
    return "通过", ""


def _dw(s):
    """按终端显示宽度算长度（中文占 2 格），否则表格会歪。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s, width):
    return s + " " * max(0, width - _dw(s))


def _clip(s, width):
    if _dw(s) <= width:
        return s
    out, used = "", 0
    for ch in s:
        w = 2 if _dw(ch) == 2 else 1
        if used + w > width - 1:
            break
        out += ch
        used += w
    return out + "…"


def report_expect_file(entries, rows, path, verbose=False):
    """打印「预期 | 实际 | 结论」差异表；返回退出码（0 只在全部通过时）。"""
    results, tally = [], {"通过": 0, "不符": 0, "未出现": 0, "超容差": 0}
    for row in rows:
        hits = series(entries, row["key"])
        actual = hits[-1][1] if hits else None
        verdict, why = judge(row, actual, len(hits))
        tally[verdict] += 1
        results.append((row, actual, len(hits), verdict, why))

    print("\n期望表：%s（%d 格）" % (os.path.basename(path), len(rows)))
    head = ("格号", "结构说明", "预期", "实际", "结论")
    widths = [8, 26, 10, 10, 8]
    print("  " + " ".join(_pad(h, w) for h, w in zip(head, widths)))
    print("  " + " ".join("-" * w for w in widths))
    for row, actual, count, verdict, _why in results:
        shown = "（没出现）" if actual is None else ("%g" % actual)
        print("  " + " ".join([
            _pad(_clip(row["key"], widths[0]), widths[0]),
            _pad(_clip(row["desc"] or "-", widths[1]), widths[1]),
            _pad(_clip(row["want_raw"] or "*", widths[2]), widths[2]),
            _pad(_clip(shown, widths[3]), widths[3]),
            _pad(verdict, widths[4]),
        ]))

    bad = [r for r in results if verbose or r[3] != "通过"]
    if bad:
        print("\n逐格明细%s：" % ("" if verbose else "（只看没通过的）"))
        for row, actual, count, verdict, why in bad:
            print("  %s  %s" % (row["key"], why or "（通过）"))
            print("     期望 %s%s / 实际 %s / 打点 %d 次%s"
                  % (row["want_raw"] or "*",
                     ("（容差 %s）" % row["tol_raw"]) if row["tol_raw"] else "",
                     "（没出现）" if actual is None else ("%g" % actual),
                     count,
                     ("（第 %d 行）" % row["line"])))
            if row["basis"] or row["note"]:
                print("     依据：%s   备注：%s" % (row["basis"] or "-", row["note"] or "-"))

    over = [r for r in results if r[3] == "超容差"]
    if over:
        print("\n超容差 %d 格：%s（值出来了，但不在容差里）"
              % (len(over), "、".join(r[0]["key"] for r in over)))
    print("%d 格：通过 %d / 不符 %d / 未出现 %d"
          % (len(rows), tally["通过"], tally["不符"], tally["未出现"]))
    return 0 if tally["通过"] == len(rows) else 1


def check_expect(entries, spec):
    """spec: 'c1=2,c2=2,c3=1' -> (ok, [(键, 期望, 实际, 秒数)], [缺失键])"""
    want = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            return False, [], [part]
        k, v = part.split("=", 1)
        want.append((k.strip(), v.strip()))
    rows, missing, ok = [], [], True
    for k, v in want:
        hit = find_value(entries, k)
        if not hit:
            missing.append(k)
            ok = False
            rows.append((k, v, "（没出现）", None))
            continue
        actual, sec = hit
        same = abs(float(_num(actual)) - float(_num(v))) < 1e-6
        ok = ok and same
        rows.append((k, v, actual, sec))
    return ok, rows, missing


def _tail_has(path, token, nbytes=8192):
    """文件末尾 nbytes 内有没有 token（探针的收尾标记）。读不到就当没有。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - nbytes))
            return token.encode("utf-8") in f.read()
    except OSError:
        return False


def wait_new_log(folder, timeout=900, settle=8, poll=1.0, show=None, end_marker=None):
    """等目录里出现「之前没有的」Log-*.txt，并在它「写完」后返回。

    「写完」有两种判据：
    - 给了 `end_marker`（探针的 `[end]`）且文件里出现了它 → 只再等 3 秒就返回，不用干等 settle 秒；
    - 没有标记 → 大小稳定 settle 秒才算写完（老探针/手写探针的兜底）。

    `show` 是可选的进度输出函数（默认打印）。返回路径或 None。
    """
    import time
    before = set(os.listdir(folder)) if os.path.isdir(folder) else set()
    if show:
        show("盯 %s（现有 %d 个文件，等新文件…）" % (folder, len(before)))
    t0 = time.time()
    path, last_size, last_change, marker_seen = None, -1, 0.0, False
    while time.time() - t0 < timeout:
        try:
            now = set(os.listdir(folder))
        except OSError:
            now = set()
        fresh = sorted(n for n in (now - before) if n.lower().startswith("log-"))
        if path is None and fresh:
            path = os.path.join(folder, fresh[-1])
            last_size, last_change = -1, time.time()
            if show:
                show("  新文件出现：%s" % fresh[-1])
        if path is not None:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = last_size
            if size != last_size:
                last_size, last_change = size, time.time()
            else:
                quiet = time.time() - last_change
                if end_marker and not marker_seen and _tail_has(path, end_marker):
                    marker_seen = True
                    if show:
                        show("  看到收尾标记 %s，等 3 秒确认写完" % end_marker)
                need = 3 if marker_seen else settle
                if quiet >= need:
                    if show:
                        show("  %d 字节，已 %d 秒没变 → 认为写完%s"
                             % (size, need, "（有收尾标记）" if marker_seen else ""))
                    return path
        time.sleep(poll)
    return None

def run(args):
    folder = getattr(args, "dir", None) or default_dir()
    if not os.path.isdir(folder):
        print("找不到日志目录：%s" % folder)
        print("先确认游戏装在哪台机器、是不是用过 `记入查看器`。可用 --dir 指定。")
        return 2

    files = list_logs(folder)
    if getattr(args, "list", False):
        if not files:
            print("目录里没有 Log-*.txt：%s" % folder)
            return 2
        print("最近 %d 个（新 → 旧）：" % min(len(files), 10))
        for p in reversed(files[-10:]):
            print("  %-42s %6d 字节  %s" % (os.path.basename(p), os.path.getsize(p),
                                          _mtime_str(p)))
        return 0

    if getattr(args, "watch", False) and not getattr(args, "file", None):
        # 纯文件轮询：不碰键鼠、不启动游戏，所以用户自己导入自己玩也能用
        got = wait_new_log(folder,
                           timeout=getattr(args, "timeout", 900) or 900,
                           settle=getattr(args, "settle", 8) or 8)
        if not got:
            print("✗ 等了 %d 秒没有新日志文件：%s"
                  % (getattr(args, "timeout", 900) or 900, folder))
            print("  先确认开关：设置 → 游戏 → 综合 → 自定游戏-地图工坊 →"
                  "「启用地图工坊查看器日志文件」（同页另一个也开）")
            print("  或者拿查看器底部「复制记录到剪贴板」的内容，存成 records.txt 用 --file 指定。")
            return 2
        args.file = got
        files = list_logs(folder)

    path = getattr(args, "file", None)
    if path:
        if not os.path.isabs(path) and not os.path.isfile(path):
            cand = os.path.join(folder, path)
            path = cand if os.path.isfile(cand) else path
        if not os.path.isfile(path):
            print("找不到日志文件：%s" % path)
            return 2
    else:
        if not files:
            print("目录里没有 Log-*.txt：%s" % folder)
            print("提示：跑完探针请**正常退到大厅再退游戏**（直接结束进程可能不落盘）。")
            return 2
        path = files[-1]

    entries = parse(read_text(path))
    if not entries:
        print("文件是空的或格式不认识：%s" % path)
        print("可能还没写完——正常退出游戏后再读一次。")
        return 2

    span = entries[-1]["sec"] - entries[0]["sec"]
    print("日志：%s" % os.path.basename(path))
    print("时间：%s → %s（%d 行，跨度 %d 秒）" % (entries[0]["ts"], entries[-1]["ts"],
                                              len(entries), span))
    age = _age_minutes(path)
    if age is not None and age > 30:
        print("注意：这个文件是 %.0f 分钟前写的。如果不是你刚才那次，用 --file 指定，"
              "或确认游戏是正常退出（退出到大厅再退）。" % age)

    groups = {}
    for e in entries:
        groups.setdefault(e["tag"] or "(无标签)", []).append(e)

    print("\n按标签：")
    for tag, items in groups.items():
        last = items[-1]
        print("  [%s] %d 条，最后一条 %s  %s" % (tag, len(items), last["ts"], last["rest"][:70]))

    want_raw = getattr(args, "raw", False)
    if want_raw or len(entries) <= 40:
        print("\n全部记录：")
        for e in entries:
            print("  [%s] %s" % (e["ts"], e["body"]))
    else:
        print("\n（%d 行，加 --raw 看全部）" % len(entries))

    spec = getattr(args, "expect", None)
    table = getattr(args, "expect_file", None)
    if spec and table:
        print("\n[错误] --expect 和 --expect-file 只能给一个。")
        return 2
    if table:
        rows, errors = parse_expect_file(table)
        if errors:
            print("\n[错误] 期望表有问题（没有判读）：")
            for e in errors:
                print("  - %s" % e)
            return 2
        return report_expect_file(entries, rows, table, verbose=getattr(args, "verbose", False))
    if spec:
        ok, rows, missing = check_expect(entries, spec)
        print("\n对期望值：")
        for k, want, actual, sec in rows:
            mark = "✓" if sec is not None and abs(float(_num(actual)) - float(_num(want))) < 1e-6 else "✗"
            where = "" if sec is None else "（%ds 那次）" % (sec - entries[0]["sec"])
            print("  %s %s 期望 %s / 实际 %s%s" % (mark, k, want, actual, where))
        if missing:
            print("  没出现的键：%s" % "、".join(missing))
        print("\n结论：%s" % ("通过" if ok else "不通过"))
        return 0 if ok else 1
    return 0


def _age_minutes(path):
    import time
    try:
        return (time.time() - os.path.getmtime(path)) / 60.0
    except OSError:
        return None


def _mtime_str(path):
    import time
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(path)))
    except OSError:
        return ""


if __name__ == "__main__":           # 单独跑：python tools/logread.py [--raw]
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir")
    ap.add_argument("--file")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--expect")
    ap.add_argument("--expect-file", dest="expect_file", help="期望表 .tsv（格号/结构说明/期望/容差/依据/备注）")
    ap.add_argument("-v", "--verbose", action="store_true", help="逐格明细连通过的也列")
    sys.exit(run(ap.parse_args()))
