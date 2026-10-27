"""FixText 引号检查（Python 重实现）。

以 FixText（PHP）src/app/Service/Quotation/QuotationChecker.php 的检测逻辑为准，
逐行重实现为独立模块，供编排器调用。本包只做【检测与报告】，不含原工具的
交互式人工修复链（QuotationFixer 的 autoFix* 系列依赖人工确认选项）。

对齐口径（见 checker.QuotationChecker docstring）：原命令统计模式
（'c'，只统计错误数）下的单遍全文件扫描语义。
"""

from .checker import QuotationChecker, QuotationError, check_file, check_text

__all__ = ["QuotationChecker", "QuotationError", "check_file", "check_text"]
