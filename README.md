# workshop-lite

> 让 AI 帮你写、查、修守望先锋工坊模式（`.ow`），不用背 225 个动作的参数。

装好之后你只需要说话，AI 负责查数据、校验、给改法，必要时直接修成能导入的版本。

**仅支持中文。**

当前版本 **v3.8.0**，更新见 [CHANGELOG.md](./CHANGELOG.md)。

---

## 它还知道地图

- **每个模式能用哪些图**：21 个模式、324 条组合，全部经游戏导入验证
- **时段编号**（早晨 / 夜晚 / 傍晚 / 黎明）：19 张图可用，写错会报「无效的地图设置」
- 埃斯佩兰萨、斗兽场两张图的时段编号是坏的（游戏数据缺陷），工具会自动只写地图名

## 装好之后，你能这么用

> **「这个模式导不进去，帮我看看」**
> → 定位到第 44 行：队伍参数不能写「双方」，改成 `所有队伍`

> **「写一个抢点模式，站圈里每秒 +1 分，30 分赢」**
> → 出完整 `.ow`，自带房间设置，能直接导入

> **「这个模式是我从游戏导出的，能修好吗」**
> → 跑 `fix`：合并折行、把「无」改回「全部禁用」、删掉导出吞掉的值，再复校一遍

> **「占领速度能不能调快」**
> → 查设置键的合法范围，给出改法

> **「这段报错是什么意思」**
> → 把游戏报的中文原文反查成具体位置和修法

**不用记命令**——AI 会自己调。想自己动手时看下面的命令表。

第一次用？先看 [5 分钟上手](./docs/quickstart.md)；遇到报错查 [报错对照手册](./docs/errors.md)；遇到报错查 [报错对照手册](./docs/errors.md)：装 → 导出 → 检查 → 修 → 导入，四步。

---

## 30 秒上手

1. **装**

```bash
npx skills add sandsand244263/overwatch-workshop-lite-skills
```

2. **导出你的模式**：游戏里「房间设置 → 总览 → **复制设置**」→ 粘到记事本 → **存成 `.txt`**

> 编码随意：UTF-8、记事本默认的 ANSI(GBK) 都能读。

3. **对 AI 说**：「检查这个文件」

---

## 输出长什么样

```
✗ 找蛋躲猫猫.ow：3 个问题会导致导入失败（另有 36 条提示，可以先不管）

  ── 必改 ──
  第 142 行：设置项「招架姿态恢复倍率」没有值（导出会把某些值吞掉）

  ── 提示（多半不用改） ──
  第 1732 行：追踪全局变量频率 这个位置导出后写作「无」，编辑器里是「全部禁用」
  …还有 34 条
```

**只认「必改」**：那几条不解决，导入一定失败。提示是给你参考的。

---

## 出问题时

| 情况 | 说 / 跑 |
|---|---|
| 不确定环境有没有问题 | `python tools/ws.py doctor` |
| 觉得它报错了（误报） | `python tools/ws.py report 你的.ow` → 生成脱敏片段，贴到 issue |
| 文件导不进去、也说不出为什么 | 直接把游戏报错原文贴给 AI |

---

## 能做什么

| 能力 | 说明 |
|---|---|
| **生成** | 按玩法描述出完整 `.ow`，自带房间设置，可直接导入 |
| **审查** | 三层检查：格式 → 数据 ID → 类型，**每条报错附改法** |
| **解释** | 逐条说明事件、条件、状态变量、可见效果 |
| **调试** | 用 `记入查看器` 打点，按最小可疑点收敛，不盲改 |
| **省元素** | 算出当前用量，给出更省的等价写法 |
| **查数据** | 任意元素的官方说明、英雄数值、设置键范围、地图 GUID |
| **出发布文件** | 源码版 + 混淆版，**产物自动复核一遍** |

---

## 校验器查什么

三层，37 个检查函数。

**第一层 格式**：括号配对、分号、块结构、函数名、参数个数、变量名只能用英文、变量声明与引用、子程序声明、事件参数行数。

**第二层 数据 ID**（最容易踩的一层）——名字必须属于当前游戏版本：

| 对象 | 数据源 |
|---|---|
| 地图 | 291 张 |
| 英雄 | 54 个 |
| 技能 | 196 个 |
| 按钮 | 10 个 |
| 设置键 | 757 个 |
| 事件名 | 14 个 |
| 扩展名 | 11 个 |
| 下拉参数取值 | 74 个带选项的参数，逐一对照 |

> 游戏更新会删改名字，报错只说「"地图("之后应有一个地图名称」，不说是哪张图。校验器直接指出是哪个名字过期了。

**第三层 类型与范围**：玩家槽塞数字、数值槽塞玩家、队伍参数写「双方」、裸字符串没包 `自定义字符串`、设置值越界、全局变量存局部值、结束比赛的动作与模式不匹配、循环里宣告胜负不退出。

**查不出来的（诚实说明）**

| 类型 | 为什么 |
|---|---|
| 行为对不对（循环、计分、HUD 刷新） | 代码里没有「你想干什么」这个信息 |
| 地图与模式是否兼容 | 数据里没有「哪张图有目标点」的对应关系 |
| 元素数精确值 | 差约 3.3%，只用于上限预警 |

