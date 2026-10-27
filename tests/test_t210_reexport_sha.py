"""M2-T2.10 历史页「重新导出」的真实性（sha 必须与基线一致）。

不编造结果：这条用例**真的跑一次六阶段校正**（788 章），再只凭运行目录
重建导出源、还原成电子书，把 sha256 与这次运行的基线比对。约 20 秒。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG / "fixtext_import"))
sys.path.insert(0, str(PKG / "fixtext_error_center"))

EPUB = PKG / "tests" / "samples" / "book_paohuo.epub"
ENGINE = (PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src"
          / "bin" / "replace_by_go-linux-amd64")
RULES = PKG / "data" / "rules"


@pytest.mark.skipif(not EPUB.exists() or not ENGINE.exists(),
                    reason="缺少真实样书或引擎")
def test_reexport_after_restart_matches_baseline(tmp_path):
    from fixtext_worker import CorrectionJob
    import fixtext_export as fx

    run = tmp_path / "run-1"
    job = CorrectionJob(epub=EPUB, workdir=run,
                        rules_before=RULES / "before.json",
                        rules_after=RULES / "after.json",
                        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
                        title="炮火弧线")
    summary = job.run()
    assert summary["chapters"] == 788
    assert summary["quote_errors"] == 108
    assert summary["hits"] == 5100
    baseline = summary["restored_sha256"]
    assert baseline.startswith("717fdfce"), baseline

    # 重启场景：不传任何导入记录，只凭运行目录重建导出源
    src = fx.resolve_source_from_run(run, None, PKG / "pipeline")
    assert src.can_restore_epub, "有原书 + 章节包时应当能还原成电子书"
    outcome = fx.export_book(src, tmp_path / "out", fmt="epub",
                             baseline_sha256=baseline)
    assert outcome.main_file and Path(outcome.main_file).exists()
    assert outcome.sha256 == baseline, "重新导出的成品应与基线逐字节一致"
    assert outcome.sha_match is True
