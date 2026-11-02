"""M2-T2.10 历史页「重新导出」的真实性（sha 必须与基线一致）。

不编造结果：这条用例**真的跑一次六阶段校正**（公版样本整本），再只凭运行目录
重建导出源、还原成电子书，把 sha256 与这次运行的基线比对。

M5-OS.1：这里**不含任何写死的数字**。章数、引号问题数、命中数全部取自
本次运行自己的产物或 ``tests/samples/fixture_run_meta.json``（后者由
``tools/make_fixture_meta.py`` 在同一个样本上真实跑一次生成）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG / "fixtext_import"))
sys.path.insert(0, str(PKG / "fixtext_error_center"))

import _public_fixture as PF  # noqa: E402  M5-OS.1：公版 fixture 唯一来源

EPUB = PF.EPUB
sys.path.insert(0, str(PKG / "pipeline"))
from fixtext_pipeline.engine_selector import select_engine  # noqa: E402
_BIN = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
ENGINE = select_engine(_BIN) or (_BIN / "__no_platform_engine__")
RULES = PKG / "data" / "rules"


@pytest.mark.skipif(not EPUB.exists() or not ENGINE.exists(),
                    reason="缺少真实样书或引擎")
def test_reexport_after_restart_matches_baseline(tmp_path):
    """一次真跑六阶段校正，再只凭运行目录重建导出源并比对 sha256。

    M5-T5.1 口径更新（两处）：

    ① ``hits``：旧断言写死 5,100——那是 M5 分袋重构**之前**的 PHP 全量扁平
       口径（304,255 条一次性全插）。重构后替换阶段只跑「默认袋」那一轮，
       规则池由 ``main_bag_ids(DEFAULT_SELECTED_BAGS)`` 决定，本用例不传
       ``selected_bags``，因此走产品默认：

           DEFAULT_SELECTED_BAGS = (b1, custom, cjk, b3, ddd, old_style)
           main_bag_ids(...)     = normal + cjk_recover + t2s + ddd + old_style
                                 = 131,692 + 643 + 3,141 + 14,615 + 1,102
                                 = 151,193 条（旧口径 304,255 条的 49.7%）

       所以命中数一定会显著低于 5,100。这里**不抄实测值**，而是把断言写成
       「替换报告里记录的规则池 == 默认袋之和」＋「命中数随规则池规模同向、
       且落在默认袋可产生区间内」的推导式：规则池若被改回全量或漏袋，
       断言会直接指认到袋，而不是只报一个数字对不上。

    ② ``restored_sha256``：旧断言比对 ``717fdfce``——那是全量口径下的成品
       指纹。规则池变了，成品字节必然变（这是正确行为，修复报告 §2.4 也
       明确「与 PHP 全量逐字节对齐——不做」）。改成品指纹断言为「与本次
       运行自己的替换产物一致」，并用运行目录里的 report 做交叉核对。
    """
    from fixtext_worker import CorrectionJob
    import fixtext_export as fx
    from _m5_manifest import bag_counts
    from fixtext_pipeline.bags import DEFAULT_SELECTED_BAGS, main_bag_ids

    run = tmp_path / "run-1"
    job = CorrectionJob(epub=EPUB, workdir=run,
                        rules_before=RULES / "before.json",
                        rules_after=RULES / "after.json",
                        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
                        title=PF.TITLE)
    summary = job.run()

    # ---- ⓪ 章数与引号问题数：与「本次运行自己的产物」一致 ----------------
    # 旧写法把 788 / 108 写死；换样本之后抄一个新数字只是把毛病换个壳
    # （产品少跑一章，测试也跟着抄少一个数，就再也发现不了）。改为读这一轮
    # 自己落盘的报告，并与 fixture 的运行记录交叉核对：
    #   章数   ← 01_merge/merge_report.json 的 chapters（流水线自报）
    #   引号数 ← 04_quote 报告里的 events 条数 == 汇总里的 error_count
    merge = json.loads((run / "01_merge" / "merge_report.json").read_text("utf-8"))
    quote_sum = json.loads((run / "04_quote" / "quote_summary.json").read_text("utf-8"))
    events = json.loads(
        (run / "04_quote" / Path(quote_sum["report_json"]).name).read_text("utf-8")
    ).get("events") or []

    assert summary["chapters"] == merge["chapters"] == merge["spine_items"], (
        f"运行摘要章数 {summary['chapters']} ≠ 合并报告 "
        f"{merge['chapters']} / spine {merge['spine_items']}")
    assert summary["quote_errors"] == quote_sum["error_count"] == len(events), (
        f"运行摘要引号问题数 {summary['quote_errors']} ≠ 汇总 "
        f"{quote_sum['error_count']} ≠ 报告事件条数 {len(events)}")
    # 与 fixture 的运行记录同源同值：样本换了却有人忘了重跑元数据，这里会红
    assert summary["chapters"] == PF.chapters(), (
        f"本次运行章数 {summary['chapters']} ≠ fixture 记录 {PF.chapters()}")
    assert summary["quote_errors"] == PF.quote_errors(), (
        f"本次运行引号问题数 {summary['quote_errors']} ≠ fixture 记录 "
        f"{PF.quote_errors()}")

    # ---- ① 命中数的推导式口径 -------------------------------------------
    rep = json.loads((run / "03_replace" / "replace_report.json").read_text("utf-8"))
    derived = rep["derived_rules"]
    expect_bags = main_bag_ids(DEFAULT_SELECTED_BAGS)
    counts = bag_counts()

    assert derived["bag_ids"] == expect_bags, (
        f"替换阶段实际用袋 {derived['bag_ids']} ≠ 默认袋 {expect_bags}")
    assert derived["base_rules"] == sum(counts[b] for b in expect_bags), (
        f"规则池 {derived['base_rules']} ≠ 默认袋之和 "
        f"{sum(counts[b] for b in expect_bags)}")
    assert rep["rules"] == derived["base_rules"], (
        f"引擎载入 {rep['rules']} ≠ 规则池 {derived['base_rules']}")

    hits = summary["hits"]
    assert isinstance(hits, int) and hits > 0, f"命中数应为正整数：{hits!r}"
    # 命中数不可能超过规则池（一条规则最多贡献一次「有变化的替换」观测）
    assert hits <= derived["base_rules"], (
        f"命中数 {hits} 超过规则池 {derived['base_rules']}")
    # 少袋必少活：默认袋只占全量的一部分，命中数必然远低于「全量扁平」口径。
    # 这里不写「某次实测的具体数字」，而是守两条语义 + 一条同源核对：
    #   ① 命中数 ≤ 规则池（结构性上限）
    #   ② 命中数 ≤ 替换正文的字符数（一次替换至少动 1 个字符）
    #   ③ 与 fixture 运行记录一致（换了样本却忘了重跑元数据 → 这里红）
    assert hits <= rep["chars_out"], (
        f"命中数 {hits} 超过被替换正文字符数 {rep['chars_out']}")
    assert hits == PF.hits(), (
        f"本次运行命中数 {hits} ≠ fixture 记录 {PF.hits()}——"
        "样本或词库变了就要重跑 tools/make_fixture_meta.py")

    baseline = summary["restored_sha256"]
    assert baseline and len(baseline) == 64, baseline

    # ---- ② 成品指纹：与本次运行的替换产物交叉核对 -----------------------
    assert rep["changed"] is True, "这本书默认袋下应当有改动"
    assert summary["artifacts"]["after_text"] == rep["after_path"], (
        "运行摘要里的替换产物路径与替换报告不一致")

    # 重启场景：不传任何导入记录，只凭运行目录重建导出源
    src = fx.resolve_source_from_run(run, None, PKG / "pipeline")
    assert src.can_restore_epub, "有原书 + 章节包时应当能还原成电子书"
    outcome = fx.export_book(src, tmp_path / "out", fmt="epub",
                             baseline_sha256=baseline)
    assert outcome.main_file and Path(outcome.main_file).exists()
    assert outcome.sha256 == baseline, "重新导出的成品应与基线逐字节一致"
    assert outcome.sha_match is True
    # 导出侧自报的命中数与运行摘要同源同值（两处口径必须对得上）
    assert outcome.hits == hits, (
        f"导出统计命中 {outcome.hits} ≠ 运行摘要命中 {hits}")
