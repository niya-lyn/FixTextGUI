"""阶段 1：EPUB 合并（T1.3 ``epubtext.merge_epub``）。

把一本 EPUB 按 spine 顺序合并成一份可校对的 TXT，并落盘账本
（``<书名>.bundle.json``）。账本是后续还原的唯一依据，必须与 TXT 同目录。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import dump_json
from ..state import sha256_file
from .base import Stage


class MergeStage(Stage):
    name = "merge"
    title = "EPUB 合并（T1.3）"
    depends_on = ()

    def outputs(self) -> list[Path]:
        return [self.cfg.merged_text(), self.cfg.merged_ledger()]

    def fingerprint(self) -> str:
        return self.fingerprint_of(
            f"epub={sha256_file(self.cfg.epub)}",
            "format=epubtext-bundle/1",
        )

    def run(self) -> dict[str, Any]:
        from epubtext import merge_epub

        out_dir = self.ensure_dir(self.cfg.stage_dir(self.name))
        target = out_dir / f"{self.cfg.book_stem}.txt"

        self.log.log(f"[merge] 输入 EPUB: {self.cfg.epub}")
        result = merge_epub(self.cfg.epub, target)
        report = dict(result.report)
        report["text_path"] = str(result.text_path)
        report["ledger_path"] = str(result.ledger_path)
        report["text_sha256"] = sha256_file(result.text_path)
        report["text_bytes"] = result.text_path.stat().st_size

        self.log.log(
            f"[merge] 合并完成：{report.get('chapters')} 章，"
            f"spine {report.get('spine_items')} 项，"
            f"正文 {report.get('text_bytes')} 字节"
        )
        if report.get("warnings"):
            for w in report["warnings"][:20]:
                self.log.log(f"[merge][warn] {w}")

        dump_json(out_dir / "merge_report.json", report)
        return report
