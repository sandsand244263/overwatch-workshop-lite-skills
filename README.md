# workshop-lite

> 写守望先锋工坊模式，不用背 225 个动作函数的参数。

`.ow` 脚本的参考知识库 —— 生成、审查、解释、调试，一个 skill 搞定。

**仅支持中文。** 所有参考文档、函数名、示例均为中文，英文用户不适用。

当前版本 **v2.22.0**，更新见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 它解决什么问题

写过 `.ow` 的人都知道：

- 225 个动作、267 个值函数，参数顺序错一个就报"应有一个关系运算子"
- 615 条内置 `字符串(...)` 词条，编一个不存在的就导入失败
- 54 个英雄、291 张地图、370 条房间设置项，写在哪一层全靠试
- 元素预算 32768，超了才知道，而且不知道哪一步最贵
- 代码能跑但就是不对，半天找不到坑

遇到这些，不用切出去翻文档，直接问。

---

## 快速开始

```bash
npx skills add sandsand244263/overwatch-workshop-lite-skills
```

装完对 AI 说：

> 帮我生成一个钩子判定规则

或者：

> 审查这段 .ow 代码

---

## 能做什么

| 模式 | 说明 |
|---|---|
| **生成** | 按需求出完整 `.ow`，沿用你已有的命名与结构 |
| **审查** | 结构 → 条件写法 → 数组索引 → 逻辑时序，逐层过 |
| **解释** | 逐条规则说明事件、关键条件、状态变量、可见效果 |
| **调试** | 用 `记入查看器` 打点，按最小可疑点收敛，不盲改 |
| **省元素** | 算出当前用量，给出更省的等价写法 |
| **出发布文件** | 源码版，按需再出混淆版 |

---

## 文件结构

```
workshop-lite/
├── SKILL.md                     技能入口：目录契约、入口命令、工作流、生成纪律
├── data/                        游戏导出生成，禁止手改
│   ├── signatures.md              225 动作 + 267 值函数的参数签名（含类型与下拉值）
│   ├── settings.tsv               370 条设置项：schema / 键 / 类型 / 可选值
│   ├── schema-keys.tsv            475 条：schema → 键名，设置项归属的权威来源
│   ├── mode-pages.tsv             1243 行：55 个模式的分页与键顺序（页序/键序取自数据数组下标）
│   ├── hero-pages.tsv             1918 行：54 个英雄的分页与键顺序
│   ├── lobby-keys.tsv             大厅 12 键（数据侧无出处，来自实测样本）
│   ├── mode-schemas.tsv           137 个模式 → 各自的 schema 列表
│   ├── hero-schemas.tsv           135 个英雄 → 各自的 schema 列表
│   ├── maps.tsv                   291 张地图 + GUID + 变体标记
│   ├── events.tsv                 14 个事件 + 参数位
│   ├── strings.md                 615 条内置 `字符串(...)` 词条
│   ├── defaults.tsv               每个参数省略时的默认值
│   ├── dropdowns.tsv              下拉参数在编辑器里的常用候选值（非唯一合法值）
│   ├── enums.md                   英雄 / 地图 / 下拉选项全集
│   ├── action-tags.tsv            484 个动作的功能分类
│   ├── settings-blocks/           8 份实测导入成功的设置块模板
│   └── meta.json                  数据基线：build、导出日期
├── docs/                        数据里没有的知识，手写
│   ├── format-spec.md             格式规范：骨架、硬规则、报错对照（先读这个）
│   ├── syntax.md                  语法参考
│   ├── pitfalls.md                执行机制陷阱：循环、等待、数组、事件
│   ├── patterns.md                设计模式与可套用骨架
│   ├── cost-patterns.md           省元素与省性能的手法
│   ├── limits.md                  容量上限 + 元素估算公式
│   ├── settings-map.md            设置界面六分区与层级来源
│   ├── diagnostics.md             注释语法与调试流程
│   ├── ui-notes.md                HUD / UI 排版
│   ├── basics.md                  常识与已知 bug
│   ├── ecosystem.md               周边工具分工
│   └── sources.md                 资料可信度分级
├── tools/
│   ├── ws.py                      唯一入口（见下）
│   ├── core.py                    解析与校验引擎
│   ├── publish.py                 出发布文件（源码版 / 混淆版）
│   ├── element_count.py           元素数估算（25 个探针标定，25/25）
│   ├── gen_data.py                从游戏导出重新生成 data/
│   ├── enrich.py                  派生表：events / action-tags / maps
│   ├── export_data.py             一条命令导出四份 JSON
│   ├── data_diff.py               两版导出全量对照
│   └── probes/                    44 个实测样本（改校验器后必跑）
├── .github/workflows/check.yml    push 与 PR 自动跑回归
├── .claude-plugin/marketplace.json  Claude Code 市场注册
└── LICENSE                        MIT
```

---

## 命令

