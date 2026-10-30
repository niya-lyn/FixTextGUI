"""M5-EX.1 运行模式优化 · 定向冒烟。

覆盖：分袋合成、动态阶段、注音后处理、词库按袋展示、
默认 / 预处理 / 严格 / 注音 / 跳过排版 的 CorrectionJob 阶段列表与主轮规则袋。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui", PKG / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RULES = PKG / "data" / "rules"
BAGS = RULES / "bags"


# ---------------------------------------------------------------------------
# 分袋 API
# ---------------------------------------------------------------------------

def test_bags_manifest_and_locked_main():
    from fixtext_pipeline import bags

    man = bags.load_manifest(BAGS)
    assert man.get("bag_count") == 15
    assert bags.LOCKED_MAIN_BAG == "normal"
    # CJK 与常规同锁，始终并入；punctuation 已移除
    ids = bags.main_bag_ids(("custom",))
    assert ids == ["normal", "cjk_recover"]
    assert "custom" not in ids  # custom 走 compose，不进袋 id
    assert bags.main_bag_ids(("b3", "b3r")) == [
        "normal", "cjk_recover", "t2s", "t2s_radical",
    ]
    assert bags.SILENT_WITH_NORMAL == ("cjk_recover",)
    assert "punctuation" not in bags.UI_BAG_MAP.values()
    assert "postfix" not in bags.UI_BAG_MAP.values()
    assert "temp" not in bags.UI_BAG_MAP.values()
    all_main = bags.main_bag_ids(tuple(bags.UI_BAG_MAP.keys()) + ("custom",))
    assert set(all_main) == set(bags.UI_BAG_MAP.values())
    for switch_bag in bags.SWITCH_BAGS.values():
        assert switch_bag not in all_main


def test_bags_concat_and_write_round(tmp_path):
    from fixtext_pipeline import bags

    b, a = bags.load_bag("strict", BAGS)
    assert len(b) == len(a) > 0
    b2, a2 = bags.concat_bags(["preprocess"], BAGS)
    assert len(b2) == len(a2)
    meta = bags.write_round_rules(
        ["strict"], tmp_path / "r_strict", include_custom=False, root=BAGS
    )
    assert meta["bag_ids"] == ["strict"]
    assert meta["include_custom"] is False
    assert Path(meta["before_path"]).is_file()
    before = json.loads(Path(meta["before_path"]).read_text(encoding="utf-8"))
    assert len(before) == len(b)


def test_main_round_compose_with_custom(tmp_path):
    from fixtext_pipeline import bags

    vocab = tmp_path / "custom_vocab.json"
    vocab.write_text(
        json.dumps(
            {
                "product": "FixText",
                "kind": "custom_vocab",
                "version": 1,
                "entries": [{"id": 1, "word": "探针词", "value": "探针值"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ids = bags.main_bag_ids(("custom",))
    meta = bags.write_round_rules(
        ids,
        tmp_path / "r_main",
        custom_path=vocab,
        include_custom=True,
        root=BAGS,
    )
    assert meta["custom_applied"] >= 1
    before = json.loads(Path(meta["before_path"]).read_text(encoding="utf-8"))
    assert before[0] == "探针词"


# ---------------------------------------------------------------------------
# 动态阶段
# ---------------------------------------------------------------------------

def test_build_stage_keys_matrix():
    from fixtext_pipeline.config import build_stage_keys, HUMAN_STAGE_LABELS

    d = build_stage_keys()
    assert d == ("merge", "layout", "replace", "quote", "bookmap", "restore")

    skip = build_stage_keys(skip_layout=True)
    assert "layout" not in skip
    assert skip[0] == "merge" and skip[1] == "replace"

    prep = build_stage_keys(enable_preprocess=True)
    assert "replace_preprocess" in prep
    assert prep.index("replace_preprocess") < prep.index("replace")

    strict = build_stage_keys(enable_strict=True)
    assert "replace_strict" in strict

    zhu = build_stage_keys(zhuyin_mode="0")
    assert "replace_zhuyin" in zhu
    assert zhu.index("replace") < zhu.index("replace_zhuyin")

    assert HUMAN_STAGE_LABELS["replace_preprocess"] == "预处理替换"
    assert HUMAN_STAGE_LABELS["replace_zhuyin"] == "生僻字注音"

    # 有 Qt 时再核对人话进度步拼装（与 build_stage_keys 同序）
    try:
        from fixtext_worker import build_human_stages
    except ModuleNotFoundError:
        return
    human = build_human_stages(
        skip_layout=True, enable_preprocess=True, zhuyin_mode="1"
    )
    keys = [s["key"] for s in human]
    assert keys == list(
        build_stage_keys(skip_layout=True, enable_preprocess=True, zhuyin_mode="1")
    )
    assert any(s["name"] == "预处理替换" for s in human)
    assert not any(s["key"] == "layout" for s in human)


def test_zhuyin_post_modes():
    from fixtext_pipeline import zhuyin_post

    text = "唬[hu][hu] 多[音一 或 音二]"
    out0, r0 = zhuyin_post.apply(text, "0")
    assert r0["removed_duplicates"] >= 1
    assert "[hu][hu]" not in out0
    out2, r2 = zhuyin_post.apply(text, "2")
    assert r2["first_reading_stripped"] >= 1
    assert "[音一]" in out2


# ---------------------------------------------------------------------------
# 词库按袋
# ---------------------------------------------------------------------------

def test_vocab_builtin_from_bags():
    from fixtext_vocab import BAG_TO_TIER, BuiltinVocab, TIER_NAMES, TIER_ORDER

    bv = BuiltinVocab(RULES)
    assert bv.available
    assert (bv.meta or {}).get("vocab_source") == "bags" or "bags" in str(bv.source)
    # bags 展示模式下指纹仍应对 flat 五件套非空，且不可对 bags 目录当文件读
    assert bv.combined_sha()
    assert bv.combined_sha() != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert bv.current_shas(), "bags 模式下 current_shas 不应恒为空"
    assert bv.source.is_dir()
    assert bv.source.name != "bags"
    assert (bv.source / "before.json").is_file()
    counts = bv.tier_counts()
    assert counts.get("b1", 0) > 1000  # normal
    assert counts.get("preprocess", 0) > 0
    assert counts.get("strict", 0) > 0
    assert counts.get("zhuyin", 0) > 0
    assert counts.get("extra", 0) > 0
    assert counts.get("ddd", 0) > 0
    assert counts.get("txt_format", 0) > 0
    assert counts.get("cjk", 0) > 0
    assert counts.get("b3", 0) == 3141
    assert counts.get("b3r", 0) == 1107  # radical + supplement
    assert set(BAG_TO_TIER) == {
        "normal", "cjk_recover", "t2s", "t2s_radical",
        "extra", "ddd", "dei2de", "old_style", "txt_format",
        "preprocess", "strict", "zhuyin",
    }
    assert "punctuation" not in BAG_TO_TIER
    assert "postfix" not in BAG_TO_TIER and "temp" not in BAG_TO_TIER
    assert set(BAG_TO_TIER.values()).issubset(set(TIER_ORDER))
    assert "preprocess" in TIER_ORDER
    assert "严格校正词库" in TIER_NAMES.values()
    assert "的地得词库" in TIER_NAMES.values()
    assert "繁简转换激进词库" in TIER_NAMES.values()


# ---------------------------------------------------------------------------
# 管线冒烟（小书 + Python 引擎；不依赖 Qt / CorrectionJob）
# ---------------------------------------------------------------------------

def _mini_epub(tmp_path: Path) -> Path:
    """两章微型 EPUB，足够跑通 merge→…→restore。"""
    import zipfile

    epub = tmp_path / "mini.epub"
    body = "那年冬天的雪下得很大。唬唬多音字探针。" * 5
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
            'unique-identifier="bid"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>迷你</dc:title><dc:creator>测</dc:creator>'
            '<dc:identifier id="bid">urn:uuid:m5ex1</dc:identifier>'
            '<dc:language>zh-CN</dc:language></metadata><manifest>'
            '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '</manifest><spine toc="ncx"><itemref idref="c1"/></spine></package>',
        )
        z.writestr(
            "OEBPS/toc.ncx",
            '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
            'version="2005-1"><navMap><navPoint id="n1" playOrder="1">'
            '<navLabel><text>第一章</text></navLabel>'
            '<content src="c1.xhtml"/></navPoint></navMap></ncx>',
        )
        z.writestr(
            "OEBPS/c1.xhtml",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>第一章</title>'
            f"</head><body><h1>第一章</h1><p>{body}</p></body></html>",
        )
    return epub


def _pick_engine() -> tuple[str, Path] | None:
    """优先 Go（大袋更快）；否则 Python（需 pyahocorasick）。"""
    from fixtext_pipeline.engine_selector import select_engine
    from fixtext_pipeline.vendor_bootstrap import bootstrap

    bootstrap(str(PKG / "pipeline"), strict=True)
    bin_dir = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
    go = select_engine(bin_dir)
    if go is not None and go.is_file():
        return "go", go
    try:
        import ahocorasick  # noqa: F401
        from fixtext.engine.py_engine import PyGreedyEngineClient  # noqa: F401

        return "python", bin_dir / "unused_go_placeholder"
    except Exception:
        return None


_ENGINE = _pick_engine()
needs_engine = pytest.mark.skipif(_ENGINE is None, reason="无可用替换引擎")


def _run_pipeline(
    tmp_path,
    *,
    skip_layout=False,
    enable_preprocess=False,
    enable_strict=False,
    zhuyin_mode="off",
    selected_bags=("b1", "custom", "cjk", "b3", "ddd", "old_style"),
):
    from fixtext_pipeline.config import PipelineConfig, build_stage_keys
    from fixtext_pipeline.logsetup import StageLogger, capture_output
    from fixtext_pipeline.stages import STAGES
    from fixtext_pipeline.vendor_bootstrap import bootstrap

    assert _ENGINE is not None
    engine_kind, engine_path = _ENGINE
    bootstrap(str(PKG / "pipeline"), strict=True)
    keys = build_stage_keys(
        skip_layout=skip_layout,
        enable_preprocess=enable_preprocess,
        enable_strict=enable_strict,
        zhuyin_mode=zhuyin_mode,
    )
    work = tmp_path / "run"
    empty_custom = tmp_path / "empty_custom.json"
    empty_custom.write_text(
        json.dumps(
            {"product": "FixText", "kind": "custom_vocab", "version": 1, "entries": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cfg = PipelineConfig(
        epub=_mini_epub(tmp_path),
        workdir=work,
        rules_before=RULES / "before.json",
        rules_after=RULES / "after.json",
        engine_path=engine_path,
        engine=engine_kind,
        replace_count=2,
        layout_profile="html-safe",
        stages=keys,
        resume=False,
        force=True,
        custom_vocab_path=empty_custom,
        derived_rules_dir=tmp_path / "derived",
        skip_layout=skip_layout,
        enable_preprocess=enable_preprocess,
        enable_strict=enable_strict,
        zhuyin_mode=zhuyin_mode,
        selected_bags=tuple(selected_bags),
    )
    work.mkdir(parents=True)
    cfg.paths.logs.mkdir(parents=True, exist_ok=True)
    cfg.paths.report.mkdir(parents=True, exist_ok=True)
    reports: dict[str, dict] = {}
    for key in keys:
        cfg.stage_dir(key).mkdir(parents=True, exist_ok=True)
        logger = StageLogger(cfg.paths.stage_log(key), echo=False)
        try:
            with capture_output(logger):
                reports[key] = STAGES[key](cfg, logger).run() or {}
        finally:
            logger.close()
    return cfg, reports, keys


@needs_engine
def test_smoke_default_no_extra_rounds(tmp_path):
    cfg, reports, keys = _run_pipeline(tmp_path)
    assert "layout" in keys
    assert "replace_preprocess" not in keys
    assert "replace_strict" not in keys
    assert "replace_zhuyin" not in keys
    text = cfg.replace_after().read_text(encoding="utf-8")
    assert len(re.findall(r"[\u4e00-\u9fff]\[[A-Za-z]", text)) == 0
    bags_used = (reports["replace"].get("derived_rules") or {}).get("bag_ids") or []
    assert "normal" in bags_used
    assert "cjk_recover" in bags_used
    assert "strict" not in bags_used
    assert "zhuyin" not in bags_used


@needs_engine
def test_smoke_preprocess_only(tmp_path):
    _, reports, keys = _run_pipeline(tmp_path, enable_preprocess=True)
    assert "replace_preprocess" in keys
    assert (reports["replace_preprocess"].get("derived_rules") or {}).get(
        "bag_ids"
    ) == ["preprocess"]


@needs_engine
def test_smoke_strict_only(tmp_path):
    _, reports, keys = _run_pipeline(tmp_path, enable_strict=True)
    assert "replace_strict" in keys
    assert (reports["replace_strict"].get("derived_rules") or {}).get("bag_ids") == [
        "strict"
    ]


@needs_engine
def test_smoke_zhuyin_after_main_and_after_raw(tmp_path):
    cfg, reports, keys = _run_pipeline(tmp_path, zhuyin_mode="0")
    assert keys.index("replace") < keys.index("replace_zhuyin")
    zhu = reports["replace_zhuyin"]
    assert zhu.get("count") == 1
    assert (zhu.get("derived_rules") or {}).get("bag_ids") == ["zhuyin"]
    raw = cfg.replace_after_raw()
    assert raw.is_file()
    raw_text = raw.read_text(encoding="utf-8")
    after_text = cfg.replace_after().read_text(encoding="utf-8")
    assert raw_text != after_text or "[" not in after_text


@needs_engine
def test_smoke_skip_layout(tmp_path):
    _, _, keys = _run_pipeline(tmp_path, skip_layout=True)
    assert "layout" not in keys
    assert keys[0] == "merge" and keys[1] == "replace"
