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

import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import history_module as hm  # noqa: E402
import fixtext_history as histdata  # noqa: E402
import _fixture_run as fxr  # noqa: E402
from history_module import HistoryModule, ConfirmDialog  # noqa: E402

app = QApplication(sys.argv)

# T2.10：历史页的数据一律来自磁盘扫描（runs/run-*/report/ui_run_summary.json），
# 不再有模块内的演示数据。冒烟先造两个**真实结构**的运行目录，
# 再让页面去扫——这样顺带验证了「重启后历史还在」这条路。
_root = Path(tempfile.mkdtemp(prefix="smoke_hist_"))
fxr.build_run(_root, name="run-1", hits=5100, title="炮火弧线")
fxr.build_run(_root, name="run-2", hits=356, title="旧巷杂记")
mod = HistoryModule()
mod.set_runs_root(_root)
mod.refresh()
mod.show()  # offscreen 下让 isVisible 反映显隐状态


def count_rows(m):
    n = 0
    for i in range(m._table_body.count()):
        w = m._table_body.itemAt(i).widget()
        if w is not None and w.findChildren(QPushButton) \
                and any(b.text() == "删除" for b in w.findChildren(QPushButton)):
            n += 1
    return n


# 1) 初始渲染：磁盘上有几个运行目录就有几行
print("初始数据行数:", count_rows(mod))
assert count_rows(mod) == 2, "磁盘上 2 个运行目录应渲染 2 条"

# 2) 状态列：真实跑完的运行都是「正常」
labels = mod.findChildren(QLabel)
warn = [l for l in labels if l.text() == "基准同步失败"]
ok = [l for l in labels if l.text() == "正常"]
print("正常标签数:", len(ok), " 同步失败标签数:", len(warn))
assert len(ok) == 2 and len(warn) == 0

# 3) 设计依据开关
mod.basis_cb.setChecked(True)
mod.basis_cb.setChecked(False)
print("设计依据开关 OK")

# 4) 重新导出的入口已是真实执行层（点下去起后台线程，不再是假 toast）
assert not hasattr(mod, "_reexport"), "假动作 _reexport 应已删除"
assert hasattr(mod, "_run_export") and hasattr(mod, "_do_export"), "应接真实导出执行层"
print("重新导出接真实执行层 OK")

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
assert count_rows(mod) == 1, "删除后应为 1 行"
assert mod.undo_btn.isVisible(), "删除 toast 应显示撤销按钮"
mod._undo()
mod.refresh()
assert count_rows(mod) == 2, "撤销后恢复为 2 行"
assert mod.status.text() == "已撤销删除，该条历史已恢复"
print("删除 + 撤销 OK")

# 6) 「恢复历史结果」已如实降级为「用该次产物重新导出」，且真的去执行
mod._undo_stack.clear()
mod._active_idx = None
calls = []
mod._run_export = lambda t: calls.append(t.get("run_dir"))
mod._confirm_restore(0)
assert calls == [mod.tasks[0]["run_dir"]], "确认后应把该次运行交给真实导出执行层"
assert mod._active_idx == 0, "应把 0 号记录标记为当前工作区"
assert "当前工作区" in mod._active_hint.text(), "应刷新当前工作区提示"
print("恢复 = 用该次产物重新导出（真实执行）OK")

# 7) 清理全部：清空撤销栈（不可撤销）
mod._undo_stack.append(dict(type="delete", item=dict(mod.tasks[0]), index=0))
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

fxr.cleanup(_root)
print("SMOKE_OK")
