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



# ---------------------------------------------------------------------------
# 进程级全局状态隔离（V1.1-F1：m5_ex1 分袋 smoke「批量跑挂」的根因修复）
#
# 引擎客户端把 subprocess 当**模块级属性**用：
#   pipeline/vendor/fixtext/engine/client.py → `import subprocess` + `subprocess.run(...)`
# 而 worker 每跑一次校正，就把这个属性换成「可取消代理」：
#   fixtext_ui/fixtext_worker.py → `_engine_client.subprocess = _SubprocessProxy(self)`
# 代理里绑的是那一次 job 的 cancel_requested——**被取消过的 job 永远是 True**，
# 代理又不会被摘掉，于是留给后面所有用例：之后每一次 Go 引擎调用都会直接抛
# 「已终止替换引擎」。这正是 m5_ex1 分袋 smoke「单跑过、批量跑挂」的机制。
#
# 这里用一条用例级 autouse fixture 给这类进程级全局量做「用例间复位」：
# 谁污染谁复位，同类测试直接复用这条 fixture，不必各自写清场代码。
# 复位只动**测试进程内的模块属性**，不碰任何产品逻辑。
# ---------------------------------------------------------------------------

#: 需要在用例之间复位的进程级全局量：(模块名, 属性名, 出厂值说明)
#: 出厂值说明只是给人看的，真实复位逻辑在 _reset_process_globals() 里。
PROCESS_GLOBAL_HOOKS = (
    ("fixtext.engine.client", "subprocess", "出厂值 = 标准库 subprocess 模块"),
    ("fixtext.engine.py_engine", "_cancel_check", "出厂值 = None"),
)


def _reset_process_globals() -> list[str]:
    """把引擎相关的进程级全局量复位到出厂值，返回真正复位过的项。

    只处理已经 import 进 ``sys.modules`` 的模块：引擎模块是靠
    ``fixtext_pipeline.vendor_bootstrap`` 把 ``pipeline/vendor`` 塞进
    ``sys.path`` 才导得进来的，测试收集阶段未必已经 import，
    所以这里查 ``sys.modules`` 而不是直接 import（避免在 conftest 里
    提前把 vendor 路径写进 sys.path，影响其它用例的导入顺序）。
    """
    import subprocess as _stdlib_subprocess

    restored: list[str] = []

    client = sys.modules.get("fixtext.engine.client")
    if client is not None and getattr(client, "subprocess", None) is not _stdlib_subprocess:
        client.subprocess = _stdlib_subprocess
        restored.append("fixtext.engine.client.subprocess")

    py_engine = sys.modules.get("fixtext.engine.py_engine")
    if py_engine is not None:
        setter = getattr(py_engine, "set_cancel_check", None)
        if callable(setter) and getattr(py_engine, "_cancel_check", None) is not None:
            setter(None)
            restored.append("fixtext.engine.py_engine._cancel_check")

    return restored


@pytest.fixture(autouse=True)
def _isolate_process_globals():
    """每条用例前后各复位一次进程级全局量。

    用例开始前复位：保证这条用例看到的是「出厂状态」，哪怕上一条用例崩了。
    用例结束后复位：这条用例留下的污染不带给下一条。
    """
    _reset_process_globals()
    yield
    _reset_process_globals()
