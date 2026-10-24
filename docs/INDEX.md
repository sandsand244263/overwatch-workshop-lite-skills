# 文档索引

> SKILL.md 只做路由；细节都在这里。**按「你在做什么」查，不要整目录读。**

| 文档 | 讲什么 | 什么时候读 |
|---|---|---|
| [quickstart.md](./quickstart.md) | 新用户第一次用：装 → 导出 → 检查 → 修 → 导入 | 用户说「不会用」「怎么开始」 |
| [ui-workflow.md](./ui-workflow.md) | 游戏界面操作：导出/导入/分享/预设/诊断 | 不知道怎么在游戏里点 |
| [errors.md](./errors.md) | 报错原文 → 原因 → 改法（实测） | 手里有一句游戏报错 |
| [pitfalls.md](./pitfalls.md) | 避坑总索引 + 必查清单 | 每次都该扫一眼 |
| [rules.tsv](./rules.tsv) | **断言表**：一条实测结论一行（禁止 / 正确 / 依据 / 证据等级 L0~L3 / 怎么验 / 检查开关） | 写码前查 `ws.py rule <关键词>`；不知道能不能做查 `ws.py verify` |
| [pitfalls-map.md](./pitfalls-map.md) | 地图池、时段编号、模式名写法 | 动地图设置 |
| [pitfalls-syntax.md](./pitfalls-syntax.md) | 字符串/队伍参数/变量/子程序/数组 | 写动作和表达式 |
| [pitfalls-runtime.md](./pitfalls-runtime.md) | 规则何时跑、循环、计分、胜负、HUD | 行为不对 |
| [pitfalls-export.md](./pitfalls-export.md) | 导出失真修法 + 校验器维护纪律 | 导入失败怀疑失真 / 改校验器 |
| [format-spec.md](./format-spec.md) | `.ow` 语法格式全表 | 要确认某个语法能不能写 |
| [syntax.md](./syntax.md) | 动作与值函数用法速查 | 写具体动作 |
| [patterns.md](./patterns.md) | 常用模式骨架（计分/回合/商店…） | 要照着写一个模式 |
| [basics.md](./basics.md) | 工坊基础概念 | 刚开始学 |
| [cost-patterns.md](./cost-patterns.md) | 元素数怎么省 | 接近 32768 上限 |
| [limits.md](./limits.md) | 硬限制（元素、规则大小、皮肤、机器人） | 担心超限 |
| [settings-map.md](./settings-map.md) | 设置键的层与取值 | 写设置块 |
| [extensions.md](./extensions.md) | 11 个扩展与副作用 | 要开扩展 |
| [hero-stats.md](./hero-stats.md) | 54 英雄面板数值 | 调英雄数值 |
| [hero-quickref.md](./hero-quickref.md) | 英雄速查 | 只想看一两个英雄 |
| [element-reverse.md](./element-reverse.md) | 元素计数的实测推导记录（历史） | 想改估算模型 |
| [reverse-notes.md](./reverse-notes.md) | **二进制/CASC 逆向**：报错文案在哪、什么工具在 80MB 上不可信、可用锚点、脚本位置 | 要做逆向 / 想拿报错全集 |
| [acceptance-flow.md](./acceptance-flow.md) | 验收规范流程：三层仓分工、探针纪律、发版自检、回传后必做四件事 | 要加探针 / 要发版 / 不确定某文件该放哪个仓 |
| [validator-coverage.md](./validator-coverage.md) | 校验器覆盖范围与漏报率测试 | 想改校验器 / 判断可信度 |
| [diagnostics.md](./diagnostics.md) | 实机诊断方法（查看器日志等） | 要定位运行时问题 |
| [samples.md](./samples.md) | 可运行样例清单 | 想找现成例子 |
| [ui-notes.md](./ui-notes.md) | 编辑器 UI 观察 | 对照界面 |
| [ecosystem.md](./ecosystem.md) | 社区工具与资源 | 找外部资料 |
| [sources.md](./sources.md) | 数据来源与权威性排序 | 怀疑数据过期 |

---

## `data/` 文件清单（工具的数据源，只由 `ws.py gen` / `enrich.py` 生成，禁止手改）

| 文件 | 内容 |
|---|---|
| `signatures.md` | 225 动作 + 266 值函数的参数签名（含类型与下拉可选值） |
| `settings.tsv` | 269 设置键：类型与可写值 |
| `schema-keys.tsv` | schema → 键名（475 条），设置项归属的权威来源 |
| `mode-schemas.tsv` | 模式 → schema 列表（137 模式） |
| `hero-schemas.tsv` | 英雄 → schema 列表（135 英雄） |
| `maps.tsv` | 291 地图名 + GUID + 变体标记 |
| `events.tsv` | 14 个事件 + 参数位 |
| `strings.md` | 615 条文本选项（`字符串(...)` 只能用这里面的） |
| `defaults.tsv` | 参数省略时的默认值 |
| `enums.md` | 英雄 / 地图 / 下拉选项全集 |
| `action-tags.tsv` | 484 动作的功能分类 |
| `meta.json` | 数据基线的 build 与导出日期 |

