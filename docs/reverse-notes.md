# 逆向笔记：二进制与 CASC（只读静态）

> 这一页只记**实测过的事实**：能做什么、不能做什么、坑在哪、证据在哪个报告里。
> 结论都会随游戏版本变，动手前先重跑一次命令核对。

日期：2026-10-24　目标：`E:\Overwatch\_retail_\Overwatch.exe`（80.7 MB，build 2.25.0.1.154504）
证据：本轮逆向实验记录（研发私有仓，不随技能发布）

## 一句话结论

**工坊报错文案不在 exe 里，在 CASC 的 0x07C 本地化文本资产里。**
想拿「报错文案全集」不用碰二进制，读 CASC 导出的字符串表即可；二进制只在「要解释某个行为为什么这样」时才有价值。

## 1. exe 里没有中文文案（这决定阶段2 怎么开工）

| 检索 | 编码 | 命中 |
|---|---|---|
| `之后应有` / `之后应有一个值` / `无效的` / `第.{0,3}行` | UTF-8 + UTF-16LE | **0** |
| `Workshop` / `GameMode`（纯 ASCII） | ASCII / UTF-16LE | **0** |
| `Ruleset` | ASCII | 17（全是 `.rdata` 的 RTTI/内部标识，不是文案） |
| `Lobby` | ASCII | 18（同上） |
| **控制组**：`玩家` / `设置` / `无效` / `错误` / `失败` / `取消` / `确认` | UTF-8 + UTF-16LE | **0** |
| **控制组**：`的` / `了` / `是` / `我` / `不` | UTF-8 + UTF-16LE | 各 0~3（单字巧合） |

控制组是关键：连「的」这种最高频汉字都只有 0~3 次，说明**整个 exe 里就没有中文字符串**，不是「目标词没命中」。
`_retail_` 下 25 个 PE × 7 词 × 2 编码 = 350 组合，345 个为 0。

## 2. 文案在 CASC，不在二进制

- 位置：CASC 的 **0x07C** 本地化文本资产（本机 zhCN 包）
- 现成产物：`C:\owdump\lobby-probe\out\strings_07C.tsv`（64,778 条 zhCN，列 = guid / key_index / locale / len / text）
- 另一份：`C:\owdump\parser-re\errors.tsv`（120 条报错，其中 108 条解析器级）
- 实例（直接抄下来的原文）：

```
00000000C7B9.07C  idx=51129  错误：第%3$s行的“%2$s”之后应有“%1$s”
```

`%1$s` / `%2$s` / `%3$s` 就是解析器的三个插值槽（期望的东西 / 实际写的东西 / 行号）。
**要「报错原文 → 规则」的映射，从这张表反推，比反编译便宜得多。**

只读复现（**不要启动游戏**）：`C:\owdump` 下已有 CASC 探针工程（`Online=false`），
一次约 6 分钟、读机械盘，别并发跑。

## 3. 工具坑（都是实测踩出来的，按严重度排）

| 坑 | 现象 | 正确做法 |
|---|---|---|
| **`rizin izz` 在大文件上静默出空** | 对 80.7MB 的 exe：`.text`(0x3508000=55MB) / `.rdata`(0x1555e00=22MB) 被 `exceeds max region size (0xa00000)` 整段跳过，最后 `Failed to generate interval list`，**输出 0 行**；同命令对 `NeacLoader.exe` 正常出 2949 行。`el~bin.` 里没有可抬的键 | 任何基于 `izz` 的「0 命中」都不算证据。字符串直接用**纯字节扫描**（Python 读整个文件，无 region 限制） |
| Ghidra 版本被锁死 | rea-agents 6.7.0 的 `GhidraReleasePolicy.js` 写死 `SUPPORTED_GHIDRA_VERSION = "12.1.4"`，装 12.2 会被判 `unsupported` | 装 **12.1.4**（`C:\Tools\ghidra`），JDK 用 `C:\Tools\jdk21` |
| REA 在 80MB 上撞响应预算 | `binary_overview` 跑 2823 秒后返回 `resource_constraint`（`result_budget_bytes ≈ 10MiB`，MCP 收包缓冲上限） | 要么先拿 5~10MB 的 PE 跑通流程，要么调 `REA_MCP_MAX_RESPONSE_BYTES`；别指望一次拉全量概览 |
| Windows 上的 rizin 桥不可用 | `rea execute-rizin-command` → `ERR_REA_WINDOWS_NATIVE`；rizin 也没有 `pdc` 插件 | 反编译只能用 Ghidra；rizin 只当「字符串 / 反汇编局部函数」用 |
| 字符串→引用的正确算法 | `axt` 依赖 `aa` 建库，80MB 上建不全，返回 0 行会被误读成「无引用」 | 用 **RIP 相对 disp32 反推**：对候选地址 A，找 `.text` 里满足 `p+7+disp32 == A` 的 lea（`48 8D 0D/05/15`…）。脚本见下 |