```bash
python tools/ws.py check 模式.ow                        # 校验，交付前必跑，必须 0 error
python tools/ws.py count 模式.ow                        # 元素数估算
python tools/ws.py defaults 创建HUD文本                  # 查参数默认值
python tools/ws.py publish 模式.ow --outdir out          # 源码版
python tools/ws.py publish 模式.ow --outdir out --obf numbers,vars   # 加一份混淆版
python tools/ws.py baseline                             # 数据基线与游戏版本比一比
python tools/ws.py check-all                            # 回归全部样本
python tools/ws.py gen --src <导出目录>                  # 重新生成 data/
python tools/ws.py diff --prev <旧> --cur <新>           # 两版数据全量对照
```


## 如何更新

这个 skill 是拷贝安装，不会自动升级。想更新时重跑一次安装命令即可（覆盖旧版本）：

```bash
npx skills add sandsand244263/overwatch-workshop-lite-skills
```

**怎么知道该不该更新**

- 每次校验代码时，如果仓库有新版本，会附一行提示（24 小时查一次，没网就静默跳过）
- 游戏更新后跑 `python tools/ws.py baseline`：数据基线跟不上游戏版本，就该更新了
- 也可以手动查：`python tools/ws.py update-check`

---

## 验证与测试

### 生成后自检（必做）

```bash
python tools/ws.py check 你的文件.ow
```

只认 0 error。检查项：括号配对、语句分号、尾逗号、条件比较、变量名英文、变量声明与引用、未知函数名、参数个数、事件块行数（全局 1 / 其它 3 / 子程序 2）、子程序是否声明、地图 id 是否为 0、占位符是否超过 `{2}`、变量与子程序数量与索引上限、设置项的值是否合法。

### 回归自检

```bash
python tools/ws.py check-all
```

44 个样本，全部 0 error。CI 在每次 push 与 PR 时自动跑。

### 已验证到什么程度

| 层 | 状态 |
|---|---|
| 格式（块结构、标点、变量两段、事件行数） | 实测导入通过 |
| 名字与参数（动作 / 值 / 枚举 / 字符串） | 由游戏数据生成，校验器按表判 |
| 设置项的词与归属 | `schema-keys.tsv` + 校验器 |
| 元素数 | 25 个探针标定，估算与实测 **25/25 一致**；最终以游戏诊断为准 |
| 运行时行为（HUD 刷新、计分、循环） | 部分实测（见 `docs/pitfalls.md`），其余需开一局验证 |

### 人工验证 prompt

> 创建一个「开始治疗调整」的规则，对事件玩家生效，持续 5 秒，每秒治疗 50

---

## 数据来源

名词表（动作、值函数、枚举、字符串词条）全部来自游戏本体，用 [overtools/OWLib](https://github.com/overtools/OWLib) 的 DataTool 从本机游戏导出：

```
DataTool "<游戏目录>" list-workshop --language zhCN --rcn --json --out=workshop.json
```

- `--language zhCN` 简体中文；`--rcn` 国服客户端
- 导出含 `Actions` / `Values` / `Dropdowns` / `TextOptions` / `Extensions` 五类
- 数据基线：**国服 2.25.0.1.154504**
- 设置项结构另由 `list-game-ruleset-schemas`、`list-gamemodes`、`list-heroes-rulesets` 导出

中文名词同时参考 [XHanL/overwatch-workshop](https://github.com/XHanL/overwatch-workshop)（MIT），一个工坊 VS Code 扩展。感谢 [@XHanL](https://github.com/XHanL)。两者不一致时以游戏数据为准。

### 相关项目

| 项目 | 状态 | 说明 |
|---|---|---|
| [overtools/OWLib](https://github.com/overtools/OWLib) | 维护中（MIT） | 上游导出工具，直接读游戏文件 |
| [XHanL/overwatch-workshop](https://github.com/XHanL/overwatch-workshop) | 维护中（MIT） | 中文名词来源 |
| [SkyinHand/owatch](https://github.com/SkyinHand/owatch) | 2021 后停止 | 第一代中文工坊插件 |
| [qaz075115961/owl-CN](https://github.com/qaz075115961/owl-CN) | 2024 后停止 | owatch 的延续 |

### 元素成本

不是暴雪公开常量，来自作者在工坊内的实测标定（25 个「同模板只改一处」探针，结果 25/25 命中）。

---

## 安全边界

- 不修改你的 `.ow` 文件
- 不联网取数据，全部参考数据打包在 skill 内，可离线用
- 代码不上传任何外部服务

---

## 版权与合规

- 本技能**不包含**游戏本体文件、美术资源、音频或任何加密材料；只包含从游戏客户端导出的**名称与数值**（动作名、参数、设置项、地图名等），用于辅助撰写与校验 `.ow` 文本。
- 名称、数值与商标归 Blizzard Entertainment 所有；本项目与 Blizzard 无关联、未获其背书。
- 使用前请自备合法购买的游戏副本。本工具不改变、不破解、不绕过游戏的任何运行机制，也不与游戏进程交互。
- 若权利人认为内容不妥，请通过 Issue 联系，会及时处理。

## License

[MIT](./LICENSE)
