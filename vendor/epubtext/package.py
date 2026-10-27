"""OPF/NCX 解析：定位根文件、解析 manifest 与 spine、提取目录标题。

设计要点（按两本真实样本的实测结构确定）：

* **阅读顺序的唯一权威是 spine**，不是文件名排序。样本里 ``chapter1/chapter10/chapter100``
  这类未补零的文件名一旦按名字排序就会全乱，只有 spine 能给出正确顺序。
* NCX 用来取章节标题与层级，同时作为「spine 缺失」时的兜底顺序来源；
  当 NCX 与 spine 不一致时（样本 B 的前置页就不在 NCX 里），以 spine 为准，并记录告警。
* EPUB3 的 ``nav.xhtml`` 在 spine 里通常带 ``linear="no"`` 或是导航文档，不参与正文合并。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from lxml import etree

from .archive import CONTAINER_NAME, EpubArchive, resolve_href
from .errors import EpubStructureError

NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
}

XHTML_MEDIA_TYPES = frozenset(
    {
        "application/xhtml+xml",
        "text/html",
        "application/x-dtbook+xml",
    }
)

# 这些条目不是「正文」：导航文档、封面、以及常见的版权/扉页噪音由调用方按需排除。
NAV_PROPERTIES = "nav"


@dataclass(frozen=True)
class ManifestItem:
    id: str
    href: str
    media_type: str
    properties: str = ""

    @property
    def is_nav(self) -> bool:
        return NAV_PROPERTIES in self.properties.split()

    @property
    def is_xhtml(self) -> bool:
        return self.media_type.lower() in XHTML_MEDIA_TYPES


@dataclass(frozen=True)
class SpineItem:
    """spine 里的一项，已解析到包内路径。"""

    idref: str
    path: str
    linear: bool
    media_type: str
    properties: str = ""

    @property
    def is_nav(self) -> bool:
        return NAV_PROPERTIES in self.properties.split()


@dataclass
class TocNode:
    label: str
    src_path: str | None
    children: list["TocNode"] = field(default_factory=list)
    depth: int = 0

    def walk(self) -> Iterable["TocNode"]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class PackageInfo:
    """一本书的解析结果：路径、元数据、spine 顺序与目录。"""

    opf_path: str
    opf_dir: str
    manifest: dict[str, ManifestItem]
    spine: list[SpineItem]
    title: str = ""
    identifier: str = ""
    creator: str = ""
    ncx_path: str | None = None
    toc: list[TocNode] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    spine_duplicates: list[str] = field(default_factory=list)

    @property
    def content_items(self) -> list[SpineItem]:
        """参与正文合并的 spine 项：XHTML 且非导航文档，保持 spine 顺序。"""
        return [item for item in self.spine if item.media_type.lower() in XHTML_MEDIA_TYPES and not item.is_nav]

    def label_for(self, path: str) -> str:
        """按 spine 项路径找 NCX 标题（同路径取第一个）。"""
        for node in self._flatten_toc():
            if node.src_path == path and node.label:
                return node.label
        return ""

    def _flatten_toc(self) -> Iterable[TocNode]:
        for node in self.toc:
            yield from node.walk()


def _parse_xml(data: bytes, what: str) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True, recover=False)
    try:
        return etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise EpubStructureError(f"{what} 解析失败：{exc}") from exc


def _find_rootfile(container_root: etree._Element) -> str:
    rootfiles = container_root.findall(".//container:rootfiles/container:rootfile", NS)
    if not rootfiles:
        # 少数不规范包没有命名空间，做一次无命名空间的兜底
        rootfiles = container_root.findall(".//rootfiles/rootfile")
    if not rootfiles:
        raise EpubStructureError("container.xml 中没有 rootfile 节点")
    if len(rootfiles) > 1:
        chosen = next(
            (rf for rf in rootfiles if rf.get("media-type") == "application/oebps-package+xml"),
            rootfiles[0],
        )
    else:
        chosen = rootfiles[0]
    full_path = chosen.get("full-path")
    if not full_path:
        raise EpubStructureError("container.xml 的 rootfile 缺少 full-path 属性")
    return full_path


def _text_of(element: etree._Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def parse_package(archive: EpubArchive, opf_path: str | None = None) -> PackageInfo:
    """解析一本书的 OPF，返回 spine 顺序与目录信息。"""
    if opf_path is None:
        container_root = _parse_xml(archive.container_xml().encode("utf-8"), "container.xml")
        opf_path = _find_rootfile(container_root)

    opf_path = opf_path.split("#", 1)[0]
    if not archive.has(opf_path):
        raise EpubStructureError(f"OPF 文件不存在：{opf_path}")
    opf_root = _parse_xml(archive.read_bytes(opf_path), f"OPF({opf_path})")
    opf_dir = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""

    manifest: dict[str, ManifestItem] = {}
    for item_el in opf_root.findall(".//opf:manifest/opf:item", NS) or opf_root.findall(".//manifest/item"):
        item_id = item_el.get("id")
        href = item_el.get("href")
        if not item_id or not href:
            continue
        manifest[item_id] = ManifestItem(
            id=item_id,
            href=href,
            media_type=item_el.get("media-type", ""),
            properties=item_el.get("properties", "") or "",
        )
    if not manifest:
        raise EpubStructureError(f"{opf_path} 的 manifest 为空或无法解析")

    spine_el = opf_root.find(".//opf:spine", NS) or opf_root.find(".//spine")
    if spine_el is None:
        raise EpubStructureError(f"{opf_path} 缺少 spine，无法确定阅读顺序")

    warnings: list[str] = []
    spine: list[SpineItem] = []
    seen_paths: dict[str, int] = {}
    duplicates: list[str] = []

    for index, ref in enumerate(spine_el.findall("opf:itemref", NS) or spine_el.findall("itemref")):
        idref = ref.get("idref")
        if not idref:
            warnings.append(f"spine 第 {index} 项缺少 idref，已跳过")
            continue
        item = manifest.get(idref)
        if item is None:
            warnings.append(f"spine 引用了 manifest 中不存在的 id：{idref}，已跳过")
            continue
        try:
            path = resolve_href(opf_dir, item.href)
        except EpubStructureError as exc:
            warnings.append(str(exc))
            continue
        # 记录包内真实条目名：href 可能是百分号编码，而 ZIP 条目名是解码形态
        path = archive.real_name(path) or path
        linear = (ref.get("linear") or "yes").lower() != "no"
        spine.append(
            SpineItem(
                idref=idref,
                path=path,
                linear=linear,
                media_type=item.media_type,
                properties=item.properties,
            )
        )
        if path in seen_paths:
            duplicates.append(path)
        seen_paths[path] = seen_paths.get(path, 0) + 1

    if not spine:
        raise EpubStructureError(f"{opf_path} 的 spine 没有任何可用 itemref")

    metadata = opf_root.find(".//opf:metadata", NS) or opf_root.find(".//metadata")
    title = ""
    identifier = ""
    creator = ""
    if metadata is not None:
        title = _text_of(metadata.find("dc:title", NS)) or _text_of(metadata.find("title"))
        identifier = _text_of(metadata.find("dc:identifier", NS)) or _text_of(metadata.find("identifier"))
        creator = _text_of(metadata.find("dc:creator", NS)) or _text_of(metadata.find("creator"))

    info = PackageInfo(
        opf_path=opf_path,
        opf_dir=opf_dir,
        manifest=manifest,
        spine=spine,
        title=title,
        identifier=identifier,
        creator=creator,
        warnings=warnings,
        spine_duplicates=duplicates,
    )

    ncx_path = _find_ncx_path(archive, opf_root, manifest, opf_dir, spine_el)
    info.ncx_path = ncx_path
    if ncx_path:
        try:
            info.toc = parse_ncx(archive, ncx_path)
        except EpubStructureError as exc:
            info.warnings.append(f"NCX 解析失败，章节标题将回退到 HTML title：{exc}")
            info.toc = []
    if not info.toc:
        info.warnings.append("未找到可解析的 NCX 目录，章节标签将回退到 HTML <title>")
    return info


def _find_ncx_path(
    archive: EpubArchive,
    opf_root: etree._Element,
    manifest: dict[str, ManifestItem],
    opf_dir: str,
    spine_el: etree._Element,
) -> str | None:
    toc_id = spine_el.get("toc")
    if toc_id and toc_id in manifest:
        return resolve_href(opf_dir, manifest[toc_id].href)
    for item in manifest.values():
        if item.media_type.lower() == "application/x-dtbncx+xml":
            return resolve_href(opf_dir, item.href)
        if item.href.lower().endswith(".ncx"):
            return resolve_href(opf_dir, item.href)
    # 最后兜底：包里任意位置的 .ncx
    for name in archive.names:
        if name.lower().endswith(".ncx"):
            return name
    return None


def parse_ncx(archive: EpubArchive, ncx_path: str) -> list[TocNode]:
    """解析 NCX，返回按 navPoint 嵌套的目录树。"""
    if not archive.has(ncx_path):
        raise EpubStructureError(f"NCX 文件不存在：{ncx_path}")
    root = _parse_xml(archive.read_bytes(ncx_path), f"NCX({ncx_path})")
    ncx_dir = ncx_path.rsplit("/", 1)[0] if "/" in ncx_path else ""

    nav_map = root.find(".//ncx:navMap", NS) or root.find(".//navMap")
    if nav_map is None:
        return []

    def build(parent: etree._Element, depth: int) -> list[TocNode]:
        nodes: list[TocNode] = []
        for nav_point in parent.findall("ncx:navPoint", NS) or parent.findall("navPoint"):
            label = ""
            for nav_label in nav_point.findall("ncx:navLabel", NS) or nav_point.findall("navLabel"):
                text_el = nav_label.find("ncx:text", NS) if nav_label.find("ncx:text", NS) is not None else nav_label.find("text")
                label = _text_of(text_el)
                if label:
                    break
            content_el = nav_point.find("ncx:content", NS) if nav_point.find("ncx:content", NS) is not None else nav_point.find("content")
            src_path = None
            if content_el is not None and content_el.get("src"):
                try:
                    src_path = resolve_href(ncx_dir, content_el.get("src", ""))
                except EpubStructureError:
                    src_path = None
            node = TocNode(label=label, src_path=src_path, depth=depth)
            node.children = build(nav_point, depth + 1)
            nodes.append(node)
        return nodes

    return build(nav_map, 0)


def reading_order(info: PackageInfo, include_nav: bool = False) -> list[str]:
    """返回正文合并用的文件顺序：spine 顺序，可按需保留/剔除导航文档。"""
    items = info.spine if include_nav else info.content_items
    return [item.path for item in items]


def verify_order_against_ncx(info: PackageInfo) -> tuple[bool, list[str]]:
    """校验 spine 顺序与 NCX 顺序一致（NCX 视为 spine 的子序列）。

    返回 (是否一致, 差异说明)。样本里前置页可以不在 NCX 中，
    因此以「NCX 序列是 spine 序列的子序列」为一致判据。
    """
    if not info.toc:
        return False, ["没有可用 NCX 目录，无法比对顺序"]
    ncx_order = [node.src_path for node in info._flatten_toc() if node.src_path]
    spine_paths = [item.path for item in info.spine]
    spine_set_index = {path: i for i, path in enumerate(spine_paths)}

    missing = [p for p in ncx_order if p not in spine_set_index]
    if missing:
        return False, [f"NCX 中有 {len(missing)} 项不在 spine 内：{missing[:5]}"]

    last = -1
    violations: list[str] = []
    for path in ncx_order:
        index = spine_set_index[path]
        if index < last:
            violations.append(f"NCX 顺序与 spine 顺序冲突：{path}（spine 第 {index} 项）出现在第 {last} 项之后")
        last = max(last, index)
    only_in_spine = [p for p in spine_paths if p not in set(ncx_order)]
    notes = [f"spine 中另有 {len(only_in_spine)} 项不在 NCX（属前置页/附页，正常）"] if only_in_spine else []
    return (not violations), violations + notes


CHAPTER_TITLE_PATTERNS = (
    re.compile(r"^\s*第\s*[0-9０-９一二三四五六七八九十百千万零〇两]+\s*[章节回卷篇集部话]"),
    re.compile(r"^\s*(?:Chapter|CHAPTER)\s+\d+"),
    re.compile(r"^\s*[0-9]{1,4}\s*[、.．]\s*\S"),
)


def looks_like_chapter_title(text: str) -> bool:
    """判断一段文本是否像章节标题（用于无 NCX 时的兜底识别）。"""
    if not text or len(text) > 60:
        return False
    return any(pattern.match(text) for pattern in CHAPTER_TITLE_PATTERNS)
