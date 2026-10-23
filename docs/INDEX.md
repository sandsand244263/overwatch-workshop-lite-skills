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

**不要直接读这些表**，用命令查：`ws.py doc` / `keyinfo` / `stats` / `defaults` / `map-code` / `modes`。
