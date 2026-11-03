"""publish 自检冒烟测试：混淆产物必须仍能通过完整校验。

历史教训（2026-10-22）：
- obfuscate_values 用旧字符串的下标替换，替换后文本变长导致位置错位，
  把 `全局.LifeguardX方向分量` 切成 `全局.LifeX方向分量`，产出无法导入的文件；
- obfuscate_indexes 用 rstrip("0") 格式化，索引 0 会写出 `0.` 这种非法数字；
- publish 自身的 lint 只传了 event_params，比 `ws.py check` 弱，
  上述两个 bug 都没被它拦住，是把检查换成 full_lint 后才暴露的。

M2（v3.38.0）起加第三条：四条 --obf 改写的回归——改名 / 删动作 / 删注释 / 清规则名
只动该动的地方，字符串一字不变。

用法：python tools/selfcheck_publish.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SK = os.path.dirname(HERE)

sys.path.insert(0, HERE)
import console  # noqa: E402

console.harden()

SAMPLE = """设置
{
	模式
	{
		死斗
		{
			启用地图
			{
				地图工坊室内 972777519512064577
			}
			获胜得分: 20
		}
	}
}

变量
{
	全局:
		0: arr

	玩家:
		0: idx
}

规则("自检")
{
	事件
	{
		持续 - 全局;
	}

	动作
	{
		设置全局变量(arr, 数组(1, 2, 3));
		在索引处设置全局变量(arr, 1, 42);
		设置全局变量(arr[1], 7);
		全局.arr[0] = 9;
		等待(0.5, 无视条件);
		记入查看器(自定义字符串("{0}
		", 全局.arr));
	}
}
"""


# --fix 冒烟用的样本：「无」分别落在倒数第二个参数（创建地图文本）和最后一个参数（设置不可见）上，
# 两个槽的数据里都有「全部禁用」，是导出失真的典型形态。
FIX_SAMPLE = """设置
{
	主程序
{
		模式名称: "自检"
	}
}

规则("修复自检")
{
	事件
	{
		持续 - 全局;
	}

	动作
	{
		创建地图文本(所有玩家(所有队伍), 自定义字符串("标题"), 矢量(0, 0, 0), 1, 不要截取, 无, 白色, 默认可见度);
		设置不可见(所有玩家(所有队伍), 无);
	}
}
"""


# ---------- M2 回归：四条改写只动该动的地方 ----------
REWRITE_SAMPLE = os.path.join(HERE, "probes", "samples", "comment-tricky-ok.ow")


def _strings(text):
    """全文的字符串字面量内容（不含引号；注释里的不算），按出现顺序。"""
    NL, BS, QT = chr(10), chr(92), '"'
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            j = text.find(NL, i)
            i = n if j < 0 else j
            continue
        if ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch == QT:
            j, buf = i + 1, []
            while j < n:
                if text[j] == BS and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                if text[j] == QT:
                    break
                buf.append(text[j])
                j += 1
            out.append("".join(buf))
            i = j + 1
            continue
        i += 1
    return out


def _standalone_string_lines(text):
    """独占一行的字符串注释的内容（删注释时整行带走的那类）。

    行尾还挂着 `//` 注释的行也算（`"200救胜利"//开关` 这种在手写模式里很常见）；
    以前的判据要求整行以引号收尾，于是这类行没被减掉，矛头就指向了 strip_comments。
    """
    import publish
    out = []
    for line in text.split(chr(10)):
        code, _cmt = publish._split_line_comment(line)
        s = code.strip()
        if len(s) >= 2 and s[0] == '"' and s[-1] == '"' and s.count('"') == 2:
            out.append(s[1:-1])
    return out


def _code_has_comment(text):
    """代码区还剩没剩下 `//` / `/*`（字符串里的两个斜杠不算）。"""
    import core
    for u in core.split_statements(text):
        if u["kind"] == "comment":
            return True
        for a, b in u["code"]:
            seg = text[a:b]
            if "//" in seg or "/*" in seg:
                return True
    return False


def _code_has_viewer(text):
    """代码区还有没有查看器动作（按语句单元开头判断，跨行也不会漏）。"""
    import core
    for u in core.split_statements(text):
        if u["kind"] != "statement":
            continue
        code = "".join(text[a:b] for a, b in u["code"]).strip()
        if code.startswith(("记入查看器", "启用查看器录制", "禁用查看器录制")):
            return True
    return False


def _is_subseq(needles, haystack):
    """needles 是不是 haystack 的子序列（顺序不变，允许被删，不许被改）。"""
    it = iter(haystack)
    return all(any(x == y for y in it) for x in needles)


def _rewrite_cases():
    """回归输入：自带探针 + 本机配了真实语料就一起上。"""
    files = [REWRITE_SAMPLE]
    try:
        import local_paths
        d = local_paths.corpus_dir()
    except Exception:
        d = os.environ.get("WS_CORPUS", "")
    if d and os.path.isdir(d):
        files += [os.path.join(d, n) for n in sorted(os.listdir(d)) if n.endswith(".ow")]
    return [p for p in files if os.path.isfile(p)]


def check_rewrites():
    """M2 回归（Task 2.1~2.4）：四种 --obf 改写只动该动的东西。

    vars        字符串字面量一字不变（#8 带注释的声明、#17 跨行字符串后的引用）
    comments    剩下的字符串 == 源字符串去掉「独占一行的字符串注释」，注释字符不残留
    viewer      查看器动作清零，字符串按顺序保留（被删语句里的除外）
    rulenames   字符串个数不变、规则名清空、别的字符串一个不动
    """
    sys.path.insert(0, HERE)
    from collections import Counter
    import publish
    import obf_parts
    bad, files = 0, _rewrite_cases()
    for path in files:
        text = open(path, encoding="utf-8").read().replace(chr(13) + chr(10), chr(10))
        src, name = _strings(text), os.path.basename(path)

        out, _n = publish.rename_vars(text)
        got = _strings(out)
        if got != src:
            print("  ✗ vars 改了字符串：%s（%d → %d 个）" % (name, len(src), len(got)))
            bad += 1

        out = publish.strip_comments(text)
        keep = list(src)
        for s in _standalone_string_lines(text):
            if s in keep:
                keep.remove(s)
        got = _strings(out)
        # 同名字符串可能出现在多处，删掉的是哪一处就说不准了 —— 比多重集合，不比顺序
        if Counter(got) != Counter(keep):
            print("  ✗ comments 之后字符串对不上：%s（应 %d 个，实 %d 个）"
                  % (name, len(keep), len(got)))
            bad += 1
        if _code_has_comment(out):
            print("  ✗ comments 之后代码区还有注释：%s" % name)
            bad += 1

        out, _v = obf_parts.strip_viewer_actions(text)
        if not _is_subseq(_strings(out), src):
            print("  ✗ viewer 把字符串改坏了：%s" % name)
            bad += 1
        if _code_has_viewer(out):
            print("  ✗ viewer 之后还有查看器动作：%s" % name)
            bad += 1

        out, _r = publish.blank_rule_names(text)
        got = _strings(out)
        if len(got) != len(src):
            print("  ✗ rulenames 改了字符串个数：%s（%d → %d）" % (name, len(src), len(got)))
            bad += 1
        else:
            moved = [i for i, (a, b) in enumerate(zip(src, got)) if a != b and b != ""]
            if moved:
                print("  ✗ rulenames 动了不是规则名的字符串：%s（第 %s 个）"
                      % (name, moved[:3]))
                bad += 1
    if bad:
        print("✗ 改写回归失败：%d 处" % bad)
        return False
    print("✓ 改写回归：%d 个文件，vars / comments / viewer / rulenames 四条都只动该动的地方"
          % len(files))
    return True


def check_fix(tmp):
    """--fix 冒烟（v3.38.1）：`无` 落在数据里有「全部禁用」的槽上，改完产物必须过完整校验。

    修前这条路一用就崩（`NameError: TEXT_FUNCS`）——只跑 `--obf` 的冒烟永远碰不到它。
    两条入口都走一遍：`ws.py publish --fix`（子命令 + 转发层）与 `publish.py --fix`（直跑）。
    """
    import core
    data = os.path.join(SK, "data")
    src = os.path.join(tmp, "fixable.ow")
    with open(src, "w", encoding="utf-8", newline="") as f:
        f.write(FIX_SAMPLE.replace(chr(10), chr(13) + chr(10)))
    before = [p for p in core.full_lint(src, data) if p[1] == "error"]
    if not before:
        print("\n✗ --fix 冒烟失败：样本本身没报错，验不出修复有没有发生")
        return False
    outdir = os.path.join(tmp, "fixout")
    for cmd in ([os.path.join(HERE, "ws.py"), "publish"],
                [os.path.join(HERE, "publish.py")]):
        r = subprocess.run([sys.executable] + cmd + [src, "--fix", "--outdir", outdir],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        out = r.stdout + r.stderr
        if r.returncode != 0 or "已修复 %d 处" % len(before) not in out:
            print("\n✗ --fix 冒烟失败：%s（exit %s）" % (" ".join(cmd[-2:]), r.returncode))
            print(out.strip()[:800])
            return False
        dst = os.path.join(outdir, "fixable.ow")
        probs = [p for p in core.full_lint(dst, data) if p[1] == "error"]
        if probs:
            print("\n✗ --fix 冒烟失败：修复后的产物还有 %d 个 error" % len(probs))
            for ln, _l, msg in probs[:5]:
                print("   第 %s 行：%s" % (ln, msg))
            return False
        text = open(dst, encoding="utf-8").read()
        if ", 无," in text or ", 无)" in text:
            print("\n✗ --fix 冒烟失败：产物里还剩「无」")
            return False
    print("✓ --fix 冒烟：两条入口都跑通，修复后的产物过完整校验")
    return True


def main():
    tmp = tempfile.mkdtemp(prefix="pubb")
    src = os.path.join(tmp, "sample.ow")
    with open(src, "w", encoding="utf-8", newline="") as f:
        f.write(SAMPLE.replace("\n", "\r\n"))
    r = subprocess.run([sys.executable, os.path.join(HERE, "ws.py"), "publish", src,
                        "--obf", "all", "--outdir", tmp], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    obf = os.path.join(tmp, "sample.obf.ow")
    ok = r.returncode == 0 and os.path.isfile(obf)
    print(out.strip())
    if not ok:
        print("\n✗ 冒烟失败：publish 没有产出可通过校验的混淆版")
        return 1
    # 再独立跑一遍完整校验，确认不是 publish 自己放水
    sys.path.insert(0, HERE)
    import core
    probs = core.full_lint(obf, os.path.join(SK, "data"))
    errs = [p for p in probs if p[1] == "error"]
    if errs:
        print("\n✗ 冒烟失败：混淆版有 %d 个 error" % len(errs))
        for ln, _l, msg in errs[:5]:
            print("   第 %s 行：%s" % (ln, msg))
        return 1
    # 第二条：带 --budget 的 fill（2026-11-02 抓到过 bug：给了 --budget 反而 UnboundLocalError）
    r2 = subprocess.run([sys.executable, os.path.join(HERE, "ws.py"), "publish", src,
                         "--obf", "fill", "--budget", "200", "--outdir", tmp],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    out2 = r2.stdout + r2.stderr
    print(out2.strip())
    if r2.returncode != 0 or "已填充假规则" not in out2 or "总预算 200" not in out2:
        print("\n✗ 冒烟失败：--obf fill --budget 没跑通")
        return 1
    errs2 = [q for q in core.full_lint(obf, os.path.join(SK, "data")) if q[1] == "error"]
    if errs2:
        print("\n✗ 冒烟失败：铺满假规则后混淆版有 %d 个 error" % len(errs2))
        for ln, _l, msg in errs2[:5]:
            print("   第 %s 行：%s" % (ln, msg))
        return 1
    print("\n✓ 冒烟通过：fill --budget 也跑通，产物可校验")
    if not check_fix(tmp):
        return 1
    # 第三条：四条改写的回归（M2：变量改名 / 删查看器动作 / 删注释 / 清规则名）
    if not check_rewrites():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
