"""包根解析的唯一入口（M4-T4.1b 打包适配）。

源码运行时包根就是本文件所在目录；打包（PyInstaller onedir）后 ``__file__``
指向程序内部目录，各模块靠 ``Path(__file__).parent.parent`` 反推会算错一层，
词库 / 引擎 / 用户区全都找不到。这里统一按可执行文件所在目录解析，
并允许用环境变量 ``FIXTEXT_PKG_ROOT`` 覆盖（便于把用户区搬到别处）。
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

#: 包根覆盖环境变量名
ENV_PKG_ROOT = "FIXTEXT_PKG_ROOT"


def is_frozen() -> bool:
    """当前进程是否由 PyInstaller 打包运行。"""
    return bool(getattr(sys, "frozen", False))


def pkg_root() -> Path:
    """包根目录：环境变量 > 打包后的可执行文件目录 > 源码目录。"""
    override = os.environ.get(ENV_PKG_ROOT)
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_export_dir() -> Path:
    """默认导出目录：包根下的 ``导出/``（与 workspace / runs 同级）。"""
    out = pkg_root() / "导出"
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# 导出目录口径（V1.1-EX.1-R1）
#
# 所有导出都收在 ``导出/`` 这一棵树里，分成两种形态：
#   · 导出页：平铺在 ``导出/书名.txt`` / ``导出/书名替换统计.txt|.csv``；
#   · 历史页「重新导出」：``导出/历史记录/<书名>_<YYYYMMDD_HHMMSS>/``，
#     书名与时间戳用下划线拼成**同一个单层目录名**，每次导出新目录、不覆盖。
# ---------------------------------------------------------------------------

#: 历史导出子目录名（在导出根之下）
HISTORY_DIRNAME = "历史记录"

#: 历史导出目录名里的时间戳格式（沿用旧口径，但不带 ``export_`` 前缀）
HISTORY_STAMP_FORMAT = "%Y%m%d_%H%M%S"

#: 书名清洗后为空时的兜底名
UNNAMED_BOOK = "未命名"

#: 文件系统非法字符（Windows 口径同时覆盖 POSIX 的 ``/``）
ILLEGAL_NAME_CHARS = frozenset('<>:"/\\|?*\n\r\t\0')

#: 单层目录名长度上限（书名部分）
DIR_NAME_MAX = 60


def safe_dir_name(name: str, *, fallback: str = UNNAMED_BOOK,
                  limit: int = DIR_NAME_MAX) -> str:
    """把书名清洗成能当**单层目录名**的形式。

    - 剔除文件系统非法字符（``\\ / : * ? " < > |`` 与控制字符）；
    - 去掉首尾的书名号、空白与点号（Windows 不允许目录名以点结尾）；
    - 清完为空（或只剩点号 / 空白）时退回 ``未命名``；
    - 过长时截断（截断后再清一次尾部空白与点，避免制造新的尾随点）。
    """
    cleaned = "".join(ch for ch in str(name or "") if ch not in ILLEGAL_NAME_CHARS)
    cleaned = cleaned.strip().strip("《》").strip().strip(".")
    cleaned = cleaned[:limit].strip().strip("《》").strip().strip(".")
    return cleaned or fallback


def _export_root(export_root: str | Path | None) -> Path:
    """导出根（**不建目录**）：给了就用给的，没给就用包根下的 ``导出/``。"""
    return Path(export_root) if export_root else pkg_root() / "导出"


def history_export_root(export_root: str | Path | None = None) -> Path:
    """历史导出的根目录：``<导出根>/历史记录``（不存在就建）。

    :param export_root: 导出根（默认 ``default_export_dir()``，即包根下的 ``导出/``）。
    """
    out = _export_root(export_root) / HISTORY_DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    return out


def history_export_dir(book: str, *, when: str | None = None,
                       export_root: str | Path | None = None) -> Path:
    """算出历史导出的目标目录（**只算路径，不建任何目录**，纯函数）。

    形态固定为 ``<导出根>/历史记录/<书名>_<时间戳>``——两层父目录 + 一个单层
    目录名，书名与时间戳之间只有一个下划线，不再按书名 / 时间戳分两层。
    """
    stamp = time.strftime(HISTORY_STAMP_FORMAT) if when is None else str(when)
    if not re.fullmatch(r"\d{8}_\d{6}", stamp):
        raise ValueError(f"时间戳必须形如 YYYYMMDD_HHMMSS：{stamp!r}")
    return _export_root(export_root) / HISTORY_DIRNAME / f"{safe_dir_name(book)}_{stamp}"


def reserve_history_export_dir(book: str, *,
                               export_root: str | Path | None = None) -> Path:
    """算出并**占位创建**本次历史导出的目录（同一秒连续导出也不撞车）。

    用 ``mkdir`` 的原子性抢目录：候选名已被占用（同一本书同一秒导出两次，或
    另一个进程正好在同一秒导出）时，把时间戳顺延到下一个未占用的秒——
    目录名形态不变，仍是 ``<书名>_<时间戳>``，且永不覆盖已有导出。
    """
    root = history_export_root(export_root)
    safe = safe_dir_name(book)
    start = time.time()
    for step in range(120):                      # 最多顺延 120 秒，够用了
        candidate = root / f"{safe}_{time.strftime(HISTORY_STAMP_FORMAT, time.localtime(start + step))}"
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise OSError(f"同一本书连续导出太密，找不到空目录：{root}")
