# -*- coding: utf-8 -*-
"""引号修复规则开关（M4-EX.6-R1）。

7 条对应 PHP ``QuotationFixer`` 的 7 个 ``autoFix*``；默认全开。
持久化 UI 在 R2；本模块只提供读写接口与默认落点约定。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterator, Mapping

#: 与 PHP autoFix 链式顺序一致（亦为默认应用顺序）
RULE_IDS: tuple[str, ...] = (
    "nested_doubles",        # autoFixNestedDoubles
    "reverted_quotations",   # autoFixRevertedQuotations
    "repeated_quotations",   # autoFixRepeatedQuotations
    "sole_right_double",     # autoFixSoleRightDouble
    "sole_right_single",     # autoFixSoleRightSingle
    "missing_left_double",   # autoFixMissingLeftDouble
    "missing_right_double",  # autoFixMissingRightDouble（流水线统一按 TXT 语义）
)

RULE_LABELS: dict[str, str] = {
    "nested_doubles": "双套双引号改单引号",
    "reverted_quotations": "写反引号反转",
    "repeated_quotations": "连续同向引号归一",
    "sole_right_double": "句尾孤立右双引号移除",
    "sole_right_single": "句尾孤立右单引号移除",
    "missing_left_double": "补左双引号",
    "missing_right_double": "补右双引号",
}


@dataclass
class QuotationFixRules:
    """7 条布尔开关；字段名即 ``RULE_IDS``。"""

    nested_doubles: bool = True
    reverted_quotations: bool = True
    repeated_quotations: bool = True
    sole_right_double: bool = True
    sole_right_single: bool = True
    missing_left_double: bool = True
    missing_right_double: bool = True

    def enabled_ids(self) -> list[str]:
        return [rid for rid in RULE_IDS if getattr(self, rid)]

    def to_dict(self) -> dict[str, bool]:
        return {f.name: bool(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "QuotationFixRules":
        """缺省全开；未知键忽略；非 bool 按真值转换。"""
        base = {f.name: True for f in fields(cls)}
        if data:
            for f in fields(cls):
                if f.name in data:
                    base[f.name] = bool(data[f.name])
        return cls(**base)

    def with_only(self, *enabled: str) -> "QuotationFixRules":
        """测试辅助：只打开列出的规则。"""
        d = {rid: False for rid in RULE_IDS}
        for rid in enabled:
            if rid not in RULE_IDS:
                raise KeyError(rid)
            d[rid] = True
        return QuotationFixRules.from_mapping(d)


def iter_rule_ids() -> Iterator[str]:
    return iter(RULE_IDS)


def default_rules_path(workspace: Path | str | None = None) -> Path:
    """R2 将把开关持久化到用户区；R1 约定默认路径，不强制创建。"""
    if workspace is None:
        return Path("workspace") / "quotation_fix_rules.json"
    return Path(workspace) / "quotation_fix_rules.json"


def load_fix_rules(path: Path | str | None = None) -> QuotationFixRules:
    """读规则文件；文件不存在或损坏 → 全开默认。"""
    if path is None:
        return QuotationFixRules()
    p = Path(path)
    if not p.is_file():
        return QuotationFixRules()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return QuotationFixRules()
    if not isinstance(data, dict):
        return QuotationFixRules()
    # 允许包一层 {"rules": {...}}
    if "rules" in data and isinstance(data["rules"], dict):
        data = data["rules"]
    return QuotationFixRules.from_mapping(data)


def save_fix_rules(rules: QuotationFixRules, path: Path | str) -> None:
    """写入规则文件（R2 UI 调用；R1 供测试与预留）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "rules": rules.to_dict(),
        "labels": dict(RULE_LABELS),
    }
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
