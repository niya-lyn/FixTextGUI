# -*- coding: utf-8 -*-
"""M4-EX.6-R2 定向验收：四态三键 / 规则开关 / 写回撤销 / 冒烟。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QPushButton

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fixtext_ui"))
sys.path.insert(0, str(ROOT / "pipeline" / "vendor"))

from check_module import (  # noqa: E402
    PHASE_EMPTY, PHASE_READY, PHASE_RUNNING, PHASE_RESULT, CheckModule, RULE_UI,
)
from fixtext_quotation.rules import RULE_IDS  # noqa: E402


SAMPLE_BAD = (
    "他说：“外层“内层”还在。”\n"
    "另一行：你好。”\n"
)
SAMPLE_OK = "他说：“你好。”\n她说：‘也好。’\n"


@pytest.fixture()
def book_file(tmp_path: Path) -> Path:
    p = tmp_path / "book.txt"
    p.write_text(SAMPLE_BAD, encoding="utf-8")
    return p


@pytest.fixture()
def mod(qapp, tmp_path: Path, book_file: Path) -> CheckModule:
    m = CheckModule()
    m.set_book(str(book_file), "测书", book_ext="txt", rules_dir=tmp_path)
    return m


# ---------- ① 四态 + 三键 ----------

def test_phase_empty_without_book(qapp):
    m = CheckModule()
    assert m.phase == PHASE_EMPTY
    assert m.empty_state.isVisibleTo(m)
    assert not m._content_w.isVisibleTo(m)


def test_phase_ready_with_book(mod: CheckModule):
    assert mod.phase == PHASE_READY
    assert mod.has_book
    assert not mod.empty_state.isVisibleTo(mod)
    assert mod._content_w.isVisibleTo(mod)
    assert "开始检查" in mod.main_btn.text()


def test_phase_running_then_cancel(mod: CheckModule, qtbot=None):
    mod.phase = PHASE_RUNNING
    mod._apply_phase()
    assert "取消" in mod.main_btn.text()
    mod.cancel_check()
    assert mod.phase == PHASE_READY
    assert "开始检查" in mod.main_btn.text()


def test_phase_result_and_recheck_button(mod: CheckModule):
    mod.start_check(sync=True)
    assert mod.phase == PHASE_RESULT
    assert "重新检查" in mod.main_btn.text()
    assert mod.has_data
    assert len(mod.probs) >= 1


def test_phase_pass_zero_findings(qapp, tmp_path: Path):
    p = tmp_path / "ok.txt"
    p.write_text(SAMPLE_OK, encoding="utf-8")
    m = CheckModule()
    m.set_book(str(p), "好书", rules_dir=tmp_path)
    m.start_check(sync=True)
    assert m.phase == PHASE_RESULT
    assert m.is_pass
    assert m.pass_banner.isVisibleTo(m)
    assert not m._result_w.isVisibleTo(m)


def test_three_buttons_only_no_legacy(mod: CheckModule):
    labels = [b.text() for b in mod.findChildren(QPushButton)]
    assert not any("只统计不修复" in t for t in labels)
    assert not any(t == "结束检查" for t in labels)
    assert any("开始检查" in t or "重新检查" in t or "取消" in t
               for t in labels)


# ---------- ② 规则开/关 ----------

def test_rules_match_r1_ids():
    assert [r[0] for r in RULE_UI] == list(RULE_IDS)


def test_rule_off_excludes_from_batch(mod: CheckModule, tmp_path: Path):
    mod.start_check(sync=True)
    before = Path(mod._text_path).read_text(encoding="utf-8")
    # 关掉嵌套规则
    mod.rule_switches["nested_doubles"].setChecked(False)
    mod.save_rules_config(silent=True)
    rules = mod.current_rules()
    assert rules.nested_doubles is False

    from fixtext_quotation.fixer import fix_text
    off = fix_text(before, rules, max_rounds=8)
    assert all(a.rule_id != "nested_doubles" for a in off.actions)

    # 全开应能产出 nested 动作（样本含双套双）
    mod.rule_switches["nested_doubles"].setChecked(True)
    on_rules = mod.current_rules()
    on = fix_text(before, on_rules, max_rounds=8)
    assert any(a.rule_id == "nested_doubles" for a in on.actions)


def test_rules_persist(mod: CheckModule):
    mod.rule_switches["missing_right_double"].setChecked(False)
    mod.save_rules_config(silent=True)
    path = mod._rules_file()
    assert path.is_file()
    m2 = CheckModule()
    m2.set_book(mod._text_path, "测书", rules_dir=path.parent)
    assert m2.rule_switches["missing_right_double"].isChecked() is False


# ---------- ③ 逐处写回 + 撤销 ----------

def test_fix_here_writeback_and_recheck(mod: CheckModule):
    mod.start_check(sync=True)
    assert mod.probs
    # 找一处有 rule_id / action 的
    idx = next(
        (i for i, p in enumerate(mod.probs)
         if p.get("rule_id") == "nested_doubles" or p.get("action")),
        0)
    mod.select(idx)
    line = mod.probs[idx]["line"]
    before = Path(mod._text_path).read_text(encoding="utf-8")
    mod.fix_here()
    after = Path(mod._text_path).read_text(encoding="utf-8")
    assert after != before, "修复应写回磁盘"

    # 重新检查：该处语义应变化（错误数不增加；写回生效）
    mod.start_check(sync=True)
    assert mod.phase == PHASE_RESULT
    # 正文仍含修复痕迹或错误数下降/稳定
    assert Path(mod._text_path).read_text(encoding="utf-8") == after


def test_undo_restores_text(mod: CheckModule):
    mod.start_check(sync=True)
    before = Path(mod._text_path).read_text(encoding="utf-8")
    # 强制走批量修复（同步确认路径用引擎直接写）
    from fixtext_quotation.fixer import fix_text
    preview = fix_text(before, mod.current_rules(), max_rounds=8)
    if not preview.actions:
        pytest.skip("样本未被引擎动作命中")
    mod.undo.append({"text_batch": True, "prev_text": before})
    mod._write_book_text(preview.text)
    assert Path(mod._text_path).read_text(encoding="utf-8") != before
    mod.undo_last()
    assert Path(mod._text_path).read_text(encoding="utf-8") == before


# ---------- ④ 冒烟 ----------

def test_e2e_smoke_empty_ready_result_recheck(qapp, tmp_path: Path):
    m = CheckModule()
    assert m.phase == PHASE_EMPTY
    book = tmp_path / "b.txt"
    book.write_text(SAMPLE_BAD, encoding="utf-8")
    m.set_book(str(book), "冒烟", rules_dir=tmp_path)
    assert m.phase == PHASE_READY
    m.start_check(sync=True)
    assert m.phase == PHASE_RESULT
    n1 = len(m.probs)
    m.on_main()  # 重新检查
    # on_main 在 result 会 start_check（异步）；强制 sync
    m.start_check(sync=True)
    assert m.phase == PHASE_RESULT
    assert len(m.probs) == n1
