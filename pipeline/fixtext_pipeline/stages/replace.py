"""阶段 3：词库替换（T0.3 Go 引擎子进程协议 + T0.2 词库）。

**本阶段不实现任何字符串替换逻辑**：规则集、请求、进程调度、错误归类全部走
T0.3 的 ``fixtext.engine`` 集成层——

    RuleSet.from_files(before.json, after.json)   # 规则
    EngineRequest(count=2, input_mode=FILE, output_mode=FILE)
    GoEngineClient.run(request)                    # 真正起子进程

替换趟数 ``count`` 默认 2，与上游 ``TextFixer`` 的 ``$replaceCount = 2`` 一致。

替换完成后做一次 **边界完整性复检**：用账本严格切分替换后的 TXT，
标记一旦被词条打坏，切分就会失败，阶段直接报错而不是把坏文本往下传。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..config import dump_json
from ..state import sha256_file
from .base import Stage, StageError


class ReplaceStage(Stage):
    name = "replace"
    title = "词库替换（T0.3 Go 引擎 + T0.2 词库）"
    depends_on = ("layout",)

    def outputs(self) -> list[Path]:
        return [
            self.cfg.replace_before(),
            self.cfg.replace_after(),
            self.cfg.stage_dir(self.name) / "replace_report.json",
        ]

    def fingerprint(self) -> str:
        return self.fingerprint_of(
            f"input={sha256_file(self.cfg.layout_text())}",
            f"rules={sha256_file(self.cfg.rules_before)}",
            f"rules_after={sha256_file(self.cfg.rules_after)}",
            f"count={self.cfg.replace_count}",
            f"engine={sha256_file(self.cfg.engine_path) if self.cfg.engine_path.exists() else 'missing'}",
        )

    def run(self) -> dict[str, Any]:
        from fixtext.engine import GoEngineClient, EngineRequest, InputMode, OutputMode, RuleSet

        engine_path = self.cfg.engine_path
        if not engine_path.exists():
            raise StageError(f"Go 引擎不存在：{engine_path}")
        if not engine_path.is_file():
            raise StageError(f"Go 引擎不是普通文件：{engine_path}")
        import os

        if os.name != "nt" and not os.access(engine_path, os.X_OK):
            # T0.3 产物解包后不带执行位，这里补上（builder.chmod_executable 同款动作）
            engine_path.chmod(engine_path.stat().st_mode | 0o111)
            self.log.log(f"[replace] 已补执行位：{engine_path}")

        rules = RuleSet.from_files(self.cfg.rules_before, self.cfg.rules_after)
        self.log.log(
            f"[replace] 规则载入完成：{len(rules)} 条（去重前 {rules.unique_before}），"
            f"替换趟数 {self.cfg.replace_count}"
        )

        out_dir = self.ensure_dir(self.cfg.stage_dir(self.name))
        before_dir = self.ensure_dir(out_dir / "before")
        after_dir = self.ensure_dir(out_dir / "after")
        before_path = before_dir / f"{self.cfg.book_stem}.txt"
        after_path = after_dir / f"{self.cfg.book_stem}.txt"

        client = GoEngineClient(engine_path, default_timeout_s=self.cfg.engine_timeout_s)
        request = EngineRequest(
            rules=rules,
            count=self.cfg.replace_count,
            input_mode=InputMode.FILE,
            input_path=self.cfg.layout_text(),
            output_mode=OutputMode.FILE,
            output_path=after_path,
            encoding="utf-8",
            timeout_s=self.cfg.engine_timeout_s,
        )

        self.log.log(f"[replace] 调起 Go 引擎：{engine_path.name}")
        response = client.run(request)
        if not response.ok:
            assert response.error is not None
            detail = response.error.as_dict()
            self.log.log(f"[replace][FAIL] {detail['code']} {detail['message']}")
            raise StageError(
                f"Go 引擎替换失败：{detail['code']} {detail['message']}；"
                f"处置建议：{detail['remedy']}"
            )

        result = response.result
        assert result is not None
        shutil.copyfile(self.cfg.layout_text(), before_path)

        self.log.log(
            f"[replace] 引擎完成：{result.engine_stdout}；"
            f"字符 {result.chars_in} → {result.chars_out}，"
            f"耗时 {result.elapsed_s:.2f}s"
        )

        integrity = self._check_boundaries(after_path)
        if not integrity["ok"]:
            raise StageError(
                "替换后边界完整性复检失败："
                + "；".join(integrity["problems"][:5])
            )

        report = {
            "engine_path": str(engine_path),
            "engine_stdout": result.engine_stdout,
            "rules": result.rules,
            "unique_rules": result.unique_rules,
            "count": result.count,
            "chars_in": result.chars_in,
            "chars_out": result.chars_out,
            "bytes_in": result.bytes_in,
            "bytes_out": result.bytes_out,
            "sha256_in": result.sha256_in,
            "sha256_out": result.sha256_out,
            "changed": result.changed,
            "engine_elapsed_s": round(result.elapsed_s, 3),
            "before_path": str(before_path),
            "after_path": str(after_path),
            "before_sha256": sha256_file(before_path),
            "after_sha256": sha256_file(after_path),
            "boundary_check": integrity,
        }
        dump_json(out_dir / "replace_report.json", report)
        return report

    def _check_boundaries(self, text_path: Path) -> dict[str, Any]:
        """用账本严格切分替换后的 TXT，确认边界标记没被打坏。"""
        from epubtext.bundle import Ledger, split_bundle

        problems: list[str] = []
        chunks: list[Any] = []
        ledger = Ledger.load(self.cfg.stage_dir("layout") / f"{self.cfg.book_stem}.bundle.json")
        try:
            text = text_path.read_text(encoding="utf-8")
            chunks = split_bundle(text, ledger, strict=True)
        except Exception as exc:  # noqa: BLE001 - 任何切分失败都是边界被破坏
            problems.append(f"切分失败：{exc.__class__.__name__}: {exc}")

        if not problems and len(chunks) != len(ledger.chapters):
            problems.append(f"切出 {len(chunks)} 章，账本 {len(ledger.chapters)} 章")
        return {
            "ok": not problems,
            "chapters": len(chunks),
            "problems": problems,
        }
