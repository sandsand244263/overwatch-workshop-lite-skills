# workshop-lite

> 查工坊语法不用翻几十页的官方文档了。

守望先锋工坊 `.ow` 脚本的参考知识库——生成、审查、解释、调试，一个 skill 搞定。

**注意：本 skill 仅支持中文。** 所有参考文档、函数名、示例均为中文，英文用户不适合。

当前版本 **v2.8.1**，更新内容见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 它解决什么问题

写过 `.ow` 的人都知道：

- 225 个动作函数、264 个条件/值函数，谁能全记住？
- 611 条内置 `字符串(...)` 词条，多了记不住、编了又不认
- 52 个英雄、36 种交流枚举、参数顺序一错就报"应有一个关系运算子"
- 元素预算动不动超限，到底哪一步最贵？
- 代码能跑但就是不对，半天找不到坑在哪

遇到这些问题，你不需要切出去翻文档。直接在对话里问 workshop-lite。

---

## 快速开始

```bash
npx skills add sandsand244263/overwatch-workshop-lite-skills
```

装完后对 AI 说：

> 帮我生成一个钩子判定规则

或者：

> 审查这段 .ow 代码

---

## 触发方式

和这个 skill 对话时，直接说你要干什么就行：

- "帮我生成一个 `创建HUD文本` 的规则"
- "审查这段 .ow 代码，看有没有元素超限"
- "解释一下这个规则在做什么"
- "调试这段代码，钩子判定有问题"
- "帮我优化一下元素预算"
- "检查一下这段代码有没有索引陷阱"

---

## 能做什么

| 模式 | 说明 |
|------|------|
| **生成** | 根据需求生成完整的 `.ow` 规则，匹配你的命名和结构 |
| **审查** | 检查结构、索引、循环、等待行为、元素预算，走完 `docs/pitfalls.md` 的避坑清单 |
| **解释** | 逐条规则解释代码在做什么 |
| **调试** | 用 `记入查看器` 探针定位问题，不靠猜 |

---

## 文件结构

```
workshop-lite/
├── SKILL.md                    技能入口：目录分工、工作流、生成纪律、交付标准
├── data/                       全部由脚本从游戏导出生成，文件头带 build 与日期，禁止手改
│   ├── signatures.md             动作 225 + 值函数 267 的参数签名，下拉参数直接标可选值
│   ├── defaults.tsv              每个参数的默认值（省略尾部参数时游戏实际填什么）
│   ├── dropdowns.tsv             每个下拉参数的候选值（只作参考，非唯一合法值）
│   ├── settings.tsv              设置项：分类 / 键 / 类型 / 可选值
│   ├── enums.md                  英雄 54 / 地图基版与节日变体 / 下拉选项全集
│   ├── strings.md                623 条内置 `字符串(...)` 词条
│   └── meta.json                 数据基线：build、导出日期、各表条数
├── docs/                       数据里没有的知识，手写
│   ├── format-spec.md            格式规范：骨架、硬规则、报错对照（先读这个）
│   ├── syntax.md                 语法参考（结构、事件、变量、控制流、导入差异）
│   ├── pitfalls.md               必查避坑清单
│   ├── patterns.md               设计模式与代码质量要求
│   ├── diagnostics.md            注释语法与调试工作流
│   ├── limits.md                 硬上限：元素 32768 / 规则 98KB / 变量与子程序各 128
│   ├── element-costs.md          元素成本实测参考表
│   ├── element-audit.md          元素超预算时的降级顺序
│   ├── ui-notes.md               HUD/UI 排版说明
│   ├── settings-map.md           设置项老 BUG：导出器写 启用/禁用，导入器只认 开启/关闭
│   ├── ecosystem.md              周边工具分工（VS Code 插件 / workshop.codes / overpy / OWLib）
│   └── sources.md                权威资料分级与更新检查顺序
├── tools/
│   ├── ws.py                     唯一入口：check / count / defaults / publish / gen / diff
│   ├── core.py                   解析与校验引擎（读 data/，不含手抄名字表）
│   ├── publish.py                出发布文件（默认源码版，按需混淆版）
│   ├── obfuscate_values.py       数值混淆（等价改写）
│   ├── element_count.py          元素数估算（数量级预警）
│   ├── gen_data.py               从游戏导出重新生成 data/
│   ├── data_diff.py              两个导出目录全量对照
│   └── probes/                   实测导入通过的探针与真实样本（改校验器后必跑）
├── agents/openai.yaml          Agent 界面配置
├── assets/                     图标与 logo
├── .claude-plugin/marketplace.json  Claude Code 市场注册
├── README.md                   本文件
└── LICENSE                     MIT
```

---

## 英雄列表

英雄列表已由**游戏本体一手数据**对齐，共 **54 名**（重装 15 / 输出 23 / 支援 16）。

- 第 4 赛季新增重装 **D.Mon**，第 5 赛季新增支援 **血律**
- 第 5 赛季「黑影」由输出改为 **支援**，本表已按游戏现状归类
- 数据来源见下方「数据来源」一节；发现遗漏欢迎提 Issue

