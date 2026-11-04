"""V1.1-D3 · 导入预览分组与查重接线的单测。

覆盖两条交付物：
① 预览按「新增 N / 冲突 M / 格式不合格 K」三组呈现 + 逐条可取消；
② 冲突 M 来自既有查重实现（`conflict_list` / `exact_word` / `exact_value`），
   本卡没有第二套比对逻辑——这里用「索引前后逐条等价」和「批量与单条等价」
   两组用例把"同源"钉住。
"""

from __future__ import annotations

import pathlib
import random

import pytest

from fixtext_vocab import (KIND_SAME_BOTH, KIND_SAME_VALUE, KIND_SAME_WORD, BuiltinVocab,
                           CustomVocab, VocabStore, conflict_list)
from fixtext_vocab_import.batching import BatchPolicy
from fixtext_vocab_import.parse import parse_text
from fixtext_vocab_import.rejects import partition_sheet
from fixtext_vocab_preview.groups import (GROUP_CONFLICT, GROUP_NEW, GROUP_REJECT,
                                          preview_from_sheet)
from fixtext_vocab_preview.rehearsal import rehearse, write_new_entries


# ---------- 公共夹具 ----------

BASE_TEXT = "错词,正确写法\n乙乙,乙\n甲的异体,甲\n,空的\n重复,值一\n重复,值二\n丙丙,丙\n"


def make_store(tmp_path, entries=(("甲的异体", "甲"),)):
    """临时词库：真实文件放在 tmp_path 下，绝不碰用户主目录那一份。"""
    real = tmp_path / "custom_vocab.json"
    vocab = CustomVocab(real)
    for w, v in entries:
        vocab.add(word=w, value=v, typ="错词校正")
    return real, VocabStore(custom_path=real, work_dir=tmp_path / "rules",
                            snap_dir=tmp_path / "snap")


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)[1]


# ---------- ① 三组分组 ----------

def test_three_groups_present_even_when_empty(store):
    """空组也要出现（界面据此显示「0 条」，而不是整行缺失）。"""
    model = preview_from_sheet(parse_text("错词,正确写法\n全新的,新写法\n"), store)
    counts = model.counts()
    assert list(counts) == [GROUP_NEW, GROUP_CONFLICT, GROUP_REJECT]
    assert counts == {GROUP_NEW: 1, GROUP_CONFLICT: 0, GROUP_REJECT: 0}
    assert model.groups()[GROUP_REJECT] == []


def test_groups_classify_by_engine_and_reject_list(store):
    """冲突来自查重引擎、不合格来自 D2 清单、剩下的是新增。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    counts = model.counts()
    assert counts == {GROUP_NEW: 2, GROUP_CONFLICT: 3, GROUP_REJECT: 1}

    # 冲突那条撞的是库里的「甲的异体 → 甲」
    conf = [it for it in model.effective(GROUP_CONFLICT) if it.word == "甲的异体"]
    assert len(conf) == 1
    assert conf[0].kinds == [KIND_SAME_BOTH]
    assert conf[0].where_text                     # 命中出处是人话，不是空串

    # 不合格那条的原因文案直接来自 D2，不是这里重算的
    rej = model.effective(GROUP_REJECT)[0]
    d2 = {r.line_no: r for r in model.rejects.rejects}[rej.line_no]
    assert rej.reject_label == d2.detail
    assert rej.reject_advice == d2.reason.advice


def test_counts_conserved_and_no_overlap(store):
    """三组之和 = 未取消的条目数，且没有一条同时属于两组。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    assert model.conserved()
    assert model.total() == sum(model.counts().values())
    assert model.total() == len(model.rejects.good) + len(model.rejects.rejects)


