"""EPUB 校验：结构可打开性、条目完整性、spine 顺序、正文内容一致性。

这里刻意不复用合并端的逻辑，而是重新解析一遍包、独立取数，
这样"通过"才是有意义的结论，而不是用自己的输出验证自己的假设。
"""

from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .archive import CONTAINER_NAME, MIMETYPE, MIMETYPE_NAME, EpubArchive, resolve_href
from .errors import EpubStructureError
from .package import NS, parse_package

XHTML_TYPES = {"application/xhtml+xml", "text/html"}


@dataclass
class CheckReport:
    path: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": self.stats,
        }


def _text_content(xhtml: bytes) -> str:
    """提取 XHTML 的可见正文文本（``<body>`` 内、不含标签），用于内容完整性比对。

    只取 ``<body>`` 是刻意的：``<head><title>`` 里的章节标题同样属于文字，
    但正文被清空时标题往往还在，若把 title 算进来就会把"正文丢失"误判成
    "文本不同"，正好漏掉本函数要抓的那类损坏。
    """
    body: str | None = None
    try:
        parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)
        root = etree.fromstring(xhtml, parser=parser)
    except etree.XMLSyntaxError:
        root = None

    if root is not None:
        nodes = root.findall(".//{*}body")
        if nodes:
            body = "".join(nodes[0].itertext())
        else:
            body = "".join(root.itertext())

    if body is None:
        # 兜底：粗粒度剥标签，并尽力裁掉 head 段
        import re

        text = xhtml.decode("utf-8", errors="replace")
        match = re.search(r"(?is)<body[^>]*>(.*?)(?:</body>|$)", text)
        if match:
            return re.sub(r"<[^>]+>", "", match.group(1))
        text = re.sub(r"(?is)<head[^>]*>.*?</head>", "", text)
        return re.sub(r"<[^>]+>", "", text)
    return body


def _normalize_ws(text: str) -> str:
    return " ".join(text.split())


def check_epub(path: str | Path, deep: bool = True) -> CheckReport:
    """校验一个 EPUB：能否打开、结构是否完整、spine 是否可用。"""
    path = Path(path)
    report = CheckReport(path=path.name)

    if not path.exists():
        report.fail(f"文件不存在：{path}")
        return report
    if path.stat().st_size == 0:
        report.fail("文件为空")
        return report

    try:
        archive = EpubArchive(path)
    except EpubStructureError as exc:
        report.fail(str(exc))
        return report

    with archive:
        # 1) ZIP 完整性（CRC）
        broken = archive.test_zip_integrity()
        if broken:
            report.fail(f"ZIP 条目 CRC 校验失败：{broken[:5]}")

        # 2) mimetype 必须存在、内容正确，且是第一个条目（不压缩）
        with zipfile.ZipFile(path) as raw_zip:
            infos = raw_zip.infolist()
        first = infos[0] if infos else None
        if first is None:
            report.fail("包内没有任何条目")
        else:
            if first.filename.strip("./") != MIMETYPE_NAME:
                report.fail(f"第一个条目应为 mimetype，实际为 {first.filename}")
            if first.compress_type != zipfile.ZIP_STORED:
                report.fail("mimetype 条目被压缩了（规范要求 STORED）")
        if not archive.has(MIMETYPE_NAME):
            report.fail("缺少 mimetype 条目")
        else:
            mimetype = archive.read_bytes(MIMETYPE_NAME).decode("utf-8", errors="replace").strip()
            if mimetype != MIMETYPE:
                report.fail(f"mimetype 内容不正确：{mimetype!r}")

        # 3) container + OPF + spine
        if not archive.has(CONTAINER_NAME):
            report.fail(f"缺少 {CONTAINER_NAME}")
            return report
        try:
            info = parse_package(archive)
        except EpubStructureError as exc:
            report.fail(f"OPF 解析失败：{exc}")
            return report

        report.stats["title"] = info.title
        report.stats["spine_items"] = len(info.spine)
        report.stats["content_items"] = len(info.content_items)
        report.stats["manifest_items"] = len(info.manifest)
        report.stats["ncx"] = bool(info.toc)
        report.stats["spine_sha256"] = hashlib.sha256(
            "\n".join(item.path for item in info.spine).encode("utf-8")
        ).hexdigest()

        missing = [item.path for item in info.spine if not archive.has(item.path)]
        if missing:
            report.fail(f"spine 引用的文件有 {len(missing)} 个不在包内：{missing[:5]}")

        # 4) manifest 里所有文件都应存在（图片/样式缺失会导致阅读器报错）
        absent_manifest: list[str] = []
        for item in info.manifest.values():
            try:
                target = resolve_href(info.opf_dir, item.href)
            except EpubStructureError:
                continue
            if item.href.startswith(("http://", "https://", "mailto:", "data:")):
                continue
            if not archive.has(target):
                absent_manifest.append(target)
        if absent_manifest:
            report.fail(f"manifest 声明了 {len(absent_manifest)} 个包内不存在的文件：{absent_manifest[:5]}")

        report.stats["duplicate_spine_paths"] = len(info.spine_duplicates)
        if info.spine_duplicates:
            report.warn(f"spine 中存在重复路径：{info.spine_duplicates[:5]}")

        # 5) 每章 XHTML 能解析、非空
        if deep:
            empty_chapters: list[str] = []
            unparsable: list[str] = []
            for item in info.content_items:
                if not archive.has(item.path):
                    continue
                data = archive.read_bytes(item.path)
                parser = etree.XMLParser(recover=False, resolve_entities=False, no_network=True, huge_tree=True)
                try:
                    etree.fromstring(data, parser=parser)
                except etree.XMLSyntaxError as exc:
                    unparsable.append(f"{item.path}: {exc}")
                    continue
                if not _normalize_ws(_text_content(data)):
                    empty_chapters.append(item.path)
            if unparsable:
                report.warn(f"{len(unparsable)} 章 XHTML 不是严格合法的 XML：{unparsable[:3]}")
            if empty_chapters:
                report.warn(f"{len(empty_chapters)} 章正文为空：{empty_chapters[:5]}")

        report.stats["warnings_from_parse"] = info.warnings

    return report


