#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_errors.py —— 生成 data/errors-full.tsv（报错文案全集）。

数据来源（两张外部表，只读；路径可用 --strings / --errors 覆盖）：

1. CASC 0x07C zhCN 文本表：guid / key_index / locale / reserved / region / platform / len / text
   默认 C:\\owdump\\lobby-probe\\out\\strings_07C.tsv
2. 上一轮筛出的工坊报错表：字符串ID / 文本 / 邻域组号 / 层 / 命中关键词
   默认 C:\\owdump\\parser-re\\errors.tsv（A 层 108 条解析器级 + B 层 12 条导入/界面提示）

用法：
    python tools/gen_errors.py                 # 生成 data/errors-full.tsv 并打印统计
    python tools/gen_errors.py --check         # 只比对不写盘（漂移退出 1）
    python tools/gen_errors.py --stats         # 只打印分类统计
    python tools/gen_errors.py --emit-doc PATH # 另外输出 docs/errors.md 用的分类 markdown 表

纪律：原文一字不改（只去掉行尾 NUL 与 \\r）；槽位含义按模板位置显式声明，判不出的写「未知」；
两次运行输出必须字节一致（表按编号排序，无时间戳）。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "errors-full.tsv"
DEFAULT_STRINGS = r"C:\owdump\lobby-probe\out\strings_07C.tsv"
DEFAULT_ERRORS = r"C:\owdump\parser-re\errors.tsv"

CAT_ORDER = ["语法解析", "类型", "参数个数", "名字不存在", "设置与地图", "导入器 GUID", "配额与上限", "其他"]

COLUMNS = [
    "编号",            # errors.tsv 的 字符串ID（= 0x07C 的 key_index）
    "层",              # A=解析器级 / B=导入与界面提示
    "归属",            # 上面 8 类之一
    "报错原文",        # 一字不改
    "槽数",            # 模板里 %N$s 的个数
    "槽位含义",        # 如 1=期望的记号;2=实际;3=行号，判不出写 未知
    "触发条件",        # 推断：游戏在什么情况下吐这句
    "真因",            # 实际写错的是什么
    "改法",            # 怎么修
    "能提前报",        # 能 / 部分 / 不能（现有 ws.py check）
    "检查类别",        # 语法 / 类型 / 参数 / 名字 / GUID / 配额 / 设置 / —（缺口清单按这列归类）
    "断言引用",        # docs/rules.tsv 的 E-xx 或 validator-coverage 的检查名；没有写 无
    "证据等级",        # L0=文案存在；L0+L1=另有结构推断（槽位/触发由占位符位置反推）
    "出处",            # guid + idx；同表给 errors.tsv 行号
    "邻域组",
]

