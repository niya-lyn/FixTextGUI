"""V1.1-E4 · 逐批确认交互的验收用例。

本卡三条验收判据（排期文档 §10.5），每条都有机器可判定的用例：

1. **未经确认不得落盘**
   → ``test_execute_without_token_writes_nothing`` /
     ``test_ui_cancel_confirmation_writes_nothing`` /
     ``test_undo_without_token_writes_nothing``
2. **跳过可回退**
   → ``test_skip_is_reversible_and_touches_disk_never``
3. **每批可单独撤销**
   → ``test_each_batch_undoable_individually``（含非末批）/
     ``test_undo_non_last_batch_keeps_later_batches``

另有两个交付物本身的结构性检查：

- 交付物①的入口：索引/范围批量选择（``test_select_range_semantics`` /
  ``test_select_all_hits_only_nonzero``）、按批执行/跳过；
  以及它与既有路由结构的接线（``test_check_page_entry_opens_manual_page``）。
- 交付物②的备份：每批动手前一份备份进既有快照体系
  （``test_backup_created_before_each_batch``）。

以及界面文案零技术词（沿用 ``test_no_jargon`` 的词表口径）。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "fixtext_ui"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fixtext_batch_confirm as bc                    # noqa: E402
from fixtext_ui import fixtext_manual_search as M     # noqa: E402

SAMPLES = Path(__file__).resolve().parent / "samples"
SAMPLE_A = SAMPLES / "a_utf8_lf.txt"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture()
def book(tmp_path: Path) -> Path:
    """一份可写的书副本（原样本只读，用例之间互不影响）。"""
    dst = tmp_path / "书" / "book.txt"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(SAMPLE_A.read_text(encoding="utf-8"), encoding="utf-8")
    return dst


@pytest.fixture()
def session(book: Path) -> bc.BatchSession:
    """按「只选有命中的规则」建会话——和界面「只选有命中」入口同一路径。"""
    rs = M.load_rules(ROOT / "data" / "manual_search" / "rules.json")
    s = bc.BatchSession(rs, book.read_text(encoding="utf-8"), target_path=book)
    s.scan()
    s.select_all_hits()
    s.plan(3)
    return s


# ---------------------------------------------------------------------------
# 判据 1：未经确认不得落盘
# ---------------------------------------------------------------------------

def test_execute_without_token_writes_nothing(book: Path, session: bc.BatchSession):
    """没有确认凭证 → 抛 ConfirmationRequired，且一个字节都没写。"""
    base = _sha(book)
    with pytest.raises(bc.ConfirmationRequired):
        session.execute(1, None)
    assert _sha(book) == base
    assert session.written_once is False
    assert session.batch(1).state == bc.ST_PENDING


def test_execute_with_forged_token_writes_nothing(book: Path, session: bc.BatchSession):
    """凭证不是这一批签发的那个 → 同样拒绝（凭证绑定批次）。"""
    base = _sha(book)
    session.preview(1)
    with pytest.raises(bc.ConfirmationRequired):
        session.execute(1, "0" * 32)
    assert _sha(book) == base
    assert session.written_once is False


def test_execute_requires_prior_preview(book: Path, session: bc.BatchSession):
    """连预览都没做、凭空给个 token → 拒绝（凭证只由 preview 签发）。"""
    base = _sha(book)
    with pytest.raises(bc.ConfirmationRequired):
        session.execute(2, "anything")
    assert _sha(book) == base


def test_preview_itself_never_writes(book: Path, session: bc.BatchSession):
    """预览是只读的：签发凭证、给出示例，但不动磁盘。"""
    base = _sha(book)
    pv = session.preview(2)
    assert pv.hits > 0 and pv.samples
    assert _sha(book) == base
    assert session.written_once is False


def test_stale_preview_refused_after_text_changed(book: Path, session: bc.BatchSession):
    """预览后正文被别处改过 → 凭证作废（旧预览不能用来写新正文）。"""
    session.preview(1)
    book.write_text(book.read_text(encoding="utf-8") + "\n补一段\n", encoding="utf-8")
    with pytest.raises(bc.StalePreview):
        session.execute(1, session._previews[1].token)


def test_stale_preview_refused_after_disk_changed(book: Path, session: bc.BatchSession):
    """预览后磁盘上的书被外部改过 → 同样作废（内存与磁盘两份都核）。"""
    session.preview(1)
    book.write_text(book.read_text(encoding="utf-8") + "\n外部追加\n", encoding="utf-8")
    with pytest.raises(bc.StalePreview):
        session.execute(1, session._previews[1].token)


def test_undo_without_token_writes_nothing(book: Path, session: bc.BatchSession):
    """撤销也会写盘，因此同样要确认：没凭证不写。"""
    pv = session.preview(1)
    session.execute(1, pv.token)
    before_undo = _sha(book)
    with pytest.raises(bc.ConfirmationRequired):
        session.undo(1, None)
    assert _sha(book) == before_undo


def test_undo_last_refuses_without_token(book: Path, session: bc.BatchSession):
    """``undo_last`` 不再自签自销凭证——否则确认关口形同虚设。"""
    pv = session.preview(1)
    session.execute(1, pv.token)
    before = _sha(book)
    with pytest.raises(bc.ConfirmationRequired):
        session.undo_last()
    assert _sha(book) == before


# ---------------------------------------------------------------------------
# 判据 2：跳过可回退
# ---------------------------------------------------------------------------

def test_skip_is_reversible_and_touches_disk_never(book: Path, session: bc.BatchSession):
    base = _sha(book)
    session.skip(1, "先不动这条")
    assert session.batch(1).state == bc.ST_SKIPPED
    assert _sha(book) == base
    session.resume_skip(1)
    assert session.batch(1).state == bc.ST_PENDING
    assert _sha(book) == base
    assert session.written_once is False


def test_skipped_batch_cannot_be_executed_without_new_preview(book: Path, session: bc.BatchSession):
    """跳过后想再执行：旧凭证已随跳过作废，必须重新预览。"""
    session.preview(1)
    token = session._previews[1].token
    session.skip(1)
    base = _sha(book)
    with pytest.raises(bc.ConfirmationRequired):
        session.execute(1, token)
    assert _sha(book) == base


def test_skipped_batch_cannot_be_skipped_after_executed(book: Path, session: bc.BatchSession):
    """已执行的批不能「跳过」——要撤请走撤销（语义不能混）。"""
    pv = session.preview(1)
    session.execute(1, pv.token)
    with pytest.raises(bc.BatchError):
        session.skip(1)


def test_skip_reason_kept_for_ui(book: Path, session: bc.BatchSession):
    session.skip(2, "这一批先跳过")
    assert session.batch(2).reason == "这一批先跳过"


# ---------------------------------------------------------------------------
# 判据 3：每批可单独撤销
# ---------------------------------------------------------------------------

def test_each_batch_undoable_individually(book: Path, session: bc.BatchSession):
    """连续执行 3 批，再逆序逐批撤销 → 每一批都能撤，最终回到基线。"""
    base = _sha(book)
    for bid in (1, 2, 3):
        pv = session.preview(bid)
        session.execute(bid, pv.token)
    assert _sha(book) != base
    for bid in (3, 2, 1):
        token = session.prepare_undo(bid)
        rec = session.undo(bid, token)
        assert rec["mismatch"] == ""
        assert rec["backup_exact"] is True, f"第 {bid} 批重放结果应与该批备份逐字节一致"
        assert session.batch(bid).state == bc.ST_PENDING
    assert _sha(book) == base
    assert session.applied_order == []


def test_undo_non_last_batch_keeps_later_batches(book: Path, session: bc.BatchSession):
    """撤销前一批不能把后来的批次一起抹掉——只摘这一批。"""
    base = _sha(book)
    for bid in (1, 2):
        pv = session.preview(bid)
        session.execute(bid, pv.token)
    token = session.prepare_undo(1)
    rec = session.undo(1, token)
    assert session.applied_order == [2]
    assert session.batch(2).state == bc.ST_EXECUTED
    assert rec["text"] != base            # 第 2 批仍在正文里
    # 再撤第 2 批 → 回到基线
    t2 = session.prepare_undo(2)
    session.undo(2, t2)
    assert _sha(book) == base


def test_undo_of_pending_batch_refused(book: Path, session: bc.BatchSession):
    with pytest.raises(bc.BatchError):
        session.prepare_undo(1)


def test_replanning_invalidates_previews_and_undo_tokens(book: Path, session: bc.BatchSession):
    """重新挑范围 → 旧批次/旧凭证全部作废，不能拿旧凭证写新计划。"""
    pv = session.preview(1)
    token = pv.token
    session.select_range(0, 5)
    session.plan(2)
    base = _sha(book)
    with pytest.raises(bc.BatchError):
        session.execute(1, token)
    assert _sha(book) == base


# ---------------------------------------------------------------------------
# 交付物①：按索引 / 按范围批量选择
# ---------------------------------------------------------------------------

def test_select_range_semantics(session: bc.BatchSession):
    n = len(session.ruleset)
    assert session.select_range(0, 4) == [0, 1, 2, 3, 4]   # 闭区间
    assert session.select_range(3, 3) == [3]               # 单点
    assert session.select_range(9, 3) == []                # 逆区间 → 空
    idx = session.select_range(n - 2, n + 100)             # 超界自动收口
    assert idx == [n - 2, n - 1]


def test_select_all_hits_only_nonzero(session: bc.BatchSession):
    picked = session.select_all_hits()
    alive = session.nonzero_indices()
    assert picked == alive
    assert all(session.hits_of(i) > 0 for i in picked)
    assert session.select_all_hits(limit=2) == alive[:2]


def test_plan_covers_exactly_selected_rules(session: bc.BatchSession):
    session.select_range(0, 6)
    batches = session.plan(3)
    covered = [r.index for b in batches for r in b.rules]
    assert covered == [0, 1, 2, 3, 4, 5, 6]
    assert [len(b.rules) for b in batches] == [3, 3, 1]


def test_clear_selection_drops_plan(session: bc.BatchSession):
    session.clear_selection()
    assert session.selected == []
    assert session.plan(3) == []


# ---------------------------------------------------------------------------
# 交付物②：每批动手前自动备份
# ---------------------------------------------------------------------------

def test_backup_created_before_each_batch(book: Path, session: bc.BatchSession):
    """每批执行前一份备份进既有快照体系；备份内容 = 该批动手前的正文。"""
    base = _sha(book)
    pre = book.read_text(encoding="utf-8")
    pv = session.preview(1)
    session.execute(1, pv.token)
    rows = session.backups()
    assert rows, "执行后应有备份点"
    newest = rows[0]
    assert newest["act"] == "batch_replace"
    backup = session.store.before_bytes(newest["point_id"])
    assert backup is not None
    assert bc.sha256_bytes(backup) == hashlib.sha256(pre.encode("utf-8")).hexdigest()
    assert newest["sha_before"] == base


def test_backup_never_overwritten_by_later_undo(book: Path, session: bc.BatchSession):
    """撤销也留档，且原有备份点不被覆盖（备份只增不改）。"""
    pv = session.preview(1)
    session.execute(1, pv.token)
    n_after_exec = len(session.backups())
    t = session.prepare_undo(1)
    session.undo(1, t)
    rows = session.backups()
    assert len(rows) == n_after_exec + 1
    kinds = {r["act"] for r in rows}
    assert kinds == {"batch_replace", "batch_undo"}
    assert any(r["undone"] for r in rows)


def test_snapshot_store_is_the_existing_warehouse(book: Path, session: bc.BatchSession):
    """备份落在既有快照目录（``batch_backups``），不是另起一套。"""
    assert session.store.dir.name == bc.BACKUP_DIRNAME
    assert session.store.dir.parent == book.parent


# ---------------------------------------------------------------------------
# 界面层：取消确认 → 零写入；入口接线
# ---------------------------------------------------------------------------

def test_ui_cancel_confirmation_writes_nothing(qt_app, book: Path):
    """真实界面路径：预览后弹确认框点「取消」→ 一个字节都不写。"""
    pytest.importorskip("PySide6")
    import manual_module as mm

    base = _sha(book)
    mod = mm.ManualModule()
    calls = {"n": 0}
    mod._confirm_hook = lambda title, note: (calls.__setitem__("n", calls["n"] + 1) and False)
    mod.set_book(str(book), "书")
    mod.pick_nonzero()
    mod.chunk_box.setValue(2)
    mod.make_plan()
    mod.batch_view.selectRow(0)
    mod.preview_selected()
    mod.batch_view.selectRow(0)
    mod.execute_selected()
    assert calls["n"] == 1, "必须真的问过用户"
    assert _sha(book) == base
    assert mod.session.written_once is False
    assert "没有写入" in mod.last_message() or "取消" in mod.last_message()
    mod.shutdown()


def test_ui_confirm_writes_and_undo_works(qt_app, book: Path):
    """确认后写回，随后撤销这一批 → 回到基线。"""
    pytest.importorskip("PySide6")
    import manual_module as mm

    base = _sha(book)
    mod = mm.ManualModule()
    mod._confirm_hook = lambda title, note: True
    mod.set_book(str(book), "书")
    mod.pick_nonzero()
    mod.chunk_box.setValue(2)
    mod.make_plan()
    mod.batch_view.selectRow(0)
    mod.preview_selected()
    mod.batch_view.selectRow(0)
    mod.execute_selected()
    assert _sha(book) != base
    mod.batch_view.selectRow(0)
    mod.undo_selected()
    assert _sha(book) == base
    mod.shutdown()


def test_ui_undo_cancel_writes_nothing(qt_app, book: Path):
    """撤销的确认也能取消——取消后正文保持执行后的样子。"""
    pytest.importorskip("PySide6")
    import manual_module as mm

    mod = mm.ManualModule()
    answers = iter([True, False])
    mod._confirm_hook = lambda title, note: next(answers)
    mod.set_book(str(book), "书")
    mod.pick_nonzero()
    mod.chunk_box.setValue(2)
    mod.make_plan()
    mod.batch_view.selectRow(0)
    mod.preview_selected()
    mod.batch_view.selectRow(0)
    mod.execute_selected()
    after_exec = _sha(book)
    mod.batch_view.selectRow(0)
    mod.undo_selected()
    assert _sha(book) == after_exec
    mod.shutdown()


def test_check_page_entry_opens_manual_page(qt_app, tmp_path: Path):
    """检查页「批量操作」卡里的入口 → 内容区平级路由页，左轨仍是 6 项。"""
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton

    from main_window import MainWindow
    from fixtext_tokens import MANUAL_KEY

    book = tmp_path / "books" / "样本A" / "book.txt"
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text(SAMPLE_A.read_text(encoding="utf-8"), encoding="utf-8")

    win = MainWindow(workspace=tmp_path / "ws")
    win._apply_current_book(None, str(book))
    win._reload_book_pages()
    assert len(win.rail_items) == 6, "左轨六入口配额不变"
    assert MANUAL_KEY in win.pages
    assert MANUAL_KEY not in win.rail_items

    btns = [b for b in win.check_module.findChildren(QPushButton) if b.text() == "打开"]
    assert btns, "检查页批量操作卡应有「打开」入口"
    QTest.mouseClick(btns[0], Qt.MouseButton.LeftButton)
    assert win.current_key == MANUAL_KEY
    assert win.page(MANUAL_KEY) is win.manual_module
    assert "样本A" in win.manual_module.book_label.text()
    win.close()


# ---------------------------------------------------------------------------
# 文案：界面文本零技术词（口径沿用 test_no_jargon 的 FORBIDDEN 表）
# ---------------------------------------------------------------------------

FORBIDDEN = [
    "spine", "opf", "container.xml", "manifest", "ncx", "xhtml", "xml", "bom",
    "utf-8", "utf8", "gbk", "gb18030", "big5", "crlf", "sha256", "hash",
    "encoding", "charset", "codec", "zip",
]
ALLOWED_WORDS = {"epub", "txt"}


def test_manual_module_texts_have_no_tech_terms(qt_app, book: Path):
    """真实构建界面 + 跑一轮扫描/分批后，把控件文本扫一遍。"""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QLabel, QPushButton, QWidget

    import manual_module as mm

    mod = mm.ManualModule()
    mod._confirm_hook = lambda title, note: False
    mod.set_book(str(book), "书")
    mod.pick_nonzero()
    mod.chunk_box.setValue(2)
    mod.make_plan()
    mod.batch_view.selectRow(0)
    mod.preview_selected()
    mod.batch_view.selectRow(0)
    mod.skip_selected()

    texts: list[str] = []
    for w in mod.findChildren(QWidget):
        for attr in ("text", "placeholderText", "toolTip", "windowTitle"):
            if hasattr(w, attr):
                value = getattr(w, attr)
                if isinstance(value, str) and value:
                    texts.append(value)
        if isinstance(w, (QLabel, QPushButton)):
            for extra in ("accessibleName", "accessibleDescription"):
                value = getattr(w, extra, "")
                if isinstance(value, str) and value:
                    texts.append(value)
    bad = []
    for t in texts:
        low = t.lower()
        hits = [x for x in FORBIDDEN if x in low and x not in ALLOWED_WORDS]
        if hits:
            bad.append((t, hits))
    mod.shutdown()
    assert not bad, f"界面文本出现技术词：{bad}"


def test_rule_note_never_exposes_source_urls():
    """rules.json 的 note 里带站点链接，界面只能用由 mark 推出来的人话说明。"""
    import manual_module as mm

    rs = M.load_rules(ROOT / "data" / "manual_search" / "rules.json")
    model = mm.RulePickModel()
    model.set_rules(rs.rules if hasattr(rs, "rules") else list(rs))
    notes = []
    for row in range(model.rowCount()):          # 205 条全扫，不只抽样
        note = model.data(model.index(row, model.COL_NOTE), mm.Qt.ItemDataRole.DisplayRole)
        notes.append(note or "")
    joined = " ".join(notes).lower()
    assert "http" not in joined and "php" not in joined
    assert all(("改" in n) or ("规则" in n) for n in notes if n), \
        f"说明应是「把 X 改成 Y」或「按…这条规则处理」的形状：{notes[:5]}"
