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
| **`-postScript` 给绝对路径的 .java 会找不到** | `analyzeHeadless … -postScript "E:/…/X.java"` → `Failed to find script in any script directory` + `The class could not be found`（脚本本身没语法错；同一条命令换个路径就能跑） | 把脚本放到 **ASCII 路径**（如 `C:/Tools/ghidra-scripts/`），加 `-scriptPath C:/Tools/ghidra-scripts`，`-postScript` 只写文件名 |
| protobuf 字段名字符串查不到引用 | `PBCGLogic*` / `CGGameRuleset*` 这些名字用 RIP 相对（0 处）和绝对 8 字节指针（0 处）都查不到引用 | 不是扫描坏了（同脚本对 `CustomGame.pb.cc` 路径串能算到 30 处）；protobuf 3.x 用 offset 表引用名字，**别拿「0 引用」当「没人用」** |

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

- **元素计价函数在 exe 里没找到（2026-10-24 专项，2 小时盒子里用了 55 分钟就撤回）**：
  `.text` 里 `cmp …, 0x8000` 只有 17 处、逐个看过没有一个在数节点（唯一成组的是一段 32768 容量的缓冲追加）；
  字符串里没有任何 element/count/budget 类锚点；protobuf 名字串查不到代码引用。
  推论：**上限与计数大概率不在 exe 这条路径上**，下一步应该走 CASC（数据侧），别再烧时间反编译。
  侦察脚本与反编译原文在研发仓 `tools-maintainer/v5-c1/`。
- 5 个地址在现有工程里没有函数体（`0x14097aab4` `0x142d53740` `0x142d7d170` `0x142df9670` `0x143235fb8`）——
  导入时 `ClearFlowAndRepairCmd` 超时留下的坑；要用得先补分析。
- `cgLogicExtensions`（0x14364c7a0）像是 CVar 名，未查它是否与逻辑树相关。
- `binary_overview` 的 10MiB 响应预算：抬到 64MiB 需要 REA 重启 + 客户端收包够大 + 结果本身够小，三条缺一不可，未实跑验证
- enUS 报错表（本机只装了 zhCN 文本包）
- `0x063` 表 54 条与 A 层 108 条的差集没对完
- `0x143622150` 那族英文解析器报错是否属于 `.ow` 解析器，未定

## 9. 解析器长什么样（2026-10-24 定稿，依据 E-75~E-79）

一句话：**没有关键词表，也没有「元素→参数个数」表；有「逐语法位置按类型挑读取器」。**

- **三层结构**：语句行总入口 `0x140C31417`（7 个语句词 + 队伍槽）→ 派发器 `0x1409BF0DD`（依次试
  设置/动作/条件/规则禁用）→ 各词校验函数（设置 `0x140C35130`、动作 `0x140C34C20`、条件 `0x140C34DC0`）。
  选词靠**调用顺序**，不靠表；函数指针/跳表在 exe 里 0 命中（E-75）。
- **槽位**：同一个 `.data` 全局 `0x144D98760` 被 7 个校验点共用——「为什么报 A 不报 B」的机器层答案是
  「走到哪一步 + 传了哪个句柄」，不是「查了哪张表」（E-76）。
- **报错编号＝文案句柄**：`0x0DE00000_<key_index>` 由 `movabs` 载入，整数错误码从不进上报函数（E-77）。
- **类型校，个数不校**（E-79）：
  每个参数位置按 CASC 签名里的类型挑一个读取器，读取器只认自己那种记号，读不到就报「之后应有一个 X」：
  队伍/玩家 `0x140C3C830`、数字与值 `0x140C37588`、选项 `0x140C3AD95`、动作 `0x140C393C4`、
  英雄名 `0x140C3E2B0`、关系运算子 `0x140C41648`、引号字符串在语句入口 `0x140C31417` 内联。
  **参数个数**这一层没有表也没有阈值：少写尾参时由终结符断言（期望 `;`）失败，报错指向最后读到的记号（E-78）。
- **八个「静态零引用」校验点都是真函数**：`0x140C2CC08` `0x140C2D397` `0x140C37588` `0x140C393C4`
  `0x140C3AD95` `0x140C3E6E2` `0x140C40C08` `0x140C47275` 各自的函数体内都有 2~10 条不同的报错发射，
  不是 ICF 别名、也不是空壳（E-79 修正 E-76 的开放项；可达性仍未经运行期证明）。
- **对校验器的意义**：引擎能拒的类型错（玩家/数字/字符串/布尔/下拉/队伍/英雄/地图/变量/子程序/扩展）
  我们的 `check` 都已镜像；**同类型内部的语义错**（数值范围合不合理、实体类型配不配）引擎不判，
  我们也别硬造检查——那是提示级假设，误报会把真问题淹掉。
