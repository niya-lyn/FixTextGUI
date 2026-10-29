"""阶段 6：EPUB 还原与校验（T1.3 ``epubtext.restore_epub`` / ``check_epub``）。

还原用原 EPUB 当模板重打包：图片、样式、OPF、NCX 全部原样保留，只替换
spine 指向的那几个 XHTML 条目，所以章节顺序天然不会乱。

校验做三件事，任一不通过即判失败：

1. ``check_epub`` —— 包能不能打开、结构完不完整（mimetype 首位、spine 文件齐全、
   manifest 文件齐全、每章 XHTML 可解析）；
2. ``compare_content`` —— 逐章比对正文文本，确认没有章节变空/丢失；
3. spine 指纹比对 —— 原包与还原包的 spine 路径序列 sha256 必须完全一致，
   这是「章节顺序不乱」最直接的证据。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import dump_json
from ..state import sha256_file
from .base import Stage, StageError


class RestoreStage(Stage):
    name = "restore"
    title = "EPUB 还原与校验（T1.3）"
    depends_on = ("replace", "quote", "bookmap")

    def outputs(self) -> list[Path]:
        return [self.cfg.restored_epub(), self.cfg.restore_report()]

    def fingerprint(self) -> str:
        return self.fingerprint_of(
            f"text={sha256_file(self.cfg.replace_after())}",
            f"template={sha256_file(self.cfg.epub)}",
        )

    def run(self) -> dict[str, Any]:
        from epubtext import check_epub, compare_content, restore_epub

        text_path = self.cfg.replace_after()
        # 跳过排版时账本仍是 merge 产物；有排版则用 layout 副本
        if self.cfg.skip_layout:
            ledger_path = self.cfg.merged_ledger()
        else:
            ledger_path = self.cfg.stage_dir("layout") / f"{self.cfg.book_stem}.bundle.json"
        out_dir = self.ensure_dir(self.cfg.stage_dir(self.name))
        output = self.cfg.restored_epub()

        self.log.log(f"[restore] 还原：{text_path.name} + 模板 {self.cfg.epub.name}")
        result = restore_epub(
            text_path,
            ledger_path,
            template_epub=self.cfg.epub,
            output_path=output,
        )
        self.log.log(
            f"[restore] 写回 {result.chapters_written} 章，"
            f"内容有变化 {result.chapters_changed} 章 → {output.name}"
        )

        self.log.log("[restore] 校验还原包结构…")
        check = check_epub(output, deep=True)
        check_dict = check.to_dict()

        self.log.log("[restore] 与原包逐章比对正文…")
        content = compare_content(self.cfg.epub, output)

        original_check = check_epub(self.cfg.epub, deep=True)
        spine_before = original_check.stats.get("spine_sha256")
        spine_after = check_dict["stats"].get("spine_sha256")

        problems: list[str] = []
        if not check_dict["ok"]:
            problems.extend(f"结构校验失败：{e}" for e in check_dict["errors"][:10])
        if not content.get("spine_order_equal"):
            problems.append("spine 顺序与原包不一致")
        if content.get("missing_files"):
            problems.append(f"缺失文件 {content['missing_files'][:5]}")
        if content.get("missing_text_chapters"):
            problems.append(f"正文变空的章节 {content['missing_text_chapters'][:5]}")
        if spine_before != spine_after:
            problems.append(f"spine 指纹不一致：{spine_before} != {spine_after}")

        report = {
            "restored_epub": str(output),
            "restored_bytes": output.stat().st_size,
            "restored_sha256": sha256_file(output),
            "restore": result.report,
            "check": check_dict,
            "content_compare": content,
            "spine_sha256_before": spine_before,
            "spine_sha256_after": spine_after,
            "problems": problems,
            "ok": not problems,
        }
        dump_json(self.cfg.restore_report(), report)

        if problems:
            for p in problems:
                self.log.log(f"[restore][FAIL] {p}")
            raise StageError("还原包校验未通过：" + "；".join(problems[:5]))

        self.log.log(
            f"[restore] 校验通过：spine 顺序一致（{spine_after[:16]}…），"
            f"逐章正文比对 {content.get('compared_chapters')} 章，"
            f"无缺失、无空章"
        )
        return report
