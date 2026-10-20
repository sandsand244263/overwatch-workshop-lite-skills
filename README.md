# workshop-lite

> 查工坊语法不用翻几十页的官方文档了。

守望先锋工坊 `.ow` 脚本的参考知识库——生成、审查、解释、调试，一个 skill 搞定。

**注意：本 skill 仅支持中文。** 所有参考文档、函数名、示例均为中文，英文用户不适合。

当前版本 **v1.4.0**，更新内容见 [CHANGELOG.md](./CHANGELOG.md)。

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
| **审查** | 检查结构、索引、循环、等待行为、元素预算，走完 52 条避坑清单 |
| **解释** | 逐条规则解释代码在做什么 |
| **调试** | 用 `记入查看器` 探针定位问题，不靠猜 |

---

## 文件结构
```
workshop-lite/
├── SKILL.md                      技能入口，定义工作流和触发条件
├── agents/
│   └── openai.yaml               Agent 界面配置（图标、颜色、默认提示词）
├── assets/
│   ├── workshop-lite-small.svg    小图标
│   └── workshop-lite-large.svg    大 logo
├── references/
│   ├── golden.ow                  游戏「复制脚本」导出的真实文件，格式唯一基准
│   ├── sources.md                 权威资料分级与下次更新的检查顺序
│   ├── format-spec.md             格式规范：骨架、硬规则、报错对照（先读这个）
│   ├── signatures.md              全部动作与值函数的参数签名（225 + 266 条）
│   ├── syntax.md                  语法参考（结构、事件、变量、控制流、导入差异）
│   ├── actions.md                 动作函数详解与完整名称表（225 个）
│   ├── values.md                  条件/值函数参考（264 个 + 常量）
│   ├── strings.md                 616 条内置 `字符串(...)` 词条
│   ├── enums.md                   英雄/地图/按钮/交流/模式/扩展枚举 + 数据基线
│   ├── patterns.md                设计模式与代码质量要求
│   ├── pitfalls.md                55 条必查避坑清单
│   ├── ui-notes.md                HUD/UI 排版说明
│   ├── diagnostics.md             注释语法与调试工作流
│   ├── element-costs.md           元素成本参考表
│   └── element-audit.md           元素审查规则
├── scripts/
│   └── lint_ow.py                 格式校验器：交付前必跑，退出码 0 才算完成
├── .claude-plugin/
│   └── marketplace.json           Claude Code 市场注册
├── README.md                      本文件
└── LICENSE                        MIT
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

装完后跑这条 prompt 即可验证：

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
