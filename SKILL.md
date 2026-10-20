---
name: WorkshopLite
description: 守望先锋工坊/创意工坊/OW 工坊触发：Overwatch Workshop `.ow` 代码生成、审查、调试与校验。
version: 1.6.2
author: 用户
platforms: [windows]
metadata:
  hermes:
    tags: [overwatch, workshop, ow-code]
---

# Overwatch Workshop Lite

Use this skill for Overwatch Workshop and `.ow` tasks.

## When To Use

Trigger this skill when the user wants any of the following:

- Generate new Overwatch Workshop code or complete a partial rule.
- Review, debug, refactor, or explain existing `.ow` code.
- Check whether Workshop syntax, actions, values, enums, or patterns are valid.
- Review or optimize a Workshop file for element budget / element limit.

## Workflow

1. Classify the task as one of: `generate`, `review`, `explain`, or `debug`.
2. Read only the reference files needed for that task.
3. Do not guess Workshop function names, enum names, punctuation, indexing rules, or tested element costs; verify against the references first.
4. `自定义字符串(...)` in Overwatch Workshop must not use placeholders beyond `{2}` in a single call. That means a single `自定义字符串(...)` may interpolate at most 3 values using only `{0}`, `{1}`, and `{2}`. If you need more displayed values, nest another `自定义字符串(...)` instead of writing `{3}` or higher.
5. `If` / `Else If` are one-shot checks, not continuous listeners; if a fix depends on a future condition becoming true, use `While` + `等待(...)` or `等待直到(...)`.
6. In `条件` blocks, prefer explicit comparison-style conditions over wrapping a full compound expression in `!(...)`; rewrite them as `(... ) == 真`, `!= 真`, `>`, or split them into multiple conditions to reduce import-time parser errors like "应有一个关系运算子".
7. Overwatch Workshop variable names and subroutine names must be **ASCII only** (letters, digits, underscore) and 32 characters or fewer. Chinese variable names fail to import outright; over-long names also fail, so validate both before finalizing generated or refactored code.
8. If a refactor touches an anti-leak or anti-copy design such as password/input mapping, preserve the obfuscation layer instead of flattening it into direct plaintext or direct button sequences.
9. Keep responses concrete and use exact Workshop names as they appear in the references.
10. If you are making a second debugging revision, follow `references/diagnostics.md` and use targeted `记入查看器` probes so the user can paste viewer output back before you propose further speculative fixes.
11. In continuous rules, if logic depends on input edges or timing state (for example single-press triggers, release
reset, double-tap, hold-to-trigger, or toggle locks), prefer putting the core input gate in the condition block and
keep the action block focused on state writes and outcomes; if one rule starts handling too many timing
responsibilities, split it by edge or responsibility instead of stacking more action-level `If` checks.
12. When the user asks to save elements, reduce element count, or review budget-heavy code, check `references/element-costs.md` and `references/element-audit.md` before proposing structural changes.
13. `字符串(...)` can only use built-in presets - never invent content for it. Pick an exact entry from `references/strings.md`; if you need free-form text, use `自定义字符串(...)` instead (placeholder cap `{2}`).
14. Function and enum names containing quotes must use Chinese curly quotes `“ ”`, e.g. `如条件为“真”则循环`, `当为“假”时中止`, `对任意为“真”`; ASCII straight quotes fail at import. Also, when code will be pasted into the game, some refresh slots need `全部禁用` rather than `无` - see `references/syntax.md`.
15. Lines starting with `#` inside the reference code blocks are annotations for humans, not Workshop syntax. Real `.ow` comments are `//`, `"注释"` (action/condition blocks only), or `/* */`.
16. **Before returning any generated or edited `.ow`, run `python scripts/lint_ow.py <file>` and fix every error it reports.** Zero errors is the delivery bar — never hand unvalidated code to the user and let them discover import failures by pasting it into the game.
17. Never invent argument counts or order: check `references/signatures.md` (225 actions + 266 value functions, generated from game data). Trailing arguments may be omitted, extra ones never.
18. **Never hand-write the `设置` block.** No tool validates settings keys (DataTool does not export them, workshop.codes does not lint them, the VS Code extension has no settings data), so the only safe move is to copy the whole block from `references/golden2.ow` and change numbers. In `综合` only `复生时间` / `急救包刷新` / `游戏模式开始` / `英雄限制` are proven valid; anything else fails with 「`综合 {` 之后应有一个游戏模式设置」.
19. `references/golden.ow` is a real file exported from the game with the copy-script button — **the only format authority**. When structure is in doubt, copy its shape, do not reason about it. The rules that break import: variables must be split into `全局:` / `玩家:` sections; every non-global event block must have exactly 3 lines (event; team; hero) while global events have 1; control flow is `While(...)/If(...)/Else If(...)/End;`; colors are `颜色(x)`; empty slots are `空`; no trailing commas; comparisons in every condition line; `可见` takes players, never `真/假`; no `===`; variable names ASCII and ≤32 chars. Full list in `references/format-spec.md`.

## Reference Map