def compare_content(
    original: str | Path,
    rebuilt: str | Path,
) -> dict:
    """逐章比对一个还原包与原始包的正文文本，返回内容比对结果。

    判据：
    * ``text_equal_chapters``：去掉标签与空白差异后，文本完全一致的章数；
    * ``missing_text_chapters``：还原后正文明显变空/缺失的章节；
    * ``text_diff_chapters``：文本有差异的章节（正常改动会落在这里）。
    """
    with EpubArchive(original) as src, EpubArchive(rebuilt) as dst:
        src_info = parse_package(src)
        dst_info = parse_package(dst)

        src_order = [item.path for item in src_info.spine]
        dst_order = [item.path for item in dst_info.spine]

        result: dict = {
            "spine_order_equal": src_order == dst_order,
            "src_spine_count": len(src_order),
            "dst_spine_count": len(dst_order),
            "order_diff": _order_diff(src_order, dst_order),
            "text_equal_chapters": 0,
            "text_diff_chapters": [],
            "missing_text_chapters": [],
            "missing_files": [],
            "compared_chapters": 0,
            "total_src_text_chars": 0,
            "total_dst_text_chars": 0,
        }

        for item in src_info.content_items:
            if not dst.has(item.path):
                result["missing_files"].append(item.path)
                continue
            src_text = _normalize_ws(_text_content(src.read_bytes(item.path)))
            dst_text = _normalize_ws(_text_content(dst.read_bytes(item.path)))
            result["compared_chapters"] += 1
            result["total_src_text_chars"] += len(src_text)
            result["total_dst_text_chars"] += len(dst_text)

            if src_text == dst_text:
                result["text_equal_chapters"] += 1
            elif not dst_text:
                result["missing_text_chapters"].append(item.path)
            else:
                ratio = (len(dst_text) / len(src_text)) if src_text else 1.0
                result["text_diff_chapters"].append(
                    {"path": item.path, "src_chars": len(src_text), "dst_chars": len(dst_text), "ratio": round(ratio, 4)}
                )

        result["content_ok"] = (
            result["spine_order_equal"]
            and not result["missing_files"]
            and not result["missing_text_chapters"]
        )
    return result


def _order_diff(src: list[str], dst: list[str]) -> list[dict]:
    diffs: list[dict] = []
    for index, (a, b) in enumerate(zip(src, dst)):
        if a != b:
            diffs.append({"index": index, "original": a, "rebuilt": b})
        if len(diffs) >= 10:
            break
    if len(src) != len(dst):
        diffs.append({"index": None, "original": f"count={len(src)}", "rebuilt": f"count={len(dst)}"})
    return diffs


def compare_bytes(original: str | Path, rebuilt: str | Path) -> dict:
    """逐条目做字节比对，用于验证"未改动的书应逐字节还原"。"""
    with EpubArchive(original) as src, EpubArchive(rebuilt) as dst:
        src_names = set(src.names)
        dst_names = set(dst.names)
        common = sorted(src_names & dst_names)
        differing = [name for name in common if src.read_bytes(name) != dst.read_bytes(name)]
        return {
            "src_entries": len(src_names),
            "dst_entries": len(dst_names),
            "only_in_src": sorted(src_names - dst_names)[:20],
            "only_in_dst": sorted(dst_names - src_names)[:20],
            "identical_entries": len(common) - len(differing),
            "differing_entries": differing[:20],
            "differing_count": len(differing),
            "byte_identical": not differing and src_names == dst_names,
        }
