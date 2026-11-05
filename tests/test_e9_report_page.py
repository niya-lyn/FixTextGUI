"""V1.1-E9 · 报告界面呈现的验收测试。

三层证据：

1. **装配层（不依赖 Qt）**：真实 fixture（《炮火弧线》788 章真产物）装出来的
   视图，数字必须与 E8 验收逐项一致；缺字段时显示「报告里没有写」而不是 0；
   命中数与明细合计对不上时两个数都摆出来。
2. **页面层（离屏）**：四种状态（有数据 / 未校正 / 空态 / 读不出）各自的可见
   分支；逐条清单、搜索、词库表、诚实缺口说明真的渲染出来。
3. **路由层**：左轨仍是 6 项；报告页按平级路由挂入；``_open_report`` 真能切页。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "report"

import fixtext_report_present as rp


def _real_csv() -> Path:
    return FIX / "炮火弧线替换统计.csv"


# ---------------------------------------------------------------------------
# 1) 装配层：真实报告 → 视图（数字与 E8 验收逐项对上）
# ---------------------------------------------------------------------------

def test_present_real_csv_numbers():
    v = rp.load_report_file(_real_csv())
    assert v.state == rp.STATE_READY
    assert v.ok_to_show is True
    assert v.title == "炮火弧线"
    assert v.hits == 2638
    assert v.detail_rows == 2477
    assert v.detail_total == 2638
    assert v.hits_consistent is True
    assert v.library_count == 2
    assert v.applied_total == 151192
    assert len(v.rows) == 2477
    # 排序：次数从多到少
    counts = [r.count for r in v.rows]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 10
    # 占比只在实际总数存在时给
    assert v.rows[0].share_text.endswith("%")


def test_present_real_txt_same_numbers():
    v = rp.load_report_file(FIX / "炮火弧线替换统计.txt")
    assert v.state == rp.STATE_READY
    assert v.hits == 2638
    assert v.detail_rows == 2477
    assert v.detail_total == 2638
    assert v.fmt_label == "文本"


def test_present_kpis_and_consistency():
    v = rp.load_report_file(_real_csv())
    labels = [(k.label, k.value) for k in v.kpis]
    assert labels == [
        ("替换命中", "2638"),
        ("明细条数", "2477"),
        ("涉及词库", "2 套"),
        ("应用规则合计", "151192 条"),
    ]
    assert "一致" in v.consistency_note
    # 诚实缺口：没有按词库拆命中数 → 有说明，且词库行不带编造的命中数
    assert v.library_hits_note
    assert all("命中" not in (lib.numbers_text or "") or "规则" in lib.numbers_text
               for lib in v.libraries)
    applied = {lib.name: lib.applied_rules for lib in v.libraries}
    assert applied["通用校对词库"] == 151192


def test_present_uncorrected_fixture():
    v = rp.load_report_file(FIX / "炮火弧线替换统计_未校正.csv")
    assert v.state == rp.STATE_UNCORRECTED
    # 未校正是一份诚实的报告（0 是真 0），但正文没有可展开的内容，
    # 呈现层用空态卡片 + 解释；命中数原样保留 0，绝不改写成别的
    assert v.ok_to_show is False
    assert "没有跑过校正" in v.empty_desc
    assert v.hits == 0
    assert v.rows == []
    assert v.applied_total is None


def test_present_unreadable_missing_file(tmp_path):
    v = rp.load_report_file(tmp_path / "不存在.csv")
    assert v.state == rp.STATE_UNREADABLE
    assert v.ok_to_show is False
    assert v.issues and v.issues[0].is_warning
    assert v.empty_desc


def test_present_empty_view():
    v = rp.empty_view("还没有书")
    assert v.state == rp.STATE_EMPTY
    assert v.ok_to_show is False


def test_present_dir_lookup():
    v = rp.load_report_dir(FIX)
    assert v.state == rp.STATE_READY
    assert v.hits == 2638
    # 目录里没有报告 → 读不出态 + 人话原因，不抛异常
    v2 = rp.load_report_dir(FIX / "不存在目录")
    assert v2.state == rp.STATE_UNREADABLE


# ---------------------------------------------------------------------------
# 2) 装配层：缺字段 / 对不上容错（不用 0 顶替）
# ---------------------------------------------------------------------------

def _write_csv(path: Path, body: str) -> Path:
    path.write_text("\ufeff" + body, encoding="utf-8")
    return path


def test_present_missing_hits_field_never_zero(tmp_path):
    # 报告没写「命中数」这一行：合计必须是「报告里没有写」，绝不能是 0
    p = _write_csv(tmp_path / "缺字段替换统计.csv",
                   "项目,值\n书名,测试书\n生成时间,2026-01-01 00:00:00\n\n"
                   "改前,改后,替换次数\n好的,好地,3\n"
                   )
    v = rp.load_report_file(p)
    assert v.state == rp.STATE_READY
    assert v.hits is None
    hits_kpi = next(k for k in v.kpis if k.key == "hits")
    assert hits_kpi.value == rp.MISSING
    assert hits_kpi.value != "0"
    assert hits_kpi.note
    # 明细合计仍然来自明细本身
    assert v.detail_total == 3
    assert "没有写" in v.consistency_note or v.consistency_note == ""


def test_present_inconsistent_counts_shows_both(tmp_path):
    # 命中数写 9，明细合计是 3 → 两个数都摆出来，写明差多少
    p = _write_csv(tmp_path / "对不上替换统计.csv",
                   "项目,值\n书名,测试书\n命中数,9\n\n"
                   "改前,改后,替换次数\n好的,好地,3\n")
    v = rp.load_report_file(p)
    assert v.hits_consistent is False
    assert "9" in v.consistency_note and "3" in v.consistency_note
    assert v.hits == 9 and v.detail_total == 3


def test_present_report_files_for_book(tmp_path):
    root = tmp_path / "导出"
    root.mkdir()
    (root / "测试书替换统计.txt").write_text("项目,值\n书名,测试书\n", encoding="utf-8")
    (root / "测试书替换统计.csv").write_text(
        "\ufeff项目,值\n书名,测试书\n", encoding="utf-8")
    files = rp.report_files_for("测试书", roots=[root])
    assert len(files) == 2
    assert files[0].suffix == ".csv"      # 表格优先
    assert rp.report_files_for("没有的书", roots=[root]) == []
    # 按书名取最近一份 → 表格那份
    v = rp.latest_report_view("测试书", roots=[root])
    assert v.fmt_label == "表格"


# ---------------------------------------------------------------------------
# 3) 页面层（离屏）：四态可见分支 + 渲染内容
# ---------------------------------------------------------------------------

def test_page_renders_ready(qt_app):
    from report_module import ReportModule
    w = ReportModule()
    w.set_context(book_name="炮火弧线")
    w.load_file(_real_csv())
    assert w.view.state == rp.STATE_READY
    assert w._body.isHidden() is False
    assert w.empty_state.isHidden() is True
    assert w.rows_table.rowCount() == 2477
    assert w.lib_table.rowCount() == 2
    assert w.kpi_row.count() == 4
    # 概况数字在控件文本里真的出现
    texts = " ".join(l.text() for l in w._body.findChildren(
        __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert "2638" in texts and "2477" in texts and "151192" in texts
    # 诚实缺口说明可见
    assert w.lib_note.text().strip()


def test_page_search_filters_rows(qt_app):
    from report_module import ReportModule
    w = ReportModule()
    w.load_file(_real_csv())
    w._on_search("的说")
    assert 0 < w.rows_table.rowCount() < 2477
    assert "搜到" in w.search_pill.text()
    w._on_search("")
    assert w.rows_table.rowCount() == 2477


@pytest.mark.parametrize("view_factory,expected_state", [
    (lambda: rp.load_report_file(FIX / "炮火弧线替换统计_未校正.csv"),
     rp.STATE_UNCORRECTED),
    (lambda: rp.empty_view("还没有"), rp.STATE_EMPTY),
    (lambda: rp.load_report_file(FIX / "不存在文件.csv"), rp.STATE_UNREADABLE),
])
def test_page_empty_states(qt_app, view_factory, expected_state):
    from report_module import ReportModule
    w = ReportModule()
    w.show_view(view_factory())
    assert w.view.state == expected_state
    assert w._body.isHidden() is True
    assert w.empty_state.isHidden() is False
    assert w.status.text().strip()


def test_page_uncorrected_explains_zero(qt_app):
    from report_module import ReportModule
    w = ReportModule()
    w.show_view(rp.load_report_file(FIX / "炮火弧线替换统计_未校正.csv"))
    # 页面上明说「0 是报告写的 0，不是读取失败」
    texts = " ".join(l.text() for l in w.findChildren(
        __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel))
    assert "没有跑过校正" in texts


def test_page_loaded_signal(qt_app):
    from report_module import ReportModule
    w = ReportModule()
    got = []
    w.loaded.connect(lambda v: got.append(v))
    w.load_file(_real_csv())
    assert got and got[0].hits == 2638


def test_page_no_jargon_visible_texts(qt_app):
    """页面可见文本零内部词（禁用词口径与全包 lint 一致）。"""
    from report_module import ReportModule
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "_no_jargon_words", Path(__file__).parent / "test_no_jargon.py")
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    FORBIDDEN = _mod.FORBIDDEN
    w = ReportModule()
    w.load_file(_real_csv())
    texts = []
    for lab in w.findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel):
        texts.append(lab.text())
        texts.append(lab.toolTip() or "")
    for btn in w.findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QPushButton"]).QPushButton):
        texts.append(btn.text())
        texts.append(btn.toolTip() or "")
    blob = "\n".join(t for t in texts if t)
    bad = [w0 for w0 in FORBIDDEN if w0 in blob.lower()]
    assert not bad, f"露出内部词：{bad}"


# ---------------------------------------------------------------------------
# 4) 路由层：左轨仍是 6 项；报告页可达
# ---------------------------------------------------------------------------

@pytest.fixture()
def main_win(qt_app, tmp_path):
    """构建主窗（首跑向导已看过，设置指到临时文件）。"""
    import fixtext_settings as app_settings
    os.environ["FIXTEXT_SETTINGS_FILE"] = str(tmp_path / "settings.ini")
    import main_window as M
    import fixtext_tokens as T
    win = M.MainWindow()
    yield win, T
    win.deleteLater()


def test_rail_stays_six_and_report_page_mounted(main_win):
    win, T = main_win
    assert len(win.rail_items) == 6
    assert sorted(win.rail_items) == [
        "check", "export", "history", "import", "oneclick", "vocab"]
    assert T.REPORT_KEY in win.pages
    assert win.page(T.REPORT_KEY) is win.report_module


def test_open_report_navigates(main_win):
    win, T = main_win
    win._open_report(book_name="没有导出过的书")
    assert win.current_key == T.REPORT_KEY
    assert win.where.text().startswith("📄")
    # 没有报告时落在空态，且不给任何数字
    assert win.report_module.view.ok_to_show is False


def test_oneclick_goto_report_signal(main_win):
    win, T = main_win
    mod = win.oneclick_module
    assert hasattr(mod, "gotoReport")
    got = []
    mod.gotoReport.connect(lambda rd: got.append(rd))
    mod._summary = {"workdir": ""}
    mod._goto_export_report()
    assert got == [""]
    assert win.current_key == T.REPORT_KEY


def test_compare_report_button_emits_run_dir(qt_app, main_win):
    win, T = main_win
    mod = win.compare_module
    assert hasattr(mod, "reportRequested")
    got = []
    mod.reportRequested.connect(lambda rd: got.append(rd))
    mod.open_run(str(ROOT))
    assert got == []                      # 打开时不发，点按钮才发
    mod._run_dir = "/tmp/某次运行"
    mod._report_btn.setEnabled(True)
    mod._report_btn.click()
    assert got == ["/tmp/某次运行"]
    assert win.current_key == T.REPORT_KEY



def test_export_result_card_has_report_button(qt_app, tmp_path):
    """导出结果卡：替换统计文件真实存在时给「查看替换报告」入口。"""
    from export_module import ExportModule
    from fixtext_export import ExportOutcome
    stats = tmp_path / "测试书替换统计.csv"
    stats.write_text("\ufeff项目,值\n书名,测试书\n", encoding="utf-8")
    main = tmp_path / "测试书.txt"
    main.write_text("正文", encoding="utf-8")
    mod = ExportModule()
    got = []
    mod.reportRequested.connect(lambda p: got.append(p))
    outcome = ExportOutcome(ok=True, fmt="txt", out_dir=str(tmp_path),
                            main_file=str(main), stats_text="",
                            stats_csv=str(stats), hits=3, libs=["通用校对词库"])
    mod._render_result(outcome)
    from PySide6.QtWidgets import QPushButton
    btns = [b for b in mod.findChildren(QPushButton)
            if "查看替换报告" in b.text()]
    assert len(btns) == 1
    btns[0].click()
    assert got == [str(stats)]
    # 反例：统计文件不存在时不给按钮（不指向一个读不出来的文件）
    outcome2 = ExportOutcome(ok=True, fmt="txt", out_dir=str(tmp_path),
                             main_file=str(main), stats_text="",
                             stats_csv=str(tmp_path / "没有.csv"),
                             hits=3, libs=[])
    mod._render_result(outcome2)
    qt_app.processEvents()   # 让 deleteLater 真正清掉上一轮按钮
    btns2 = [b for b in mod.findChildren(QPushButton)
             if "查看替换报告" in b.text()]
    assert btns2 == []