- `references/syntax.md` - File structure, settings blocks, event types, variables, shorthand syntax, advanced variable patterns, control flow, and wait semantics.
- `references/actions.md` - Action signatures, HUD/effect APIs, movement/state helpers, variable operations, gameplay control, projectiles, beams, and the complete action function list.
- `references/values.md` - Value and condition functions, common constants, strings, colors, map workshop settings, player/hero data, and the complete value/function list.
- `references/golden.ow` - 从游戏「复制脚本」导出的真实文件（155 行，简单模式），格式基准之一。
- `references/verified/` - 实测导入通过的探针样本：`settings-probe.ow`（设置词表）、`syntax-probe.ow`（控制流/数组/字符串/三元）、`subroutine-probe.ow`（子程序块）。
- `references/golden3.ow` - 实测导入成功的最小可用模式（设置块 + 变量 + 6 条规则），设置块照它抄。
- `references/golden2.ow` - 复杂模式样本（900 行，含散号变量、子程序块、数组、三元、跨行参数、纯字符串注释行），格式基准之二；lint 必须始终对它 0 error。
- `references/settings-schema.tsv` - 269 个设置项的权威表：键 → 类型 → 可写值（BOOL 恒为 开启/关闭，ENUM 为枚举原文）。校验器直接用它判值。
- `references/settings-map.md` - 设置项的老 BUG 说明（导出器写 启用/禁用、导入器只认 开启/关闭）与判定方法。
- `references/sources.md` - 权威资料分级（游戏 > 官方补丁 > 数据导出 > 社区工具）与下次更新的检查顺序。
- `references/format-spec.md` - 文件骨架、硬格式规则（分号/尾逗号/条件比较/可见参数/变量命名）、常见导入报错对照表。
- `references/signatures.md` - 全部动作与值函数的参数签名（225 + 266 条），生成代码时核对参数个数与顺序。
- `references/enums.md` - 英雄 54 名、地图 85 张、按钮名称、交流枚举、相对枚举、游戏模式、事件玩家/队伍过滤、扩展清单与元素成本、源数据勘误，以及顶部的数据基线说明。
- `references/strings.md` - 616 条内置 `字符串(...)` 预设词条（47 条带 `{0}`~`{2}` 占位符的格式模板 + 569 条固定词条）。
- `references/patterns.md` - Code quality requirements, performance-sensitive patterns, third-person and hero-selection patterns, and common one-line techniques.
- `references/ui-notes.md` - HUD / UI display notes, including multi-color HUD layout, slot sizing, sorting, and presentation-layer budgeting guidance.
- `references/pitfalls.md` - Mandatory pitfall checklist for reviews and debugging.
- `references/diagnostics.md` - Comment syntax rules and the required debugging workflow.
- `references/element-costs.md` - Tested element-cost reference grouped by values, context values, conditions, actions, and rule structures.
- `references/element-audit.md` - Practical audit rules for element-budget reviews and optimization order.
- `scripts/lint_ow.py` - 中文 `.ow` 格式校验器：括号、分号、尾逗号、条件比较、变量名、未知函数、参数个数、占位符、全局规则误用事件玩家。交付前必跑，退出码 0 才算完成。

## Task Guidance

### Generate

- Prefer the smallest correct rule set that satisfies the request.
- Match the user's existing naming and structure when editing a file.
- Call out required Workshop extensions, map-workshop settings, or other prerequisites when they matter.
- For condition rewrites, avoid emitting a whole line like `!(A && B)` in a `条件` block when an explicit equivalent is available.
- Before finalizing, sanity-check syntax, indexing, wait behavior, loop behavior, and any required refresh modes.

### Review

- Validate structure first: event, condition, and action order; semicolons; and valid block placement.
- Check `条件` lines for parser-fragile forms, especially full-line `!(A && B)` / `!(A || B)` compound negation.
- Check array indexing carefully, especially places where append-to-array patterns create 1-indexed access.
- Check single-assignment, wait behavior, `While`, and per-frame execution behavior for logic bugs.
- Use `references/pitfalls.md` as a checklist before concluding that code is correct.
- If the user asks for optimization or budget review, check the biggest costs in this order: HUD/effects, rule structure, filtering/sorting, then small value substitutions.

### Explain

- Explain code in Workshop terms, ideally rule-by-rule or system-by-system.
- Name the event, key conditions, state variables, and visible effects or outputs.
- If behavior depends on an enum or action signature, verify it in the references instead of paraphrasing from memory.

### Debug

- Reproduce the likely failure path from event trigger to final action.
- On the first pass, identify the smallest plausible fix.
- On the second pass or later, follow `references/diagnostics.md` and use targeted `记入查看器` probes before suggesting more changes.
- If you are unsure whether a Workshop syntax form, function combination, parameter shape, or engine behavior is supported, do not keep revising the main file speculatively; first build a minimal isolated test, ask the user to report whether it imports and how it behaves, then apply the verified approach to the real code.

## Output Expectations

- **Every generated or edited `.ow` must pass `scripts/lint_ow.py` with zero errors before it is returned**, and must import in one paste. Before returning code, self-check the things that actually break import: only names that exist in the references, Chinese curly quotes in quoted function names, no placeholder above `{2}`, variable and subroutine names ≤ 32 characters, and the correct refresh slot (`全部禁用` vs `无`).
- Keep generated Workshop code idiomatic and consistent with the references.
- Preserve exact function names and special punctuation where required.
- When a fix depends on a specific Workshop behavior, say which reference file you checked.
- When making an element-budget recommendation, say whether the main savings come from values, conditions, actions, or rule structure.

## Related Skills

- None required — all references, agents, and assets are bundled with this skill.
