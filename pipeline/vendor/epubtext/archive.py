"""EPUB 归档层：ZIP 读写、条目名规范化、路径安全解析、合规打包。

这一层只认"容器"，不理解 OPF 语义；所有路径都按 POSIX 相对路径处理，
并拒绝逃出根目录的 href（``../``），避免解压式路径穿越。
"""

from __future__ import annotations

import hashlib
import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote

from .errors import EpubStructureError

MIMETYPE = "application/epub+zip"
MIMETYPE_NAME = "mimetype"
CONTAINER_NAME = "META-INF/container.xml"


def normalize_name(name: str) -> str:
    """把 ZIP 条目名规范成根相对 POSIX 路径（去掉 ``./``、多余分隔符、反斜杠）。

    以 ``/`` 结尾的条目是目录项，统一返回空串表达"不是文件"；调用方据此过滤。
    """
    name = name.replace("\\", "/")
    if name.endswith("/"):
        return ""
    while name.startswith("./"):
        name = name[2:]
    name = name.lstrip("/")
    normalized = posixpath.normpath(name) if name else ""
    return "" if normalized == "." else normalized


def resolve_href(opf_dir: str, href: str) -> str:
    """把 manifest 里的 href 解析成 ZIP 内根相对路径。

    href 可能是百分号编码的；包里条目的实际名字既可能是编码形态也可能是解码形态，
    :func:`candidate_names` 会把两种都返回，由调用方按包内实际存在的那一种取用。
    """
    raw = href.split("#", 1)[0].split("?", 1)[0]
    if raw.startswith("//"):
        raise EpubStructureError(f"manifest href 指向外部主机：{href!r}")
    if raw.startswith("/"):
        raw = raw.lstrip("/")
    joined = posixpath.normpath(posixpath.join(opf_dir, raw)) if opf_dir else posixpath.normpath(raw)
    if joined.startswith("../") or joined == "..":
        raise EpubStructureError(f"manifest href 逃出包根目录：{href!r}")
    return joined


def candidate_names(path: str) -> list[str]:
    """同一个逻辑路径在包里可能出现的几种写法（原样 / 解码 / 编码）。"""
    from urllib.parse import quote, unquote

    names = [path]
    decoded = unquote(path)
    if decoded != path:
        names.append(decoded)
    encoded = quote(path, safe="/._-~")
    if encoded != path:
        names.append(encoded)
    return names


@dataclass(frozen=True)
class Entry:
    """ZIP 内一个条目的轻量描述（不含内容，避免一次性载入大包）。"""

    name: str
    is_dir: bool
    size: int
    compress_type: int


@dataclass(frozen=True)
class FileEntry:
    """写出用的条目：名称 + 字节内容 + 是否压缩存储。"""

    name: str
    data: bytes
    compress: bool = True


class EpubArchive:
    """只读 EPUB 归档封装，提供按名读取与容器级结构访问。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise EpubStructureError(f"文件不存在：{self.path}")
        try:
            self._zip = zipfile.ZipFile(self.path, "r")
        except zipfile.BadZipFile as exc:
            raise EpubStructureError(f"不是合法的 ZIP/EPUB：{self.path}（{exc}）") from exc
        self._names = {normalize_name(name): name for name in self._zip.namelist() if not name.endswith("/")}
        # 百分号编码的条目名：同时登记解码后的别名，读取时优先用真实条目名
        self._alias: dict[str, str] = {}
        for normalized in list(self._names):
            for candidate in candidate_names(normalized):
                if candidate in self._names and candidate != normalized:
                    self._alias[normalized] = candidate

    def real_name(self, name: str) -> str | None:
        """返回包内实际条目名（处理百分号编码差异）；不存在返回 None。"""
        key = normalize_name(name)
        if key in self._names:
            return key
        alias = self._alias.get(key)
        return alias

    def __enter__(self) -> "EpubArchive":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._zip.close()

    @property
    def names(self) -> list[str]:
        """全部文件条目名（已规范化、不含目录项）。"""
        return sorted(self._names)

    def has(self, name: str) -> bool:
        return self.real_name(name) is not None

    def read_bytes(self, name: str) -> bytes:
        real = self.real_name(name)
        if real is None:
            raise EpubStructureError(f"EPUB 内缺少条目：{name}")
        return self._zip.read(self._names[real])

    def iter_entries(self) -> Iterator[Entry]:
        for info in self._zip.infolist():
            yield Entry(
                name=normalize_name(info.filename),
                is_dir=info.filename.endswith("/"),
                size=info.file_size,
                compress_type=info.compress_type,
            )

    def sha256(self) -> str:
        digest = hashlib.sha256()
        with self.path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def test_zip_integrity(self) -> list[str]:
        """校验 ZIP 中央目录与各条目 CRC，返回损坏条目名列表（空表示完好）。"""
        broken = self._zip.testzip()
        return [] if broken is None else [normalize_name(broken)]

    # ---- 容器级结构 ----

    def container_xml(self) -> str:
        if not self.has(CONTAINER_NAME):
            raise EpubStructureError(
                f"{self.path.name} 缺少 {CONTAINER_NAME}，无法定位 OPF；请先用 Calibre/Sigil 规范化结构"
            )
        return self.read_bytes(CONTAINER_NAME).decode("utf-8", errors="replace")


def write_epub(destination: str | Path, entries: list[FileEntry], compress_level: int = 6) -> Path:
    """按 EPUB 规范写包：``mimetype`` 必须是首个条目且不压缩、无 extra 字段。

    其余条目沿用调用方给定顺序（通常即模板原有的条目顺序），
    这样还原出来的包在结构上与模板保持一致，只是正文被替换。
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()

    if not any(entry.name == MIMETYPE_NAME for entry in entries):
        raise EpubStructureError("写包时必须提供 mimetype 条目")

    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=compress_level) as archive:
        for entry in entries:
            name = normalize_name(entry.name)
            if name in seen:
                raise EpubStructureError(f"写包时出现重复条目：{name}")
            seen.add(name)

            if name == MIMETYPE_NAME:
                info = zipfile.ZipInfo(MIMETYPE_NAME, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.external_attr = 0o644 << 16
                info.extra = b""
                archive.writestr(info, entry.data)
                continue

            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED if entry.compress else zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            archive.writestr(info, entry.data)

    return destination


def collect_entries(archive: EpubArchive) -> list[FileEntry]:
    """把整个归档读成条目列表（仅用于需要整包重写的场景）。"""
    entries: list[FileEntry] = []
    with zipfile.ZipFile(archive.path, "r") as source:
        for info in source.infolist():
            if info.filename.endswith("/"):
                continue
            name = normalize_name(info.filename)
            entries.append(
                FileEntry(
                    name=name,
                    data=source.read(info.filename),
                    compress=info.compress_type != zipfile.ZIP_STORED or name != MIMETYPE_NAME,
                )
            )
    return entries
