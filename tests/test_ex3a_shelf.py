"""M4-EX.3a 回归：导入页书架 + 「当前书」显式化 + 顶栏当前书。

口径来源：原型 v3（合并版）更新记录 §6「多书工作区与书架打磨」与任务卡三条要求。

关键事实断言（不是"看起来对"）：
- 书架数据源就是工作区现有书目枚举，不新增导入副本；
- 书架状态只剩「已导出」一处，且必须由真实导出记录（exports.json）驱动——
  本卡没有写入方，所以正常路径下这个标识**不显示**（不放假状态）；
- 状态槽 60px + 动作槽 96px 固定宽度：切换当前书时相邻文字不位移；
- 「当前」是标识（QLabel），「设为当前」是主操作（QPushButton），两者分离；
- 当前书选择落设置文件、重启可恢复；导入新书自动设为当前（单书动线不退化）；
- 顶栏常驻书名（超长省略 + tooltip 全文），点击复用 go("import") 跳书架。
"""

import json
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtext_ui"))

LONG_TITLE = "第二部书的书名特别长用来验证顶栏省略号是否生效以及悬浮提示是否给出全文"


def _mk_book(ws: Path, book_id: str, title: str, suffix: str, size: int, when: str) -> Path:
    """在工作区里造一本"已导入"的书（结构与 importer 落盘一致）。"""
    d = ws / book_id
    (d / "original").mkdir(parents=True, exist_ok=True)
    (d / "book.txt").write_text("正文内容" * 50, encoding="utf-8")
    (d / "import.json").write_text(json.dumps({
        "book_id": book_id,
        "title": title,
        "author": "某作者",
        "source_suffix": suffix,
        "imported_at": when,
        "text_path": str(d / "book.txt"),
        "original_copy_path": str(d / "original" / f"book.{suffix}"),
    }, ensure_ascii=False), encoding="utf-8")
    (d / "original" / f"book.{suffix}").write_bytes(b"\0" * size)
    return d


@pytest.fixture()
def ws_two(tmp_path):
    """两本书的工作区：B 较新。返回 (workspace, b1_dir, b2_dir)。"""
    ws = tmp_path / "workspace"
    b1 = _mk_book(ws, "b1", "第一部书", "epub", 1024 * 1024, "2026-10-20 09:15:00")
    b2 = _mk_book(ws, "b2", LONG_TITLE, "txt", 800 * 1024, "2026-10-27 21:40:12")
    return ws, b1, b2


# ------------------------------------------------------------------ 数据层

def test_list_books_newest_first_with_real_fields(ws_two):
    """书架列表：新导入的在前，字段全来自 import.json 与实际目录。"""
    import fixtext_shelf as S

    ws, _, _ = ws_two
    books = S.list_books(ws)
    assert [b.book_id for b in books] == ["b2", "b1"], "最近导入的排在最前"
    assert books[0].title == LONG_TITLE
    assert books[0].fmt == "TXT" and books[1].fmt == "EPUB"
    assert books[0].size_bytes > 0 and books[1].size_bytes > books[0].size_bytes
    assert books[0].imported_at == "2026-10-27 21:40:12"
    assert books[0].text_path.endswith("book.txt")


def test_exported_flag_reads_real_record_only(ws_two):
    """「已导出」只能来自真实导出记录；本卡没有写入方 → 恒为空。"""
    import fixtext_shelf as S

    ws, b1, _ = ws_two
    assert all(b.exported_at == "" for b in S.list_books(ws)), \
        "没有任何导出记录时不允许出现「已导出」状态"
    # 真写一条导出记录 → 标识立刻有数据（证明判据接的是真数据源，不是写死 False）
    (b1 / "exports.json").write_text(json.dumps(
        {"exported_at": "2026-10-28 10:00:00", "path": "out.epub"}, ensure_ascii=False),
        encoding="utf-8")
    book = S.find_book(ws, "b1")
    assert book is not None and book.exported_at == "2026-10-28 10:00:00"


def test_current_book_persists_in_settings(ws_two):
    """当前书落设置文件：清掉内存态后仍能读回（= 重启保持）。"""
    import fixtext_shelf as S
    import fixtext_settings as app_settings

    ws, _, _ = ws_two
    S.set_current_book_id("b1")
    assert S.stored_current_id() == "b1"
    assert app_settings._get(S.KEY_CURRENT_BOOK) == "b1", "必须写进设置文件，不能只存内存"
    S.clear_current_book_id()
    assert S.stored_current_id() == ""


def test_resolve_current_fallbacks(ws_two):
    """没记录 → 最近导入的那本；记录指向已不存在的书 → 同样回落，不留死引用。"""
    import fixtext_shelf as S

    ws, _, _ = ws_two
    books = S.list_books(ws)
    S.clear_current_book_id()
    cur = S.resolve_current(ws, books)
    assert cur is not None and cur.book_id == "b2", "无记录时按最近导入"
    S.set_current_book_id("b_gone")
    cur = S.resolve_current(ws, books)
    assert cur is not None and cur.book_id == "b2", "记录失效必须回落，不能让顶栏空着"
    S.clear_current_book_id()


