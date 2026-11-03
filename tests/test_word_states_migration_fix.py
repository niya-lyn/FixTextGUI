# -*- coding: utf-8 -*-
"""V1.1-T1.1 迁入数据的缺陷回归（小组长核验时发现的两处内容错误）。

背景：迁入首版总数恰好 5,840（与独立重算相同），但其中一条是解析伪影、
另一条应与迁入却缺失，两条数量互抵、掩盖了内容错误。这里锁住正确口径：

* 迁入集合 = 「PHP 注释态词条」中 **before 词面不出现在任何活动词条** 的去重集；
* 伪影不得进档：``'硬梆梆"'``（源行引号不配对导致的解析残留）不在迁入集，
  它在 3.txtFormat 活动态有用，应保持现状；
* 用 ``#`` 注释（PHP 合法单行注释）的词条同样算注释态，不得漏迁；
* 迁入词条不得与在用规则**同键**——否则「禁用某条」会连带停掉一条活规则。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui", PKG / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_word_states import entry_key, WordStateStore  # noqa: E402

STATES = PKG / "data" / "word_states" / "builtin_states.json"
BEFORE = PKG / "data" / "rules" / "before.json"
AFTER = PKG / "data" / "rules" / "after.json"


def _entries():
    return json.loads(STATES.read_text(encoding="utf-8"))["entries"]


def _live_pairs():
    b = json.loads(BEFORE.read_text(encoding="utf-8"))
    a = json.loads(AFTER.read_text(encoding="utf-8"))
    return set(zip(b, a)), set(b), set(a)


def test_no_quote_artifact_migrated():
    """解析伪影不得进档：'硬梆梆"' 不在迁入集。"""
    words = [e["word"] for e in _entries()]
    assert '硬梆梆"' not in words
    # 原文 硬梆梆 在用（3.txtFormat 活动态），按口径应「保持现状不动」
    pairs, _, _ = _live_pairs()
    assert ("硬梆梆", "硬邦邦") in pairs
    assert not any(w == "硬梆梆" for w in words)


def test_hash_comment_entry_migrated():
    """用 # 注释的词条也是注释态，必须迁入（早闪人了 两个源文件都是注释态）。"""
    pairs = {(e["word"], e["value"]) for e in _entries()}
    assert ("早闪人了", "早闪入了") in pairs
    live, _, _ = _live_pairs()
    assert ("早闪人了", "早闪入了") not in live          # 无在用出处


def test_no_migrated_pair_collides_with_live_rule():
    """安全底线：迁入词条不得与在用规则同键（否则禁用会连带停掉活规则）。"""
    live, _, _ = _live_pairs()
    live_keys = {entry_key(w, v) for w, v in live}
    collided = [e for e in _entries() if entry_key(e["word"], e["value"]) in live_keys]
    assert collided == [], f"与在用规则同键：{collided[:5]}"


def test_no_quote_or_control_chars_migrated():
    """迁入词条不得含引号 / 反斜杠 / 控制字符（解析伪影的典型特征）。

    注意：源库本身存在「首尾带空格 / 全角空格」的合法词条（如 ``" 之罪"``、
    ``"\\u3000反到是"``），那是作者写法，不属伪影，不能用 strip 判。
    """
    import re

    bad = [e for e in _entries()
           if re.search(r'["\'`\\]', e["word"] + e["value"])
           or re.search(r"[\x00-\x1f\x7f]", e["word"] + e["value"])]
    assert bad == [], f"畸形条目：{bad[:5]}"


def test_migrated_entries_are_unique_and_locatable():
    """迁入集无重复，且每条都带可回指的来源定位（文件 + 行号）。"""
    entries = _entries()
    shipped = {(e["word"], e["value"]) for e in entries}
    assert len(shipped) == len(entries)                  # 无重复
    assert all(e["src"].endswith(".php") and int(e["line"]) > 0 for e in entries)
    assert all(e["word"] and e["value"] for e in entries)


def test_migrated_count_and_keys():
    """数量口径：迁入条数 5,840、键唯一 5,840。

    只比总数会漏掉「一条错迁 + 一条漏迁」互抵的情形，故本用例配合
    test_no_quote_artifact_migrated / test_hash_comment_entry_migrated
    （内容逐条核对）一起构成判据。
    """
    entries = _entries()
    assert len(entries) == 5840
    assert len({entry_key(e["word"], e["value"]) for e in entries}) == 5840


def test_orphan_targets_live_rule_key():
    """孤儿词条「费劲思量→费尽思量」与在用规则同键：误迁在用，现改为默认禁用。

    这是唯一被允许「与在用规则同键」的条目——它本身就是被纠正的误迁项，
    进的是 orphans（默认禁用），不进 entries。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        store = WordStateStore(writable_path=Path(tmp) / "word_states.json")
        orphan = store.orphan_entries()[0]
        key = entry_key(orphan["word"], orphan["value"])
        live, _, _ = _live_pairs()
        assert (orphan["word"], orphan["value"]) in live     # 该条在用
        assert key in store.initial_disabled_keys()          # 但默认禁用
        assert store.is_disabled(orphan["word"], orphan["value"])
        # 孤儿不得同时出现在 entries（否则会重复计数）
        assert (orphan["word"], orphan["value"]) not in {
            (e["word"], e["value"]) for e in store.imported_entries()}
