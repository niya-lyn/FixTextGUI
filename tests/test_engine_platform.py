# -*- coding: utf-8 -*-
"""平台引擎选择：单元断言 + 真实调用 build_run_context 的注入断言。

这条测试存在的理由：只测 engine_selector 是「自己测自己」，证明不了界面真的
用上了它。所以最关键的用例是 test_build_run_context_injects_platform_engine
—— 真的把一个导入记录摆好、真的调主窗口的 build_run_context，断言它注入的
engine_path 是本平台那一个。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "fixtext_ui"))

from fixtext_pipeline import engine_selector  # noqa: E402

BIN = ROOT / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"


@pytest.fixture()
def fake_platform(monkeypatch):
    def as_(plat: str):
        monkeypatch.setattr(sys, "platform", plat)
    return as_


def test_windows_picks_exe_even_when_both_exist(fake_platform):
    """两引擎并存的包（最常见）里，Windows 必须拿 .exe，不许回落 Linux。"""
    assert (BIN / engine_selector.WINDOWS_NAME).is_file()
    assert (BIN / engine_selector.LINUX_NAME).is_file()
    fake_platform("win32")
    got = engine_selector.select_engine(BIN)
    assert got is not None
    assert got.name == engine_selector.WINDOWS_NAME


def test_linux_picks_elf(fake_platform):
    fake_platform("linux")
    got = engine_selector.select_engine(BIN)
    assert got is not None and got.name == engine_selector.LINUX_NAME


def test_darwin_returns_none_with_readable_reason(fake_platform):
    fake_platform("darwin")
    assert engine_selector.select_engine(BIN) is None
    reason = engine_selector.unsupported_reason()
    assert reason and "不支持" in reason
    # 不许给 macOS 用户 Linux 专属建议
    assert "chmod" not in reason


def test_windows_missing_exe_returns_none_not_linux(fake_platform, tmp_path):
    """目录里只有 Linux 版时，Windows 必须返回 None —— 证明没有回落。"""
    import shutil
    shutil.copy2(BIN / engine_selector.LINUX_NAME,
                 tmp_path / engine_selector.LINUX_NAME)
    fake_platform("win32")
    assert engine_selector.select_engine(tmp_path) is None


def test_windows_reason_has_no_chmod_hint(fake_platform, tmp_path):
    fake_platform("win32")
    reason = engine_selector.unsupported_reason()
    assert "chmod" not in reason
    assert ".exe" in reason


def test_discover_engine_uses_same_selector(fake_platform):
    """CLI 侧不能自成一套顺序。"""
    from fixtext_pipeline import cli
    fake_platform("linux")
    got = cli.discover_engine()
    assert got is not None and got.name == engine_selector.LINUX_NAME


def test_build_run_context_injects_platform_engine(fake_platform, tmp_path):
    """真实调用主窗口 build_run_context，断言注入的是本平台引擎。

    造一本书目录：``import.json`` 指向一个真实存在的副本文件。
    """
    pytest.importorskip("PySide6")
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import main_window as mw

    book_dir = tmp_path / "book"
    book_dir.mkdir()
    original = book_dir / "text.epub"
    original.write_bytes(b"PK\x03\x04")          # 内容无所谓，只要存在
    working = book_dir / "book.txt"
    working.write_text("工作区正文", encoding="utf-8")
    (book_dir / "import.json").write_text(json.dumps({
        "original_copy_path": str(original),
        "title": "探针书",
        "author": "",
    }), encoding="utf-8")

    win = mw.MainWindow.__new__(mw.MainWindow)   # 不走完整窗口构造（太重）

    fake_platform("win32")
    ctx = mw.MainWindow.build_run_context(win, str(working))
    assert ctx is not None, "Windows 下应能构建上下文（包里确有 .exe）"
    assert Path(ctx["engine_path"]).name == engine_selector.WINDOWS_NAME, (
        f"Windows 注入的引擎错了：{ctx['engine_path']}")
    # EPUB：校正吃 book.txt；原件只作导出模板
    assert ctx.get("plain_source") == str(working)
    assert ctx.get("template_epub") == str(original)
    assert "epub" not in ctx
    # 无账本时仍可建上下文（TXT 包装兜底）；有账本则注入
    assert "ledger_path" not in ctx or Path(ctx["ledger_path"]).name.endswith(".json")

    fake_platform("linux")
    ctx = mw.MainWindow.build_run_context(win, str(working))
    assert ctx is not None
    assert Path(ctx["engine_path"]).name == engine_selector.LINUX_NAME


def test_main_window_has_no_hardcoded_engine_literal():
    """界面代码里不许再出现写死的引擎文件名（判断已收敆到唯一入口）。"""
    src = (ROOT / "fixtext_ui" / "main_window.py").read_text(encoding="utf-8")
    assert "replace_by_go-linux-amd64" not in src
    assert "replace_by_go-windows-amd64.exe" not in src
