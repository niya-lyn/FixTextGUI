"""历史记录的真实数据层（无 Qt 依赖，可单独测试）
=================================================

历史一律**从磁盘扫描重建**，不存任何内存态假数据：

    runs/run-*/report/ui_run_summary.json

每个运行目录一次的摘要里有书名、完成时间、命中数、章数、成品校验值。
界面重启后重新扫一遍，历史就回来了——不依赖任何会话内状态。

条目上的动作都落到真实磁盘：
    add_task / scan_runs   读
    delete_run             删（真删运行目录，可撤销 = 目录移到回收站再移回）
    mark_exported          记最近一次重新导出的产物
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

SUMMARY_FILE = Path("report") / "ui_run_summary.json"

#: 单次扫描最多读多少个运行目录（防历史过多时启动变慢）
MAX_SCAN = 300

TIME_FMT = "%Y-%m-%d %H:%M"


def _fmt_time(ts: float | None) -> str:
    if not ts:
        return ""
    try:
        return time.strftime(TIME_FMT, time.localtime(float(ts)))
    except Exception:
        return ""


def _read_summary(run_dir: Path) -> dict | None:
    path = run_dir / SUMMARY_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _record_of(run_dir: Path, summary: dict) -> dict:
    """把一次运行的摘要整理成历史条目（字段缺失就留空，不编造）。"""
    title = summary.get("title") or summary.get("book") or run_dir.name
    started = summary.get("started_at") or 0
    finished = summary.get("finished_at") or 0
    if not finished:
        try:                      # 摘要没写完成时间时用目录时间（事实时间，不是猜测）
            finished = (run_dir / SUMMARY_FILE).stat().st_mtime
        except Exception:
            finished = 0
    hits = summary.get("hits")
    if hits is None:
        hits = summary.get("replace_hits")
    return dict(
        run_dir=str(run_dir),
        book=f"《{title}》" if title and not str(title).startswith("《") else str(title),
        title=str(title),
        time=_fmt_time(finished),
        time_ts=float(finished or 0),
        started_at=_fmt_time(started),
        hits=int(hits) if isinstance(hits, int) else None,
        chapters=summary.get("chapters"),
        quote_errors=summary.get("quote_errors"),
        sha256=str(summary.get("restored_sha256") or ""),
        status="ok",
        source_epub=str(summary.get("source_epub") or ""),
        author=str(summary.get("author") or ""),
        exported_at=str(summary.get("exported_at") or ""),
        exported_sha=str(summary.get("exported_sha256") or ""),
    )


def scan_runs(runs_root: str | Path) -> list[dict]:
    """扫运行目录，重建历史列表（按完成时间倒序）。

    只认带「运行摘要」的目录——那是校正真正跑完的证据；
    中途取消的运行目录会被清理，不会在这里冒充一条历史。
    """
    root = Path(runs_root)
    if not root.is_dir():
        return []
    out: list[dict] = []
    for run_dir in sorted(root.glob("run-*"))[:MAX_SCAN]:
        if not run_dir.is_dir():
            continue
        summary = _read_summary(run_dir)
        if summary is None:
            continue
        out.append(_record_of(run_dir, summary))
    out.sort(key=lambda r: r["time_ts"], reverse=True)
    return out


def write_run_meta(run_dir: str | Path, **fields: Any) -> dict | None:
    """把本次校正的关键信息补进运行摘要（书名 / 开始时间 / 命中数 / 来源）。

    摘要已经存在（校正收尾时写的那份），这里只补历史页需要的字段，
    不覆盖任何已记录的产物路径或统计。
    """
    run_dir = Path(run_dir)
    path = run_dir / SUMMARY_FILE
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(summary, dict):
        return None
    for key, value in fields.items():
        if value is not None:
            summary[key] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except Exception:
        return None
    return summary


def delete_run(run_dir: str | Path, trash_dir: str | Path | None = None) -> Path | None:
    """删除一条历史：把运行目录移到回收站（可撤销），返回它的落点。"""
    src = Path(run_dir)
    if not src.is_dir():
        return None
    if trash_dir:
        dest = Path(trash_dir)
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f"{src.name}-{int(time.time() * 1000)}"
        try:
            shutil.move(str(src), str(target))
            return target
        except Exception:
            return None
    shutil.rmtree(src, ignore_errors=True)
    return None


def restore_run(trash_path: str | Path, original: str | Path) -> bool:
    """撤销删除：把回收站里的运行目录移回原位。"""
    src, dest = Path(trash_path), Path(original)
    if not src.is_dir():
        return False
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return True
    except Exception:
        return False


def clear_all(runs_root: str | Path) -> int:
    """清理全部历史：删掉所有带摘要的运行目录，返回条数。"""
    root = Path(runs_root)
    n = 0
    for rec in scan_runs(root):
        shutil.rmtree(rec["run_dir"], ignore_errors=True)
        n += 1
    return n


def find_by_run_dir(records: list[dict], run_dir: str) -> dict | None:
    for rec in records:
        if rec.get("run_dir") == run_dir:
            return rec
    return None
