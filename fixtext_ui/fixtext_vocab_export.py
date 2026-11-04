"""V1.1-D7 · 「我的词库」备份导出与还原辅助（**不依赖 Qt**）。

这张卡的验收硬指标是**闭环**：导出的文件必须能被本工程自带的导入通道
（D1 解析 + D2 分批 + D3 预览）原样读回来。所以格式不是"看起来像表格就行"，
而是逐条对着 D1 的解析规则推出来的：

1. **字段转义复用原版那套标记**（``escape_escaped``）。原版把会破坏列结构的
   四个字符换成【】标记，D1 的还原与它同源，因此导出侧也必须用同一套。
   反过来自己发明一套转义，导入侧认不出来，闭环就断了。
2. **列用英文逗号分隔**。D1 判定分隔符靠"每行列数一致"投票；固定 6 列、
   且值里的逗号已被换成标记，所以每一行列数恒为 6，逗号稳定胜出。
3. **第一行写表头**，并且表头用词要命中 D1 的表头字样（原词 / 替换为 /
   类型 / 注音），这样列映射会自动对好，用户不需要在预览页手工改列。
4. **多出来的两列（参与校正 / 书籍）走「不使用这列」**。D1 的表头建议
   在关键两列都命中后**不再**退回位置约定，所以这两列会稳稳落到
   ``ROLE_IGNORE``，既不干扰导入，又能在备份文件里留住信息。

**为什么必须自己检查"能不能装得下"**：转义表只覆盖四个字符。制表符会让
D1 的分隔符投票误判成制表符分列，回车会被统一成换行从而把一条词条劈成两行；
而值里若本来就有字面量 ``【英文逗号】``，还原时无法与真正的逗号区分。
这些都不是"概率小"，而是**一定**读不回来。所以本模块宁可明确拒绝并说清
是哪几条、为什么，也不写出一份"看着成功、实际丢内容"的备份。

范围边界：只读写「我的词库」这一层；出厂词库全程只读（本模块不提供任何
写入口）；不做"导出后编辑再导入"的双向编辑语义——改过的文件再导入，
语义以导入预览给出的三组为准。
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from fixtext_paths import HISTORY_STAMP_FORMAT, default_export_dir

#: 导出文件的表头。**顺序即列顺序**，改动前先看模块头第 3 条：
#: 前四列会被导入通道认领，后两列只作备份记录（导入时按「不使用这列」处理）。
EXPORT_HEADER: tuple[str, ...] = ("原词", "替换为", "类型", "注音", "参与校正", "书籍")

#: 「参与校正」列的两个取值（人话，导入不读它）
STATE_ON = "是"
STATE_OFF = "否"

#: 文件名前缀（后接时间戳）。固定名字，不含用户输入，因此不需要清洗。
FILE_PREFIX = "我的词库备份_"

#: 导出目录里给用户看的目录名（与包根下那个目录同名，不另造一套）
EXPORT_DIR_NAME = "导出"

#: 导出后的说明文字：一条用途、一条边界。界面弹窗原样展示这段，
#: 不在这里拆成"标题 + 正文"两套说法。
EXPLANATION_TITLE = "这份备份用在哪、不能用来做什么"

EXPLANATION_POINTS: tuple[str, ...] = (
    "用在哪：换一台电脑接着用同一份「我的词库」，或者平时手动留个备份。",
    "怎么用：在新的机器上打开「导入预览」，选中这份文件，看清三组再确认写入。",
    "不能做什么：它不是双向编辑格式。改了这个文件再导入，语义以导入预览给出的"
    "三组为准——预览说冲突就是冲突，说格式不成立就不会写进去。",
    "也不能做什么：它只装「我的词库」这一层，出厂自带的词库不在里面，"
    "导入也不会动到出厂词库。",
    "留一分小心：若某条词条里本身就写着「【英文逗号】」这样的字样，"
    "读回来时无法与真正的逗号区分——原版导出也有同样的限制。",
)

#: 会被导入通道吃掉 / 认错的字符：值里出现就不能保证读回来一模一样。
#: (字符或字样, 人话原因)
BLOCKING_CHARS: tuple[tuple[str, str], ...] = (
    ("\t", "制表符——导入会把它当成分列符，一条词条会被切成两列"),
    ("\r", "回车——导入会把它当成换行，一条词条会被劈成两行"),
    ("\x00", "空字符——读回来时会被丢掉"),
)

#: 原版四个占位标记：值里本来就有这几个字时，还原会把它变成标点，无法区分。
LITERAL_MARKERS: tuple[str, ...] = (
    "【英文逗号】", "【英文单引号】", "【英文双引号】", "【换行符】",
)


class VocabExportError(Exception):
    """导出没能完成（原因已经写成用户能看懂的一句话）。"""

    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


@dataclass
class ExportOutcome:
    """一次导出的实测结果（界面与验收都读这个，不自己再数一遍）。"""

    path: Path
    count: int = 0                      # 写进文件的词条数
    disabled_count: int = 0             # 其中标记为「不参与校正」的条数
    bytes: int = 0
    sha256: str = ""
    stamp: str = ""

    def describe(self) -> dict:
        return dict(path=str(self.path), name=self.path.name, count=self.count,
                    disabled_count=self.disabled_count, bytes=self.bytes,
                    sha256=self.sha256, stamp=self.stamp)


@dataclass
class BackupRow:
    """从备份文件里读回来的一行（word / value / 类型 / 注音 / 状态 / 书籍）。"""

    line_no: int = 0
    word: str = ""
    value: str = ""
    typ: str = ""
    pinyin: str = ""
    enabled: bool | None = None          # None = 文件里没有这一列
    book: str = ""


@dataclass
class Unrepresentable:
    """一条装不进这份备份的词条：说清是哪条、哪个字段、为什么。"""

    id: int = 0
    word: str = ""
    where: str = ""                      # 字段名（人话）
    reason: str = ""

    def as_text(self) -> str:
        return f"「{self.word}」的{self.where}：{self.reason}"


# ---------------------------------------------------------------------------
# 能不能装得下
# ---------------------------------------------------------------------------

def _field_problem(text: str) -> str:
    """这段文本有没有会被导入通道吃掉 / 认错的字符；有就返回人话原因。"""
    for ch, why in BLOCKING_CHARS:
        if ch in text:
            return why
    for marker in LITERAL_MARKERS:
        if marker in text:
            return (f"本来就写着「{marker}」，读回来时会变回原符号，"
                    f"无法与真正的符号区分")
    for ch in text:
        code = ord(ch)
        if code == 0x0A:                        # 换行有标记可替，能原样读回
            continue
        if code < 0x20 or code == 0x7F:          # 其余控制字符：一律不装
            return "含有不可见的控制字符，读回来无法保证一模一样"
    return ""


def scan_unrepresentable(entries: Iterable[dict]) -> list[Unrepresentable]:
    """逐条检查能不能装进这份备份（只读，不改任何文件）。"""
    out: list[Unrepresentable] = []
    for e in entries:
        rid = int(e.get("id") or 0)
        word = str(e.get("word") or "")
        value = str(e.get("value") or "")
        typ = str(e.get("type") or "")
        pinyin = str(e.get("pinyin") or "")
        book = str(e.get("book") or "")
        for name, text in (("原词", word), ("替换为", value),
                           ("类型", typ), ("注音", pinyin), ("书籍", book)):
            why = _field_problem(text)
            if why:
                out.append(Unrepresentable(id=rid, word=word, where=name, reason=why))
        if not word.strip(" \t") or not value.strip(" \t"):
            out.append(Unrepresentable(
                id=rid, word=word, where="原词或替换为",
                reason="这一格是空的——空的词条导入时会被判为格式不成立"))
    return out


# ---------------------------------------------------------------------------
# 生成表格
# ---------------------------------------------------------------------------

def _escape_field(text: str) -> str:
    """把一个字段转成能安全放进一行里的样子（复用原版那套四个标记）。"""
    from fixtext_vocab_import.escape import escape_escaped

    return escape_escaped(text or "")


def build_table(entries: Sequence[dict], *, enabled_of=None) -> str:
    """把词条列表拼成整份表格文本（表头 + 每条一行）。

    :param enabled_of: 判断某条是否参与校正的回调，签名 ``(word, value) -> bool``；
                       不给就一律按参与校正写（只用于没有状态层的最小场景）。
    """
    lines = [",".join(EXPORT_HEADER)]
    for e in entries:
        word = str(e.get("word") or "")
        value = str(e.get("value") or "")
        on = True if enabled_of is None else bool(enabled_of(word, value))
        fields = [
            word, value, str(e.get("type") or ""), str(e.get("pinyin") or ""),
            STATE_ON if on else STATE_OFF, str(e.get("book") or ""),
        ]
        lines.append(",".join(_escape_field(f) for f in fields))
    return "\n".join(lines) + "\n"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _pick_target(out_dir: Path, stamp: str) -> Path:
    """选定目标文件名；同一秒重复导出顺延编号，绝不覆盖已有备份。"""
    base = f"{FILE_PREFIX}{stamp}"
    candidate = out_dir / f"{base}.csv"
    for step in range(2, 200):
        if not candidate.exists():
            return candidate
        candidate = out_dir / f"{base}_{step}.csv"
    return out_dir / f"{base}_{int(time.time())}.csv"


def _write_atomic(path: Path, text: str) -> None:
    """先写同目录临时文件再换名，避免留下半截备份。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.part"
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def export_custom_vocab(store, *, out_dir: str | Path | None = None,
                        when: str | None = None) -> ExportOutcome:
    """把「我的词库」这一层全量导出成一份备份文件。

    * ``store``：只需提供 ``custom.entries()`` 与 ``entry_enabled(word, value)``
      （``VocabStore`` 两者都有；本模块不碰出厂词库的写接口）；
    * ``out_dir``：不给就用包根下的 ``导出/``（与导出页同一个口径，不另造路径）；
    * ``when``：只给测试用，固定时间戳，便于断言文件名。

    :raises VocabExportError: 有词条装不下（会说清是哪几条、为什么）。
    """
    entries = list(store.custom.entries())
    if not entries:
        raise VocabExportError(
            "「我的词库」里还没有词条，没有可以导出的内容",
            detail=dict(count=0))

    bad = scan_unrepresentable(entries)
    if bad:
        shown = "；".join(u.as_text() for u in bad[:3])
        more = f"（另有 {len(bad) - 3} 处）" if len(bad) > 3 else ""
        raise VocabExportError(
            f"有 {len(bad)} 处内容无法原样读回来，先改掉再导出：{shown}{more}",
            detail=dict(count=len(bad), items=[u.as_text() for u in bad]))

    stamp = str(when) if when else time.strftime(HISTORY_STAMP_FORMAT)
    target_dir = Path(out_dir) if out_dir else default_export_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = _pick_target(target_dir, stamp)

    def _enabled(word: str, value: str) -> bool:
        try:
            return bool(store.entry_enabled(word, value))
        except Exception:                  # 状态层不可用时按"参与校正"写，不阻断导出
            return True

    text = build_table(entries, enabled_of=_enabled)
    try:
        _write_atomic(path, text)
    except OSError as exc:
        raise VocabExportError(
            "备份没能写进「导出」文件夹——可能没有写入权限，或者磁盘空间不够",
            detail=dict(errno=getattr(exc, "errno", 0), name=type(exc).__name__)) from exc

    disabled = sum(1 for e in entries
                   if not _enabled(str(e.get("word") or ""), str(e.get("value") or "")))
    return ExportOutcome(path=path, count=len(entries), disabled_count=disabled,
                         bytes=path.stat().st_size, sha256=_sha256_file(path),
                         stamp=stamp)


