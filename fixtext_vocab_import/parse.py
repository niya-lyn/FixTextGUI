"""V1.1-D1 · 解析主入口：粘贴通道 + 文件通道。

管线顺序（**顺序本身就是设计**，每一步都有测试守着）：

    ① 取内容（粘贴：直接用；文件：识别字符集后读出来）
    ② 去掉文件头标记（BOM）与行尾空白
    ③ 按物理行切分（原版导出的一行就是一条词条，跨行字段已被转成标记）
    ④ 判分隔符（按列数一致性投票，不是猜）
    ⑤ 切列（**先切列**）
    ⑥ 认表头（只在"看起来像表头"时跳过第一行）
    ⑦ 列映射 + **切完之后**才还原占位标记
    ⑧ 逐行给出人话原因

④→⑤→⑦ 的顺序是最容易做错的地方：**先还原再切列**会让值里的逗号
变成列边界；**先切列再还原**才对（原版 `Csv.php` 也是这个顺序）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import dialect, messages as msg
from .escape import restore_escaped_once
from .mapping import ColumnMapping, MappingResult, apply_mapping

#: 文件通道接受的扩展名（人话里也用它来说明"能拖什么"）
TABLE_SUFFIXES: tuple[str, ...] = (".csv", ".txt", ".tsv", ".tab", ".dat", "")

#: 一次能读的最大体积（超了走人话拒绝，不硬啃内存）
MAX_FILE_BYTES = 64 * 1024 * 1024

#: 表头判定的采样行数
HEADER_SAMPLE_ROWS = 5

ParseError = msg.ParseProblem            # 对外只暴露这一个异常类型


@dataclass
class ParsedSheet:
    """一份解析好、可直接进预览的候选表。"""

    raw_text: str = ""
    delimiter: str | None = None
    delimiter_name: str = ""
    delimiter_evidence: list[str] = field(default_factory=list)
    headers: list[str] | None = None
    header_skipped: bool = False
    column_count: int = 0
    data_rows: list[tuple[int, list[str]]] = field(default_factory=list)
    mapping: ColumnMapping = field(default_factory=lambda: ColumnMapping())
    messages: msg.ImportMessages = field(default_factory=msg.ImportMessages)
    encoding_label: str = ""
    encoding_certain: bool = True
    source: str = "paste"                # paste | file
    source_name: str = ""

    # ----- 供预览 / D2 使用 -----

    @property
    def row_count(self) -> int:
        return len(self.data_rows)

    def mapped(self) -> MappingResult:
        """按当前映射套出候选词条（改映射后可反复调用，不必重解析）。"""
        return apply_mapping(self.data_rows, self.mapping)

    def problems(self) -> list[str]:
        return self.mapping.problems()

    def is_ready(self) -> bool:
        return self.mapping.is_ready() and self.row_count > 0

    def set_mapping(self, mapping: ColumnMapping) -> None:
        """改列映射——这是"错配时可纠正"的唯一入口（不重解析）。"""
        if len(mapping) != self.column_count:
            raise ValueError("列指派数量与这份表的列数不一致")
        self.mapping = mapping


# ---------------------------------------------------------------------------
# ③–⑥ 共用：从「已经解好编码的文本」到「已切列的原始行」
# ---------------------------------------------------------------------------

def _normalize_newlines(text: str) -> str:
    """统一行尾；同时吃掉 BOM 留下的不可见字符。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # UTF-8 BOM 若已被解码成字符（utf-8 而非 utf-8-sig），这里兜一层
    return text.replace("\ufeff", "")


#: 原版导出 CSV 时写在第一行的说明文字（`Csv.php:41` 的原文，逐字对照）。
#: 它自己就含一个真逗号，会让第一行切出 3 列，把整表列数一致性拉低。
_ORIG_BANNER_PREFIX = "【英文逗号】【英文单引号】【英文双引号】【换行符】"
_ORIG_BANNER_KEYWORD = "转成了以【】包裹的特殊标记"


