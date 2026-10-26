"""空壳应用启动 / 退出验证（offscreen）。

T0.1 验收项：主窗口能启动能退出。本用例用 QTimer 驱动事件循环，
真实走一遍 app.exec()，而不是只构造窗口对象。
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QTimer  # noqa: E402

from fixtext.app import build_application, create_main_window  # noqa: E402


@pytest.mark.gui
def test_app_builds_and_quits() -> None:
    """事件循环能进入、主窗口可见、并在定时器触发的 quit 后正常退出。"""
    app = build_application([])
    window = create_main_window()
    window.show()

    observed: dict[str, bool] = {}

    def _probe() -> None:
        observed["visible"] = window.isVisible()
        observed["title"] = window.windowTitle().startswith("FixText")  # type: ignore[assignment]
        app.quit()

    QTimer.singleShot(120, _probe)
    exit_code = app.exec()

    assert exit_code == 0, f"事件循环返回码应为 0，实际 {exit_code}"
    assert observed.get("visible") is True, "定时器触发时主窗口应处于可见状态"
    assert observed.get("title") is True, "窗口标题应以 FixText 开头"

    window.close()


@pytest.mark.gui
def test_close_event_terminates_window() -> None:
    """关闭主窗口应真正关闭，不残留窗口。"""
    build_application([])
    window = create_main_window()
    window.show()
    assert window.isVisible()

    assert window.close() is True
    assert not window.isVisible()


@pytest.mark.gui
def test_app_console_entrypoint_returns_zero() -> None:
    """命令行入口 --smoke-test 返回 0，等价于「启动即正常退出」。"""
    from fixtext.app import main

    assert main(["--smoke-test", "150", "--log-level", "WARNING"]) == 0
