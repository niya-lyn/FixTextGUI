"""运行报告（JSON + Markdown）。

报告是验收标准 4 要求的「各阶段产物清单与运行耗时」的落盘版本，
``run_report.md`` 直接可贴进任务评论。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import PipelineConfig, STAGE_META


def build_report(
    cfg: PipelineConfig,
    stages: dict[str, dict[str, Any]],
    *,
    started_at: float,
    ended_at: float,
    status: str,
    error: str = "",
) -> dict[str, Any]:
    ordered = [name for name in STAGE_META if name in stages]
    total_elapsed = round(ended_at - started_at, 3)
    stage_elapsed = round(
        sum(float(stages[name].get("elapsed_s") or 0.0) for name in ordered), 3
    )
    return {
        "status": status,
        "error": error,
        "epub": str(cfg.epub),
        "workdir": str(cfg.workdir),
        "config": cfg.to_dict(),
        "started_at": started_at,
        "ended_at": ended_at,
        "total_elapsed_s": total_elapsed,
        "stage_elapsed_sum_s": stage_elapsed,
        "stages": {name: stages[name] for name in ordered},
    }


def _fmt_seconds(value: float | None) -> str:
    if value is None:
        return "-"
    if value < 1:
        return f"{value:.2f}s"
    if value < 60:
        return f"{value:.1f}s"
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes)}m{seconds:04.1f}s"


def render_markdown(report: dict[str, Any]) -> str:
    """把报告渲染成 Markdown（给评论与归档用）。"""
    lines: list[str] = []
    lines.append("# FixText 一键校正编排器 · 运行报告")
    lines.append("")
    lines.append(f"- 输入 EPUB：`{report['epub']}`")
    lines.append(f"- 工作目录：`{report['workdir']}`")
    lines.append(f"- 运行状态：**{report['status']}**")
    lines.append(f"- 总耗时：{_fmt_seconds(report['total_elapsed_s'])}"
                 f"（各阶段耗时合计 {_fmt_seconds(report['stage_elapsed_sum_s'])}）")
    lines.append("")

    lines.append("## 阶段耗时")
    lines.append("")
    lines.append("| # | 阶段 | 引擎 | 状态 | 耗时 | 关键结果 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for index, (name, meta) in enumerate(STAGE_META.items(), start=1):
        stage = report["stages"].get(name)
        if not stage:
            continue
        summary = stage.get("summary", "")
        lines.append(
            f"| {index} | {meta[1]} | `{name}` | {stage.get('status')} | "
            f"{_fmt_seconds(stage.get('elapsed_s'))} | {summary} |"
        )
    lines.append("")

    lines.append("## 各阶段产物")
    lines.append("")
    for name in report["stages"]:
        stage = report["stages"][name]
        outputs = stage.get("outputs") or []
        if not outputs:
            continue
        lines.append(f"### {STAGE_META[name][1]}")
        lines.append("")
        for item in outputs:
            lines.append(f"- `{item}`")
        lines.append("")

    if report.get("error"):
        lines.append("## 失败信息")
        lines.append("")
        lines.append("```")
        lines.append(report["error"])
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def write_report(report_dir: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "run_report.json"
    md_path = report_dir / "run_report.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path