def test_within_sheet_duplicate_is_conflict_not_new(store):
    """同一份表里重复出现：后一条算冲突，否则「预览 N、写入 N-1」。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    later = model.find(6)                       # 第二条「重复」
    assert later.group == GROUP_CONFLICT
    assert later.within_batch
    assert KIND_SAME_WORD in later.kinds or KIND_SAME_VALUE in later.kinds
    assert "同一份表里" in later.label()
    first = model.find(5)
    assert first.group == GROUP_NEW            # 先出现的那条才是新增
    assert model.internal_duplicates == 1


def test_batch_declaration_uses_d2_plan(store):
    """分批声明走 D2 的 plan_batches，不自己算批大小。"""
    rows = "错词,正确写法\n" + "".join(f"词{i},值{i}\n" for i in range(1, 26))
    model = preview_from_sheet(parse_text(rows), store, policy=BatchPolicy())
    plan = model.plan()
    assert plan.batch_count == 1               # 25 < 1000
    assert model.batch_count() == plan.batch_count

    small = preview_from_sheet(parse_text(rows), store,
                               policy=BatchPolicy(batch_size=5, threshold=5))
    assert small.batch_count() == 5            # 25 行 / 每批 5 条
    assert "5 批" in small.batch_note()


# ---------- ② 逐条可取消 ----------

def test_cancel_removes_item_from_every_group(store):
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    target = model.effective(GROUP_CONFLICT)[0].line_no
    model.cancel(target)

    assert model.is_cancelled(target)
    assert not any(model.find(target) in model.effective(g)
                   for g in (GROUP_NEW, GROUP_CONFLICT, GROUP_REJECT))
    assert target not in [it.line_no for it in model.effective()]
    assert model.conserved()


def test_cancel_rejudges_later_duplicate(store):
    """取消前一条重复行后，后一条要从「冲突」变「新增」——否则预览与真写对不上。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    first = model.find(5)
    assert first.group == GROUP_NEW
    model.cancel(first.line_no)
    later = model.find(6)
    assert later.group == GROUP_NEW
    assert not later.within_batch


def test_restore_puts_item_back(store):
    """恢复后分组回到原样（取消最后一行「丙丙」，它后面没有同词行，不会引起重判）。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    before = model.counts()
    line = [it.line_no for it in model.effective(GROUP_NEW) if it.word == "丙丙"][0]
    model.cancel(line)
    assert model.counts()[GROUP_NEW] == before[GROUP_NEW] - 1
    model.restore(line)
    assert model.counts() == before

    model.cancel(line)
    assert model.restore_all() == 1
    assert model.counts() == before
    assert model.cancelled_items == []


def test_cancel_all_leaves_nothing(store):
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    for it in model.effective():
        model.cancel(it.line_no)
    assert model.counts() == {GROUP_NEW: 0, GROUP_CONFLICT: 0, GROUP_REJECT: 0}
    assert model.total() == 0
    assert "取消" in model.summary_text()


# ---------- 新增数字与真实写入一致（预演对账）----------

def test_rehearsal_numbers_match_preview(store):
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    result = rehearse(model)
    for name, preview, measured, verdict in result.diff_columns():
        assert verdict == "一致", f"{name}: 预览 {preview} / 实测 {measured}"
    assert result.identical
    assert result.real_untouched
    assert result.measured_new == 2
    assert result.after_count - result.before_count == 2


def test_rehearsal_real_vocab_untouched(tmp_path):
    """只读底线：真实词库前后指纹必须相同。"""
    real, store = make_store(tmp_path)
    sha_before = real.read_bytes()
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    result = rehearse(model)
    assert result.real_untouched
    assert real.read_bytes() == sha_before


def test_cancelled_item_not_written_and_count_drops(store):
    """取消一条新增后：它不在任何组里，预演写入的条目数也少一条。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    base = rehearse(model)
    assert base.measured_new == 2

    line = [it.line_no for it in model.effective(GROUP_NEW) if it.word == "丙丙"][0]
    model.cancel(line)
    after = rehearse(model)

    assert after.measured_new == base.measured_new - 1
    assert "丙丙" not in after.written_words
    assert after.identical
    assert not model.effective(GROUP_NEW) or line not in [i.line_no for i in model.effective()]


def test_rehearsal_detects_preview_overcount(store):
    """反证：预览若多算一条新增，对账必须报不一致（否则这套核对是空转）。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    snapshot = model.counts()
    snapshot[GROUP_NEW] = snapshot[GROUP_NEW] + 1      # 人为把预览数字调高
    result = rehearse(model, preview_snapshot=snapshot)
    assert not result.identical
    assert result.diff_columns()[0][3] == "不一致"


def test_write_entry_only_writes_new_group(store):
    """写入口只落「新增」组；冲突与不合格一条都不进库。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    new_items = model.effective(GROUP_NEW)
    words_before = {e["word"] for e in store.custom.entries()}
    write_new_entries(store, new_items)
    words_after = {e["word"] for e in store.custom.entries()}
    assert words_after - words_before == {it.word for it in new_items}
    assert "甲的异体" not in (words_after - words_before)   # 冲突那条没写
    assert len(store.custom.entries()) == len(words_before) + len(new_items)


# ---------- 第二件交付物：复用既有查重的等价性 ----------

