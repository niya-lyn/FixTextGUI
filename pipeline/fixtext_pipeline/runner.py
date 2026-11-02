"""编排器主循环。

负责：准备目录 → 逐阶段执行/跳过 → 计时 → 写状态 → 出报告。

断点恢复的判定写在 :func:`_should_skip`：阶段状态为 done、输入指纹一致、
产物仍全部存在，三条同时满足才跳过；否则重跑该阶段。
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any

from .config import PipelineConfig, STAGE_META
from .logsetup import StageLogger, capture_output
from .report import build_report, write_report
from .stages import STAGES, StageError
from .state import StateStore, outputs_exist


class PipelineError(RuntimeError):
    """编排器级别的失败。"""


def _prepare(cfg: PipelineConfig) -> None:
    cfg.workdir.mkdir(parents=True, exist_ok=True)
    cfg.paths.logs.mkdir(parents=True, exist_ok=True)
    cfg.paths.report.mkdir(parents=True, exist_ok=True)
    for stage in cfg.stages:
        cfg.stage_dir(stage).mkdir(parents=True, exist_ok=True)


def _should_skip(
    cfg: PipelineConfig,
    store: StateStore,
    name: str,
    fingerprint: str,
) -> tuple[bool, str]:
    """返回 (是否跳过, 原因)。"""
    if not cfg.resume:
        return False, "未启用 --resume"
    if cfg.force:
        return False, "--force 强制重跑"
    stage = store.stage(name)
    if stage.status != "done":
        return False, f"上次状态为 {stage.status}"
    if not stage.fingerprint:
        return False, "上次没有记录指纹"
    if stage.fingerprint != fingerprint:
        return False, "输入指纹已变"
    if not outputs_exist(stage.outputs):
        return False, "上次产物已缺失"
    return True, "状态 done + 指纹一致 + 产物齐全"


def run_pipeline(cfg: PipelineConfig) -> tuple[int, dict[str, Any]]:
    """执行全链路。返回 (退出码, 运行报告)。"""
    from .vendor_bootstrap import bootstrap

    bootstrap()

    _prepare(cfg)
    store = StateStore(cfg.paths.state_file).load()
    store.set_config(cfg.to_dict())

    run_log = cfg.paths.run_log
    run_log.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.time()

    results: dict[str, dict[str, Any]] = {}
    status = "done"
    error = ""

    with StageLogger(run_log, echo=False) as log:
        log.log(f"=== FixTextGUI 一键校正编排器 · {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        log.log(f"输入 EPUB：{cfg.epub}")
        log.log(f"工作目录：{cfg.workdir}")
        log.log(f"排版档案：{cfg.layout_profile}　替换趟数：{cfg.replace_count}")

        for name in cfg.stages:
            meta = STAGE_META[name]
            stage_cls = STAGES[name]
            logger = StageLogger(cfg.paths.stage_log(name), echo=True)

            # 依赖检查
            missing_deps = [
                dep for dep in stage_cls.depends_on
                if results.get(dep, {}).get("status") not in ("done", "skipped")
            ]
            if missing_deps:
                message = f"前置阶段未完成：{missing_deps}"
                logger.log(f"[{name}][SKIP] {message}")
                logger.close()
                status = "failed"
                error = message
                results[name] = {
                    "status": "skipped",
                    "elapsed_s": 0.0,
                    "summary": message,
                    "outputs": [],
                }
                store.mark(name, status="skipped", error=message)
                break

            stage = stage_cls(cfg, logger)
            try:
                fingerprint = stage.fingerprint()
            except Exception as exc:  # noqa: BLE001
                message = f"指纹计算失败：{exc.__class__.__name__}: {exc}"
                logger.log(f"[{name}][FAIL] {message}")
                logger.close()
                status = "failed"
                error = message
                results[name] = {"status": "failed", "elapsed_s": 0.0, "summary": message, "outputs": []}
                break

            skip, reason = _should_skip(cfg, store, name, fingerprint)
            if skip:
                previous = store.stage(name)
                logger.log(f"[{name}][SKIP] {reason}（沿用上次结果，耗时 {previous.elapsed_s}s）")
                logger.close()
                results[name] = {
                    "status": "skipped",
                    "elapsed_s": previous.elapsed_s or 0.0,
                    "summary": f"断点恢复：{reason}",
                    "outputs": list(previous.outputs),
                    "report": previous.report,
                }
                log.log(f"[{name}] 跳过（{reason}）")
                continue

            logger.log(f"[{name}] 开始：{meta[1]}")
            stage_started = time.time()
            store.mark(name, status="running", fingerprint=fingerprint, started_at=stage_started)
            store.save()

            stage_report: dict[str, Any] = {}
            stage_status = "done"
            stage_error = ""
            try:
                with capture_output(logger):
                    stage_report = stage.run() or {}
            except StageError as exc:
                stage_status = "failed"
                stage_error = str(exc)
                logger.log(f"[{name}][FAIL] {stage_error}")
                logger.log(traceback.format_exc(limit=3))
            except Exception as exc:  # noqa: BLE001
                stage_status = "failed"
                stage_error = f"{exc.__class__.__name__}: {exc}"
                logger.log(f"[{name}][FAIL] {stage_error}")
                logger.log(traceback.format_exc(limit=6))
            finally:
                elapsed = round(time.time() - stage_started, 3)
                logger.close()

            outputs = [str(p) for p in stage.outputs()]
            store.mark(
                name,
                status=stage_status,
                fingerprint=fingerprint,
                ended_at=time.time(),
                elapsed_s=elapsed,
                outputs=outputs,
                report=stage_report,
                error=stage_error,
            )
            store.save()

            results[name] = {
                "status": stage_status,
                "elapsed_s": elapsed,
                "summary": _summarize(name, stage_report),
                "outputs": outputs,
                "report": stage_report,
                "error": stage_error,
            }
            log.log(f"[{name}] 结束：{stage_status}，耗时 {elapsed}s")

            if stage_status == "failed":
                status = "failed"
                error = f"{meta[1]} 失败：{stage_error}"
                if not cfg.keep_going:
                    break

        ended_at = time.time()
        report = build_report(
            cfg, results, started_at=started_at, ended_at=ended_at, status=status, error=error
        )
        json_path, md_path = write_report(cfg.paths.report, report)
        log.log(f"=== 结束：{status}，总耗时 {round(ended_at - started_at, 3)}s ===")
        log.log(f"报告：{json_path} / {md_path}")

    exit_code = 0 if status == "done" else 1
    return exit_code, report


def _summarize(name: str, stage_report: dict[str, Any]) -> str:
    """给报告表格准备一行摘要。"""
    if not isinstance(stage_report, dict):
        return ""
    if name == "merge":
        return f"{stage_report.get('chapters')} 章 / {stage_report.get('text_bytes')} 字节"
    if name == "layout":
        return (
            f"改 {stage_report.get('changed')} 章 / 回退 {stage_report.get('reverted')} 章"
            f"（档案 {stage_report.get('profile')}）"
        )
    if name == "replace":
        return (
            f"{stage_report.get('rules')} 条规则 × {stage_report.get('count')} 趟，"
            f"字符 {stage_report.get('chars_in')}→{stage_report.get('chars_out')}"
        )
    if name == "quote":
        return f"引号错误 {stage_report.get('error_count')} 处"
    if name == "bookmap":
        counts = stage_report.get("entry_counts") or {}
        total = sum(counts.values())
        return f"专有词条 {total} 条 → {Path(stage_report.get('book_map_file', '')).name}"
    if name == "restore":
        restore = stage_report.get("restore") or {}
        compare = stage_report.get("content_compare") or {}
        return (
            f"写回 {restore.get('chapters_written')} 章，"
            f"spine 顺序一致={compare.get('spine_order_equal')}"
        )
    return ""
