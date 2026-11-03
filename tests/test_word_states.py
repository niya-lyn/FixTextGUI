# -*- coding: utf-8 -*-
"""V1.1-T1.1 · 词条启用 / 禁用的数据层与变更识别。

判据（对应排期 7.4 定稿的验收口径）：

* **契约一致**：fixtext_ui 与 fixtext_pipeline 两棵子树的 ``entry_key``、
  默认禁用集路径必须逐字节相同（否则两棵树各说各话）；
* **迁入数据**：出厂迁入文件可解析、条数 5,840、键不重复、孤儿词条
  「费劲思量→费尽思量」在初始禁用集里（误迁在用 → 默认禁用）；
* **只读边界**：数据层全部读写操作之后，出厂词库与出厂迁入数据 sha 不变；
* **独立接口**：「恢复默认状态」与「清空禁用」是两个操作，结果可区分、都可撤销；
* **变更识别**：改禁用状态 → 替换阶段指纹变化 → ``_should_skip`` 判
  「输入指纹已变」→ 断点不复用旧正文。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui", PKG / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_word_states import (  # noqa: E402
    WordStateStore as UIWordStateStore,
    entry_key as ui_entry_key,
)
from fixtext_pipeline import word_states as pipe_ws  # noqa: E402

RULES = PKG / "data" / "rules"
BUILTIN_STATES = PKG / "data" / "word_states" / "builtin_states.json"

#: 迁入口径的锁定值（排期 7.4：约 6,000 条；实测去重 5,840）
IMPORTED_TOTAL = 5840

ORPHAN_WORD, ORPHAN_VALUE = "费劲思量", "费尽思量"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# 契约：两棵子树必须同口径
# ---------------------------------------------------------------------------

def test_contract_entry_key_identical():
    """UI 侧与管线侧的词条键实现必须逐字节一致。"""
    samples = [
        ("萧衍", "萧彦"), ("费劲思量", "费尽思量"), ("", ""),
        ("a\x00b", "c"), ("多字节", "繁體字"), ("x" * 500, "y" * 500),
    ]
    for w, v in samples:
        assert ui_entry_key(w, v) == pipe_ws.entry_key(w, v)


def test_contract_default_paths_identical():
    """两棵子树解析出的默认禁用集文件必须是同一个路径（唯一一份）。"""
    assert UIWordStateStore().path == pipe_ws.default_states_path()
    assert BUILTIN_STATES == pipe_ws.builtin_states_path()


def test_contract_sha_matches_pipeline():
    """UI 侧 store 算出的有效禁用集指纹 == 管线侧 effective_disabled_sha。"""
    store = UIWordStateStore()
    assert store.sha() == pipe_ws.effective_disabled_sha(store.path)


# ---------------------------------------------------------------------------
# 键定位：内容哈希，不依赖行号 / 顺序
# ---------------------------------------------------------------------------

def test_entry_key_is_content_hash():
    k = ui_entry_key("萧衍", "萧彦")
    assert len(k) == 64 and int(k, 16) >= 0     # sha256 hex
    assert ui_entry_key("萧衍", "萧彦") == k      # 稳定
    assert ui_entry_key("萧彦", "萧衍") != k      # 词与值不分家
    assert ui_entry_key("萧衍", "萧") != ui_entry_key("萧", "衍")  # 无分隔歧义


def test_entry_key_independent_of_order():
    """同一批词条无论什么顺序算键，集合一致——禁用状态不依赖词库顺序。"""
    pairs = [("a", "1"), ("b", "2"), ("c", "3")]
    s1 = {ui_entry_key(w, v) for w, v in pairs}
    s2 = {ui_entry_key(w, v) for w, v in reversed(pairs)}
    assert s1 == s2


# ---------------------------------------------------------------------------
# 迁入数据：数量、去重、孤儿处置
# ---------------------------------------------------------------------------

def test_builtin_migration_data_integrity():
    data = json.loads(BUILTIN_STATES.read_text(encoding="utf-8"))
    entries = data["entries"]
    assert len(entries) == IMPORTED_TOTAL
    keys = [ui_entry_key(e["word"], e["value"]) for e in entries]
    assert len(set(keys)) == IMPORTED_TOTAL      # 键不重复（去重过）
    # 每条都带来源定位（word/value/src/line），可回到 PHP 源核对
    for e in entries[:50]:
        assert e["word"] and e["src"] and int(e["line"]) > 0
    # 孤儿词条记录在 orphans，且默认禁用
    orphans = data["orphans"]
    assert any(o["word"] == ORPHAN_WORD and o["value"] == ORPHAN_VALUE
               for o in orphans)


def test_orphan_word_disabled_by_default(tmp_path):
    """孤儿词条「费劲思量→费尽思量」：初始即禁用（不参与校正）。"""
    store = UIWordStateStore(writable_path=tmp_path / "word_states.json")
    assert store.is_disabled(ORPHAN_WORD, ORPHAN_VALUE)
    assert ui_entry_key(ORPHAN_WORD, ORPHAN_VALUE) in store.initial_disabled_keys()


def test_initial_disabled_equals_imported_plus_orphans():
    store = UIWordStateStore()
    expected = {ui_entry_key(e["word"], e["value"]) for e in store.imported_entries()}
    expected.update(ui_entry_key(o["word"], o["value"]) for o in store.orphan_entries())
    assert store.initial_disabled_keys() == frozenset(expected)
    assert len(expected) == IMPORTED_TOTAL + 1


def test_imported_entries_all_disabled_by_default(tmp_path):
    """迁入词条按口径默认禁用（词条可见、可自行启用、默认不参与校正）。"""
    store = UIWordStateStore(writable_path=tmp_path / "word_states.json")
    for e in store.imported_entries()[:200]:
        assert store.is_disabled(e["word"], e["value"])


# ---------------------------------------------------------------------------
# WordStateStore：读写、回落、「恢复默认」与「清空禁用」分离
# ---------------------------------------------------------------------------

@pytest.fixture()
def store(tmp_path):
    return UIWordStateStore(writable_path=tmp_path / "word_states.json")


def test_no_user_file_falls_back_to_initial(store):
    assert not store.path.is_file()
    assert store.effective_disabled() == store.initial_disabled_keys()
    assert store.disabled_count() == IMPORTED_TOTAL + 1


def test_set_enabled_writes_user_file(store):
    e = store.imported_entries()[0]
    r = store.set_enabled([(e["word"], e["value"])], enabled=True)
    assert r["changed"] == 1
    assert store.path.is_file()
    assert not store.is_disabled(e["word"], e["value"])
    assert store.disabled_count() == IMPORTED_TOTAL  # 少了一条
    # 再禁用回来
    r2 = store.set_enabled([(e["word"], e["value"])], enabled=False)
    assert r2["changed"] == 1
    assert store.is_disabled(e["word"], e["value"])


def test_corrupt_user_file_falls_back_to_initial(store):
    store.set_enabled([], enabled=True)             # 产生一份合法文件
    store.path.write_text("{ 不是 JSON", encoding="utf-8")
    assert store.effective_disabled() == store.initial_disabled_keys()


def test_clear_disabled_is_distinct_from_reset(store):
    """「清空禁用」→ 空集；「恢复默认状态」→ 初始集。两个独立操作。"""
    r_clear = store.clear_disabled()
    assert r_clear["disabled_total"] == 0
    assert store.disabled_count() == 0
    assert not store.is_disabled(ORPHAN_WORD, ORPHAN_VALUE)
    cleared_bytes = store.raw_bytes()

    r_reset = store.reset_to_default()
    assert r_reset["disabled_total"] == IMPORTED_TOTAL + 1
    assert store.is_disabled(ORPHAN_WORD, ORPHAN_VALUE)
    # 清空后的文件内容 ≠ 恢复后的文件内容（不是同一个操作的两份叫法）
    assert store.raw_bytes() != cleared_bytes


def test_raw_bytes_restore_roundtrip(store):
    """撤销栈接口：留存字节 → 改动 → 写回 = 回到改动前。"""
    store.set_enabled([("萧衍", "萧彦")], enabled=False)
    raw = store.raw_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    store.clear_disabled()
    assert store.raw_bytes() != raw
    store.restore(raw)
    assert hashlib.sha256(store.raw_bytes()).hexdigest() == sha


def test_restore_empty_bytes_removes_file(store):
    store.set_enabled([("萧衍", "萧彦")], enabled=False)
    assert store.path.is_file()
    store.restore(b"")                              # 「操作前文件不存在」
    assert not store.path.is_file()
    assert store.effective_disabled() == store.initial_disabled_keys()


# ---------------------------------------------------------------------------
# 出厂只读边界
# ---------------------------------------------------------------------------

def test_factory_files_untouched_by_all_ops(store, tmp_path):
    """全部读写操作后：出厂词库五件套 + 出厂迁入数据 sha 一致。"""
    rules_files = ["before.json", "after.json", "builtin_tiers.bin",
                   "builtin_marks.json", "builtin_index_meta.json"]
    before = {n: _sha(RULES / n) for n in rules_files}
    builtin_sha = _sha(BUILTIN_STATES)

    store.set_enabled([("萧衍", "萧彦")], enabled=False)
    store.clear_disabled()
    store.reset_to_default()
    store.set_enabled([("测试", "测试")], enabled=True)

    assert all(_sha(RULES / n) == before[n] for n in rules_files)
    assert _sha(BUILTIN_STATES) == builtin_sha


# ---------------------------------------------------------------------------
# VocabStore 集成：撤销栈复用 + 独立接口
# ---------------------------------------------------------------------------

@pytest.fixture()
def vstore(tmp_path):
    from fixtext_vocab import VocabStore

    return VocabStore(custom_path=tmp_path / "vocab" / "custom_vocab.json")


def test_store_set_entries_enabled_creates_undoable_point(vstore):
    e = vstore.states.imported_entries()[0]
    assert vstore.entry_enabled(e["word"], e["value"]) is False   # 默认禁用
    r = vstore.set_entries_enabled([(e["word"], e["value"])], enabled=True)
    assert r["changed"] == 1
    assert vstore.entry_enabled(e["word"], e["value"]) is True
    assert vstore.can_undo
    # 操作历史有这条记录，动作用人话代号
    ops = vstore.ops(limit=3)
    assert ops[0]["act"] == "enable"


def test_undo_restores_disabled_set(vstore):
    e = vstore.states.imported_entries()[0]
    sha_before = vstore.states.sha()
    vstore.set_entries_enabled([(e["word"], e["value"])], enabled=True)
    assert vstore.states.sha() != sha_before
    r = vstore.undo()
    assert r is not None
    assert vstore.states.sha() == sha_before
    assert vstore.entry_enabled(e["word"], e["value"]) is False


def test_clear_and_reset_via_store_are_independent_ops(vstore):
    vstore.clear_disabled_entries()
    assert vstore.states.disabled_count() == 0
    vstore.reset_word_states_default()
    assert vstore.states.disabled_count() == IMPORTED_TOTAL + 1
    # 各自可撤销：撤销「恢复默认状态」→ 回到清空后的状态
    vstore.undo()
    assert vstore.states.disabled_count() == 0


def test_word_states_summary_shape(vstore):
    s = vstore.word_states_summary()
    assert s["imported_total"] == IMPORTED_TOTAL
    assert s["orphan_total"] == 1
    assert s["disabled_total"] == IMPORTED_TOTAL + 1
    assert s["imported_disabled"] == IMPORTED_TOTAL
    assert s["has_user_file"] is False


# ---------------------------------------------------------------------------
# 变更识别：指纹含禁用集 → 断点不复用旧正文
# ---------------------------------------------------------------------------

def _make_cfg(tmp_path, states_path):
    from fixtext_pipeline.config import PipelineConfig

    epub = tmp_path / "probe.epub"
    epub.write_bytes(b"PK\x03\x04empty")
    work = tmp_path / "run"
    work.mkdir(parents=True, exist_ok=True)
    return PipelineConfig(
        epub=epub, workdir=work,
        rules_before=RULES / "before.json",
        rules_after=RULES / "after.json",
        engine_path=tmp_path / "fake_engine",
        stages=("replace",), resume=True, force=False,
        custom_vocab_path=tmp_path / "custom.json",
        derived_rules_dir=tmp_path / "derived",
        word_states_path=states_path,
    )


def _fingerprint(cfg):
    from fixtext_pipeline.logsetup import StageLogger
    from fixtext_pipeline.stages.replace import ReplaceStage

    log = StageLogger(cfg.paths.stage_log("replace"), echo=False)
    try:
        return ReplaceStage(cfg, log).fingerprint()
    finally:
        log.close()


def test_fingerprint_changes_with_disabled_state(tmp_path):
    """改禁用状态 → 主轮替换指纹必须变（否则断点恢复误判缓存命中）。"""
    (tmp_path / "custom.json").write_text('{"entries": []}', encoding="utf-8")
    states = tmp_path / "word_states.json"
    cfg = _make_cfg(tmp_path, states)

    fp1 = _fingerprint(cfg)
    fp1b = _fingerprint(cfg)
    assert fp1 == fp1b                          # 不改状态时指纹稳定

    store = UIWordStateStore(writable_path=states)
    store.set_enabled([("萧衍", "萧彦")], enabled=False)   # 禁用一条词
    fp2 = _fingerprint(cfg)
    assert fp2 != fp1, "禁用状态改了而指纹没变 → 断点恢复会复用旧正文"

    store.clear_disabled()
    fp3 = _fingerprint(cfg)
    assert fp3 != fp2 and fp3 != fp1


def test_resume_rejects_stale_replace_after_disabled_change(tmp_path):
    """端到端断点判据：上次 done 的 replace 阶段，改了禁用状态后必须重跑。

    这是「指纹含禁用集」的存在理由：改了禁用状态但指纹不变的话，
    ``_should_skip`` 会判缓存命中，--resume 直接复用旧正文。
    """
    from fixtext_pipeline.runner import _should_skip
    from fixtext_pipeline.state import StateStore

    (tmp_path / "custom.json").write_text('{"entries": []}', encoding="utf-8")
    states = tmp_path / "word_states.json"
    cfg = _make_cfg(tmp_path, states)

    store = UIWordStateStore(writable_path=states)
    fp1 = _fingerprint(cfg)

    # 模拟上次运行：replace 阶段 done、指纹 fp1、产物齐全
    sstore = StateStore(cfg.paths.state_file)
    for out in ReplaceOutputs(cfg):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("旧正文", encoding="utf-8")
    sstore.mark("replace", status="done", fingerprint=fp1, outputs=[
        str(p) for p in ReplaceOutputs(cfg)])

    # 指纹未变 → 跳过（断点复用成立）
    skip, why = _should_skip(cfg, sstore, "replace", fp1)
    assert skip, why

    # 改禁用状态 → 指纹变 → 不跳过（必须重跑，不复用旧正文）
    store.set_enabled([("萧衍", "萧彦")], enabled=False)
    fp2 = _fingerprint(cfg)
    assert fp2 != fp1
    skip2, why2 = _should_skip(cfg, sstore, "replace", fp2)
    assert not skip2
    assert "指纹" in why2


def ReplaceOutputs(cfg):
    from fixtext_pipeline.stages.replace import ReplaceStage

    return ReplaceStage(cfg, _NullLog()).outputs()


class _NullLog:
    def log(self, *a, **k):  # pragma: no cover - outputs() 不打日志
        pass