def _strip_orig_banner(text: str) -> tuple[str, bool]:
    """去掉原版导出文件第一行的说明文字。

    判定要**两个特征同时命中**（开头四个标记连排 + 说明语），
    否则一条恰好以标记开头的真实词条会被误删。

    做法是把那一行**置空**而不是删掉——这样后面每一条的行号
    仍与原文件一致（D2 的不合格清单要靠行号让用户回到原文定位）。

    :return: (说明文字被置空后的文本, 是否确实处理过)
    """
    lines = text.split("\n")
    if not lines:
        return text, False
    first = lines[0].strip()
    if not first.startswith(_ORIG_BANNER_PREFIX):
        return text, False
    if _ORIG_BANNER_KEYWORD not in first:
        return text, False
    lines[0] = ""
    return "\n".join(lines), True


def _physical_lines(text: str) -> list[tuple[int, str]]:
    """按物理行切分，保留**原始行号**（D2 的不合格清单要靠它定位）。"""
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(text.split("\n"), start=1):
        if line.strip() == "":
            continue                       # 空行不参与解析，但行号仍然按原文计
        out.append((idx, line.rstrip("\t ")))
    return out


def _looks_like_header(fields: list[str], following: Sequence[list[str]]) -> bool:
    """判断这一行是不是表头。

    三个信号，命中两个、且第一格明显不是词条时才认：
    ① 某个格子含表头字样（错词 / 原文 / 正确写法 / 分类 …）；
    ② 这一行**没有任何**原版占位标记（表头是办公软件写的，不是原版导出的）；
    ③ 后续行的第一格与本行第一格"长得不像"（表头是描述词，词条是内容）。
    """
    from .mapping import _match_header        # 复用同一套表头字样

    if not fields:
        return False
    signals = 0

    # ① 至少一格像表头字样
    if any(_match_header(f) is not None for f in fields):
        signals += 1
    else:
        return False                            # 没有这个信号直接判否，避免误伤

    # ② 这一行不含原版占位标记
    if not any(_contains_marker(f) for f in fields):
        signals += 1

    # ③ 后续行的第一格不像本行第一格（表头是"描述"，数据是"内容"）
    first = fields[0].strip()
    if first and following:
        same_first = sum(1 for row in following if row and row[0].strip() == first)
        if same_first == 0:
            signals += 1

    return signals >= 2


def _contains_marker(text: str) -> bool:
    from .escape import contains_escaped_markers
    return contains_escaped_markers(text)


def _split_all(lines: list[tuple[int, str]], delimiter: str | None,
               quote_aware: bool) -> list[tuple[int, list[str]]]:
    """切列。**未还原占位标记**——还原一定要等切完。"""
    out: list[tuple[int, list[str]]] = []
    for line_no, line in lines:
        if delimiter is None:
            out.append((line_no, [line]))
        else:
            out.append((line_no, dialect._split_line(line, delimiter, quote_aware)))
    return out


def _build_sheet(
    text: str,
    *,
    source: str,
    source_name: str = "",
    encoding_label: str = "",
    encoding_certain: bool = True,
    allow_single_column_value_fill: bool = False,
) -> ParsedSheet:
    """把一段已知编码的文本做成 `ParsedSheet`（两条通道共用）。"""
    text = _normalize_newlines(text)
    if not text.strip():
        raise msg.empty_input()

    # 原版导出的第一行是它自己的说明文字，先置空（行号保持不变）
    text, banner_removed = _strip_orig_banner(text)

    guess = dialect.guess_delimiter(text)
    lines = _physical_lines(text)
    if not lines:
        raise msg.empty_input()

    rows = _split_all(lines, guess.delimiter, guess.quote_aware)

    # 列数：取众数（与分隔符判定一致），并保证至少 1
    column_count = max((len(f) for _ln, f in rows), default=1) if guess.delimiter is None \
        else max(guess.column_count, max((len(f) for _ln, f in rows), default=1))

    # 表头判定（只在前几行里找，且**不能吃掉唯一的行**）
    headers: list[str] | None = None
    header_skipped = False
    if len(rows) > 1:
        sample_following = [f for _ln, f in rows[1:1 + HEADER_SAMPLE_ROWS]]
        if _looks_like_header(rows[0][1], sample_following):
            headers = [f.strip() for f in rows[0][1]]
            header_skipped = True
            data_rows = rows[1:]
        else:
            data_rows = rows
    else:
        data_rows = rows

    mapping = ColumnMapping.suggested(headers, column_count)

    notes = msg.ImportMessages()
    notes.headline = msg.parsed_ok(len(data_rows), column_count).headline
    notes.details.append(msg.delimiter_note(dialect.delimiter_name(guess.delimiter)))
    if header_skipped and headers:
        notes.details.append(msg.header_detected(headers))
    else:
        notes.details.append(msg.header_absent())
    notes.details.append(msg.mapping_suggested(mapping.describe()))
    if banner_removed:
        notes.details.append(msg.banner_note())
    if guess.delimiter is None:
        notes.details.append(msg.single_column_note())
    notes.details.extend(guess.evidence)

    return ParsedSheet(
        raw_text=text,
        delimiter=guess.delimiter,
        delimiter_name=dialect.delimiter_name(guess.delimiter),
        delimiter_evidence=list(guess.evidence),
        headers=headers,
        header_skipped=header_skipped,
        column_count=column_count,
        data_rows=data_rows,
        mapping=mapping,
        messages=notes,
        encoding_label=encoding_label,
        encoding_certain=encoding_certain,
        source=source,
        source_name=source_name,
    )