# ------------------------------------------------------------------ 书架界面

def test_shelf_rows_content_and_fixed_slots(qapp, ws_two):
    """行内容齐全（书名/格式/大小/导入时间/当前标识）+ 两个固定宽度槽位。"""
    import fixtext_shelf_ui as SU
    import fixtext_shelf as S

    ws, _, _ = ws_two
    S.clear_current_book_id()
    panel = SU.ShelfPanel(ws)
    panel.resize(880, 300)
    panel.show()
    panel.refresh()
    assert len(panel.rows) == 2

    # 当前书 = 最近导入（b2）→ 第一行是「当前」标识，第二行是「设为当前」操作
    cur_row, other_row = panel.rows
    assert cur_row.book.book_id == "b2"
    assert cur_row.badge is not None and cur_row.badge.text() == "当前"
    assert cur_row.action_btn is None, "当前行不应再出现「设为当前」"
    assert other_row.badge is None and other_row.action_btn is not None
    assert other_row.action_btn.text() == "设为当前"

    # 「当前」是 QLabel 标识，「设为当前」是 QPushButton 主操作 —— 两者分离
    assert isinstance(cur_row.badge, QLabel)
    assert isinstance(other_row.action_btn, QPushButton)

    # 固定槽位：状态 60 / 动作 96，标识与按钮同高 → 切换不位移
    assert cur_row.status.width() == cur_row.status.width() == SU.STATUS_SLOT_W
    assert cur_row.action_slot.width() == other_row.action_slot.width() == SU.ACTION_SLOT_W
    assert cur_row.badge.height() == other_row.action_btn.height() == SU.SHELF_BADGE_H

    # 行内容：书名带书名号与后缀；格式·大小·导入时间
    assert cur_row.name.full_text() == f"《{LONG_TITLE}》txt"
    assert "TXT ·" in cur_row.meta.text() and "10月27日" in cur_row.meta.text()
    assert other_row.name.full_text() == "《第一部书》epub"
    assert "EPUB ·" in other_row.meta.text() and "10月20日" in other_row.meta.text()

    # 只有真实导出记录才显示「已导出」，否则空
    assert cur_row.status.text() == "" and other_row.status.text() == ""


def test_shelf_set_current_switches_and_persists(qapp, ws_two):
    """点「设为当前」→ 当前标记换行 + 落设置 + 发信号；不动其它行文字。"""
    import fixtext_shelf_ui as SU
    import fixtext_shelf as S

    ws, _, _ = ws_two
    S.clear_current_book_id()
    panel = SU.ShelfPanel(ws)
    panel.resize(880, 300)
    panel.show()
    panel.refresh()

    fired = []
    panel.currentChanged.connect(fired.append)
    before = [r.name.full_text() for r in panel.rows]

    target = [r for r in panel.rows if r.book.book_id == "b1"][0]
    target.action_btn.click()

    assert fired == ["b1"], "书架面板把选中的书 id 报给外层（路径由外层按记录解析）"
    assert panel.current_id() == "b1"
    assert S.stored_current_id() == "b1", "切换必须持久化"
    assert [r.name.full_text() for r in panel.rows] == before, "切换不得改动任何书名文字（不位移）"

    cur = [r for r in panel.rows if r.property("current") == "true"][0]
    assert cur.book.book_id == "b1" and cur.badge is not None
    S.clear_current_book_id()


