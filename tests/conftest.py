"""pytest 共享配置：把包根与 ui_kit 加进 sys.path，并把样本目录准备好。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "ui_kit"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SAMPLES = Path(__file__).resolve().parent / "samples"

#: 无头渲染：CI / 沙箱里没有显示器，Qt 必须在离屏后端下跑
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    return SAMPLES


@pytest.fixture()
def sample(samples_dir):
    """按文件名取一个样本，返回 Path。"""
    def _get(name: str) -> Path:
        p = samples_dir / name
        assert p.exists(), f"样本缺失：{name}"
        return p
    return _get


@pytest.fixture()
def workdir(tmp_path):
    """每个用例独立工作区，互不干扰。"""
    return tmp_path / "workspace"


@pytest.fixture(scope="session")
def qt_app():
    """会话级 QApplication（Qt 不允许建多个）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
