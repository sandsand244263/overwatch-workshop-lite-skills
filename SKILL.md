---
name: WorkshopLite
description: 守望先锋工坊/创意工坊/OW 工坊触发：Overwatch Workshop `.ow` 代码生成、审查、调试与校验。
version: 1.2.2
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
7. Overwatch Workshop variable names and subroutine names must be 32 characters or fewer; longer names can fail to import, so validate name length before finalizing generated or refactored code.
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

## Reference Map

- `references/syntax.md` - File structure, settings blocks, event types, variables, shorthand syntax, advanced variable patterns, control flow, and wait semantics.
- `references/actions.md` - Action signatures, HUD/effect APIs, movement/state helpers, variable operations, gameplay control, projectiles, beams, and the complete action function list.
- `references/values.md` - Value and condition functions, common constants, strings, colors, map workshop settings, player/hero data, and the complete value/function list.
- `references/enums.md` - 英雄 54 名、地图 85 张、按钮名称、交流枚举、相对枚举、游戏模式、事件玩家/队伍过滤、扩展清单与元素成本、源数据勘误，以及顶部的数据基线说明。
- `references/strings.md` - 616 条内置 `字符串(...)` 预设词条（47 条带 `{0}`~`{2}` 占位符的格式模板 + 569 条固定词条）。
- `references/patterns.md` - Code quality requirements, performance-sensitive patterns, third-person and hero-selection patterns, and common one-line techniques.
- `references/ui-notes.md` - HUD / UI display notes, including multi-color HUD layout, slot sizing, sorting, and presentation-layer budgeting guidance.
- `references/pitfalls.md` - Mandatory pitfall checklist for reviews and debugging.
- `references/diagnostics.md` - Comment syntax rules and the required debugging workflow.
- `references/element-costs.md` - Tested element-cost reference grouped by values, context values, conditions, actions, and rule structures.
- `references/element-audit.md` - Practical audit rules for element-budget reviews and optimization order.

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

- Keep generated Workshop code idiomatic and consistent with the references.
- Preserve exact function names and special punctuation where required.
- When a fix depends on a specific Workshop behavior, say which reference file you checked.
- When making an element-budget recommendation, say whether the main savings come from values, conditions, actions, or rule structure.

## Related Skills

- None required — all references, agents, and assets are bundled with this skill.
