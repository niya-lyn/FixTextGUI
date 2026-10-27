"""阶段 4：引号检查（T1.4 ``fixtext_quotation``）。

对替换后的整书文本做一次引号配对检查，产出与上游 ``check-quotation-marks``
同款的两份报告：人类可读报告（TXT）与机器可读报告（JSON）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import dump_json
from ..state import sha256_file
from .base import Stage


class QuoteStage(Stage):
    name = "quote"
    title = "引号检查（T1.4）"
    depends_on = ("replace",)

    def outputs(self) -> list[Path]:
        return [self.cfg.quote_report_txt(), self.cfg.quote_report_json()]

    def fingerprint(self) -> str:
        return self.fingerprint_of(f"text={sha256_file(self.cfg.replace_after())}")

    def run(self) -> dict[str, Any]:
        from fixtext_quotation import QuotationChecker
        from fixtext_quotation.report import render_json, render_report

        target = self.cfg.replace_after()
        text = target.read_text(encoding="utf-8")
        self.log.log(f"[quote] 检查文件：{target.name}（{len(text)} 字符）")

        checker = QuotationChecker()
        errors = checker.check_file(target)

        out_dir = self.ensure_dir(self.cfg.stage_dir(self.name))
        report_txt = self.cfg.quote_report_txt()
        report_json = self.cfg.quote_report_json()
        report_txt.write_text(render_report(str(target), text, errors), encoding="utf-8")
        report_json.write_text(render_json(str(target), errors), encoding="utf-8")

        report = {
            "checked_file": str(target),
            "chars": len(text),
            "error_count": len(errors),
            "report_txt": str(report_txt),
            "report_json": str(report_json),
            "first_errors": [e.to_dict() for e in errors[:20]],
        }
        dump_json(out_dir / "quote_summary.json", report)

        self.log.log(f"[quote] 完成：检出引号错误 {len(errors)} 处 → {report_txt.name}")
        for err in errors[:10]:
            self.log.log(f"[quote] 第 {err.line} 行：{err.msg}")
        return report
