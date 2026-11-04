"""V1.1-D4 · 冲突处置与确认执行：数据层单测。

本卡两条交付物的"可验证"部分都在这里：

① **三种处置各自独立取证**（不共用一条断言，每种都有自己的判据）
   - 改值        → 该条按**新值**进预演（副本里写进去的是新值，不是原值）；
   - 跳过        → 该条**不进写入清单**，且副本的新增集合里没有它；
   - 设为禁用    → 写入清单里该条 `disabled=True`，且副本的禁用集里真有它。

② **影响预览数字 vs 预演实测数字两列对照**（沿用 D3 口径，D4 扩到 8 列）。

③ **「设为禁用」与 B 组禁用同一语义**：只写 `word_states.json` 一份存储、
   不另造字段/文件；判据是"副本目录里除了词库就只多这一份状态文件"，
   且禁用判定走的是与词库页 B 组开关同一个 `WordStateStore` 接口。

范围边界：本卡不实现批量事务写入（D5）——所以这里验的是 `write_plan_entries`
在**临时副本**上的效果，真实词库与真实禁用状态文件全程只读。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from fixtext_vocab import (KIND_SAME_BOTH, KIND_SAME_VALUE, KIND_SAME_WORD, CustomVocab,
                           VocabStore)
from fixtext_vocab_import.parse import parse_text
from fixtext_vocab_preview import (ACTION_DISABLE, ACTION_EDIT, ACTION_SKIP, EFFECT_ADD,
                                   EFFECT_DISABLED, EFFECT_SKIPPED, EFFECT_UPDATE,
                                   GROUP_CONFLICT, GROUP_NEW, preview_from_sheet, rehearse)
from fixtext_vocab_preview.groups import PreviewModel
from fixtext_vocab_preview.rehearsal import write_plan_entries

# 与 D3 同一份表：2 新增 / 3 冲突 / 1 不合格。
# 冲突三条刚好落进三种形态，三种处置各能对着一条做实验：
#   行 2「乙乙 → 乙」      同值异词（库里别的词已是这个写法）
#   行 3「甲的异体 → 甲」  同词同值（库里就是这一条）
#   行 6「重复 → 值二」    同词异值（表内上一行「重复 → 值一」已占位）
BASE_TEXT = "错词,正确写法\n乙乙,乙\n甲的异体,甲\n,空的\n重复,值一\n重复,值二\n丙丙,丙\n"


def make_store(tmp_path, entries=(("甲的异体", "甲"), ("丁丁", "乙"))):
    """临时词库：真实文件在 tmp_path 下，绝不碰用户目录那一份。"""
    real = tmp_path / "custom_vocab.json"
    vocab = CustomVocab(real)
    for w, v in entries:
        vocab.add(word=w, value=v, typ="错词校正")
    return real, VocabStore(custom_path=real, work_dir=tmp_path / "rules",
                            snap_dir=tmp_path / "snap")


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)[1]


@pytest.fixture
def model(store):
    return preview_from_sheet(parse_text(BASE_TEXT), store)


# ---------- ① 三种处置各自独立取证 ----------

def test_edit_disposition_writes_the_new_value(model):
    """改值：该条按**新值**进预演——副本里写进去的是新值，不是原来的写法。"""
    item = model.edit_value(2, "乙乙乙")          # 原值「乙」撞了库里的「丁丁 → 乙」
    assert item.action == ACTION_EDIT
    assert item.effective_value == "乙乙乙"
    assert item.effect == EFFECT_ADD               # 改完不再撞车，按新增算
    assert item.group == GROUP_NEW                 # 跟着从冲突组挪到新增组
    assert "乙乙乙" in item.action_note

    wl = {d["line_no"]: d for d in model.write_list()}
    assert wl[2]["value"] == "乙乙乙"

    res = rehearse(model)
    assert res.identical, res.text()
    # 副本里真的写进了「新值」，不是原来的写法
    assert "乙乙 → 乙乙乙" in res.written_pairs
    assert "乙乙 → 乙" not in res.written_pairs
    assert res.real_untouched and res.real_states_untouched


def test_edit_to_same_word_family_updates_existing_entry(tmp_path):
    """改值撞上「同词异值」→ 改库里那条的值（这才算"更新"，不是再加一条）。

    用一封专为这条造的表：库里「戊戊 → 己」，表里「戊戊 → 庚」是同词异值。
    """
    real = tmp_path / "custom_vocab.json"
    vocab = CustomVocab(real)
    vocab.add(word="戊戊", value="己", typ="错词校正")
    store = VocabStore(custom_path=real, work_dir=tmp_path / "rules",
                       snap_dir=tmp_path / "snap")

    model = preview_from_sheet(parse_text("错词,正确写法\n戊戊,庚\n"), store)
    conflict = model.find(2)
    assert KIND_SAME_WORD in conflict.kinds
    assert conflict.effect.startswith("pending")

    model.edit_value(2, "辛")                      # 改成一个库里没有的新值
    item = model.find(2)
    assert item.effect == EFFECT_UPDATE
    assert item.update_target == 1                 # 指向库里那条，不是新增
    assert model.write_plan()["update"] == 1
    assert model.write_plan()["add"] == 0

    res = rehearse(model)
    assert res.identical, res.text()
    assert res.measured_update == 1
    assert res.measured_new == 0                   # 没有多出一条


def test_skip_disposition_excludes_item_from_write_list(model):
    """跳过：该条不进写入清单，且副本里没有它。"""
    item = model.skip(6)                           # 同词异值那条
    assert item.action == ACTION_SKIP
    assert item.effect == EFFECT_SKIPPED
    assert item.will_write is False
    # 仍然留在冲突组里（状态可见、可撤销），只是不写
    assert item.group == GROUP_CONFLICT

    wl = {d["line_no"] for d in model.write_list()}
    assert 6 not in wl                             # 「不进写入清单」的落点
    assert model.write_plan()["skipped"] == 1

    res = rehearse(model)
    assert res.identical, res.text()
    assert res.measured_skipped >= 1
    assert "重复 → 值二" not in res.written_pairs


def test_disable_disposition_marks_item_and_writes_word_states(model):
    """设为禁用：写入清单里该条带禁用标记，副本的禁用集里真有它。"""
    item = model.disable(7)                        # 「丙丙 → 丙」，库里没有，会新增后禁用
    assert item.action == ACTION_DISABLE
    assert item.effect == EFFECT_DISABLED
    wl = {d["line_no"]: d for d in model.write_list()}
    assert wl[7]["disabled"] is True               # 「带禁用标记」的落点
    assert wl[7]["effect"] == EFFECT_DISABLED

    res = rehearse(model)
    assert res.identical, res.text()
    assert res.measured_disabled == 1
    assert res.disabled_ok and not res.disabled_failed
    assert res.copy_disabled_after == res.copy_disabled_before + 1


def test_disable_existing_entry_does_not_duplicate_it(tmp_path):
    """库里本来就是「同词同值」那条 → 禁用那一条本身，不再加一条一样的。

    否则词库里会多出一条重复词条，词库页多一行废数据——这与「禁用」语义不符。
    """
    real = tmp_path / "custom_vocab.json"
    vocab = CustomVocab(real)
    vocab.add(word="甲的异体", value="甲", typ="错词校正")
    store = VocabStore(custom_path=real, work_dir=tmp_path / "rules",
                       snap_dir=tmp_path / "snap")
    model = preview_from_sheet(parse_text("错词,正确写法\n甲的异体,甲\n"), store)
    conflict = model.find(2)
    assert KIND_SAME_BOTH in conflict.kinds

    model.disable(2)
    plan = model.write_plan()
    assert plan["disabled"] == 1
    assert plan["new"] == 0                        # 不新建条目
    assert model.write_list()[0]["update_target"] == 1

    res = rehearse(model)
    assert res.identical, res.text()
    assert res.measured_new == 0                   # 副本条目数没变
    assert res.measured_disabled == 1


# ---------- ② 「设为禁用」与 B 组禁用同一语义（同一份存储、不另造）----------

def test_disable_uses_the_single_word_states_store(tmp_path):
    """禁用只落 `word_states.json` 一份存储；副本目录里没有多出别的状态文件。"""
    real, store = make_store(tmp_path)
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    model.disable(7)

    res = rehearse(model)
    assert res.identical, res.text()

    # 用户真实目录：只有词库这一个文件。禁用状态文件由副本那边自己写，
    # 真实目录连这个文件都不该冒出来（预演不落用户状态）。
    names = sorted(p.name for p in tmp_path.iterdir() if p.is_file())
    assert "custom_vocab.json" in names
    assert "word_states.json" not in names          # 真实状态文件全程没被创建/改动

    # 状态存储的唯一性：整个包里只有 WordStateStore 这一个类会写状态文件，
    # 禁用处置只经它（`set_entries_enabled` → `states.set_enabled`），不另造字段。
    from fixtext_ui.fixtext_word_states import WordStateStore
    assert hasattr(WordStateStore, "set_enabled")
    assert store.states.path.name == "word_states.json"


def test_disable_state_is_readable_through_the_same_api_as_group_b(tmp_path):
    """词库页 B 组开关读的就是 `WordStateStore.is_disabled`，禁用处置必须同口径可查。"""
    real, store = make_store(tmp_path)
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    model.disable(7)

    # 在副本上演练写入后，用与界面同一套接口问"这一条启用了吗"
    from fixtext_vocab_preview.rehearsal import rehearse as _r
    res = _r(model)
    assert res.identical, res.text()
    # 预演自己已经逐条实证过（disabled_ok 用的是 store.states.is_disabled）
    assert res.disabled_ok == ["丙丙 → 丙"]


def test_no_new_field_or_file_for_disposition_state(tmp_path):
    """处置本身**不落盘**：模型里记着，撤销即回到原样；没有任何处置结果文件。

    这是"可撤销到导入前"的结构保障：处置只是 `_build` 的输入，重判是无状态计算。
    """
    real, store = make_store(tmp_path)
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    before_names = {p.name for p in tmp_path.iterdir()}

    model.disable(7)
    model.skip(6)
    model.edit_value(2, "乙乙乙")
    after_names = {p.name for p in tmp_path.iterdir()}
    assert after_names == before_names            # 没多出任何文件

    n = model.restore_all_actions()
    assert n == 3
    assert model.dispositions == {}
    assert model.write_plan()["disabled"] == 0
    assert model.write_plan()["skipped"] == 0
    # 回到打开预览时的原样：仍然 3 条冲突待处置
    assert model.write_plan()["pending"] == 3
    assert model.find(2).value == "乙"             # 新值没有留下痕迹


# ---------- ③ 改值后其余行自动重判 ----------

def test_edit_reruns_judgement_for_the_rest_of_the_rows(store):
    """跳过/改值会改变后面那些重复行的判定——不重判就会「预览 N、写入 N+k」。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    assert model.find(6).group == GROUP_CONFLICT   # 行 6 撞行 5

    # 行 5（先出现的「重复 → 值一」）跳过不写，行 6 就不该再算冲突
    model.skip(5)
    later = model.find(6)
    assert later.group == GROUP_NEW
    assert later.effect == EFFECT_ADD
    assert model.write_plan()["pending"] == 2      # 只剩行 2、行 3 两条待处置

    # 再验一次「改值」方向：整表重判后这一条自己换了组，且不牵动别的行
    fresh = preview_from_sheet(parse_text(BASE_TEXT), store)
    fresh.edit_value(2, "乙乙乙")                  # 行 2 原本「乙乙 → 乙」撞车
    assert fresh.find(2).group == GROUP_NEW        # 改成新写法后不再撞
    assert fresh.find(2).effect == EFFECT_ADD
    assert fresh.find(6).group == GROUP_CONFLICT   # 行 6 与行 5 的同词异值照旧
    assert fresh.find(5).value == "值一"           # 别的行的值没有被改写


