---
name: WorkshopLite
description: 守望先锋工坊/创意工坊/OW 工坊触发：Overwatch Workshop `.ow` 代码生成、审查、调试与校验。
version: 2.2.0
author: 用户
platforms: [windows]
metadata:
  hermes:
    tags: [overwatch, workshop, ow-code]
---

# Overwatch Workshop Lite

定位：**纯 vibe coding**。用户只做两件事——把文件导入工坊、开一局看功能对不对。其余（语法、参数、设置项、元素预算、混淆、发布文件）全部由你兜底，不许要求用户手改代码或装插件。

## 目录分工

| 目录 | 内容 | 能否手改 |
|---|---|---|
| `data/` | 动作、值函数、参数、下拉选项、设置项、字符串、英雄地图；由 `tools/gen_data.py` 从游戏导出生成，文件头带 build 与导出日期 | **禁止手改** |
| `docs/` | 数据里没有的知识：格式、坑、模式、诊断、上限、元素成本、生态 | 手写 |
| `tools/` | `ws.py` 唯一入口 + 校验引擎 + 数据生成 + 实测探针 | 手写 |

判据：**数据决定"存在什么"，实测决定"能不能导入"**。冲突时以实测为准，并在 `docs/` 写明依据。

## 唯一入口

```bash
python tools/ws.py check 模式.ow                        # 校验，交付前必跑，必须 0 error
python tools/ws.py count 模式.ow                        # 元素数估算（预警用）
python tools/ws.py defaults 创建HUD文本                  # 查参数默认值（省略尾部参数时游戏用什么）
python tools/ws.py publish 模式.ow --outdir out          # 出源码版
python tools/ws.py publish 模式.ow --outdir out --obf numbers,vars   # 额外出混淆版
python tools/ws.py gen --src <导出目录>                  # 重新生成 data/
python tools/ws.py diff --prev <旧导出> --cur <新导出>    # 全量对照
```

## 工作流

1. **查数据不凭记忆**：参数个数与顺序看 `data/signatures.md`（`ws.py defaults 函数名` 能查每个参数省略时的默认值）；设置项键与值看 `data/settings.tsv`；`字符串(...)` 只能用 `data/strings.md` 里的现成词条，自由文本一律 `自定义字符串`。
2. **格式照 `docs/format-spec.md`**：块标题独占一行、`{` 在下一行；变量分 `全局:` / `玩家:` 两段；事件块全局 1 行、其它 3 行、子程序 2 行；控制流 `While(...)/If(...)/Else If(...)/End;`。
3. **写完必跑 `ws.py check`**，0 error 才交付；有 error 自己改，不交给用户试错。
4. **设置块整块照抄** `tools/probes/golden3.ow`，键值不手改——导出器有老 BUG（布尔项导出 `启用/禁用`，导入只认 `开启/关闭`）。`综合` 块只有 `复生时间` / `急救包刷新` / `游戏模式开始` / `英雄限制` 四个键可用。
5. **默认只给源码版**。用户明确要防复制才出混淆版，并说清代价（占元素额度、影响可维护性、索引混淆拖性能、字符串混淆改变比较语义）。
6. **元素超预算**先用 `ws.py count` 预警，再按 `docs/element-audit.md` 的顺序降级：HUD/特效 → 规则结构 → 过滤排序 → 小值替换。报数字时说明是估算，最终以游戏诊断为准。
7. **改 skill 前先 `ws.py diff`**：无差异才动别的；有差异先摆给用户确认。

## 生成纪律（会直接导致导入失败的点）

- 单个 `自定义字符串` 最多用 `{0}{1}{2}`；再多要嵌套，别写 `{3}`。
- `If` / `Else If` 是一次性判断，不是监听器；等未来条件用 `While` + `等待(...)` 或 `等待直到(...)`。
- 条件块避免整行 `!(A && B)`，改写成 `(...) == 真` / `!= 真` 或拆成多条，否则报"应有一个关系运算子"。
- 变量名、子程序名只能 ASCII（字母数字下划线），≤32 字符，不能数字开头；中文名直接导不进。
- 函数名里带引号的必须用中文弯引号 `“ ”`（如 `如条件为“真”则循环`），ASCII 直引号导入失败。
- 刷新槽等位置只能写 `全部禁用`，不能写 `无`（校验器会点名）。
- `.ow` 注释只有 `//`、`/* */` 和动作/条件块内的 `"注释"` 三种；`#` 是给人看的，不是语法。
- 反泄漏/防复制设计（密码、按键映射）重构时保留混淆层，不要摊平成明文。

## 参考索引

- 格式与报错：`docs/format-spec.md`、`docs/syntax.md`、`docs/diagnostics.md`
- 坑：`docs/pitfalls.md`；上限：`docs/limits.md`；模式：`docs/patterns.md`
- HUD 排版：`docs/ui-notes.md`；元素成本：`docs/element-costs.md`、`docs/element-audit.md`
- 设置项老 BUG：`docs/settings-map.md`；周边工具：`docs/ecosystem.md`；资料分级：`docs/sources.md`
- 实测探针（导入验证过）：`tools/probes/`；改校验器后必须重跑 `ws.py check tools/probes/*.ow`

## 任务处理

- **生成**：给满足需求的最小规则集；沿用用户已有的命名与结构；涉及扩展、地图设置时提前说明。
- **审查**：先结构（事件/条件/动作顺序、分号、块位置），再条件写法，再数组索引（追加式数组是 1 起始），最后逻辑与时序。
- **解释**：按规则逐条讲，说清事件、关键条件、状态变量、可见效果；枚举与签名先查表再讲。
- **调试**：第一轮找最小可疑点；第二轮起用 `记入查看器` 打点让用户回传，不要连续盲改。语法或行为不确定时，先写最小探针让用户导入验证，再改正式代码。

## 交付标准

- 交付的 `.ow` 必须 `ws.py check` 0 error，且一次粘贴导入成功。
- 只说结果和导入后看什么（元素数、功能现象），不解释内部结构，除非用户问。
- 报元素成本时说明节省来自值、条件、动作还是规则结构，并声明是估算。

## 相关技能

- 数据更新流程见 `workshop-data-update`（导出 → 生成 → 对照 → 回归 → 发版）。
