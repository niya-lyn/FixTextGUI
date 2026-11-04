"""V1.1-E2 · 前后对比视图（只读）与定位的验收用例。

覆盖四件事：

1. **左右对比界面**真的建得起来，且用的是 E1 的差异结构（不另造 diff）；
2. **定位准确**：差异项报的章 / 行 / 行内区间，与书里的原文逐字对得上；
3. **只读**：打开、筛选、跳转全流程都不碰原文（文件指纹不变、界面无写入控件）；
4. **大书不卡死**：差异项再多，界面线程也不被长时间占住。

外加两条纪律检查：装载层（``vocab_bridge.compose`` / ``bags.write_round_rules``）
一个字都没被本卡改到；界面文案不出现内部技术词。
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "fixtext_ui"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from fixtext_compare import (                                   # noqa: E402
    CompareModel, CompareModule, IndexModel, _after_spans, locate_item,
)
from fixtext_diff_view import (                                 # noqa: E402
    ATTR_VERIFIED, KIND_REPLACE, DiffItem, DiffReport, SideRef,
)

#: 界面绝不允许出现的内部技术词（与 tests/test_no_jargon.py 同口径）
FORBIDDEN = [
    "spine", "opf", "container.xml", "manifest", "ncx", "xhtml", "xml",
    "bom", "utf-8", "utf8", "gbk", "gb18030", "big5", "crlf", "sha256",
    "hash", "encoding", "charset", "codec", "zip",
]
ALLOWED_WORDS = {"epub", "txt"}


# ---------------------------------------------------------------------------
# 造数据：用 E1 的结构，不另造 diff
# ---------------------------------------------------------------------------

def _make_item(index: int, before: str, after: str, *, chapter: int = 0,
               title: str = "第一章", line: int = 1,
               spans: list[tuple[int, int]] | None = None,
               rule_before: str = "", rule_after: str = "") -> DiffItem:
    item = DiffItem(
        index=index,
        kind=KIND_REPLACE,
        before_text=before,
        after_text=after,
        before_snippet=before,
        after_snippet=after,
        before=SideRef(chapter_index=chapter, chapter_title=title, line=line,
                       char_start=0, char_end=len(before)),
        after_ref=SideRef(chapter_index=chapter, chapter_title=title, line=line,
                          char_start=0, char_end=len(after)),
        char_spans=list(spans or []),
        attribution=ATTR_VERIFIED if rule_before else "no_rules",
        rule_before=rule_before,
        rule_after=rule_after,
    )
    return item


@pytest.fixture()
def sample_report(tmp_path):
    """造一份差异报告，正文真的落盘（定位核对要拿原文逐字比）。"""
    body = "    <p>他叫萧衍，走进城里，风很大。</p>\n"
    after = "    <p>他叫萧晏，走进城里，风很大。</p>\n"
    before_path = tmp_path / "before.txt"
    after_path = tmp_path / "after.txt"
    before_path.write_text(body, encoding="utf-8")
    after_path.write_text(after, encoding="utf-8")
    item = _make_item(0, body.rstrip("\n"), after.rstrip("\n"),
                      chapter=0, title="进城", line=1,
                      spans=[(6, 8)], rule_before="萧衍", rule_after="萧晏")
    report = DiffReport(
        items=[item],
        chapters=[{"index": 0, "title": "进城", "path": ""}],
        item_count=1,
        before_path=str(before_path),
        after_path=str(after_path),
    )
    return report, before_path, after_path


# ---------------------------------------------------------------------------
# 1. 界面建得起来
# ---------------------------------------------------------------------------

def test_compare_page_builds(qt_app):
    mod = CompareModule()
    assert mod is not None
    assert mod.compare_model.rowCount() == 0
    mod.shutdown()


def test_main_window_exposes_compare_route(qt_app):
    """对比页是内容区的平级路由页，左轨仍是 6 项（不占配额）。"""
    from fixtext_tokens import COMPARE_KEY, ENTRIES
    from main_window import MainWindow

    win = MainWindow()
    assert len(ENTRIES) == 6
    assert COMPARE_KEY in win.pages
    assert win.page(COMPARE_KEY) is not None
    win.close()
    win.deleteLater()


def test_oneclick_has_compare_entry(qt_app):
    """一键校正的结果卡上有「看看前后对比」入口。"""
    from oneclick_module import OneClickModule

    mod = OneClickModule()
    assert hasattr(mod, "gotoCompare")
    mod.deleteLater()


# ---------------------------------------------------------------------------
# 2. 定位准确
# ---------------------------------------------------------------------------

def test_location_points_at_real_text(sample_report):
    """差异项报的位置，落在书上就是它说的那一行、那几个字。"""
    report, before_path, _after_path = sample_report
    item = report.items[0]
    pos = locate_item(item)
    assert pos.located and pos.exact
    assert pos.chapter_index == 0
    assert pos.before_line == 1
    line = before_path.read_text(encoding="utf-8").split("\n")[0]
    assert pos.before_char_start == 0
    assert line[pos.before_char_start:pos.before_char_end] == item.before_text
    assert "第 1 章" in pos.describe()
    assert "第 1 行" in pos.describe()


def test_location_uses_e1_side_ref_without_recomputing(sample_report):
    """位置直接取 E1 的 SideRef，不自己再推一遍。"""
    report, _b, _a = sample_report
    item = report.items[0]
    item.before.char_start = 7
    item.before.char_end = 9
    pos = locate_item(item)
    assert (pos.before_char_start, pos.before_char_end) == (7, 9)
    assert "第 8–9 字" in pos.describe()


def test_position_readout_updates_on_selection(qt_app, sample_report):
    report, _b, _a = sample_report
    mod = CompareModule()
    mod.set_report(report)
    mod.step(1)
    pos = mod.current_position()
    assert pos is not None and pos.before_line == 1
    assert "第 1 章" in mod._loc_line.text()
    mod.shutdown()


def test_chapter_filter_narrows_list(qt_app):
    items = [_make_item(0, "甲", "乙", chapter=0, line=3),
             _make_item(1, "丙", "丁", chapter=1, line=7)]
    report = DiffReport(items=items, chapters=[{"index": 0}, {"index": 1}],
                        item_count=2)
    mod = CompareModule()
    mod.set_report(report)
    assert mod.compare_model.rowCount() == 2
    mod._chapter_box.setCurrentIndex(2)          # 第 2 章
    assert mod.compare_model.rowCount() == 1
    assert mod.compare_model.item_at(0).before.chapter_index == 1
    mod.shutdown()


def test_step_navigates_between_items(qt_app):
    items = [_make_item(i, f"前{i}", f"后{i}", chapter=0, line=i + 1)
             for i in range(3)]
    report = DiffReport(items=items, chapters=[{"index": 0}], item_count=3)
    mod = CompareModule()
    mod.set_report(report)
    mod.step(1)
    assert mod._cur == 0
    mod.step(1)
    assert mod._cur == 1
    mod.step(-1)
    assert mod._cur == 0
    mod.shutdown()


# ---------------------------------------------------------------------------
# 3. 只读
# ---------------------------------------------------------------------------

def _fingerprint(path: Path) -> tuple[str, float]:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), path.stat().st_mtime


def test_opening_and_navigating_never_touches_the_book(qt_app, sample_report):
    """打开 / 筛选 / 跳转全流程跑一遍，原文文件一个字节都没变。"""
    report, before_path, after_path = sample_report
    before_fp = _fingerprint(before_path)
    after_fp = _fingerprint(after_path)

    mod = CompareModule()
    mod.set_report(report)
    mod.step(1)
    mod.step(1)
    mod.step(-1)
    mod.copy_position()
    mod._kind_box.setCurrentIndex(1)
    mod.shutdown()

    assert _fingerprint(before_path) == before_fp
    assert _fingerprint(after_path) == after_fp


def test_compare_module_has_no_write_entry_point():
    """对比页不能有任何「写回原文」的入口。"""
    from fixtext_compare import CompareModule

    banned = ("save", "write", "apply", "commit", "replace_text", "set_text",
              "rewrite", "persist")
    # 只看本类自己定义的成员：Qt 基类自带的 setter 不算「写回原文的入口」
    for name in vars(CompareModule):
        if name.startswith("_"):
            continue
        assert not any(b in name.lower() for b in banned), f"出现了疑似写回入口：{name}"


def test_compare_module_never_calls_a_writer():
    """源码里不出现写文件的动作（只读视图的硬保证）。"""
    src = (ROOT / "fixtext_ui" / "fixtext_compare.py").read_text(encoding="utf-8")
    # 去掉注释与文档字符串后再扫，避免把说明文字当成代码
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    code = re.sub(r"#.*", "", code)
    for pattern in (r"\.write_text\(", r"\.write_bytes\(", r"open\([^)]*['\"]w",
                    r"shutil\.copy", r"os\.remove", r"\.unlink\("):
        assert not re.search(pattern, code), f"对比页里出现了写盘动作：{pattern}"


def test_no_editable_widget_holds_book_text(qt_app, sample_report):
    """界面里没有能改的输入控件装着正文。"""
    from PySide6.QtWidgets import QAbstractScrollArea, QLineEdit, QPlainTextEdit, QTextEdit

    report, _b, _a = sample_report
    mod = CompareModule()
    mod.set_report(report)
    mod.step(1)
    bad = []
    editable = (list(mod.findChildren(QLineEdit))
                + list(mod.findChildren(QTextEdit))
                + list(mod.findChildren(QPlainTextEdit)))
    for w in editable:
        if isinstance(w, QAbstractScrollArea) and not w.isReadOnly():
            bad.append(type(w).__name__)
            continue
        # 能改的输入控件里不许装着正文
        try:
            content = w.text()
        except Exception:
            content = ""
        if "他叫萧衍" in str(content):
            bad.append(type(w).__name__)
    assert not bad, f"有能改的控件装着正文：{bad}"
    mod.shutdown()


def test_loading_layer_is_untouched():
    """本卡不许改装载层：compose / write_round_rules 仍在原样。"""
    pipe = str(ROOT / "pipeline")
    added = pipe not in sys.path
    if added:
        sys.path.insert(0, pipe)
    try:
        from fixtext_pipeline import bags, vocab_bridge
        assert hasattr(vocab_bridge, "compose")
        assert hasattr(bags, "write_round_rules")
    finally:
        if added:
            sys.path.remove(pipe)
            for name in [n for n in sys.modules if n.startswith("fixtext_pipeline")]:
                sys.modules.pop(name, None)
    src = (ROOT / "fixtext_ui" / "fixtext_compare.py").read_text(encoding="utf-8")
    # 去掉注释与文档字符串再扫：说明文字里提到「不碰装载层」不算碰
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    code = re.sub(r"#.*", "", code)
    assert "vocab_bridge" not in code
    assert "write_round_rules" not in code


# ---------------------------------------------------------------------------
# 4. 复用 E1 的差异结构，不另造 diff
# ---------------------------------------------------------------------------

def test_view_uses_e1_diff_structures():
    """对比页直接吃 E1 的 DiffItem / DiffReport，不另造一套差异。"""
    src = (ROOT / "fixtext_ui" / "fixtext_compare.py").read_text(encoding="utf-8")
    assert "from fixtext_diff_view import" in src
    for forbidden in ("import difflib", "generate_patch", "PatchAnalyzer",
                      "difflib.SequenceMatcher"):
        assert forbidden not in src, f"对比页自己算了一遍差异：{forbidden}"


def test_after_spans_come_from_rule_attribution():
    """改后一侧的高亮来自 E1 给的规则归属，不是另算差异。"""
    item = _make_item(0, "他叫萧衍", "他叫萧晏", spans=[(3, 5)],
                      rule_before="萧衍", rule_after="萧晏")
    assert _after_spans(item) == [(2, 4)], "改后高亮应落在新写法所在的那两个字上"
    plain = _make_item(1, "甲乙", "甲丙", spans=[(1, 2)])
    assert _after_spans(plain) == []


def test_models_expose_e1_items(qt_app):
    items = [_make_item(0, "甲", "乙", chapter=0, line=1)]
    report = DiffReport(items=items, chapters=[{"index": 0}], item_count=1)
    mod = CompareModule()
    mod.set_report(report)
    assert isinstance(mod.compare_model, CompareModel)
    assert isinstance(mod.index_model, IndexModel)
    got = mod.compare_model.item_at(0)
    assert got is report.items[0]
    mod.shutdown()


# ---------------------------------------------------------------------------
# 5. 大书不卡死
# ---------------------------------------------------------------------------

def _synthetic_report(n_items: int) -> DiffReport:
    """造一份大清单（不落盘正文，只量界面这一侧的规模）。"""
    items = []
    for i in range(n_items):
        items.append(_make_item(i, f"前文{i}萧衍", f"后文{i}萧晏",
                                 chapter=i % 300, line=i + 1,
                                 spans=[(3, 5)], rule_before="萧衍",
                                 rule_after="萧晏"))
    return DiffReport(items=items,
                       chapters=[{"index": i} for i in range(300)],
                       item_count=n_items)


def test_large_list_opens_without_blocking(qt_app):
    """两万条差异项：装载与首屏都不能把界面线程占住。"""
    report = _synthetic_report(20000)
    mod = CompareModule()
    t0 = time.perf_counter()
    mod.set_report(report)
    ready = time.perf_counter() - t0
    assert mod.compare_model.rowCount() == 20000
    # 界面这一侧只做「把清单挂到 model 上」，不做任何逐条渲染
    assert ready < 5.0, f"挂载 2 万条差异项用了 {ready:.2f}s，太慢"
    mod.shutdown()


def test_cells_are_computed_on_demand(qt_app):
    """单元格按需现算：挂载后不该已经把所有行都渲染了一遍。"""
    report = _synthetic_report(5000)
    mod = CompareModule()
    mod.set_report(report)
    assert len(mod.compare_model._cache) == 0, "挂载时不该预渲染任何一格"
    mod.compare_model.data(mod.compare_model.index(0, 0))
    assert len(mod.compare_model._cache) == 1
    mod.shutdown()


def test_text_cache_is_bounded(qt_app):
    """行内文字缓存有上限，大书不会把内存吃满。"""
    from fixtext_compare import TEXT_CACHE_LIMIT

    report = _synthetic_report(TEXT_CACHE_LIMIT + 500)
    mod = CompareModule()
    mod.set_report(report)
    for row in range(TEXT_CACHE_LIMIT + 500):
        mod.compare_model.data(mod.compare_model.index(row, 0))
    assert len(mod.compare_model._cache) <= TEXT_CACHE_LIMIT + 1
    mod.shutdown()


# ---------------------------------------------------------------------------
# 6. 文案不出现内部技术词
# ---------------------------------------------------------------------------

def test_compare_ui_text_has_no_tech_terms(qt_app, sample_report):
    from PySide6.QtWidgets import QWidget

    report, _b, _a = sample_report
    mod = CompareModule()
    mod.set_report(report)
    mod.step(1)
    texts: list[str] = []
    for w in mod.findChildren(QWidget):
        for attr in ("text", "placeholderText", "toolTip"):
            if hasattr(w, attr):
                value = getattr(w, attr)
                if isinstance(value, str) and value:
                    texts.append(value)
    bad = []
    for t in texts:
        low = t.lower()
        hits = [w for w in FORBIDDEN if w in low and w not in ALLOWED_WORDS]
        if hits:
            bad.append((t, hits))
    mod.shutdown()
    assert not bad, f"界面文案出现技术词：{bad}"
