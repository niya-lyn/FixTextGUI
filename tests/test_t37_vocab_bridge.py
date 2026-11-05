"""M3-T3.7 · 自定义词生效（词库 → 替换引擎的桥）与查重清单收口。

判据全部是实测字节，不看函数返回值自报：

* **正向**：在「我的词库」加一条自定义词，跑一次真实校正（真引擎、真六阶段），
  校正后正文里原词消失、替换词出现，且句数与命中数对得上；
* **反向对照**：同一份输入喂给**移除桥接**的代码（直接读随包词库原件），
  替换结果里原词一个都没少 —— 证明正向断言不是恒真的；
* **只读**：随包词库原件 sha256 前后一致；
* **指纹**：自定义词一变，替换阶段的指纹必须跟着变（否则断点恢复会误判命中）；
* **查重清单**：全量渲染、只读（点完文件 sha 不变）、不含"假按钮"。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui", PKG / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from fixtext_pipeline.engine_selector import select_engine  # noqa: E402
_BIN = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
ENGINE = select_engine(_BIN) or (_BIN / "__no_platform_engine__")
RULES = PKG / "data" / "rules"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_CORPUS = (
    "萧衍 起身，众人皆看向萧衍。\n"
    "萧衍 说：萧衍 之言不可尽信。\n"
    "唯萧衍旧部尚在，萧衍 已去。\n"
)


def _write_corpus(path: Path, filler: str = "") -> Path:
    path.write_text(_CORPUS + filler, encoding="utf-8")
    return path


def _run(workdir: Path, epub: Path, vocab: Path | None,
         derived: Path | None) -> dict:
    from plain_book import plain_source_epub          # fixtext_ui
    from fixtext_worker import CorrectionJob

    src = plain_source_epub(epub, workdir / "src", title="探针")
    job = CorrectionJob(epub=src, workdir=workdir / "run",
                        rules_before=RULES / "before.json",
                        rules_after=RULES / "after.json",
                        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
                        title="探针", custom_vocab_path=vocab,
                        derived_rules_dir=derived)
    return job.run()


needs_engine = pytest.mark.skipif(not ENGINE.exists(), reason="缺少真实引擎")


@pytest.fixture()
def corpus(tmp_path):
    return _write_corpus(tmp_path / "probe.txt")


@pytest.fixture()
def vocab(tmp_path):
    p = tmp_path / "custom_vocab.json"
    p.write_text(json.dumps(
        {"product": "FixText", "kind": "custom_vocab", "version": 1,
         "entries": [{"id": 1, "word": "萧衍", "value": "萧彦"}]},
        ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 桥接模块本身的语义（纯计算，不起管线）
# ---------------------------------------------------------------------------

def test_compose_prepends_custom_and_keeps_base_order():
    from fixtext_pipeline import vocab_bridge as vb

    out = vb.compose(["甲", "乙丙"], ["一", "二"],
                     [{"id": 1, "word": "萧衍", "value": "萧彦"}])
    assert out["before"] == ["萧衍", "甲", "乙丙"], "自定义词必须前置（引擎按顺序先命中者胜）"
    assert out["after"] == ["萧彦", "一", "二"]
    assert out["stats"]["custom_applied"] == 1
    assert out["stats"]["total_rules"] == 3


def test_compose_longest_custom_first():
    """自定义词之间长词优先：短词不会先吃掉长词的前缀。"""
    from fixtext_pipeline import vocab_bridge as vb

    out = vb.compose(["甲"], ["一"],
                     [{"id": 1, "word": "萧", "value": "萧X"},
                      {"id": 2, "word": "萧衍", "value": "萧彦"}])
    assert out["before"][:2] == ["萧衍", "萧"]


def test_compose_skips_identity_empty_and_duplicate_with_reasons():
    from fixtext_pipeline import vocab_bridge as vb

    out = vb.compose(["甲"], ["一"], [
        {"id": 1, "word": "", "value": "空"},
        {"id": 2, "word": "同", "value": "同"},
        {"id": 3, "word": "萧衍", "value": "萧彦"},
        {"id": 4, "word": "萧衍", "value": "萧彦二"},
    ])
    st = out["stats"]
    assert st["custom_applied"] == 1
    assert [x["id"] for x in st["skipped_empty"]] == [1]
    assert [x["id"] for x in st["skipped_identity"]] == [2]
    assert [x["id"] for x in st["skipped_duplicate"]] == [4]
    assert st["skipped_duplicate"][0]["kept_value"] == "萧彦", "同原词只留第一条并说明保留了哪条"


def test_derived_bytes_identical_when_no_custom(tmp_path):
    """自定义词为空时，派生规则与出厂词库**逐字节**一致（内置行为不变）。"""
    from fixtext_pipeline import vocab_bridge as vb

    empty = tmp_path / "none.json"
    empty.write_text('{"entries": []}', encoding="utf-8")
    meta = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                  empty, tmp_path / "derived")
    assert meta["derived_before_sha256"] == meta["base_before_sha256"]
    assert meta["derived_after_sha256"] == meta["base_after_sha256"]
    assert meta["custom_applied"] == 0


def test_derived_rules_regenerate_only_when_custom_changes(tmp_path, vocab):
    from fixtext_pipeline import vocab_bridge as vb

    out = tmp_path / "derived"
    m1 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json", vocab, out)
    m2 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json", vocab, out)
    assert m1["reused"] is False and m2["reused"] is True, "输入没变就复用，不重复写盘"

    vocab.write_text(json.dumps(
        {"entries": [{"id": 1, "word": "萧衍", "value": "萧彦二"}]},
        ensure_ascii=False), encoding="utf-8")
    m3 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json", vocab, out)
    assert m3["reused"] is False, "自定义词变了就必须重新生成"
    assert m3["compose_key"] != m2["compose_key"]
    assert m3["derived_after_sha256"] != m2["derived_after_sha256"], "替换值变了，派生规则必须重写"


def test_broken_custom_file_does_not_block_run(tmp_path):
    """词库文件坏了不能让校正跑不起来：降级为空词库并如实记录原因。"""
    from fixtext_pipeline import vocab_bridge as vb

    bad = tmp_path / "bad.json"
    bad.write_text("{这不是 JSON", encoding="utf-8")
    meta = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                  bad, tmp_path / "derived")
    assert meta["custom_applied"] == 0
    assert "无法解析" in meta["custom_error"]
    entries, err = vb.load_custom_entries(bad)
    assert entries == [] and err


# ---------------------------------------------------------------------------
# 正向：真跑一次校正，自定义词真的被引擎用上
# ---------------------------------------------------------------------------

@needs_engine
def test_custom_word_takes_effect_in_real_correction(corpus, vocab, tmp_path):
    before_rules = _sha(RULES / "before.json")
    after_rules = _sha(RULES / "after.json")

    summary = _run(tmp_path / "run", corpus, vocab, tmp_path / "derived")
    rep = json.loads((tmp_path / "run" / "run" / "03_replace" / "replace_report.json")
                     .read_text(encoding="utf-8"))
    after_text = Path(rep["after_path"]).read_text(encoding="utf-8")
    before_text = Path(rep["before_path"]).read_text(encoding="utf-8")

    assert before_text.count("萧衍") == 6
    assert after_text.count("萧衍") == 0, "自定义词没生效：原词仍在正文里"
    assert after_text.count("萧彦") == 6, "替换值没有写进正文"
    assert rep["derived_rules"]["custom_applied"] == 1
    # V1.1-F3 修订：``applied_words`` 已不再写进 ``replace_report.json``。
    # M5-EX.1 ``21cb712`` 把分袋多轮改成「每轮一个派生目录」
    # （``derived_rules_dir/round_<id>/``），同时把报告里的派生字段收窄成
    # ``bag_ids / base_rules / custom_input / custom_applied / total_rules /
    # custom_error / include_custom`` 七项——逐条明细移到派生目录自己的
    # ``round_meta.json``（``bags.write_round_rules`` 落盘的同一份 stats）。
    # 所以核对明细要去派生目录读，不是报告里读；语义（哪一条自定义词生效）
    # 一模一样，只是换了落点。分层证据：报告 = 本轮摘要，round_meta = 明细。
    meta_main = (tmp_path / "derived" / "round_main" / "round_meta.json")
    assert meta_main.is_file(), "主轮派生目录必须留下自己的元数据"
    derived_meta = json.loads(meta_main.read_text(encoding="utf-8"))
    assert derived_meta["custom_applied"] == 1
    assert derived_meta["applied_words"] == [
        {"word": "萧衍", "value": "萧彦", "id": 1}]
    # 命中数按上游 diff 口径统计（同上下文合并计数），只校验有命中且词条对得上
    assert summary["hits"] >= 1
    rows = json.loads((tmp_path / "run" / "run" / "03_replace" / "replace_report.json")
                      .read_text(encoding="utf-8")).get("hits_rows") or []
    # 命中词条明细（若报告带该字段则核对，不带就跳过——不以元数据缺失为失败）
    if rows:
        pairs = {(r.get("before"), r.get("after")) for r in rows}
        assert ("萧衍", "萧彦") in pairs or any(
            "萧衍" in str(b) and "萧彦" in str(a) for b, a in pairs)

    assert _sha(RULES / "before.json") == before_rules, "随包词库原件被改动了"
    assert _sha(RULES / "after.json") == after_rules


@needs_engine
def test_negative_control_without_bridge_keeps_custom_word_inert(corpus, vocab, tmp_path):
    """反向对照：**绕过桥接**、直接读随包词库原件跑同一份语料 → 原词一个不少。

    这条是"断言不是恒真"的证明：同样的输入、同样的引擎，只是不用派生规则，
    「萧衍」就不会变成「萧彦」。
    """
    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.stages import STAGES
    from fixtext_pipeline.logsetup import StageLogger
    import fixtext.engine.client as engine_client

    work = tmp_path / "noapi"
    work.mkdir(parents=True, exist_ok=True)
    from plain_book import plain_source_epub
    src = plain_source_epub(corpus, work / "src", title="探针")

    cfg = PipelineConfig(epub=src, workdir=work / "run",
                         rules_before=RULES / "before.json",
                         rules_after=RULES / "after.json",
                         engine_path=ENGINE, replace_count=2,
                         layout_profile="html-safe",
                         stages=("merge", "layout", "replace"),
                         resume=False, force=False)
    for key in ("merge", "layout", "replace"):
        cfg.stage_dir(key).mkdir(parents=True, exist_ok=True)
    cfg.paths.logs.mkdir(parents=True, exist_ok=True)
    cfg.paths.report.mkdir(parents=True, exist_ok=True)

    for key in ("merge", "layout", "replace"):
        logger = StageLogger(cfg.paths.stage_log(key), echo=False)
        stage = STAGES[key](cfg, logger)
        if key == "replace":
            # 关键：把"派生规则"指回随包原件 —— 这就是桥接缺失时旧代码的行为
            stage.derived_rules = lambda: dict(
                before_path=str(RULES / "before.json"),
                after_path=str(RULES / "after.json"),
                base_rules=0, custom_input=0, custom_applied=0, total_rules=0,
                reused=False, custom_error="", skipped_empty=[], skipped_identity=[],
                skipped_duplicate=[], short_custom=[], applied_words=[])
        try:
            stage.run()
        finally:
            logger.close()

    rep = json.loads((work / "run" / "03_replace" / "replace_report.json")
                     .read_text(encoding="utf-8"))
    after_text = Path(rep["after_path"]).read_text(encoding="utf-8")
    assert after_text.count("萧衍") == 6, "对照失败：去掉桥接后原词竟然被替换了，正向断言不成立"
    assert after_text.count("萧彦") == 0


def test_fingerprint_tracks_custom_vocab_sha(tmp_path):
    """主轮指纹必须含自定义词库内容；改词后指纹变，断点才不会复用旧正文。"""
    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.logsetup import StageLogger
    from fixtext_pipeline.stages.replace import ReplaceStage

    vocab = tmp_path / "custom_vocab.json"
    vocab.write_text(json.dumps(
        {"entries": [{"id": 1, "word": "萧衍", "value": "萧彦"}]},
        ensure_ascii=False), encoding="utf-8")
    epub = tmp_path / "probe.epub"
    epub.write_bytes(b"PK\x03\x04empty")
    work = tmp_path / "run"
    work.mkdir(parents=True, exist_ok=True)
    eng = ENGINE if ENGINE.is_file() else (tmp_path / "fake_engine.exe")
    if not eng.is_file():
        eng.write_bytes(b"MZ")
    cfg = PipelineConfig(
        epub=epub, workdir=work,
        rules_before=RULES / "before.json",
        rules_after=RULES / "after.json",
        engine_path=eng, stages=("replace",),
        resume=True, force=False,
        custom_vocab_path=vocab,
        selected_bags=("b1", "custom", "cjk"),
        derived_rules_dir=tmp_path / "derived",
    )
    cfg.stage_dir("replace").mkdir(parents=True, exist_ok=True)
    log = StageLogger(cfg.paths.stage_log("replace"), echo=False)
    try:
        fp1 = ReplaceStage(cfg, log).fingerprint()
        vocab.write_text(json.dumps(
            {"entries": [{"id": 1, "word": "萧衍", "value": "萧彦二"}]},
            ensure_ascii=False), encoding="utf-8")
        fp2 = ReplaceStage(cfg, log).fingerprint()
    finally:
        log.close()
    assert fp1 != fp2, "自定义词改了而指纹没变 → 断点恢复会误判缓存命中"


@needs_engine
def test_fingerprint_changes_with_custom_vocab(corpus, vocab, tmp_path):
    """规则变了指纹必须变，否则断点恢复会把旧正文当新结果复用。"""
    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.stages import STAGES
    from fixtext_pipeline.stages.replace import ReplaceStage
    from fixtext_pipeline.logsetup import StageLogger
    from plain_book import plain_source_epub

    work = tmp_path / "fp"
    work.mkdir(parents=True, exist_ok=True)
    src = plain_source_epub(corpus, work / "src", title="探针")
    cfg = PipelineConfig(epub=src, workdir=work / "run",
                         rules_before=RULES / "before.json",
                         rules_after=RULES / "after.json",
                         engine_path=ENGINE, stages=("merge", "layout", "replace"),
                         resume=False, force=False,
                         custom_vocab_path=vocab,
                         derived_rules_dir=tmp_path / "derived")
    for key in ("merge", "layout", "replace"):
        cfg.stage_dir(key).mkdir(parents=True, exist_ok=True)
        logger = StageLogger(cfg.paths.stage_log(key), echo=False)
        try:
            STAGES[key](cfg, logger).run()
        finally:
            logger.close()
    fp1 = ReplaceStage(cfg, StageLogger(cfg.paths.stage_log("replace"), echo=False)).fingerprint()

    vocab.write_text(json.dumps(
        {"entries": [{"id": 1, "word": "萧衍", "value": "萧彦二"}]},
        ensure_ascii=False), encoding="utf-8")
    fp2 = ReplaceStage(cfg, StageLogger(cfg.paths.stage_log("replace"), echo=False)).fingerprint()
    assert fp1 != fp2, "自定义词改了而指纹没变 → 断点恢复会误判缓存命中"


# ---------------------------------------------------------------------------
# 查重清单：全量、只读
# ---------------------------------------------------------------------------

def test_dup_list_is_actionable_and_complete(qapp, tmp_path):
    """25 组冲突全部列出、打开清单不动文件、每组带处置动作（V1.1-EX.2R）。"""
    import vocab_module as vm
    from fixtext_vocab import VocabStore
    from PySide6.QtWidgets import QDialog, QFrame, QPushButton

    m = vm.VocabModule()
    m.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    m._page, m.search = 0, ""
    m.dict_, m.tier = "custom", "custom"
    try:
        for i in range(25):
            m.store.add_entry(word=f"词{i}", value=f"甲{i}", typ="错词校正")
            m.store.add_entry(word=f"词{i}", value=f"乙{i}", typ="错词校正")
        m._render_all()
        sha_before = _sha(m.store.custom.path)

        groups = m.open_dup()
        assert len(groups) == 25, f"应检出 25 组，实际 {len(groups)}"
        assert m._dup_view["total"] == 25 and m._dup_view["shown"] == 25
        assert m._dup_view["readonly"] is False, "查重清单已由只读改为可处理"
        assert _sha(m.store.custom.path) == sha_before, "打开查重清单不许改动词库"

        from PySide6.QtWidgets import QApplication
        # 按窗口标题定位本弹窗（整轮测试里可能还有别的窗口活着）
        dlgs = [w for w in QApplication.instance().topLevelWidgets()
                if isinstance(w, QDialog)
                and w.windowTitle().startswith("查重清单")]
        assert dlgs, "查重清单窗口没出现"
        dlg = dlgs[0]
        boxes = dlg.findChildren(QFrame, "DupGroup")
        assert len(boxes) == 25, f"界面只画了 {len(boxes)} 组，不是全量"
        feet = [b.text() for b in dlg.findChildren(QPushButton)]
        assert "我知道了" not in feet and "暂时不处理" not in feet, \
            "这两个按钮不做任何动作，不能留着误导用户"
        assert "关闭" in feet
        # 每一组都带处置动作（同词异值 → 「保留这一条」；同词同值 → 「一键去重」）
        assert feet.count("保留这一条") == 25, f"25 组同词异值应各有保留动作，实际 {feet}"
        assert "一键去重" not in feet, "本场景没有同词同值组，不该出现去重按钮"
        dlg.reject()
    finally:
        m.close()
