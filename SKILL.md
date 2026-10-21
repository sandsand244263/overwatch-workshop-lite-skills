---
name: WorkshopLite
description: 守望先锋工坊/创意工坊/OW 工坊触发：Overwatch Workshop `.ow` 代码生成、审查、调试与校验。
version: 2.39.0
author: 用户
platforms: [windows]
metadata:
  hermes:
    tags: [overwatch, workshop, ow-code]
---

# Overwatch Workshop Lite

写 `.ow` 工坊代码。用户只负责导入和试玩，语法、参数、设置项、元素预算、混淆、交付文件由本技能兜底。

## 版本与数据基线

| 项 | 当前值 |
|---|---|
| 技能版本 | 见本文件 `version:` 字段 |
| 数据基线 | `data/meta.json` 的 `build`（当前 2.25.0.1.154504） |

- 游戏更新后先跑 `python tools/ws.py baseline`：不一致说明数据过期，去仓库拉新版
- `ws.py check` 会顺带查一次新版本（24 小时缓存，没网/超时静默跳过），有新版本附一行提示
- 升级：`npx skills add sandsand244263/overwatch-workshop-lite-skills`（重复执行即覆盖安装）

## 目录契约

| 目录 | 内容 | 维护方式 |
|---|---|---|
| `data/` | 游戏导出的权威数据 | **只由 `ws.py gen` / `enrich.py` 生成，禁止手改** |
| `docs/` | 数据里没有的知识 | 手写 |
| `tools/` | 唯一入口 `ws.py`、校验引擎、生成器、探针 | 手写 |

判据：**数据决定"存在什么"，实测决定"能不能导入"**。两者冲突以实测为准，并写进 `docs/`。

### data/ 文件清单

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

## 入口

```bash
python tools/ws.py check 模式.ow                        # 校验，交付前必跑，必须 0 error
python tools/ws.py count 模式.ow                        # 元素数估算
python tools/ws.py defaults 创建HUD文本                  # 查参数默认值
python tools/ws.py modes                                # 列出全部模式
python tools/ws.py settings --mode 死斗 --lobby --hero 死神 --out 房间.ow   # 生成设置块
python tools/ws.py publish 模式.ow --outdir out          # 源码版
python tools/ws.py publish 模式.ow --outdir out --obf numbers,vars   # 加一份混淆版
python tools/ws.py gen --src <导出目录>                  # 重新生成 data/
python tools/ws.py diff --prev <旧> --cur <新>           # 两版数据全量对照
```

## 工作流

1. **查表不凭记忆**：参数与顺序查 `data/signatures.md`；设置键查 `data/settings.tsv`；`字符串(...)` 只用 `data/strings.md` 的现成词条，自由文本一律 `自定义字符串`。
2. **先抄骨架**：HUD、周期、计分、条件等待、数组、快照六类在 `docs/patterns.md` 末尾「可套用模板」。
3. **格式照 `docs/format-spec.md`**：块标题独占一行、`{` 另起一行；变量分 `全局:` / `玩家:` 两段；事件块全局 1 行、其它 3 行、子程序 2 行；控制流 `While(...)/If(...)/Else If(...)/End;`。
4. **设置块**：优先 `ws.py settings --mode <模式>` 按数据里的页序与键序自动生成（55 个模式全覆盖），再按需改值；`data/settings-blocks/` 的 8 份模板作为对照参考。布尔项只能写 `开启` / `关闭`。
5. **默认只交付源码版**。要防复制才出混淆版，并说明代价：占元素、影响可维护性、索引混淆拖性能、字符串混淆改变比较语义。
6. **元素超预算**：`ws.py count` 预警 → 按 `docs/cost-patterns.md` 的顺序降级 → 报数时说明是估算。
7. **改数据前先 `ws.py diff`**：无差异才动别的。

## 生成纪律（写错就导不进去）

- 持续做事必须显式循环：`While(真); …; 等待(0.1, 无视条件); End;`。`持续` 规则不会重入，单加 `等待` 也不循环。
- `If` / `Else If` 是一次性判断；等未来条件用 `While` + `等待` 或 `等待直到`。
- 条件块不写整行 `!(A && B)`，改写 `(...) == 真` / `!= 真` 或拆成多条。
- 变量名、子程序名只能 ASCII 字母数字下划线，≤32 字符，不能数字开头。
- 函数名里的引号必须是中文弯引号 `“ ”`，ASCII 直引号导入失败。
- `自定义字符串` 单条最多 `{0}{1}{2}`，再多要嵌套。
- 刷新槽等位置只能写 `全部禁用`，不能写 `无`。
- 动作/条件的行尾必须有分号；块结尾 `}` 后面不加分号。

## 参考索引

| 文件 | 用途 |
|---|---|
| `docs/basics.md` | 常识与已知 bug |
| `docs/format-spec.md` | 骨架、硬规则、报错对照 |
| `docs/syntax.md` | 语法细节 |
| `docs/pitfalls.md` | 执行机制陷阱（循环、等待、数组、事件） |
| `docs/patterns.md` | 可套用骨架 |
| `docs/cost-patterns.md` | 省元素与省性能的手法 |
| `docs/limits.md` | 容量上限 + 元素估算公式 |
| `docs/settings-map.md` | 设置界面分区与层级来源 |
| `docs/diagnostics.md` | 报错定位 |
| `docs/ui-notes.md` | HUD 排版 |
| `docs/ecosystem.md` | 周边工具 |
| `docs/sources.md` | 资料可信度分级 |

实测探针在 `tools/probes/`；改校验器后重跑 `ws.py check-all`（必须全过）。

## 交付标准

- `ws.py check` 0 error，一次粘贴导入成功。
- 只说结果和导入后看什么，不解释内部结构，除非用户问。
- 报元素成本时说清节省来自值、条件、动作还是规则结构，并声明是估算。

## 相关技能

数据更新走 `workshop-data-update`（导出 → 对照 → 生成 → 回归 → 发版）。
