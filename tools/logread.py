# -*- coding: utf-8 -*-
"""读工坊查看器日志。

游戏自己会把 `记入查看器` 的每一条存成文件：

    %USERPROFILE%\\Documents\\Overwatch\\Workshop\\Log-<年-月-日-时-分-秒>.txt

所以实测拿到读数**不需要用户复制粘贴**——跑完直接读最新那个文件即可。
（2026-10-24 实测，一天产出 35 个文件，格式就是屏幕上的 `[时分秒] 内容`。）

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
    sys.exit(run(ap.parse_args()))