# ---------------------------------------------------------------------------
# 分类表：每个分组 = 一批同族文案 + 判定。
# ids 必须覆盖 errors.tsv 的每一行（脚本会断言，漏一条直接报错）。
# slots 写法：  "1=期望的记号;2=实际写到的记号;3=行号"，条数必须等于模板里的槽数。
# ---------------------------------------------------------------------------
GROUPS: list[dict] = [
    # ---------------- 语法解析 ----------------
    dict(
        ids=[51129], cat="语法解析", slots="1=期望的记号;2=实际写到的记号;3=行号",
        trigger="解析器在该位置要求一个固定记号（实测最常见是 `;` 或 `)`），读到的却是别的东西",
        cause="少写分号 / 少写尾参 / 该写函数的地方裸写了名字",
        fix="在报的行补上期望的记号；参数个数按语料补齐（如 创建效果 至少 6 参），不要按签名省参数",
        pre="部分", kind="语法", rf="E-55", ev="L0+L1",
    ),
    dict(
        ids=[51130], cat="语法解析", slots="1=期望的剪贴板段名;2=行号",
        trigger="导入/粘贴的文本缺少剪贴板结构的起始段（复制时只拷了半截）",
        cause="粘贴内容被截断，或从中间开始复制",
        fix="重新完整复制（从文件第一行开始），或用 ws.py fix 重新导出",
        pre="不能", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51131], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求一个带引号的字符串字面量，读到的是别的记号",
        cause="字符串没写引号，或中文引号/全角引号被当成字符",
        fix="把该处改成 \"...\"，或（字符串参数）包一层 自定义字符串(...)",
        pre="部分", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51148], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求一个队伍（所有队伍 / 队伍1 / 队伍2），读到别的词",
        cause="队伍参数写成事件筛选词（双方/全部）或写错队伍名",
        fix="队伍值只认 所有队伍 / 队伍1 / 队伍2；全部、双方只用在事件块的选择器行",
        pre="能", kind="参数", rf="E-51", ev="L0+L1",
    ),
    dict(
        ids=[51149], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求一个玩家表达式（事件玩家 / 所有玩家(...) 等），读到字面量或队伍词",
        cause="玩家槽塞了数字或队伍筛选词",
        fix="玩家槽写 事件玩家 / 所有玩家(所有队伍)；队伍词换成 所有玩家(队伍1)",
        pre="部分", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51150], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求英雄参数，读到裸英雄名或别的值",
        cause="英雄参数没包 英雄(...)",
        fix="写成 英雄(死神)；数据里的英雄名要逐字一致",
        pre="能", kind="参数", rf="E-51", ev="L0+L1",
    ),
    dict(
        ids=[51151], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求一个变量引用（全局.X / 事件玩家.X / 玩家.X），读到别的记号",
        cause="变量没带域（裸写 i = 1）或变量名不存在",
        fix="赋值与取值都带域：全局.i / 事件玩家.i；变量名要在变量块里声明",
        pre="部分", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51152], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求数值字面量，读到字符串/变量/函数",
        cause="数值参数写了字符串或未加域的变量",
        fix="改成纯数字（百分比也写纯数字 50，不写 50%）",
        pre="部分", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51153], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求关系运算符（== / != / > / < 等），读到的不是运算符",
        cause="条件写成赋值 `=`，或运算符写成中文/全角",
        fix="条件用 ==；只在赋值语句里用 =",
        pre="不能", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51154], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器在事件块要求事件名，读到非事件名",
        cause="事件名写错（如官方改名），或事件块缺事件名",
        fix="事件名对照 data/events.tsv 的 14 个写法",
        pre="能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51155], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求一个下拉选项词，读到不在选项里的词",
        cause="下拉参数写了自己编的词 / 旧版本词",
        fix="按 data/param-options.tsv 的该参数选项逐字写",
        pre="能", kind="参数", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51156], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求一个值表达式，读到动作或空",
        cause="等号右边写了动作；或参数位置留空/多写了逗号",
        fix="右边只能用值函数；动作单独成句，再用 上一个文本ID 一类取值",
        pre="部分", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51158], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="剪贴板结构没有以应有的结束段收尾",
        cause="粘贴内容被截断，或段落顺序被打乱",
        fix="重新完整复制整份文本；不要手工删段落边界",
        pre="不能", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51159], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求一个动作，读到值函数或别的记号",
        cause="值函数当动作写（比赛结束();），或动作名写错",
        fix="值函数不能单独成句；动作名对照签名表",
        pre="部分", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51160], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="规则块里事件段没有正常结束（缺事件行或事件段没收尾）",
        cause="规则里没写 事件 { ... }，或事件段少分号",
        fix="每条规则以 事件 { 事件名; 选择器; } 开头；`check` 已能直接拦（规则缺事件块）",
        pre="能", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51161], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="该处数字写法不合法（超出范围、格式不对）",
        cause="数字里混了单位/百分号/全角字符",
        fix="写纯数字；百分比不带 %",
        pre="部分", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51163], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="该处字符串写法解析器不支持",
        cause="字符串里用了未转义引号 / 写了引擎不认的文本选项",
        fix="文本选项只能取 data/strings.md 里的 615 条；自由文本包 自定义字符串(\"...\")",
        pre="部分", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51164], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="该位置读到类型与槽位不兼容的值",
        cause="槽位类型与填的值不匹配（如数值槽填玩家表达式）",
        fix="按签名表该参数的类型填；队伍/英雄/玩家三类最容易错",
        pre="部分", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[51166], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="注释语法错误（`//` 之后或注释块写坏）",
        cause="注释里混了引号/反斜杠，或注释没换行就接了代码",
        fix="注释单独成行或行尾，别在注释里留未闭合引号",
        pre="不能", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[52840], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="字符串字面量内部出现真实换行",
        cause="手写多行字符串，没合并成一行",
        fix="字符串写在一行内；需要换行就分成两条（或写引擎认的转义写法）",
        pre="能", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[52841], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="字符串字面量缺右引号",
        cause="少写 \"，或字符串里有未转义引号",
        fix="补齐引号；引号内的引号要转义；`check` 按行数引号奇偶直接拦",
        pre="能", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[54290], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器在地图块要求地图名，读到的不是合法地图名",
        cause="写了地图内部子区域名（釜山寺院），或地图名不在当前版本",
        fix="只写主图名（釜山）；`ws.py check` 会点名不在编辑器里的名字",
        pre="能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[61799], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器在模式块要求游戏模式名，读到的不是合法模式名",
        cause="模式名写了编辑器显示名（攻击/护送），而 .ow 里要写 攻击护送",
        fix="按 data/mode-list.tsv 的写法：攻击护送、占领要点 6v6（小写 v）、角斗领域 训练靶场",
        pre="部分", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[65241], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器在子程序事件处要求子程序名，读到的不是已声明子程序",
        cause="子程序名写错，或子程序块没声明",
        fix="名字与子程序块里的声明逐字一致；`ws.py check` 会报未声明",
        pre="能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[65687, 65688, 65689, 65709, 65710, 65711, 65719, 65723, 65767, 65918],
        cat="设置与地图", slots="1=实际写到的记号;2=行号",
        trigger="设置块层级/键位置不对：解析器在该层要求 大厅/主程序/游戏模式/英雄/队伍/设置/设置选项/数据中心 结构，读到的不是",
        cause="设置块结构与层级写错（键挂错层、启用英雄 挂在 英雄 直属层、模式块里写英雄页键）",
        fix="按 data/schema-keys.tsv 的归属摆：综合 只收模式系键，英雄页键写进英雄块；启用英雄 写在 综合/队伍1/队伍2 里",
        pre="能", kind="设置", rf="E-45", ev="L0+L1",
    ),
    dict(
        ids=[65712, 65718], cat="设置与地图", slots="1=实际写到的记号;2=行号",
        trigger="同一设置块里同一类设置/队伍出现两次",
        cause="整段复制粘贴导致重复块",
        fix="删掉重复的那个块",
        pre="能", kind="设置", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[65728, 65729, 177340], cat="设置与地图", slots="",
        trigger="设置块里出现引擎不认的类别（英雄/队伍/游戏模式/地图/赛前环节 设置）",
        cause="设置块写了该模式不支持的类别（如团队模式里写 赛前环节）",
        fix="按模式页实际有的类别写；`ws.py settings <模式>` 查当前可用键",
        pre="部分", kind="设置", rf="无", ev="L0+L1",
    ),
    dict(
        # v13 探针 c5 / c4（E-84，用户实机）：同两句文案至少还有两种真因——值越界、编号不存在。
        # 玩家只看这两句分不出是哪一种，所以 trigger/cause 都要写全。
        ids=[65730, 65731], cat="设置与地图", slots="",
        trigger="设置块里的值/编号引擎不认：类别不支持、数值越界、地图编号不存在 三种都吐这一句",
        cause="① 设置块写了该模式不支持的类别（如团队模式里写 赛前环节）；"
              "② 数值超出该键范围（v13 c5：获胜得分 9999 > 上限 5000 → 65730）；"
              "③ 地图编号前缀对但表里没有（v13 c4：972777519512069999 → 65731）",
        fix="类别按模式页实际有的写；数值按 data/setting-ranges.tsv 的范围写；"
            "地图编号从编辑器里选、不要手抄（`ws.py check` 能提前报这三类）",
        pre="能", kind="设置", rf="E-84", ev="L0+L1+L3",
    ),
    dict(
        ids=[65724, 65725, 65726, 65727], cat="名字不存在", slots="",
        trigger="设置块引用了不存在的游戏类型 / 英雄 / 地图 / 队伍",
        cause="名字写错、版本删改、或该模式没有这个值",
        fix="对照 data/modes.tsv / heroes.tsv / maps.tsv / map-pools.tsv 逐字改",
        pre="能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[68414], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求按钮名，读到的不是 10 个按钮之一",
        cause="按钮名写错（按钮(技能三)）",
        fix="按钮名对照 data/buttons.tsv 的 10 个",
        pre="能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[70577], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求 真 / 假，读到别的写法",
        cause="布尔槽写了 开启/关闭/是/否/1",
        fix="布尔字面量只写 真 / 假",
        pre="部分", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[76176], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求扩展名，读到的不是 11 个扩展之一",
        cause="扩展名写错或用旧名",
        fix="按 docs/extensions.md 的 11 个写法",
        pre="不能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[67738], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器要求赋值/条件左侧是一个变量，读到的不是",
        cause="赋值左边写了表达式或字面量",
        fix="左边只能是 全局.X / 事件玩家.X / 玩家.X",
        pre="部分", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[67739], cat="语法解析", slots="1=实际写到的记号;2=行号",
        trigger="解析器在语句位置要求赋值运算符，读到别的东西",
        cause="值函数当动作写（比赛结束();）或语句写坏",
        fix="该行改成赋值，或换用对应动作",
        pre="部分", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50045], cat="语法解析", slots="",
        trigger="循环动作（如 循环 / While 体）之前没有 等待 动作",
        cause="引擎要求每个循环迭代至少有一次让出（等待）",
        fix="循环体里加 `等待(0.1, 无视条件);`（放循环开头或结尾）",
        pre="不能", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[65581], cat="语法解析", slots="",
        trigger="子程序对应的规则里写了条件块",
        cause="子程序事件规则加了 条件",
        fix="把判断挪进子程序体里的 If",
        pre="不能", kind="语法", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[65607], cat="名字不存在", slots="",
        trigger="两条规则都声明了同一个子程序名",
        cause="复制规则后忘改子程序名",
        fix="每个子程序只留一条声明规则",
        pre="不能", kind="名字", rf="无", ev="L0+L1",
    ),
    # ---------------- 类型 ----------------
    dict(
        ids=[50044], cat="类型", slots="",
        trigger="把字符串值存进变量",
        cause="工坊变量只能存数字/向量等，字符串不能入变量",
        fix="字符串改用 自定义字符串 现拼，或用 HUD 文本承载",
        pre="不能", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[70076], cat="类型", slots="",
        trigger="局部值（本地玩家相关的值）进入非视觉/HUD 位置，通常是存进全局变量",
        cause="设置全局变量(x, 生命值(本地玩家)) 或 全局.x = 生命值(本地玩家)",
        fix="存玩家数据用玩家变量；需要「这个人」把规则换成 持续 - 每名玩家 + 事件玩家",
        pre="能", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50042], cat="类型", slots="",
        trigger="把「当前数组的元素」这个值用在数组遍历之外",
        cause="在 For 之外引用 当前数组元素",
        fix="取值放进 For 里面，或用 数组中的值(arr, i)",
        pre="部分", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[70077], cat="类型", slots="",
        trigger="把「当前数组的索引」用在数组遍历之外",
        cause="在 For 之外引用 当前数组索引",
        fix="放进 For 里面，或自己维护计数变量",
        pre="不能", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50043], cat="类型", slots="",
        trigger="某些值被叠加到多于 1 层（叠加语义不支持）",
        cause="对不支持叠加的值做了重复叠加",
        fix="改成显式相乘/相加，别指望叠加",
        pre="不能", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50049], cat="类型", slots="",
        trigger="脚本里出现当前上下文受限制的值（如该事件不允许的引用）",
        cause="用了当前事件/规则上下文不允许的值",
        fix="换事件或换取值路径；先 `ws.py check` 看是否点名",
        pre="不能", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50055], cat="类型", slots="",
        trigger="值本身非法（类型对但取值不合法）",
        cause="枚举/范围外的值，或数组/向量写法不合法",
        fix="对照 data/ 的取值表改；这类游戏不给细节，先跑 check",
        pre="不能", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50040], cat="类型", slots="",
        trigger="在 持续 - 全局 规则里引用 事件玩家",
        cause="全局规则没有事件上下文，事件玩家不存在",
        fix="换成 持续 - 每名玩家 + 事件玩家，或改用 所有玩家(所有队伍)",
        pre="能", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50041], cat="类型", slots="",
        trigger="攻击者/被攻击者 出现在不是「玩家参与消灭」一类的事件里",
        cause="事件选错，或在持续规则里引用这两个值",
        fix="换到对应事件（玩家造成最后一击 / 玩家参与消灭）",
        pre="部分", kind="类型", rf="check_attacker_scope", ev="L2",
    ),
    dict(
        ids=[52256], cat="类型", slots="",
        trigger="治疗者/被治疗者 出现在不是治疗类事件里",
        cause="事件选错",
        fix="换到 玩家受到治疗 / 玩家造成治疗 一类事件",
        pre="不能", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[65498], cat="类型", slots="",
        trigger="同一个变量同时被 Chase 行动和 For 行动使用",
        cause="Chase（追踪）与 For 抢同一个变量",
        fix="两处用不同变量",
        pre="不能", kind="类型", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[67646], cat="类型", slots="1=实际写到的记号;2=行号",
        trigger="该位置之前读到类型不兼容的值（与 51164 同族，位置在前）",
        cause="槽位类型与填的值不匹配",
        fix="按签名表该参数类型填",
        pre="部分", kind="类型", rf="无", ev="L0+L1",
    ),
    # ---------------- 名字不存在 ----------------
    dict(
        ids=[60278, 60314], cat="名字不存在", slots="1=实际写到的记号;2=行号",
        trigger="引用了未声明/无法识别的变量",
        cause="变量名写错，或变量块里没声明",
        fix="在变量块声明同名变量；名字逐字一致（大小写敏感）",
        pre="能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[60279], cat="名字不存在", slots="1=实际写到的记号;2=行号",
        trigger="变量索引超出声明范围",
        cause="手工改过变量块的序号",
        fix="让变量块的序号连续（重新导出最省事）",
        pre="不能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[60280], cat="名字不存在", slots="1=实际写到的记号;2=行号",
        trigger="同一段（全局 / 玩家）里两行写同一个索引",
        cause="复制粘贴变量行后没改序号",
        fix="同一段内索引唯一即可（跳号没关系）；改掉重复的那一行",
        pre="能", kind="变量", rf="check_var_index_dup", ev="L2",
    ),
    dict(
        ids=[65531, 65536], cat="名字不存在", slots="1=实际写到的记号;2=行号",
        trigger="引用了未声明/无法识别的子程序",
        cause="子程序名写错或子程序块缺失",
        fix="对照子程序块的名字逐字改",
        pre="能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[65532, 65533], cat="名字不存在", slots="1=实际写到的记号;2=行号",
        trigger="子程序索引超出范围 / 重复",
        cause="手工改过子程序块的序号",
        fix="子程序序号连续不重复；重新导出",
        pre="不能", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[60190, 60201], cat="名字不存在", slots="1=变量名",
        trigger="变量声明处名字为空",
        cause="变量块里留了空名",
        fix="补上名字或删掉该声明",
        pre="部分", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[60193, 60203, 60285, 60290], cat="名字不存在", slots="1=变量名",
        trigger="两个变量（全局或玩家）同名/冲突",
        cause="复制粘贴导致重名",
        fix="每个变量独立命名",
        pre="部分", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[60197, 60202, 60281, 60288], cat="名字不存在", slots="1=变量名",
        trigger="变量名含非法字符",
        cause="名字里用了空格/标点/中文以外的符号等",
        fix="用字母数字下划线，别用空格和标点",
        pre="部分", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[60206, 60207, 60282, 60289], cat="名字不存在", slots="1=变量名",
        trigger="变量名过长",
        cause="名字超过引擎上限（具体字节数未验证）",
        fix="缩短名字；上限值未验证，别贴着猜",
        pre="部分", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[65242, 65243, 65244, 65245, 65534, 65535], cat="名字不存在", slots="1=子程序名",
        trigger="子程序声明的名字为空/过长/非法/与另一个冲突/子程序本身过长",
        cause="子程序命名或体积问题",
        fix="子程序名短且唯一、只用字母数字下划线；过长的子程序拆开",
        pre="部分", kind="名字", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[76839], cat="名字不存在", slots="",
        trigger="引用了不存在的工坊扩展",
        cause="扩展名写错或版本没有该扩展",
        fix="按 docs/extensions.md 的 11 个扩展写",
        pre="不能", kind="名字", rf="无", ev="L0+L1",
    ),
    # ---------------- 导入器 GUID ----------------
    dict(
        ids=[50053], cat="导入器 GUID", slots="",
        trigger="导入时脚本头的值/版本与当前引擎不匹配（文件被外部改过或版本旧）",
        cause="改过 .ow 头、或用别的版本导出后手工编辑",
        fix="在编辑器里重新导出一次（重新保存），再用 ws.py fix 做格式修补",
        pre="不能", kind="GUID", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50054], cat="导入器 GUID", slots="",
        trigger="导入时动作/条件词典与引擎内置表不一致",
        cause="版本差异导致元素编号对不上（跨版本导入）",
        fix="用当前版本编辑器重新导出；跨版本文件不要硬导",
        pre="不能", kind="GUID", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50029], cat="导入器 GUID", slots="",
        trigger="导入时脚本逻辑尚未载入（引擎状态未就绪）",
        cause="重试太早，或上一份脚本还在加载",
        fix="稍等再导；持续失败重启游戏客户端",
        pre="不能", kind="GUID", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[30872], cat="导入器 GUID", slots="1=未知（内层错误详情）",
        trigger="通用错误前缀：把具体原因拼在这句后面",
        cause="看实际拼进来的那句；本行本身不含原因",
        fix="按拼接进来的具体错误处理",
        pre="不能", kind="GUID", rf="无", ev="L0+L1",
    ),
    # ---------------- 配额与上限 ----------------
    dict(
        ids=[50039], cat="配额与上限", slots="",
        trigger="脚本总量过大（规则/动作总量）",
        cause="单文件塞了太多动作",
        fix="拆成多个模式文件；`ws.py count` 看估算",
        pre="部分", kind="配额", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50113], cat="配额与上限", slots="",
        trigger="自定游戏设置（设置块）体积过大",
        cause="设置块条目过多",
        fix="删掉不影响玩法的设置项",
        pre="部分", kind="配额", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[50048], cat="配额与上限", slots="",
        trigger="单个动作列表过于复杂（嵌套/元素过多）",
        cause="一条规则里塞了超长动作链",
        fix="拆成多条规则或子程序",
        pre="不能", kind="配额", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[61873], cat="配额与上限", slots="",
        trigger="自定义字符串条数超上限",
        cause="大量 自定义字符串 重复写",
        fix="合并重复文本，或改成运行时拼接",
        pre="不能", kind="配额", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[70585, 74809], cat="配额与上限", slots="",
        trigger="地图工坊设置项 / 设置选项数量超上限",
        cause="每个英雄每项都写了设置",
        fix="只写需要改的项，其余用默认",
        pre="不能", kind="配额", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[76448, 76840], cat="配额与上限", slots="",
        trigger="已用扩展点数超过可用点数（可用点数按大厅空栏位算）",
        cause="开的扩展太多，或大厅栏位写小导致可用点数变少",
        fix="减扩展，或把大厅空栏位调大（可用点数 = 4 × 空栏位，推断值）",
        pre="不能", kind="配额", rf="无", ev="L0+L1",
    ),
    # ---------------- 其他 ----------------
    dict(
        ids=[24164], cat="其他", slots="",
        trigger="运行时除数为零",
        cause="表达式里除数可能是 0（或数组长度的差）",
        fix="除数加保护：先判断再除，或 最大值(除数, 1)",
        pre="部分", kind="运行时", rf="check_divide_by_zero", ev="L2",
    ),
    dict(
        ids=[50050], cat="其他", slots="",
        trigger="账号/环境禁用了用户生成内容",
        cause="家长控制或账号 UGC 限制",
        fix="检查账号设置；本地环境问题，校验器无法预判",
        pre="不能", kind="—", rf="无", ev="L0+L1",
    ),
    # ---------------- B 层：导入与界面提示 ----------------
    dict(
        ids=[1048, 1049, 7321], cat="设置与地图", slots="",
        trigger="大厅/自定游戏的地图、名称或选项不合法（界面提示，导入时也会出现）",
        cause="地图没选、名字为空或含非法字符、选项不在允许范围",
        fix="先选一张该模式池里的图、起个合法名字；`ws.py check` 会先拦明显项",
        pre="部分", kind="设置", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[17588, 17848, 22873, 35491], cat="设置与地图", slots="",
        trigger="设置块整体不合法（界面统一提示；导出/导入时同一原因）",
        cause="设置块结构或取值错，常见于整段复制",
        fix="按 data/setting-ranges.tsv 的范围改；`ws.py check` 先跑一遍",
        pre="能", kind="设置", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[25575, 50028], cat="设置与地图", slots="",
        trigger="没有可用的地图（地图页全关，或写的地图在该模式下选不到）",
        cause="「关闭所有」地图；或地图写法与该模式池不匹配",
        fix="别全关；按 data/map-pools.tsv 该模式的写法逐字改",
        pre="部分", kind="设置", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[25576, 50038], cat="设置与地图", slots="",
        trigger="没有可用的英雄（英雄页全关，或写错英雄名）",
        cause="英雄页全部关闭",
        fix="至少开一个英雄；名字对照 data/heroes.tsv",
        pre="部分", kind="设置", rf="无", ev="L0+L1",
    ),
    dict(
        ids=[65644], cat="导入器 GUID", slots="",
        trigger="从剪贴板导入前的确认提示（不是错误）",
        cause="点了「从剪贴板导入」",
        fix="确认会覆盖当前设置再点；备份当前导出",
        pre="不能", kind="GUID", rf="无", ev="L0",
    ),
]

