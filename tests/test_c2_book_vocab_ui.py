"""V1.1-C2 · 按书词库界面与端到端验证。

排期 8.3 的两条交付物，每一条都有可证伪断言：

1. **界面层**：本书停用清单的查看 / 新增 / 移出 / 行内启停——全部复用
   B2 的行内开关与撤销栈语义（点一下即时生效、即时留还原点、失败就地
   退回真实状态），不另造交互范式。判据是**真实点击**（QTest.mouseClick）
   + 磁盘字节的 sha，不看函数返回值自报。
2. **端到端**：A 书停用某词条 → A 校正结果变化（真引擎）；B 书不受影响
   （= 全局默认基线）；A 切回（移出）→ 恢复基线；界面撤销 → 文件字节复原。

范围边界（任务原文）：数据与装载层已由 C1 完成，本卡不另造过滤路径、
不绕过 C1 的 book_vocab 数据层——界面所有读写都经 VocabStore 转调
``fixtext_book_scope`` → C1 ``book_vocab``。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui", PKG / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 注意：必须用顶层 fixtext_vocab 导入（与 vocab_module 的导入路径一致）。
# sys.path 同时含 PKG 与 PKG/fixtext_ui 时，fixtext_ui.fixtext_vocab 与顶层
# fixtext_vocab 是两个模块对象、各自持有不同的 VocabDataError 类，
# monkeypatch 抛错会因 except 不命中而穿透。
from fixtext_vocab import VocabStore, VocabDataError                       # noqa: E402
from fixtext_pipeline import book_vocab as bv                              # noqa: E402

RULES = PKG / "data" / "rules"

#: 与 C1 同一枚探针（公版样本里真实出现、不在迁入禁用集里）。
PROBE_WORD = "告之"
PROBE_VALUE = "告知"

BOOK_A = "书A_1a2b3c4d"
BOOK_B = "书B_9f8e7d6c"

_ENGINE_BIN = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
try:
    from fixtext_pipeline.engine_selector import select_engine

    ENGINE = select_engine(_ENGINE_BIN) or (_ENGINE_BIN / "__no_platform_engine__")
except Exception:                                              # pragma: no cover
    ENGINE = _ENGINE_BIN / "__no_platform_engine__"

needs_engine = pytest.mark.skipif(not ENGINE.exists(), reason="缺少真实引擎")

#: 与 t32 同源的内部概念禁词（本卡只扫按书面板新增的文案）。
FORBIDDEN = [
    r"/home/", r"/tmp", r"\.json\b", r"\bsnapshots?\b", r"\bworkspace\b",
    r"custom_vocab", r"\brules\b", r"\bindex\.json\b", r"[A-Za-z]:\\\\",
    r"\bpath\b", r"\bdir\b", r"sha256", r"\bhash\b",
]


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 工具：真实点击
# ---------------------------------------------------------------------------

def _click(widget):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    widget.show()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)


def _click_button_text(root, text: str) -> bool:
    from PySide6.QtWidgets import QAbstractButton

    root.show()
    for b in root.findChildren(QAbstractButton):
        if b.text().strip() == text and b.isVisibleTo(root):
            _click(b)
            return True
    return False


def _visible_modals(mod):
    from fixtext_widgets import Modal

    from PySide6.QtWidgets import QApplication
    return [d for d in QApplication.topLevelWidgets() if isinstance(d, Modal) and d.isVisible()]


def _modal_by_title(mod, title: str):
    """按标题选可见弹窗——topLevelWidgets 的返回顺序不保证稳定，取 [-1] 会抖动。"""
    for d in _visible_modals(mod):
        if d.windowTitle() == title or d.property("title") == title:
            return d
    return None


def _book_file(store: VocabStore, book_id: str = "") -> Path:
    p = store._book_path_for(book_id)
    assert p is not None, "合法书 id 必须能推算出按书文件位置"
    return p


@pytest.fixture()
def mod(qapp, tmp_path):
    """词库面板：自定义词库 / 还原点 / 按书清单都落在临时子树（不碰交付包用户区）。"""
    import vocab_module as vm

    m = vm.VocabModule()
    m.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    m.store.add_entry(word=PROBE_WORD, value=PROBE_VALUE, typ="错词校正")
    m._page = 0
    m.search = ""
    m.dict_, m.tier = "custom", "custom"
    m._render_all()
    m.set_book_scope(BOOK_A, "书甲")
    yield m
    m.close()


def _stop_probe_via_store(store: VocabStore, book_id: str = BOOK_A) -> Path:
    """经界面同一数据层落一条停用（测试前置，不绕过 VocabStore）。"""
    store.set_book(book_id)
    store.set_book_excluded(PROBE_WORD, PROBE_VALUE, excluded=True,
                            reason="测试·本书停用")
    return _book_file(store, book_id)


# ---------------------------------------------------------------------------
# 1 · 查看入口：卡片可见性 + 空状态 + 文案不露内部概念
# ---------------------------------------------------------------------------

def test_book_card_hidden_without_current_book(qapp, tmp_path):
    import vocab_module as vm

    m = vm.VocabModule()
    m.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    m._render_all()
    try:
        assert m._book_card_w.isHidden() is True, "没有选中的书不该出现按书面板"
        assert m._book_scope_id == ""
    finally:
        m.close()


def test_book_card_shows_book_and_empty_state(mod):
    assert mod._book_card_w.isHidden() is False
    assert "书甲" in mod._book_scope_head.text()
    assert "0 条" in mod._book_scope_head.text()
    # 空状态给人话引导，不摆假清单
    texts = [w.text() for w in mod._book_card_w.findChildren(type(mod.legend))]
    assert any("本书没有停用的词条" in t for t in texts), texts


def test_book_card_texts_have_no_internal_concepts(mod):
    from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

    _stop_probe_via_store(mod.store)
    mod._render_book_scope()
    texts: list[str] = []
    for w in mod._book_card_w.findChildren(QWidget):
        for attr in ("toolTip", "accessibleName", "placeholderText"):
            v = getattr(w, attr, "")
            v = v() if callable(v) else v
            if isinstance(v, str) and v:
                texts.append(v)
        if isinstance(w, QLabel):
            texts.append(w.text())
        if isinstance(w, QAbstractButton):
            texts.append(w.text())
    hits = [(pat, t[:80]) for t in texts for pat in FORBIDDEN
            if re.search(pat, t, re.IGNORECASE)]
    assert not hits, f"按书面板文案出现内部概念 {hits}"


def test_invalid_book_id_hides_card(mod):
    mod.set_book_scope("../etc", "坏书")
    assert mod._book_scope_id == "", "不合规的书 id 不许进面板"
    assert mod.store.book_id() == ""
    assert mod._book_card_w.isHidden() is True


# ---------------------------------------------------------------------------
# 2 · 新增停用：先预览、再确认（真实两步点击）
# ---------------------------------------------------------------------------

def test_add_book_stop_full_flow_real_clicks(mod):
    f = _book_file(mod.store)
    assert not f.exists()
    points_before = mod.store.point_count()

    assert _click_button_text(mod, "＋ 新增停用"), "工具区必须有「新增停用」入口"
    modals = _visible_modals(mod)
    assert modals, "新增停用必须先弹预览输入窗"
    # topLevelWidgets 顺序不保证稳定，必须按标题选窗（偶发取错窗会让断言抖动）
    dlg = _modal_by_title(mod, "本书停用词条")
    # 预览阶段一个字节都不写（底线④）
    assert not f.exists() and mod.store.point_count() == points_before

    from PySide6.QtWidgets import QLineEdit
    edits = [e for e in dlg.findChildren(QLineEdit)]
    assert len(edits) >= 2, "新增停用要能填原词与替换值"
    edits[0].setText(PROBE_WORD)
    edits[1].setText(PROBE_VALUE)
    assert _click_button_text(dlg, "预览并确认"), "必须有「预览并确认」按钮"

    modals = _visible_modals(mod)
    assert modals, "预览确认窗必须出现"
    dlg2 = _modal_by_title(mod, "停用本书词条（二次确认）")
    assert dlg2 is not dlg
    # 确认前仍然一个字节都不写
    assert not f.exists() and mod.store.point_count() == points_before
    assert _click_button_text(dlg2, "确认停用"), "预览窗里必须有「确认停用」"

    # 落盘核对：文件真的写了、内容是这条排除项
    assert f.exists()
    raw = json.loads(f.read_text(encoding="utf-8"))
    keys = [e["key"] for e in raw["excluded"]]
    assert bv.entry_key(PROBE_WORD, PROBE_VALUE) in keys
    assert mod.store.point_count() == points_before + 1, "停用必须留还原点"
    # 界面同步：清单出现这一行，计数从 0 → 1
    assert "1 条" in mod._book_scope_head.text()
    assert (PROBE_WORD, PROBE_VALUE) in mod._book_switches


def test_preview_rejects_pair_not_in_vocab(mod):
    f = _book_file(mod.store)
    mod.preview_book_stop(None, "不存在的词", "不存在的值")
    assert not f.exists(), "词库里没有的词条不许写进停用清单"
    assert "没有找到" in mod.status.text()


def test_preview_rejects_already_stopped(mod):
    _stop_probe_via_store(mod.store)
    f = _book_file(mod.store)
    before = _sha(f)
    mod._render_book_scope()
    mod.preview_book_stop(None, PROBE_WORD, PROBE_VALUE)
    assert _sha(f) == before, "已停用的词条重复提交不该再写文件"
    assert "已经是停用" in mod.status.text()


# ---------------------------------------------------------------------------
# 3 · 行内启停 + 移出：真实点击，失败回退，撤销复原字节
# ---------------------------------------------------------------------------

def _pump(qapp):
    """让 singleShot 延迟重排执行完（开关信号返回事件循环之后）。"""
    for _ in range(8):
        qapp.processEvents()


def test_switch_real_click_removes_and_undo_restores_bytes(mod, qapp):
    f = _stop_probe_via_store(mod.store)
    mod._render_book_scope()
    stopped_sha = _sha(f)
    points_before = mod.store.point_count()

    sw = mod._book_switches[(PROBE_WORD, PROBE_VALUE)]
    assert sw.isChecked() is False, "清单里的行初始就是本书停用"
    _click(sw)

    # 开关生效：文件里这条排除被移出，且留了还原点
    raw = json.loads(f.read_text(encoding="utf-8"))
    assert bv.entry_key(PROBE_WORD, PROBE_VALUE) not in [e["key"] for e in raw["excluded"]]
    assert mod.store.point_count() == points_before + 1
    _pump(qapp)
    assert "0 条" in mod._book_scope_head.text(), "清单要按新数据重排"

    # 撤销：字节级复原（与操作前逐字节相同）
    mod._undo()
    assert _sha(f) == stopped_sha, "撤销后按书文件必须回到操作前的字节"
    assert "1 条" in mod._book_scope_head.text()
    assert (PROBE_WORD, PROBE_VALUE) in mod._book_switches


def test_remove_button_real_click_and_undo(mod):
    f = _stop_probe_via_store(mod.store)
    mod._render_book_scope()
    stopped_sha = _sha(f)

    assert _click_button_text(mod._book_card_w, "移出"), "每行必须有「移出」入口"
    raw = json.loads(f.read_text(encoding="utf-8"))
    assert bv.entry_key(PROBE_WORD, PROBE_VALUE) not in [e["key"] for e in raw["excluded"]]
    assert "0 条" in mod._book_scope_head.text()

    mod._undo()
    assert _sha(f) == stopped_sha, "移出撤销后必须逐字节复原"


def test_switch_failure_rolls_back_in_place(mod, qapp, monkeypatch):
    f = _stop_probe_via_store(mod.store)
    mod._render_book_scope()
    before = _sha(f)

    def _boom(*a, **k):
        raise VocabDataError("写入被测试拦下")

    monkeypatch.setattr(mod.store, "set_book_excluded", _boom)
    sw = mod._book_switches[(PROBE_WORD, PROBE_VALUE)]
    _click(sw)
    # 失败：开关退回真实状态（仍是停用），文件一个字节没动
    assert sw.isChecked() is False, "落盘失败开关必须就地退回"
    assert _sha(f) == before
    assert "没有改成功" in mod.status.text()


def test_idempotent_toggle_leaves_no_point(mod):
    _stop_probe_via_store(mod.store)
    points = mod.store.point_count()
    res = mod.store.set_book_excluded(PROBE_WORD, PROBE_VALUE, excluded=True)
    assert res["changed"] is False
    assert mod.store.point_count() == points, "状态没变不该留还原点"


# ---------------------------------------------------------------------------
# 4 · 跨书隔离（界面侧）：A 的停用不落 B，切书即换清单
# ---------------------------------------------------------------------------

def test_cross_book_isolation_in_ui(mod):
    fa = _stop_probe_via_store(mod.store, BOOK_A)
    a_sha = _sha(fa)

    mod.set_book_scope(BOOK_B, "书乙")
    fb = _book_file(mod.store, BOOK_B)
    assert not fb.exists(), "B 书自己的清单文件不该被创建"
    assert "书乙" in mod._book_scope_head.text()
    assert "0 条" in mod._book_scope_head.text(), "B 书面板不允许出现 A 书的停用条目"
    assert _sha(fa) == a_sha, "切到 B 书不允许改动 A 书的清单"

    # 切回 A：清单还在（撤销栈也还认这本书）
    mod.set_book_scope(BOOK_A, "书甲")
    assert "1 条" in mod._book_scope_head.text()
    assert (PROBE_WORD, PROBE_VALUE) in mod._book_switches


def test_undo_after_switching_book_restores_original_book(mod):
    """撤销发生在切书之后：还原点必须写回**当初那本书**，不污染当前书。"""
    fa = _stop_probe_via_store(mod.store, BOOK_A)
    a_sha = _sha(fa)

    mod.set_book_scope(BOOK_B, "书乙")
    fb = _book_file(mod.store, BOOK_B)
    mod._undo()          # 撤销的是 A 书那次停用；现在当前书是 B
    assert not fb.exists(), "撤销 A 书的操作不许把字节写进 B 书"
    # A 书那次停用被撤销 → 还原点是「操作前文件不存在」→ 文件被删掉
    assert not fa.exists(), "撤销后 A 书清单应回到操作前（当初文件不存在）"


# ---------------------------------------------------------------------------
# 5 · GUI 接线：主窗口注入 book_id、换书即换面板
# ---------------------------------------------------------------------------

def _mk_book(ws: Path, book_id: str, title: str) -> Path:
    d = ws / book_id
    (d / "original").mkdir(parents=True, exist_ok=True)
    (d / "book.txt").write_text(f"《{title}》正文。" * 20, encoding="utf-8")
    (d / "import.json").write_text(json.dumps({
        "book_id": book_id, "title": title, "author": "某作者",
        "source_suffix": "txt", "imported_at": "2026-11-04 09:00:00",
        "text_path": str(d / "book.txt"),
        "original_copy_path": str(d / "original" / "book.txt"),
    }, ensure_ascii=False), encoding="utf-8")
    (d / "original" / "book.txt").write_bytes(b"\0" * 64)
    return d


def test_build_run_context_injects_book_id(qapp, tmp_path):
    import main_window as mw

    ws = tmp_path / "ws"
    ws.mkdir()
    _mk_book(ws, BOOK_A, "书甲")
    _mk_book(ws, BOOK_B, "书乙")
    win = mw.MainWindow(workspace=ws)
    try:
        ctx_a = win.build_run_context(str(ws / BOOK_A / "book.txt"))
        ctx_b = win.build_run_context(str(ws / BOOK_B / "book.txt"))
        assert ctx_a["book_id"] == BOOK_A
        assert ctx_b["book_id"] == BOOK_B
    finally:
        win.close()


def test_switching_current_book_updates_vocab_panel(qapp, tmp_path):
    import main_window as mw

    ws = tmp_path / "ws"
    ws.mkdir()
    _mk_book(ws, BOOK_A, "书甲")
    _mk_book(ws, BOOK_B, "书乙")
    win = mw.MainWindow(workspace=ws)
    try:
        # 词库页挂临时存储（不碰交付包用户区），界面链路保持真实
        win.vocab_module.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
        win.vocab_module.store.add_entry(word=PROBE_WORD, value=PROBE_VALUE,
                                         typ="错词校正")
        win._on_current_book_changed(str(ws / BOOK_A / "book.txt"))
        assert win.vocab_module._book_scope_id == BOOK_A
        assert "书甲" in win.vocab_module._book_scope_head.text()

        _stop_probe_via_store(win.vocab_module.store, BOOK_A)
        win.vocab_module._render_book_scope()
        assert "1 条" in win.vocab_module._book_scope_head.text()

        # 换书：面板跟到 B，A 的条目不留页面上
        win._on_current_book_changed(str(ws / BOOK_B / "book.txt"))
        assert win.vocab_module._book_scope_id == BOOK_B
        assert "书乙" in win.vocab_module._book_scope_head.text()
        assert "0 条" in win.vocab_module._book_scope_head.text()

        # 换回 A：清单还在
        win._on_current_book_changed(str(ws / BOOK_A / "book.txt"))
        assert "1 条" in win.vocab_module._book_scope_head.text()
    finally:
        win.close()


# ---------------------------------------------------------------------------
# 6 · 位置契约：界面写的位置 = 管线读的位置（默认推算，同一条链）
# ---------------------------------------------------------------------------

def test_default_book_location_gui_matches_pipeline():
    """GUI 默认写的按书文件位置必须与管线 book_id 默认推算**同一处**。

    这条断言是「界面停用 → 下次校正生效」的链路前提：两边各算各的、
    差一个目录，用户在界面停用的词条就永远到不了校正那边。
    """
    from fixtext_vocab import CUSTOM_DIR

    gui_path = CUSTOM_DIR / "books" / BOOK_A / "book_vocab.json"
    pipe_path = bv.book_vocab_path(BOOK_A)      # 只给书 id 的默认推算
    assert gui_path == pipe_path, (
        f"界面与管线推算出了两个位置：{gui_path} vs {pipe_path}")


# ---------------------------------------------------------------------------
# 7 · 真引擎端到端：界面写的清单驱动校正结果（A 变 / B 不变 / A 切回复原）
# ---------------------------------------------------------------------------

_CORPUS = (
    "他告之众人，众人告之他。\n"
    "告之 之事，不可告之 两次。\n"
    "费劲思量，终究费劲思量。\n"
)


def _body_only(text: str) -> str:
    """摘掉 epubtext-bundle 头部（含随机 nonce 与书名）再比对正文。"""
    return "\n".join(
        ln for ln in text.splitlines() if not ln.startswith("<!-- EPUBTEXT-"))


def _run_book(tmp_path: Path, name: str, *, book_vocab_path=None, book_id=""):
    """跑一次真六阶段校正，返回 (正文 sha256, 报告里的按书层字段)。"""
    from fixtext_worker import CorrectionJob
    from plain_book import plain_source_epub

    tag = name.replace("/", "_")
    src_txt = tmp_path / f"{tag}.txt"
    src_txt.write_text(_CORPUS, encoding="utf-8")
    src = plain_source_epub(src_txt, tmp_path / f"{tag}_src", title=tag)
    custom = tmp_path / f"{tag}_custom.json"
    custom.write_text('{"entries": []}', encoding="utf-8")
    job = CorrectionJob(
        epub=src, workdir=tmp_path / f"{tag}_run",
        rules_before=RULES / "before.json", rules_after=RULES / "after.json",
        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
        title=tag, custom_vocab_path=custom,
        derived_rules_dir=tmp_path / f"{tag}_derived",
        book_id=book_id, book_vocab_path=book_vocab_path,
    )
    summary = job.run()
    after = Path(summary["artifacts"]["after_text"])
    raw = _body_only(after.read_text(encoding="utf-8"))
    rep = json.loads((tmp_path / f"{tag}_run" / "03_replace"
                      / "replace_report.json").read_text(encoding="utf-8"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), rep


@needs_engine
def test_e2e_ui_written_stop_changes_book_a_only(tmp_path):
    """端到端四段（排期 8.3 判据的逐字落地）：

    A 书停用探针词条（**经界面同一数据层 VocabStore 写入**）→ A 校正
    正文变化且 ``book_excluded_applied``=1；B 书不受影响（= 全局默认基线，
    且 B 的清单文件从头到尾不存在）；A 移出停用 → 恢复基线。
    """
    store = VocabStore(custom_path=tmp_path / "ws" / "custom_vocab.json")
    pa = _book_file(store, BOOK_A)
    pb = _book_file(store, BOOK_B)

    # 段 0：基线（两本书都没有按书层）
    sha_a0, rep_a0 = _run_book(tmp_path, "a0", book_vocab_path=pa, book_id=BOOK_A)
    sha_b0, rep_b0 = _run_book(tmp_path, "b0", book_vocab_path=pb, book_id=BOOK_B)
    assert rep_a0["derived_rules"]["book_excluded_applied"] == 0
    assert rep_b0["derived_rules"]["book_excluded_applied"] == 0

    # 段 1：界面同一数据层停用 A 书的探针词条 → A 结果变化
    store.set_book(BOOK_A)
    store.set_book_excluded(PROBE_WORD, PROBE_VALUE, excluded=True,
                            reason="端到端·本书停用")
    assert pa.exists(), "界面写入必须真的落盘"
    sha_a1, rep_a1 = _run_book(tmp_path, "a1", book_vocab_path=pa, book_id=BOOK_A)
    assert sha_a1 != sha_a0, "A 书停用了词条，校正结果却没变 → 按书层没生效"
    assert rep_a1["derived_rules"]["book_excluded_applied"] == 1
    assert (rep_a1["derived_rules"]["ruleset_sha256"]
            != rep_a0["derived_rules"]["ruleset_sha256"])

    # 段 2：B 书不受影响（仍在全局默认基线上，且 B 的文件从未被创建）
    sha_b1, rep_b1 = _run_book(tmp_path, "b1", book_vocab_path=pb, book_id=BOOK_B)
    assert sha_b1 == sha_b0, "A 书的停用泄漏到了 B 书的校正结果"
    assert rep_b1["derived_rules"]["book_excluded_applied"] == 0
    assert not pb.exists(), "B 书的清单文件不该被顺手创建"

    # 段 3：A 移出停用（界面同一数据层）→ 恢复基线
    store.set_book_excluded(PROBE_WORD, PROBE_VALUE, excluded=False)
    sha_a2, rep_a2 = _run_book(tmp_path, "a2", book_vocab_path=pa, book_id=BOOK_A)
    assert sha_a2 == sha_a0, "移出停用后没有回到全局默认基线"
    assert rep_a2["derived_rules"]["book_excluded_applied"] == 0
    assert (rep_a2["derived_rules"]["ruleset_sha256"]
            == rep_a0["derived_rules"]["ruleset_sha256"])
