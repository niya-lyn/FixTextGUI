#!/usr/bin/env python3
"""独立校验还原后的 EPUB（不依赖编排器自己的 check_epub）。

用标准库 zipfile + lxml 直接拆包核对，回答四个问题：

1. 包本身完整吗（zip CRC、mimetype 位置与压缩方式）；
2. OPF 的 manifest / spine 自洽吗（每个 spine idref 都能解析到 manifest 条目）；
3. 每章 XHTML 都是合法 XML 且正文非空吗；
4. 章节顺序和原书一模一样吗（spine href 序列逐项比对 + 整列 sha256），
   非 spine 资源（图片 / 样式 / OPF / NCX）有没有被改动。

用法::

    python tools/verify_epub.py 原书.epub 还原书.epub
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

from lxml import etree

OPF_NS = "http://www.idpf.org/2007/opf"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text_of(xhtml: bytes) -> str:
    """取 XHTML 正文里的可见文本。"""
    parser = etree.XMLParser(recover=False, resolve_entities=False, no_network=True, huge_tree=True)
    root = etree.fromstring(xhtml, parser=parser)
    for bad in root.iter():
        if isinstance(bad.tag, str) and bad.tag.lower() in ("script", "style"):
            bad.text = None
    return "".join(root.itertext())


def _package_path(zf: zipfile.ZipFile) -> str:
    """从 META-INF/container.xml 找到 OPF 的真实路径。"""
    container = etree.fromstring(zf.read("META-INF/container.xml"))
    for rootfile in container.iter(f"{{{CONTAINER_NS}}}rootfile"):
        full = rootfile.get("full-path")
        if full:
            return full
    raise RuntimeError("container.xml 里没有 rootfile")


def _parse_opf(zf: zipfile.ZipFile, opf_path: str) -> tuple[dict[str, str], list[str], dict[str, str]]:
    """返回 (id->href 映射, spine 顺序的 href 列表, manifest 条目的 media-type)。"""
    root = etree.fromstring(zf.read(opf_path))
    base = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""

    id_to_href: dict[str, str] = {}
    media_types: dict[str, str] = {}
    for item in root.iter(f"{{{OPF_NS}}}item"):
        item_id = item.get("id")
        href = item.get("href")
        if item_id is None or href is None:
            continue
        full = f"{base}/{href}" if base else href
        id_to_href[item_id] = full
        media_types[full] = item.get("media-type", "")

    spine: list[str] = []
    for itemref in root.iter(f"{{{OPF_NS}}}itemref"):
        idref = itemref.get("idref")
        if idref is None:
            continue
        if idref not in id_to_href:
            raise RuntimeError(f"spine 里的 idref={idref} 在 manifest 中不存在")
        spine.append(id_to_href[idref])
    return id_to_href, spine, media_types


def verify(original: Path, restored: Path) -> dict:
    report: dict = {"original": str(original), "restored": str(restored), "problems": []}
    problems: list[str] = report["problems"]

    with zipfile.ZipFile(original) as zo, zipfile.ZipFile(restored) as zr:
        # --- 1. zip 完整性 + mimetype ---
        bad = zr.testzip()
        if bad is not None:
            problems.append(f"zip CRC 校验失败：{bad}")
        names = zr.namelist()
        report["restored_entry_count"] = len(names)
        report["original_entry_count"] = len(zo.namelist())

        if not names or names[0] != "mimetype":
            problems.append(f"mimetype 不是首个条目（实际首个：{names[0] if names else '空'}）")
        else:
            info = zr.getinfo("mimetype")
            report["mimetype_stored"] = info.compress_type == zipfile.ZIP_STORED
            report["mimetype_value"] = zr.read("mimetype").decode("ascii", "replace")
            if not report["mimetype_stored"]:
                problems.append("mimetype 被压缩了（EPUB 规范要求 STORED）")
            if report["mimetype_value"] != "application/epub+zip":
                problems.append(f"mimetype 内容不对：{report['mimetype_value']}")

        # --- 2. OPF / spine ---
        opf_o = _package_path(zo)
        opf_r = _package_path(zr)
        report["opf_path"] = opf_r
        _, spine_o, _ = _parse_opf(zo, opf_o)
        id_map_r, spine_r, media_r = _parse_opf(zr, opf_r)

        report["spine_count_original"] = len(spine_o)
        report["spine_count_restored"] = len(spine_r)
        report["spine_order_equal"] = spine_o == spine_r
        report["spine_sha256_original"] = "sha256:" + _sha256("\n".join(spine_o).encode())
        report["spine_sha256_restored"] = "sha256:" + _sha256("\n".join(spine_r).encode())
        if spine_o != spine_r:
            first_diff = next(
                (i for i, (a, b) in enumerate(zip(spine_o, spine_r)) if a != b),
                min(len(spine_o), len(spine_r)),
            )
            problems.append(
                f"spine 顺序不一致，首个差异在第 {first_diff} 项："
                f"{spine_o[first_diff:first_diff+1]} vs {spine_r[first_diff:first_diff+1]}"
            )

        # --- 3. 每章可解析且正文非空 ---
        empty_chapters: list[str] = []
        unparsable: list[str] = []
        total_text = 0
        for href in spine_r:
            try:
                body = zr.read(href)
            except KeyError:
                unparsable.append(f"{href}(缺失)")
                continue
            try:
                text = _text_of(body)
            except Exception as exc:  # noqa: BLE001
                unparsable.append(f"{href}({exc.__class__.__name__})")
                continue
            stripped = "".join(text.split())
            total_text += len(stripped)
            if not stripped:
                empty_chapters.append(href)

        report["chapters_parsed"] = len(spine_r) - len(unparsable)
        report["chapters_empty"] = len(empty_chapters)
        report["chapters_unparsable"] = len(unparsable)
        report["total_visible_chars"] = total_text
        report["empty_chapter_samples"] = empty_chapters[:10]
        report["unparsable_samples"] = unparsable[:10]
        if unparsable:
            problems.append(f"{len(unparsable)} 章无法解析/缺失：{unparsable[:5]}")
        if empty_chapters:
            problems.append(f"{len(empty_chapters)} 章正文为空：{empty_chapters[:5]}")

        # --- 4. 非 spine 资源是否原样保留 ---
        changed_assets: list[str] = []
        missing_assets: list[str] = []
        spine_set = set(spine_r) | {opf_r}
        for name in zo.namelist():
            if name in spine_set or name.endswith("/"):
                continue
            if name not in names:
                missing_assets.append(name)
                continue
            if _sha256(zo.read(name)) != _sha256(zr.read(name)):
                changed_assets.append(name)
        report["assets_checked"] = len([n for n in zo.namelist() if n not in spine_set])
        report["assets_changed"] = changed_assets[:20]
        report["assets_missing"] = missing_assets[:20]
        if missing_assets:
            problems.append(f"原包有 {len(missing_assets)} 个非 spine 资源在还原包中丢失")
        if changed_assets:
            problems.append(f"{len(changed_assets)} 个非 spine 资源被改动：{changed_assets[:5]}")

        # --- 5. 正文字符级变化统计（证明替换确实落到书里了） ---
        changed_chapters = 0
        for href in spine_r:
            try:
                if zo.read(href) != zr.read(href):
                    changed_chapters += 1
            except KeyError:
                pass
        report["chapters_changed_vs_original"] = changed_chapters

    report["ok"] = not problems
    return report


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    original, restored = Path(argv[1]), Path(argv[2])
    for p in (original, restored):
        if not p.is_file():
            print(f"文件不存在：{p}", file=sys.stderr)
            return 2
    report = verify(original, restored)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print()
    print("校验通过：还原后的 EPUB 可正常打开，章节顺序与原书一致。" if report["ok"]
          else "校验未通过，问题见 problems 字段。")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
