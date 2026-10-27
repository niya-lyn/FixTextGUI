"""诊断日志（M2-T2.4）——技术错误细节只进文件，不进界面。

设计：
- 每次错误记录一行 JSON（JSONL，便于排障工具逐行读）：
  ``{"ts", "code", "title", "exc_type", "message", "errno", "engine_code",
     "context", "traceback"}``
- 文件按「当天」命名（fixtext-YYYYMMDD.log），整天一个文件，追加写；
- 单文件超过 _ROTATE_BYTES 时滚动为 ``.1``（最多保留 1 个滚动副本）；
- 界面永远只拿人话文案；本模块产物仅供「设置 → 打开诊断日志目录」与支持排障。

线程安全：单进程内加锁写（Qt 主线程 / worker 线程都会写）。
初始化：``init(log_dir)``；未初始化时写到系统临时目录下的 ``fixtext-diag``。
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import tempfile
import threading

_ROTATE_BYTES = 2 * 1024 * 1024  # 单文件 2MB 滚动
_keep = 1

_lock = threading.Lock()
_log_dir: str | None = None
_enabled = True


def init(log_dir: str | None = None, enabled: bool = True) -> str:
    """初始化诊断日志目录（幂等，可重复调用）。返回当前日志目录。"""
    global _log_dir, _enabled
    _enabled = enabled
    if log_dir:
        _log_dir = log_dir
    elif _log_dir is None:
        base = os.environ.get("FIXTEXT_LOG_DIR")
        if base:
            _log_dir = base
        else:
            _log_dir = os.path.join(tempfile.gettempdir(), "fixtext-diag")
    os.makedirs(_log_dir, exist_ok=True)
    return _log_dir


def log_dir() -> str:
    """当前日志目录（未 init 时用默认并保证存在）。"""
    global _log_dir
    if _log_dir is None:
        init()
    assert _log_dir is not None
    return _log_dir


def log_path() -> str:
    """今天的日志文件完整路径。"""
    return os.path.join(log_dir(), f"fixtext-{_today()}.log")


def _today() -> str:
    return _dt.datetime.now().strftime("%Y%m%d")


def write_record(code: str, title: str, technical: dict) -> str | None:
    """追加一条错误记录，返回本次写入的文件路径；失败返回 None（永不抛异常）。

    technical 为 classify.format_technical 的产物（含 traceback）。
    """
    if not _enabled:
        return None
    try:
        with _lock:
            path = log_path()
            _rotate_if_needed(path)
            record = {
                "ts": _dt.datetime.now().isoformat(timespec="seconds"),
                "code": code,
                "title": title,
            }
            record.update(technical)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            return path
    except Exception:  # 日志绝不能把错误路径又炸一遍
        return None


def _rotate_if_needed(path: str) -> None:
    try:
        if os.path.exists(path) and os.path.getsize(path) > _ROTATE_BYTES:
            rotated = path + ".1"
            if os.path.exists(rotated):
                os.remove(rotated)
            os.replace(path, rotated)
    except Exception:
        pass


def read_records(path: str | None = None) -> list[dict]:
    """读回日志记录（测试 / 证据脚本用；损坏行跳过）。"""
    if path is None:
        path = log_path()
    out: list[dict] = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def last_record(path: str | None = None) -> dict | None:
    recs = read_records(path)
    return recs[-1] if recs else None
