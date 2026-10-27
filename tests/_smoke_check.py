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
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import check_module as cm  # noqa: E402


app = QApplication(sys.argv)
mod = cm.CheckModule()
mod.show()  # offscreen 下让 isVisible 反映显隐状态


# 1) save_and_next 入栈 + 撤销回退
print("问题总数:", len(mod.probs))
mod.cur = 0
mod.probs[0]["state"] = None
before = dict(mod.probs[0])
mod.save_and_next()
assert mod.undo, "save_and_next 应推入撤销栈"
assert mod.undo[-1]["i"] == 0, "撤销记录应指向当前问题"
assert mod.probs[0]["state"] == "fixed", "save_and_next 应标记为已修复"
mod.undo_last()
assert mod.probs[0]["state"] == before["state"], "撤销应回退 fixed 标记"
assert mod.cur == 0, "撤销应回到原问题"
print("save_and_next 入栈 + 撤销回退 OK")


# 2) 批量操作入栈（批量记录）+ 撤销整体回退
# 打桩 QMessageBox.exec 直接返回 Ok，绕过阻塞式弹窗（保留真实类与枚举）
orig_exec = cm.QMessageBox.exec
cm.QMessageBox.exec = lambda self: QMessageBox.StandardButton.Ok
affected = mod._affected_single()
print("批量受影响处数:", len(affected))
assert affected, "应检出至少 1 处单引号"
idx, _p = affected[0]
orig_hl = mod.probs[idx]["hl"]
assert "‘" in orig_hl or "’" in orig_hl, "受影响处原文本应含单引号"
mod.batch_op()
cm.QMessageBox.exec = orig_exec
assert mod.undo and mod.undo[-1].get("batch"), "批量操作应推入批量撤销记录"
assert mod.undo[-1]["items"][0]["i"] == idx
assert "“" in mod.probs[idx]["hl"], "批量后单引号应转为双引号"
mod.undo_last()
assert mod.probs[idx]["hl"] == orig_hl, "撤销批量应整体回退原文"
print("批量操作入栈 + 撤销整体回退 OK")


print("CHECK_SMOKE_OK")
