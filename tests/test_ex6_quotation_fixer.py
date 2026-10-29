# -*- coding: utf-8 -*-
"""M4-EX.6-R1：引号修复引擎单测（7 规则 / 开关 / 多轮 / 边界）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "pipeline" / "vendor"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from fixtext_quotation.checker import check_text
from fixtext_quotation.fixer import QuotationFixer, fix_text
from fixtext_quotation.rules import (
    RULE_IDS,
    QuotationFixRules,
    load_fix_rules,
    save_fix_rules,
)


# ——— 规则样本（各规则至少一处可被该规则修掉）———


@pytest.mark.parametrize(
    "rule_id,src,expect_substr",
    [
        (
            "nested_doubles",
            "他说：“外层“内层”还在。”\n",
            "‘内层’",
        ),
        (
            "reverted_quotations",
            "他说：”写反了“完。\n",
            "“写反了”",
        ),
        (
            "repeated_quotations",
            "他说：“连写“同向。\n",
            "“连写”",
        ),
        (
            "sole_right_double",
            "句尾单独。”\n",
            "句尾单独。\n",
        ),
        (
            "sole_right_single",
            "句尾单独。’\n",
            "句尾单独。\n",
        ),
        (
            "missing_left_double",
            "他说：你好。”\n",
            "“他说：你好。”",  # PHP 正则把行首到右双整段前补左双
        ),
        (
            "missing_right_double",
            "他说：“你好。\n下一行\n",
            "“你好。”\n",
        ),
    ],
)
def test_each_rule_alone(rule_id: str, src: str, expect_substr: str):
    rules = QuotationFixRules().with_only(rule_id)
    # 有的样本可能被 checker 报在别的语义上；只断言本规则开时能改动且含期望片段
    assert check_text(src), f"样本应先被检查器报错: {rule_id}"
    result = fix_text(src, rules, max_rounds=8)
    assert result.text != src or expect_substr in result.text
    assert expect_substr in result.text
    assert all(a.rule_id == rule_id for a in result.actions)


@pytest.mark.parametrize("rule_id", list(RULE_IDS))
def test_rule_off_leaves_matching_sample(rule_id: str):
    """关掉某规则后，专属样本不应再被该规则改写（允许其它规则改）。"""
    samples = {
        "nested_doubles": "他说：“外层“内层”还在。”\n",
        "reverted_quotations": "他说：”写反了“完。\n",
        "repeated_quotations": "他说：“连写“同向。\n",
        "sole_right_double": "句尾单独。”\n",
        "sole_right_single": "句尾单独。’\n",
        "missing_left_double": "他说：你好。”\n",
        "missing_right_double": "他说：“你好。\n下一行\n",
    }
    src = samples[rule_id]
    rules = QuotationFixRules()
    setattr(rules, rule_id, False)
    result = fix_text(src, rules, max_rounds=8)
    assert all(a.rule_id != rule_id for a in result.actions)


def test_default_all_rules_on():
    r = QuotationFixRules()
    assert r.enabled_ids() == list(RULE_IDS)


def test_rules_roundtrip_json(tmp_path: Path):
    path = tmp_path / "quotation_fix_rules.json"
    rules = QuotationFixRules().with_only("nested_doubles", "missing_right_double")
    save_fix_rules(rules, path)
    loaded = load_fix_rules(path)
    assert loaded.to_dict() == rules.to_dict()
    assert load_fix_rules(tmp_path / "missing.json").enabled_ids() == list(RULE_IDS)


def test_eof_no_newline_missing_right_helper():
    """末行无 ``\\n`` 时 #6 仍补右双（checker 对无尾换行未闭合可能不报错，故测行级助手）。"""
    from fixtext_quotation.fixer import _fix_missing_right

    assert _fix_missing_right("他说：“你好。") == "他说：“你好。”"
    assert _fix_missing_right("他说：“你好。\n") == "他说：“你好。”\n"


def test_clean_text_untouched():
    src = "他说：“你好。”\n她说：‘也好。’\n"
    assert check_text(src) == []
    result = fix_text(src)
    assert result.text == src
    assert result.actions == []
    assert result.remaining_count == 0


def test_multi_round_recheck():
    """一处修复可能改变配对；多轮后应收敛并给出 remaining。"""
    # 双套双 + 缺右：第一轮嵌套改单，可能仍留其它问题
    src = "甲：“外“内”层\n乙：“完好。”\n"
    result = fix_text(src, max_rounds=16)
    assert result.rounds >= 1
    assert isinstance(result.remaining_count, int)
    # 不应振荡超限后仍每次都改
    result2 = fix_text(result.text, max_rounds=4)
    assert result2.actions == [] or result2.text == result.text


def test_does_not_corrupt_clean_line_when_other_line_errors():
    """报错行旁的正常配对行不得被 #6 误加右引号。"""
    src = "好的：“正常。”\n坏的：“缺右\n"
    result = fix_text(src, QuotationFixRules().with_only("missing_right_double"))
    assert "“正常。”" in result.text
    assert result.text.count("“正常。””") == 0


def test_quotation_fixer_class_and_from_file(tmp_path: Path):
    path = tmp_path / "rules.json"
    save_fix_rules(QuotationFixRules().with_only("nested_doubles"), path)
    fixer = QuotationFixer.from_rules_file(path)
    src = "他说：“外层“内层”还在。”\n"
    out = fixer.fix(src)
    assert "‘内层’" in out.text
    assert out.to_dict()["remaining_count"] == out.remaining_count


def test_fix_result_actions_have_labels():
    src = "他说：“外层“内层”还在。”\n"
    result = fix_text(src, QuotationFixRules().with_only("nested_doubles"))
    assert result.actions
    assert result.actions[0].rule_name
    assert result.actions[0].line >= 1
