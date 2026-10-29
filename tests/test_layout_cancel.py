"""P1-7：排版阶段在章节边界响应 cancel_check。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "pipeline", PKG / "pipeline" / "vendor", PKG / "fixtext_ui"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

EPUB = PKG / "tests" / "samples" / "book_paohuo.epub"
RULES = PKG / "data" / "rules"


@pytest.mark.skipif(not EPUB.is_file(), reason="缺少样本 EPUB")
def test_layout_raises_stage_cancelled_at_chapter_boundary(tmp_path):
    """cancel_check 在第 3 章开始前返回 True → StageCancelled，且未写完 layout 产物。"""
    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.logsetup import StageLogger
    from fixtext_pipeline.stages import StageCancelled
    from fixtext_pipeline.stages.layout import LayoutStage
    from fixtext_pipeline.stages.merge import MergeStage

    work = tmp_path / "run"
    cfg = PipelineConfig(
        epub=EPUB,
        workdir=work,
        rules_before=RULES / "before.json",
        rules_after=RULES / "after.json",
        engine_path=tmp_path / "no-engine",
        stages=("merge", "layout"),
        resume=False,
        force=True,
    )
    work.mkdir(parents=True)
    cfg.paths.logs.mkdir(parents=True, exist_ok=True)
    cfg.stage_dir("merge").mkdir(parents=True, exist_ok=True)
    cfg.stage_dir("layout").mkdir(parents=True, exist_ok=True)

    merge_log = StageLogger(cfg.paths.stage_log("merge"), echo=False)
    try:
        MergeStage(cfg, merge_log).run()
    finally:
        merge_log.close()

    calls = {"n": 0}

    def cancel_check() -> bool:
        calls["n"] += 1
        # 前两章放行（calls=1,2），第三章开始时取消（calls=3）
        return calls["n"] > 2

    cfg.cancel_check = cancel_check
    layout_log = StageLogger(cfg.paths.stage_log("layout"), echo=False)
    try:
        with pytest.raises(StageCancelled, match="章节边界"):
            LayoutStage(cfg, layout_log).run()
    finally:
        layout_log.close()

    assert calls["n"] == 3
    # 取消后不应留下完整排版产物（run 中途抛错，未写到 outputs）
    assert not cfg.layout_text().is_file()


@pytest.mark.skipif(not EPUB.is_file(), reason="缺少样本 EPUB")
def test_correction_job_layout_cancel_cleans_workdir(tmp_path):
    """CorrectionJob 注入 cancel_check：排版中途取消 → CorrectionCancelled + 删 workdir。"""
    from fixtext_pipeline.engine_selector import select_engine
    from fixtext_worker import CorrectionCancelled, CorrectionJob, HUMAN_STAGES

    bin_dir = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
    engine = select_engine(bin_dir)
    if engine is None:
        pytest.skip("本平台无替换引擎")

    work = tmp_path / "job-run"
    job = CorrectionJob(
        epub=EPUB,
        workdir=work,
        rules_before=RULES / "before.json",
        rules_after=RULES / "after.json",
        engine_path=engine,
        pipeline_root=PKG / "pipeline",
        title="cancel-test",
    )

    layout_idx = next(i for i, s in enumerate(HUMAN_STAGES) if s["key"] == "layout")
    seen_layout = {"started": False}

    def on_started(i: int) -> None:
        if i == layout_idx:
            seen_layout["started"] = True
            # 排版一开始就请求取消；章循环会在第 1 章开始前或稍后命中
            job.request_cancel()

    job.set_stage_callbacks(on_started, None)

    with pytest.raises(CorrectionCancelled):
        job.run()

    assert seen_layout["started"]
    assert not work.exists()