# ---------------------------------------------------------------------------
# 读回来：状态与书籍这两列（导入通道不带它们，所以单独读一遍）
# ---------------------------------------------------------------------------

def _header_index(headers: Sequence[str], name: str, fallback: int,
                  column_count: int) -> int | None:
    """按表头名找列号；表头被用户改掉了就退回固定位置（仍要求列数够）。"""
    try:
        return list(headers).index(name)
    except ValueError:
        return fallback if column_count > fallback else None


def read_backup(path: str | Path) -> list[BackupRow]:
    """把一份备份读成行清单：词条四字段走导入通道，状态与书籍走那两列。

    这条读法**不另写解析**：词条四字段直接取 D1 的映射结果，保证"读到什么"
    与"导入会写什么"是同一个口径；只有导入不认的那两列由这里按列号取。
    """
    from fixtext_vocab_import.escape import restore_escaped_once
    from fixtext_vocab_import.parse import parse_file

    sheet = parse_file(path)
    headers = list(sheet.headers or [])
    mapped_by_line = {r.line_no: r for r in sheet.mapped().rows}
    state_col = _header_index(headers, EXPORT_HEADER[4], 4, sheet.column_count)
    book_col = _header_index(headers, EXPORT_HEADER[5], 5, sheet.column_count)

    out: list[BackupRow] = []
    for line_no, fields in sheet.data_rows:
        row = mapped_by_line.get(line_no)
        if row is None:
            continue
        state = _cell(fields, state_col, restore_escaped_once)
        book = _cell(fields, book_col, restore_escaped_once)
        if state == STATE_OFF:
            enabled: bool | None = False
        elif state == STATE_ON:
            enabled = True
        else:
            enabled = None                 # 文件里没有这一列 / 值认不出
        out.append(BackupRow(line_no=line_no, word=row.word, value=row.value,
                             typ=row.typ, pinyin=row.pinyin, enabled=enabled,
                             book=book))
    return out


