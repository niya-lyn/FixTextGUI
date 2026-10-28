"""引擎选择的数据层（M4-T4.2 · 排期 §3.3 / §3.1「Go 默认 / Python 可选」）。

**契约键**：``engine``，取值 ``go`` | ``python``，默认 ``go``。
本模块是唯一的读写实现；设置页的引擎选择控件（M4-EX.2a，UI 线）与本卡
的 replace 阶段 / worker 都通过这里取值——**键名两边一致，不另立第二套**。

落点：与 M4-T4.4 收口后的应用设置同一个文件（用户区
``<包根>/workspace/settings.ini``，``FIXTEXT_SETTINGS_FILE`` 可覆盖）。
QSettings(IniFormat) 把无分组键写在 ``[General]`` 节下，本模块用标准库
``configparser`` 读写同一个节，两种写入方式互相可读（值都是纯 ASCII 的
``go`` / ``python``，无转义差异）。

读取优先级：环境变量 ``FIXTEXT_ENGINE``（测试 / 一次性覆盖，不落盘）→
设置文件 ``[General] engine`` → 默认 ``go``。

降级口径（排期 §3.3）：Go 引擎缺失 / 启动失败 / 被杀软隔离时，经用户确认
改走 Python 引擎——**确认只对本次运行生效**，本模块的持久化值不被降级
路径改写；只有设置页（或显式调用 ``set_engine_choice``）才改长期设置。

Go 可用性检测：``go_engine_status`` 做三级检查——文件在不在、可不可执行
（自动补执行位后仍不行才算失败）、能否真的启动（无参跑一次，进程能起即
可，退出码不要求 0——这是「被杀软换成占位文件 / 架构不符」的探针）。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

#: 契约键名（M4-EX.2a 设置页控件与 replace 阶段共用，不得另起名）
ENGINE_KEY = "engine"

ENGINE_GO = "go"
ENGINE_PYTHON = "python"

#: 合法取值（顺序即 UI 展示顺序：Go 默认在前）
ENGINE_CHOICES = (ENGINE_GO, ENGINE_PYTHON)

#: 默认引擎（排期 §3.1：Go 默认 / Python 可选）
DEFAULT_ENGINE = ENGINE_GO

#: 设置文件里无分组键所在的节（QSettings IniFormat 的固定行为）
_SETTINGS_SECTION = "General"


def settings_file(pkg_root: Path | str | None = None) -> Path:
    """设置文件路径：``FIXTEXT_SETTINGS_FILE`` 优先，否则用户区 ``workspace/``。

    pkg_root 缺省按本模块位置推算（``pipeline/fixtext_pipeline/`` 的上两级
    = 包根），与 ``fixtext_settings.settings_path()`` 落同一文件。
    """
    override = os.environ.get("FIXTEXT_SETTINGS_FILE")
    if override:
        return Path(override)
    if pkg_root is None:
        pkg_root = Path(__file__).resolve().parents[2]
    return Path(pkg_root) / "workspace" / "settings.ini"


def normalize_choice(value: object) -> str:
    """把任意输入归一成合法引擎值：不认识的一律回落默认 ``go``。"""
    text = str(value or "").strip().lower()
    if text == ENGINE_PYTHON:
        return ENGINE_PYTHON
    return ENGINE_GO


def get_engine_choice(*, file: Path | str | None = None) -> str:
    """当前生效的引擎：环境变量 → 设置文件 → 默认 ``go``。"""
    env = os.environ.get("FIXTEXT_ENGINE")
    if env:
        return normalize_choice(env)
    path = Path(file) if file is not None else settings_file()
    try:
        import configparser

        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        if parser.has_option(_SETTINGS_SECTION, ENGINE_KEY):
            return normalize_choice(parser.get(_SETTINGS_SECTION, ENGINE_KEY))
    except (OSError, ValueError):
        pass                      # 读不到 / 文件坏：按默认，不在这里抛
    return DEFAULT_ENGINE


def set_engine_choice(value: str, *, file: Path | str | None = None) -> str:
    """持久化引擎选择（设置页控件 / 验收脚本用）。

    值先归一；文件按 QSettings IniFormat 兼容格式写（``key=value`` 无空格），
    保留文件里已有的其它键。返回归一后的值。
    """
    choice = normalize_choice(value)
    path = Path(file) if file is not None else settings_file()
    import configparser

    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    if not parser.has_section(_SETTINGS_SECTION):
        parser.add_section(_SETTINGS_SECTION)
    parser.set(_SETTINGS_SECTION, ENGINE_KEY, choice)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        parser.write(fh)
    return choice


# ---------------------------------------------------------------------------
# Go 引擎可用性检测（降级路径的触发判据）
# ---------------------------------------------------------------------------

def go_engine_status(engine_path: Path | str) -> tuple[bool, str]:
    """检查 Go 引擎当前是否可用，返回 (可用, 人话原因)。

    三级检查：
      1. 文件存在且是普通文件（缺失 = 被删 / 被杀软隔离走的最常见形态）；
      2. POSIX 上有执行位（先尝试自动补——zip 解包丢 +x 是已知情况，
         补完仍不可执行才算失败）；
      3. 启动探针：无参跑一次，进程能起来并退出即可（退出码不要求 0，
         引擎无参时打印用法退出码 1 属正常）——探的是「二进制真的能执行」，
         捕获 OSError / Exec format error / 超时。
    """
    path = Path(engine_path)
    if not path.exists():
        return False, f"引擎文件不存在（可能被删除或被杀毒软件隔离）：{path.name}"
    if not path.is_file():
        return False, f"引擎路径不是普通文件：{path.name}"
    if os.name != "nt" and not os.access(path, os.X_OK):
        try:
            path.chmod(path.stat().st_mode | 0o111)
        except OSError:
            pass
        if not os.access(path, os.X_OK):
            return False, f"引擎文件没有执行权限：{path.name}"
    try:
        subprocess.run(
            [str(path)],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "引擎启动后长时间无响应（可能是杀毒软件拦截）"
    except OSError as exc:
        return False, f"引擎无法启动：{exc.__class__.__name__}"
    return True, ""
