# v14-silent：6 条「在 160 个文件里从没响过」的检查，各给一个最小探针

## 为什么有这一组

v14 收尾时把所有检查单独拿去跑 **151 个探针 + 9 份真实语料**，发现 6 条**一次都没出声**：

`check_arg_count` / `check_block_layers` / `check_duplicate_blocks` / `check_types` / `check_var_refs` / `check_misc`

「不出声」有两种可能：死代码，或者触发面太窄。这一组文件就是拿来区分的——**每条都能响**，
所以它们不是死代码，只是现有样本里没人踩到。

## 怎么用

```
python tools/ws.py check tools/probes/lab/v14-silent/<文件>.ow
```

对照 `expect.tsv` 看那条第几行有没有出现。**这组目前不进 `check-all` 的回归集**，
所以 `check-all` 还是 67 条；要防退化就把它们搬进 `tools/probes/negative/` + `expect.tsv`（数字会变 73）。

## 注意

- `block_layers` 是**提示级**（warning），`check` 的「必改」段里看不到，要看完整输出；
- `var_refs` 的判据是「`事件玩家.X` / `本地玩家.X` 必须在变量块 `玩家:` 段声明」，
  写 `玩家.X` 不会触发（那是另一条检查）；
- `misc.ow` 打的是 `check_misc` 里「变量名只差大小写」那条子规则。