# ---------------------------------------------------------------------------
# 补录层 C：同一张 0x07C 表里、但 errors.tsv 的 5 个关键词过滤没抓到的工坊报错。
# 判定依据：同表可读到（L0 文案存在）；用途按语义推断（L1）；errors.tsv 里没有行号。
# ---------------------------------------------------------------------------
SUPPLEMENT: list[dict] = [
    dict(
        id=68106, cat="设置与地图", slots="",
        trigger="大厅设置不合法（导入/退出设置页时出现；界面与导入两条路径同一句）",
        cause="队伍栏位合计超 12、单队超 12、观战者超上限、团队模式占混战栏位",
        fix="按 data/setting-ranges-lobby.tsv 改；`ws.py check` 会点名具体哪一项",
        pre="能", kind="设置", rf="无",
    ),
    dict(
        id=62494, cat="配额与上限", slots="1=单条规则长度上限（KB）",
        trigger="单条规则超过引擎给的 KB 上限（面板提示里带上限值，实测为 98）",
        cause="一条规则里塞了超长动作链",
        fix="拆成多条规则；`ws.py check` 按 100352 字节（98KB）判",
        pre="能", kind="配额", rf="无",
    ),
    dict(
        id=70584, cat="名字不存在", slots="",
        trigger="两个「地图工坊设置」用了同一个自定义名（忽略空格与大小写）",
        cause="批量生成时同名的 地图工坊设置整数/开关/字符串 写了多次",
        fix="每个自定义设置独立命名；批量生成器加序号",
        pre="不能", kind="名字", rf="无",
    ),
    dict(
        id=73024, cat="名字不存在", slots="",
        trigger="同一个「地图工坊设置」里两个选项用了同一个自定义名",
        cause="选项名重复（多个设置之间重名是允许的，同一设置内不行）",
        fix="同一设置内选项名唯一",
        pre="不能", kind="名字", rf="无",
    ),
    dict(
        id=70586, cat="类型", slots="",
        trigger="「地图工坊设置」的类别/名称参数不是无参数的 自定义字符串(...)",
        cause="把变量或带参数的自定义字符串传进去",
        fix="写成 自定义字符串(\"名字\")，不带 {0} 一类占位符",
        pre="部分", kind="类型", rf="无",
    ),
    dict(
        id=70589, cat="类型", slots="",
        trigger="类别/名称参数为空，或含 { } : 等符号",
        cause="名字里用了花括号/冒号，或留空",
        fix="名字非空且不含 { } :",
        pre="不能", kind="类型", rf="无",
    ),
    dict(
        id=73023, cat="类型", slots="",
        trigger="「地图工坊设置组合」的选项参数不是由 自定义字符串 组成的非空数组",
        cause="传了空数组、数字数组，或写了裸字符串",
        fix="写成 数组(自定义字符串(\"A\"), 自定义字符串(\"B\"))",
        pre="部分", kind="类型", rf="无",
    ),
    dict(
        id=73025, cat="类型", slots="",
        trigger="「地图工坊设置」的字符串参数为空，或含 { } : 等符号",
        cause="字符串值留空或含占位符符号",
        fix="非空且不含 { } :",
        pre="不能", kind="类型", rf="无",
    ),
    dict(
        id=51443, cat="配额与上限", slots="",
        trigger="整个自定义游戏里的工坊脚本总量超过服务器配额（整局被关闭）",
        cause="房间内多人/多脚本合计超限",
        fix="减少脚本数量或体积；这是房间级限制，单文件检查管不到",
        pre="不能", kind="配额", rf="无",
    ),
    dict(
        id=52767, cat="设置与地图", slots="",
        trigger="存在无效设置，无法重新开始（界面提示）",
        cause="设置块里有引擎不认的键或值",
        fix="`ws.py check` 先跑；按报出的键改",
        pre="部分", kind="设置", rf="无",
    ),
    dict(
        id=51027, cat="其他", slots="1=未知（错误码段）;2=未知;3=未知",
        trigger="运行自定义游戏时客户端崩溃，附带三段错误码",
        cause="脚本把客户端打崩（多半是极端循环或巨量实体）",
        fix="按错误码查；先缩小到能复现的最小规则",
        pre="不能", kind="—", rf="无",
    ),
    dict(
        id=50052, cat="其他", slots="",
        trigger="未知错误（没有更具体的文案）",
        cause="未分类，游戏自己也不知道",
        fix="只能靠二分法定位：注释掉一半规则再导",
        pre="不能", kind="—", rf="无",
    ),
    dict(
        id=77207, cat="名字不存在", slots="",
        trigger="某个名字包含无效字符",
        cause="名字里出现非法字符（具体字符集未验证）",
        fix="改成字母数字下划线",
        pre="部分", kind="名字", rf="无",
    ),
    dict(
        id=47990, cat="导入器 GUID", slots="",
        trigger="创建「游戏设置代码」失败（导入代码路径，不是 .ow 文件路径）",
        cause="代码字符串被截断或校验失败",
        fix="重新完整复制代码串",
        pre="不能", kind="GUID", rf="无",
    ),
    dict(
        id=47997, cat="导入器 GUID", slots="",
        trigger="导入「游戏设置代码」时解析失败",
        cause="代码串损坏/版本不符",
        fix="重新复制；跨版本代码不要硬导",
        pre="不能", kind="GUID", rf="无",
    ),
    dict(
        id=76429, cat="配额与上限", slots="",
        trigger="已用扩展点数超过可用扩展点数（与 76448 同义，带不带「错误：」前缀）",
        cause="开的扩展太多，或大厅栏位少导致可用点数不足",
        fix="减扩展；可用点数 = 4 × 空栏位数（推断）",
        pre="不能", kind="配额", rf="无",
    ),
]