> 对齐基准：国服 2.25.0.0.154461（用 OWLib 的 `list-heroes` / `list-workshop` 导出）。

---

## 安全边界

- **不会主动修改你的 `.ow` 文件**——你给代码，它给建议/生成，你自己决定改不改
- **不会联网获取数据**——所有参考数据打包在 skill 内，离线可用
- **不会发送你的代码到外部**——处理都在你本地完成

---

## 验证与测试

### 生成后自检（必做）

```bash
python tools/ws.py check 你的文件.ow
```

只认 0 error。检查项：括号配对、语句分号、尾逗号、条件比较、变量名英文、变量声明与引用、未知函数名、参数个数（不超过）、事件块行数（1 / 3 / 子程序 2）、子程序是否声明、地图 id 是否为 0、占位符是否超过 `{2}`、变量与子程序索引与数量上限、设置项的值是否合法（按 `data/settings.tsv`）。

### 其他命令

```bash
python tools/ws.py count 你的文件.ow                    # 元素数估算（数量级预警）
python tools/ws.py defaults 创建HUD文本                  # 查参数默认值
python tools/ws.py publish 模式.ow --outdir out          # 出源码版
python tools/ws.py publish 模式.ow --outdir out --obf numbers,vars   # 额外出混淆版
python tools/ws.py gen --src <游戏导出目录>              # 重新生成 data/
python tools/ws.py diff --prev <旧导出> --cur <新导出>    # 全量对照，检测官方暗改
```

### 回归自检（改校验器或数据后必做）

```bash
python tools/ws.py check tools/probes/*.ow tools/probes/calib/*.ow
```

对 24 个样本要求全部 0 error：3 个实测导入通过的探针 + 3 个真实模式样本 + 18 个元素标定探针。

### 已验证的范围

| 层 | 状态 |
|---|---|
| 格式（块结构、标点、变量两段、事件 1/3 行、子程序两行事件） | 实测导入通过 |
| 名字与参数（动作/值函数/枚举/字符串） | 由游戏数据生成，校验器按表判 |
| 设置项的词（含导出器把布尔写成 `启用/禁用` 的老 BUG） | 数据表 + 校验器 |
| 元素数估算 | **数量级预警**，精确值以游戏「显示诊断结果 → 总计元素数量」为准 |
| 运行时行为（HUD 是否刷新、击杀是否计分） | **未覆盖**，需实际开一局验证 |

### 人工验证 prompt

> 创建一个 `开始治疗调整` 的规则，对事件玩家生效，持续 5 秒，每秒治疗 50

---

## 数据来源

### 一手来源：游戏本体（用 OWLib 导出）

本 skill 里的名词表——动作函数、条件/值函数、各种枚举、内置 `字符串(...)` 词条、扩展项——最终都来自游戏本体的工坊数据。

这个数据可以用开源工具 [overtools/OWLib](https://github.com/overtools/OWLib) 里的 DataTool，从**本机已安装的游戏**里直接导出：

```
DataTool.exe "<游戏目录>" list-workshop --language zhCN --rcn --json --out=workshop.json
```

- `--language zhCN` 指定简体中文；`--rcn` 用于国服 / 网易客户端（加载中国区专属内容）
- 导出内容含 `Actions`、`Values`、`Dropdowns`、`TextOptions`、`Extensions` 五类，即本 skill 全部名词的来源
- DataTool 跟随游戏版本更新，通常每月一版。在 [releases](https://github.com/overtools/OWLib/releases) 直接下载 `toolchain-release.zip` 即可，不需要 Discord

### 现成中文成品：XHanL 扩展

本 skill 的**中文名词**同时参考 [XHanL/overwatch-workshop](https://github.com/XHanL/overwatch-workshop)（MIT License），一个守望先锋工坊 VS Code 扩展。感谢 [@XHanL](https://github.com/XHanL)。

数据基线：**游戏本体国服 2.25.0.0.154461**（一手 dump 为准）；XHanL 扩展 3.11.35（源码 `src/web/model.ts`）作为对照，两者不一致处以游戏数据为准。

### 中文工坊工具的前身

| 项目 | 状态 | 说明 |
|---|---|---|
| [SkyinHand/owatch](https://github.com/SkyinHand/owatch) | 2021 年后停止 | 第一代中文工坊插件，用 Python 脚本提取动作函数并自动生成拼音 |
| [qaz075115961/owl-CN](https://github.com/qaz075115961/owl-CN) | 2024 年后停止 | 在 owatch 基础上继续开发 |
| [XHanL/overwatch-workshop](https://github.com/XHanL/overwatch-workshop) | 维护中（MIT） | 当前中文数据来源，名词随游戏新英雄更新 |
| [overtools/OWLib](https://github.com/overtools/OWLib) | 维护中（MIT） | 上游工具，直接从游戏文件导出，跟游戏版本走 |

### 元素成本数据

元素成本来自作者在工坊内的实际测试，非暴雪官方公开常量。

---

## License

[MIT](./LICENSE)
