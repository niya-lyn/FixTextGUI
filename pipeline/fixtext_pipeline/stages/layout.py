"""阶段 2：排版（T1.2 ``fixtext_layout``）。

排版在 **逐章** 粒度上执行，原因有二：

1. 合并后的 TXT 里夹着 ``EPUBTEXT-*`` 边界标记行，对整份文件做「每行加全角缩进」
   这类排版会把标记行顶坏，账本切分随之失效；
2. 逐章执行才能对每一章单独做 **XML 结构守卫**：排版后若该章不再是合法 XML、
   或标签/属性结构被改坏，该章自动回退到排版前内容，并记进阶段报告。

排版档案默认是 ``html-safe``：只开「标点规范」这类不碰标签结构的开关；
``change_text_format`` 保持关闭（上游默认也是关闭的），因为它会给每一行加
全角缩进，把 ``<?xml version='1.0' ...?>`` 顶出文件头，章节就不再是合法 XML。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import dump_json
from ..state import sha256_file
from .base import Stage, StageCancelled, StageError


def _xml_signature(text: str) -> tuple[tuple[str, tuple[str, ...]], ...] | None:
    """章节的标签/属性结构签名；解析失败返回 ``None``。

    签名只记录「有哪些标签、每个标签带哪些属性名」，不记录属性值与文本内容——
    排版本来就允许改文本，签名是用来发现「标签结构被改坏」的。
    """
    from lxml import etree

    try:
        root = etree.fromstring(
            text.encode("utf-8"),
            parser=etree.XMLParser(recover=False, resolve_entities=False, no_network=True, huge_tree=True),
        )
    except (etree.XMLSyntaxError, ValueError):
        return None

    sig: list[tuple[str, tuple[str, ...]]] = []
    for element in root.iter():
        tag = element.tag if isinstance(element.tag, str) else "#node"
        sig.append((tag, tuple(sorted(element.attrib.keys()))))
    return tuple(sig)


class LayoutStage(Stage):
    name = "layout"
    title = "排版（T1.2）"
    depends_on = ("merge",)

    def outputs(self) -> list[Path]:
        return [
            self.cfg.layout_text(),
            self.cfg.stage_dir(self.name) / f"{self.cfg.book_stem}.bundle.json",
            self.cfg.stage_dir(self.name) / "layout_report.json",
        ]

    def fingerprint(self) -> str:
        import json

        return self.fingerprint_of(
            f"merged={sha256_file(self.cfg.merged_text())}",
            f"options={json.dumps(self.cfg.layout_options, ensure_ascii=False, sort_keys=True)}",
        )

    def run(self) -> dict[str, Any]:
        from epubtext.bundle import (
            Ledger,
            build_book_marker,
            build_header,
            build_split_marker,
            canonical_body,
            split_bundle,
        )
        from fixtext_layout import LayoutEngine, LayoutOptions

        text = self.cfg.merged_text().read_text(encoding="utf-8")
        ledger = Ledger.load(self.cfg.merged_ledger())
        chunks = split_bundle(text, ledger, strict=True)
        if len(chunks) != len(ledger.chapters):
            raise StageError(f"切出 {len(chunks)} 章，账本 {len(ledger.chapters)} 章，对不上")

        options = LayoutOptions(**self.cfg.layout_options)
        engine = LayoutEngine(options)
        self.log.log(f"[layout] 排版选项：{options.to_dict()}")

        bodies: list[str] = []
        stats = {
            "chapters": len(chunks),
            "changed": 0,
            "unchanged": 0,
            "reverted": 0,
            "revert_reasons": {},
            "no_xml_guard": 0,
        }
        reverted_samples: list[dict[str, str]] = []

        for chunk, record in zip(chunks, ledger.chapters):
            # 章节边界协作取消（M4收尾 P1-7）：每章开始前查一次，避免大书
            # 排版整段跑完才响应「取消」。命令行未注入 cancel_check 时跳过。
            check = self.cfg.cancel_check
            if check is not None and check():
                raise StageCancelled("已取消：排版在当前章节边界停下")
            original = canonical_body(chunk.body)
            lead = original[: len(original) - len(original.lstrip())]
            try:
                formatted = engine.format(original)
            except Exception as exc:  # noqa: BLE001 - 单章排版失败不应毁掉整本书
                stats["reverted"] += 1
                reason = f"排版异常:{exc.__class__.__name__}"
                stats["revert_reasons"][reason] = stats["revert_reasons"].get(reason, 0) + 1
                if len(reverted_samples) < 20:
                    reverted_samples.append({"path": record.path, "reason": reason})
                bodies.append(original)
                continue

            candidate = lead + formatted.rstrip("\r\n")
            if candidate == original:
                stats["unchanged"] += 1
                bodies.append(original)
                continue

            reason = self._guard(original, candidate)
            if reason:
                stats["reverted"] += 1
                stats["revert_reasons"][reason] = stats["revert_reasons"].get(reason, 0) + 1
                if len(reverted_samples) < 20:
                    reverted_samples.append({"path": record.path, "reason": reason})
                bodies.append(original)
                continue

            stats["changed"] += 1
            bodies.append(candidate)

        text_out = self._reassemble(ledger, bodies)
        out_dir = self.ensure_dir(self.cfg.stage_dir(self.name))
        target = out_dir / f"{self.cfg.book_stem}.txt"
        target.write_text(text_out, encoding="utf-8", newline="\n")
        # 账本随 TXT 一起放一份，替换/还原阶段直接取本目录的这份
        ledger_out = out_dir / f"{self.cfg.book_stem}.bundle.json"
        ledger_out.write_text(ledger.to_json(), encoding="utf-8")

        report = {
            "options": options.to_dict(),
            "profile": self.cfg.layout_profile,
            **stats,
            "reverted_samples": reverted_samples,
            "text_path": str(target),
            "text_sha256": sha256_file(target),
            "text_bytes": target.stat().st_size,
        }
        dump_json(out_dir / "layout_report.json", report)

        self.log.log(
            f"[layout] 完成：{stats['chapters']} 章，"
            f"改动 {stats['changed']} 章，未变 {stats['unchanged']} 章，"
            f"回退 {stats['reverted']} 章"
        )
        for reason, count in stats["revert_reasons"].items():
            self.log.log(f"[layout][revert] {reason} × {count}")
        return report

    # ---- 内部工具 ----

    @staticmethod
    def _guard(original: str, candidate: str) -> str:
        """返回空串表示放行；否则返回回退原因。"""
        sig_before = _xml_signature(original)
        if sig_before is None:
            # 原章就不是合法 XML（源书本身如此），没有可比结构，只做长度体检
            if len(candidate) == 0:
                return "排版后内容为空"
            return ""

        sig_after = _xml_signature(candidate)
        if sig_after is None:
            return "排版后不再是合法 XML"
        if sig_after != sig_before:
            return "排版改动了标签/属性结构"
        return ""

    @staticmethod
    def _reassemble(ledger, bodies: list[str]) -> str:
        """按合并时的格式把章节正文拼回带标记的 TXT。

        结构与 ``epubtext.merge.merge_epub`` 完全一致：头部 + 书标记 +
        （章标记 + 正文 + 空行）×N，因此切分与还原都能原样工作。
        """
        from epubtext.bundle import build_book_marker, build_header, build_split_marker

        lines: list[str] = [build_header(ledger.nonce, len(ledger.books), len(ledger.chapters))]
        cursor = 0
        for book_index, book in enumerate(ledger.books):
            lines.append(
                build_book_marker(
                    ledger.nonce, book_index, book.title or "", book.source, len(book.chapters)
                )
            )
            for chapter in book.chapters:
                body = bodies[cursor].replace("\r\n", "\n").rstrip("\r\n")
                cursor += 1
                lines.append(
                    build_split_marker(
                        ledger.nonce,
                        chapter.index,
                        chapter.path,
                        chapter.label,
                        chapter.size,
                        chapter.sha256,
                    )
                )
                lines.append(body)
                lines.append("")
        text = "\n".join(lines)
        if not text.endswith("\n"):
            text += "\n"
        return text
