"""M3-T3.1 词库管理页冒烟：五操作全部走真实词库（无演示数据）。

与 M2-T2.6 的 v4 冒烟不同，本版**不再断言内存假列表**：所有断言都落到
``fixtext_ui/fixtext_vocab.py`` 的真实数据层（内置 304,255 条 + 自定义 JSON 文件），
并且每个用例都跑在临时自定义词库上，不污染交付包里的 workspace。

跑法（pytest 不收集下划线前缀，独立执行）：

    QT_QPA_PLATFORM=offscreen PYTHONPATH=<包根>:<qt> python3 tests/_smoke_vocab.py

覆盖：初始空状态 / 检索命中真实条数 / 新增（含查重两种冲突）/ 编辑 / 删除（预览+撤销）/
查重清单组内去重与选一保留（预览+确认+撤销）/ 本书专有词 / 恢复默认（内置自检）/
撤销后文件逐字节一致。

V1.1-EX.2R：工具栏的独立「合并」入口已下线，合并成为查重清单里的组内动作，
所以第 8 段改成从 ``open_dup()`` 进清单、点组内按钮走完整写盘与撤销链路。
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for p in (str(PKG), str(PKG / "fixtext_ui")):
    if p not in sys.path:
        sys.path.insert(0, p)

from PySide6.QtWidgets import QApplication

import vocab_module as vm
from fixtext_vocab import VocabStore
from fixtext_widgets import ConfirmDialog

app = QApplication.instance() or QApplication([])

PASSED: list[str] = []


def ok(msg: str) -> None:
    PASSED.append(msg)
    print(f"  [OK] {msg}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_foot(host, label_prefix: str):
    """在 host 下当前可见的弹窗里按按钮文案前缀找那颗真按钮。"""
    from PySide6.QtWidgets import QDialog, QPushButton

    dlg = None
    for d in host.findChildren(QDialog):
        if d.isVisible():
            dlg = d
    assert dlg is not None, "没找到正在显示的弹窗"
    for b in dlg.findChildren(QPushButton):
        if b.text().startswith(label_prefix):
            return b
    raise AssertionError(f"弹窗里找不到按钮「{label_prefix}」")


class FakeModal:
    """替身模态窗：只需要 accept()/reject()/show() 的副作用。"""

    def __init__(self):
        self.accepted = False
        self.shown = 0

    def accept(self):
        self.accepted = True

    def reject(self):
        self.accepted = False

    def show(self):
        self.shown += 1


def make_module(tmp: Path) -> vm.VocabModule:
    """构造一个把自定义词库指向临时文件的面板（内置词库仍读交付包里的真实数据）。"""
    mod = vm.VocabModule()
    custom_path = tmp / "custom_vocab.json"
    mod.store = VocabStore(custom_path=custom_path)
    mod._page = 0
    mod.search = ""
    mod.dict_, mod.tier = "custom", "custom"
    mod._render_all()
    mod.show()
    return mod


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="t31smoke_"))
    custom_path = tmp / "custom_vocab.json"

    # 1) 初始：自定义空、内置真实
    mod = make_module(tmp)
    counts = mod.store.counts()
    assert counts["custom"] == 0, f"自定义初始应为空，实际 {counts['custom']}"
    # V1.1-F3 口径（本次 V1.1-EX.2R 顺手修正）：builtin_total 是**界面可达**袋之和
    # （BAG_TO_TIER 的 12 个袋，当前 302,957 条）；磁盘 304,255 里另有 3 个不可达袋
    # （postfix/temp/punctuation，共 1,298 条）。M5-EX.1 上袋后这里仍写死 304,255，
    # 属漏改的过期断言——按可达分级动态求和，不再写死数字。
    import json as _json
    from fixtext_vocab import BAG_TO_TIER, RULES_DIR as _RULES_DIR
    _reachable = sum(
        len(_json.loads((_RULES_DIR / "bags" / b / "before.json").read_text("utf-8")))
        for b in BAG_TO_TIER)
    assert mod.store.builtin_total == _reachable, \
        f"内置（界面可达）应为 {_reachable} 条，实际 {mod.store.builtin_total}"
    _tiers_all = [k for k in counts if k not in ("custom", "imported")]
    assert sum(counts[t] for t in _tiers_all) == mod.store.builtin_total, "分级之和应等于内置总数"
    assert len(mod.get_filtered()) == 0, "初始页不应有假词条（旧版此处是 5 条演示数据）"
    ok(f"初始：自定义 0 条 / 内置（界面可达）{mod.store.builtin_total} 条"
       f" / 页面 0 条")

    # 2) 空状态是人话，且不含虚构书名
    empty = mod._empty_state()
    from PySide6.QtWidgets import QLabel
    empty_text = empty.text() if isinstance(empty, QLabel) else ""
    assert "还没有词条" in empty_text, f"空状态文案应说明无数据，实际：{empty_text!r}"
    for ghost in ("星河彼端", "旧巷杂记"):
        assert ghost not in empty_text, f"空状态不应出现虚构书名 {ghost}"
    ok(f"空状态文案：{empty_text.splitlines()[0]}")

    # 3) 检索命中真实数据（内置分级，命中数与数据层一致）
    for q, expect_scope in (("好象", "b1"), ("萧", "all"), ("，", "b2")):
        total_ui, _ = mod.store.query(q, scope=expect_scope, offset=0, limit=vm.PAGE_SIZE)
        total_direct = mod.store.builtin.search_count(q) if expect_scope != "custom" else 0
        assert total_ui > 0, f"检索「{q}」应命中真实词条"
        if expect_scope == "all":
            assert total_ui == total_direct + len(mod.store.custom), "全库命中数应等于内置+自定义"
    mod.search = "好象"
    # V1.1-F3 口径：dict_="all"+tier="b1" 是界面上不存在的状态组合
    # （_scope() 先看 dict_，会落回全库 18 条）；按真实点击路径 select_dict("b1")
    mod.select_dict("b1")
    mod._page = 0
    mod._render_entries()
    n_b1 = mod.store.builtin.search_count("好象", dict_code="b1")
    assert mod._hit_total == n_b1, f"界面命中 {mod._hit_total} 应等于数据层 {n_b1} 条"
    ok(f"检索「好象」常规校正分级命中 {mod._hit_total} 条（与数据层一致）")
    mod.search = ""
    mod.dict_, mod.tier = "custom", "custom"
    mod._page = 0
    mod._render_entries()

    # 4) 新增：落盘到自定义词库文件
    sha_before = sha(custom_path)
    mod._pending_add = dict(word="萧衍", value="萧彦", typ="角色名", pinyin="xiāo yǎn")
    mod.confirm_add(FakeModal())
    assert custom_path.is_file(), "新增后应生成自定义词库文件"
    assert len(mod.store.custom) == 1, f"自定义应有 1 条，实际 {len(mod.store.custom)}"
    assert sha(custom_path) != sha_before, "新增后文件内容应变化"
    row = mod.store.custom.entries()[0]
    assert (row["word"], row["value"], row["type"]) == ("萧衍", "萧彦", "角色名"), row
    assert mod._hit_total == 1, "新增后自定义视图应显示 1 条"
    ok("新增「萧衍→萧彦」写入自定义词库，文件 sha 变化，视图 1 条")

    # 5) 查重：同词同值 / 同词异值 两种冲突都触发
    same_both = mod.store.conflicts_for_add("萧衍", "萧彦")
    assert any(c["kind"] == "同词同值" for c in same_both), f"应触发同词同值，实际 {same_both}"
    same_word = mod.store.conflicts_for_add("萧衍", "别的值")
    assert any(c["kind"] == "同词异值" for c in same_word), f"应触发同词异值，实际 {same_word}"
    mod.preview_add(FakeModal(), "萧衍", "萧彦", "角色名", "")
    assert mod._pending_add is not None, "预览应保留待写入项，等待二次确认"
    mod._pending_add = None
    ok(f"查重触发：同词同值 {len(same_both)} 条、同词异值 {len(same_word)} 条，预览弹窗正常")

    # 6) 编辑（原型有编辑按钮，落到真实写入 + 撤销栈）
    rid = mod.store.custom.entries()[0]["id"]
    mod.save_edit(rid, "萧衍", "萧彦改", "角色名", "xiāo yǎn", FakeModal())
    assert mod.store.custom.entries()[0]["value"] == "萧彦改", "编辑应真实写入文件"
    mod._undo()
    assert mod.store.custom.entries()[0]["value"] == "萧彦", "撤销编辑应回到原值"
    ok("编辑写入 + 撤销回原值")

    # 7) 删除：预览清单 → 确认 → 撤销后逐字节一致
    mod.store.add_entry(word="甲词", value="甲替", typ="错词校正")
    mod.store.add_entry(word="乙词", value="乙替", typ="错词校正")
    mod._render_all()
    n_all = len(mod.store.custom)
    assert n_all == 3, f"应有 3 条自定义，实际 {n_all}"
    pre_delete_sha = sha(custom_path)
    ids = [e["id"] for e in mod.store.custom.entries() if e["word"] in ("甲词", "乙词")]
    mod._confirm_delete(ids)               # 只出预览，不动文件
    assert len(mod.store.custom) == n_all, "预览阶段不应改动词库"
    mod.do_delete(ids, None)
    assert len(mod.store.custom) == n_all - 2, "确认后应删除 2 条"
    post_delete_sha = sha(custom_path)
    assert post_delete_sha != pre_delete_sha, "删除后文件应变化"
    rec = mod.store.undo()
    assert rec and rec["identical"], f"撤销应逐字节一致，实际 {rec}"
    assert sha(custom_path) == pre_delete_sha, "撤销后文件 sha 应与删除前完全相同"
    ok(f"删除 {len(ids)} 条：预览不动文件、确认后 {n_all}→{n_all - 2}、撤销后 sha 全等")

    # 8) 查重清单组内动作：同词异值组「选一保留」→ 撤销 sha 全等
    for v in ("甲替", "乙替", "丙替"):
        mod.store.add_entry(word="合并词", value=v, typ="错词校正")
    mod._render_all()
    pre_merge_sha = sha(custom_path)
    pre_merge_n = len(mod.store.custom)
    before_merge_entries = [dict(e) for e in mod.store.custom.entries()]
    groups = mod.open_dup()
    assert groups, "三条同词异值应当被查重清单检出"
    assert mod._dup_view["readonly"] is False, "查重清单已改为可处理，不再是只读"
    grp = next(g for g in groups if g["key"] == "合并词")
    assert grp["kind"] == "同词异值", f"这一组应判同词异值，实际 {grp['kind']}"
    assert len(mod.store.custom) == pre_merge_n, "打开清单不应改动文件"
    assert sha(custom_path) == pre_merge_sha, "打开清单不应改动文件（sha 也不许变）"

    keep = [r for r in grp["items"] if r["value"] == "乙替"][0]

    class _Combo:
        def currentData(self):
            return keep["id"]

    mod._dup_keep_one(grp, _Combo())        # 只出改动清单，不动文件
    assert sha(custom_path) == pre_merge_sha, "组内动作的第一层只是预览"
    confirm = _find_foot(mod, "确认保留")
    confirm.click()                          # 真实点击「确认保留」
    assert len(mod.store.custom) == pre_merge_n - 2, \
        f"保留 1 条后应剩 {pre_merge_n - 2} 条，实际 {len(mod.store.custom)}"
    kept = [e for e in mod.store.custom.entries() if e["word"] == "合并词"]
    assert len(kept) == 1 and kept[0]["value"] == "乙替", kept
    assert sha(custom_path) != pre_merge_sha, "确认后文件应变化"
    rec = mod.store.undo()
    assert rec and rec["identical"], f"合并撤销应逐字节一致，实际 {rec}"
    assert sha(custom_path) == pre_merge_sha, "合并撤销后 sha 应与合并前完全相同"
    assert [dict(e) for e in mod.store.custom.entries()] == before_merge_entries, \
        "撤销后词条应逐条回到原样"
    ok(f"同词异值 {len(grp['items'])} 条→保留 1 条：预览不动文件、确认后写盘、撤销后 sha 全等")

    # 8b) 同词同值组「一键去重」：保留第一条、其余移除、撤销 sha 全等
    # （造 3 条：去重移除 2 条，下面断言才是 pre_dedup_n - 2）
    for _ in range(3):
        mod.store.add_entry(word="重复词", value="同值", typ="错词校正")
    mod._render_all()
    pre_dedup_sha = sha(custom_path)
    pre_dedup_n = len(mod.store.custom)
    groups = mod.open_dup()
    grp2 = next(g for g in groups if g["key"] == "重复词")
    assert grp2["kind"] == "同词同值", f"这一组应判同词同值，实际 {grp2['kind']}"
    mod._dup_dedup_same(grp2)
    assert sha(custom_path) == pre_dedup_sha, "去重的第一层只是预览"
    _find_foot(mod, "确认去重").click()
    assert len(mod.store.custom) == pre_dedup_n - 2, \
        f"去重后应剩 {pre_dedup_n - 2} 条，实际 {len(mod.store.custom)}"
    assert sha(custom_path) != pre_dedup_sha, "去重确认后文件应变化"
    rec = mod.store.undo()
    assert rec and rec["identical"], f"去重撤销应逐字节一致，实际 {rec}"
    assert sha(custom_path) == pre_dedup_sha, "去重撤销后 sha 应与去重前完全相同"
    ok(f"同词同值 {len(grp2['items'])} 条→1 条：预览不动文件、确认后写盘、撤销后 sha 全等")

    # 9) 重启持久化（新建 VocabStore 等价于重开程序）
    store2 = VocabStore(custom_path=custom_path)
    assert len(store2.custom) == len(mod.store.custom), "重启后自定义条数应一致"
    assert [e["word"] for e in store2.custom.entries()] == \
           [e["word"] for e in mod.store.custom.entries()], "重启后词条内容应一致"
    # 内置与自定义物理分离
    assert store2.custom.path != (PKG / "data" / "rules"), "自定义词库不能落在内置词库目录"
    assert store2.builtin.dir != store2.custom.path.parent, "内置与自定义应物理分离"
    ok(f"重启后自定义 {len(store2.custom)} 条仍在；自定义路径与内置目录分离")

    # 10) 本书专有词（真实写入自定义）
    mod._book_words = [dict(word="本书角色甲", note="出现在第 3 章"),
                       dict(word="本书角色乙", note="出现在第 9 章")]
    mod._book_title = "示例书"
    n0 = len(mod.store.custom)
    mod._book_checks = [FakeCheckBox(True), FakeCheckBox(True)]
    added = mod.add_book_words(FakeModal())
    assert added == 2, f"应加入 2 条专有词，实际 {added}"
    assert len(mod.store.custom) == n0 + 2
    mod._undo()
    ok(f"本书专有词加入 {added} 条并已撤销")

    # 11) 恢复默认：只校验内置，自定义保留
    vm.ConfirmDialog = FakeConfirm
    n_custom = len(mod.store.custom)
    mod.restore_default()
    assert len(mod.store.custom) == n_custom, "恢复默认不应改动自定义词条"
    ok_check = mod.store.builtin.self_check()
    assert ok_check[0], f"内置自检应通过，实际 {ok_check}"
    ok(f"恢复默认：内置自检 {ok_check}，自定义 {n_custom} 条保留")

    mod.close()
    print(f"\nVOCAB_SMOKE_OK（{len(PASSED)} 组断言全过）")
    return 0


class FakeCheckBox:
    def __init__(self, checked: bool):
        self._c = checked

    def isChecked(self) -> bool:
        return self._c


class FakeConfirm(ConfirmDialog):
    """打桩确认框：exec 直接返回 Accepted。"""

    def __init__(self, **kw):
        super().__init__(**kw)

    def exec(self):                            # noqa: D401
        from PySide6.QtWidgets import QDialog
        return QDialog.DialogCode.Accepted


if __name__ == "__main__":
    sys.exit(main())