GROUP_BY_ID: dict[int, dict] = {}
for g in GROUPS:
    for i in g["ids"]:
        if i in GROUP_BY_ID:
            raise SystemExit(f"分类表重复：{i}")
        GROUP_BY_ID[i] = g

SUPP_BY_ID = {g["id"]: g for g in SUPPLEMENT}
_overlap = set(SUPP_BY_ID) & set(GROUP_BY_ID)
if _overlap:
    raise SystemExit(f"补录与已归档重复：{sorted(_overlap)}")



def clean(text: str) -> str:
    return text.replace("\x00", "").replace("\r", "").strip()


def load_strings(path: Path) -> dict[int, list[tuple[str, str]]]:
    idx: dict[int, list[tuple[str, str]]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            try:
                key = int(row["key_index"])
            except (TypeError, ValueError):
                continue
            idx.setdefault(key, []).append((row["guid"], clean(row["text"])))
    return idx


def load_errors(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for i, r in enumerate(rows):
        r["_line"] = i + 2  # 表头占第 1 行
        r["_id"] = int(r["字符串ID"])
        r["_text"] = clean(r["文本"])
    return rows


SLOT_RE = re.compile(r"%([1-9])\$s")


def build(strings_path: Path, errors_path: Path) -> tuple[list[list[str]], dict]:
    strings = load_strings(strings_path)
    errors = load_errors(errors_path)

    out: list[list[str]] = []
    problems: list[str] = []
    for r in errors:
        idx, text = r["_id"], r["_text"]
        cands = strings.get(idx, [])
        match = [(g, t) for (g, t) in cands if t == text]
        if not match:
            problems.append(f"{idx}: 在 strings 表里找不到同文（候选 {len(cands)} 条）")
            continue
        guid = match[0][0]
        g = GROUP_BY_ID.get(idx)
        if g is None:
            problems.append(f"{idx}: 分类表没覆盖")
            continue

        found = SLOT_RE.findall(text)
        n = len(found)
        declared = g["slots"]
        if declared:
            want = len([x for x in declared.split(";") if x.strip()])
            if want != n:
                problems.append(f"{idx}: 声明槽数 {want} 与模板 {n} 不符：{text}")
        elif n:
            problems.append(f"{idx}: 有 {n} 个槽但没声明含义：{text}")

        label = "A" if r["层"] == "A" else "B"
        out.append([
            str(idx), label, g["cat"], text, str(n), declared or "—",
            g["trigger"], g["cause"], g["fix"], g["pre"], g["kind"],
            g["rf"], g["ev"],
            f"{guid} idx={idx} | errors.tsv:{r['_line']}" if guid else f"errors.tsv:{r['_line']}",
            r.get("邻域组号", ""),
        ])

    out.sort(key=lambda row: int(row[0]))

    # 补录层 C：同表可读、errors.tsv 未收录
    for idx, g in SUPP_BY_ID.items():
        cands = strings.get(idx, [])
        if not cands:
            problems.append(f"C{idx}: 在 strings 表里找不到")
            continue
        guid, text = cands[0]
        found = SLOT_RE.findall(text)
        n = len(found)
        declared = g["slots"]
        if declared:
            want = len([x for x in declared.split(";") if x.strip()])
            if want != n:
                problems.append(f"C{idx}: 声明槽数 {want} 与模板 {n} 不符：{text}")
        elif n:
            problems.append(f"C{idx}: 有 {n} 个槽但没声明含义：{text}")
        out.append([
            str(idx), "C", g["cat"], text, str(n), declared or "—",
            g["trigger"], g["cause"], g["fix"], g["pre"], g["kind"], g["rf"], "L0+L1",
            f"{guid} idx={idx} | errors.tsv:未收录（本轮补录）", "",
        ])
    out.sort(key=lambda row: int(row[0]))

    # 断言：A 层全部归档
    a_total = sum(1 for r in errors if r["层"] == "A")
    a_done = sum(1 for row in out if row[1] == "A")
    if problems:
        raise SystemExit("生成失败：\n  " + "\n  ".join(problems))
    if a_done != a_total:
        raise SystemExit(f"A 层归档不全：{a_done}/{a_total}")

    # 断言：非 A 档不许当判据 —— 「断言引用」非「无」的行，层必须是 A
    # 依据：B 档在 exe 里没有引用点、C 档只是导入界面文案，拿它们当检查依据就是误报源（E-77 / E-78）
    bad_tier = [row for row in out if row[11].strip() not in ("无", "") and row[1] != "A"]
    if bad_tier:
        raise SystemExit(
            "档位断言失败：以下条目的「断言引用」不是「无」，但层不是 A（B/C 档只做报错翻译，不做判据）：\n  "
            + "\n  ".join(f"{r[0]}（{r[1]} 档，引用 {r[11]}）：{r[3][:40]}" for r in bad_tier))

    stats = summarize(out, a_total, len(errors))
    return out, stats


def summarize(rows: list[list[str]], a_total: int, total: int) -> dict:
    from collections import Counter
    cat = Counter(r[2] for r in rows)
    pre = Counter(r[9] for r in rows)
    pre_a = Counter(r[9] for r in rows if r[1] == "A")
    kind = Counter(r[10] for r in rows if r[9] in ("不能", "部分") and r[1] == "A")
    dup = Counter(r[3] for r in rows)
    dup_texts = [(t, c) for t, c in dup.items() if c > 1]
    layers = Counter(r[1] for r in rows)
    return {
        "total": len(rows), "a": a_total, "b": layers.get("B", 0), "c": layers.get("C", 0),
        "cat": cat, "pre": pre, "pre_a": pre_a, "kind_gap": kind,
        "dup_texts": dup_texts,
    }


def render(rows: list[list[str]]) -> str:
    lines = ["\t".join(COLUMNS)]
    for r in rows:
        cells = [c.replace("\t", " ").replace("\n", " ") for c in r]
        lines.append("\t".join(cells))
    return "\n".join(lines) + "\n"


def print_stats(stats: dict) -> None:
    print(f"总条数 {stats['total']}（A 解析器级 {stats['a']} / B 导入与界面 {stats['b']} / C 本轮补录 {stats['c']}）")
    print("\n按归属：")
    for cat in CAT_ORDER:
        if stats["cat"].get(cat):
            print(f"  {cat:<8} {stats['cat'][cat]:>3}")
    print("\n现有校验器能否提前报（全部）：")
    for k in ("能", "部分", "不能"):
        print(f"  {k:<3} {stats['pre'].get(k, 0):>3}")
    print("A 层：")
    for k in ("能", "部分", "不能"):
        print(f"  {k:<3} {stats['pre_a'].get(k, 0):>3}")
    if stats["kind_gap"]:
        print("\n缺口按检查类别（A 层 部分+不能）：")
        for k, v in stats["kind_gap"].most_common():
            print(f"  {k:<5} {v:>3}")
    if stats["dup_texts"]:
        print("\n同文多条（同一句原文多个编号 / A+B 重复）：")
        for t, c in sorted(stats["dup_texts"], key=lambda x: -x[1]):
            print(f"  ×{c}  {t}")


def emit_doc(rows: list[list[str]], path: Path) -> None:
    """导出 docs/errors.md 用的分类表（原文直接取自表，避免手抄）。"""
    by_cat: dict[str, list[list[str]]] = {}
    for r in rows:
        by_cat.setdefault(r[2], []).append(r)
    buf: list[str] = []
    for cat in CAT_ORDER:
        rs = by_cat.get(cat, [])
        if not rs:
            continue
        buf.append(f"### {cat}（{len(rs)} 条）\n")
        buf.append("| 编号 | 原文（逐字） | 真因 | 改法 | 校验器 | 断言 |")
        buf.append("|---|---|---|---|---|---|")
        for r in rs:
            tag = "" if r[1] == "A" else "（B 层）"
            buf.append(
                f"| {r[0]}{tag} | `{r[3]}` | {r[7]} | {r[8]} | {r[9]} / {r[10]} | {r[11]} |"
            )
        buf.append("")
    path.write_text("\n".join(buf) + "\n", encoding="utf-8", newline="\n")
    print(f"doc 表已写入 {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成报错文案全集 data/errors-full.tsv")
    ap.add_argument("--strings", default=DEFAULT_STRINGS, help="0x07C 全量 zhCN 文本表")
    ap.add_argument("--errors", default=DEFAULT_ERRORS, help="已筛出的报错表")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--check", action="store_true", help="只比对不写盘；漂移退出 1")
    ap.add_argument("--stats", action="store_true", help="只打印统计")
    ap.add_argument("--emit-doc", default=None, help="额外输出分类 markdown 表")
    a = ap.parse_args(argv)

    sp, ep = Path(a.strings), Path(a.errors)
    for p in (sp, ep):
        if not p.exists():
            print(f"找不到输入：{p}", file=sys.stderr)
            return 2

    rows, stats = build(sp, ep)
    text = render(rows)
    md5 = hashlib.md5(text.encode("utf-8")).hexdigest()
    stats["md5"] = md5

    if a.stats:
        print_stats(stats)
        print(f"\nmd5 {md5}")
        return 0

    out = Path(a.out)
    if a.check:
        old = out.read_text(encoding="utf-8") if out.exists() else ""
        if old != text:
            print(f"漂移：{out} 与重新生成的内容不一致", file=sys.stderr)
            return 1
        print(f"无漂移（{len(rows)} 行，md5 {md5}）")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"写入 {out}：{len(rows)} 行，md5 {md5}")

    print_stats(stats)
    if a.emit_doc:
        emit_doc(rows, Path(a.emit_doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
