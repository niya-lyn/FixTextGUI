#!/usr/bin/env python3
"""FixText V1 · 主程序入口（M2-T2.5 四卡集成）

一个入口把四张卡拼成可运行的程序：

    python main_app.py

启动顺序（与 T2.4 的接线形态一致）：
1. 把包根与 `fixtext_ui/` 放进 `sys.path`（模块之间是平级 import：`fixtext_tokens`
   / `import_module` / `oneclick_module` / `fixtext_import` / `fixtext_error_center`）；
2. 建 QApplication + 加载 `fixtext.qss`；
3. 初始化错误中心：`init(日志目录)` → `install_app_hooks()`；
4. 建主窗口，`set_dialog_host(win)`，show。

目录约定（绿色分发，整体搬走即可）：
    workspace/   导入的书副本与导入记录（用户可见）
    runs/        每次校正的工作目录与替换报告
    logs/        诊断日志（设置页可一键打开）
    data/rules/  词库规则（before / after）
    pipeline/    M1 编排器与引擎（一键校正的真链路）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 包根：源码态是本文件所在目录；打包后是可执行文件所在目录（M4-T4.1b）。
# 先算出来并写进环境变量，后续所有模块（含 pipeline 里的）统一按它定位——
# 冻结后 __file__ 不再指源码树，各自反推会算错一层，词库 / 引擎 / 用户区全会找不到。
if getattr(sys, "frozen", False):
    HERE = Path(sys.executable).resolve().parent
else:
    HERE = Path(__file__).resolve().parent
os.environ.setdefault("FIXTEXT_PKG_ROOT", str(HERE))

UI = HERE / "fixtext_ui"
for p in (str(UI), str(HERE)):
    # 打包后 fixtext_ui 不是目录（模块已平铺进程序内部目录），跳过即可
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", ""))


def ensure_dirs() -> None:
    for name in ("workspace", "runs", "logs"):
        (HERE / name).mkdir(parents=True, exist_ok=True)


def main() -> int:
    # M4-T4.1b：打包自检入口。`FixText.exe --self-check` 不打开界面，
    # 直接把「包根对不对 / 词库和引擎在不在 / 新用户会不会看到向导」打印出来。
    if "--self-check" in sys.argv[1:]:
        import fixtext_self_check   # noqa: PLC0415

        return fixtext_self_check.main()

    # 打包冒烟（仅试打包包内含此模块）：在冻结进程里跑通导入→校正→导出。
    # 正式绿色包不放这个模块，所以这里用可缺省导入。
    if "--smoke" in sys.argv[1:]:
        try:
            import fxbundle_smoke   # noqa: PLC0415
        except ImportError:
            print("本包不含打包冒烟模块（正式版不需要）。")
            return 2
        return fxbundle_smoke.main()

    from PySide6.QtWidgets import QApplication, QMessageBox

    from main_window import MainWindow, load_qss  # noqa: PLC0415

    ensure_dirs()
    app = QApplication(sys.argv)
    app.setApplicationName("FixText")
    load_qss(app)

    # P2-2：macOS 等无引擎平台启动即明示不支持完整校正（仍可打开界面查看）
    if sys.platform == "darwin":
        QMessageBox.warning(
            None,
            "当前系统不支持完整校正",
            "FixText 的一键校正目前只支持 Windows 与 Linux。\n\n"
            "在 Mac 上可以打开界面、导入与查看，但无法跑完整校正链路。"
            "请改用 Windows 或 Linux 完成校正与导出。",
        )

    try:
        import fixtext_error_center as error_center
    except Exception:
        error_center = None

    if error_center is not None:
        # M4-EX.2a：日志目录 / 留痕开关优先取设置页保存的值，未配置用包内默认
        try:
            import fixtext_settings as app_settings   # noqa: PLC0415
            _log_dir = app_settings.log_dir()
            _diag = app_settings.diag_enabled()
        except Exception:                              # noqa: BLE001
            _log_dir, _diag = None, True
        try:
            error_center.init(
                str(_log_dir) if _log_dir is not None else str(HERE / "logs"),
                enabled=_diag)
        except Exception:
            pass
        try:
            error_center.install_app_hooks()
        except Exception:
            pass

    win = MainWindow(HERE / "workspace")
    if error_center is not None:
        try:
            error_center.set_dialog_host(win)
        except Exception:
            pass
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
