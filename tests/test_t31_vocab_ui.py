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
    assert mod.store.builtin_total == 304255
    counts = mod.store.counts()
    assert counts["b1"] + counts["b2"] + counts["b3"] == 304255


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
    mod.search = "好象"
    mod.dict_, mod.tier = "all", "b1"
    mod._page = 0
    mod._render_entries()
    expect = mod.store.builtin.search_count("好象", dict_code="b1")
    assert mod._hit_total == expect
    assert expect > 0
    assert len(mod.get_filtered()) == min(expect, 40)


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
# 合并：预览 → 二次确认 → 写入真实词库 → 撤销
# ---------------------------------------------------------------------------

def test_merge_preview_confirm_undo_full_click_path(mod):
    """完整点击链路：预览清单 → 二次确认清单 → 写盘 → 撤销。"""
    for w in ("甲", "乙", "丙"):
        mod.store.add_entry(word=w, value=f"{w}替", typ="错词校正")
    mod._render_all()
    path = mod.store.custom.path
    sha_before = _sha(path)
    ids = [e["id"] for e in mod.store.custom.entries()]
    mod._selected = set(ids)

    mod.open_merge()                                   # 第一个弹窗：选主词 + 预览清单
    assert _sha(path) == sha_before, "合并预览不应写文件"

    parent = FakeModal()
    preview = mod.do_merge(parent, "甲")               # 第二个弹窗：二次确认
    assert preview and preview["pending"] is True
    assert preview["removed"] == 2
    assert parent.accepted is True, "预览弹窗应被收起"
    assert _sha(path) == sha_before, "二次确认前不应写文件"
    assert len(mod.store.custom) == 3

    res = mod._do_merge_commit(FakeModal(), ids, "甲")  # 真正写盘
    assert res["removed"] == 2
    assert len(mod.store.custom) == 1
    assert mod.store.custom.entries()[0]["word"] == "甲"
    assert _sha(path) != sha_before

    mod._undo()
    assert _sha(path) == sha_before, "撤销后应与合并前逐字节一致"
    assert len(mod.store.custom) == 3


def test_merge_requires_two_selections(mod):
    mod.store.add_entry(word="唯一", value="值", typ="错词校正")
    mod._render_all()
    mod._selected = {mod.store.custom.entries()[0]["id"]}
    mod.open_merge()
    assert mod._merge_sel is None, "不足 2 条时不应进入合并流程"


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