这类问题只能开一局验证，经验都在 `docs/pitfalls.md` 与 `data/behavior-notes.tsv`。

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
├── docs/                        数据里没有的知识，手写（18 篇）
│   ├── format-spec.md             格式规范：骨架、硬规则、报错对照（先读这个）
│   ├── samples.md                 三个可运行样例的适用与不适用
│   ├── validator-coverage.md      校验器覆盖清单与已知盲区
│   ├── extensions.md              扩展系统：写法、成本、上限
│   ├── element-count.md         元素计数推导记录
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
│   ├── element_count2.py          元素数模型（实测标定版）
│   ├── gen_*.py                   从游戏导出重新生成 data/
│   ├── selfcheck_publish.py       混淆产物冒烟测试
│   └── probes/                    65 正样本 + 21 反向用例 + 3 个可运行样例
├── .github/workflows/check.yml    push 与 PR 自动跑回归
├── .claude-plugin/marketplace.json  Claude Code 市场注册
└── LICENSE                        MIT
```

---

## 命令

```bash
python tools/ws.py doctor                         # 环境自检（Python/数据/编码）
python tools/ws.py check 模式.ow                  # 校验：先列「必改」，再列「提示」
python tools/ws.py check 模式.ow --json           # 结构化输出，给编辑器/CI
python tools/ws.py fix 导出的.txt                  # 修成可导入版本，并复校
python tools/ws.py report 模式.ow                 # 误报反馈：生成脱敏的最小复现
python tools/ws.py check-all                      # 回归全部样本（65 正 + 20 反例）
python tools/ws.py count 模式.ow                  # 元素数估算
python tools/ws.py scaffold --rule 测试            # 生成最小骨架（默认死斗）
python tools/ws.py scaffold --mode 占领要点 --rule 测试   # 其它模式骨架
python tools/ws.py doc 创建HUD文本                  # 查官方说明
python tools/ws.py doc --search 范围               # 按关键词搜
python tools/ws.py stats 半藏                      # 查英雄数值
python tools/ws.py settings --mode 死斗            # 生成该模式的设置块
python tools/ws.py explain 应有一个关系运算子        # 报错文案反查
python tools/ws.py fix 导出.txt                                # 修成可导入版本并复校
python tools/ws.py publish 模式.ow --outdir out                # 源码版
python tools/ws.py publish 模式.ow --outdir out --obf all      # 加混淆版
python tools/ws.py baseline                       # 数据基线 vs 游戏版本
python tools/ws.py update-check                   # 查是否有新版
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

只认 0 error。详见上面「校验器查什么」三层。

### 回归自检

```bash
python tools/ws.py check-all
```

65 正样本 + 21 反向用例。反向用例是**故意写错的文件**，用来测校验器本身：它一报错，说明检查还在；它不报错，说明检查坏了。CI 在每次 push 与 PR 时自动跑。

```bash
python tools/ws.py calib            # 37 个元素标定样本，偏差必须为 0
python tools/selfcheck_publish.py   # 混淆产物冒烟测试
```

### 已验证到什么程度

| 层 | 状态 |
|---|---|
| 格式（块结构、标点、变量两段、事件行数） | 实测导入通过 |
| 名字与参数（动作 / 值 / 枚举 / 字符串） | 由游戏数据生成，校验器按表判 |
| 设置项的词与归属 | `schema-keys.tsv` + 校验器 |
| 数据 ID（地图/英雄/技能/按钮/设置键/事件/扩展） | 按当前版本表核对 |
| 元素数 | 37 个探针标定；235 KB 真实模式误差 **-3.3%**，最终以游戏诊断为准 |
| 运行时行为（HUD 刷新、计分、循环） | 部分实测（见 `docs/pitfalls.md`），其余需开一局验证 |

**真实模式验证过**：235 KB 的实战模式（165 条规则）0 error；三个样例与一个从零写的模式实机跑通。

### 可运行样例

`tools/probes/samples/` 里三个完整可导入的最小模式，**先抄后改**：

| 样例 | 覆盖 |
|---|---|
| `sample-periodic.ow` | 全局心跳（持续-全局 + `While(真)` + `等待`） |
| `sample-event.ow` | 事件驱动（击杀计数 + 播报 + 宣告胜利） |
| `sample-countdown.ow` | 条件等待（倒计时到 0 平局） |

每个样例头部写了「适用 / 不要用」。同一件事在工坊里有好几种正确写法，所以给样例而不是单一模板，详见 `docs/samples.md`。

### 已知限制

| 项 | 现状 |
|---|---|
| 元素数 | 小样本精确（37 个标定）；真实模式 -3.3%，只用于上限预警 |
| 语义层 | `持续` 规则不循环、`While(真)` 无退出等，噪声太大，只在 `check --strict` 提示 |
| 地图 × 模式 | 数据里没有对应关系，地图选错只能靠实机导入发现 |
| HUD 实时数值 | `大字体信息` 有动效，跟不上每秒刷新；测数值请用 `记入查看器` |
| 扩展点数上限 | 取决于大厅配置，`.ow` 里常常不写，算不出来 |

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

不是暴雪公开常量。单价来自 37 个「同模板只改一处」的实机探针：动作 1、字符串 3、数组元素另计、`事件玩家.X` 比 `全局.X` 贵 1、变量下标 +2、三元表达式本体 5……完整表见 `docs/limits.md`。

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
