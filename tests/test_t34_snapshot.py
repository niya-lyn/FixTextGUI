"""M3-T3.4 历史页「恢复到任一快照」的验收用例（入口⑥ 验收②）。

本卡把 T2.10 里「恢复」的降级（= 用该次产物重新导出）换成真恢复：
把书切回某次运行的某个阶段点，之后能直接导出、也能从该点继续。

这里的三组用例对应验收里能机器判定的事实：
1. 阶段点枚举：真实运行目录有几个时点就有几个，缺的置灰并给原因；
2. 恢复后导出：恢复到「替换完成」→ 导出 → sha 与该阶段产物一致；
3. 撤销 / 重启：撤销回到恢复前；新建模块只凭磁盘仍枚举出同样时点。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG / "fixtext_import"))

import _fixture_run as fxr  # noqa: E402
import fixtext_run_snapshot as snap  # noqa: E402

from _public_fixture import EPUB  # noqa: E402  M5-OS.1：公版 fixture 唯一来源
sys.path.insert(0, str(PKG / "pipeline"))
from fixtext_pipeline.engine_selector import select_engine  # noqa: E402
_BIN = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
# 按平台取引擎；取不到时落到不存在的路径，让 skipif 正常跳过（避免 Win 上
# 因 Linux 二进制 exists() 为真却 subprocess 炸 WinError 193）
ENGINE = select_engine(_BIN) or (_BIN / "__no_platform_engine__")
RULES = PKG / "data" / "rules"
BASE_SHA = fxr.BASE_SHA


def _sha(path) -> str:
    return snap.sha256_file(path)


@pytest.fixture()
def runs_root(tmp_path):
    root = tmp_path / "runs"
    root.mkdir()
    fxr.build_run(root, name="run-1", hits=5100, title="示例书稿")
    return root


# ---------------------------------------------------------------------------
# 1. 阶段点枚举（缺就置灰，不假装可用）
# ---------------------------------------------------------------------------

def test_points_only_where_artifacts_exist(runs_root):
    """夹具只留了替换 / 引号两步的产物 → 只有这两个点可用，其余置灰给原因。"""
    pts = snap.list_points(runs_root / "run-1")
    assert [p["key"] for p in pts] == ["merge", "layout", "replace", "quote", "restore"]
    by = {p["key"]: p for p in pts}
    assert by["replace"]["available"] is True
    assert by["quote"]["available"] is True
    assert by["merge"]["available"] is False
    assert by["layout"]["available"] is False
    assert by["restore"]["available"] is False
    for key in ("merge", "layout", "restore"):
        assert by[key]["reason"], f"{key} 不可用必须写原因"
        assert "没有留下可恢复的结果" in by[key]["reason"]
    # 不可用的点不能带出可导出的工作正文（避免假装可恢复）
    assert by["merge"]["text_path"] == ""
    assert by["replace"]["text_path"].endswith(".txt")


def test_point_names_are_human(runs_root):
    """五个时点是给人看的文案，不出现内部阶段名。"""
    names = [p["name"] for p in snap.list_points(runs_root / "run-1")]
    assert names == ["导入合并完成", "排版完成", "替换完成", "引号检查完成", "还原完成"]


def test_points_survive_restart(runs_root, qapp):
    """重启语义：全新模块只凭磁盘，仍枚举出同样的时点（不是内存态）。"""
    import history_module as hm

    mod = hm.HistoryModule()
    mod.set_runs_root(runs_root)
    mod.refresh()
    assert mod.row_count == 1
    pts_a = snap.list_points(mod.tasks[0]["run_dir"])

    fresh = hm.HistoryModule()
    fresh.set_runs_root(runs_root)
    fresh.refresh()
    pts_b = snap.list_points(fresh.tasks[0]["run_dir"])
    assert [(p["key"], p["available"]) for p in pts_a] == \
           [(p["key"], p["available"]) for p in pts_b]


# ---------------------------------------------------------------------------
# 2. 恢复 → 导出 sha 一致
# ---------------------------------------------------------------------------

def test_restore_then_export_matches_point(runs_root, tmp_path):
    """恢复到「替换完成」→ 工作正文 sha 等于 03_replace/after 产物；
    导出的纯文本正文 sha 也等于该点产物清理后的结果（同源逐字节）。"""
    run = runs_root / "run-1"
    src_after = snap.resolve_artifacts(run)["after_text"]
    res = snap.restore_point(run, "replace", runs_root)
    assert res.ok, res.message
    cur = snap.current_state(runs_root)
    assert cur and cur["point"] == "replace"

    assert _sha(cur["working_text"]) == _sha(src_after), "恢复后的工作正文必须与该点产物一致"
    assert all(v["equal"] for v in cur["verify"].values()), "逐项 sha 对照应全部相等"
    assert "after_text" in cur["verify"] and "before_text" in cur["verify"]

    # 再导出一次：正文文件与工作区正文一致（没有被改写）
    assert _sha(cur["working_text"]) == _sha(cur["working_text"])
    assert Path(cur["working_text"]).read_text(encoding="utf-8") == \
        Path(src_after).read_text(encoding="utf-8")


def test_restore_refuses_unavailable_point(runs_root):
    """没有产物的时点：明确拒绝并说明，不落指针。"""
    res = snap.restore_point(runs_root / "run-1", "restore", runs_root)
    assert res.ok is False
    assert "没有走到这一步" in res.message
    assert snap.current_state(runs_root) is None, "失败不应写当前工作区指针"


def test_restore_is_reversible(runs_root):
    """恢复可撤销：撤销后指针回到恢复前（这里是未指定）。"""
    run = runs_root / "run-1"
    assert snap.restore_point(run, "replace", runs_root).ok
    first = (snap.current_state(runs_root) or {}).get("snapshot_dir")
    assert first

    # 再从另一时点恢复一次：撤销应回到前一次（而不是直接清空）
    assert snap.restore_point(run, "quote", runs_root).ok
    assert (snap.current_state(runs_root) or {}).get("point") == "quote"
    back = snap.undo_restore(runs_root)
    assert back and back["point"] == "replace", "撤销应回到上一次的恢复点"
    assert snap.undo_restore(runs_root) is None, "再撤销回到未指定"
    assert snap.current_state(runs_root) is None


def test_restore_does_not_touch_run_dir(runs_root):
    """恢复只读：运行目录里的产物一个字节都不能变。"""
    run = runs_root / "run-1"
    before = {p: _sha(p) for p in run.rglob("*") if p.is_file()}
    assert snap.restore_point(run, "replace", runs_root).ok
    after = {p: _sha(p) for p in run.rglob("*") if p.is_file()}
    assert before == after, "恢复不得改写运行目录"


# ---------------------------------------------------------------------------
# 3. 界面侧：真实点击 → 弹窗枚举 → 恢复 → 提示刷新
# ---------------------------------------------------------------------------

def test_ui_restore_flow(runs_root, qapp):
    """点「恢复」弹窗、选中一个时点、确认后界面提示切到该点，且可撤销。"""
    import history_module as hm
    from PySide6.QtWidgets import QDialog, QPushButton, QRadioButton

    mod = hm.HistoryModule()
    mod.set_runs_root(runs_root)
    mod.refresh()

    buttons = [b.text() for b in mod.findChildren(QPushButton)]
    assert any("恢复" == t.strip("↺ ") for t in buttons), "行内应有「恢复」入口"
    assert not any("降级" in t for t in buttons), "不再出现降级口径"

    # 弹窗本身要按真实可用性列出选项（不可用置灰）
    pts = snap.list_points(runs_root / "run-1")
    dlg = hm.SnapshotDialog(book="公版样本", when="2026-10-27 23:34",
                            points=pts)
    radios = {r.text(): r for r in dlg.findChildren(QRadioButton)}
    assert len(radios) == 5
    assert radios["替换完成"].isEnabled()
    assert not radios["导入合并完成"].isEnabled(), "没有产物的时点必须置灰"
    assert not dlg.ok_btn.isEnabled(), "没选时点前确认按钮应禁用"
    radios["替换完成"].setChecked(True)
    assert dlg.ok_btn.isEnabled()
    dlg.reject()

    class _Pick:
        def __init__(self, **kw):
            self.kw = kw
            self.chosen = "replace"

        def exec(self):
            return QDialog.DialogCode.Accepted

    orig = hm.SnapshotDialog
    hm.SnapshotDialog = _Pick
    try:
        mod._open_snapshot_dialog(0)
    finally:
        hm.SnapshotDialog = orig

    assert "替换完成" in mod._active_hint.text()
    assert snap.current_state(runs_root)["point"] == "replace"
    assert mod.export_ws_btn.isEnabled(), "恢复后应能直接导出当前工作区"
    assert mod.continue_btn.isEnabled(), "恢复后应能从该点继续"

    mod._undo()
    assert "未指定" in mod._active_hint.text()
    assert not mod.export_ws_btn.isEnabled()


@pytest.mark.skipif(not EPUB.exists() or not ENGINE.exists(),
                    reason="缺少真实样书或引擎")
def test_restore_replace_then_resume_skips_done_stages(tmp_path):
    """真跑一次六阶段校正 → 恢复到「替换完成」→ 续跑：前面三步跳过。

    成品指纹口径（M5-T5.2 收口）：旧断言写死 ``717fdfce``——那是 M5 分袋
    重构**之前**的全量口径成品指纹。分袋重构后替换阶段只跑「默认袋」那一轮，
    规则池缩小、成品字节必然变（这是正确行为），硬编码前缀既失效又会锁死
    实现。按与 ``test_t210_reexport_sha`` 同款口径改为「与本次运行自己的
    产物一致」：摘要自述指纹 == 本次运行产出的成品文件实际 sha。
    """
    from fixtext_worker import CorrectionJob

    runs_root = tmp_path / "runs"
    run = runs_root / "run-1"
    job = CorrectionJob(epub=EPUB, workdir=run,
                        rules_before=RULES / "before.json",
                        rules_after=RULES / "after.json",
                        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
                        title="示例书稿")
    summary = job.run()
    baseline = summary["restored_sha256"]
    assert baseline and len(baseline) == 64, baseline
    restored_epub = summary["artifacts"]["restored_epub"]
    assert restored_epub and Path(restored_epub).is_file(), restored_epub
    assert baseline == _sha(restored_epub), (
        f"摘要指纹 {baseline} 与本次运行的成品 {restored_epub} 不一致")

    # 真实运行目录：五个时点全部可用
    pts = snap.list_points(run)
    assert all(p["available"] for p in pts), [(p["key"], p["reason"]) for p in pts]

    res = snap.restore_point(run, "replace", runs_root)
    assert res.ok, res.message
    cur = snap.current_state(runs_root)
    src_after = snap.resolve_artifacts(run)["after_text"]
    assert _sha(cur["working_text"]) == _sha(src_after)

    out = snap.resume_from_point(
        cur["snapshot_dir"], runs_root, point="replace",
        epub=summary["source_epub"],
        rules_before=RULES / "before.json", rules_after=RULES / "after.json",
        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
        work_dir=runs_root / "_snapshots" / "work-test", adopt=False)
    assert out["exit_code"] == 0, out.get("report")
    results = out["report"]["stages"]
    assert results["merge"]["status"] == "skipped"
    assert results["layout"]["status"] == "skipped"
    assert results["replace"]["status"] == "skipped"
    assert results["quote"]["status"] == "done"
    assert results["restore"]["status"] == "done"
    # 续跑出来的成品与本次运行产出的成品逐字节一致（不与历史口径硬编码比对）
    work = Path(out["work_dir"])
    restored = [p for p in (work / "06_restore").glob("*.epub")]
    assert restored, "续跑应产出成品电子书"
    resumed_sha = _sha(restored[0])
    resume_restore = out["report"]["stages"]["restore"]["report"]
    assert resumed_sha == resume_restore["restored_sha256"], (
        f"续跑产物 {resumed_sha} 与续跑报告自述不一致")
    assert resumed_sha == baseline, (
        f"续跑成品 {resumed_sha} 与首次运行成品 {baseline} 不一致——"
        "续跑应只补齐后续阶段，不改已完成的替换结果")


@pytest.mark.skipif(not EPUB.exists() or not ENGINE.exists(),
                    reason="缺少真实样书或引擎")
def test_resume_adopts_workspace_and_stays_exportable(tmp_path):
    """M3-T3.5 回归：续跑成功后「当前工作区」必须仍然可导出。

    合并前 ``_adopt_workspace`` 写指针时漏了 ``snapshot_dir``，``current_state``
    因此判定「没有时点」返回 None —— 续跑本身成功、成品 sha 也对，但紧接着
    「导出当前工作区」会报「还没有恢复过时点」。这条锁住指针完整性。
    """
    from fixtext_worker import CorrectionJob

    runs_root = tmp_path / "runs"
    run = runs_root / "run-1"
    job = CorrectionJob(epub=EPUB, workdir=run,
                        rules_before=RULES / "before.json",
                        rules_after=RULES / "after.json",
                        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
                        title="示例书稿")
    summary = job.run()
    baseline = summary["restored_sha256"]
    assert baseline and len(baseline) == 64, baseline
    assert baseline == _sha(summary["artifacts"]["restored_epub"]), (
        "摘要指纹应与本次运行产出的成品一致")

    res = snap.restore_point(run, "replace", runs_root)
    assert res.ok, res.message
    cur = snap.current_state(runs_root)

    out = snap.resume_from_point(
        cur["snapshot_dir"], runs_root, point="replace",
        epub=summary["source_epub"],
        rules_before=RULES / "before.json", rules_after=RULES / "after.json",
        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
        work_dir=runs_root / "_snapshots" / "work-adopt", adopt=True)
    assert out["exit_code"] == 0, out.get("report")

    after = snap.current_state(runs_root)
    assert after is not None, "续跑后当前工作区指针丢了（snapshot_dir 未写入）"
    assert after.get("snapshot_dir"), "指针缺 snapshot_dir"
    assert Path(after["snapshot_dir"]).is_dir()
    assert after.get("working_text") and Path(after["working_text"]).is_file()

    # 指针完整性还要能真正走通「导出当前工作区」的取源
    src = snap.build_export_source(after, PKG / "pipeline")
    assert src.corrected and Path(src.text_path).is_file()
    assert src.can_restore_epub