## 4. 还能用的锚点

| 锚点 | 地址 / 命中 | 用途 |
|---|---|---|
| `D:\Madness\production\Worker\2_25_0_1\game\Core\Utilities\Protobuf\CustomGame.pb.cc` | `0x1447e48d0`，**30 处代码引用**，首个 `0x143365c53` | 定位 `.ow`（protobuf `CGGameRuleset`）相关代码 |
| `CGGameRuleset` | 14 处，全是 MSVC RTTI inline name | 结构上就没有指针引用，**0 命中是必然**，别当异常 |
| 全量扫描 | 13,951 条 RIP 相对引用 / 7,190 个被引用字符串 | 找别的锚点时复用这套扫描 |

## 5. 现成脚本（在研发私有仓，不随技能发布）

| 脚本 | 干什么 |
|---|---|
| `pe_strings.py`（本轮脚本，私有仓） | 参数化主工具：给 PE 与词/正则，出「字符串 VA + 文件偏移 + 引用代码 RVA + 引用类型」；两次运行输出 sha256 完全一致 |
| `byte_scan.py`（同上） | 纯字节扫描（UTF-8 / UTF-16LE），不受 region 上限影响 |
| `scan_dir.py`（同上） | 整目录批量扫（只扫 `_retail_`，别扩到全盘） |
| `casc-probe/`（同上） | CASC 只读探针（`Online=false`），取 0x07C 文本 |

## 6. 安全边界（硬性，不商量）

只读文件做静态分析。**不启动游戏、不注入进程、不挂调试器、不碰反作弊模块**
（`NeacInterface.dll` / `NeacLoader.exe`），不用 REA 的 runtime / process-capture 功能。
CASC 探针必须 `Online=false`。

## 7. 反编译到底能不能用（2026-10-24 实测）

**能，但导入很慢，而且工程要留着别重建。**

| 步骤 | 命令 | 实测 |
|---|---|---|
| 建工程（一次性） | `analyzeHeadless <工程目录> owproj -import Overwatch.exe -max-cpu 2 -analysisTimeoutPerFile 2100` | **37 分 33 秒**，`Import succeeded`，峰值 1.97 GiB |
| 反编译任意函数 | `analyzeHeadless C:/Tools/ghidra-proj owproj -process -noanalysis -readOnly -postScript DecompileDump.java` | 一次一个函数，几十秒级 |

- **现成工程在 `C:\Tools\ghidra-proj\owproj`（969 MB，别删）**。删了就得再等 37 分钟。
- 堆上限用**环境变量** `GHIDRA_HEADLESS_MAXMEM=4G`（默认只有 2G），不是命令行 `-Xmx`。
- `-readOnly` 能省掉 postScript 之后那段「ANALYZING changes made by post scripts」（不加会白跑十几分钟）。
- 批量反编译要在**一个脚本里循环**（`DECOMP_LIMIT=N`），别 N 次启进程——每次启动大半时间在开 80MB 工程。

- `Analysis timed out` **不等于失败**：PE 头、段表、符号、反汇编、函数识别都已完成并落盘，超时卡在收尾步骤
  `ClearFlowAndRepairCmd`（函数体修复）。工程可用，函数能反编译。
- 实测反编译出的引用点与字节扫描（`pe_strings.py` 算的 disp32）**互相印证**，不是幻觉。
- 批量反编译要在**一个脚本里循环**（`DECOMP_LIMIT=N`），别 N 次启进程——每次启动约 2 分钟，其中大半是开工程。
- 别并发两个 Ghidra；REA 的 `inspect` 单次就要 0.9~1.4 GB。

## 8. 现在还没解决的

- `binary_overview` 的 10MiB 响应预算：抬到 64MiB 需要 REA 重启 + 客户端收包够大 + 结果本身够小，三条缺一不可，未实跑验证
- enUS 报错表（本机只装了 zhCN 文本包）
- `0x063` 表 54 条与 A 层 108 条的差集没对完
- `0x143622150` 那族英文解析器报错是否属于 `.ow` 解析器，未定