def _cell(fields: Sequence[str], idx: int | None, restore) -> str:
    if idx is None or idx >= len(fields):
        return ""
    return restore(fields[idx]).text.strip(" \t")


def restore_backup_state(store, rows: Sequence[BackupRow] | None = None,
                         *, path: str | Path | None = None) -> dict:
    """导入写完之后，把「不参与校正」这一状态补回去（**词条内容不再改**）。

    为什么补在导入之后：导入通道（D1–D6）只带词条四字段，不带启用状态；
    状态在新机器上是由 ``VocabStore`` 单独记的。这里走它的公开写入口，
    所以同样留还原点、同样可撤销。

    「书籍」这一列只读回、不写回：导入通道没有这个字段，写它需要改数据层的
    公开接口（属别的卡），本卡不越界——读回来放在返回值里，供后续人工核对。
    """
    if rows is None:
        if path is None:
            return dict(disabled_applied=0, book_rows=0, book_restored=False)
        rows = read_backup(path)

    pairs = [(r.word, r.value) for r in rows if r.enabled is False]
    applied = 0
    if pairs:
        result = store.set_entries_enabled(pairs, enabled=False)
        applied = int(result.get("changed") or 0)
    book_rows = sum(1 for r in rows if r.book)
    return dict(disabled_applied=applied, book_rows=book_rows,
                book_restored=False, rows=len(rows))


def explanation_text() -> str:
    """说明文字的整段（弹窗原样展示，测试也断言这一份）。"""
    return "\n".join(EXPLANATION_POINTS)


def summary_text(outcome: ExportOutcome) -> str:
    """导出成功后的那句人话（只给文件名，不出任何目录路径）。"""
    head = f"已导出 {outcome.count} 条词条：{outcome.path.stem}"
    if outcome.disabled_count:
        head += f"（其中 {outcome.disabled_count} 条标着不参与校正）"
    return head + f"，放在「{EXPORT_DIR_NAME}」文件夹里。"