# ---------------------------------------------------------------------------
# 粘贴通道
# ---------------------------------------------------------------------------

def parse_text(text: str) -> ParsedSheet:
    """解析**从 Excel / 在线表格复制**出来的文本。

    这类文本的特点：以制表符分列、以换行分行、**不含原版占位标记**
    （原版导出走的是文件通道）。但用户也可能把原版导出的 CSV 内容
    整段粘进来，所以还原逻辑照旧保留。

    :raises ParseError: 内容为空、或完全无法成列
    """
    if text is None:
        raise msg.empty_input()
    sheet = _build_sheet(text, source="paste")
    if sheet.column_count >= 2 and not sheet.data_rows:
        raise msg.no_columns()
    return sheet


# ---------------------------------------------------------------------------
# 文件通道
# ---------------------------------------------------------------------------

def parse_file(path: str | Path) -> ParsedSheet:
    """解析拖进来的表格 / 文本文件。

    编码识别直接复用导入链路已交付的那一层
    （`fixtext_import/encoding.py`：BOM → 纯英文 → 严格解码 → 可读性仲裁），
    因为那层已经用真实语料验证过 GBK / GB18030 / Big5 的区分，
    本卡再造一份只会引入两套不一致的判定。

    :raises ParseError: 文件不存在、体积超限、类型不支持、内容读不出、无法成列
    """
    p = Path(path)
    name = p.name

    try:
        if not p.exists():
            raise msg.file_missing(name)
        if p.is_dir():
            raise msg.not_a_table_file("文件夹")
        size = p.stat().st_size
    except msg.ParseProblem:
        raise
    except OSError as exc:
        raise msg.ParseProblem(msg.human_error(exc)) from None

    if size > MAX_FILE_BYTES:
        raise msg.file_too_big(size / (1024 * 1024), MAX_FILE_BYTES / (1024 * 1024))

    suffix = p.suffix.lower()
    if suffix not in TABLE_SUFFIXES:
        raise msg.not_a_table_file(suffix or "无扩展名")

    if size == 0:
        raise msg.empty_input()

    try:
        from fixtext_import.encoding import decode_file, probe
    except Exception:                      # pragma: no cover - 极端环境缺依赖
        raise msg.unreadable_text("这份内容需要先确认它的字符写法") from None

    try:
        probe_result = probe(p)
    except OSError as exc:
        raise msg.ParseProblem(msg.human_error(exc)) from None

    try:
        text = decode_file(p, probe_result.codec, errors="replace")
    except (UnicodeError, OSError) as exc:
        raise msg.unreadable_text(msg.human_error(exc)) from None

    # 兜底：若解码结果可读性很差且文件并非空，明确说"读不出来"而不是硬读
    from fixtext_import.encoding import text_plausibility
    if text_plausibility(text[:20000]) < 0.35:
        raise msg.unreadable_text(
            "换了几种常见的中文写法，读出来的内容都不像正常的文字"
        )

    sheet = _build_sheet(
        text, source="file", source_name=name,
        encoding_label=probe_result.label,
        encoding_certain=probe_result.certain,
    )
    if not sheet.data_rows:
        raise msg.no_columns()
    return sheet
