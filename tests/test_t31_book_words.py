"""M3-T3.1 本书专有词条 · 真实链路（不退回演示数据）。

验收口径里「演示数据全部清除」不只看词库页自身：一键校正页的
「本书专有词条」入口过去弹的是硬编码的三条词（星陨大陆 / 墨羽 /
九转玄功），点了还会提示「已加入 N 条」但**一条都没写进文件**。
本文件锁住三件事：

1. bookmap 阶段真的把抽出的词条带进报告（``entry_preview``）；
2. worker 把报告整理成界面可用的三元组，没有就返回空列表；
3. 一键校正页只发真实词条；词库页在空列表时**不显示横幅**，绝不编词。
"""

from __future__ import annotations

import sys
from pathlib import Path

IK = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(IK / "fixtext_ui"), str(IK), str(IK / "pipeline")]

import pytest  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 阶段：报告里的真实词条预览
# ---------------------------------------------------------------------------

def test_bookmap_report_carries_entry_preview():
    """bookmap 阶段必须把抽出的词条带进报告，界面才有真数据可展示。"""
    from fixtext_pipeline.stages.bookmap import ENTRY_PREVIEW_MAX, BookMapStage

    assert ENTRY_PREVIEW_MAX >= 1
    src = (IK / "pipeline" / "fixtext_pipeline" / "stages" / "bookmap.py").read_text(
        encoding="utf-8")
    assert '"entry_preview"' in src, "报告必须带 entry_preview 字段"
    assert "ENTRY_PREVIEW_MAX" in src, "预览必须按上限截断，不能把几千条塞进报告"
    assert hasattr(BookMapStage, "run")


# ---------------------------------------------------------------------------
# 2. worker：报告 → 界面三元组
# ---------------------------------------------------------------------------

class _FakeWorker:
    """只借 worker 的整理方法，不启动任何真实校正。"""

    def __init__(self, title: str = "炮火弧线"):
        self.title = title
        self.epub = Path("paohuo.epub")


def test_worker_maps_real_entries():
    from fixtext_worker import CorrectionJob

    w = _FakeWorker("炮火弧线")
    w.title, w.epub = "炮火弧线", Path("paohuo.epub")
    bookmap = {
        "entry_preview": {
            "paohuo": [
                {"before": "帝国双璧掏心置腹", "after": "帝国双璧推心置腹"},
                {"before": "血染亚得里亚海", "after": "血染亚的里亚海"},
            ]
        }
    }
    rows = CorrectionJob._book_words_preview(w, bookmap)
    assert len(rows) == 2
    assert rows[0]["word"] == "帝国双璧掏心置腹"
    assert rows[0]["value"] == "帝国双璧推心置腹"
    assert "炮火弧线" in rows[0]["note"]


def test_worker_dedups_same_change_across_contexts():
    """同一处改动在相邻上下文里各抽一次 → 必须去重，别让横幅条数与实写条数不符。"""
    from fixtext_worker import CorrectionJob

    w = _FakeWorker("炮火弧线")
    dup = {"before": "帝国双璧掏心置腹（补", "after": "帝国双璧推心置腹（补"}
    other = {"before": "血染亚得里亚海", "after": "血染亚的里亚海"}
    rows = CorrectionJob._book_words_preview(
        w, {"entry_preview": {"k": [dup, dict(dup), other]}})
    assert len(rows) == 2, f"重复条目未去重：{[r['word'] for r in rows]}"


def test_worker_returns_empty_without_entries():
    """没有真实词条时必须返回空列表 —— 界面据空列表就不显示横幅。"""
    from fixtext_worker import CorrectionJob

    w = _FakeWorker("某本书")
    assert CorrectionJob._book_words_preview(w, {}) == []
    assert CorrectionJob._book_words_preview(w, {"entry_preview": {"k": []}}) == []
    # 只有空字符串的条目也要被过滤掉，不能变成「空气词条」
    assert CorrectionJob._book_words_preview(
        w, {"entry_preview": {"k": [{"before": "   ", "after": "x"}]}}
    ) == []


def test_summary_exposes_book_words_key():
    src = (IK / "fixtext_ui" / "fixtext_worker.py").read_text(encoding="utf-8")
    assert '"book_words"' in src, "运行摘要必须带 book_words，供一键校正页取用"


# ---------------------------------------------------------------------------
# 3. 演示词清零 + 空列表不显示横幅
# ---------------------------------------------------------------------------

def test_no_demo_book_words_in_oneclick():
    """一键校正页不得再持有任何硬编码专有词。"""
    src = (IK / "fixtext_ui" / "oneclick_module.py").read_text(encoding="utf-8")
    for ghost in ("星陨大陆", "九转玄功", "BOOK_WORDS"):
        assert ghost not in src, f"演示专有词残留：{ghost}"


def test_oneclick_emits_real_words(monkeypatch):
    """有真实词条时发信号，没有时只提示、不发信号。"""
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from oneclick_module import OneClickModule

    mod = OneClickModule()
    got = []
    mod.bookWordsReady.connect(lambda words, title: got.append((words, title)))

    mod._summary = {"book_words": [dict(word="甲", value="乙", note="n")], "title": "炮火弧线"}
    mod._open_book_words()
    assert len(got) == 1 and got[0][0][0]["word"] == "甲" and got[0][1] == "炮火弧线"

    mod._summary = {"book_words": []}
    mod._open_book_words()
    assert len(got) == 1, "没有真实词条时不得发信号（否则界面会拿空列表造横幅）"
    app.processEvents()


def test_banner_hidden_when_no_real_words(tmp_path):
    """词库页：空列表 → 横幅不可见；有真实词条 → 显示真实条数。"""
    pytest.importorskip("PySide6")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from fixtext_vocab import VocabStore
    from vocab_module import VocabModule

    # 构造只用真实交付包（内置 304,255 条），但把自定义词库指向临时文件，
    # 免得测试往交付包里写东西。
    mod = VocabModule()
    mod.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    mod.set_book_words([])
    assert mod._banner_w.isVisible() is False

    mod.set_book_words([dict(word="甲", value="乙", note="n")], "炮火弧线")
    assert mod._banner_title.text() != ""
    assert "1" in mod._banner_title.text()
    assert "炮火弧线" in mod._banner_title.text()
    mod.close()
    app.processEvents()