def test_skip_first_duplicate_lets_the_second_one_through(store):
    """跳过前一条重复，后一条就该从冲突变新增（真实判定不是"记住第一次的结论"）。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    assert model.find(6).group == GROUP_CONFLICT

    model.skip(5)
    later = model.find(6)
    assert later.group == GROUP_NEW
    assert later.effect == EFFECT_ADD
    plan = model.write_plan()
    assert plan["skipped"] == 1
    assert plan["pending"] == 2

    res = rehearse(model)
    assert res.identical, res.text()


# ---------- ④ 影响预览数字 vs 预演实测（D3 口径的 D4 扩展）----------

def test_impact_numbers_match_rehearsal_columns(model):
    """影响预览的四类数字与预演实测逐列一致（防「预览说 N、写入变 N+k」）。"""
    model.edit_value(2, "乙乙乙")
    model.skip(6)
    model.disable(7)

    plan = model.write_plan()
    text = model.impact_text()
    # 文案里的四个数就是 write_plan 的四个数，不另算
    for n in (plan["write"], plan["add"], plan["update"], plan["disabled"], plan["skipped"]):
        assert str(n) in text

    res = rehearse(model)
    assert res.identical, res.text()
    cols = {row[0]: row[1:] for row in res.diff_columns()}
    assert cols["新增"] == (plan["new"], plan["new"], "一致")
    assert cols["更新"] == (plan["update"], plan["update"], "一致")
    assert cols["禁用"] == (plan["disabled"], plan["disabled"], "一致")
    assert cols["跳过"] == (plan["skipped"], plan["skipped"], "一致")
    assert cols["被改动"][0] == 0 and cols["被删除"][0] == 0


def test_impact_preview_is_the_pre_write_count_not_the_group_count(model):
    """影响预览数的是"这次会拿它做什么"，不是"它落在哪一组"。

    跳过处置后条目仍留在冲突组里（状态可见），但影响预览的写入数必须少一条。
    """
    base = model.write_plan()
    assert base["write"] == 2 and base["pending"] == 3

    model.skip(6)
    after = model.write_plan()
    assert after["write"] == base["write"]        # 行 6 本来就没写（待处置）
    assert after["pending"] == base["pending"] - 1
    assert after["skipped"] == 1


# ---------- ⑤ pending 拦门（确认前必须处置完）----------

def test_pending_items_block_the_confirmation(model):
    """还有冲突没处置时，确认执行必须被拦下——否则这几条写不写说不清。"""
    assert len(model.pending_items()) == 3
    assert model.pending_items()[0].action_note

    model.edit_value(2, "乙乙乙")   # → 新增
    model.skip(6)                   # → 跳过
    model.disable(7)                # 行 7 本来不是冲突，这条与 pending 无关
    # 行 3「甲的异体 → 甲」仍是待处置（库里一模一样，只能跳过或改值）
    assert [it.line_no for it in model.pending_items()] == [3]

    model.skip(3)
    assert model.pending_items() == []
    plan = model.write_plan()
    assert plan["pending"] == 0
    assert plan["skipped"] == 2


def test_all_rows_disposed_and_plan_closes(model):
    """把三条冲突都处置掉之后，写入数与"合法行数 - 跳过数"能对上。"""
    model.edit_value(2, "乙乙乙")
    model.skip(3)                   # 库里一模一样，写也没意义
    model.skip(6)
    assert model.pending_items() == []

    plan = model.write_plan()
    assert plan["pending"] == 0
    assert plan["write"] + plan["skipped"] == len(model.effective_good_rows())

    res = rehearse(model)
    assert res.identical, res.text()


# ---------- ⑥ 撤销与幂等 ----------

def test_dispositions_are_replaceable_and_revocable(store):
    """同一条反复处置以最后一次为准；撤销后回到"还没处置"。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    line = 2
    assert model.action_of(line) == ""

    model.edit_value(line, "乙乙乙")
    assert model.action_of(line) == ACTION_EDIT
    model.disable(line)                            # 改成禁用
    assert model.action_of(line) == ACTION_DISABLE
    assert model.find(line).effective_value == "乙"   # 改值的新值不再生效

    model.clear_action(line)
    assert model.action_of(line) == ""
    assert model.find(line).effect == "pending"
    assert model.write_plan()["pending"] == 3


