"""M2-T2.10 历史页磁盘持久化（入口⑥）。

验收点：历史一律从 ``runs/run-*/report/ui_run_summary.json`` 扫出来，
所以**重启进程后记录仍然在**；页面不持有任何会话内假数据；
「重新导出」走真实导出执行层；「恢复」在 M3-T3.4 换成了真快照恢复
（阶段级时点，见 ``test_t34_snapshot.py``），这里只守 T2.10 那几条。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PKG / "fixtext_ui"))

import _fixture_run as fxr  # noqa: E402
import fixtext_history as histdata  # noqa: E402


@pytest.fixture()
def runs_root(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    fxr.build_run(root, name="run-1", hits=5100, title="炮火弧线")
    fxr.build_run(root, name="run-2", hits=356, title="旧巷杂记")
    return root


def test_scan_builds_records_from_disk(runs_root):
    """两个运行目录 → 两条记录，书名 / 命中数来自磁盘摘要。"""
    recs = histdata.scan_runs(runs_root)
    assert len(recs) == 2
    books = sorted(r["book"] for r in recs)
    assert books == ["《旧巷杂记》", "《炮火弧线》"]
    r1 = histdata.find_by_run_dir(recs, str(runs_root / "run-1"))
    assert r1 is not None
    assert r1["hits"] == 5100
    assert r1["status"] == "ok"
    assert r1["sha256"] == fxr.BASE_SHA
    assert Path(r1["run_dir"]).is_dir()


def test_history_survives_restart(runs_root, qapp):
    """模拟重启：全新的界面实例、没有任何内存态，仍能扫出同样记录。"""
    import history_module as hm

    first = hm.HistoryModule()
    first.set_runs_root(runs_root)
    first.refresh()
    assert first.row_count == 2

    # 新实例 = 重启后的进程：没传过任何数据，只给了运行目录根
    second = hm.HistoryModule()
    second.set_runs_root(runs_root)
    second.refresh()
    assert second.row_count == 2, "重启后应重新扫出全部历史"
    assert [t["run_dir"] for t in second.tasks] == [t["run_dir"] for t in first.tasks]
    assert {t["hits"] for t in second.tasks} == {5100, 356}


def test_empty_history_gives_human_hint(tmp_path, qapp):
    """空目录：人话引导，不出现任何假记录。"""
    import history_module as hm
    from PySide6.QtWidgets import QLabel

    empty = tmp_path / "runs"
    empty.mkdir()
    mod = hm.HistoryModule()
    mod.set_runs_root(empty)
    mod.refresh()
    assert mod.row_count == 0
    texts = [l.text() for l in mod.findChildren(QLabel)]
    # M4-EX.2b：空状态换成原型 v3 §4 统一形态（标题 + 引导文案 + 双按钮）
    assert any("还没有校正历史" in t for t in texts), "空状态要给人话引导"
    assert any("完成一次校正后" in t for t in texts), "空状态要说明怎么走出空状态"
    # 空状态把任务表与快照面板收起，只留引导
    assert not mod._task_w.isVisibleTo(mod), "无任务时任务表应收起"
    assert not mod._snap_w.isVisibleTo(mod), "无任务时快照面板应收起"
    assert mod.empty_state.isVisibleTo(mod), "无任务时显示统一空状态"
    # 旧演示数据里的书名一个都不能出现
    for fake in ("星河彼端", "旧巷杂记", "灯下漫笔"):
        assert not any(fake in t for t in texts), f"不得残留假数据：{fake}"


def test_add_task_dedups_by_run_dir(runs_root, qapp):
    """同一运行目录重复写入只留一条（按 run_dir 去重）。"""
    import history_module as hm

    mod = hm.HistoryModule()
    mod.set_runs_root(runs_root)
    mod.refresh()
    before = mod.row_count
    rec = dict(mod.tasks[0])
    mod.add_task(rec)
    assert mod.row_count == before, "同一运行目录不应重复成两行"
    rec2 = dict(rec)
    rec2["run_dir"] = str(runs_root / "run-3")
    mod.add_task(rec2)
    assert mod.row_count == before + 1


def test_reexport_is_wired_to_real_export_layer(runs_root, qapp):
    """历史页的导出 / 恢复入口都接真实执行层（没有假动作）。"""
    import history_module as hm
    from PySide6.QtWidgets import QPushButton

    mod = hm.HistoryModule()
    mod.set_runs_root(runs_root)
    mod.refresh()
    assert not hasattr(mod, "_reexport"), "假动作 _reexport 必须已删除"
    for name in ("_run_export", "_do_export", "_confirm_restore",
                 "_open_snapshot_dialog", "_apply_restore"):
        assert hasattr(mod, name), f"应存在真实执行路径：{name}"
    texts = [b.text() for b in mod.findChildren(QPushButton)]
    assert any("重新导出" in t for t in texts), "行内动作应明说「重新导出」"
    assert any(t.strip("↺ ") == "恢复" for t in texts), "行内应有「恢复」入口"
    # 「重新导出」确认后直接进真实导出，而不是只弹个提示
    # 确认框是模态 exec()，无头环境下必须打桩，否则自动化会卡死。
    class _FakeConfirm:
        def __init__(self, **kw):
            self.kw = kw

        def exec(self):
            from PySide6.QtWidgets import QDialog
            return QDialog.DialogCode.Accepted

    orig = hm.ConfirmDialog
    hm.ConfirmDialog = _FakeConfirm
    try:
        calls = []
        mod._run_export = lambda t: calls.append(t.get("run_dir"))
        mod._confirm_restore(0)
    finally:
        hm.ConfirmDialog = orig
    assert calls == [mod.tasks[0]["run_dir"]], "确认后应真的走导出执行层"
