---
name: WorkshopLite
description: 守望先锋工坊/创意工坊/OW 工坊触发：Overwatch Workshop `.ow` 代码生成、审查、调试与校验。
version: 3.12.1
author: 用户
platforms: [windows]
metadata:
  hermes:
    tags: [overwatch, workshop, ow-code]
---

# Overwatch Workshop Lite

写 `.ow` 工坊代码。**用户只做三件事：导入、试玩、提需求。**
语法、参数、设置项、元素预算、混淆、实测读数都由本技能兜底——不要反过来让用户盯屏幕或复制日志。

## 四条判定原则（写码前先过一遍）

1. **执行模型**：规则在「条件由假变真」那一刻执行一次。无条件 = 开场一次；一直为真不重复。
   要持续做事必须 `While(真)` + `等待`（只加 `等待` 不算循环）。「条件成立时做一下」用 `条件` 块。
2. **每名玩家 = 每人一个实例**：条件边沿、`While` 循环、玩家变量都是实例私有，后加入的玩家补一个实例。
   按玩家写的计数器**不用除以人数**——加一次就是一个人头。
3. **事件规则单实例**：事件动作里写长 `While`，期间的同类事件被直接丢弃（不排队、不重入）。
   要「触发一次、慢慢处理」→ 事件里只记标记，循环放到另一条 `持续 - 全局` 里轮询。
4. **动作目标慎用 `本地玩家`**：`伤害` / `隐藏英雄HUD` / `开始镜头` 写在 `持续 - 全局` 里对 `本地玩家` 无效
   （HUD 文本、玩家过滤、距离计算可以用）。这类「动身体/视角」的动作放 `每名玩家` + `事件玩家`。

每条都有实机读数，依据查得到：`python tools/ws.py rule <关键词>`（断言表 `docs/rules.tsv`，29 条）。
**别凭记忆写**——断言表是唯一可查入口，散文里可能有过期说法。

**断言表带证据等级，说话必须对上等级：**

| 等级 | 含义 | 能不能当结论 |
|---|---|---|
| L0 | 数据里有 | 不能，只能说「未验证」 |
| L1 | 结构成立、check 能过 | 不能，还没跑过 |
| L2 | 实机导入成功 | 能说「这条路存在」 |
| L3 | 行为符合预期（有读数） | 能说「这么做能达成效果」 |

不知道某个效果能不能做：`python tools/ws.py verify`（列还没验的）→
`verify --scaffold 10 --out 验证.ow`（生成 10 格探针）→ 用户跑一次 → `readlog --expect` 判 →
`verify --set <场景> --level L3 --evidence E-54` 回填。**一次导入验 8~12 条，别一条一条问用户。**

## 命令

```bash
python tools/ws.py check 模式.ow                       # 交付前必跑，必须 0 error
python tools/ws.py fix 模式.ow --fix-bools             # 导出文件修成可导入（导出文件不能直接导）
python tools/ws.py readlog [--raw|--expect "c1=2"]     # 读工坊日志：实测读数自己取
python tools/ws.py rule <关键词>                       # 查断言表（带证据等级 L0~L3）
python tools/ws.py verify [--scaffold 10 --out X.ow]  # 列出/生成还没验的断言验证探针
python tools/ws.py scaffold --rule 名字 --out X.ow     # 起测试骨架（自带房间设置）
python tools/ws.py count 模式.ow                       # 元素估算（真实模式偏低 4~19%，靠近上限别赌）
python tools/ws.py doc <动作>                          # 官方说明 + 每个参数的可选值
python tools/ws.py reveal 文件                         # 交付测试文件（记事本直接打开）
python tools/ws.py upgrade --check                     # 开工前看版本；升级前先发版本地改动，否则被覆盖
```

环境类问题先 `python tools/ws.py doctor`；用户认为误报时用 `report 文件` 生成脱敏复现片段。

## 路由（先看这张表，别整目录读）

