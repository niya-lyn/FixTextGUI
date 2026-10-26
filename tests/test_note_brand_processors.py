# -*- coding: utf-8 -*-
"""T1.6 单元测试 —— noteBrandProcessors 3 处 PHP 闭包的 Python 重实现。

运行：pytest -q tests/test_note_brand_processors.py（不依赖 PHP，纯 Python 可跑）
每条用例的注释标注对应的 PHP 语义来源（general.php 行号 + PHP 原语）。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from note_brand_processors import (  # noqa: E402
    NOTE_BRAND_PROCESSORS,
    PHP_SOURCE_LINES,
    process_calibre,
    process_moonreader,
    process_weread,
)

# match 行结构（同 PHP PREG_SET_ORDER）：
#   [整体匹配, 分组1(划线/before), 分组2(批注/after，可缺失=None)]


# ---------------------------------------------------------------- moonreader

def test_moonreader_basic_split():
    # L1086-1093：分组1 尾部 " (批注)" 拆出；分组2 trim ' ()'
    m = [["x (a) y\n想法文字", "x (a) y", "想法文字"]]
    process_moonreader(m)
    assert m[0][1] == "x"
    assert m[0][2] == "a"  # "(a)" 去两端括号


def test_moonreader_no_annotation_untouched():
    # 无 " ("：分组1 不动、分组2 保持缺失（PHP 不写 $match[2]）
    m = [["只是划线\n想法", "只是划线", "想法"]]
    process_moonreader(m)
    assert m[0][1] == "只是划线"
    assert m[0][2] == "想法"


def test_moonreader_first_open_last_close():
    # 懒 `(.*?)` 取**最早**出现的 " ("；`(.*)` 贪婪+s 跨行取**最后**一个 ")"
    m = [["划线里也有 (第一) 个\n批注 (第二)", "划线里也有 (第一) 个\n批注 (第二)", "zz"]]
    process_moonreader(m)
    assert m[0][1] == "划线里也有"
    assert m[0][2] == "第一) 个\n批注 (第二"  # trim ' ()' 只剥两端字符集


def test_moonreader_trim_charset():
    # trim($ret[2], ' ()')：按字符集剥两端，中间不动
    m = [["划线 (  (( 嵌套 ))  )", "划线 (  (( 嵌套 ))  )", "zz"]]
    process_moonreader(m)
    # trim ' ()' 按字符集剥两端：两端所有空格/括号全剥，仅余最内层文字
    assert m[0][2] == "嵌套"


def test_moonreader_multiline_group1():
    # s 修饰符：分组1 可跨行，" (" 可出现在后续行
    m = [["第一行\n第二行 (批注)", "第一行\n第二行 (批注)", None]]
    process_moonreader(m)
    assert m[0][1] == "第一行\n第二行"
    assert m[0][2] == "批注"


def test_moonreader_missing_group2_autogrow():
    # PHP 数组缺键：$match[2] = ... 会自动创建下标 2；Python _set 补 None 再赋值
    m = [["划线 (批注)\n想法", "划线 (批注)"]]  # 行长仅 2（模拟 PHP 缺 $match[2] 键）
    process_moonreader(m)
    assert len(m[0]) == 3
    assert m[0][2] == "批注"


def test_moonreader_no_space_before_paren_not_split():
    # 必须是 " ("（空格+左括号）；紧贴的 "(" 不触发拆分
    m = [["划线(无空格)\n想法", "划线(无空格)", "想法"]]
    process_moonreader(m)
    assert m[0][1] == "划线(无空格)"


# ------------------------------------------------------------------ calibre

def test_calibre_heading_removed():
    # L1095-1100：删除所有 "#+ 至行尾" 片段（`.` 不跨行）
    m = [["## 标题\n正文", "## 标题\n正文", "zz"]]
    process_calibre(m)
    assert m[0][1] == "\n正文"


def test_calibre_heading_midline():
    # 行内 "xxx # yyy" → "xxx "（unanchored，# 不在行首也删）
    m = [["前后 # 中间标题", "前后 # 中间标题", "zz"]]
    process_calibre(m)
    assert m[0][1] == "前后 "


def test_calibre_hash_without_space_kept():
    # `#+ ` 必须含空格：无空格的 "#" 不删
    m = [["无空格#标签", "无空格#标签", "zz"]]
    process_calibre(m)
    assert m[0][1] == "无空格#标签"


def test_calibre_bom_removed():
    # str_replace(U+FEFF)：删除 BOM（源码中不可见字符）
    m = [["\ufeff正文", "\ufeff正文", "zz"]]
    process_calibre(m)
    assert m[0][1] == "正文"


def test_calibre_group2_untouched():
    # 只动分组1；分组2 原样保留
    m = [["## 标题\n正文\n感想", "## 标题\n正文", "感想"]]
    process_calibre(m)
    assert m[0][1] == "\n正文"
    assert m[0][2] == "感想"


# ------------------------------------------------------------------- weread

def test_weread_note_swaps_fields():
    # L1102-1119：含 "发表想法" 时 match[1]=原文、match[2]=想法（交换）
    whole = "◆ 发表想法\n这是想法\n原文：这是原文\n"
    m = [[whole, "旧1", "旧2"]]
    process_weread(m)
    assert m[0][1] == "这是原文\n"
    assert m[0][2] == "这是想法\n"


def test_weread_note_multiline_original():
    # 分组2 `(.*)` 贪婪+s：原文跨行全部纳入
    whole = "发表想法\n短评\n原文：第一行\n第二行\n"
    m = [[whole, "旧1", "旧2"]]
    process_weread(m)
    assert m[0][1] == "第一行\n第二行\n"
    assert m[0][2] == "短评\n"


def test_weread_note_missing_original_empty():
    # 内层 preg_match 失败（缺 "原文："）⇒ `$ret[1] ?? ''`、`$ret[2] ?? ''` 均为 ''
    m = [["◆ 发表想法\n只有想法没有原文\n", "旧1", "旧2"]]
    process_weread(m)
    assert m[0][1] == ""
    assert m[0][2] == ""


def test_weread_plain_underline_removes_marker():
    # 纯划线：match[1] = 整体匹配去所有 "◆ "；分组2 **保持原值不动**（PHP else 分支不写该键）
    m = [["◆ 划线一\n◆ 划线二\n", "旧1", "旧2"]]
    process_weread(m)
    assert m[0][1] == "划线一\n划线二\n"
    assert m[0][2] == "旧2"


def test_weread_plain_underline_autogrow():
    # 行长不足 2 时 _set 自动补位（PHP 数组自动扩展语义）；分组2 保持缺失
    m = [["◆ 划线\n"]]
    process_weread(m)
    assert len(m[0]) == 2
    assert m[0][1] == "划线\n"


def test_weread_overall_reverse_inplace():
    # 末尾整体倒序（原地 reverse，等价 PHP 引用重绑定 array_reverse）
    rows = [
        ["a", "a1", None],
        ["b 发表想法\nx\n原文：y", "b1", "b2"],
        ["c", "c1", None],
    ]
    process_weread(rows)
    assert [r[0] for r in rows] == ["c", "b 发表想法\nx\n原文：y", "a"]
    # 倒序后逐行核对：a/c 是纯划线行 ⇒ 分组1 被重写为整体匹配本身；
    # b 是批注行 ⇒ 分组1/2 交换为 原文/想法
    assert rows[0][1] == "c"
    assert rows[2][1] == "a"
    assert rows[1][1] == "y"
    assert rows[1][2] == "x\n"


def test_weread_priority_note_before_underline():
    # 源码注释：同一处既划线又批注时，划线排后 ⇒ 倒序后批注在前（优先级更高）
    note_row = ["◆ 发表想法\n想法\n原文：原文段", "x", "y"]
    underline_row = ["◆ 原文段\n", "x", "y"]
    rows = [underline_row, note_row]  # 匹配顺序：划线在后
    process_weread(rows)
    assert "发表想法" in rows[0][0]  # 倒序后批注行在前


# ---------------------------------------------------------------- registry

def test_registry_keys_and_lines():
    assert set(NOTE_BRAND_PROCESSORS) == {"moonreader", "calibre", "weread"}
    assert NOTE_BRAND_PROCESSORS["moonreader"] is process_moonreader
    assert NOTE_BRAND_PROCESSORS["calibre"] is process_calibre
    assert NOTE_BRAND_PROCESSORS["weread"] is process_weread
    assert PHP_SOURCE_LINES == {"moonreader": 1086, "calibre": 1095, "weread": 1102}


def test_processors_mutate_inplace_like_php_reference():
    # PHP `array &$matches` 引用传参 ⇒ Python 三个函数必须原地修改同一列表对象
    original = [["划线 (批注)\n想法", "划线 (批注)", "想法"]]
    aliased = original
    process_moonreader(original)
    assert aliased[0][2] == "批注"  # 同一对象被修改
