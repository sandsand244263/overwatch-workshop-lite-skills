---
name: WorkshopLite
description: 守望先锋工坊/创意工坊/OW 工坊触发：Overwatch Workshop `.ow` 代码生成、审查、调试与校验。
version: 3.20.0
author: 用户
platforms: [windows]
metadata:
  hermes:
    tags: [overwatch, workshop, ow-code]
---

# Overwatch Workshop Lite

## ① 定位

用户是产品经理，agent 是实现者：**玩法好不好玩归用户，本技能只管实现质量**——
能不能导入、跑起来对不对、元素够不够省。不给创意建议，不替用户判断玩感。
用户只做三件事：导入、试玩、提需求。语法、参数、上限、混淆、读数由本技能兜底，
不要让用户盯屏幕、复制日志、自己改代码。

## ② 入口命令（就这五个，其余 `python tools/ws.py --help`）

| 命令 | 干什么 |
|---|---|
| `ws.py intake "<用户原话>"` | 路由：任务类型 / 该跑什么 / 该读什么 / 该查什么 / 别做什么；命中不了退回「其他」 |
| `ws.py check 模式.ow` | 交付前必跑，必须 0 error；`--strict` 会跑未验证检查、有误报 |
| `ws.py locate "游戏报错原文" [--file 模式.ow]` | 报错 → 模板 → 第几行 → 改法（离线，一次到行） |
| `ws.py deliver 模式.ow` | 交付固定三行：文件 / 怎么跑 / 看哪里；有必改就不打印，先修 |
| `ws.py devcheck [--corpus]` | 一条命令跑完全部回归，输出 ≤5 行；发版前必须全绿 |

文档按「你在做什么」查 `docs/INDEX.md`。**不要直接读 `data/` 里的表**——那是工具的数据源，用命令查。
实测只走 `记入查看器` + `ws.py readlog`：读数自己取，不要用户复制屏幕或贴日志。
开工前 `ws.py upgrade --check` 看版本；**升级前先发版本地改动**，否则 `tools/` 被远端覆盖。

## ③ 事实优先级

**实机读数 > `data/` 表 > `docs/` > 逆向推断。**
冲突以实机读数为准，并且必须回来改表——只改结论不改表，下一轮还会错在同一个地方。

## ④ 证据档位

报错表 `data/errors-full.tsv` 每条带档：**A 档**（解析器级，exe 里有引用点）/
**B 档**（导入界面提示，exe 无引用点）/ **C 档**（补录的界面文案）。
**B/C 档只做报错翻译，不做判据；检查规则只许引用 A 档**（`gen_errors.py` 已断言）。
断言表 `docs/rules.tsv` 每条带 L0~L3：只有 L2/L3（实机导入成功 / 行为有读数）能当结论，
L0/L1 只能说「未验证」。查表用 `ws.py rule <关键词>`，别凭记忆写——散文里可能有过期说法。

## ⑤ 改一条事实的链路

1. 改种子或生成器（`tools/*-src.tsv`、`tools/gen_*.py`）——**不许手改 `data/`**；整库数据更新走 `workshop-data-update` 技能
2. 重生成：`python tools/gen_<表>.py`（整库重建用 `ws.py gen`）
3. 回归：`python tools/ws.py devcheck`，必须全绿、生成器无漂移
4. 文档同步：`docs/rules.tsv` 那一行 + 对应 `docs/` 篇目 + `CHANGELOG.md`
5. 发版：`VERSION` / `SKILL.md` / `CHANGELOG.md` 三处版本号对齐，公开仓与私有仓同版本

## ⑥ 五条铁律

1. **执行模型**：规则只在「条件由假变真」那一刻跑一次；要持续做事必须 `While(真)` + `等待`。
   事件规则同一时刻只有一份在执行，期间同类事件被丢弃 → 事件里只记标记，循环放另一条 `持续 - 全局`。
2. **条件块不写整行 `!(A && B)`**：改写 `(...) == 真` / `!= 真`，或拆成多条。
3. **混淆不许手工改**：只走 `ws.py publish 模式.ow --outdir out --obf all`；字符串混淆交 VS Code 插件。
4. **交付前 `check` 必须 0 error**，一次粘贴导入成功才算交付；报元素成本要说清省在哪、并声明是估算（真实模式偏低 4%~19%）。
5. **`data/` 禁止手改**：只由生成器产出；`docs/` 才是手写知识。
