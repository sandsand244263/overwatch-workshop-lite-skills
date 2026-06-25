# workshop-lite

> 查工坊语法不用翻几十页的官方文档了。

守望先锋工坊 `.ow` 脚本的参考知识库——生成、审查、解释、调试，一个 skill 搞定。

**注意：本 skill 仅支持中文。** 所有参考文档、函数名、示例均为中文，英文用户不适合。

---

## 它解决什么问题

写过 `.ow` 的人都知道：

- 226 个动作函数、264 个条件/值函数，谁能全记住？
- 50 个英雄、36 种交流枚举、参数顺序一错就报"应有一个关系运算子"
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
│   ├── syntax.md                  语法参考（结构、事件、变量、控制流）
│   ├── actions.md                 226 个动作函数签名
│   ├── values.md                  264 个条件/值函数参考
│   ├── enums.md                   英雄/地图/按钮/交流/模式枚举
│   ├── patterns.md                设计模式与代码质量要求
│   ├── pitfalls.md                52 条必查避坑清单
│   ├── ui-notes.md                HUD/UI 排版说明
│   ├── diagnostics.md             注释语法与调试工作流
│   ├── element-costs.md           元素成本参考表
│   └── element-audit.md           元素审查规则
├── .claude-plugin/
│   └── marketplace.json           Claude Code 市场注册
├── README.md                      本文件
└── LICENSE                        MIT
```

---

## 英雄列表

当前参考的英雄列表约 **50 名**，部分较新英雄（如 Sierra 等）暂未收录。欢迎提交 PR 补充，或提 Issue 告知遗漏。

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

本 skill 的工坊语法/函数/枚举数据基于 [XHanL/overwatch-workshop](https://github.com/XHanL/overwatch-workshop)（MIT License），一个守望先锋工坊 VS Code 扩展。感谢 [@XHanL](https://github.com/XHanL) 的整理工作。

元素成本数据来自作者在工坊内的实际测试，非暴雪官方公开常量。

---

## License

[MIT](./LICENSE)
