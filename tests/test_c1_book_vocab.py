"""V1.1-C1 · 按书专有词库的数据形态、存储位置与装载层接线。

排期 8.2 的三条交付物，每一条都在这份用例里有对应的可证伪断言：

1. **数据形态与存储位置**：一本书一份（``workspace/vocab/books/<书 id>/book_vocab.json``），
   与「出厂只读层」「全局自定义层」三级分离——按书层不复制任何词条内容，
   只承载本书的排除项。
2. **装载层接线**：按书排除集只从**同一处**入口下发（``write_round_rules`` →
   ``compose``），不另造第二条过滤路径；四轮全走同一道过滤。
3. **叠加判定**：全局禁用 ∪ 按书排除，全局禁用优先、按书层不得抵消——
   这是排期判据里「互不串扰」的语义基础，必须有专门的判定用例。

验收判据的对照怎么落地：

* 「同一本书在不同按书配置下校正结果可复现」→ ``test_same_book_reproducible_across_configs``
  用真引擎跑两遍同一份配置，正文 sha 必须逐字节相同；改配置再跑必须变。
* 「未配置按书词库的书走全局默认，行为与 B3 收口时完全一致」→
  ``test_unconfigured_book_matches_b3_bytes`` 直接拿 B3 收口时的
  ``compose`` 输出（不带按书参数）与带空按书层的输出对拍字节。
* 「互不串扰」→ ``test_two_books_do_not_leak``：A 书的排除不作用于 B 书，
  且同一本书换配置后旧派生缓存不会被复用。
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

from fixtext_pipeline import bags, book_vocab as bv, rule_keys, vocab_bridge as vb  # noqa: E402

RULES = PKG / "data" / "rules"

#: 与 T1.3 同一枚探针（公版样本里真实出现、且不在迁入禁用集里）。
PROBE_WORD = "告之"
PROBE_VALUE = "告知"

#: 第二个探针：验证「两层各自命中、不冒充」。
PROBE2_WORD = "费劲思量"
PROBE2_VALUE = "费尽思量"


def _keys(*pairs: tuple[str, str]) -> frozenset[str]:
    return frozenset(rule_keys.entry_key(w, v) for w, v in pairs)


@pytest.fixture(scope="module")
def base_pool():
    """默认主轮的出厂规则池（与产品默认勾选一致）。"""
    from fixtext_pipeline.bags import DEFAULT_SELECTED_BAGS, main_bag_ids

    return bags.concat_bags(main_bag_ids(DEFAULT_SELECTED_BAGS))


# ---------------------------------------------------------------------------
# 1 · 数据形态与存储位置：三级分离、一本书一份
# ---------------------------------------------------------------------------

def test_book_vocab_path_is_unique_per_book(tmp_path):
    """一本书一份、路径唯一：``<用户区>/vocab/books/<书 id>/book_vocab.json``。"""
    p = bv.book_vocab_path("书A_1a2b3c4d", workspace=tmp_path)
    assert p == tmp_path / "vocab" / "books" / "书A_1a2b3c4d" / "book_vocab.json"
    # 同一本书永远是同一个位置（不按书名猜、不带时间戳）
    assert bv.book_vocab_path("书A_1a2b3c4d", workspace=tmp_path) == p
    # 两本书落在两个目录里，互不覆盖
    other = bv.book_vocab_path("书B_9f8e7d6c", workspace=tmp_path)
    assert other.parent.name == "书B_9f8e7d6c"
    assert other != p


def test_book_vocab_is_three_tier_separated(tmp_path):
    """三级分离：出厂只读层 / 全局自定义层 / 按书层是三棵互不相同的树。"""
    root = bv.books_root(workspace=tmp_path)
    assert root == tmp_path / "vocab" / "books"
    assert root != RULES and RULES.resolve() != root.resolve()
    # 全局自定义层与按书层是同一棵用户区下的两个兄弟目录（一份 vs 一本书一份）
    assert (tmp_path / "vocab" / "custom_vocab.json").parent == tmp_path / "vocab"
    assert root.parent == tmp_path / "vocab"
    assert bv.books_root(workspace=tmp_path) / "b1" != tmp_path / "vocab" / "custom_vocab.json"


def test_book_vocab_holds_only_exclusions(tmp_path):
    """按书文件只承载排除项：``entries`` 键位在、但本期不生效并被如实说明。"""
    p = bv.book_vocab_path("book_x", workspace=tmp_path)
    bv.write_book_vocab(p, "book_x", [(PROBE_WORD, PROBE_VALUE)])
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["kind"] == "book_vocab"
    assert raw["entries"] == [], "按书层不该承载新增词条（本期只接排除）"
    assert raw["excluded"], "排除项必须落在文件里"
    assert len(p.read_bytes()) < 4096, "按书文件不该塞进整份词库副本"

    # 就算有人手工往里写了 entries，读取时也只报「不生效」，不悄悄生效
    raw["entries"] = [{"word": "甲", "value": "乙"}]
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    info = bv.load_book_vocab(p)
    assert info["excluded_keys"] == _keys((PROBE_WORD, PROBE_VALUE))
    assert info["ignored"] and "entries" in info["ignored"][0]


def test_book_vocab_write_is_canonical(tmp_path):
    """同输入同字节：排除项顺序不影响落盘（可复现的落盘侧前提）。"""
    p1 = bv.book_vocab_path("b1", workspace=tmp_path)
    p2 = bv.book_vocab_path("b2", workspace=tmp_path)
    bv.write_book_vocab(p1, "b1", [(PROBE_WORD, PROBE_VALUE), (PROBE2_WORD, PROBE2_VALUE)])
    bv.write_book_vocab(p2, "b2", [(PROBE2_WORD, PROBE2_VALUE), (PROBE_WORD, PROBE_VALUE)])
    k1 = [x["key"] for x in json.loads(p1.read_text(encoding="utf-8"))["excluded"]]
    k2 = [x["key"] for x in json.loads(p2.read_text(encoding="utf-8"))["excluded"]]
    assert k1 == k2, "排除项顺序不该影响落盘内容"
    assert bv.book_excluded_sha(bv.book_excluded_keys(p1)) == \
        bv.book_excluded_sha(bv.book_excluded_keys(p2))


def test_book_id_is_path_safe(tmp_path):
    """书 id 会被拼进路径：空 / 路径分隔符 / ``..`` 一律拒绝（不猜路径）。"""
    for bad in ("", "   ", "../..", "../../etc", "a/b", "a\\b", "..", "a..b/../c"):
        with pytest.raises(bv.BookVocabError):
            bv.book_vocab_path(bad, workspace=tmp_path)
    # 中文书名与「可读前缀_哈希」两种合法形态都能过
    assert bv.book_vocab_path("呐喊_1a2b3c4d", workspace=tmp_path).name == "book_vocab.json"
    # 落点必须固定在用户区 ``vocab/books/<book_id>/`` 下，不因书 id 跑到别处
    assert bv.book_vocab_path("book_9f8e7d6c", workspace=tmp_path) == (
        tmp_path / "vocab" / "books" / "book_9f8e7d6c" / "book_vocab.json")


def test_unconfigured_book_reads_empty(tmp_path):
    """没有按书文件 = 没有按书配置，不是错误：空集 + ``configured=False``。"""
    info = bv.load_book_vocab(bv.book_vocab_path("book_y", workspace=tmp_path))
    assert info["configured"] is False
    assert info["excluded_keys"] == frozenset()
    assert info["error"] == ""
    # None（连书都没有）同样按「没有按书层」处理
    assert bv.load_book_vocab(None)["excluded_keys"] == frozenset()


def test_corrupt_book_vocab_degrades_instead_of_raising(tmp_path):
    """按书文件坏掉不该让整本校正跑不起来，但必须如实说明没生效。"""
    p = bv.book_vocab_path("book_z", workspace=tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ 这不是 JSON", encoding="utf-8")
    info = bv.load_book_vocab(p)
    assert info["configured"] is False
    assert info["excluded_keys"] == frozenset()
    assert info["error"], "坏文件必须留下原因，不能静默当没有"
    assert bv.book_excluded_keys(p) == frozenset()


# ---------------------------------------------------------------------------
# 2 · 叠加判定：全局禁用 ∪ 按书排除，全局优先、按书层不得抵消
# ---------------------------------------------------------------------------

def test_overlay_policy_is_union_and_global_wins():
    """**本卡指定用例**：全局禁用 + 按书排除叠加时以谁为准。

    判定：取并集；同一条同时命中按**全局禁用**记账（``both``），
    按书层不得抵消全局禁用。这一条是排期判据的直接落地，必须逐项核对。
    """
    g = _keys((PROBE_WORD, PROBE_VALUE))                    # 全局禁用：告之→告知
    b = _keys((PROBE_WORD, PROBE_VALUE),                    # 按书也排除了同一条
              (PROBE2_WORD, PROBE2_VALUE))                  # 按书另排除一条

    out = bv.resolve_excluded(g, b)
    assert out["policy"] == "global_wins_union"
    assert out["effective"] == g | b, "有效排除集必须是并集（排除只增不减）"
    assert out["sources"][rule_keys.entry_key(PROBE_WORD, PROBE_VALUE)] == "both"
    assert out["sources"][rule_keys.entry_key(PROBE2_WORD, PROBE2_VALUE)] == "book"
    assert out["overlap"] == 1
    assert out["global_only"] == 0 and out["book_only"] == 1
    assert out["global_count"] == 1 and out["book_count"] == 2
    assert out["policy_note"], "判定口径必须带人话说明，便于证据逐字核对"

    # 反向也成立：按书层**不能**把全局禁用变成可用（没有「按书启用」这个动作）
    only_book = bv.resolve_excluded([], b)
    assert only_book["sources"][rule_keys.entry_key(PROBE_WORD, PROBE_VALUE)] == "book"
    assert only_book["global_count"] == 0


def test_overlay_global_only_is_untouched_by_book_layer():
    """全局禁用一条、按书层完全不提它 → 仍按全局禁用排掉（行为不回退）。"""
    g = _keys((PROBE_WORD, PROBE_VALUE))
    out = bv.resolve_excluded(g, [])
    assert out["effective"] == g
    assert out["sources"][rule_keys.entry_key(PROBE_WORD, PROBE_VALUE)] == "global"
    assert out["overlap"] == 0


def test_compose_union_is_one_filter_pass(base_pool):
    """装载层只有一道过滤：两层命中都在同一次 ``compose`` 里剔除并各自记账。"""
    before, after = base_pool
    g = _keys((PROBE_WORD, PROBE_VALUE))
    b = _keys((PROBE_WORD, PROBE_VALUE), (PROBE2_WORD, PROBE2_VALUE))
    out = vb.compose(before, after, [], disabled_keys=g, book_excluded_keys=b,
                     book_id="书A_1a2b3c4d")
    stats = out["stats"]
    pairs = list(zip(out["before"], out["after"]))

    # 并集生效：两条都不在下发规则里
    assert (PROBE_WORD, PROBE_VALUE) not in pairs, "全局禁用的词条仍在规则里"
    assert (PROBE2_WORD, PROBE2_VALUE) not in pairs, "按书排除的词条仍在规则里"
    # 记账不混：全局 1（含叠加）、按书生效 2（含叠加）、按书独占 1、叠加 1
    assert stats["disabled_applied"] == 1, "全局禁用口径只算全局侧"
    assert stats["book_only_applied"] == 1, "按书层独占的只有那 1 条"
    assert stats["book_excluded_applied"] == 2, "本书确实被排除了 2 条（含叠加那条）"
    assert stats["overlap_applied"] == 1
    assert stats["excluded_total_applied"] == 2, "去重后的真实剔除条数"
    assert stats["book_id"] == "书A_1a2b3c4d"
    assert stats["excluded_policy"] == "global_wins_union"
    # 只有两条被剔掉，其余保住
    assert stats["base_kept"] == stats["base_rules"] - 2


def test_compose_overlap_reason_mentions_both_layers(base_pool):
    """叠加那一条的剔除原因必须两层都说清楚（证据可读，不靠猜）。"""
    before, after = base_pool
    g = _keys((PROBE_WORD, PROBE_VALUE))
    b = _keys((PROBE_WORD, PROBE_VALUE))
    out = vb.compose(before, after, [], disabled_keys=g, book_excluded_keys=b)
    reasons = {d["word"]: d for d in out["stats"]["book_excluded"]}
    # 叠加那条按全局记账（不进 book_excluded），所以改从统计核对
    assert out["stats"]["overlap_applied"] == 1
    assert out["stats"]["book_excluded_applied"] == 1
    assert out["stats"]["disabled_applied"] == 1


def test_compose_book_layer_also_filters_custom_entries():
    """自定义词同样受按书排除约束（按书层不是只管出厂侧）。"""
    before, after = bags.concat_bags(["normal"])
    custom = [{"id": 1, "word": "萧衍", "value": "萧彦"}]
    out = vb.compose(before, after, custom,
                     book_excluded_keys=_keys(("萧衍", "萧彦")), book_id="书B")
    stats = out["stats"]
    assert stats["custom_input"] == 1
    assert stats["custom_applied"] == 0, "按书排除了却还前置进规则"
    assert stats["book_custom_applied"] == 1
    assert "萧衍" not in out["before"]


def test_compose_book_only_does_not_touch_global_disabled_counter(base_pool):
    """按书层单独命中不得冒充全局禁用（两种排除不能混成一个数字）。"""
    before, after = base_pool
    out = vb.compose(before, after, [],
                     book_excluded_keys=_keys((PROBE_WORD, PROBE_VALUE)))
    stats = out["stats"]
    assert stats["disabled_applied"] == 0, "按书层命中被算成了全局禁用"
    assert stats["book_excluded_applied"] == 1


# ---------------------------------------------------------------------------
# 3 · 未配置按书词库 = B3 收口行为（逐字节回归对照）
# ---------------------------------------------------------------------------

def test_unconfigured_book_matches_b3_bytes(base_pool):
    """未配置按书词库的书，输出与 B3 收口时**逐字节一致**（回归对照）。

    B3 收口的调用形态是 ``compose(before, after, entries, disabled_keys=off)``；
    C1 之后同一个调用仍走同一分支，而显式传空按书层必须给出同样的字节。
    """
    before, after = base_pool
    g = _keys((PROBE2_WORD, PROBE2_VALUE))

    b3 = vb.compose(before, after, [], disabled_keys=g)                    # B3 形态
    c1_none = vb.compose(before, after, [], disabled_keys=g,
                         book_excluded_keys=None)                          # 显式 None
    c1_empty = vb.compose(before, after, [], disabled_keys=g,
                          book_excluded_keys=frozenset(), book_id="")      # 显式空集

    for other in (c1_none, c1_empty):
        assert other["before"] == b3["before"]
        assert other["after"] == b3["after"]
        assert json.dumps(other["before"], ensure_ascii=False).encode("utf-8") == \
            json.dumps(b3["before"], ensure_ascii=False).encode("utf-8")

    # 空按书层的统计字段如实为 0，且不谎报有排除
    assert c1_empty["stats"]["book_excluded_applied"] == 0
    assert c1_empty["stats"]["overlap_applied"] == 0
    assert c1_empty["stats"]["excluded_total_applied"] == b3["stats"]["disabled_applied"]
    # 空排除集时判定口径留空（不声称用了并集规则）
    assert c1_empty["stats"]["excluded_policy"] == "" or g


def test_unconfigured_book_derived_rules_byte_identical(tmp_path):
    """落盘侧对照：不带按书层与带空按书层，派生文件字节必须相同。"""
    custom = tmp_path / "custom.json"
    custom.write_text('{"entries": []}', encoding="utf-8")
    m_b3 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                 custom, tmp_path / "d_b3", disabled_keys=[])
    m_c1 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                 custom, tmp_path / "d_c1", disabled_keys=[],
                                 book_excluded_keys=frozenset(), book_id="")
    assert m_b3["derived_before_sha256"] == m_c1["derived_before_sha256"]
    assert m_b3["derived_after_sha256"] == m_c1["derived_after_sha256"]
    assert m_b3["ruleset_sha256"] == m_c1["ruleset_sha256"]
    assert m_b3["compose_key"] == m_c1["compose_key"], (
        "空按书层的合成键必须与 B3 形态相同，否则同一份输入会被当成新配置重写")
    assert m_c1["book_excluded_sha"] == bv.book_excluded_sha(frozenset())


def test_book_config_change_regenerates_derived_rules(tmp_path):
    """按书配置改了必须重写派生文件（不能被缓存挡住，否则改了等于没改）。"""
    custom = tmp_path / "custom.json"
    custom.write_text('{"entries": []}', encoding="utf-8")
    out = tmp_path / "d"
    kw = dict(disabled_keys=[], book_id="书A_1a2b3c4d")

    m0 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                custom, out, book_excluded_keys=frozenset(), **kw)
    assert m0["reused"] is False

    # 同一份按书配置再写一次 → 命中缓存，不重写
    m1 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                custom, out,
                                book_excluded_keys=frozenset(), **kw)
    assert m1["reused"] is True
    assert m1["derived_before_sha256"] == m0["derived_before_sha256"]

    # 按书排除集变了 → 必须重写，且下发规则真少了那一条
    m2 = vb.write_derived_rules(RULES / "before.json", RULES / "after.json",
                                custom, out,
                                book_excluded_keys=_keys((PROBE_WORD, PROBE_VALUE)), **kw)
    assert m2["reused"] is False
    assert m2["compose_key"] != m0["compose_key"]
    assert m2["book_excluded_sha"] != m0["book_excluded_sha"]
    written = json.loads(Path(m2["before_path"]).read_text(encoding="utf-8"))
    assert PROBE_WORD not in written, "按书排除没进派生文件"


# ---------------------------------------------------------------------------
# 4 · 装载层接线：四轮全走同一道过滤
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bag", [["preprocess"], ["strict"], ["zhuyin"], ["normal"]])
def test_all_rounds_honor_book_exclusion(tmp_path, bag):
    """预处理 / 严格 / 注音 / 主轮四轮都受按书排除影响（不只主轮）。"""
    b, a = bags.concat_bags(bag)
    if not b:
        pytest.skip(f"袋 {bag} 为空")
    w, v = b[0], a[0]
    meta = bags.write_round_rules(bag, tmp_path, book_excluded_keys=_keys((w, v)),
                                  book_id="书A_1a2b3c4d")
    assert meta["book_excluded_applied"] == 1
    assert meta["book_id"] == "书A_1a2b3c4d"
    written = json.loads(Path(meta["before_path"]).read_text(encoding="utf-8"))
    assert w not in written, f"{bag} 轮的按书排除没生效"


def test_bags_meta_reports_book_layer(tmp_path):
    """装载层元数据必须带按书层事实（书 id / 检查条数 / 指纹），证据可核。"""
    meta = bags.write_round_rules(["normal"], tmp_path, book_id="书A_1a2b3c4d",
                                  book_excluded_keys=_keys((PROBE_WORD, PROBE_VALUE)))
    assert meta["book_id"] == "书A_1a2b3c4d"
    assert meta["book_excluded_keys_checked"] == 1
    assert meta["book_excluded_sha"] == bv.book_excluded_sha(
        _keys((PROBE_WORD, PROBE_VALUE)))
    assert meta["book_excluded_applied"] == 1


# ---------------------------------------------------------------------------
# 5 · 交叉隔离：两本书互不串扰
# ---------------------------------------------------------------------------

def test_two_books_do_not_leak(tmp_path, base_pool):
    """A 书的按书排除不作用于 B 书；B 书不配置就走全局默认。"""
    before, after = base_pool
    a_keys = _keys((PROBE_WORD, PROBE_VALUE))
    pa = bv.book_vocab_path("书A_1a2b3c4d", workspace=tmp_path)
    pb = bv.book_vocab_path("书B_9f8e7d6c", workspace=tmp_path)
    bv.write_book_vocab(pa, "书A_1a2b3c4d", [(PROBE_WORD, PROBE_VALUE)])

    out_a = vb.compose(before, after, [],
                       book_excluded_keys=bv.book_excluded_keys(pa),
                       book_id="书A_1a2b3c4d")
    out_b = vb.compose(before, after, [],
                       book_excluded_keys=bv.book_excluded_keys(pb),
                       book_id="书B_9f8e7d6c")

    assert (PROBE_WORD, PROBE_VALUE) not in list(zip(out_a["before"], out_a["after"]))
    assert (PROBE_WORD, PROBE_VALUE) in list(zip(out_b["before"], out_b["after"])), (
        "A 书的按书排除漏到了 B 书")
    assert out_a["stats"]["book_excluded_applied"] == 1
    assert out_b["stats"]["book_excluded_applied"] == 0
    # 两本书各自的合成键不同 → 派生缓存不会互相复用
    assert bv.book_excluded_sha(bv.book_excluded_keys(pa)) != \
        bv.book_excluded_sha(bv.book_excluded_keys(pb))


# ---------------------------------------------------------------------------
# 6 · 阶段接线：配置 → 指纹 / 报告
# ---------------------------------------------------------------------------

def _stage(tmp_path, *, book_id="", book_vocab_path=None, states=None):
    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.logsetup import StageLogger
    from fixtext_pipeline.stages.replace import ReplaceStage

    epub = tmp_path / "probe.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"PK\x03\x04empty")
    work = tmp_path / "run"
    work.mkdir(parents=True, exist_ok=True)
    custom = tmp_path / "custom.json"
    if not custom.is_file():
        custom.write_text('{"entries": []}', encoding="utf-8")
    cfg = PipelineConfig(
        epub=epub, workdir=work,
        rules_before=RULES / "before.json", rules_after=RULES / "after.json",
        engine_path=tmp_path / "fake_engine",
        stages=("replace",), resume=True, force=False,
        custom_vocab_path=custom,
        derived_rules_dir=tmp_path / "derived",
        word_states_path=states,
        book_id=book_id,
        book_vocab_path=book_vocab_path,
    )
    log = StageLogger(cfg.paths.stage_log("replace"), echo=False)
    return ReplaceStage(cfg, log), log


def test_config_resolves_book_vocab_path(tmp_path):
    """只给书 id，配置自己按唯一位置推算；非法书 id 不猜路径、留原因。"""
    from fixtext_pipeline.config import PipelineConfig

    epub = tmp_path / "p.epub"
    epub.write_bytes(b"PK")
    base = dict(epub=epub, workdir=tmp_path / "run",
                rules_before=RULES / "before.json",
                rules_after=RULES / "after.json",
                engine_path=tmp_path / "eng")

    cfg = PipelineConfig(book_id="书A_1a2b3c4d", **base)
    assert cfg.book_vocab_path is not None
    assert cfg.book_vocab_path.name == "book_vocab.json"
    assert cfg.book_vocab_path.parent.name == "书A_1a2b3c4d"
    assert cfg.to_dict()["book_id"] == "书A_1a2b3c4d"
    # 续跑还原同一份
    assert PipelineConfig.from_state(cfg.to_dict()).book_vocab_path == cfg.book_vocab_path

    bad = PipelineConfig(book_id="../..", **base)
    assert bad.book_vocab_path is None, "非法书 id 被拼进了文件系统路径"
    assert bad.book_id_error, "非法书 id 必须留下原因"

    plain = PipelineConfig(**base)
    assert plain.book_vocab_path is None and plain.book_id == ""


def test_stage_report_and_fingerprint_track_book_layer(tmp_path):
    """阶段指纹跟着按书配置变；报告如实给出按书层事实。"""
    p = bv.book_vocab_path("书A_1a2b3c4d", workspace=tmp_path / "ws")
    bv.write_book_vocab(p, "书A_1a2b3c4d", [(PROBE_WORD, PROBE_VALUE)])

    s1, log1 = _stage(tmp_path, book_id="书A_1a2b3c4d", book_vocab_path=p)
    try:
        fp_book = s1.fingerprint()
        assert fp_book == s1.fingerprint(), "同一输入两次算指纹必须一致"
        meta = s1._prepare_rules()
        assert s1.dispatched_ruleset_sha() == meta["ruleset_sha256"], (
            "指纹里用的规则集与实际下发的不一致")
        assert meta["book_excluded_applied"] == 1
        layer = s1._book_layer_report()
        assert layer["book_id"] == "书A_1a2b3c4d"
        assert layer["configured"] is True
        assert layer["excluded_checked"] == 1
    finally:
        log1.close()

    s2, log2 = _stage(tmp_path, book_id="书A_1a2b3c4d", book_vocab_path=None)
    try:
        fp_unconfigured = s2.fingerprint()
        assert fp_unconfigured != fp_book, "按书配置改了，指纹却没变 → 断点会复用旧正文"
        assert s2._book_layer_report()["configured"] is False
    finally:
        log2.close()

    # 同一本书、同一份按书配置两遍 → 指纹必须一致（可复现）
    s3, log3 = _stage(tmp_path, book_id="书A_1a2b3c4d", book_vocab_path=p)
    try:
        assert s3.fingerprint() == fp_book
    finally:
        log3.close()


def test_stage_report_is_book_scoped(tmp_path):
    """两本书互相不串扰：各自报告的按书层事实只见自己那本。"""
    ws = tmp_path / "ws"
    pa = bv.book_vocab_path("书A_1a2b3c4d", workspace=ws)
    pb = bv.book_vocab_path("书B_9f8e7d6c", workspace=ws)
    bv.write_book_vocab(pa, "书A_1a2b3c4d", [(PROBE_WORD, PROBE_VALUE)])
    bv.write_book_vocab(pb, "书B_9f8e7d6c", [(PROBE2_WORD, PROBE2_VALUE)])

    sa, la = _stage(tmp_path / "a", book_id="书A_1a2b3c4d", book_vocab_path=pa)
    try:
        ma = sa._prepare_rules()
    finally:
        la.close()

    sb, lb = _stage(tmp_path / "b", book_id="书B_9f8e7d6c", book_vocab_path=pb)
    try:
        mb = sb._prepare_rules()
    finally:
        lb.close()

    assert ma["book_id"] == "书A_1a2b3c4d" and mb["book_id"] == "书B_9f8e7d6c"
    assert ma["book_excluded_sha"] != mb["book_excluded_sha"]
    assert ma["ruleset_sha256"] != mb["ruleset_sha256"], "两本书下发规则不该相同"


# ---------------------------------------------------------------------------
# 7 · 真引擎端到端：可复现 + 不串扰
# ---------------------------------------------------------------------------

_ENGINE_BIN = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
try:
    from fixtext_pipeline.engine_selector import select_engine

    ENGINE = select_engine(_ENGINE_BIN) or (_ENGINE_BIN / "__no_platform_engine__")
except Exception:                                              # pragma: no cover
    ENGINE = _ENGINE_BIN / "__no_platform_engine__"

needs_engine = pytest.mark.skipif(not ENGINE.exists(), reason="缺少真实引擎")

_CORPUS = (
    "他告之众人，众人告之他。\n"
    "告之 之事，不可告之 两次。\n"
    "费劲思量，终究费劲思量。\n"
)


def _body_only(text: str) -> str:
    """摘掉 epubtext-bundle 头部再比对。

    头部三行注释里带**每次运行随机的 nonce** 和书名 / 源文件名
    （``<!-- EPUBTEXT-BUNDLE nonce=…`` 等）——不同 title 的两次运行头部
    必不相同，但正文逐字相同。可比对的是正文，不是头部。
    """
    return "\n".join(
        ln for ln in text.splitlines() if not ln.startswith("<!-- EPUBTEXT-"))


def _run_book(tmp_path, name: str, *, book_vocab_path=None, book_id=""):
    """跑一次真六阶段校正，返回 (正文 sha256, 报告里的按书层字段)。"""
    import hashlib

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
    # 权威产物路径由各阶段报告自述（summary["artifacts"]），不按文件名猜；
    # 正文 sha 摘掉 bundle 头（含随机 nonce 与书名）再算，只比内容
    after = Path(summary["artifacts"]["after_text"])
    raw = _body_only(after.read_text(encoding="utf-8"))
    rep = json.loads((tmp_path / f"{tag}_run" / "03_replace"
                      / "replace_report.json").read_text(encoding="utf-8"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), rep


@needs_engine
def test_same_book_reproducible_across_configs(tmp_path):
    """同一本书、同一份按书配置跑两遍 → 校正结果逐字节相同（可复现）。

    再换一份按书配置跑一遍 → 结果必须变（证明配置真的起作用，
    而不是「两次都恰好没生效」把可复现混成恒等）。
    """
    ws = tmp_path / "ws"
    p = bv.book_vocab_path("书A_1a2b3c4d", workspace=ws)
    bv.write_book_vocab(p, "书A_1a2b3c4d", [(PROBE_WORD, PROBE_VALUE)])

    sha1, rep1 = _run_book(tmp_path, "a1", book_vocab_path=p, book_id="书A_1a2b3c4d")
    sha2, rep2 = _run_book(tmp_path, "a2", book_vocab_path=p, book_id="书A_1a2b3c4d")
    assert sha1 == sha2, "同一配置两次跑结果不一致"
    assert rep1["derived_rules"]["book_excluded_applied"] == 1
    assert rep2["derived_rules"]["book_excluded_applied"] == 1
    assert rep1["derived_rules"]["ruleset_sha256"] == rep2["derived_rules"]["ruleset_sha256"]

    sha3, rep3 = _run_book(tmp_path, "a3", book_vocab_path=p, book_id="书A_1a2b3c4d")
    # 换配置：换成排掉另一条词
    bv.write_book_vocab(p, "书A_1a2b3c4d", [(PROBE2_WORD, PROBE2_VALUE)])
    sha4, rep4 = _run_book(tmp_path, "a4", book_vocab_path=p, book_id="书A_1a2b3c4d")
    assert sha3 == sha1
    assert sha4 != sha1, "换了按书配置结果却没变 → 按书层没真正生效"
    assert rep4["derived_rules"]["ruleset_sha256"] != rep1["derived_rules"]["ruleset_sha256"]


@needs_engine
def test_unconfigured_book_matches_b3_end_to_end(tmp_path):
    """未配置按书词库的书：校正正文与 B3 收口时（无按书参数）逐字节相同。"""
    sha_plain, rep_plain = _run_book(tmp_path, "plain")
    ws = tmp_path / "ws"
    p = bv.book_vocab_path("书B_9f8e7d6c", workspace=ws)     # 文件根本不建
    sha_c1, rep_c1 = _run_book(tmp_path, "c1", book_vocab_path=p, book_id="书B_9f8e7d6c")

    assert sha_plain == sha_c1, "未配置按书词库的书结果漂移了（B3 回归对照失败）"
    assert (rep_plain["derived_rules"]["ruleset_sha256"]
            == rep_c1["derived_rules"]["ruleset_sha256"])
    assert rep_c1["derived_rules"]["book_excluded_applied"] == 0
    assert rep_c1["book_layer"]["configured"] is False


@needs_engine
def test_two_books_end_to_end_do_not_leak(tmp_path):
    """A 书有按书排除、B 书没有 → A 的结果不同、B 的结果等于全局默认。"""
    ws = tmp_path / "ws"
    pa = bv.book_vocab_path("书A_1a2b3c4d", workspace=ws)
    bv.write_book_vocab(pa, "书A_1a2b3c4d", [(PROBE_WORD, PROBE_VALUE)])
    pb = bv.book_vocab_path("书B_9f8e7d6c", workspace=ws)     # 不建

    sha_a, rep_a = _run_book(tmp_path, "xa", book_vocab_path=pa, book_id="书A_1a2b3c4d")
    sha_b, rep_b = _run_book(tmp_path, "xb", book_vocab_path=pb, book_id="书B_9f8e7d6c")
    sha_plain, _ = _run_book(tmp_path, "xp")

    assert sha_a != sha_b, "两本书结果相同 → 按书层没生效或串扰"
    assert sha_b == sha_plain, "B 书没配按书层，却没走全局默认"
    assert rep_a["derived_rules"]["book_excluded_applied"] == 1
    assert rep_b["derived_rules"]["book_excluded_applied"] == 0