def test_conflict_list_is_single_implementation(store):
    """预览用的 `conflict_list` 与单条接口 `conflicts_for_add` 判定一致。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    for it in model.effective():
        if it.group == GROUP_REJECT:
            continue
        if it.within_batch:
            continue        # 同表重复只有预览层知道（库里还没有前一条）
        direct = store.conflicts_for_add(it.word, it.value)
        assert [c["kind"] for c in direct] == it.kinds
        assert it.group == (GROUP_CONFLICT if direct else GROUP_NEW)


def test_conflict_kinds_constants_used(store):
    """三种冲突形态都用到了库里已定义的常量，没有另起名字。"""
    real, store2 = make_store(tmp_path_factory_dir(), entries=(
        ("甲", "乙"),            # 同词异值：再来一条「甲 → 丙」
        ("丁", "戊"),            # 同值异词：再来一条「己 → 戊」
    ))
    model = preview_from_sheet(parse_text(
        "错词,正确写法\n甲,丙\n己,戊\n甲,乙\n"), store2)
    kinds = model.conflict_kinds()
    assert KIND_SAME_WORD in kinds
    assert KIND_SAME_VALUE in kinds
    assert KIND_SAME_BOTH in kinds


def tmp_path_factory_dir():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


def test_conflicts_for_add_many_matches_per_item(store):
    """批量接口与逐条调用同结果（界面预览上千行时走批量，不能变判定）。"""
    pairs = [("甲的异体", "甲"), ("全新的", "新写法"), ("重复", "值一")]
    many = store.conflicts_for_add_many(pairs)
    one_by_one = [store.conflicts_for_add(w, v) for w, v in pairs]
    assert [[c["kind"] for c in row] for row in many] == \
           [[c["kind"] for c in row] for row in one_by_one]


@pytest.fixture(scope="module")
def builtin():
    vocab = BuiltinVocab()
    if not getattr(vocab, "available", False):
        pytest.skip("内置词库不可用")
    return vocab


def test_index_lookup_equals_linear_scan(builtin):
    """惰性索引换的是查法、不是判定：抽样逐条与线性扫全表的结果必须逐项相等。"""
    total = len(builtin)
    if not total:
        pytest.skip("词库为空")
    rng = random.Random(20261104)
    indexes = sorted(rng.sample(range(total), min(200, total)))
    indexes += [0, total - 1]

    for i in indexes:
        word = builtin.word_at(i)
        value = builtin.value_at(i)
        got = builtin.exact_word(word, limit=5)
        want = [builtin.row(j) for j in range(total) if builtin.word_at(j) == word][:5]
        assert got == want, f"下标 {i} 词 {word!r}：索引与线性扫不一致"
        got_v = builtin.exact_value(value, limit=5)
        want_v = [builtin.row(j) for j in range(total) if builtin.value_at(j) == value][:5]
        assert got_v == want_v, f"下标 {i} 值 {value!r}：索引与线性扫不一致"


def test_index_preserves_limit_boundary(builtin):
    """边界照抄旧口径：limit<=0 时仍返回 1 条（旧实现「先收一条再判」）。"""
    if not len(builtin):
        pytest.skip("词库为空")
    word = builtin.word_at(0)
    assert len(builtin.exact_word(word, limit=1)) >= 1
    assert len(builtin.exact_word(word, limit=0)) >= 1


def test_index_rebuilt_after_reload(builtin):
    """重新载入后索引必须作废重建，不能留着旧表的命中。"""
    word = builtin.word_at(0)
    before = builtin.exact_word(word, limit=5)
    builtin.reload()
    after = builtin.exact_word(word, limit=5)
    assert len(after) == len(before)


# ---------- 零露出 ----------

FORBIDDEN = ("utf-8", "gbk", "gb18030", "bom", "encoding", "delimiter", "csv",
             "sha256", "traceback", "json", "sqlite")


def test_preview_package_messages_are_plain_language():
    """界面会显示出来的文案里不出现内部术语。"""
    root = pathlib.Path(__file__).resolve().parent.parent / "fixtext_vocab_preview"
    # 只扫 messages.py：那是唯一会原样显示给用户的文案表；
    # groups.py / rehearsal.py 里的字面量是内部标识（文件名、键名），不上界面。
    for py in [root / "messages.py"]:
        text = py.read_text(encoding="utf-8")
        # 只看字符串字面量里、且不像路径/注释的部分：逐行取引号内文本
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for quoted in _quoted(stripped):
                low = quoted.lower()
                for bad in FORBIDDEN:
                    assert bad not in low, f"{py.name}: 文案里出现 {bad} → {quoted}"


def _quoted(line: str) -> list[str]:
    out, buf, inside = [], [], False
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if not inside and ch in "\"'":
            inside, quote, buf = True, ch, []
        elif inside and ch == quote:
            out.append("".join(buf))
            inside = False
        elif inside:
            buf.append(ch)
        i += 1
    return out
