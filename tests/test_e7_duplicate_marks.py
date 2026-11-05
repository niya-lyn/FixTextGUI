"""V1.1-E7 · 重复段落清单与处置的验收用例。

本卡四类硬指标各有一组机器可判定的用例：

1. **清单数据装配（消费 ``DuplicateReport.payload()``）**
   → ``test_build_list_consumes_payload`` / ``test_four_location_views`` /
     ``test_order_and_filters`` / ``test_handler_state_in_list``
2. **处置状态机**
   → ``test_state_machine_idempotent`` / ``test_state_rejects_unknown`` /
     ``test_scope_isolation_by_threshold``
3. **处置不修改原文 + 撤销逐字节**
   → ``test_marks_never_touch_book`` / ``test_undo_restores_bytes`` /
     ``test_clear_scope_undoable``
4. **跳转定位信号**
   → ``test_jump_payload_carries_four_views`` /
     ``test_check_page_entry_opens_duplicate_page``

界面侧一律离屏构建真实控件、真实点击（不调内部函数冒充用户路径）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "fixtext_ui"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_duplicates import DetectOptions, detect_text        # noqa: E402
from fixtext_duplicates.model import (KIND_EXACT, KIND_SIMILAR,   # noqa: E402
                                       ORDER_BY_COUNT, ORDER_BY_POSITION)
from fixtext_ui import fixtext_duplicate_list as dl               # noqa: E402
from fixtext_ui import fixtext_duplicate_marks as dm              # noqa: E402

SAMPLES = Path(__file__).resolve().parent / "samples"
SAMPLE_A = SAMPLES / "a_utf8_lf.txt"

THRESHOLD = 0.75
MIN_CHARS = 10


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw(path: Path | None) -> bytes:
    """处置记录当前字节；文件不存在等同于空（撤销回到「还没记过」就是这个态）。"""
    if path is None or not Path(path).exists():
        return b""
    return Path(path).read_bytes()


def _book(tmp_path: Path, *, name: str = "样本A") -> Path:
    """在工作区里放一本真实样本（书 id = 目录名，与书架同一口径）。"""
    book = tmp_path / "books" / name / "book.txt"
    book.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SAMPLE_A, book)
    return book


@pytest.fixture(scope="module")
def payload() -> dict:
    """真实检测一次（E6 的 ``detect_text`` → ``payload()``），整轮复用。"""
    report = detect_text(SAMPLE_A.read_text(encoding="utf-8"),
                         DetectOptions(threshold=THRESHOLD, min_chars=MIN_CHARS))
    return report.payload()


# ---------------------------------------------------------------------------
# 1. 清单数据装配
# ---------------------------------------------------------------------------

def test_build_list_consumes_payload(payload: dict):
    """清单只读 ``payload()``：组数、组号、成员位置一处不少，不重算。"""
    view = dl.build_list(payload)
    assert len(view.items) == len(payload["groups"])
    assert view.threshold == pytest.approx(payload["threshold"])
    assert view.min_chars == payload["min_chars"]
    ids = [it.group_id for it in view.items]
    assert ids == [g["group_id"] for g in payload["groups"]], "组号与报告逐字一致"
    for it in view.items:
        assert it.slots, f"{it.group_id} 少了成员位置"
        assert it.occurrences == len(it.slots)


def test_four_location_views(payload: dict):
    """四套口径齐全且自洽：段序号 / 章节 / 行区间 / 字符偏移。"""
    view = dl.build_list(payload)
    slot = view.items[0].slots[0]
    texts = slot.texts()
    assert set(texts) == {"index", "chapter", "line", "char"}
    assert f"序号 {slot.index}" in texts["index"]
    assert slot.line_start >= 1 and slot.line_end >= slot.line_start
    assert slot.char_end > slot.char_start
    target = slot.target()
    assert target["paragraph_index"] == slot.index
    assert target["line_start"] == slot.line_start
    assert target["char_start"] == slot.char_start
    # 章节口径来自报告；样本无章节信息时如实说「未分章」
    if slot.chapter_no > 0:
        assert slot.chapter_title in texts["chapter"]
    else:
        assert texts["chapter"] == "未分章"


def test_order_and_filters(payload: dict):
    """三种排序可在清单上重排；类型筛选与「只看未处置」各只留该留的。"""
    by_count = dl.build_list(payload, order=ORDER_BY_COUNT)
    by_pos = dl.build_list(payload, order=ORDER_BY_POSITION)
    assert [it.first_position for it in by_pos.items] == sorted(
        it.first_position for it in by_pos.items), "按位置排序必须单调递增"
    assert by_count.items[0].occurrences >= by_count.items[-1].occurrences

    exact = dl.build_list(payload, kind=dl.FILTER_EXACT)
    assert all(it.kind == KIND_EXACT for it in exact.items)
    similar = dl.build_list(payload, kind=dl.FILTER_SIMILAR)
    assert all(it.kind == KIND_SIMILAR for it in similar.items)
    assert len(exact.items) + len(similar.items) == len(by_count.items)

    first = by_count.items[0].group_id
    open_only = dl.build_list(payload, show="open", marks={first: dm.ST_MARKED})
    assert first not in [it.group_id for it in open_only.items]


def test_handler_state_in_list(payload: dict):
    """处置状态进清单：已处置数、状态文本、「正文已改动」提示都在这层。"""
    gid = payload["groups"][0]["group_id"]
    view = dl.build_list(payload, marks={gid: dm.ST_MARKED})
    assert view.state_of(gid) == dm.ST_MARKED
    assert view.handled_count() == 1
    assert view.counts()["groups"] == len(payload["groups"])


# ---------------------------------------------------------------------------
# 2. 处置状态机
# ---------------------------------------------------------------------------

def test_state_machine_idempotent(tmp_path: Path, payload: dict):
    """同一状态重复设置不写盘、不留还原点；切到另一态才落一笔。"""
    book = _book(tmp_path)
    mk = dm.DuplicateMarks(workspace=tmp_path / "ws")
    assert mk.bind(book) == "样本A"
    gid = dl.build_list(payload).items[0].group_id

    r1 = mk.set_state(gid, dm.ST_MARKED, threshold=THRESHOLD, min_chars=MIN_CHARS)
    assert r1["changed"] and r1["point_id"] > 0
    r2 = mk.set_state(gid, dm.ST_MARKED, threshold=THRESHOLD, min_chars=MIN_CHARS)
    assert r2["changed"] is False, "同一状态重复设置必须幂等"
    r3 = mk.set_state(gid, dm.ST_IGNORED, threshold=THRESHOLD, min_chars=MIN_CHARS)
    assert r3["changed"] and r3["from_state"] == dm.ST_MARKED
    assert mk.states(THRESHOLD, MIN_CHARS) == {gid: dm.ST_IGNORED}
    r4 = mk.set_state(gid, dm.ST_NONE, threshold=THRESHOLD, min_chars=MIN_CHARS)
    assert r4["changed"] and mk.states(THRESHOLD, MIN_CHARS) == {}


def test_state_rejects_unknown(tmp_path: Path):
    """状态机只认「标记 / 忽略 / 清回」三值——自动删除这类动作根本不存在。"""
    book = _book(tmp_path)
    mk = dm.DuplicateMarks(workspace=tmp_path / "ws")
    mk.bind(book)
    for bad in ("deleted", "remove", "delete", "auto"):
        with pytest.raises(ValueError):
            mk.set_state("E-1", bad, threshold=THRESHOLD, min_chars=MIN_CHARS)
    assert dm.STATES == ("", dm.ST_MARKED, dm.ST_IGNORED)


def test_scope_isolation_by_threshold(tmp_path: Path):
    """换阈值就是换作用域：组号会重新分配，处置不能串味到另一轮检测。"""
    book = _book(tmp_path)
    mk = dm.DuplicateMarks(workspace=tmp_path / "ws")
    mk.bind(book)
    mk.set_state("S-1", dm.ST_MARKED, threshold=THRESHOLD, min_chars=MIN_CHARS)
    assert mk.states(THRESHOLD, MIN_CHARS) == {"S-1": dm.ST_MARKED}
    assert mk.states(0.60, MIN_CHARS) == {}, "另一档阈值不该看到这条处置"
    assert dm.scope_key(THRESHOLD, MIN_CHARS) == "t0.75-m10"


def test_marks_are_per_book(tmp_path: Path):
    """处置随书存：A 书的标记不出现在 B 书，文件落在各自书目录。"""
    a = _book(tmp_path, name="样本A")
    b = _book(tmp_path, name="样本B")
    wa = dm.DuplicateMarks(workspace=tmp_path / "ws")
    wa.bind(a)
    wa.set_state("S-1", dm.ST_MARKED, threshold=THRESHOLD, min_chars=MIN_CHARS)
    assert wa.states(THRESHOLD, MIN_CHARS) == {"S-1": dm.ST_MARKED}
    path_a = wa.path()
    wb = dm.DuplicateMarks(workspace=tmp_path / "ws")
    wb.bind(b)
    assert wb.states(THRESHOLD, MIN_CHARS) == {}, "B 书不该看到 A 书的处置"
    assert wb.path() != path_a


# ---------------------------------------------------------------------------
# 3. 不修改原文 + 撤销逐字节
# ---------------------------------------------------------------------------

def test_marks_never_touch_book(tmp_path: Path, payload: dict):
    """标记 / 忽略全过程书稿逐字节不变（处置只写自己的记录文件）。"""
    book = _book(tmp_path)
    before = _sha(book)
    mk = dm.DuplicateMarks(workspace=tmp_path / "ws")
    mk.bind(book)
    items = dl.build_list(payload).items
    for state in (dm.ST_MARKED, dm.ST_IGNORED):
        mk.set_state(items[0].group_id, state, threshold=THRESHOLD, min_chars=MIN_CHARS)
        assert _sha(book) == before, f"处置到「{state}」时书稿被动过"
        assert _raw(mk.path()), "处置记录本身要落盘"
    mk.set_state(items[0].group_id, dm.ST_NONE, threshold=THRESHOLD, min_chars=MIN_CHARS)
    assert _sha(book) == before, "清回未处置也不该动书稿"


def test_undo_restores_bytes(tmp_path: Path, payload: dict):
    """撤销后处置记录逐字节回到处置前（``identical`` 按字节核，非按内容比）。"""
    book = _book(tmp_path)
    before = _sha(book)
    mk = dm.DuplicateMarks(workspace=tmp_path / "ws")
    mk.bind(book)
    gid = dl.build_list(payload).items[0].group_id
    raw_before = _raw(mk.path())

    r = mk.set_state(gid, dm.ST_MARKED, threshold=THRESHOLD, min_chars=MIN_CHARS)
    raw_marked = _raw(mk.path())
    assert raw_marked != raw_before

    u = mk.undo_last()
    assert u is not None and u["identical"] is True, "撤销必须逐字节回到处置前"
    assert _raw(mk.path()) == raw_before
    assert mk.states(THRESHOLD, MIN_CHARS) == {}
    assert _sha(book) == before, "撤销不该顺带动书稿"


def test_clear_scope_undoable(tmp_path: Path):
    """整批清回也进还原点，一步撤销可回到清回前（逐字节）。"""
    book = _book(tmp_path)
    mk = dm.DuplicateMarks(workspace=tmp_path / "ws")
    mk.bind(book)
    for gid in ("S-1", "S-2"):
        mk.set_state(gid, dm.ST_MARKED, threshold=THRESHOLD, min_chars=MIN_CHARS)
    raw_before = _raw(mk.path())
    res = mk.clear_scope(threshold=THRESHOLD, min_chars=MIN_CHARS)
    assert res["changed"] and res["cleared"] == 2
    u = mk.undo_last()
    assert u is not None and u["identical"] is True
    assert _raw(mk.path()) == raw_before


def test_canonical_bytes_accept_dict_or_list(tmp_path: Path):
    """规范字节对 ``records`` 的两种形状都认（dict 与 list），内容等价。"""
    one = dm.canonical_bytes("样本A", {"t0.75-m10": {"threshold": 0.75, "min_chars": 10,
                                                    "records": {"S-1": {"group_id": "S-1",
                                                                        "state": "marked"}}}})
    two = dm.canonical_bytes("样本A", {"t0.75-m10": {"threshold": 0.75, "min_chars": 10,
                                                    "records": [{"group_id": "S-1",
                                                                 "state": "marked"}]}})
    assert one == two
    assert json.loads(one.decode("utf-8"))["kind"] == dm.MARKS_KIND


# ---------------------------------------------------------------------------
# 4. 界面：跳转定位信号 + 入口接线 + 零技术词
# ---------------------------------------------------------------------------

def test_module_jump_and_marks(qt_app, tmp_path: Path, payload: dict):
    """页面装配清单 → 选中一组 → 跳转载荷带四套口径 → 标记 → 撤销。"""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from duplicate_module import DuplicateModule

    book = _book(tmp_path)
    before = _sha(book)
    mod = DuplicateModule()
    seen: list[dict] = []
    mod.jumpRequested.connect(seen.append)
    mod.set_book(str(book), "样本A")
    mod.shutdown()
    mod.set_payload(payload)
    assert mod.model.rowCount() == len(payload["groups"])
    assert mod.metrics()["groups"] == len(payload["groups"])

    mod.view.selectRow(0)
    payload_jump = mod.jump()
    assert payload_jump is not None and seen, "跳转必须发信号（供正文区接）"
    target = payload_jump["target"]
    assert set(target) >= {"paragraph_index", "chapter_no", "chapter_title",
                           "line_start", "line_end", "char_start", "char_end"}
    assert mod.last_jump()["group_id"] == payload_jump["group_id"]
    # 真实跳转的落点：这一行的正文出现在预览里，且光标选中的就是这一段
    shown = mod.preview.toPlainText()
    marked_line = f"L{target['line_start']}   "
    assert marked_line in shown, "跳转后预览里必须出现这一行"
    assert mod.preview.extraSelections(), "跳转后必须有高亮，否则不算跳到正文"
    selected = mod.preview.textCursor().selectedText()
    slot_text = dl.build_list(payload).items[0].slots[0].text
    assert selected.strip() and selected.strip()[:12] in slot_text, \
        "光标选中的应当是这一段的正文"

    gid = payload_jump["group_id"]
    QTest.mouseClick(mod.mark_btn, Qt.MouseButton.LeftButton)
    assert mod.marks.states(THRESHOLD, MIN_CHARS) == {gid: dm.ST_MARKED}
    assert _sha(book) == before
    QTest.mouseClick(mod.undo_btn, Qt.MouseButton.LeftButton)
    assert mod.marks.states(THRESHOLD, MIN_CHARS) == {}
    assert _sha(book) == before


def test_jump_payload_carries_four_views(qt_app, tmp_path: Path, payload: dict):
    """组内「上一处 / 下一处」切换后，跳转载荷跟着换到对应那一处。"""
    pytest.importorskip("PySide6")
    from duplicate_module import DuplicateModule

    book = _book(tmp_path)
    mod = DuplicateModule()
    mod.set_book(str(book), "样本A")
    mod.shutdown()
    mod.set_payload(payload)
    multi = [i for i, it in enumerate(payload["groups"]) if len(it["members"]) > 1]
    if not multi:
        pytest.skip("样本这轮没有多处成组的重复")
    mod.view.selectRow(multi[0])
    first = mod.jump()
    mod.step_member(1)
    second = mod.jump()
    assert second["member"] == 1 and second["total"] == first["total"]
    assert second["target"]["paragraph_index"] != first["target"]["paragraph_index"]


def test_check_page_entry_opens_duplicate_page(qt_app, tmp_path: Path):
    """检查页「批量操作」卡的入口 → 内容区平级路由页，左轨仍是 6 项。"""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from fixtext_tokens import DUPLICATE_KEY
    from main_window import MainWindow

    book = _book(tmp_path)
    win = MainWindow(workspace=tmp_path / "ws")
    win._apply_current_book(None, str(book))
    win._reload_book_pages()
    assert len(win.rail_items) == 6, "左轨六入口配额不变"
    assert DUPLICATE_KEY in win.pages and DUPLICATE_KEY not in win.rail_items

    btns = [b for b in win.check_module.findChildren(QPushButton) if b.text() == "打开"]
    assert len(btns) >= 2, "检查页批量操作卡应有「重复段落清单」入口"
    QTest.mouseClick(btns[-1], Qt.MouseButton.LeftButton)
    assert win.current_key == DUPLICATE_KEY
    assert win.page(DUPLICATE_KEY) is win.duplicate_module
    assert win.duplicate_module.book_id == "样本A", "点一次入口就必须挂上当前这本书"
    win.duplicate_module.shutdown()


def test_duplicate_page_has_no_tech_jargon(qt_app, tmp_path: Path, payload: dict):
    """页面可见文案零技术词（沿用 ``test_no_jargon`` 的禁用词口径）。"""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QLabel, QPushButton

    from duplicate_module import DuplicateModule
    from test_no_jargon import FORBIDDEN

    book = _book(tmp_path)
    mod = DuplicateModule()
    mod.set_book(str(book), "样本A")
    mod.shutdown()
    mod.set_payload(payload)
    hits: list[str] = []
    for w in mod.findChildren(QLabel) + mod.findChildren(QPushButton):
        text = (w.text() or "") + " " + (w.toolTip() or "")
        low = text.lower()
        hits += [f"{word}→{text[:40]}" for word in FORBIDDEN if word in low]
    assert not hits, f"页面出现了技术词：{hits[:5]}"
