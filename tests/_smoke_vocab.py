"""M2-T2.6 移植验收：v4 冒烟脚本适配版（词库/历史/检查）。

由 UI v4 骨架的同名冒烟移植而来：仅把 sys.path 指向从 v4 src 改为
本交付包的 fixtext_ui（可用环境变量 FIXTEXT_UI_DIR 覆盖），
断言语义与 v4 原版逐条一致。pytest 不会收集（下划线前缀），
独立运行：QT_QPA_PLATFORM=offscreen python3.12 tests/_smoke_*.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.environ.get(
    "FIXTEXT_UI_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtext_ui")))

from PySide6.QtWidgets import QApplication, QDialog

import vocab_module as vm
from fixtext_widgets import ConfirmDialog

app = QApplication(sys.argv)


# 打桩 ConfirmDialog：exec 直接返回 Accepted，用于测试恢复默认等依赖确认的动作
class FakeConfirm(QDialog):
    def __init__(self, **kw):
        super().__init__()
    def exec(self):  # noqa: D401
        return QDialog.DialogCode.Accepted


mod = vm.VocabModule()
# offscreen 下无真实屏幕，show() 仅设置逻辑可见态，使 isVisible() 可用于断言
mod.show()

# 1) 初始渲染：14 条（5 自定义 + 9 内置），4 个 basis 标注
assert len(mod.entries) == 14, f"初始应有 14 条，实际 {len(mod.entries)}"
assert len(mod.basis_labels) == 4, f"basis 应为 4，实际 {len(mod.basis_labels)}"
assert not mod.status_box.isVisible()
print("初始：14 条 / 4 basis / 状态隐藏 OK")

# 2) 过滤
mod.tier, mod.dict_ = "all", "custom"
assert len(mod.get_filtered()) == 5
mod.tier, mod.dict_ = "builtin", "all"
assert len(mod.get_filtered()) == 9
mod.tier, mod.dict_ = "all", "b1"
assert len(mod.get_filtered()) == 4
mod.search = "萧"
mod.tier, mod.dict_ = "all", "custom"
assert len(mod.get_filtered()) == 1, "检索『萧』应命中 1 条"
mod.search = ""
print("过滤（自定义5 / 内置9 / b1=4 / 检索1）OK")

# 3) 选择 → 删除 / 合并按钮态
cid = next(e["id"] for e in mod.entries if e["tier"] == "custom")
mod._toggle_row(cid, 2)  # checked
mod._update_sel_state()
assert mod._del_btn.isEnabled()
assert not mod._merge_btn.isEnabled()  # 仅 1 条不可合并
mod._toggle_all(2)  # 全选（filtered = 5 custom）
mod._update_sel_state()
assert mod._merge_btn.isEnabled()
print("选择计数 / 删除+合并按钮态 OK")

# 4) 新增词条（预览→确认）
n0 = len(mod.entries)
mod._pending_add = dict(word="测试词", value="测试值", type="错词校正", pinyin="")
fake = type("M", (), {"accept": lambda s: None})()
mod.confirm_add(fake)
assert len(mod.entries) == n0 + 1, "新增后应 +1"
assert len(mod._undo_stack) == 1
assert mod.status_box.isVisible() and mod.undo_btn.isVisible()
print("新增词条（二次确认写入）OK，撤销栈 +1")

# 5) 删除 + 撤销
n1 = len(mod.entries)
new_id = max(e["id"] for e in mod.entries if e["word"] == "测试词")
mod.do_delete([new_id])
assert len(mod.entries) == n1 - 1
mod._undo()
assert any(e["id"] == new_id for e in mod.entries), "撤销应恢复被删词条"
print("删除 + 撤销恢复 OK")

# 6) 查重：先制造一条同词重复（自定义内），再计算
dup_word = "重复X"
nid = max(e["id"] for e in mod.entries) + 1
mod.entries.append(dict(id=nid, word=dup_word, value="a", type="错词校正", pinyin="", dict="custom", tier="custom", books=[]))
nid2 = nid + 1
mod.entries.append(dict(id=nid2, word=dup_word, value="b", type="错词校正", pinyin="", dict="custom", tier="custom", books=[]))
groups = mod._compute_dups()
assert any(g["type"] == "同词不同值" and g["key"] == dup_word for g in groups)
# 清理：删掉这两条
mod.do_delete([nid, nid2])
assert not any(g["type"] == "同词不同值" and g["key"] == dup_word for g in mod._compute_dups())
print("查重（同词不同值检测 + 清理）OK")

# 7) 合并：选 2 条自定义 → do_merge
sel = [e["id"] for e in mod.entries if e["tier"] == "custom"][:2]
mod._merge_sel = sel
target = mod._by_id(sel[0])["word"]
n2 = len(mod.entries)
mod.do_merge(type("M", (), {"accept": lambda s: None})(), target)
assert len(mod.entries) == n2 - 1, "合并后应 -1"
print("合并（预览写入 → 保留主词）OK")

# 8) 快照 + 恢复快照
assert len(mod._snapshots) >= 1
snap_id = mod._snapshots[0]["id"]
before_count = len(mod.entries)
# 造一个变更
mod.entries.pop()
mod._snap("测试变更")
mod.restore_snap(snap_id)
assert len(mod.entries) == before_count, "恢复快照应回到该时间点条数"
print("自动快照 + 恢复到此 OK")

# 9) 恢复默认词库（保留自定义）：打桩 ConfirmDialog
vm.ConfirmDialog = FakeConfirm
mod.restore_default()
custom_n = sum(1 for e in mod.entries if e["tier"] == "custom")
builtin_n = sum(1 for e in mod.entries if e["tier"] == "builtin")
assert builtin_n == 9 and custom_n == sum(1 for e in mod.entries if e["tier"] == "custom"), "内置应重置为 9"
print("恢复默认词库（内置重置为 9、自定义保留）OK")

# 10) 本书专有词：add_book_words
n3 = len(mod.entries)
checks = [type("C", (), {"isChecked": lambda s: True})() for _ in range(3)]
mod._book_checks = checks
mod.add_book_words(type("M", (), {"accept": lambda s: None})())
assert len(mod.entries) == n3 + 3, "加入 3 条专有词后 +3"
print("本书专有词（加入预览 → 写入自定义）OK")

# 11) 设计依据开关（隐藏卡片如快照卡的设计依据随之不可见，属正常）
mod._toggle_basis(True)
shown = [b for b in mod.basis_labels if b.parent().isVisible()]
assert all(b.isVisible() for b in shown), "可见卡片的设计依据应显示"
mod._toggle_basis(False)
assert all(not b.isVisible() for b in mod.basis_labels), "关闭后设计依据应全部隐藏"
print("设计依据开关（可见卡片显示 / 关闭全隐）OK")
mod._toggle_basis(False)
assert not any(b.isVisible() for b in mod.basis_labels)
print("设计依据开关 OK")

mod.close()
print("VOCAB_SMOKE_OK")
