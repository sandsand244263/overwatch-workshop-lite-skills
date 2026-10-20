# 权威资料与更新流程

工坊这块没有单一权威文档：**格式看游戏，名词看数据，规则看社区工具**。三者分工不同，别拿一个当全部。

## 一、来源分级

| 级别 | 来源 | 能定什么 | 怎么查 |
|---|---|---|---|
| 1 | **游戏本体：复制脚本** | 文本格式的唯一权威（块结构、缩进、段标签、控制流写法） | 工坊里打开任意模式 → 复制脚本 → 存成 `golden.ow`。格式有疑问先看它，不要看文档 |
| 1 | **游戏报错信息** | 中文关键字、块要求的权威（如「`变量 {` 之后应有 `全局`」） | 导入失败时把报错原文记下来，直接就是规范 |
| 2 | **官方补丁说明** ow.blizzard.cn/news/patch-notes/ | 新英雄、新地图、模式改动、工坊相关调整 | 版本更新后先看，确认有没有动工坊 |
| 2 | **OWLib / DataTool 导出** | 元素名、参数签名、枚举、内置字符串 | 本机 `DataTool.exe` 三个 list 命令，见 `workshop-data-update` 技能 |
| 3 | **workshop.codes**（linter 源码） | 真实导入错误规则：尾逗号、条件必须比较、事件参数、变量大小写、地图 id 0、英雄设置开关 | `app/javascript/src/lib/OWLanguageLinter.ts` |
| 3 | **overpy**（反编译器 + 真实 .ow 样例） | 结构规则：事件 1 行或 3 行、变量两块、语句分号 | `src/decompiler/workshopToAst.ts`、`src/tests/decompiler/*.txt` |
| 3 | **OSTW**（TextMate 语法） | 四块结构（settings / variables / subroutines / rule） | `tmlanguage-generator/src/ow/ow-grammar.ts` |
| 3 | **xhanl/overwatch-workshop** | 中文元素名对照 + 中文语法高亮规则（`syntaxes/ow.tmLanguage.json`）+ 官方测试 `.ow` 文件 | 元素改名、语法高亮、缩进写法 |
| — | **设置项（settings）没有任何工具覆盖** | 键和合法值没有数据源：DataTool 不导、workshop.codes 不查、VS Code 插件里也没有 | 只能整块照抄 `golden2.ow`，绝不手写 |

优先级：**1 > 2 > 3**。冲突时以游戏实际行为为准，其余都只是旁证。

## 二、下次更新时先查什么

按顺序走，前一步没结论再走下一步：

1. **游戏版本变了吗** → 读客户端 `.build.info` 的 Version，与 `enums.md` 顶部数据基线比
2. **官方动了工坊吗** → 看当月补丁说明，搜「工坊 / 自定义游戏 / 地图工坊」
3. **数据变了吗** → 重导 DataTool，跑 `workshop_diff.py --prev/--cur` 出差异清单
4. **格式变了吗** → 从游戏里重新复制一份脚本，与 `golden.ow` 对比；不一样就以新的为准，替换 golden
5. **社区工具跟上了吗**（可选）→ 看 workshop.codes 的 linter 有没有新增规则、overpy 最近提交是否提到格式变化

## 三、格式类的疑问怎么定

不要靠推理，靠样本：

1. 在游戏里复制一份含该结构的模式（变量就加变量，事件就加事件）
2. 存成 `golden.ow` 覆盖旧的，或另存为 `golden-<主题>.ow`
3. 跑 `python tools/ws.py check tools/probes/golden*.ow`，必须全部 0 问题
4. 有问题就是校验器的规则错了，改校验器，不要改样本

## 四、资料可信度备忘

- DataTool 导出的是**图形数据结构**，不含文本格式；它能定名字和参数，定不了怎么写
- workshop.codes 的解析器只认**英文语法**，不能校验中文 `.ow`，只能当规则来源
- overpy 的样例文件是英文版导出，中文块名要靠游戏报错来对（如 `变量` / `全局` / `玩家`）
- 社区工具都可能有滞后：官方改了、工具没跟上，此时以游戏为准
