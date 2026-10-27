"""M2-T2.6 移植验收：v4 冒烟脚本适配版（词库/历史/检查）。

由 UI v4 骨架的同名冒烟移植而来：仅把 sys.path 指向从 v4 src 改为
本交付包的 fixtext_ui（可用环境变量 FIXTEXT_UI_DIR 覆盖），
断言语义与 v4 原版逐条一致。pytest 不会收集（下划线前缀），
独立运行：QT_QPA_PLATFORM=offscreen python3.12 tests/_smoke_*.py
"""
import os
import sys

sys.path.insert(0, os.environ.get(
    "FIXTEXT_UI_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fixtext_ui")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QLabel

import history_module as hm
from history_module import HistoryModule, ConfirmDialog, TASKS

app = QApplication(sys.argv)
mod = HistoryModule()
mod.show()  # offscreen 下让 isVisible 反映显隐状态


def count_rows(m):
    n = 0
    for i in range(m._table_body.count()):
        w = m._table_body.itemAt(i).widget()
        if w is not None and w.findChildren(QPushButton) \
                and any(b.text() == "删除" for b in w.findChildren(QPushButton)):
            n += 1
    return n


# 1) 初始渲染 3 行
print("初始数据行数:", count_rows(mod))
assert count_rows(mod) == 3, "应有 3 条任务"

# 2) 状态列：2 正常 + 1 同步失败
labels = mod.findChildren(QLabel)
warn = [l for l in labels if l.text() == "基准同步失败"]
ok = [l for l in labels if l.text() == "正常"]
print("正常标签数:", len(ok), " 同步失败标签数:", len(warn))
assert len(ok) == 2 and len(warn) == 1

# 3) 设计依据开关
mod.basis_cb.setChecked(True)
mod.basis_cb.setChecked(False)
print("设计依据开关 OK")

# 4) 重新导出 toast（无 undo 按钮）
mod._reexport(0)
assert "重新导出" in mod.status.text(), "toast 文案应包含「重新导出」"
assert not mod.undo_btn.isVisible(), "重新导出 toast 不应显示撤销按钮"
print("重新导出 toast:", mod.status.text())

# 5) 删除 + 撤销（打桩 ConfirmDialog 绕过 exec）
class FakeConfirm:
    def __init__(self, **kw):
        self.kw = kw
    def exec(self):
        return QDialog.DialogCode.Accepted
    def setParent(self, p):
        pass
hm.ConfirmDialog = FakeConfirm

mod._confirm_delete(0)
assert count_rows(mod) == 2, "删除后应为 2 行"
assert mod.undo_btn.isVisible(), "删除 toast 应显示撤销按钮"
mod._undo()
assert count_rows(mod) == 3, "撤销后恢复为 3 行"
assert mod.status.text() == "已撤销删除，该条历史已恢复"
print("删除 + 撤销 OK")

# 6) 恢复 + 撤销（真实回退工作区前态）
mod._undo_stack.clear()
mod._active_idx = None
mod._confirm_restore(0)
assert mod.undo_btn.isVisible(), "恢复 toast 应显示撤销按钮"
assert "已恢复" in mod.status.text()
assert mod._active_idx == 0, "恢复后应把 0 号快照标记为当前工作区"
assert "当前工作区" in mod._active_hint.text(), "应刷新当前工作区提示"
mod._undo()
assert mod._active_idx is None, "撤销恢复应回到恢复前（无激活快照）"
assert mod.status.text() == "已撤销恢复，回到恢复前状态"
assert "未指定" in mod._active_hint.text(), "撤销后工作区提示应复位"
print("恢复 + 撤销（真实回退）OK")

# 7) 清理全部：清空撤销栈（不可撤销）
mod._undo_stack.append(dict(type="delete", item=dict(TASKS[0]), index=0))
mod._confirm_clear()
assert count_rows(mod) == 0, "清理后应为空"
assert len(mod._undo_stack) == 0, "清理全部应清空撤销栈"
print("清理全部 + 清空撤销栈 OK")

# 8) 空栈提示
mod._undo()
assert "没有可撤销的操作" in mod.status.text()
print("空栈提示 OK")

# 9) 真实 ConfirmDialog 仍可构造（导入自共享库，未改动）
d = ConfirmDialog(icon="🧹", title="x", note="y", note_kind="warn",
                  confirm_text="确认清理全部", confirm_kind="danger")
assert d.windowTitle() == "x"
print("ConfirmDialog 构造 OK")

# 10) 复位数据（避免影响后续运行）
TASKS[:] = [
    dict(book="《星河彼端》", time="2026-10-26 17:42", hits=1284, status="ok"),
    dict(book="《旧巷杂记》", time="2026-10-25 09:10", hits=356, status="ok"),
    dict(book="《灯下漫笔》", time="2026-10-22 21:03", hits=87, status="syncfail"),
]
print("SMOKE_OK")
