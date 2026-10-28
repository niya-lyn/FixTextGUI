"""M4-EX.3b 回归：各模块按书联动。

口径来源：任务卡三条要求 + 用户 2026-10-28 确认的数据划分
（校正记录 / 检查结果 / 导出 / 历史按书分开；通用词库全局共享；
本书专有词按书；设置全局）。

关键事实断言（不是"看起来对"）：
- ``build_run_context`` 的运行目录指向 ``runs/<书 id>`` —— 运行按书隔离，
  书架切换后下次校正作用于新书；
- 切换当前书时四个数据页（一键校正 / 检查 / 历史 / 导出）即时按书重挂载，
  B 书页面上不允许出现 A 书数据；没有记录的书走空状态；
- 导出成功写入书的 ``exports.json`` 与运行摘要的导出状态，
  书架「已导出」标识只由这份真实记录点亮。
"""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtext_ui"))

import main_window as mw                                    # noqa: E402

PKG_ROOT = mw.PKG_ROOT


# ------------------------------------------------------------------ 造数据

def _mk_book(ws: Path, book_id: str, title: str, suffix: str = "txt") -> Path:
    """在工作区里造一本"已导入"的书（结构与 importer 落盘一致）。"""
    d = ws / book_id
    (d / "original").mkdir(parents=True, exist_ok=True)
    (d / "book.txt").write_text(f"《{title}》正文内容。" * 30, encoding="utf-8")
    (d / "import.json").write_text(json.dumps({
        "book_id": book_id,
        "title": title,
        "author": "某作者",
        "source_suffix": suffix,
        "imported_at": "2026-10-28 09:00:00",
        "text_path": str(d / "book.txt"),
        "original_copy_path": str(d / "original" / f"book.{suffix}"),
    }, ensure_ascii=False), encoding="utf-8")
    (d / "original" / f"book.{suffix}").write_bytes(b"\0" * 1024)
    return d


def _mk_run(runs_root: Path, book_id: str, title: str, *, n_errors: int = 1) -> Path:
    """在 runs/<书 id>/ 下造一次"跑完了"的运行（含检查报告与可导出正文）。"""
    run = runs_root / book_id / f"run-{int(time.time() * 1000)}"
    (run / "report").mkdir(parents=True, exist_ok=True)
    (run / "04_quote").mkdir(parents=True, exist_ok=True)
    after = run / "03_replace" / "after.txt"
    after.parent.mkdir(parents=True, exist_ok=True)
    after.write_text(f"《{title}》校正后的正文。\n" * 20, encoding="utf-8")
    events = [{"line": i + 1, "char": 2, "msg": '直引号 " 应为 “'}
              for i in range(n_errors)]
    (run / "04_quote" / f"{title}.report.json").write_text(json.dumps(
        {"events": events, "errCount": n_errors}, ensure_ascii=False),
        encoding="utf-8")
    (run / "report" / "ui_run_summary.json").write_text(json.dumps({
        "book": title, "title": title, "author": "某作者",
        "started_at": int(time.time()) - 60, "finished_at": int(time.time()),
        "hits": n_errors, "chapters": 1, "quote_errors": n_errors,
        "restored_sha256": "", "source_epub": "",
        "workdir": str(run),
        "artifacts": {"after_text": str(after)},
    }, ensure_ascii=False), encoding="utf-8")
    return run


@pytest.fixture()
def two_books(tmp_path):
    """两本书 + 甲书的一次运行；结束后清掉包根 runs/ 下的测试书目录。"""
    ws = tmp_path / "workspace"
    a = _mk_book(ws, "ex3b_a", "甲书")
    b = _mk_book(ws, "ex3b_b", "乙书")
    runs_root = PKG_ROOT / "runs"
    run_a = _mk_run(runs_root, "ex3b_a", "甲书", n_errors=2)
    yield ws, a, b, run_a
    for book_id in ("ex3b_a", "ex3b_b"):
        shutil.rmtree(runs_root / book_id, ignore_errors=True)


# ------------------------------------------------------------ 运行上下文按书

