"""专有词库生成的运行选项。

默认值与上游 ``App\\Service\\Diff\\Option`` 完全一致，
保证「不改选项」时 Python 与 PHP 的行为逐条对齐。

对应上游源码：FixText/src/app/Service/Diff/Option.php
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Option:
    """专有词库生成 / 替换次数统计的选项集合。

    字段名与上游 Option 的属性名一一对应（Python 用 snake_case）。
    """

    #: 只有重复替换次数大于此值的词条才会进入报告
    replace_count_threshold: int = 0
    #: 截取差异字符时的上下文长度
    context_len: int = 3
    #: 0-不移除；>0 移除头部对应长度字符；<0 移除尾部对应长度字符
    remove_l_or_r_char: int = 0
    #: 是否依据特定关键字进行筛选
    filter_keywords: bool = False
    #: 是否需要提取跨行差异
    get_multi_line_content: bool = False
    #: 是否需要移除每处差异的首尾标点符号
    trim_punctuations: bool = False
    #: 是否另外存一份移除了 html 标签的内容
    add_html_stripped_copy: bool = True
    #: 是否记录当前时间（写入词库文件的时间点注释）
    add_current_time: bool = True
