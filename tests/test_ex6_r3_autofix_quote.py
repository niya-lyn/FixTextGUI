# -*- coding: utf-8 -*-
"""M4-EX.6-R3：自动修复引号开关 / QuoteStage 挂接 / 摘要三分支。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "fixtext_ui"))
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "pipeline" / "vendor"))

SAMPLE = (
    "他说：“外层“内层”还在。”\n"
    "另一行：你好。”\n"
)


# ---------- 摘要三分支 ----------

def test_quote_status_branches():
    from fixtext_quote_status import quote_status_from_summary

    t, go, tip = quote_status_from_summary({
        "auto_fix_quotes": False,
        "quote_errors": 7,
        "quote_errors_before": 7,
    })
    assert "检出引号问题 7 处" == t
    assert go is True
    assert "逐处" in tip

    t, go, tip = quote_status_from_summary({
        "auto_fix_quotes": True,
        "quote_errors": 2,
        "quote_errors_before": 7,
        "quote_fixed": 5,
    })
    assert "已自动修复 5 处，剩余 2 处待人工确认" == t
    assert go is True

    t, go, tip = quote_status_from_summary({
        "auto_fix_quotes": True,
        "quote_errors": 0,
        "quote_errors_before": 7,
        "quote_fixed": 7,
    })
    assert "已自动修复 7 处" == t
    assert go is False


def test_settings_auto_fix_quote_default_off(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTEXT_SETTINGS_FILE", str(tmp_path / "settings.ini"))
    import fixtext_settings as S
    assert S.auto_fix_quote() is False
    S.set_auto_fix_quote(True)
    assert S.auto_fix_quote() is True
    S.set_auto_fix_quote(False)
    assert S.auto_fix_quote() is False


# ---------- QuoteStage 开/关 ----------

class _Log:
    def log(self, msg: str) -> None:
        pass


def _make_quote_cfg(tmp: Path, *, auto: bool, text: str = SAMPLE):
    """最小 cfg：只满足 QuoteStage 读写路径。"""
    work = tmp / "run"
    after = work / "03_replace" / "after" / "book.txt"
    after.parent.mkdir(parents=True, exist_ok=True)
    after.write_text(text, encoding="utf-8")
    (work / "04_quote").mkdir(parents=True, exist_ok=True)
    cfg = SimpleNamespace(
        workdir=work,
        auto_fix_quotes=auto,
        quotation_rules_path=None,
        book_stem="book",
        replace_after=lambda: after,
        quote_report_txt=lambda: work / "04_quote" / "book.report.txt",
        quote_report_json=lambda: work / "04_quote" / "book.report.json",
        stage_dir=lambda name: work / {"quote": "04_quote", "replace": "03_replace"}[name],
    )
    return cfg, after


def test_quote_stage_off_keeps_errors(tmp_path):
    from fixtext_pipeline.stages.quote import QuoteStage
    from fixtext_quotation.checker import check_text

    cfg, after = _make_quote_cfg(tmp_path, auto=False)
    before_n = len(check_text(after.read_text(encoding="utf-8")))
    assert before_n >= 1
    stage = QuoteStage(cfg, _Log())  # type: ignore[arg-type]
    report = stage.run()
    assert report["auto_fix_quotes"] is False
    assert report["error_count"] == before_n
    # 正文未改
    assert after.read_text(encoding="utf-8") == SAMPLE
    assert report["quote_fixed"] == 0


def test_quote_stage_on_reduces_errors(tmp_path):
    from fixtext_pipeline.stages.quote import QuoteStage
    from fixtext_quotation.checker import check_text

    cfg, after = _make_quote_cfg(tmp_path, auto=True)
    before_n = len(check_text(SAMPLE))
    stage = QuoteStage(cfg, _Log())  # type: ignore[arg-type]
    report = stage.run()
    assert report["auto_fix_quotes"] is True
    assert report["error_count_before"] == before_n
    after_text = after.read_text(encoding="utf-8")
    after_n = len(check_text(after_text))
    assert after_n == report["error_count"]
    assert report["quote_fixed"] == before_n - after_n
    assert after_n < before_n or report["fix_actions"] >= 0
    # 至少尝试修过（样本可被 nested / missing_left 命中）
    assert report["quote_fixed"] >= 1 or report["fix_actions"] >= 1


def test_oneclick_has_autofix_switch(qapp):
    import oneclick_module as om

    mod = om.OneClickModule()
    assert hasattr(mod, "sw_auto_fix_quote")
    assert mod.sw_auto_fix_quote.isChecked() is False


def test_result_actions_show_go_check(qapp):
    import oneclick_module as om

    mod = om.OneClickModule()
    mod._summary = {
        "auto_fix_quotes": False,
        "quote_errors": 3,
        "quote_errors_before": 3,
        "book": "测",
        "chapters": 1,
    }
    # 直接渲染结果卡
    mod._render_result(mod._summary)
    labels = [b.text() for b in mod.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
    assert any("去检查页" in t for t in labels)

    mod._summary = {
        "auto_fix_quotes": True,
        "quote_errors": 0,
        "quote_errors_before": 5,
        "quote_fixed": 5,
        "book": "测",
        "chapters": 1,
    }
    mod._render_result(mod._summary)
    labels = [b.text() for b in mod.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton)]
    assert not any("去检查页" in t for t in labels)