def test_run_context_runs_root_is_per_book(two_books):
    """一键校正的运行目录按书隔离：runs/<书 id>，换书即换目录。"""
    ws, a, b, _ = two_books
    win = mw.MainWindow(workspace=ws)
    try:
        ctx_a = win.build_run_context(str(a / "book.txt"))
        ctx_b = win.build_run_context(str(b / "book.txt"))
        assert ctx_a and ctx_b, "两本书都要能建出真实上下文"
        assert ctx_a["runs_root"] == str(PKG_ROOT / "runs" / "ex3b_a")
        assert ctx_b["runs_root"] == str(PKG_ROOT / "runs" / "ex3b_b")
        assert ctx_a["runs_root"] != ctx_b["runs_root"]
    finally:
        win.deleteLater()


def test_switch_reloads_all_four_pages(qapp, two_books):
    """切换当前书：一键校正 / 检查 / 历史 / 导出四页即时按书重挂载。"""
    import fixtext_shelf as S

    ws, a, b, run_a = two_books
    S.set_current_book_id("ex3b_b")          # 启动落在乙书（没有运行记录）
    try:
        win = mw.MainWindow(workspace=ws)
        # 乙书没有记录：检查页空状态、历史页空、导出页挂的是乙书原文
        assert not win.check_module.has_data, "乙书没有记录，检查页必须空"
        assert win.history_module.tasks == [], "乙书没有记录，历史页必须空"
        assert win.history_module._runs_root == PKG_ROOT / "runs" / "ex3b_b"
        assert win.export_module.source and \
            win.export_module.source.title == "乙书", \
            "导出页必须挂乙书（没跑过校正就挂原文），不能是甲书"

        # 切到甲书（有运行记录）：四页全部换成甲书的数据
        win._on_current_book_changed(str(a / "book.txt"))
        assert win.oneclick_module.run_context["runs_root"] \
            == str(PKG_ROOT / "runs" / "ex3b_a"), "下次校正必须作用于甲书"
        assert win.check_module.has_data, "甲书有检查报告，检查页必须有数据"
        assert win.check_module.report["book"] == "甲书"
        assert [t["title"] for t in win.history_module.tasks] == ["甲书"]
        assert win.export_module.source and \
            win.export_module.source.text_path, "导出页要挂甲书最近校正产物"
        assert win.export_module.source.title == "甲书"
        assert win.export_module.source.corrected, "甲书有运行，导出的应是校正后正文"

        # 切回乙书：甲书的数据一个都不许留在页面上
        win._on_current_book_changed(str(b / "book.txt"))
        assert not win.check_module.has_data
        assert win.history_module.tasks == []
        assert win.history_module._runs_root == PKG_ROOT / "runs" / "ex3b_b"
        assert win.export_module.source and \
            win.export_module.source.title == "乙书"
        assert not win.export_module.source.corrected, \
            "乙书没跑过校正，导出页不许还挂着甲书的校正产物"
        assert win.oneclick_module.run_context["runs_root"] \
            == str(PKG_ROOT / "runs" / "ex3b_b")
        win.deleteLater()
    finally:
        S.clear_current_book_id()


def test_repeated_switch_keeps_data_correct(qapp, two_books):
    """A/B 连续多次来回切换：数据始终正确、无残留。"""
    import fixtext_shelf as S

    ws, a, b, _ = two_books
    try:
        win = mw.MainWindow(workspace=ws)
        for i in range(4):
            book, title, book_id = ((a, "甲书", "ex3b_a") if i % 2 == 0
                                    else (b, "乙书", "ex3b_b"))
            win._on_current_book_changed(str(book / "book.txt"))
            assert win.book_chip.name.full_text() == title
            assert win.oneclick_module.run_context["runs_root"] \
                == str(PKG_ROOT / "runs" / book_id)
            assert win.history_module._runs_root == PKG_ROOT / "runs" / book_id
            if book_id == "ex3b_a":
                assert win.check_module.report["book"] == "甲书"
                assert [t["title"] for t in win.history_module.tasks] == ["甲书"]
            else:
                assert not win.check_module.has_data
                assert win.history_module.tasks == []
        win.deleteLater()
    finally:
        S.clear_current_book_id()


# --------------------------------------------------------------- 已导出写点

