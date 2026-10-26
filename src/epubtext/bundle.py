"""合并产物（bundle）的格式定义：边界标记、头部、账本序列化与解析。

格式选择的理由：

* **不能靠字节偏移**。合并出来的 TXT 是要拿去外部校对软件里改字的，
  长度一变偏移全废。原实现用「数 ``</html>`` 出现次数」再按下标硬对齐，
  一旦某个章节里出现第二个 ``</html>`` 或用户删掉一个标签，就会整体错位且静默无提示。
* **用带 nonce 的行级标记**。每章前放一行 ``<!-- EPUBTEXT-SPLIT:{nonce}:{i} ... -->``，
  标记独占一行，既不破坏单个章节文档的 XML 结构，也不受行尾 CRLF/LF 转换影响。
  nonce 每次合并随机生成，正文里出现同样标记的概率可以忽略；
  解析时还会用「索引连续 + path 与账本一致 + 数量等于头部声明」三重校验。
* **账本随 TXT 一起落盘**（sidecar JSON），记录每章的原始路径、字节数、sha256、
  行尾风格、被剥掉的行尾，以及整本书的 OPF 信息，使还原不依赖原 EPUB 也能校验。

字节级可逆的关键在 :func:`reconstruct_chapter_bytes`：它把「切出来的文本」
按账本记录的行尾风格和章末换行还原成原始字节，还原与校验共用这一个函数，
因此「校验通过」等价于「写出来的字节与合并前一致」。
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, unquote

from .errors import BundleFormatError

BUNDLE_FORMAT = "epubtext-bundle/1"
HEADER_PREFIX = "<!-- EPUBTEXT-BUNDLE"
SPLIT_PREFIX = "<!-- EPUBTEXT-SPLIT"
BOOK_PREFIX = "<!-- EPUBTEXT-BOOK"

HEADER_RE = re.compile(r"^<!--\s*EPUBTEXT-BUNDLE\s+(?P<body>.*?)\s*-->\s*$", re.IGNORECASE)
SPLIT_RE = re.compile(
    r"^<!--\s*EPUBTEXT-SPLIT:(?P<nonce>[0-9a-f]{8,32}):(?P<index>\d+)\s+(?P<body>.*?)\s*-->\s*$",
    re.IGNORECASE,
)
BOOK_RE = re.compile(
    r"^<!--\s*EPUBTEXT-BOOK:(?P<nonce>[0-9a-f]{8,32}):(?P<index>\d+)\s+(?P<body>.*?)\s*-->\s*$",
    re.IGNORECASE,
)
ATTR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")

SEPARATOR = "\n"  # 每章正文与下一个标记之间的固定分隔
BOM_BYTES = b"\xef\xbb\xbf"


def new_nonce(length: int = 16) -> str:
    return secrets.token_hex(length // 2)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_attrs(body: str) -> dict[str, str]:
    return {key: unquote(value) for key, value in ATTR_RE.findall(body)}


def encode_attr(value: str) -> str:
    return quote(str(value), safe="._-/:@+~")


def detect_eol(raw: bytes) -> str:
    """判断章节原始行尾风格。"""
    return "crlf" if b"\r\n" in raw else "lf"


def strip_trailing_newlines(data: bytes) -> tuple[bytes, bytes]:
    """拆出正文末尾的连续换行，返回 (主体, 被剥掉的行尾字节)。"""
    stripped = data.rstrip(b"\r\n")
    return stripped, data[len(stripped):]


@dataclass
class ChapterRecord:
    """账本里的一章：足够把它逐字节写回去。"""

    index: int
    path: str
    label: str
    media_type: str
    size: int
    sha256: str
    eol: str = "lf"  # 原始行尾：lf / crlf
    tail: str = ""  # 原始章末换行，以 latin-1 存字符串，保证字节可逆
    bom: bool = False  # 原始文件是否带 UTF-8 BOM
    order: int = 0  # 在 spine 中的位置
    linear: bool = True
    book_index: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict) -> "ChapterRecord":
        return ChapterRecord(
            index=int(raw["index"]),
            path=raw["path"],
            label=raw.get("label", ""),
            media_type=raw.get("media_type", "application/xhtml+xml"),
            size=int(raw.get("size", 0)),
            sha256=raw.get("sha256", ""),
            eol=raw.get("eol", "lf"),
            tail=raw.get("tail", ""),
            bom=bool(raw.get("bom", False)),
            order=int(raw.get("order", 0)),
            linear=bool(raw.get("linear", True)),
            book_index=int(raw.get("book_index", 0)),
        )


@dataclass
class BookRecord:
    source: str
    title: str
    identifier: str
    opf_path: str
    opf_dir: str
    sha256: str
    spine: list[str] = field(default_factory=list)
    chapters: list[ChapterRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "identifier": self.identifier,
            "opf_path": self.opf_path,
            "opf_dir": self.opf_dir,
            "sha256": self.sha256,
            "spine": self.spine,
            "chapters": [chapter.to_dict() for chapter in self.chapters],
            "warnings": self.warnings,
        }

    @staticmethod
    def from_dict(raw: dict) -> "BookRecord":
        return BookRecord(
            source=raw.get("source", ""),
            title=raw.get("title", ""),
            identifier=raw.get("identifier", ""),
            opf_path=raw.get("opf_path", ""),
            opf_dir=raw.get("opf_dir", ""),
            sha256=raw.get("sha256", ""),
            spine=list(raw.get("spine", [])),
            chapters=[ChapterRecord.from_dict(item) for item in raw.get("chapters", [])],
            warnings=list(raw.get("warnings", [])),
        )


@dataclass
class Ledger:
    """一次合并操作的完整账本。"""

    nonce: str
    books: list[BookRecord]
    text_path: str = ""
    format: str = BUNDLE_FORMAT

    @property
    def chapters(self) -> list[ChapterRecord]:
        return [chapter for book in self.books for chapter in book.chapters]

    def to_json(self) -> str:
        return json.dumps(
            {
                "format": self.format,
                "nonce": self.nonce,
                "text_path": self.text_path,
                "books": [book.to_dict() for book in self.books],
            },
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def from_json(raw: str) -> "Ledger":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BundleFormatError(f"账本 JSON 无法解析：{exc}") from exc
        if data.get("format") != BUNDLE_FORMAT:
            raise BundleFormatError(f"账本格式不受支持：{data.get('format')!r}")
        return Ledger(
            nonce=data["nonce"],
            books=[BookRecord.from_dict(item) for item in data.get("books", [])],
            text_path=data.get("text_path", ""),
            format=data["format"],
        )

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @staticmethod
    def load(path: str | Path) -> "Ledger":
        path = Path(path)
        if not path.exists():
            raise BundleFormatError(f"账本文件不存在：{path}")
        return Ledger.from_json(path.read_text(encoding="utf-8"))


def ledger_path_for(text_path: str | Path) -> Path:
    """账本与 TXT 同目录同名，后缀换成 ``.bundle.json``。"""
    text_path = Path(text_path)
    return text_path.with_name(text_path.stem + ".bundle.json")


def build_header(nonce: str, book_count: int, chapter_count: int) -> str:
    return (
        f"{HEADER_PREFIX} format={BUNDLE_FORMAT} nonce={nonce} "
        f"books={book_count} chapters={chapter_count} -->"
    )


def build_book_marker(nonce: str, index: int, title: str, source: str, chapter_count: int) -> str:
    return (
        f"{BOOK_PREFIX}:{nonce}:{index} title={encode_attr(title)} "
        f"source={encode_attr(source)} chapters={chapter_count} -->"
    )


def build_split_marker(nonce: str, index: int, path: str, label: str, chars: int, sha: str) -> str:
    return (
        f"{SPLIT_PREFIX}:{nonce}:{index} path={encode_attr(path)} "
        f"label={encode_attr(label)} chars={chars} sha={sha[:16]} -->"
    )


@dataclass
class SplitChunk:
    """从合并文本里切出来的一段：紧跟在某个章节标记之后。"""

    marker: dict[str, str]
    index: int
    body: str


def canonical_body(chunk_body: str) -> str:
    """去掉合并时追加的那个固定分隔换行，得到原始正文主体（LF 形态）。"""
    if chunk_body.endswith(SEPARATOR):
        return chunk_body[: -len(SEPARATOR)]
    return chunk_body


def reconstruct_chapter_bytes(chunk: SplitChunk, record: ChapterRecord) -> bytes:
    """把切出来的一章文本还原成原始字节，与合并时的 sha256 可直接比对。"""
    body = canonical_body(chunk.body)
    if record.eol == "crlf":
        data = body.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    else:
        data = body.replace("\r\n", "\n").encode("utf-8")
    return (BOM_BYTES if record.bom else b"") + data + record.tail.encode("latin-1")


def split_bundle(text: str, ledger: Ledger, strict: bool = True) -> list[SplitChunk]:
    """按标记把合并文本切回逐章正文，并做三重一致性校验。

    校验项（``strict`` 时任一失败即抛错）：

    1. 头部存在且 nonce 与账本一致；
    2. 标记索引从 0 连续递增，数量等于账本声明的章数；
    3. 每个标记的 path 必须与账本同位置的记录一致。

    只数标记数量是不够的：漏掉一个标记而多出一个伪造标记，
    总数依旧对得上，但正文会被写进错误的文件，所以还要比对 path 与顺序。
    """
    lines = text.split("\n")
    header_seen = False
    chunks: list[SplitChunk] = []
    current: dict[str, str] | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current is not None:
            chunks.append(SplitChunk(marker=current, index=int(current["index"]), body="\n".join(buffer)))
        buffer = []

    for line in lines:
        stripped = line.rstrip("\r")

        header_match = HEADER_RE.match(stripped)
        if header_match is not None and not header_seen and current is None:
            attrs = parse_attrs(header_match.group("body"))
            header_seen = True
            if attrs.get("nonce") != ledger.nonce:
                raise BundleFormatError(
                    f"合并文本头部 nonce({attrs.get('nonce')}) 与账本({ledger.nonce}) 不一致，"
                    "可能不是同一次合并的产物"
                )
            declared = attrs.get("chapters")
            if declared is not None and int(declared) != len(ledger.chapters):
                raise BundleFormatError(f"头部声明 {declared} 章，账本记录 {len(ledger.chapters)} 章，不一致")
            continue

        if BOOK_RE.match(stripped) is not None:
            continue

        split_match = SPLIT_RE.match(stripped)
        if split_match is not None:
            attrs = parse_attrs(split_match.group("body"))
            attrs["index"] = split_match.group("index")
            attrs["nonce"] = split_match.group("nonce")
            flush()
            current = attrs
            continue

        buffer.append(line)

    flush()

    if not strict:
        return chunks

    if not header_seen:
        raise BundleFormatError("合并文本缺少 EPUBTEXT-BUNDLE 头部，无法确认来源与章数")
    expected = ledger.chapters
    if len(chunks) != len(expected):
        raise BundleFormatError(f"切出 {len(chunks)} 章，账本记录 {len(expected)} 章，数量不一致")
    for position, chunk in enumerate(chunks):
        record = expected[position]
        if chunk.index != position:
            raise BundleFormatError(
                f"第 {position} 段标记索引为 {chunk.index}，索引不连续（可能有重复或缺失标记）"
            )
        marked_path = chunk.marker.get("path", "")
        if marked_path != record.path:
            raise BundleFormatError(
                f"第 {position} 段标记指向 {marked_path!r}，账本记录为 {record.path!r}，顺序被破坏"
            )
    return chunks


def verify_chapter_integrity(chunk: SplitChunk, record: ChapterRecord) -> dict:
    """比对单章内容是否仍与合并时一致（以真实还原字节的 sha256 为准）。"""
    data = reconstruct_chapter_bytes(chunk, record)
    actual = sha256_bytes(data)
    return {
        "index": record.index,
        "path": record.path,
        "unchanged": actual == record.sha256,
        "expected_sha": record.sha256[:16],
        "actual_sha": actual[:16],
        "expected_size": record.size,
        "actual_size": len(data),
    }


def verify_bundle(chunks: Iterable[SplitChunk], ledger: Ledger) -> list[dict]:
    """逐章校验整份合并文本，返回每章的差异报告（不抛错，供调用方决策）。"""
    return [verify_chapter_integrity(chunk, record) for chunk, record in zip(chunks, ledger.chapters)]
