"""FixText V1 · 导入服务（T2.2）

一条导入链路的完整实现，界面层只负责收集用户意图和展示结果。

固定流程（顺序不可变）：

1. 识别文件类型（TXT / EPUB）。
2. **记录原文件 sha256**（导入前）。
3. 把原文件**逐字节复制**进内部工作区 `<工作区>/<书 id>/original/`。
4. TXT：识别字符集 → 读成文本 → 统一换行 → 以通用格式写入 `book.txt`。
   EPUB：按用户选择走「可还原合并」（M1 `merge_epub`，产出 book.txt + 账本）
   或「先转 TXT」（剥标签的纯文本）。
5. **再次计算原文件 sha256**，与第 2 步比对；再校验工作区副本与原文件一致。
6. 写导入记录 `import.json`（含两份哈希、识别结果、用户选择的导入方式）。

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
    """导入选项（对应 §2.7.3 的选项空间）。"""

    #: EPUB 导入方式：direct=直接处理（可还原） / text=先转成 TXT
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

    # 幂等：同内容已导入过则复用，不产生重复目录
    if options.reuse_existing and record_path.exists():
        try:
            old = json.loads(record_path.read_text(encoding="utf-8"))
            if old.get("source_sha256_before") == sha_before and Path(old.get("text_path", "")).exists():
                tick("这本书之前导入过，直接打开", 100)
                result = ImportResult(**{k: v for k, v in old.items()
                                         if k in ImportResult.__dataclass_fields__})
                result.elapsed_ms = int((time.time() - started) * 1000)
                result.reused = True
                result.reminded = list(old.get("reminded", [])) + [messages.duplicate_note()]
                return result
        except (json.JSONDecodeError, TypeError):
            pass  # 记录损坏时按新导入处理

    original_dir = book_dir / "original"
    original_dir.mkdir(parents=True, exist_ok=True)
    original_copy = original_dir / source.name

    tick("正在复制到工作区（原文件只读，不会被改）", 25)
    copied_src_sha, copied_dst_sha = copy_verbatim(source, original_copy)
    if copied_src_sha != sha_before:
        # 复制过程中源文件被外部改动 —— 明确报错而不是继续
        raise ImportError_("导入时这个文件正在被其它程序修改，请关掉它再试一次。")

    notes: list[str] = [messages.copied_note()]

    epub_mode = options.epub_mode if kind == "epub" else "text"
    ledger_path: str | None = None
    chapters = 0
    encoding = ProbeResult(codec="utf-8", label="UTF-8", confidence="strict", has_bom=False)
    newline_kind, newline_changed, replaced = "lf", False, 0
    text_path = book_dir / "book.txt"

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

        if epub_mode == "direct":
            tick("正在按书的顺序合并章节", 70)
            merged = epub_import.merge_reversible(original_copy, text_path)
            ledger_path = str(merged.ledger_path)
        else:
            tick("正在把章节拼成一份纯文本", 70)
            epub_import.merge_to_plain_text(original_copy, text_path)
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

    record = asdict(result)
    record.update({
        "workspace_version": WORKSPACE_VERSION,
        "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "workspace_copy_matches_source": copied_dst_sha == sha_before,
    })
    write_text_atomic(record_path, json.dumps(record, ensure_ascii=False, indent=2))
    tick("导入完成", 100)
    return result


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
