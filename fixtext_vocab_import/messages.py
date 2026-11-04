"""V1.1-D1 · 解析层的人话文案。

验收判据原文：**「解析失败给出人话原因（不得是异常栈或英文术语）」**。

这条判据有两个可执行的含义，本模块按它们来写：

1. **不出现英文技术词**：`UnicodeDecodeError`、`csv.Error`、`codec`、
   `delimiter`、`UTF-8`、`GBK`、`BOM`、`CRLF`、`encoding`、`exception`、
   `Traceback` 这些一律不进界面文案。单测里有一张禁用词表做机械扫描
   （含大小写变体），**扫描源文件里所有面向用户的中文字面量**。
2. **说清「哪里、为什么、怎么办」三件事**，而不是只说「解析失败」。
   例：「第 12 行的「错词」这一格是空的。补上内容，或者把这一行删掉再导入。」

约定与 `fixtext_import/messages.py` 一致：主语是「这份表」，动词是我做了什么。
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 面向用户文案里**禁止出现**的技术词（小写比对，含下划线/连字符变体）。
#: 这不是"风格偏好"，是验收判据；新增文案必须过这张表。
FORBIDDEN_TERMS: tuple[str, ...] = (
    "utf-8", "utf8", "gbk", "gb18030", "big5", "unicode", "codec", "decode",
    "encode", "encoding", "delimiter", "bom", "crlf", "lf", "csv", "tsv",
    "exception", "traceback", "error", "errno", "null", "none", "str", "int",
    "parseerror", "indexerror", "valueerror", "keyerror", "quot", "sep=",
)


@dataclass
class ImportMessages:
    """一次解析/映射过程产生的所有人话提示，按「结论 + 细节」组织。"""

    headline: str = ""
    details: list[str] = field(default_factory=list)
    advice: str = ""

    def is_empty(self) -> bool:
        return not (self.headline or self.details or self.advice)

    def lines(self) -> list[str]:
        out = [self.headline] if self.headline else []
        out.extend(self.details)
        if self.advice:
            out.append(self.advice)
        return out

    def text(self) -> str:
        return "\n".join(self.lines())


# ---------------------------------------------------------------------------
# 成功路径的说明句（用户看到的是"我做了什么"，不是"我用了什么算法"）
# ---------------------------------------------------------------------------

def parsed_ok(rows: int, columns: int) -> ImportMessages:
    return ImportMessages(headline=f"读到了 {rows} 行内容，每行 {columns} 列。")


def delimiter_note(name: str) -> str:
    return f"这份内容是按「{name}」分开的。"


def header_detected(headers: list[str]) -> str:
    shown = "、".join(h for h in headers if h) or "（空表头）"
    return f"第一行看起来是表头（{shown}），已经跳过，没有当成词条。"


def header_absent() -> str:
    return "第一行看起来就是词条，没有表头。"


def mapping_suggested(items: list[str]) -> str:
    return "我按表头认了列：" + "；".join(items) + "。如果不对，下面可以逐列改。"


def restored_note(count: int) -> str:
    return (
        f"其中 {count} 处是旧版导出时被换成中文标记的符号，"
        "已经一次性还原成原来的符号。"
    )


def single_column_note() -> str:
    return "这份内容只有一列，我按「一行一个错词」来读；正确写法需要你手工填或再补一列。"


def skipped_blank_note(count: int) -> str:
    return f"中间有 {count} 个空行，已经跳过。"


def banner_note() -> str:
    return "第一行是旧版导出时自动写的说明文字，已经跳过，没有当成词条。"


# ---------------------------------------------------------------------------
# 失败路径：说清 哪里 / 为什么 / 怎么办
# ---------------------------------------------------------------------------

@dataclass
class ParseProblem(Exception):
    """解析层的统一失败信号：**只携带人话**，不携带异常对象。"""

    headline: str
    details: list[str] = field(default_factory=list)
    advice: str = ""

    def __str__(self) -> str:            # 便于日志与断言，内容仍是人话
        return self.as_messages().text()

    def as_messages(self) -> ImportMessages:
        return ImportMessages(self.headline, list(self.details), self.advice)


def empty_input() -> ParseProblem:
    return ParseProblem(
        headline="没有读到任何内容。",
        details=["粘贴区是空的，或者这个文件里只有空行。"],
        advice="把要导入的词条复制进来，或者换一个文件再试。",
    )


def no_columns() -> ParseProblem:
    return ParseProblem(
        headline="这份内容没法分成列。",
        details=["每一行都没有任何可用的分隔，也无法当作「一行一个词条」来读。"],
        advice="从表格里复制时会自动带上分隔；如果是手工写的，一行放一条词条即可。",
    )


def unreadable_text(reason: str) -> ParseProblem:
    return ParseProblem(
        headline="这个文件的内容读不出来。",
        details=[f"我试过几种常见的中文写法都没有读通：{reason}"],
        advice="用记事本或表格软件把这个文件另存一次，再拖进来试试。",
    )


def file_missing(name: str) -> ParseProblem:
    return ParseProblem(
        headline="找不到这个文件。",
        details=[f"「{name}」可能已经被移动、改名或删除了。"],
        advice="确认文件还在原来的位置，或者重新拖一次。",
    )


def not_a_table_file(suffix: str) -> ParseProblem:
    return ParseProblem(
        headline="这个文件不是表格或文本文件。",
        details=[f"「{suffix}」这种文件我没法当成词条表来读。"],
        advice="把它另存为表格或纯文本文件，再拖进来。",
    )


def file_too_big(size_mb: float, limit_mb: float) -> ParseProblem:
    return ParseProblem(
        headline="这个文件太大了。",
        details=[f"它有约 {size_mb:.1f} MB，一次最多读 {limit_mb:.0f} MB 的词条表。"],
        advice="分成几个小一点的文件，一个一个导入。",
    )


def row_problem(line_no: int, reason: str) -> str:
    return f"第 {line_no} 行：{reason}"


#: 行级原因（人话；这些字会直接进不合格清单）
ROW_WORD_EMPTY = "「错词」这一格是空的"
ROW_VALUE_EMPTY = "「正确写法」这一格是空的"
ROW_NO_WORD_COLUMN = "这份表还没有指定「错词」列"
ROW_NO_VALUE_COLUMN = "这份表还没有指定「正确写法」列"

ROW_ADVICE = "补上这一格的内容，或者把这一行删掉再导入。"


def mapping_problem(item: str) -> ParseProblem:
    return ParseProblem(
        headline="列还没对应好，暂时不能导入。",
        details=[item],
        advice="在上面逐列指定：哪一列是「错词」，哪一列是「正确写法」。",
    )


def nothing_to_import() -> ImportMessages:
    return ImportMessages(
        headline="这份表里没有可以直接导入的词条。",
        details=["每一行都缺「错词」或「正确写法」。"],
        advice="补齐内容后再试，或者先看下面的逐行说明。",
    )


def human_error(exc: BaseException) -> str:
    """把任意异常翻成一句人话（**不含异常类名、不含堆栈**）。

    这是最后一道兜底：解析层内部应尽量自己抛 `ParseProblem`，
    但文件系统、解压、第三方库仍可能抛别的异常——那时也不能把英文扔给用户。
    """
    if isinstance(exc, ParseProblem):
        return exc.as_messages().text()

    name = type(exc).__name__
    if isinstance(exc, (PermissionError,)):
        return "这个文件被其它程序占用了，读不进去。关掉正在打开它的软件再试。"
    if isinstance(exc, (FileNotFoundError,)):
        return "找不到这个文件，它可能已经被移动或改名了。"
    if isinstance(exc, (IsADirectoryError,)):
        return "这是一个文件夹，不是文件。请拖进来一个具体的文件。"
    if isinstance(exc, (UnicodeError,)):
        return "这个文件的内容读不出来，可能不是一份文字内容。"
    if isinstance(exc, (MemoryError,)):
        return "这个文件太大，内存放不下。请分成几个小一点的文件。"
    if isinstance(exc, (OSError,)):
        return "这个文件读不进去，可能正在被别的程序使用，或者磁盘出了问题。"
    # 兜底也不许吐英文类名——用户看不懂，也无从下手。
    # 类名只进日志（`log_unexpected`），界面上只说「我没能读通」。
    return "我在读这份内容时遇到了一个没预料到的情况，暂时没能读通。换个文件，或者把内容拆小一点再试。"


def log_unexpected(exc: BaseException) -> str:
    """给日志用的一行技术信息（**不进界面**）。界面只拿 `human_error()` 的结论。"""
    return f"{type(exc).__name__}: {exc}"


FORBIDDEN_NOTE = (
    "FORBIDDEN_TERMS 只用于单测扫描，不会出现在任何面向用户的句子里。"
)
