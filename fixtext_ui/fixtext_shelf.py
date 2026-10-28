"""FixText V1 · 工作区书架与「当前书」（M4-EX.3a）

本模块是**当前书机制的唯一数据层**，不含任何 Qt 依赖，界面层只做渲染：

- 书架条目口：`list_books()` 枚举工作区里真实的书（判据与
  `fixtext_import.workspace_usage` 一致——目录下有导入记录 `import.json` 才算一本书），
  **不新增任何导入副本机制**，书架只是已有副本的视图。
- 当前书：持久化在用户区 `workspace/settings.ini` 的 `currentBook` 键，
  存的是书 id（目录名），重启后按它恢复；找不到这本书时回落到「最近导入的那本」，
  再没有就视为没有当前书。
- 已导出标识：**只由真实导出记录驱动**——书目录下存在 `exports.json` 才显示。
  M4-EX.3a 不写这个记录（导出完成写入属 M4-EX.3b），所以这版标识不会出现，
  不是「先把状态摆上去、数据以后补」。

为什么当前书要单独存一份而不是每次现算「最近导入」：导入模块支持多本，
「最近导入」只是时间顺序，用户选中哪本是他自己的决定，必须在重启后仍然成立。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import fixtext_settings as app_settings

#: 当前书在设置文件里的键（值是书 id，即工作区里那本书的目录名）
KEY_CURRENT_BOOK = "currentBook"
#: 单本书的导出记录文件名（M4-EX.3b 才写入；本卡只读，用来驱动「已导出」标识）
EXPORT_RECORD = "exports.json"
#: 导入记录文件名（导入链路固定写这个名字）
IMPORT_RECORD = "import.json"

_FORMAT_LABELS = {".epub": "EPUB", ".txt": "TXT"}


@dataclass
class Book:
    """工作区里的一本书（全部字段来自磁盘上的真实文件）。"""

    book_id: str
    dir: Path
    title: str
    fmt: str
    suffix: str
    size_bytes: int
    imported_at: str
    imported_dt: datetime | None
    record: dict

    @property
    def text_path(self) -> str:
        return str(self.record.get("text_path") or "")

    @property
    def original_copy_path(self) -> str:
        return str(self.record.get("original_copy_path") or "")

    @property
    def exported_at(self) -> str:
        """最近一次导出的时间；没有真实导出记录时为空串（界面据此决定显不显示）。"""
        data = read_export_record(self.dir)
        return str(data.get("exported_at") or "") if data else ""


# ---------------------------------------------------------------------------
# 读盘
# ---------------------------------------------------------------------------

def book_dir_of(workspace_root: str | Path, book_id: str) -> Path:
    return Path(workspace_root) / str(book_id)


def read_import_record(book_dir: str | Path) -> dict | None:
    """读一本书的导入记录；损坏或不存在都返回 None（不猜内容）。"""
    path = Path(book_dir) / IMPORT_RECORD
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_export_record(book_dir: str | Path) -> dict | None:
    """读一本书的导出记录；没有就返回 None。"""
    path = Path(book_dir) / EXPORT_RECORD
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _dir_size(root: Path) -> int:
    total = 0
    for f in root.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def _parse_time(text: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except (TypeError, ValueError):
            continue
    return None


def _fallback_dt(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def load_book(book_dir: str | Path) -> Book | None:
    """把工作区里的一个目录读成 Book；不是书（没有导入记录）返回 None。"""
    d = Path(book_dir)
    record = read_import_record(d)
    if record is None:
        return None
    suffix = str(record.get("source_suffix") or "").lower()
    if not suffix:
        # 老记录没有这个字段时，按原文件副本的后缀判断（仍是磁盘事实）
        suffix = Path(str(record.get("original_copy_path") or "")).suffix.lower()
    title = str(record.get("title") or "").strip() or d.name
    imported_at = str(record.get("imported_at") or "")
    when = _parse_time(imported_at) or _fallback_dt(d)
    return Book(
        book_id=d.name,
        dir=d,
        title=title,
        fmt=_FORMAT_LABELS.get(suffix, suffix.lstrip(".").upper() or "未知"),
        suffix=suffix,
        size_bytes=_dir_size(d),
        imported_at=imported_at,
        imported_dt=when,
        record=record,
    )


def list_books(workspace_root: str | Path) -> list[Book]:
    """工作区里所有真实的书，按导入时间从新到旧（时间相同按书名稳定排序）。"""
    root = Path(workspace_root)
    if not root.exists():
        return []
    books: list[Book] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        book = load_book(child)
        if book is not None:
            books.append(book)
    books.sort(key=lambda b: b.book_id)
    books.sort(
        key=lambda b: (b.imported_dt.timestamp() if b.imported_dt else 0.0),
        reverse=True,
    )
    return books


# ---------------------------------------------------------------------------
# 当前书（持久化）
# ---------------------------------------------------------------------------

def stored_current_id() -> str:
    """设置文件里记着的当前书 id（可能是空串，也可能是已经不在工作区的旧 id）。"""
    return str(app_settings._get(KEY_CURRENT_BOOK, "") or "").strip()


def set_current_book_id(book_id: str) -> None:
    """记下当前书（只写设置文件，不动书本体）。"""
    app_settings._set(KEY_CURRENT_BOOK, str(book_id or ""))


def clear_current_book_id() -> None:
    set_current_book_id("")


def resolve_current(workspace_root: str | Path,
                    books: list[Book] | None = None) -> Book | None:
    """当前书：设置里记的那本 → 不存在时退回最近导入的那本 → 都没有则 None。"""
    items = books if books is not None else list_books(workspace_root)
    if not items:
        return None
    wanted = stored_current_id()
    if wanted:
        for b in items:
            if b.book_id == wanted:
                return b
    return items[0]


def find_book(workspace_root: str | Path, book_id: str) -> Book | None:
    if not book_id:
        return None
    return load_book(book_dir_of(workspace_root, book_id))


# ---------------------------------------------------------------------------
# 人话字段
# ---------------------------------------------------------------------------

def human_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "大小未知"
    mb = size_bytes / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.1f} MB"
    kb = size_bytes / 1024
    return f"{kb:.0f} KB"


def human_imported(book: Book, now: datetime | None = None) -> str:
    """导入时间的人类写法；跨年时补上年份（不显示原始时间串）。"""
    dt = book.imported_dt
    if dt is None:
        return "导入时间未知"
    current_year = (now or datetime.now()).year
    if dt.year != current_year:
        return f"{dt.year}年{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}"
    return f"{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}"


def shelf_caption(n_books: int, size_bytes: int) -> str:
    """书架上方的一句话（数量 + 占用）。"""
    if n_books <= 0:
        return "工作区还是空的，导入第一本书后就会出现在这里。"
    return f"工作区里已有 {n_books} 本书，共约 {size_bytes / (1024 * 1024):.1f} MB。"


def total_size(books: list[Book]) -> int:
    return sum(b.size_bytes for b in books)
