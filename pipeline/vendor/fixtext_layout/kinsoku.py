"""标点禁排（禁则处理）与挤压 —— 按显示宽度做 CJK 行断行。

说明（重要边界）
================

FixText 的 PHP 原始实现里**没有**禁排/挤压逻辑；本模块是任务规格点名要求的
Python 侧扩展能力。它**不参与** ``LayoutEngine.format()`` 的默认排版路径——
默认输出与 PHP 逐字节等价。需要按固定宽度重排时，由调用方显式调用
:func:`wrap_text`。

规则说明
========

**行首禁排**：句读点与收尾类标点（``，。、；：？！``、收括号/收引号、省略号等）
不能出现在行首。

**行尾禁排**：开括号/开引号类字符不能出现在行尾。

**挤压**：行尾连续全角标点中，最左一个保持全宽、其余折半宽（全角 2 → 半宽 1），
使行尾标点不被挤到下一行。仅在「按全宽计已溢出、按挤压宽计不溢出」时启用。

断行算法（贪心 + 禁则回退）
==========================

逐字累加显示宽度；行满后从行尾向行首回退寻找合法断点（行尾非开括号、
行首非禁排标点），在断点处断行；找不到合法断点时硬断（保证有进展）。
宽度度量委托 :mod:`fixtext_layout.width`。
"""

from __future__ import annotations

from typing import List, Optional

from .width import WidthConfig, char_width

__all__ = [
    'LINE_START_FORBIDDEN',
    'LINE_END_FORBIDDEN',
    'COMPRESSION_TARGETS',
    'can_break_before',
    'can_break_after',
    'effective_width',
    'wrap_text',
]

#: 行首禁排字符：句读点、收尾类括号/引号、省略号等
LINE_START_FORBIDDEN = (
    '，。、；：？！'
    '）】〉》」』〕'
    '”’'
    '…‥'
    '·'
    ',.;:?!'
)

#: 行尾禁排字符：起始类括号/引号
LINE_END_FORBIDDEN = (
    '（【〈《「『〔'
    '“‘'
)

#: 可参与挤压的行尾标点
COMPRESSION_TARGETS = '，。、；：？！”’』」）】》〉'

_START_FORBIDDEN = frozenset(LINE_START_FORBIDDEN)
_END_FORBIDDEN = frozenset(LINE_END_FORBIDDEN)
_COMPRESSION = frozenset(COMPRESSION_TARGETS)


def can_break_before(ch: str) -> bool:
    """``ch`` 是否允许出现在行首（不在行首禁排集合中即允许）。"""
    return ch not in _START_FORBIDDEN


def can_break_after(ch: str) -> bool:
    """``ch`` 是否允许出现在行尾（不在行尾禁排集合中即允许）。"""
    return ch not in _END_FORBIDDEN


def effective_width(line: str, config: Optional[WidthConfig] = None,
                    compression: bool = False) -> int:
    """一行文本的有效宽度；``compression=True`` 时应用行尾标点挤压。

    挤压规则：行尾连续**全角**可挤压标点中，最左 1 个保持全宽（2 列），
    其余每个折半（2 → 1 列）。
    """
    cfg = config or WidthConfig()
    full = cfg.width(line)
    if not compression:
        return full
    run = 0
    for ch in reversed(line):
        if ch in _COMPRESSION and cfg.width_of(ch) == 2:
            run += 1
        else:
            break
    if run >= 2:
        return full - (run - 1)
    return full


def _find_break_point(buf: str, next_ch: Optional[str],
                      cfg: WidthConfig) -> Optional[int]:
    """在已排满的 ``buf`` 内寻找合法断点下标 ``pos``（当前行 = buf[:pos]）。

    断点约束：
    * ``buf[pos-1]`` 可以出现在行尾（非开括号/开引号）；
    * 断点后的首字符（``buf[pos]`` 或溢出的 ``next_ch``）可以出现在行首
      （非句读点/收尾标点）。

    从 ``len(buf)`` 向行首回退；无合法断点返回 None。
    """
    pos = len(buf)
    while pos > 0:
        if not can_break_after(buf[pos - 1]):
            pos -= 1
            continue
        nxt = buf[pos] if pos < len(buf) else next_ch
        if nxt is not None and not can_break_before(nxt):
            pos -= 1
            continue
        return pos
    return None


def _wrap_paragraph(par: str, width: int, cfg: WidthConfig,
                    compression: bool) -> List[str]:
    """对单段文本按宽度贪心断行（含禁排与可选挤压）。"""
    lines: List[str] = []
    buf: List[str] = []
    used = 0
    for ch in par:
        w = cfg.width_of(ch)
        if buf and used + w > width:
            if compression and effective_width(''.join(buf) + ch, cfg, True) <= width:
                buf.append(ch)
                used += w
                continue
            text = ''.join(buf)
            cut = _find_break_point(text, ch, cfg)
            if cut is None or cut == 0:
                cut = len(text)
            lines.append(text[:cut])
            rest = text[cut:]
            buf = list(rest)
            used = cfg.width(rest)
        buf.append(ch)
        used += w
    if buf:
        lines.append(''.join(buf))
    return lines


def wrap_text(text: str, width: int,
              config: Optional[WidthConfig] = None,
              compression: bool = True,
              keep_paragraphs: bool = True) -> str:
    """按显示宽度断行，应用禁排与挤压规则。

    Args:
        text: 待重排文本。
        width: 目标行宽（显示列数），必须 > 0。
        config: 宽度配置，默认 :data:`fixtext_layout.width.DEFAULT`。
        compression: 是否启用行尾标点挤压。
        keep_paragraphs: True 时按原换行分段、段内重排（保留段界）；
            False 时先把原换行符移除、整段重排。

    Returns:
        重排后文本（换行符 ``\\n``）。算法单遍扫描，复杂度 O(n)。

    示例::

        >>> wrap_text('他说：“你好。”然后走了。', 8)
        '他说：“你好。”\\n然后走了。'
    """
    if width <= 0:
        raise ValueError('width 必须 > 0，收到 %r' % width)
    cfg = config or WidthConfig()

    if not keep_paragraphs:
        text = text.replace('\n', '')

    out: List[str] = []
    for par in text.split('\n'):
        if par == '':
            out.append('')
            continue
        out.extend(_wrap_paragraph(par, width, cfg, compression))
    return '\n'.join(out)
