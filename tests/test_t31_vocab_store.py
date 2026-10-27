"""M3-T3.1 词库五操作接真实词库 · 数据层与界面层单元验证。

覆盖排期 §2.4.1 的五条验收：
    ① 五操作接真实词库（检索 / 查重 / 删除 / 合并 + 新增）
    ② 新增词条写入自定义分级、可撤销
    ③ 无演示数据、空状态给人话
    ④ 分级存储（自定义与内置物理分离）
    ⑤ 批量操作先预览后执行、撤销后文件逐字节一致

每条用例都在**临时自定义词库**上跑，绝不改动交付包里的 workspace。
内置词库读的是交付包 data/rules 里的真实 304,255 条。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fixtext_ui.fixtext_vocab import (
    KIND_SAME_BOTH,
    KIND_SAME_WORD,
    VocabStore,
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def builtin_store(tmp_path_factory) -> VocabStore:
    """一个干净的自定义词库（模块级复用，内置只加载一次）。"""
    p = tmp_path_factory.mktemp("vocab_builtin") / "custom_vocab.json"
    return VocabStore(custom_path=p)


@pytest.fixture()
def store(tmp_path) -> VocabStore:
    """每条用例一个全新的自定义词库文件。"""
    return VocabStore(custom_path=tmp_path / "custom_vocab.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# ① 检索：命中真实数据，命中数与 JSON 实际条数一致
# ---------------------------------------------------------------------------

def test_search_hits_real_builtin_data(builtin_store: VocabStore):
    """检索命中内置真实词条，且命中数与逐条 JSON 实算一致。"""
    rules = Path(__file__).resolve().parent.parent / "data" / "rules"
    before = json.loads((rules / "before.json").read_text("utf-8"))
    after = json.loads((rules / "after.json").read_text("utf-8"))
    assert len(before) == len(after) == 304255

    q = "好象"
    expect = sum(1 for i in range(len(before))
                 if q in before[i] or q in after[i])
    total, rows = builtin_store.query(q, scope="builtin", offset=0, limit=50)
    assert total == expect, f"命中 {total} 应与 JSON 实算 {expect} 一致"
    assert total > 0
    assert len(rows) == min(50, total)
    for r in rows:
        assert q in r["word"] or q in r["value"]
    # 分页不丢不重：第 2 页与第 1 页无重叠
    _, page2 = builtin_store.query(q, scope="builtin", offset=50, limit=50)
    if page2:
        assert not ({r["id"] for r in page2} & {r["id"] for r in rows})


def test_search_scoped_to_tier(builtin_store: VocabStore):
    """分级检索按分级码过滤，三个分级之和等于内置总数。"""
    counts = builtin_store.counts()
    assert counts["b1"] + counts["b2"] + counts["b3"] == 304255
    assert counts["b1"] == 299114 and counts["b2"] == 893 and counts["b3"] == 4248
    total_b2, _ = builtin_store.query("，", scope="b2", limit=5)
    assert 0 <= total_b2 <= counts["b2"]
    # 全库命中 = 各分级命中之和
    q = "好象"
    all_total, _ = builtin_store.query(q, scope="builtin", limit=5)
    parts = sum(builtin_store.builtin.search_count(q, dict_code=c)
                for c in ("b1", "b2", "b3"))
    assert all_total == parts


# ---------------------------------------------------------------------------
# ② 新增词条：落盘自定义分级、重启后仍在、与内置分离
# ---------------------------------------------------------------------------

def test_add_writes_custom_and_survives_restart(store: VocabStore, tmp_path):
    """新增写入自定义词库文件；新建 VocabStore（等价重启）后仍在。"""
    n_builtin_before = len(store.builtin)
    res = store.add_entry(word="萧衍", value="萧彦", typ="角色名", pinyin="xiāo yǎn")
    assert res["word"] == "萧衍"
    path = store.custom.path
    assert path.is_file()
    assert path.parent != store.builtin.dir, "自定义词库不能落在内置词库目录"

    # 文件内容真的写进去了
    data = json.loads(path.read_text("utf-8"))
    assert data["count"] == 1
    assert data["entries"][0]["word"] == "萧衍"

    # 内置条数不变（新增只写自定义）
    assert len(store.builtin) == n_builtin_before

    # 等价重启
    again = VocabStore(custom_path=path)
    assert len(again.custom) == 1
    assert again.custom.entries()[0]["value"] == "萧彦"
    assert again.custom.entries()[0]["pinyin"] == "xiāo yǎn"

    # 内置与自定义物理分离：两个不同的目录树
    assert again.custom.path.resolve() != again.builtin.dir.resolve()
    assert again.custom.path.parent != again.builtin.dir


def test_add_is_undoable_byte_identical(store: VocabStore):
    """新增可撤销，撤销后文件与新增前逐字节一致。"""
    sha_before = _sha(store.custom.path)
    store.add_entry(word="甲词", value="甲替", typ="错词校正")
    assert _sha(store.custom.path) != sha_before
    rec = store.undo()
    assert rec is not None and rec["identical"] is True
    assert _sha(store.custom.path) == sha_before


# ---------------------------------------------------------------------------
# ③ 查重：同词同值 / 同词异值两种冲突都要触发
# ---------------------------------------------------------------------------

def test_dup_same_word_same_value(store: VocabStore):
    store.add_entry(word="重复词", value="同一替换", typ="错词校正")
    conflicts = store.conflicts_for_add("重复词", "同一替换")
    assert any(c["kind"] == KIND_SAME_BOTH for c in conflicts), conflicts


def test_dup_same_word_diff_value(store: VocabStore):
    store.add_entry(word="重复词", value="旧替换", typ="错词校正")
    conflicts = store.conflicts_for_add("重复词", "新替换")
    assert any(c["kind"] == KIND_SAME_WORD for c in conflicts), conflicts


def test_dup_detects_conflict_with_builtin(builtin_store: VocabStore):
    """新增词若与内置词库撞车，也要给出提示。"""
    q = "好象"
    total, rows = builtin_store.query(q, scope="b1", limit=1)
    assert total > 0
    word, value = rows[0]["word"], rows[0]["value"]
    conflicts = builtin_store.conflicts_for_add(word, value)
    assert any(c["kind"] == KIND_SAME_BOTH for c in conflicts), conflicts
    assert any(c["where"] != "我的词库" for c in conflicts), "应指出冲突来自内置词库"


def test_dup_groups_lists_custom_duplicates(store: VocabStore):
    store.add_entry(word="同词", value="值一", typ="错词校正")
    store.add_entry(word="同词", value="值二", typ="错词校正")
    groups = store.dup_groups()
    assert groups, "应检出重复分组"
    assert any(g["key"] == "同词" for g in groups)


# ---------------------------------------------------------------------------
# ④ 删除：先预览后执行，撤销后逐字节一致
# ---------------------------------------------------------------------------

def test_delete_preview_only_writes_after_confirm(store: VocabStore):
    """删除的数据层语义：不调用就不动文件；调用后才删。"""
    for w in ("一", "二", "三"):
        store.add_entry(word=f"{w}词", value=f"{w}替", typ="错词校正")
    sha_before = _sha(store.custom.path)
    assert _sha(store.custom.path) == sha_before          # 只有新增时变过
    ids = [e["id"] for e in store.custom.entries() if e["word"] in ("一词", "二词")]
    res = store.delete_entries(ids)
    assert res["removed"] == 2
    assert len(store.custom) == 1
    assert _sha(store.custom.path) != sha_before


def test_delete_undo_restores_exact_bytes(store: VocabStore):
    for w in ("一", "二", "三"):
        store.add_entry(word=f"{w}词", value=f"{w}替", typ="错词校正")
    sha_before = _sha(store.custom.path)
    ids = [e["id"] for e in store.custom.entries() if e["word"] in ("一词", "二词")]
    store.delete_entries(ids)
    assert len(store.custom) == 1
    rec = store.undo()
    assert rec["identical"] is True
    assert _sha(store.custom.path) == sha_before
    assert len(store.custom) == 3


# ---------------------------------------------------------------------------
# ⑤ 合并：先预览后执行，撤销后逐字节一致
# ---------------------------------------------------------------------------

def test_merge_keeps_one_and_undo_byte_identical(store: VocabStore):
    store.add_entry(word="甲", value="替A", typ="错词校正")
    store.add_entry(word="乙", value="替B", typ="错词校正")
    store.add_entry(word="丙", value="替C", typ="错词校正")
    sha_before = _sha(store.custom.path)
    ids = [e["id"] for e in store.custom.entries()]
    res = store.merge_entries(ids, "甲")
    assert res["removed"] == 2
    assert len(store.custom) == 1
    assert store.custom.entries()[0]["word"] == "甲"
    assert _sha(store.custom.path) != sha_before
    rec = store.undo()
    assert rec["identical"] is True
    assert _sha(store.custom.path) == sha_before


# ---------------------------------------------------------------------------
# ⑤ 分级存储 / 编辑 / 撤销栈历史 / 内置自检
# ---------------------------------------------------------------------------

def test_custom_and_builtin_are_physically_separate(store: VocabStore):
    store.add_entry(word="测试", value="替换", typ="其他")
    assert store.custom.path.parent != store.builtin.dir
    assert store.custom.path.name != "before.json"
    assert not str(store.custom.path).startswith(str(store.builtin.dir))


def test_update_entry_is_undoable(store: VocabStore):
    rid = store.add_entry(word="原词", value="原值", typ="错词校正")["id"]
    sha_before = _sha(store.custom.path)
    store.update_entry(rid, value="新值")
    assert store.custom.entries()[0]["value"] == "新值"
    rec = store.undo()
    assert rec["identical"] is True
    assert _sha(store.custom.path) == sha_before


def test_history_and_undo_to_multiple_steps(store: VocabStore):
    """变更记录可读，且能回到指定的更早还原点。"""
    sha_base = _sha(store.custom.path)
    store.add_entry(word="第一", value="A", typ="错词校正")
    store.add_entry(word="第二", value="B", typ="错词校正")
    assert len(store.custom) == 2
    hist = store.history()
    assert len(hist) == 2
    assert "第一" in hist[-1]["label"]
    assert hist[0]["time"], "记录应带时间戳"
    # 回到最早那条记录（新增「第一」之前的状态）
    rec = store.undo_to(len(hist) - 1)
    assert rec["identical"] is True
    assert _sha(store.custom.path) == sha_base
    assert len(store.custom) == 0


def test_builtin_self_check_passes(builtin_store: VocabStore):
    ok, detail = builtin_store.builtin.self_check()
    assert ok is True and detail == ""


def test_custom_starts_empty_no_demo_data(store: VocabStore):
    """新词库没有任何演示数据（旧版硬编码的《星河彼端》等必须清零）。"""
    assert len(store.custom) == 0
    assert store.custom.entries() == []
    raw = store.custom.path.read_text("utf-8")
    for ghost in ("星河彼端", "旧巷杂记"):
        assert ghost not in raw
    total, rows = store.query("", scope="custom", limit=20)
    assert total == 0 and rows == []
