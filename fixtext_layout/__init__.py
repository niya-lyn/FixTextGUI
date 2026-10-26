"""fixtext_layout — FixText 排版功能引擎（Python 复刻）。

对外主入口：``fixtext_layout.format_text(content, options)``。
规则权威来源为 FixText PHP 源码；与 PHP 的等价性证据见 docs/等价性对比报告.md。
"""

from fixtext_layout.engine import LayoutEngine, format_text
from fixtext_layout.options import LayoutOptions

__all__ = ['LayoutEngine', 'LayoutOptions', 'format_text']
__version__ = '1.0.0'
