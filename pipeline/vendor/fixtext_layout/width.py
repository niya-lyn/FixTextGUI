"""东亚文字宽度库 —— 字符宽度的度量与计算。

说明（重要边界）
================

FixText 的 PHP 原始实现里**没有**宽度库与禁排/挤压逻辑；本模块是任务规格点名
要求的 Python 侧扩展能力，用于支撑 :mod:`fixtext_layout.kinsoku` 的禁排换行与
标点挤压。它**不参与**默认排版路径 —— ``LayoutEngine.format()`` 的输出与 PHP
逐字节等价，不会调用本模块。

宽度口径
========

参照 Unicode 东亚宽度（East Asian Width）属性：

=================  ==============  ========  =========================
east_asian_width   含义           宽度      示例
=================  ==============  ========  =========================
``W``              全角(Wide)      2        汉字、々、ぁ-ん、ァ-ン
``F``              全角(Fullwidth) 2        ＡＢＣ、１２３、！？
``A``              两可(Ambiguous) 可配置    ±、×、·、希腊字母
``Na``             窄(Narrow)      1        a-zA-Z、半角数字
``H``              半角(Halfwidth) 1        ｧｨｩ、ﾊﾋﾌ
``N``              中立(Neutral)   1        空格、组合符号
=================  ==============  ========  =========================

``A``（两可宽度）在 CJK 排版习惯里常按全角（2）处理，在拉丁排版里按半角（1）。
默认按 1 处理，可通过 :class:`WidthConfig` 调整。

组合字符（Mn/Mc/Me 类）宽度计 0，与「视觉上不占独立列」一致。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Optional

__all__ = ['WidthConfig', 'char_width', 'text_width', 'visual_length', 'display_width']

# 宽度常量
ZERO = 0
NARROW = 1
WIDE = 2

#: East Asian Width 属性 → 宽度（两可 A 除外，见 WidthConfig.ambiguous_wide）
_EAW_WIDTH = {
    'W': WIDE,
    'F': WIDE,
    'Na': NARROW,
    'H': NARROW,
    'N': NARROW,
}


@dataclass
class WidthConfig:
    """宽度计算配置。

    Attributes:
        ambiguous_wide: 两可宽度（``A``）字符按宽（2）还是窄（1）计。
            CJK 语境通常设 True；默认 False 与多数终端一致。
        combining_zero: 组合记号（Mn/Mc/Me）宽度按 0 计，默认 True。
        control_zero: 控制字符（Cc）宽度按 0 计，默认 True。
        tab_width: 制表符宽度（默认 0，禁排换行场景按不占列处理）。
    """

    ambiguous_wide: bool = False
    combining_zero: bool = True
    control_zero: bool = True
    tab_width: int = 0

    def width_of(self, ch: str) -> int:
        """返回单字符宽度（0 / 1 / 2）。"""
        if len(ch) != 1:
            raise ValueError('width_of 只接受单个字符: %r' % ch)
        cat = unicodedata.category(ch)
        if self.combining_zero and cat in ('Mn', 'Mc', 'Me'):
            return ZERO
        if self.control_zero and cat == 'Cc':
            if ch == '\t':
                return self.tab_width
            return ZERO
        eaw = unicodedata.east_asian_width(ch)
        if eaw == 'A':
            return WIDE if self.ambiguous_wide else NARROW
        return _EAW_WIDTH[eaw]

    def width(self, text: str) -> int:
        """返回整段文本的显示宽度（按显示列累加）。"""
        total = 0
        for ch in text:
            total += self.width_of(ch)
        return total


#: 进程级默认配置（两可宽度按窄计）
DEFAULT = WidthConfig()


def char_width(ch: str, config: Optional[WidthConfig] = None) -> int:
    """单字符显示宽度（0/1/2）。"""
    return (config or DEFAULT).width_of(ch)


def text_width(text: str, config: Optional[WidthConfig] = None) -> int:
    """整段文本的显示宽度（显示列数累加）。"""
    return (config or DEFAULT).width(text)


#: :func:`text_width` 的别名，便于按「视觉长度」语义调用
visual_length = text_width

#: :func:`text_width` 的别名，便于按「显示宽度」语义调用
display_width = text_width
