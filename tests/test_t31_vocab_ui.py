"""M3-T3.1 词库管理页 · 界面层真实点击链路验证。

与 ``test_t31_vocab_store.py`` 的分工：那边验数据层语义，这边验**界面按钮
真的把动作落到真实词库文件上**——预览弹窗阶段不动文件、二次确认后写盘、
撤销后文件逐字节回到操作前。

界面构造用临时的自定义词库路径，内置词库仍读交付包里的真实 304,255 条。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fixtext_ui.fixtext_vocab import VocabStore


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeModal:
    """替身模态窗：只提供 accept / reject / show 三个副作用。"""

    def __init__(self):
        self.accepted = False

    def accept(self):
        self.accepted = True

    def reject(self):
        self.accepted = False

    def show(self):
        pass


class FakeCheckBox:
    def __init__(self, checked: bool = True):
        self._c = checked

    def isChecked(self) -> bool:
        return self._c


@pytest.fixture()
def mod(qapp, tmp_path):
    """把词库面板的自定义词库指向临时文件，其余照真实交付包。"""
    import vocab_module as vm

    m = vm.VocabModule()
    m.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    m._page = 0
    m.search = ""
    m.dict_, m.tier = "custom", "custom"
    m._render_all()
    yield m
    m.close()


# ---------------------------------------------------------------------------
# 初始状态：无演示数据
# ---------------------------------------------------------------------------

def test_module_starts_with_empty_custom(mod):
    assert len(mod.store.custom) == 0
    assert mod.get_filtered() == [], "初始页不应有演示词条"
    assert mod._hit_total == 0
    assert mod.pages() == 1


def test_module_shows_real_builtin_count(mod):
    """界面汇总的内置条数必须等于「各可达分级之和」，且来自真实数据。

    V1.1-F3 修订：原断言 ``builtin_total == 304255`` 且 ``b1+b2+b3 == 304255``。
    两处前提都过期了：
      * ``b2``（标点规范）在 M5-QC.2 ``18a1a7c`` 被移除（标点已迁排版），
        分级表里不再有 b2，取 ``counts["b2"]`` 直接 KeyError；
      * 词库展示从 flat 五件套改读按袋目录（M5-EX.1 ``21cb712``），
        ``builtin_total`` 现在是**界面可达**的 302,957 条；磁盘上的 304,255
        里有 1,298 条属 ``punctuation`` / ``postfix`` / ``temp`` 三袋，
        界面上不挂（见 ``BAG_TO_TIER`` 与 bags manifest）。

    因此改为不写死数字的等价断言：可达分级之和 == builtin_total ==
    manifest 可达袋之和；磁盘总数另算一笔并核准差额出处。
    """
    from fixtext_ui.fixtext_vocab import BAG_TO_TIER

    counts = mod.store.counts()
    reachable = sorted(set(BAG_TO_TIER.values()))
    rule_counts = {b["id"]: b["rule_count"] for b in mod.store.builtin.meta["bags"]}

    assert sum(counts[t] for t in reachable) == mod.store.builtin_total
    assert mod.store.builtin_total == sum(
        rule_counts[b] for b in BAG_TO_TIER)
    # 磁盘总数多出来的那部分，必须正好是界面上不挂的三袋
    hidden = sorted(set(rule_counts) - set(BAG_TO_TIER))
    assert sum(rule_counts.values()) == mod.store.builtin_total + sum(
        rule_counts[b] for b in hidden)


def test_empty_state_is_plain_language(mod):
    from PySide6.QtWidgets import QLabel
    lab = mod._empty_state()
    assert isinstance(lab, QLabel)
    text = lab.text()
    assert "还没有词条" in text
    for ghost in ("星河彼端", "旧巷杂记"):
        assert ghost not in text


# ---------------------------------------------------------------------------
# 检索：界面命中数与数据层一致
# ---------------------------------------------------------------------------

def test_search_hit_count_matches_data_layer(mod):
    """界面命中数必须与数据层同口径：左边点哪个分级，右边就只数那个分级。

    V1.1-F3 修订：原用例把界面置成 ``dict_="all"`` + ``tier="b1"``——
    这是**界面上不存在**的状态组合。页头那组分档（全部/自定义/内置，
    ``set_tier``）与左侧分级列表（``select_dict``）任何一条真实点击路径都
    不会产生它：``set_tier("all")`` 不动 ``dict_``，``select_dict(d)`` 会把
    ``tier`` 归到 ``custom`` / ``all``。而 ``_scope()`` 先看 ``dict_``——
    ``dict_="all"`` 落进 ``if self.dict_ in TIER_NAMES``？不，``"all"``
    不在里面，于是最终返回 ``"all"``（全库），界面显示 18，
    而用例拿 ``search_count(dict_code="b1")`` 的 9 去比 —— 18 != 9。

    改为按真实点击路径置状态：``select_dict("b1")``（等价于用户点左侧
    「常规校正词库」），再核对命中数与数据层 b1 同口径。
    """
    from vocab_module import PAGE_SIZE   # 每页条数是界面常量，不在数据层

    mod.select_dict("b1")
    mod.search = "好象"
    mod._page = 0
    mod._render_entries()

    expect = mod.store.builtin.search_count("好象", dict_code="b1")
    assert expect > 0
    assert mod._hit_total == expect, (
        f"界面显示 {mod._hit_total}，数据层 b1 口径是 {expect}"
        "（界面必须与数据层同口径，不能一边全库一边单分级）"
    )
    assert len(mod.get_filtered()) == min(expect, PAGE_SIZE)


# ---------------------------------------------------------------------------
# 新增：预览 → 确认 → 落盘
# ---------------------------------------------------------------------------

def test_add_via_ui_writes_real_file(mod):
    path = mod.store.custom.path
    sha_before = _sha(path)
    mod._pending_add = dict(word="萧衍", value="萧彦", typ="角色名", pinyin="xiāo yǎn")
    modal = FakeModal()
    mod.confirm_add(modal)
    assert modal.accepted is True
    assert _sha(path) != sha_before
    assert len(mod.store.custom) == 1
    assert mod._hit_total == 1
    entry = mod.store.custom.entries()[0]
    assert entry["type"] == "角色名", "类型字段应真实落盘"


def test_add_preview_does_not_write(mod):
    path = mod.store.custom.path
    sha_before = _sha(path)
    mod.preview_add(FakeModal(), "预览词", "预览替换", "错词校正", "")
    assert mod._pending_add is not None, "预览应挂起待确认项"
    assert _sha(path) == sha_before, "预览阶段不应写文件"
    assert len(mod.store.custom) == 0
    mod._pending_add = None


def test_add_preview_blocks_empty_word(mod):
    mod.preview_add(FakeModal(), "", "替换", "错词校正", "")
    assert mod._pending_add is None, "原词为空时不应挂起待写入项"


def test_add_shows_conflict_hint(mod):
    mod._pending_add = dict(word="重复", value="值甲", typ="错词校正", pinyin="")
    mod.confirm_add(FakeModal())
    same_both = mod.store.conflicts_for_add("重复", "值甲")
    same_word = mod.store.conflicts_for_add("重复", "值乙")
    assert any(c["kind"] == "同词同值" for c in same_both)
    assert any(c["kind"] == "同词异值" for c in same_word)


# ---------------------------------------------------------------------------
# 删除：预览不动文件 → 确认删除 → 撤销逐字节一致
# ---------------------------------------------------------------------------

def test_delete_preview_then_confirm_then_undo(mod):
    for w in ("甲词", "乙词", "丙词"):
        mod.store.add_entry(word=w, value=f"{w}替", typ="错词校正")
    mod._render_all()
    path = mod.store.custom.path
    sha_before = _sha(path)
    ids = [e["id"] for e in mod.store.custom.entries() if e["word"] in ("甲词", "乙词")]

    mod._confirm_delete(ids)                     # 只出预览
    assert _sha(path) == sha_before, "预览阶段不应写文件"
    assert len(mod.store.custom) == 3

    res = mod.do_delete(ids)
    assert res["removed"] == 2
    assert len(mod.store.custom) == 1
    assert _sha(path) != sha_before

    mod._undo()
    assert len(mod.store.custom) == 3
    assert _sha(path) == sha_before, "撤销后应与删除前逐字节一致"


def test_delete_ignores_builtin_rows(mod):
    """内置词条只读：即使被选中也不允许删除。"""
    mod._selected = {-1}
    mod._on_delete_selected()
    assert len(mod.store.custom) == 0


# ---------------------------------------------------------------------------
# 去重合并：查重清单组内动作 → 改动清单 → 二次确认 → 写入真实词库 → 撤销
# ---------------------------------------------------------------------------

def test_dup_dialog_keep_one_then_undo(mod):
    """同词异值组：清单里选一条保留 → 改动清单 → 确认 → 写盘 → 撤销。"""
    for v in ("替A", "替B", "替C"):
        mod.store.add_entry(word="甲", value=v, typ="错词校正")
    mod._render_all()
    path = mod.store.custom.path
    sha_before = _sha(path)
    before = [dict(e) for e in mod.store.custom.entries()]

    groups = mod.open_dup()
    grp = next(g for g in groups if g["key"] == "甲")
    assert grp["kind"] == "同词异值"
    assert _sha(path) == sha_before, "打开查重清单不许动文件"
    assert mod._dup_view["readonly"] is False, "查重清单已改为可处理"

    keep = [r for r in grp["items"] if r["value"] == "替A"][0]

    class _Combo:
        def currentData(self):
            return keep["id"]

    mod._dup_keep_one(grp, _Combo())
    assert _sha(path) == sha_before, "第一层只是改动清单，不许写盘"
    assert len(mod.store.custom) == 3

    # 二次确认弹窗里的那颗按钮：真实点击
    from PySide6.QtWidgets import QDialog, QPushButton
    dlg = [d for d in mod.findChildren(QDialog) if d.isVisible()][-1]
    btn = [b for b in dlg.findChildren(QPushButton) if b.text().startswith("确认保留")][0]
    btn.click()
    assert len(mod.store.custom) == 1, f"合并后应保留 1 条，实际 {len(mod.store.custom)}"
    assert mod.store.custom.entries()[0]["value"] == "替A"
    assert _sha(path) != sha_before, "确认后应写盘"

    mod._undo()
    assert _sha(path) == sha_before, "撤销后应与合并前逐字节一致"
    assert [dict(e) for e in mod.store.custom.entries()] == before


def test_dup_dialog_dedup_same_value_then_undo(mod):
    """同词同值组：一键去重 → 改动清单 → 确认 → 写盘 → 撤销。"""
    for _ in range(3):
        mod.store.add_entry(word="乙", value="同值", typ="错词校正")
    mod._render_all()
    path = mod.store.custom.path
    sha_before = _sha(path)

    groups = mod.open_dup()
    grp = next(g for g in groups if g["key"] == "乙")
    assert grp["kind"] == "同词同值"
    mod._dup_dedup_same(grp)
    assert _sha(path) == sha_before, "第一层只是改动清单，不许写盘"

    from PySide6.QtWidgets import QDialog, QPushButton
    dlg = [d for d in mod.findChildren(QDialog) if d.isVisible()][-1]
    btn = [b for b in dlg.findChildren(QPushButton) if b.text().startswith("确认去重")][0]
    btn.click()
    assert len(mod.store.custom) == 1, f"去重后应剩 1 条，实际 {len(mod.store.custom)}"
    assert _sha(path) != sha_before, "确认后应写盘"

    mod._undo()
    assert _sha(path) == sha_before, "撤销后应与去重前逐字节一致"
    assert len(mod.store.custom) == 3


def test_dup_groups_no_longer_reports_same_value_diff_word(qapp, tmp_path):
    """同值异词不再算重复（用户拍板）：两条不同原词映射到同一替换值不分组。"""
    store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    store.add_entry(word="丁", value="戊", typ="错词校正")
    store.add_entry(word="己", value="戊", typ="错词校正")
    groups = store.dup_groups()
    assert not [g for g in groups if g["kind"] == "同值异词"], groups
    assert not [g for g in groups if g["key"] == "戊"], groups


# ---------------------------------------------------------------------------
# 编辑 / 本书专有词 / 恢复默认
# ---------------------------------------------------------------------------

def test_edit_via_ui_then_undo(mod):
    rid = mod.store.add_entry(word="原词", value="原值", typ="错词校正")["id"]
    path = mod.store.custom.path
    sha_before = _sha(path)
    mod.save_edit(rid, "原词", "新值", "错词校正", "", FakeModal())
    assert mod.store.custom.entries()[0]["value"] == "新值"
    mod._undo()
    assert _sha(path) == sha_before


def test_book_words_via_ui(mod):
    mod._book_words = [dict(word="书中角色", note="第 2 章")]
    mod._book_title = "示例书"
    mod._book_checks = [FakeCheckBox(True)]
    added = mod.add_book_words(FakeModal())
    assert added == 1
    entry = mod.store.custom.entries()[0]
    assert entry["word"] == "书中角色"
    assert entry["book"] == "示例书"


def test_book_words_skip_existing(mod):
    mod._book_words = [dict(word="已有词", note="")]
    mod._book_title = "示例书"
    mod.store.add_entry(word="已有词", value="已有词", typ="专有名词")
    mod._book_checks = [FakeCheckBox(True)]
    added = mod.add_book_words(FakeModal())
    assert added == 0, "已存在的词条不应重复写入"
    assert len(mod.store.custom) == 1


def test_restore_default_keeps_custom(mod):
    import vocab_module as vm
    from PySide6.QtWidgets import QDialog, QDialogButtonBox

    class _Accepted(vm.ConfirmDialog):
        def exec(self):
            return QDialog.DialogCode.Accepted

    mod.store.add_entry(word="保留我", value="值", typ="错词校正")
    n = len(mod.store.custom)
    old = vm.ConfirmDialog
    vm.ConfirmDialog = _Accepted
    try:
        mod.restore_default()
    finally:
        vm.ConfirmDialog = old
    assert len(mod.store.custom) == n, "恢复默认不应动自定义词条"
    ok, detail = mod.store.builtin.self_check()
    assert ok is True
