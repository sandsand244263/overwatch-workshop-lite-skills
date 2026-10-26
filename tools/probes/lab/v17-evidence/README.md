# v17 探针包（9 个文件 / 12 格）

这一包只做一件事：把 11 条「只有文档依据」的校验检查，逐个换成实机读数。
**每格只看一个数**，读数走 `记入查看器`，不靠截图。

- 设计表（哪一格证明什么、期望怎么写才叫证伪）：`workshop-lite-re/v17-re/S3-probe-design.tsv`
- 每个 `.ow` 旁边有同名 `.expect.tsv`，判读时直接喂给 `readlog`

## 怎么跑

```bash
# 1) 校验（这一包全部 0 error，有 0~1 条提示是正常的）
cd E:/工作内容/11_vibe-coding项目/workshop-lite
for f in tools/probes/lab/v17-evidence/*.ow; do python tools/ws.py check "$f"; done

# 2) 进游戏：自定义游戏 → 设置 → 导入代码，逐个导入
#    跑够 20 秒左右，退到大厅再退游戏（别直接结束进程）

# 3) 判读（用户一导入就盯目录，写完自动判读）
python tools/ws.py readlog --watch --expect-file tools/probes/lab/v17-evidence/P8-percent-modulo.expect.tsv
```

**口径**（E-92 勘误后统一）：没报错＝能导入；有日志＝真跑起来了；被拒本身是证据。
大厅不会弹「设置无效」这种提示，判「设置被不被接受」只看能不能启动。

## 九格

写法上 12 格里 **7 格是计数格**（`全局.cN = 全局.cN + 1`，读数=次数）、**5 格是采样格**
（c4/c5 存字符串长度、c9 存改写后的锚点值、c10/c11 存读回来的变量值）。
采样格没法写成计数器——它们要量的是「值是多少」而不是「跑了几轮」；每格仍然只有一个专属变量、
只有一处写、每秒打点一次，读数归属一样清楚。

| 文件 | 格 | 验什么 |
|---|---|---|
| `P7-lobby-team-ffa.ow` | c1 | 团队模式（攻击/护送）+ 自由混战人数上限 2，能不能进比赛 |
| `P8-percent-modulo.ow` | c2 / c3 | `%` 是取余运算符（50%7=1 涨、50%5=0 不涨） |
| `P9-string-interp.ow` | c4 / c5 | 模板占位符比实参多一个，字符串长度差多少 |
| `P10a-prestart-damage.ow` | c6 | 持续-全局 首句就 伤害，有没有人真的掉血 |
| `P10b-prestart-damage-gated.ow` | c7 | 同一句伤害加守门后掉不掉血（尺子） |
| `P11-no-settings-block.ow` | c8 | 没有 设置 块能不能导入并跑起来 |
| `P12-lazy-display.ow` | c9 | 大字体信息 显示后立刻改写，屏幕上是旧值还是新值（**肉眼看屏幕**） |
| `P13-case-var-names.ow` | c10 / c11 | `Temp` 与 `temp` 是不是同一个变量 |
| `P14-long-subroutine-name.ow` | c12 | 39 字符的子程序名能不能用 |

## 没做成探针的部分（别当成忘了）

这三条整条、五个分支验不了，理由都写在设计表里（`格号 = —`）：

- `check_balance`（括号配对）：要验的就是「括号数不等」，探针必被自家 check 判 error，与「0 error」冲突
- `check_duplicate_blocks`（顶层块重复）：同上
- `check_var_refs` 的「`全局.X` 点号引用未声明」分支：同上（裸名分支已有 E-92 实机）
- `check_percent_operator` 的「`50%` 被拒」分支、`check_misc` 的 `};` 与 地图 id 0 两个分支、
  `check_name_too_long_raw` 的变量名分支、`check_lobby_ffa_slots` 的死斗分支：全部是 error 级，同样冲突

## 顺手发现的盲区（写代码的人该看）

1. `check_lobby_ffa_slots` 只认 `TEAM_MODES` 里那 10 个名字，`攻击/护送`（mode-list 里的正式写法带斜杠）认不出 → 不判。
2. `check_duplicate_blocks` 的正则要求块名独占整行、行首无缩进，第二块缩进写就看不见。
3. `check_name_too_long_raw` 的两个分支都够不着：变量分支被 `core.py:5144` 的 error 级同名检查遮住；
   `子程序("…")` 那个写法在 .ow 格式里根本不存在（真实写法是 `子程序 { 1: 名字 }`）。
4. `check_lazy_display` 的 docstring 说也管 `记入查看器`，函数体只 grep `大字体信息`。
5. `check_string_interp` 只认单位数占位符（`\{(\d)\}`），`{10}` 以上不判。

这些都不在本轮改动范围内（不动 `core.py`），留给下一轮定夺。
