"""pytest 共享配置（合并包版：M2-T2.5 集成联调）。

T2.2 原始包把测试放在 `tests/` 同级、源码在 `ui_kit/`；
合并后源码统一落在 `pkg/fixtext_ui/`，因此 sys.path 指向包根 + fixtext_ui。
其余 fixture 与原包保持一致，用例本身一字未改。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # build/pkg
for p in (ROOT, ROOT / "fixtext_ui"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SAMPLES = Path(__file__).resolve().parent / "samples"

#: 无头渲染：CI / 沙箱里没有显示器，Qt 必须在离屏后端下跑
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _isolated_settings(tmp_path_factory):
    """M4-EX.2a：设置文件指到会话临时目录。

    设置页（词库位置 / 日志目录 / 引擎 / 开关）全部落在 settings.ini，
    测试必须与包内真实配置隔离，否则上一次人工验收留下的值会串进用例。
    """
    target = tmp_path_factory.mktemp("settings") / "settings.ini"
    os.environ["FIXTEXT_SETTINGS_FILE"] = str(target)
    yield
    os.environ.pop("FIXTEXT_SETTINGS_FILE", None)


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """合并包内 Qt 一定可用：整轮测试共用一个离屏 QApplication。

    T2.4 的用例会在 report() 里真的弹错误卡（非模态对话框），
    T2.2 的用例会构建 ImportModule 界面 —— 两者都必须先有 QApplication，
    否则没有应用实例时创建 QWidget 会让进程直接 abort（不是抛异常）。
    单独跑 T2.4 原包时 Qt 不可导入、错误卡走降级分支，所以那边不需要。
    """
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:                                    # pragma: no cover
        yield None
        return
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="session")
def qt_app(qapp):
    """原 T2.2 包里的名字（test_no_jargon 用它）；与 qapp 是同一个应用实例。"""
    return qapp


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
    d = tmp_path / "ws"
    d.mkdir(parents=True, exist_ok=True)
    return d