| 用户的话 / 我在做什么 | 跑什么 | 读什么 |
|---|---|---|
| 「写个 XX 模式」 | `scaffold` 起手 → 写完 `check` | `docs/patterns.md` |
| 「这个导不进去」/ 贴了游戏报错 | `check` | `docs/errors.md`（报错原文 → 真因 → 改法） |
| 能导入但行为不对 | `readlog` 取读数 → `rule` 查写法 | `docs/pitfalls-runtime.md` |
| 写动作、字符串、变量、数组 | `doc <动作>` | `docs/pitfalls-syntax.md`、`docs/syntax.md` |
| 动地图 / 时段 / 模式名 | `map-code` | `docs/pitfalls-map.md` |
| 设置块怎么写 | `settings --mode X` | `docs/settings-map.md` |
| 元素快超了 | `count` | `docs/limits.md`、`docs/cost-patterns.md` |
| 要开扩展 | `settings` | `docs/extensions.md` |
| 怀疑导出失真 | `fix` | `docs/pitfalls-export.md` |
| 用户不知道怎么导出/导入 | — | `docs/ui-workflow.md`、`docs/quickstart.md` |
| 要加探针 / 要发版 | — | `docs/acceptance-flow.md` |
| 想改校验器 / 判断可信度 | — | `docs/validator-coverage.md` |
| 调英雄数值 | `stats <英雄>` | `docs/hero-stats.md` |

全部文档按「你在做什么」排：**`docs/INDEX.md`**（含 `data/` 文件清单）。
**不要读 `data/` 里的表**——那是工具的数据源，用命令查。

## 测试与探针（用户只导入，不观察、不复制）

- **自带房间设置、点开始就跑**：`scaffold` 起手（死斗 + 工坊室内 + `游戏模式开始: 即时` + `随机英雄复生: 开启`）。
  只给工坊代码让用户自己配房间，结论不可比。
- **输出只用 `记入查看器`**：记录会落到 `%USERPROFILE%\Documents\Overwatch\Workshop\Log-*.txt`，
  用 `ws.py readlog` 自己读，`--expect "c1=2,c2=2"` 直接判对错。**不要要用户复制粘贴。**
  用户跑完要退回大厅再退游戏，否则可能不落盘；真拿不到才退回人工。
- **屏幕隐蔽**：单独一条 `持续 - 每名玩家` 规则，循环里每 0.5~1 秒重设
  `隐藏英雄HUD(事件玩家)` / `隐藏游戏模式HUD(事件玩家)` / `开始镜头(事件玩家, 矢量(0,50,0), 矢量(0,200,0), 100)`。
  写在全局规则里配 `本地玩家` 无效；`设置不可见` 也不管用。
- **一切自证**：要验证的东西必须变成查看器里的一行数字（ID、数量、真假），
  不留「请看屏幕上有没有」「请按某个键」「请走过去踩一下」。
- 一次性探针放 `tools/probes/lab/<主题>/`，配 `README.md` 写清问题、对照方式、读数怎么判。

## 两条 check 管不到的铁律

- **条件块不写整行 `!(A && B)`**：改写 `(...) == 真` / `!= 真`，或拆成多条。
- **混淆不许手工改**：`ws.py publish 模式.ow --outdir out --obf all` 一次出源码版 + 混淆版（300 条规则 0.21 秒）。
  手工替换几千处必然改坏引用。字符串混淆本脚本不做（会改变比较语义），交 VS Code 插件。

## 交付标准

- `ws.py check` 0 error，一次粘贴导入成功。
- 只说三样：**文件 + 一句怎么跑 + 一句跑完看哪里**。不解释内部结构，除非用户问。
- 报元素成本要说清省在哪（值 / 条件 / 动作 / 规则结构），并声明是估算。

## 数据与版本

- `data/` 只由 `ws.py gen` / `enrich.py` 生成，**禁止手改**；`docs/` 是数据里没有的知识（手写）；`tools/` 只有 `ws.py` 一个入口。
- 判据：**数据决定「存在什么」，实测决定「能不能导入」**；两者冲突以实测为准，并写进 `docs/`。
- 游戏更新后先 `ws.py baseline`；不一致说明数据过期，去仓库拉新版。
- `check` 会顺带查一次新版本（24 小时缓存，没网静默跳过）。
- 发版前：`selftest` + `check-all`（看「正样本 N 个：N 通过」那一行）+ `calib`。

## 相关技能

数据更新走 `workshop-data-update`（导出 → 对照 → 生成 → 回归 → 发版）。