def test_shelf_row_click_also_switches(qapp, ws_two):
    """整行可点（原型 .ws-row cursor:pointer 的行为），不只是按钮。"""
    import fixtext_shelf_ui as SU
    import fixtext_shelf as S
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QPoint

    ws, _, _ = ws_two
    S.clear_current_book_id()
    panel = SU.ShelfPanel(ws)
    panel.resize(880, 300)
    panel.show()
    panel.refresh()
    row = [r for r in panel.rows if r.book.book_id == "b1"][0]
    QTest.mouseClick(row, Qt.MouseButton.LeftButton, pos=QPoint(30, row.height() // 2))
    assert panel.current_id() == "b1"
    S.clear_current_book_id()


# ------------------------------------------------------------------ 顶栏胶囊

def test_book_chip_ellipsis_and_tooltip(qapp):
    """超长书名省略显示 + tooltip 给全文；点一下发 clicked（由主窗口路由）。"""
    import fixtext_shelf_ui as SU

    chip = SU.BookChip()
    chip.resize(SU.CHIP_MAX_W, SU.CHIP_H)
    chip.set_book(LONG_TITLE)
    chip.show()
    qapp.processEvents()

    shown = chip.name.text()
    assert shown.endswith("…") and len(shown) < len(LONG_TITLE), "超长书名必须省略"
    assert chip.toolTip().startswith(LONG_TITLE), "悬浮提示必须给完整书名"
    assert chip.width() <= SU.CHIP_MAX_W
    assert chip.property("empty") == "false"

    fired = []
    chip.clicked.connect(lambda: fired.append(1))
    from PySide6.QtTest import QTest
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    assert fired == [1], "点击必须发信号（无书时也一样跳书架）"


def test_book_chip_empty_placeholder_still_clickable(qapp):
    """没有书 → 中性占位文案，依然可点。"""
    import fixtext_shelf_ui as SU
    from PySide6.QtTest import QTest

    chip = SU.BookChip()
    chip.resize(SU.CHIP_MAX_W, SU.CHIP_H)
    chip.set_book(None)
    chip.show()
    fired = []
    chip.clicked.connect(lambda: fired.append(1))
    QTest.mouseClick(chip, Qt.MouseButton.LeftButton)
    assert chip.property("empty") == "true"
    assert chip.name.text() == "未选择书", "无书时用中性文案，不能空着"
    assert fired == [1], "无书点击也要能跳到书架"


# ------------------------------------------------------------- 主窗口集成

def _win(ws: Path, monkeypatch):
    """构建主窗口，工作区指向临时目录。"""
    import main_window as mw
    return mw.MainWindow(workspace=ws)


def test_window_shows_restored_current_book(qapp, ws_two, monkeypatch):
    """启动即显示设置里记的当前书（= 重启保持）；顶栏书名来自真记录。"""
    import fixtext_shelf as S
    import main_window as mw

    ws, _, _ = ws_two
    S.set_current_book_id("b1")
    try:
        win = mw.MainWindow(workspace=ws)
        assert win.book_chip.name.full_text() == "第一部书"
        assert win._import_record is not None
        assert win._import_record.get("title") == "第一部书"
        assert win._current_text_path.endswith(("b1/book.txt", "b1\\book.txt"))
    finally:
        S.clear_current_book_id()


def test_window_click_chip_routes_to_import_and_highlights(qapp, ws_two):
    """点顶栏 → 走既有 go("import") 到导入页，且书架里当前书行高亮。"""
    import fixtext_shelf as S
    import fixtext_shelf_ui as SU
    import main_window as mw
    from PySide6.QtTest import QTest

    ws, _, _ = ws_two
    S.set_current_book_id("b1")
    try:
        win = mw.MainWindow(workspace=ws)
        win.show()
        assert win.current_key != "import"
        QTest.mouseClick(win.book_chip, Qt.MouseButton.LeftButton)
        assert win.current_key == "import", "点击顶栏必须复用既有 go() 路由到导入页"
        panel = win.import_module.shelf
        assert not win.import_module.empty_state.isVisibleTo(win.import_module)
        active = [r for r in panel.rows if r.property("current") == "true"]
        assert len(active) == 1 and active[0].book.book_id == "b1", "当前书行要高亮"
    finally:
        S.clear_current_book_id()


def test_window_shelf_switch_updates_chip_only(qapp, ws_two):
    """书架里换书 → 顶栏书名跟着换；不做跨页联动（3b 范围）。"""
    import fixtext_shelf as S
    import main_window as mw

    ws, _, _ = ws_two
    S.set_current_book_id("b2")
    try:
        win = mw.MainWindow(workspace=ws)
        assert win.book_chip.name.full_text().startswith(LONG_TITLE[:6])
        win._on_current_book_changed(str(ws / "b1" / "book.txt"))
        assert win.book_chip.name.full_text() == "第一部书", "切书后顶栏必须换名"
        assert win._import_record.get("title") == "第一部书"
    finally:
        S.clear_current_book_id()


def test_new_import_auto_becomes_current(qapp, ws_two):
    """导入新书自动设为当前 —— 单书动线「导入完直接往下走」的关键闭环。"""
    import fixtext_shelf as S
    import main_window as mw

    ws, _, _ = ws_two
    S.set_current_book_id("b1")
    try:
        win = mw.MainWindow(workspace=ws)
        assert win.book_chip.name.full_text() == "第一部书"
        # 模拟第二本导入完成（b2 已在工作区，走同一条接力）
        win._on_book_ready(str(ws / "b2" / "book.txt"))
        assert S.stored_current_id() == "b2", "新导入的书必须自动成为当前书"
        assert win.book_chip.name.full_text().startswith(LONG_TITLE[:6])
        # 书架同步重排：b2 行显示「当前」，b1 行回到「设为当前」
        rows = win.import_module.shelf.rows
        cur = [r for r in rows if r.property("current") == "true"][0]
        assert cur.book.book_id == "b2"
    finally:
        S.clear_current_book_id()


def test_empty_workspace_keeps_empty_state_and_placeholder(qapp, tmp_path):
    """无书：导入页空状态照旧（2b 契约）+ 顶栏中性占位。"""
    import main_window as mw

    ws = tmp_path / "workspace"
    ws.mkdir()
    win = mw.MainWindow(workspace=ws)
    assert win.book_chip.property("empty") == "true"
    assert win.book_chip.name.text() == "未选择书"
    assert win.import_module.empty_state.isVisibleTo(win.import_module)
    assert not win.import_module.workspace_card.isVisibleTo(win.import_module)