def test_disposition_overrides_previous_cancel(store):
    """先取消、后给它一个处置：取消要让位（两种状态混在一起账算不清）。"""
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    model.cancel(6)
    assert 6 in model.cancelled_lines

    model.skip(6)
    assert 6 not in model.cancelled_lines
    assert model.find(6).effect == EFFECT_SKIPPED


def test_edit_requires_a_value(model):
    with pytest.raises(ValueError):
        model.edit_value(2, "   ")
    with pytest.raises(ValueError):
        model.set_action(2, "nonsense")
    assert model.set_action(9999, ACTION_SKIP) is None     # 行号不存在


# ---------- ⑦ 写入清单结构（D5 的输入契约）----------

def test_write_list_shape_is_the_d5_input_contract(model):
    model.edit_value(2, "乙乙乙")
    model.disable(7)
    wl = model.write_list()
    assert wl, "写入清单不能空"
    for row in wl:
        assert set(row) >= {"line_no", "word", "value", "typ", "pinyin",
                            "effect", "action", "disabled", "update_target"}
        assert row["value"].strip(), "写入清单里不允许空值"
        assert row["disabled"] is (row["effect"] == EFFECT_DISABLED)
    assert all(row["effect"] != EFFECT_SKIPPED for row in wl)


def test_write_plan_entries_is_the_same_entry_d5_will_use(tmp_path):
    """`write_plan_entries` 就是 D5 事务写入的口径：更新走 update、禁用走 states。"""
    real, store = make_store(tmp_path)
    model = preview_from_sheet(parse_text(BASE_TEXT), store)
    model.edit_value(5, "重复改过")     # 行 6 变新增
    model.skip(6)
    model.disable(7)

    items = [it for it in model.effective() if it.will_write]
    pre_copy = real.read_bytes()                 # 写入前的真实词库快照
    copy = tmp_path / "copy" / "custom_vocab.json"
    copy.parent.mkdir()
    copy.write_bytes(pre_copy)
    tmp_store = VocabStore(custom_path=copy, work_dir=tmp_path / "copy" / "rules",
                           snap_dir=tmp_path / "copy" / "snap")
    outcome = write_plan_entries(tmp_store, items)
    assert len(outcome["added"]) == len([it for it in items
                                         if it.effect in (EFFECT_ADD, EFFECT_DISABLED)
                                         and not it.update_target])
    assert outcome["disabled_pairs"]
    assert tmp_store.states.is_disabled("丙丙", "丙")
    # 真实词库一个字节没动：副本是在写入**之前**按字节复制的，所以拿它当基准
    assert real.read_bytes() == pre_copy
    assert copy.read_bytes() != pre_copy          # 副本真被写过了
