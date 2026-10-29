"""阶段 4：引号检查（T1.4 ``fixtext_quotation``）+ 可选自动修复（M4-EX.6-R3）。

对替换后的整书文本做一次引号配对检查，产出与上游 ``check-quotation-marks``
同款的两份报告：人类可读报告（TXT）与机器可读报告（JSON）。

最小侵入：六阶段结构不动。``PipelineConfig.auto_fix_quotes`` 开启时，
在本阶段内先按检查页同一份规则跑 R1 ``fix_text``，写回 ``replace_after``，
再复查；关闭时行为与 T1.4 完全一致。
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
        flag = "1" if getattr(self.cfg, "auto_fix_quotes", False) else "0"
        rules = getattr(self.cfg, "quotation_rules_path", None)
        rules_fp = sha256_file(rules) if rules and Path(rules).is_file() else "none"
        return self.fingerprint_of(
            f"text={sha256_file(self.cfg.replace_after())}|autofix={flag}|rules={rules_fp}"
        )

    def run(self) -> dict[str, Any]:
        from fixtext_quotation import QuotationChecker
        from fixtext_quotation.report import render_json, render_report

        target = self.cfg.replace_after()
        text = target.read_text(encoding="utf-8")
        self.log.log(f"[quote] 检查文件：{target.name}（{len(text)} 字符）")

        checker = QuotationChecker()
        auto = bool(getattr(self.cfg, "auto_fix_quotes", False))
        fixed_count = 0
        actions_n = 0
        errors_before = 0

        if auto:
            from fixtext_quotation.fixer import fix_text
            from fixtext_quotation.rules import load_fix_rules

            rules_path = getattr(self.cfg, "quotation_rules_path", None)
            rules = load_fix_rules(rules_path)
            before_errs = checker.check_text(text)
            errors_before = len(before_errs)
            self.log.log(
                f"[quote] 自动修复开启：修复前 {errors_before} 处，"
                f"启用规则 {len(rules.enabled_ids())} 条"
            )
            result = fix_text(text, rules, max_rounds=16)
            actions_n = len(result.actions)
            if result.text != text:
                target.write_text(result.text, encoding="utf-8", newline="\n")
                text = result.text
                self.log.log(
                    f"[quote] 已写回修复后正文（动作 {actions_n} 步，"
                    f"{result.rounds} 轮）"
                )
            else:
                self.log.log("[quote] 自动修复未改动正文")
            errors = result.remaining_errors
            # 「修了几处」按检出差：与原型 N−M 口径一致
            fixed_count = max(0, errors_before - len(errors))
        else:
            errors = checker.check_file(target)
            errors_before = len(errors)

        out_dir = self.ensure_dir(self.cfg.stage_dir(self.name))
        report_txt = self.cfg.quote_report_txt()
        report_json = self.cfg.quote_report_json()
        report_txt.write_text(render_report(str(target), text, errors), encoding="utf-8")
        report_json.write_text(render_json(str(target), errors), encoding="utf-8")

        report = {
            "checked_file": str(target),
            "chars": len(text),
            "error_count": len(errors),
            "error_count_before": errors_before,
            "auto_fix_quotes": auto,
            "quote_fixed": fixed_count,
            "fix_actions": actions_n,
            "report_txt": str(report_txt),
            "report_json": str(report_json),
            "first_errors": [e.to_dict() for e in errors[:20]],
        }
        dump_json(out_dir / "quote_summary.json", report)

        if auto:
            self.log.log(
                f"[quote] 完成：修复前 {errors_before} → 剩余 {len(errors)} "
                f"（已自动修复 {fixed_count} 处）→ {report_txt.name}"
            )
        else:
            self.log.log(
                f"[quote] 完成：检出引号错误 {len(errors)} 处 → {report_txt.name}"
            )
        for err in errors[:10]:
            self.log.log(f"[quote] 第 {err.line} 行：{err.msg}")
        return report
