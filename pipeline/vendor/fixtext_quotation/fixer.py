# -*- coding: utf-8 -*-
"""引号修复引擎（M4-EX.6-R1）。

对照 PHP ``QuotationFixer`` 的 7 个 ``autoFix*``，做成**非交互**整书文本修复，
供检查页（逐处/批量）与校正流水线共用。本模块不碰 UI、不改 ``stages/quote.py``。

对齐口径：
- PHP 只在 ``dumpErr`` 当前行上链式尝试 autoFix；本引擎每轮先
  ``check_text``，再**只改报错行**（避免 #6 等规则误伤正常行）。
- 规则 #6（补右双引号）：卡要求**不做文件类型分支**，统一 TXT 行尾 ``\\n`` 语义；
  末行无换行时单独处理。
- 多轮复查：修 → 再扫 → 直至文本不再变化或达 ``max_rounds``；返回最终剩余错误。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from .checker import QuotationError, check_text, _php_file_lines
from .rules import RULE_IDS, RULE_LABELS, QuotationFixRules, load_fix_rules

_FLAGS = re.MULTILINE

_RE_NESTED = re.compile(
    r"“([^\n。…？！；～~（）：“”‘’]+?)”(?=.*”)",
    _FLAGS,
)
_RE_REVERTED = re.compile(
    r"[”’]([^\n、，。…？！；～~（）：“”‘’]+?)[“‘]",
    _FLAGS,
)
_REPEATED_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"“([^\n”‘’]*?)“", _FLAGS), r"“\1”"),
    (re.compile(r"”([^\n“‘’]*?)”([^\n“‘’]*?)”", _FLAGS), r"”\1“\2”"),
    (re.compile(r"”([^\n“‘’]*?)”", _FLAGS), r"“\1”"),
    (re.compile(r"‘([^\n“”’]*?)‘", _FLAGS), r"‘\1’"),
    (re.compile(r"’([^\n“”‘]*?)’", _FLAGS), r"‘\1’"),
)
_RE_SOLE_RD = re.compile(r"([^“]*)”((</p>)?[\r\n<]*)$", _FLAGS)
_RE_SOLE_RS = re.compile(r"([^‘]*)’((</p>)?[\r\n<]*)$", _FLAGS)
_RE_MISS_LD = re.compile(r"([^“\s<>【】]*”)((.*?)(</p>)?[\r\n<]*)$", _FLAGS)
_RE_MISS_RD = re.compile(r"(“[^<>”]*)(.*)\n", _FLAGS)
_RE_MISS_RD_EOF = re.compile(r"(“[^<>”]*)$", _FLAGS)


@dataclass
class FixAction:
    """一次具体替换（可供检查页展示）。"""

    rule_id: str
    rule_name: str
    before: str
    after: str
    round_index: int = 1
    line: int = 0

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "before": self.before,
            "after": self.after,
            "round_index": self.round_index,
            "line": self.line,
        }


@dataclass
class FixResult:
    """修复结果：文本 + 动作列表 + 复查剩余。"""

    text: str
    actions: list[FixAction] = field(default_factory=list)
    rounds: int = 0
    remaining_errors: list[QuotationError] = field(default_factory=list)

    @property
    def remaining_count(self) -> int:
        return len(self.remaining_errors)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "actions": [a.to_dict() for a in self.actions],
            "rounds": self.rounds,
            "remaining_count": self.remaining_count,
            "remaining_errors": [e.to_dict() for e in self.remaining_errors],
        }


def _clip(s: str, n: int = 120) -> str:
    s = s.replace("\r", "\\r")
    return s if len(s) <= n else s[: n - 1] + "…"


def _record(
    actions: list[FixAction],
    rule_id: str,
    before: str,
    after: str,
    round_index: int,
    line: int,
) -> None:
    if before == after:
        return
    actions.append(
        FixAction(
            rule_id=rule_id,
            rule_name=RULE_LABELS[rule_id],
            before=_clip(before),
            after=_clip(after),
            round_index=round_index,
            line=line,
        )
    )


def _sub_line(
    line: str,
    pattern: re.Pattern[str],
    repl: str | Callable[[re.Match[str]], str],
) -> str:
    if callable(repl):
        return pattern.sub(repl, line)
    return pattern.sub(repl, line)


def _fix_nested(line: str) -> str | None:
    if not _RE_NESTED.search(line):
        return None

    def repl(m: re.Match[str]) -> str:
        return "‘" + m.group(1) + "’"

    return _sub_line(line, _RE_NESTED, repl)


def _fix_reverted(line: str) -> str | None:
    if not _RE_REVERTED.search(line):
        return None

    def repl(m: re.Match[str]) -> str:
        s = m.group(0)
        for a, b in (
            ("“", "<<rdq>>"),
            ("”", "<<ldq>>"),
            ("‘", "<<rsq>>"),
            ("’", "<<lsq>>"),
        ):
            s = s.replace(a, b)
        for a, b in (
            ("<<rdq>>", "”"),
            ("<<ldq>>", "“"),
            ("<<rsq>>", "’"),
            ("<<lsq>>", "‘"),
        ):
            s = s.replace(a, b)
        return s

    return _sub_line(line, _RE_REVERTED, repl)


def _fix_repeated(line: str) -> str | None:
    # PHP：当前行只选第一条命中的子规则
    for pattern, repl in _REPEATED_RULES:
        if pattern.search(line):
            return _sub_line(line, pattern, repl)
    return None


def _fix_sole_right_double(line: str) -> str | None:
    if not _RE_SOLE_RD.search(line):
        return None
    return _sub_line(line, _RE_SOLE_RD, r"\1\2")


def _fix_sole_right_single(line: str) -> str | None:
    if not _RE_SOLE_RS.search(line):
        return None
    return _sub_line(line, _RE_SOLE_RS, r"\1\2")


def _fix_missing_left(line: str) -> str | None:
    if not _RE_MISS_LD.search(line):
        return None
    return _sub_line(line, _RE_MISS_LD, r"“\1\2")


def _fix_missing_right(line: str) -> str | None:
    # TXT 语义：有换行用 ``…\n``；末行无换行用 EOF 变体
    if _RE_MISS_RD.search(line):
        return _sub_line(line, _RE_MISS_RD, r"\1\2”\n")
    if "\n" not in line and _RE_MISS_RD_EOF.search(line):
        return _sub_line(line, _RE_MISS_RD_EOF, r"\1”")
    return None


#: 与 PHP 链式顺序一致；返回新行或 None（本规则未命中）
_LINE_FIXERS: dict[str, Callable[[str], str | None]] = {
    "nested_doubles": _fix_nested,
    "reverted_quotations": _fix_reverted,
    "repeated_quotations": _fix_repeated,
    "sole_right_double": _fix_sole_right_double,
    "sole_right_single": _fix_sole_right_single,
    "missing_left_double": _fix_missing_left,
    "missing_right_double": _fix_missing_right,
}


def _join_php_lines(lines: list[str]) -> str:
    return "".join(lines)


def apply_rules_to_error_lines(
    text: str,
    rules: QuotationFixRules,
    error_lines: set[int],
    *,
    round_index: int = 1,
    actions: list[FixAction] | None = None,
) -> tuple[str, list[FixAction]]:
    """对报错行按启用规则链式尝试（对齐 PHP dumpErr → autoFix 链）。

    每行采用**第一条命中**的启用规则即停（对齐 PHP：某 autoFix 成功后
    ReloadThenSkip，不再对本行继续后续规则）。
    """
    bag = actions if actions is not None else []
    if not error_lines:
        return text, bag

    lines = _php_file_lines(text)
    enabled = [rid for rid in RULE_IDS if getattr(rules, rid)]

    for lineno in sorted(error_lines):
        idx = lineno - 1
        if idx < 0 or idx >= len(lines):
            continue
        original = lines[idx]
        current = original
        for rid in enabled:
            new = _LINE_FIXERS[rid](current)
            if new is None or new == current:
                continue
            _record(bag, rid, current, new, round_index, lineno)
            current = new
            break  # 本行本轮只采纳一条（对齐 PHP 抛 ReloadThenSkip）
        lines[idx] = current

    return _join_php_lines(lines), bag


def apply_rules_once(
    text: str,
    rules: QuotationFixRules,
    *,
    round_index: int = 1,
    actions: list[FixAction] | None = None,
) -> tuple[str, list[FixAction]]:
    """先扫错，再对报错行跑一轮修复链。"""
    errs = check_text(text)
    return apply_rules_to_error_lines(
        text,
        rules,
        {e.line for e in errs},
        round_index=round_index,
        actions=actions,
    )


def fix_text(
    text: str,
    rules: QuotationFixRules | None = None,
    *,
    max_rounds: int = 16,
) -> FixResult:
    """修复整书文本并多轮复查。

    Parameters
    ----------
    text:
        当前书文本（流水线里已是合并后的整书 TXT）。
    rules:
        规则开关；``None`` 表示全开默认。
    max_rounds:
        最多复查轮数（防振荡）。
    """
    rules = rules or QuotationFixRules()
    actions: list[FixAction] = []
    current = text
    rounds = 0

    for i in range(1, max(1, max_rounds) + 1):
        rounds = i
        before = current
        errs = check_text(current)
        if not errs:
            break
        current, _ = apply_rules_to_error_lines(
            current,
            rules,
            {e.line for e in errs},
            round_index=i,
            actions=actions,
        )
        if current == before:
            break

    remaining = check_text(current)
    return FixResult(
        text=current,
        actions=actions,
        rounds=rounds,
        remaining_errors=remaining,
    )


class QuotationFixer:
    """可复用的修复器实例（检查页 / 流水线持有同一配置源）。"""

    def __init__(self, rules: QuotationFixRules | None = None):
        self.rules = rules or QuotationFixRules()

    @classmethod
    def from_rules_file(cls, path: str | None = None) -> "QuotationFixer":
        return cls(load_fix_rules(path))

    def fix(self, text: str, *, max_rounds: int = 16) -> FixResult:
        return fix_text(text, self.rules, max_rounds=max_rounds)

    def set_rules(self, rules: QuotationFixRules) -> None:
        self.rules = rules