def test_write_export_record_roundtrip(two_books):
    """导出记录写入方：键结构与 3a 只读方兼容，标识立刻可读。"""
    import fixtext_shelf as S

    ws, a, _, _ = two_books
    rec = S.write_export_record(a, fmt="txt", path="/tmp/out/x.txt",
                                sha256="ab12", hits=7)
    assert rec and rec["exported_at"], "写入方要返回带时间的完整记录"
    data = S.read_export_record(a)
    assert data["fmt"] == "txt" and data["path"] == "/tmp/out/x.txt"
    assert data["exported_sha256"] == "ab12" and data["hits"] == 7
    book = S.find_book(ws, "ex3b_a")
    assert book and book.exported_at == rec["exported_at"], \
        "书架数据层必须立刻读到刚写的导出状态"


def test_shelf_row_lights_exported_badge(qapp, two_books):
    """书架「已导出」标识随真实记录点亮（此前从未点亮过）。"""
    import fixtext_shelf as S

    ws, a, b, _ = two_books
    win = mw.MainWindow(workspace=ws)
    try:
        panel = win.import_module.shelf
        row_a = next(r for r in panel.rows if r.book.book_id == "ex3b_a")
        row_b = next(r for r in panel.rows if r.book.book_id == "ex3b_b")
        assert row_a.status.text() == "" and row_b.status.text() == ""
        S.write_export_record(a, fmt="txt", path="/tmp/out/a.txt")
        win.import_module.refresh_shelf()
        panel = win.import_module.shelf
        row_a = next(r for r in panel.rows if r.book.book_id == "ex3b_a")
        row_b = next(r for r in panel.rows if r.book.book_id == "ex3b_b")
        assert row_a.status.text() == "已导出", "导出过的书必须亮「已导出」"
        assert row_b.status.text() == "", "没导出过的书不许亮"
    finally:
        win.deleteLater()


def test_export_module_records_book_and_run(qapp, two_books):
    """导出页成功导出 → 书的 exports.json + 运行摘要都写上导出状态。"""
    from fixtext_export import ExportOutcome

    ws, a, _, run_a = two_books
    win = mw.MainWindow(workspace=ws)
    try:
        win._on_current_book_changed(str(a / "book.txt"))
        fired = []
        win.export_module.exportRecorded.connect(lambda: fired.append(1))
        out_dir = ws / "exports"
        out_dir.mkdir(exist_ok=True)
        main_file = out_dir / "甲书.txt"
        main_file.write_text("正文", encoding="utf-8")
        outcome = ExportOutcome(
            ok=True, fmt="txt", out_dir=str(out_dir), main_file=str(main_file),
            stats_text="", stats_csv="", hits=3, libs=["通用"],
            sha256="cd34" * 8)
        win.export_module._on_succeeded(outcome)
        assert fired == [1], "导出状态落盘后必须发出信号（主窗口据此刷书架）"
        import fixtext_shelf as S
        data = S.read_export_record(a)
        assert data and data["exported_at"] and data["path"] == str(main_file)
        assert data["exported_sha256"] == "cd34" * 8
        summary = json.loads(
            (run_a / "report" / "ui_run_summary.json").read_text(encoding="utf-8"))
        assert summary.get("exported_at") == data["exported_at"]
        assert summary.get("exported_sha256") == "cd34" * 8
    finally:
        win.deleteLater()


def test_history_reexport_records_book(qapp, two_books):
    """历史页重新导出成功 → 同样写入书的导出记录与该次运行的状态。"""
    import fixtext_shelf as S
    from fixtext_export import ExportOutcome

    ws, a, _, run_a = two_books
    win = mw.MainWindow(workspace=ws)
    try:
        win._on_current_book_changed(str(a / "book.txt"))
        assert win.history_module._export_ctx.get("book_dir") == str(a), \
            "历史页要拿到当前书的目录，重新导出才知道记到哪本书上"
        outcome = ExportOutcome(
            ok=True, fmt="txt", main_file="/tmp/out/again.txt",
            hits=5, sha256="ef56" * 8)
        win.history_module._record_export_outcome(
            {"run_dir": str(run_a)}, outcome)
        data = S.read_export_record(a)
        assert data and data["exported_at"] and data["path"] == "/tmp/out/again.txt"
        summary = json.loads(
            (run_a / "report" / "ui_run_summary.json").read_text(encoding="utf-8"))
        assert summary.get("exported_sha256") == "ef56" * 8
    finally:
        win.deleteLater()
