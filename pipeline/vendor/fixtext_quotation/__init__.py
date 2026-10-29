"""FixText 引号检查 / 修复（Python 重实现）。

检测：以 FixText（PHP）QuotationChecker.php 为准（见 checker docstring）。
修复（M4-EX.6-R1）：对照 QuotationFixer 的 7 个 autoFix，见 fixer / rules。
"""

from .checker import QuotationChecker, QuotationError, check_file, check_text
from .fixer import FixAction, FixResult, QuotationFixer, apply_rules_once, fix_text
from .rules import (
    RULE_IDS,
    RULE_LABELS,
    QuotationFixRules,
    load_fix_rules,
    save_fix_rules,
)

__all__ = [
    "QuotationChecker",
    "QuotationError",
    "check_file",
    "check_text",
    "QuotationFixer",
    "QuotationFixRules",
    "FixAction",
    "FixResult",
    "RULE_IDS",
    "RULE_LABELS",
    "fix_text",
    "apply_rules_once",
    "load_fix_rules",
    "save_fix_rules",
]
