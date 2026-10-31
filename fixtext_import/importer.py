"""FixText V1 · 导入服务（T2.2 · M5-EX.3 统一可逆）

一条导入链路的完整实现，界面层只负责收集用户意图和展示结果。

固定流程（顺序不可变）：

1. 识别文件类型（TXT / EPUB）。
2. **记录原文件 sha256**（导入前）。
3. 把原文件**逐字节复制**进内部工作区 `<工作区>/<书 id>/original/`。
4. TXT：识别字符集 → 读成文本 → 统一换行 → 以通用格式写入 `book.txt`。
   EPUB：**一律可逆合并**（产出 ``book.txt`` + 章节映射账本；导出页再选
   TXT / 还原 EPUB）。不再提供「先转 TXT」产品路径。
5. **再次计算原文件 sha256**，与第 2 步比对；再校验工作区副本与原文件一致。
6. 写导入记录 `import.json`（含两份哈希、识别结果、导入方式）。

重复导入（同内容 → 同书 id）：优先复用；若记录损坏但 ``book.txt`` 已在，
**绝不覆盖工作正文**（校正/检查页改动保留），只刷新原件副本与记录。

原文件在整条链路里只被**只读打开**（`rb`），没有任何写入路径指向它。
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import messages
from .encoding import probe, decode_file, ProbeResult
from .textfile import (
    copy_verbatim, normalize, sha256_file, write_text_atomic,
)

SUPPORTED_SUFFIXES = {".txt", ".epub"}
WORKSPACE_VERSION = 1


class ImportError_(Exception):
    """导入失败（消息已是人话）。"""


@dataclass
class ImportOptions:
    """导入选项。

    ``epub_mode`` 保留字段以兼容旧调用 / 旧 ``import.json``；M5-EX.3 起
    EPUB **始终**按可逆（``direct``）处理，传入其它值也会被忽略。
    """

    #: 历史字段；产品路径固定为可逆（direct）
    epub_mode: str = "direct"
    #: 同一本书重复导入时是否复用已有副本
    reuse_existing: bool = True


@dataclass
class ImportResult:
    book_id: str
    title: str
    source_path: str
    source_suffix: str
    workspace_dir: str
    text_path: str
    original_copy_path: str
    ledger_path: str | None
    # 哈希证据
    source_sha256_before: str
    source_sha256_after: str
    workspace_copy_sha256: str
    source_unchanged: bool
    # 文本事实
    encoding_codec: str
    encoding_label: str
    encoding_confidence: str
    encoding_certain: bool
    newline_kind: str
    newline_changed: bool
    text_chars: int
    text_bytes: int
    replaced_chars: int
    chapters: int
    epub_mode: str
    reminded: list[str] = field(default_factory=list)
    reused: bool = False
    elapsed_ms: int = 0
    #: 作者（导入时从书的元信息里自动提取，可在导出页修正）
    author: str = ""

    @property
    def human_notes(self) -> list[str]:
        """给界面直接展示的人话提示（顺序即展示顺序）。"""
        return self.reminded


def _book_id(name: str, sha: str) -> str:
    """书 id：可读前缀 + 内容哈希前 8 位，保证同内容幂等、不同内容不撞。"""
    stem = Path(name).stem
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", stem).strip("_")[:40] or "book"
    return f"{safe}_{sha[:8]}"


def _count_chars(text: str) -> int:
    """正文字数（不计空白），与排期文档里"字数"的口径一致。"""
    return len(re.sub(r"\s+", "", text))


def detect_kind(path: str | Path) -> str:
    """返回 'txt' / 'epub'；不支持的类型抛人话异常。"""
    path = Path(path)
    if not path.exists() or not path.is_file():
        raise ImportError_("找不到这个文件，它可能被移动或删除了。")
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return "txt"
    if suffix == ".epub":
        return "epub"
    if path.stat().st_size == 0:
        raise ImportError_(messages.empty_file())
    raise ImportError_(messages.unsupported_type())


def import_book(
    source: str | Path,
    workspace_root: str | Path,
    options: ImportOptions | None = None,
    progress=None,
) -> ImportResult:
    """把一本书导入内部工作区。`progress(step, percent)` 可为 None。"""
    started = time.time()
    options = options or ImportOptions()
    source = Path(source)
    workspace_root = Path(workspace_root)

    def tick(step: str, pct: int) -> None:
        if progress:
            progress(step, pct)

    if source.stat().st_size == 0:
        raise ImportError_(messages.empty_file())
    kind = detect_kind(source)

    tick("正在读你选的文件", 5)
    sha_before = sha256_file(source)
    book_id = _book_id(source.name, sha_before)
    book_dir = workspace_root / book_id
    record_path = book_dir / "import.json"
    text_path = book_dir / "book.txt"

    # 幂等：同内容已导入过则复用，不覆盖工作正文、不产生重复目录
    if options.reuse_existing:
        reused = _try_reuse_existing(
            record_path, text_path, sha_before, started, tick)
        if reused is not None:
            return reused

    original_dir = book_dir / "original"
    original_dir.mkdir(parents=True, exist_ok=True)
    original_copy = original_dir / source.name

    tick("正在复制到工作区（原文件只读，不会被改）", 25)
    copied_src_sha, copied_dst_sha = copy_verbatim(source, original_copy)
    if copied_src_sha != sha_before:
        # 复制过程中源文件被外部改动 —— 明确报错而不是继续
        raise ImportError_("导入时这个文件正在被其它程序修改，请关掉它再试一次。")

    # 书目录里已有 book.txt（校正/检查页可能已改过）：绝不覆盖工作正文
    if text_path.is_file():
        tick("保留工作区已有正文，不覆盖校正结果", 70)
        result = _result_keeping_working_copy(
            source=source,
            kind=kind,
            book_id=book_id,
            book_dir=book_dir,
            text_path=text_path,
            original_copy=original_copy,
            sha_before=sha_before,
            copied_dst_sha=copied_dst_sha,
            started=started,
            old_record=_read_record_loose(record_path),
        )
        _write_import_record(record_path, result, copied_dst_sha == sha_before)
        tick("导入完成", 100)
        return result

    notes: list[str] = [messages.copied_note()]

    # M5-EX.3：EPUB 统一可逆；TXT 记为 text（无账本）。忽略 options.epub_mode。
    epub_mode = "direct" if kind == "epub" else "text"
    ledger_path: str | None = None
    chapters = 0
    encoding = ProbeResult(codec="utf-8", label="UTF-8", confidence="strict", has_bom=False)
    newline_kind, newline_changed, replaced = "lf", False, 0

    if kind == "txt":
        tick("正在看这本书的字符格式", 45)
        encoding = probe(original_copy)
        raw_text = decode_file(original_copy, encoding.codec)
        tick("正在整理正文", 65)
        norm = normalize(raw_text)
        replaced = norm.replaced_chars
        newline_kind, newline_changed = norm.newline_kind, norm.newline_changed
        write_text_atomic(text_path, norm.text)
        notes.append(messages.encoding_note(encoding.codec, encoding.certain))
        if newline_changed:
            notes.append(messages.newline_note(True))
        if not encoding.certain:
            notes.append(messages.uncertain_warning())
        chapters = 1
        title = source.stem
        author = ""
    else:
        from . import epub_import

        tick("正在读这本书的章节", 40)
        preview = epub_import.chapter_preview(original_copy)
        chapters = len(preview.chapters)
        title = preview.title or source.stem
        author = preview.author or ""
        notes.append(messages.epub_merged_note(chapters))

        tick("正在按书的顺序合并章节（可还原）", 70)
        merged = epub_import.merge_reversible(original_copy, text_path)
        ledger_path = str(merged.ledger_path)
        encoding = ProbeResult(codec="utf-8", label="UTF-8", confidence="strict")
        newline_kind, newline_changed = "lf", False

    tick("正在核对原文件有没有被改动", 88)
    sha_after = sha256_file(source)
    copy_veri_sha = sha256_file(original_copy)
    source_unchanged = sha_after == sha_before
    if not source_unchanged:
        raise ImportError_(
            "导入期间这个文件被其它程序改动了，请你先关掉它再导入一次。"
        )
    notes.append(messages.unchanged_note())

    text = text_path.read_text(encoding="utf-8")
    result = ImportResult(
        book_id=book_id,
        title=title,
        author=author,
        source_path=str(source),
        source_suffix=source.suffix.lower(),
        workspace_dir=str(book_dir),
        text_path=str(text_path),
        original_copy_path=str(original_copy),
        ledger_path=ledger_path,
        source_sha256_before=sha_before,
        source_sha256_after=sha_after,
        workspace_copy_sha256=copy_veri_sha,
        source_unchanged=source_unchanged,
        encoding_codec=encoding.codec,
        encoding_label=encoding.label,
        encoding_confidence=encoding.confidence,
        encoding_certain=encoding.certain,
        newline_kind=newline_kind,
        newline_changed=newline_changed,
        text_chars=_count_chars(text),
        text_bytes=len(text.encode("utf-8")),
        replaced_chars=replaced,
        chapters=chapters,
        epub_mode=epub_mode,
        reminded=notes,
        elapsed_ms=int((time.time() - started) * 1000),
    )

    _write_import_record(record_path, result, copied_dst_sha == sha_before)
    tick("导入完成", 100)
    return result


def _read_record_loose(record_path: Path) -> dict:
    if not record_path.is_file():
        return {}
    try:
        data = json.loads(record_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, TypeError):
        return {}


def _try_reuse_existing(
    record_path: Path,
    text_path: Path,
    sha_before: str,
    started: float,
    tick,
) -> ImportResult | None:
    """同内容 + 工作正文仍在 → 直接复用，不改 book.txt。"""
    if not record_path.is_file() or not text_path.is_file():
        return None
    old = _read_record_loose(record_path)
    if not old or old.get("source_sha256_before") != sha_before:
        return None
    recorded = Path(str(old.get("text_path") or ""))
    if recorded.resolve() != text_path.resolve() and recorded.is_file():
        # 记录指向别处且文件还在：仍以标准 book.txt 为准
        pass
    tick("这本书之前导入过，直接打开", 100)
    fields = {k: v for k, v in old.items() if k in ImportResult.__dataclass_fields__}
    fields["text_path"] = str(text_path)
    # 账本以盘上为准（校正后可能已换成 book.bundle.json）
    bundle = text_path.with_name("book.bundle.json")
    if bundle.is_file():
        fields["ledger_path"] = str(bundle)
    elif old.get("ledger_path") and Path(str(old["ledger_path"])).is_file():
        fields["ledger_path"] = str(old["ledger_path"])
    try:
        text = text_path.read_text(encoding="utf-8")
        fields["text_chars"] = _count_chars(text)
        fields["text_bytes"] = len(text.encode("utf-8"))
    except OSError:
        pass
    result = ImportResult(**fields)
    result.elapsed_ms = int((time.time() - started) * 1000)
    result.reused = True
    result.reminded = list(old.get("reminded") or []) + [messages.duplicate_note()]
    return result


def _result_keeping_working_copy(
    *,
    source: Path,
    kind: str,
    book_id: str,
    book_dir: Path,
    text_path: Path,
    original_copy: Path,
    sha_before: str,
    copied_dst_sha: str,
    started: float,
    old_record: dict,
) -> ImportResult:
    """书目录已有 book.txt：只刷新原件，保留工作正文与账本。"""
    sha_after = sha256_file(source)
    if sha_after != sha_before:
        raise ImportError_(
            "导入期间这个文件被其它程序改动了，请你先关掉它再导入一次。"
        )
    text = text_path.read_text(encoding="utf-8")
    bundle = book_dir / "book.bundle.json"
    ledger_path = None
    if bundle.is_file():
        ledger_path = str(bundle)
    elif old_record.get("ledger_path") and Path(str(old_record["ledger_path"])).is_file():
        ledger_path = str(old_record["ledger_path"])

    title = str(old_record.get("title") or source.stem)
    author = str(old_record.get("author") or "")
    chapters = int(old_record.get("chapters") or (1 if kind == "txt" else 0))
    if kind == "epub" and chapters <= 0:
        try:
            from . import epub_import
            preview = epub_import.chapter_preview(original_copy)
            chapters = len(preview.chapters) or 1
            title = preview.title or title
            author = preview.author or author
        except Exception:
            chapters = max(chapters, 1)
    notes = [
        messages.copied_note(),
        messages.keep_working_copy_note(),
        messages.unchanged_note(),
    ]
    return ImportResult(
        book_id=book_id,
        title=title,
        author=author,
        source_path=str(source),
        source_suffix=source.suffix.lower(),
        workspace_dir=str(book_dir),
        text_path=str(text_path),
        original_copy_path=str(original_copy),
        ledger_path=ledger_path,
        source_sha256_before=sha_before,
        source_sha256_after=sha_after,
        workspace_copy_sha256=copied_dst_sha,
        source_unchanged=True,
        encoding_codec=str(old_record.get("encoding_codec") or "utf-8"),
        encoding_label=str(old_record.get("encoding_label") or "UTF-8"),
        encoding_confidence=str(old_record.get("encoding_confidence") or "strict"),
        encoding_certain=bool(old_record.get("encoding_certain", True)),
        newline_kind=str(old_record.get("newline_kind") or "lf"),
        newline_changed=bool(old_record.get("newline_changed", False)),
        text_chars=_count_chars(text),
        text_bytes=len(text.encode("utf-8")),
        replaced_chars=int(old_record.get("replaced_chars") or 0),
        chapters=chapters or 1,
        epub_mode="direct" if kind == "epub" else "text",
        reminded=notes,
        reused=True,
        elapsed_ms=int((time.time() - started) * 1000),
    )


def _write_import_record(
    record_path: Path, result: ImportResult, copy_matches: bool,
) -> None:
    record = asdict(result)
    record.update({
        "workspace_version": WORKSPACE_VERSION,
        "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "workspace_copy_matches_source": copy_matches,
    })
    write_text_atomic(record_path, json.dumps(record, ensure_ascii=False, indent=2))


def load_record(book_dir: str | Path) -> dict | None:
    p = Path(book_dir) / "import.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def verify_untouched(result: ImportResult) -> dict:
    """事后复核：原文件与工作区副本是否仍与导入时一致。"""
    src = Path(result.source_path)
    out = {
        "source_exists": src.exists(),
        "source_sha256_now": "",
        "source_unchanged": False,
        "copy_sha256_now": sha256_file(result.original_copy_path),
        "copy_unchanged": False,
    }
    if out["source_exists"]:
        out["source_sha256_now"] = sha256_file(src)
        out["source_unchanged"] = out["source_sha256_now"] == result.source_sha256_before
    out["copy_unchanged"] = out["copy_sha256_now"] == result.source_sha256_before
    return out


def workspace_usage(workspace_root: str | Path) -> tuple[int, int]:
    """(书数, 占用字节)。"""
    root = Path(workspace_root)
    if not root.exists():
        return 0, 0
    books = 0
    size = 0
    for d in root.iterdir():
        if d.is_dir() and (d / "import.json").exists():
            books += 1
            size += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    return books, size
