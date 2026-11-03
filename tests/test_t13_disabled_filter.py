"""V1.1-T1.3 · 词条禁用的引擎装载层过滤。

P1.3 架构评估实测确认：T1.1 只落了数据层与指纹、T1.2 只做了界面，
``compose()`` 没有任何禁用过滤——**禁用的词条仍在参与校正**。本卡把
「禁用」接到规则真正下发引擎之前的最后一站（``write_round_rules`` →
``compose``），并用这些用例把它锁住。

覆盖面（每条都对着一个可证伪的点）：

1. 出厂侧过滤：命中禁用键的出厂规则整条不进派生文件；
2. 自定义侧过滤：自定义词同样受禁用集约束（否则界面上的「禁用」等于没点）；
3. 空集等价：不传 / 传空集时输出与 T1.2 **逐字节**一致（既有行为不漂移）；
4. 指纹联动：禁用集改了下发的规则集指纹必须变，同一禁用集两次跑要一致；
5. 缓存：禁用集变化必须让派生文件重写（不能吃旧缓存）；
6. 规范字节对拍：``vocab_bridge.canonical_disabled`` 与
   ``word_states.canonical_bytes`` 必须给出同样的字节（两处独立实现）；
7. 四轮全过滤：主轮 / 预处理 / 严格 / 注音都走同一道过滤；
8. 阶段指纹：``ruleset=`` 进指纹，且它与实际落盘的 ``ruleset_sha256`` 一致。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui", PKG / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_pipeline import bags, rule_keys, vocab_bridge as vb, word_states as ws  # noqa: E402

RULES = PKG / "data" / "rules"

#: 公版样本里真实出现 54 次的出厂词条（normal 袋），且**不在** T1.1 的迁入
#: 禁用集里——所以它是「默认启用、可被禁用」的天然探针。
PROBE_WORD = "告之"
PROBE_VALUE = "告知"


def _off(*pairs: tuple[str, str]) -> frozenset[str]:
    return frozenset(rule_keys.entry_key(w, v) for w, v in pairs)


@pytest.fixture(scope="module")
def base_pool():
    """默认主轮的出厂规则池（与产品默认勾选一致）。"""
    from fixtext_pipeline.bags import DEFAULT_SELECTED_BAGS, main_bag_ids

    ids = main_bag_ids(DEFAULT_SELECTED_BAGS)
    return bags.concat_bags(ids)


# ---------------------------------------------------------------------------
# 1 · 出厂侧过滤
# ---------------------------------------------------------------------------

def test_compose_filters_factory_entry(base_pool):
    """禁用一条出厂词条 → 派生数组里这条规则消失，且统计如实记账。"""
    before, after = base_pool
    probe = _off((PROBE_WORD, PROBE_VALUE))
    base = vb.compose(before, after, [], disabled_keys=probe)
    stats = base["stats"]

    assert stats["disabled_keys_checked"] == 1
    assert stats["disabled_base_applied"] == 1, (
        f"应当剔掉 1 条出厂规则，实际 {stats['disabled_base_applied']}")
    assert stats["base_kept"] == stats["base_rules"] - 1
    assert stats["total_rules"] == stats["base_rules"] - 1

    pairs_kept = list(zip(base["before"], base["after"]))
    assert (PROBE_WORD, PROBE_VALUE) not in pairs_kept, "禁用了却还在下发"


def test_compose_factory_filter_is_content_keyed(base_pool):
    """内容键（word+NUL+value）判定：同词不同值不算命中，同值不同词也不算。"""
    before, after = base_pool
    wrong_value = _off((PROBE_WORD, "别的值"))
    wrong_word = _off(("别的词", PROBE_VALUE))
    no_hit = vb.compose(before, after, [], disabled_keys=wrong_value | wrong_word)
    assert no_hit["stats"]["disabled_base_applied"] == 0

    hit = vb.compose(before, after, [], disabled_keys=_off((PROBE_WORD, PROBE_VALUE)))
    assert hit["stats"]["disabled_base_applied"] == 1


def test_compose_default_disabled_set_hits_the_orphan(base_pool):
    """T1.1 的出厂初始禁用集里，唯一落在出厂袋中的是孤儿词条「费劲思量」。"""
    before, after = base_pool
    off = ws.initial_disabled_keys()
    out = vb.compose(before, after, [], disabled_keys=off)
    assert out["stats"]["disabled_base_applied"] == 1, (
        "出厂初始禁用集与出厂袋的交集应当正好是那 1 条孤儿词条")
    assert ("费劲思量", "费尽思量") not in list(zip(out["before"], out["after"]))
    # 而探针词条此时仍是启用的 → 还在
    assert (PROBE_WORD, PROBE_VALUE) in list(zip(out["before"], out["after"]))


# ---------------------------------------------------------------------------
# 2 · 自定义侧过滤
# ---------------------------------------------------------------------------

CUSTOM = [
    {"id": 1, "word": "萧衍", "value": "萧彦"},
    {"id": 2, "word": "费劲思量", "value": "费尽思量"},
]


def test_compose_filters_custom_entry():
    """自定义词被禁用 → 不再前置进统一词库（界面禁用必须一路到底）。"""
    before, after = bags.concat_bags(["normal"])
    out = vb.compose(before, after, CUSTOM,
                     disabled_keys=_off(("萧衍", "萧彦"), ("费劲思量", "费尽思量")))
    stats = out["stats"]
    assert stats["custom_input"] == 2
    assert stats["custom_applied"] == 0, "自定义词被禁用了却还生效"
    assert stats["disabled_custom_applied"] == 2
    assert stats["disabled_applied"] == 1 + 2      # 1 条出厂（同款孤儿）+ 2 条自定义
    assert "萧衍" not in out["before"]


def test_compose_keeps_other_custom_when_one_disabled():
    """只禁其中一条时，另一条照旧前置，且下标 0（自定义优先）。"""
    before, after = bags.concat_bags(["normal"])
    out = vb.compose(before, after, CUSTOM,
                     disabled_keys=_off(("费劲思量", "费尽思量")))
    lo, la = out["before"][0], out["after"][0]
    assert (lo, la) == ("萧衍", "萧彦")
    assert out["stats"]["custom_applied"] == 1
    assert out["stats"]["disabled_custom_applied"] == 1


# ---------------------------------------------------------------------------
# 3 · 空集等价：既有行为逐字节不变
# ---------------------------------------------------------------------------

def test_no_disabled_is_byte_identical_to_baseline(tmp_path):
    """``None`` 与空集都必须与 T1.2 的输出逐字节一致。"""
    before, after = bags.concat_bags(["normal"])
    none_out = vb.compose(before, after, CUSTOM, disabled_keys=None)
    empty_out = vb.compose(before, after, CUSTOM, disabled_keys=())
    ref_out = vb.compose(before, after, CUSTOM)          # 旧调用形态

    assert none_out["before"] == empty_out["before"] == ref_out["before"]
    assert none_out["after"] == empty_out["after"] == ref_out["after"]
    for stats in (none_out["stats"], empty_out["stats"], ref_out["stats"]):
        assert stats["disabled_applied"] == 0
        assert stats["disabled_keys_checked"] == 0


def test_derived_bytes_identical_when_disabled_empty(tmp_path):
    """落盘层同样：空禁用集时派生文件 sha 与 T1.2 完全一致。"""
    vocab = tmp_path / "custom.json"
    vocab.write_text(json.dumps({"entries": CUSTOM}, ensure_ascii=False), encoding="utf-8")
    m1 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                               vocab, tmp_path / "d1")
    m2 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                               vocab, tmp_path / "d2", disabled_keys=())
    assert m1["derived_before_sha256"] == m2["derived_before_sha256"]
    assert m1["derived_after_sha256"] == m2["derived_after_sha256"]
    assert m1["ruleset_sha256"] == m2["ruleset_sha256"]


# ---------------------------------------------------------------------------
# 4 · 指纹联动
# ---------------------------------------------------------------------------

def test_disabled_sha_matches_word_states_canonical():
    """两处独立实现的规范字节必须一模一样（否则指纹会两套口径）。"""
    off = ws.initial_disabled_keys()
    assert vb.canonical_disabled(off) == ws.canonical_bytes(off)
    assert vb.disabled_sha(off) == ws.effective_disabled_sha(None)


def test_ruleset_sha_changes_only_when_rules_change(base_pool):
    before, after = base_pool
    clean = vb.compose(before, after, [])
    hit = vb.compose(before, after, [], disabled_keys=_off((PROBE_WORD, PROBE_VALUE)))
    miss = vb.compose(before, after, [], disabled_keys=_off(("没这条", "也没这条")))

    sha = lambda d: vb.ruleset_sha(d["before"], d["after"])  # noqa: E731
    assert sha(clean) != sha(hit), "禁掉一条真规则，规则集指纹却没变"
    assert sha(clean) == sha(miss), "禁用一条本来就不下发的词，规则集指纹不该变"


def test_round_meta_pins_disabled_and_ruleset(tmp_path):
    """落盘元数据里的 disabled_sha / ruleset_sha256 必须与实算一致。"""
    off = _off((PROBE_WORD, PROBE_VALUE))
    meta = bags.write_round_rules(
        bags.main_bag_ids(("b1", "custom", "cjk", "b3", "ddd", "old_style")),
        tmp_path, disabled_keys=off)
    assert meta["disabled_sha"] == vb.disabled_sha(off)
    assert meta["disabled_applied"] == 1
    written_b = json.loads(Path(meta["before_path"]).read_text(encoding="utf-8"))
    written_a = json.loads(Path(meta["after_path"]).read_text(encoding="utf-8"))
    assert meta["ruleset_sha256"] == vb.ruleset_sha(written_b, written_a)
    assert (PROBE_WORD, PROBE_VALUE) not in list(zip(written_b, written_a))


# ---------------------------------------------------------------------------
# 5 · 缓存不被旧派生文件挡住
# ---------------------------------------------------------------------------

def test_derived_rules_regenerate_when_disabled_changes(tmp_path):
    """只改禁用集也必须重写派生文件——否则禁用白点一次。"""
    vocab = tmp_path / "custom.json"
    vocab.write_text(json.dumps({"entries": CUSTOM}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "derived"
    off = _off((PROBE_WORD, PROBE_VALUE))

    m1 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                vocab, out)
    m_no = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                  vocab, out, disabled_keys=())
    assert m_no["reused"] is True, "禁用集没变时应当复用（幂等）"
    assert m_no["derived_before_sha256"] == m1["derived_before_sha256"]

    m_off = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                   vocab, out, disabled_keys=off)
    assert m_off["reused"] is False, "禁用集变了却复用了旧派生文件"
    assert m_off["derived_before_sha256"] != m1["derived_before_sha256"]
    assert m_off["disabled_applied"] == 1          # 探针那条出厂规则（flat 词库）
    assert m_off["ruleset_sha256"] != m1["ruleset_sha256"]

    # 再跑同一禁用集：又回到幂等
    m_again = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                     vocab, out, disabled_keys=off)
    assert m_again["reused"] is True
    assert m_again["derived_before_sha256"] == m_off["derived_before_sha256"]


# ---------------------------------------------------------------------------
# 6 · 四轮都走同一道过滤
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bag", [["preprocess"], ["strict"], ["zhuyin"]])
def test_other_rounds_also_filtered(tmp_path, bag):
    """预处理 / 严格 / 注音三轮同样受禁用影响（不只是主轮）。"""
    # 这三袋里的第一条规则拿来当探针：先读出来，再用它的内容键禁用
    b, a = bags.concat_bags(bag)
    if not b:
        pytest.skip(f"袋 {bag} 为空")
    w, v = b[0], a[0]
    meta = bags.write_round_rules(bag, tmp_path, disabled_keys=_off((w, v)))
    assert meta["disabled_applied"] == 1
    written = json.loads(Path(meta["before_path"]).read_text(encoding="utf-8"))
    assert w not in written, f"{bag} 轮的禁用过滤没生效"


def test_main_round_without_custom_also_filtered(tmp_path):
    """不带自定义词的主轮也要过滤出厂侧——最常见的「禁用出厂词条」路径。"""
    meta = bags.write_round_rules(["normal"], tmp_path,
                                  disabled_keys=_off((PROBE_WORD, PROBE_VALUE)))
    assert meta["include_custom"] is False
    assert meta["custom_input"] == 0
    assert meta["disabled_base_applied"] == 1
    written = json.loads(Path(meta["before_path"]).read_text(encoding="utf-8"))
    assert PROBE_WORD not in written


# ---------------------------------------------------------------------------
# 7 · 阶段指纹与实际下发规则集一致
# ---------------------------------------------------------------------------

def _stage(tmp_path, states_path):
    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.logsetup import StageLogger
    from fixtext_pipeline.stages.replace import ReplaceStage

    epub = tmp_path / "probe.epub"
    epub.write_bytes(b"PK\x03\x04empty")
    work = tmp_path / "run"
    work.mkdir(parents=True, exist_ok=True)
    (tmp_path / "custom.json").write_text('{"entries": []}', encoding="utf-8")
    cfg = PipelineConfig(
        epub=epub, workdir=work,
        rules_before=RULES / "before.json", rules_after=RULES / "after.json",
        engine_path=tmp_path / "fake_engine",
        stages=("replace",), resume=True, force=False,
        custom_vocab_path=tmp_path / "custom.json",
        derived_rules_dir=tmp_path / "derived",
        word_states_path=states_path,
    )
    log = StageLogger(cfg.paths.stage_log("replace"), echo=False)
    return ReplaceStage(cfg, log), log


def test_fingerprint_ruleset_matches_disk(tmp_path):
    """指纹里揉进去的规则集指纹，必须与落盘元数据里的同源同值。"""
    states = tmp_path / "word_states.json"
    wstore = __import__("fixtext_word_states").WordStateStore(writable_path=states)
    wstore.set_enabled([(PROBE_WORD, PROBE_VALUE)], enabled=False)

    stage, log = _stage(tmp_path, states)
    try:
        predicted = stage.dispatched_ruleset_sha()
        meta = stage._prepare_rules()
        assert predicted == meta["ruleset_sha256"], (
            "指纹里用的规则集与实际下发的不一致 → 指纹与行为脱节")
        assert meta["disabled_applied"] == 2   # 探针 + 出厂初始禁用集里的孤儿词条
        # 指纹本身是 sha256 摘要，验它的可复现性 + 对规则集敏感
        fp = stage.fingerprint()
        assert fp.startswith("sha256:")
        assert fp == stage.fingerprint(), "同一输入两次算指纹必须一致"
    finally:
        log.close()


def test_fingerprint_stable_for_same_states(tmp_path):
    """同一禁用集两次算指纹必须一致（否则断点恢复永远命中不了）。"""
    states = tmp_path / "word_states.json"
    wstore = __import__("fixtext_word_states").WordStateStore(writable_path=states)
    wstore.set_enabled([(PROBE_WORD, PROBE_VALUE)], enabled=False)
    stage, log = _stage(tmp_path, states)
    try:
        assert stage.fingerprint() == stage.fingerprint()
    finally:
        log.close()


def test_fingerprint_changes_when_probe_toggled(tmp_path):
    """禁用 → 启用，指纹必须变；而禁用一条不下发的词则不变。"""
    states = tmp_path / "word_states.json"
    wstore = __import__("fixtext_word_states").WordStateStore(writable_path=states)

    stage, log = _stage(tmp_path, states)
    try:
        fp_all_on = stage.fingerprint()
    finally:
        log.close()

    wstore.set_enabled([(PROBE_WORD, PROBE_VALUE)], enabled=False)
    stage2, log2 = _stage(tmp_path, states)
    try:
        fp_off = stage2.fingerprint()
    finally:
        log2.close()
    assert fp_off != fp_all_on, "禁用了一条真正下发的词，指纹却没变"

    # 禁用一条本来就不在任何袋里的词：指纹里 words= 会变（T1.1 口径），
    # 但规则集指纹不能变 —— 两个字段各司其职。
    wstore.clear_disabled()
    wstore.set_enabled([("完全不存在的词", "更不存在的值")], enabled=False)
    stage3, log3 = _stage(tmp_path, states)
    try:
        fp_ghost = stage3.fingerprint()
        meta = stage3._prepare_rules()
    finally:
        log3.close()
    assert fp_ghost != fp_all_on, "words= 字段应当随禁用集变（T1.1 口径）"
    assert meta["disabled_applied"] == 0
    # 规则集指纹与「全启用」时同值：禁用一条本就不下发的词，不改规则集
    on_stage, on_log = _stage(tmp_path, states)
    try:
        wstore.clear_disabled()
        assert on_stage.dispatched_ruleset_sha() == meta["ruleset_sha256"], (
            "禁用一条本就不下发的词，规则集指纹不该变")
    finally:
        on_log.close()
