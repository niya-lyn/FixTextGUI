"""应用设置落点（M4-T4.4 写路径收口）。

问题：原先首启向导的「看过没有」用 ``QSettings("FixText", "V1")`` 存，
Qt 会把它写到**操作系统的配置目录**（Linux ``~/.config/FixText/V1.conf``、
Windows 注册表或 ``%APPDATA%``、macOS ``~/Library/Preferences``）——那是
包根之外的位置，与「绿色分发、整棵包搬走即可」冲突，也过不了写路径审计
（写点只允许 workspace / runs / logs / 用户显式选择的导出目录）。

做法：设置一律存进**用户区** ``<包根>/workspace/settings.ini``（IniFormat，
纯文本、可随包搬走）。``FIXTEXT_SETTINGS_FILE`` 可显式指定文件，
验收脚本用它把每个阶段的状态隔离开。

兼容：对外仍是 ``QSettings`` 的子类，``QSettings("FixText", "V1")`` 这种
两参数调用照旧可用（参数被忽略，落点固定为用户区文件），所以界面代码与
既有脚本不需要改调用形态。
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSettings

# 包根统一由 fixtext_paths 解析（M4-T4.1b，冻结后 __file__ 不再指源码树）
try:
    from fixtext_paths import pkg_root as _pkg_root

    PKG_ROOT = _pkg_root()
except Exception:                     # pragma: no cover
    PKG_ROOT = Path(__file__).resolve().parent.parent
#: 用户区里的设置文件名（不是内置词库那棵 ``data/rules/`` 子树）
SETTINGS_FILE = "settings.ini"


def settings_path() -> Path:
    """设置文件路径：``FIXTEXT_SETTINGS_FILE`` 优先，否则用户区 ``workspace/``。"""
    override = os.environ.get("FIXTEXT_SETTINGS_FILE")
    if override:
        target = Path(override)
    else:
        target = PKG_ROOT / "workspace" / SETTINGS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


class AppSettings(QSettings):
    """固定落在用户区的设置对象（IniFormat，忽略组织 / 应用名参数）。"""

    def __init__(self, *args, **kwargs):        # noqa: D401 - 参数仅为调用形态兼容
        super().__init__(str(settings_path()), QSettings.Format.IniFormat)


# ---------------------------------------------------------------------------
# 设置页持久化键（M4-EX.2a）
# ---------------------------------------------------------------------------
# 值统一存字符串（IniFormat 下布尔也走 "1"/"0"，避免 true/false 方言问题）。

KEY_ENGINE = "engine"            # 替换引擎：go | python（默认 go）
KEY_VOCAB_DIR = "vocabDir"       # 自定义词库存储位置（空串 = 包内默认）
KEY_LOG_DIR = "logDir"           # 诊断日志目录（空串 = 包内默认目录）
KEY_DIAG_ENABLED = "diagEnabled" # 出错时自动保留现场（默认开）
KEY_SHOW_BASIS = "showBasis"     # 显示设计依据（默认关）

#: 与 M4-T4.2（引擎双轨）的对接契约：取值只有这两个，默认 go。
ENGINE_CHOICES = ("go", "python")
ENGINE_DEFAULT = "go"


def _get(key: str, default: str = "") -> str:
    s = AppSettings()
    v = s.value(key, default)
    return str(v) if v is not None else default


def _set(key: str, value: str) -> None:
    s = AppSettings()
    s.setValue(key, str(value))
    s.sync()


def engine() -> str:
    """替换引擎选择（go / python）。非契约取值一律回落 go。"""
    v = _get(KEY_ENGINE, ENGINE_DEFAULT)
    return v if v in ENGINE_CHOICES else ENGINE_DEFAULT


def set_engine(v: str) -> None:
    if v not in ENGINE_CHOICES:
        return
    _set(KEY_ENGINE, v)


def vocab_dir() -> Path | None:
    """自定义词库存储位置；未配置（空）返回 None = 包内默认。"""
    v = _get(KEY_VOCAB_DIR).strip()
    return Path(v) if v else None


def set_vocab_dir(p: str | Path | None) -> None:
    _set(KEY_VOCAB_DIR, str(p).strip() if p else "")


def vocab_custom_file() -> Path | None:
    """按当前设置算「我的词库」文件位置（设置空时 None = 走包内默认）。"""
    d = vocab_dir()
    if d is None:
        return None
    from fixtext_vocab import CUSTOM_FILE    # 延迟导入：文件名常量只此一份
    return d / CUSTOM_FILE


def log_dir() -> Path | None:
    """诊断日志目录；未配置（空）返回 None，即用包内默认目录。"""
    v = _get(KEY_LOG_DIR).strip()
    return Path(v) if v else None


def set_log_dir(p: str | Path | None) -> None:
    _set(KEY_LOG_DIR, str(p).strip() if p else "")


def diag_enabled() -> bool:
    return _get(KEY_DIAG_ENABLED, "1") == "1"


def set_diag_enabled(on: bool) -> None:
    _set(KEY_DIAG_ENABLED, "1" if on else "0")


def show_basis() -> bool:
    return _get(KEY_SHOW_BASIS, "0") == "1"


def set_show_basis(on: bool) -> None:
    _set(KEY_SHOW_BASIS, "1" if on else "0")
