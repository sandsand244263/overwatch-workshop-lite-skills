"""publish 自检冒烟测试：混淆产物必须仍能通过完整校验。

历史教训（2026-10-22）：
- obfuscate_values 用旧字符串的下标替换，替换后文本变长导致位置错位，
  把 `全局.LifeguardX方向分量` 切成 `全局.LifeX方向分量`，产出无法导入的文件；
- obfuscate_indexes 用 rstrip("0") 格式化，索引 0 会写出 `0.` 这种非法数字；
- publish 自身的 lint 只传了 event_params，比 `ws.py check` 弱，
  上述两个 bug 都没被它拦住，是把检查换成 full_lint 后才暴露的。

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
	}
}
"""


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
    print("\n✓ 冒烟通过：混淆版可解析、可校验")
    return 0


if __name__ == "__main__":
    sys.exit(main())
