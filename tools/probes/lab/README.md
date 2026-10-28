# `probes/lab/` 是什么

**这里是「某一轮实机验证」留下的证据档，不是回归样本。**

`check-all` 只扫 `probes/*.ow`（正样本）、`probes/calib/`、`probes/samples/`，
加上 `probes/negative/`（反向用例，清单在 `negative/expect.tsv`）。**整个 `lab/` 不在回归里**——
它跟着某一轮（v13 ~ v18）的实机读数走，改一次校验器不需要它们重跑。

## 三条规矩

1. **新增回归样本别放这儿。** 会挡导入的写坏样本 → `probes/negative/` + `expect.tsv` 加一行；
   能跑的完整模式 → `probes/samples/`。
2. **放这儿的唯一理由是「某条结论有实机读数」。** 目录名带 `vNN-evidence` 的，对应
   `docs/rules.tsv` / `CHANGELOG` 里的 `E-NN`；文件里的 `expect.tsv` 是当时判读用的格子。
3. **别删也别改。** 读数与文件是一对证据，改文件等于改证据；要重新验就新建目录。

## 总览

| 目录 | 是什么 |
|---|---|
| `v13-evidence/` ~ `v17-evidence/` | 各轮的实机探针包（每包有 README 说明验哪几条、怎么读） |
| `v18-rejection/` | 故意写坏 → 导入 → 抄游戏原话（E-95 三格被拒读数） |
| `acceptance/` | 两个「跑一遍就知道这套靠不靠谱」的验收模式（A1/A2） |
| `calib2/` | 元素数模型的第二组标定样本（第一组在 `probes/calib/`） |
| `pricing/` | 元素成本单价推导（同模板只改一处） |
| `runtime-r3/` | 运行时行为读数（阵亡清不清分、HUD 上限等） |
| `endcheck/` | 动作块末尾省 `End;` 的行为读数（E-61） |
| `bisect/` | 某次导入失败的最小化收敛过程 |
| `locate/` | `ws.py locate` 的行号保真用例（`cases.tsv`） |
| `t15/`、`syntax-batch-1/`、`v14-silent/`、`_smoke/` | 批次跑剩的单点样本，来源见各自目录里的 expect/md |

> 用户自己的模式**不要**写进 `lab/`：这里的文件按「证据」维护，不按「模板」维护。
> 写完要验就跑 `python tools/ws.py check 你的.ow`。
