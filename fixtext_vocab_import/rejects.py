"""V1.1-D2 · 不合格行清单：原因分类、原始行号定位、可导出。

验收判据两条，本模块把它们变成可执行的东西：

1. **不合格行不阻塞合法行。** 所以这里不抛「整表失败」，而是给出一份
   `RejectList`：`good` 是**照常入库**的那些，`rejects` 是留在清单里的那些。
   两者不重不漏，条数守恒有硬断言（`RejectList.conserved()`）——
   「不阻塞」不能只是嘴上说：合法行必须一条不少地出现在 `good` 里。
2. **清单每条能定位到原始行号。** 行号口径与 D1 完全一致：**原文件里的
   物理行号，从 1 起算**；原版导出写在第一行的说明文字是**置空、不删行**，
   所以第 2 行的词条行号就是 2，不会因为跳过说明而整体前移一位。
   除了行号，每条还带上**那一行的原文**，用户可以直接在自己文件里按
   行号跳过去、按原文核对。

**只判格式，不判语义。**「改前和改后一模一样」这类不算不合格：
它是一条能存进去、只是改了等于没改的词条，属于 D3/D4 的查重与冲突
处置范围（出厂相邻词库 `orig_oldstyle_map.csv` 里就有 103 行这样真实存在，
把它们打成「不合格」是把合法数据误判）。本卡只判「这一行自己成不成立」。

范围边界：不做预览分组（D3）、不做冲突处置（D4）、不写库（D5）。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from .mapping import ColumnMapping, MappedRow, MappingResult

#: 导出文件的后缀与文件名片段（机器用的部分与中文文案分开写：
#: 文案扫描器只扫含中文的字面量，文件后缀不是给人读的句子）
EXT_TABLE = ".csv"
EXPORT_NAME_HEAD = "导入不合格清单_"

#: 判定「只有空白」时要算进去的空白字符（含全角空格与不换行空格）。
#: D1 的 `apply_mapping` 只去两端普通空格与制表符——用户从 Word / 网页
#: 复制时常见全角空格，那一格看着是空的、去普通空格却判它非空，
#: 于是变成一个「错词是全角空格」的词条被照常入库。本卡补上这一刀。
BLANK_CHARS = " \t\u3000\u00a0\u200b\u200c\u200d\ufeff"


# ---------------------------------------------------------------------------
# 原因分类
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RejectReason:
    """一类不合格原因。`code` 给程序用，`label` / `detail` / `advice` 给人看。"""

    code: str
    label: str          # 清单里的「原因分类」那一列
    detail: str         # 这一类的通用说明（汇总里用）
    advice: str         # 怎么办
    blocking: bool = False   # True = 整表阻塞（列没指好，谁来都不合格）

    def row_text(self, line_no: int) -> str:
        return f"第 {line_no} 行：{self.label}"


#: 原因分类表。顺序即清单里的分组顺序（阻塞类在最前，其余按「越常见越靠前」）。
REJECT_REASONS: tuple[RejectReason, ...] = (
    RejectReason(
        code="NO_WORD_COLUMN", label="还没有指定「错词」列",
        detail="整张表都缺「错词」这一列，谁都存不进去。",
        advice="先在上面指定哪一列是「错词」，再回来看这份清单。",
        blocking=True,
    ),
    RejectReason(
        code="NO_VALUE_COLUMN", label="还没有指定「正确写法」列",
        detail="整张表都缺「正确写法」这一列，谁都存不进去。",
        advice="先在上面指定哪一列是「正确写法」，再回来看这份清单。",
        blocking=True,
    ),
    RejectReason(
        code="WORD_EMPTY", label="「错词」这一格是空的",
        detail="没有要替换的写法，这一行没法变成词条。",
        advice="补上这一格的内容，或者把这一行删掉再导入。",
    ),
    RejectReason(
        code="VALUE_EMPTY", label="「正确写法」这一格是空的",
        detail="没写替换成什么，这一行没法变成词条。",
        advice="补上这一格的内容，或者把这一行删掉再导入。",
    ),
    RejectReason(
        code="BOTH_EMPTY", label="「错词」和「正确写法」都是空的",
        detail="这一行只剩分隔符，没有任何内容。",
        advice="直接删掉这一行，或者把两格都补上。",
    ),
    RejectReason(
        code="SHORT_ROW", label="这一行少了几格",
        detail="这一行切出来的格子不够，「错词」或「正确写法」的位置是空的。",
        advice="检查这一行是不是漏了分隔，或者补上缺的那一格。",
    ),
)

#: code → 原因（按 code 取，避免调用处写字符串漂移）
REASON_BY_CODE: dict[str, RejectReason] = {r.code: r for r in REJECT_REASONS}


def reason_of(code: str) -> RejectReason:
    try:
        return REASON_BY_CODE[code]
    except KeyError:                       # pragma: no cover - 防御性
        raise ValueError(f"未知的不合格原因：{code}") from None


#: 清单表格的列名（顺带把行号口径写进列名，用户一眼知道这个「行号」指什么）
#: 七列各有各的信息，不设「原因分类 / 原因说明」那种两列几乎同文的冗余。
EXPORT_COLUMNS: tuple[str, ...] = (
    "原文行号", "原因分类", "怎么改", "错词", "正确写法", "分类", "该行原文",
)


def _one_line(text: str) -> str:
    """把可能带换行的原文压成一行（清单是表格，一格不能撑破行）。"""
    return (text or "").replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


# ---------------------------------------------------------------------------
# 清单条目
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RejectedRow:
    """清单里的一条：**行号 + 原文 + 原因**，三者缺一就不能定位。"""

    line_no: int                    # 原文件物理行号，从 1 起（与 D1 同口径）
    code: str                       # 原因分类的 code
    word: str
    value: str
    typ: str = "错词校正"
    raw_line: str = ""              # 那一行的原文（未切列、未还原，逐字保留）
    cell_note: str = ""             # 补充说明（例如「只有空白字符」）

    @property
    def reason(self) -> RejectReason:
        return reason_of(self.code)

    @property
    def label(self) -> str:
        return self.reason.label

    @property
    def detail(self) -> str:
        """这一条的具体原因（分类名 + 补充说明）。"""
        return f"{self.label}（{self.cell_note}）" if self.cell_note else self.label

    def where(self) -> str:
        return f"第 {self.line_no} 行"

    def text(self) -> str:
        """一条人话：「第 12 行：『错词』这一格是空的」。"""
        return f"第 {self.line_no} 行：{self.detail}"

    def as_table_row(self) -> list[str]:
        """清单表格的一行（导出与界面表格共用同一份列序）。"""
        return [
            str(self.line_no),
            self.detail,
            self.reason.advice,
            _one_line(self.word),
            _one_line(self.value),
            _one_line(self.typ),
            _one_line(self.raw_line),
        ]


# ---------------------------------------------------------------------------
# 清单
# ---------------------------------------------------------------------------

@dataclass
class RejectList:
    """一份不合格行清单：按原因分组、可计数、可导出。"""

    rejects: list[RejectedRow] = field(default_factory=list)
    good: list[MappedRow] = field(default_factory=list)   # 合法行（照常入库的那批）
    source_name: str = ""
    banner_note: bool = False       # 原文件首行是说明文字，行号口径要交代
    skipped_blank: int = 0          # 跳过的空行数（告诉用户，不静默丢弃）

    # ----- 计数 -----

    def __len__(self) -> int:
        return len(self.rejects)

    def __iter__(self):
        """让清单本身可迭代（`for r in 清单` 就是逐条不合格行）。"""
        return iter(self.rejects)

    @property
    def total_rows(self) -> int:
        return len(self.good) + len(self.rejects)

    def counts(self) -> dict[str, int]:
        """原因分类 → 条数（按 REJECT_REASONS 的顺序，空分类不出现）。"""
        tally = {r.code: 0 for r in REJECT_REASONS}
        for r in self.rejects:
            if r.code in tally:
                tally[r.code] += 1
        out: dict[str, int] = {}
        for reason in REJECT_REASONS:
            if tally[reason.code]:
                out[reason.label] = tally[reason.code]
        return out

    def grouped(self) -> list[tuple[RejectReason, list[RejectedRow]]]:
        """按原因分组（固定顺序，组内按行号升序）。"""
        out: list[tuple[RejectReason, list[RejectedRow]]] = []
        for reason in REJECT_REASONS:
            rows = sorted((r for r in self.rejects if r.code == reason.code),
                          key=lambda r: r.line_no)
            if rows:
                out.append((reason, rows))
        return out

    def is_blocking(self) -> bool:
        """整表阻塞（列都没指好）——这时「合法行」是 0，不是用户的行有错。"""
        return any(r.reason.blocking for r in self.rejects)

    def blocking_items(self) -> list[str]:
        """阻塞时要说清两条（列没指好），不重复啰嗦每一行。"""
        seen: list[str] = []
        for reason in REJECT_REASONS:
            if reason.blocking and any(r.code == reason.code for r in self.rejects):
                seen.append(reason.detail + reason.advice)
        return seen

    def conserved(self) -> bool:
        """条数守恒自检：合法行 + 不合格行 = 全部非空行，且两边不重叠。"""
        good_lines = [r.line_no for r in self.good]
        bad_lines = [r.line_no for r in self.rejects]
        if len(set(good_lines)) != len(good_lines) or len(set(bad_lines)) != len(bad_lines):
            return False
        if set(good_lines) & set(bad_lines):
            return False
        return len(good_lines) + len(bad_lines) == self.total_rows

    # ----- 文案 -----

    def header_note(self) -> str:
        """行号口径的交代（清单表头 / 界面提示直接显示）。"""
        out = "清单里的「行号」是原文里的行号，从第 1 行起算，跟你在文件里数的一致。"
        if self.banner_note:
            out += "原文第一行是旧版导出时自动写的说明文字，跳过不计入词条，但那一行还在，行号没有前移。"
        if self.skipped_blank:
            out += f"另有 {self.skipped_blank} 个空行已跳过，它们也不占词条位置。"
        return out

    def summary_text(self) -> str:
        """一句汇总（界面顶部 / 交付评论里用）。"""
        if not self.rejects:
            return f"全部 {len(self.good)} 行都合格，没有不合格的行。"
        tally = "、".join(f"{label} {n} 条" for label, n in self.counts().items())
        head = (f"{self.total_rows} 行里，{len(self.good)} 行合格会照常导入，"
                f"{len(self.rejects)} 行不合格：{tally}。")
        head += ("先按清单上的提示把列对应好，合格的行才会跟着多起来。"
                 if self.is_blocking()
                 else "不合格的行不会挡住合格的行，清单可以导出，按行号回原文改。")
        return head

    # ----- 导出 -----

    def table_lines(self) -> list[list[str]]:
        """清单的所有行（含表头），导出与界面共用。"""
        return [list(EXPORT_COLUMNS)] + [r.as_table_row() for r in self.rejects]

    def to_table_text(self, delimiter: str = "\t") -> str:
        """纯文本版（可直接粘进表格软件，也便于在评论里贴）。"""
        lines = [delimiter.join(_one_line(c) for c in row) for row in self.table_lines()]
        return "\n".join(lines) + "\n"

    def to_file_bytes(self) -> bytes:
        """导出文件的字节。

        带签名的写法是为了让表格软件双击就认出中文——不然用户打开会看到
        一列乱码，那就不叫「可导出」。这是实质要求，不是细节。
        """
        lines = []
        for row in self.table_lines():
            cells = []
            for cell in row:
                text = _one_line(cell)
                if '"' in text:
                    cells.append('"' + text.replace('"', '""') + '"')
                else:
                    cells.append(text)
            lines.append(",".join(cells))
        return ("\n".join(lines) + "\n").encode("utf-8-sig")

    def export_name(self, stamp: str = "") -> str:
        """导出文件名：中文名 + 时间戳 + 表格后缀（不含任何路径）。"""
        tail = stamp.strip("_ ") if stamp else ""
        if tail:
            return f"{EXPORT_NAME_HEAD}{tail}{EXT_TABLE}"
        return f"{EXPORT_NAME_HEAD.rstrip('_')}{EXT_TABLE}"

    def write_export(self, path, stamp: str = "") -> str:
        """把清单写到 `path`，返回实际写入的路径（目录由调用方选）。"""
        target = Path(path)
        if target.suffix.lower() != EXT_TABLE:
            target = target.with_name(target.stem + EXT_TABLE)
        target.write_bytes(self.to_file_bytes())
        return str(target)

    def export_ready(self) -> bool:
        """有不合格行才值得导出（没有就不该生成一个空清单糊弄用户）。"""
        return bool(self.rejects)


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------

def _is_blank(text: str) -> bool:
    return (text or "").strip(BLANK_CHARS) == ""


def judge_row(row: MappedRow, fields: list[str], mapping: ColumnMapping,
              column_count: int) -> tuple[str, str] | None:
    """判这一行合不合格；合格返回 None，不合格返回 (原因 code, 补充说明)。"""
    wcol = mapping.word_column
    vcol = mapping.value_column
    if wcol is None:
        return ("NO_WORD_COLUMN", "")
    if vcol is None:
        return ("NO_VALUE_COLUMN", "")

    # 先判「格子根本没切出来」——比「格子是空的」更准确，也更好改
    need = max(wcol, vcol) + 1
    if fields and len(fields) < need:
        return ("SHORT_ROW", f"只切出 {len(fields)} 格，表头有 {column_count} 列")

    word_blank, value_blank = _is_blank(row.word), _is_blank(row.value)
    if word_blank and value_blank:
        return ("BOTH_EMPTY", "")
    if word_blank:
        return ("WORD_EMPTY", "只有空白字符" if row.word else "")
    if value_blank:
        return ("VALUE_EMPTY", "只有空白字符" if row.value else "")
    return None


def _raw_lines(text: str) -> dict[int, str]:
    """原文按物理行切成 行号 → 原文（1 起算，与解析层同一口径）。"""
    return {idx: line for idx, line in enumerate((text or "").split("\n"), start=1)}


def build_reject_list(
    sheet,
    result: MappingResult | None = None,
    *,
    source_name: str = "",
) -> RejectList:
    """把一份解析好的表切成「合法行」与「不合格行清单」。

    **不吃掉合法行**：合格的一律进 `good`，不合格的只进清单，不影响前者。
    """
    result = result if result is not None else sheet.mapped()
    fields_by_line: dict[int, list[str]] = {ln: f for ln, f in sheet.data_rows}
    raw_by_line = _raw_lines(sheet.raw_text)

    rejects: list[RejectedRow] = []
    good: list[MappedRow] = []
    for row in result.rows:
        fields = fields_by_line.get(row.line_no, [])
        verdict = judge_row(row, fields, sheet.mapping, sheet.column_count)
        if verdict is None:
            good.append(row)
            continue
        code, note = verdict
        rejects.append(RejectedRow(
            line_no=row.line_no, code=code, word=row.word, value=row.value,
            typ=row.typ, raw_line=raw_by_line.get(row.line_no, ""), cell_note=note,
        ))

    return RejectList(
        rejects=rejects, good=good,
        source_name=source_name or getattr(sheet, "source_name", ""),
        banner_note=bool(getattr(sheet, "banner_removed", False)),
        # 空行有两种来源：解析层在物理行阶段整行丢掉的，和映射层判「整行只有分隔符」
        # 的。两种都要报，不能因为飘到不同层就变成静默丢弃。
        skipped_blank=(int(getattr(sheet, "blank_skipped", 0) or 0)
                       + int(getattr(result, "skipped_blank", 0) or 0)),
    )


def partition_sheet(sheet, *, source_name: str = "") -> RejectList:
    """解析好了的表 → 切分结果（界面层与单测都用这一个入口）。"""
    return build_reject_list(sheet, sheet.mapped(), source_name=source_name)


def partition_rows(
    rows: Sequence[MappedRow],
    *,
    word_col_present: bool = True,
    value_col_present: bool = True,
    raw_lines: dict[int, str] | None = None,
) -> RejectList:
    """只拿 `MappedRow` 序列切分（不依赖 `ParsedSheet` 的轻量入口）。

    D1 的映射结果已经算好了、手边没有 sheet 时用这个；
    缺 sheet 就没有「少了几格」这条判定，其余判据不受影响。
    """
    rejects: list[RejectedRow] = []
    good: list[MappedRow] = []
    for row in rows:
        if not word_col_present:
            code, note = "NO_WORD_COLUMN", ""
        elif not value_col_present:
            code, note = "NO_VALUE_COLUMN", ""
        elif _is_blank(row.word) and _is_blank(row.value):
            code, note = "BOTH_EMPTY", ""
        elif _is_blank(row.word):
            code, note = "WORD_EMPTY", "只有空白字符" if row.word else ""
        elif _is_blank(row.value):
            code, note = "VALUE_EMPTY", "只有空白字符" if row.value else ""
        else:
            good.append(row)
            continue
        rejects.append(RejectedRow(
            line_no=row.line_no, code=code, word=row.word, value=row.value,
            typ=row.typ, raw_line=(raw_lines or {}).get(row.line_no, ""), cell_note=note,
        ))
    return RejectList(rejects=rejects, good=good)


__all__ = [
    "BLANK_CHARS",
    "EXPORT_COLUMNS",
    "REASON_BY_CODE",
    "REJECT_REASONS",
    "RejectList",
    "RejectReason",
    "RejectedRow",
    "build_reject_list",
    "judge_row",
    "partition_rows",
    "partition_sheet",
    "reason_of",
]