### 阶段 1 新增（S1a / S1b 表 + 两个生成脚本）

| 文件 | 内容 | 谁生成 / 怎么验 |
|---|---|---|
| [`action-blocks.tsv`](../data/action-blocks.tsv) | 505 行（动作 225 / 值 261 / 条件 5 / 事件 14）× 五个块位置（事件块 / 持续-全局 / 持续-每名玩家 / 条件块 / 子程序体），四态取值：`是` / `否(数据:…)` / `未验证`，附语料出现次数与「冲突」列 | `python tools/gen_action_blocks.py`；`--check` 只比对不写盘（漂移退出 1） |
| [`element-completeness.tsv`](../data/element-completeness.tsv) | 752 行：动作 / 值 / 设置键 三类 × 三向差集（现有表有·语料有 / 现有表有·语料没有 / 语料有·现有表没有） | 同上 |
| [`defaults-full.tsv`](../data/defaults-full.tsv) | 831 行：400 元素的全部参数 —— 默认值 + **默认值性质**（字面值 / 类型占位 / 下拉默认档 / 无记录）+ 来源 + 尾参可省 + 语料反例数 + 等级 | `python tools/gen_element_facts.py`；`--check` 0 漂移、`--no-corpus` 无语料也能跑 |
| [`dropdown-aliases.tsv`](../data/dropdown-aliases.tsv) | 406 行：下拉槽 / 布尔项 / 队伍 / 英雄 / 扩展独占取值 —— 规范词 × 别名 × 别名是否被接受 × 是否导出显示词 | 同上 |
| [`param-exceptions.tsv`](../data/param-exceptions.tsv) | 6 行：签名说可省但引擎要求写（1 正向）+ 签名列了参数而语料一致少写（5 反向） | 同上 |
| [`limits-mutex.tsv`](../data/limits-mutex.tsv) | 23 行：上限 10 / 互斥 7 / 百分比 3 / 合法写法 2 / 运行时 1 | 同上 |
| [`word-lists.tsv`](../data/word-lists.tsv) | **23 行 / 36 条去重词**：从 exe 里读出来的「合法词校验点」——16 组多词表 + 6 个单关键词校验 + 比较运算符表；列：校验点 / exe 函数 VA / 槽位 / 词 / CASC key_index / 比较器 / 证据等级 / 出处 | `python tools/gen_word_lists.py`；`--check` 只比对（漂移退出 1），`--stats` 出统计；源表 `tools/word-lists-src.tsv`（**改源表再重生成，别手改 data/**）。依据 E-71 |

### 阶段 2 新增（报错文案全集）

| 文件 | 内容 | 谁生成 / 怎么验 |
|---|---|---|
| [`errors-full.tsv`](../data/errors-full.tsv) | 136 行 = 108 解析器级 + 12 导入界面 + 16 本轮补录；列：原文模板 / 槽数与含义 / 归属 8 类 / 触发条件 / 真因 / 改法 / 现有校验器能提前报三档 / 检查类别 / 断言引用 / 证据 L0·L1 / 出处（guid + idx + errors.tsv 行号） | `python tools/gen_errors.py`；`--check` 只比对（漂移退出 1），`--stats` 出分类统计，`--emit-doc` 导出 `docs/errors.md` 用的表；输入是 CASC `0x07C` 文本表与 `errors.tsv`，只读 |
| [`gen_errors.py`](../tools/gen_errors.py) | 报错文案全集的生成器：两表 join（按 `key_index` 对 `字符串ID`，逐条校验原文一致）+ 分类表（漏一条直接报错）+ 槽位声明校验 + 可复现输出（两次 md5 一致） | `python tools/gen_errors.py --stats` 自查 |

**查元素表不要直接读文件**：`python tools/ws.py 知道 <名字>` 一条命令出六段（身份 / 参数 / 能出现在哪 / 取值 / 已知坑 / 出处），
`--brief` 只给身份 + 已知坑，`--json` 给结构化版本，`--audit` 全量自查（0 崩溃 / 0 缺段 + 未答清单）。

**不要直接读这些表**，用命令查：`ws.py 知道` / `doc` / `keyinfo` / `stats` / `defaults` / `map-code` / `modes`。
