"""FixText 引号检查核心（Python 重实现）。

源逻辑：FixText/src/app/Service/Quotation/QuotationChecker.php（检测部分逐行对齐），
状态语义来自 QuotationContext.php。

与原版的对齐说明：
- 原命令 `check-quotation-marks` 的统计模式（'c'：只统计错误数）语义为：
  第一遍撞到第一处报错后 directCount=true 并从文件头重读；第二遍从头到尾，
  每处 dumpErr 计 1 次错误。因此错误总数 == 【单遍全文件扫描】的 dumpErr 调用数
  （初始状态干净：quoteStack 空、isMultiLine=false、directCount=true）。
- 本模块即实现该单遍扫描：每处报错记录为一条 QuotationError，
  并跳过当前行（等价于原版异常路径 handleLineException → resetLineState → break）。
- 检测规则本身（check_left_singles / check_right_singles / check_left_doubles /
  check_right_doubles / check_eol / check_missing_right_quote /
  check_left_quote_prev_char / search_for_right_quote）与 PHP 原实现逐条对齐，
  包括跨行探测的 SEARCH_FOR_RD_LINES=100 上限与文件末尾处重复探测最后一行的原版行为。

已实现的规则族（与 PHP 原版报错文案一一对应）：
- 引号配对：缺左/右引号、左右交叉错乱、空引号、同向嵌套（双套双/单套单）
- 跨行配对：段首左引号位置不合法、隔行左引号错位、下方多行找不到右引号、
  多层嵌套不允许跨行、文件末尾未闭合
- 英文弯撇号过滤（'’' 两侧均为字母/数字/空格时视为撇号，不参与配对）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

# ———— 常量（与 PHP QuotationChecker / QuotationContext 对齐）————

QUOTE_CHARS = ("“", "”", "‘", "’")
SEARCH_FOR_RD_LINES = 100

# letters = a-z A-Z 0-9 与空格（QuotationContext::__construct）
LETTERS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ")

# checkLeftQuotePrevChar 默认 prevAllowedExpr "/[【〖。？！：，> 　\r\n]/um"
DEFAULT_PREV_ALLOWED = {"【", "〖", "。", "？", "！", "：", "，", ">", " ", "　", "\r", "\n"}

# searchForRightQuote 的 nextExpr "/[> 　\r\n]/um"
NEXT_EXPR_ALLOWED = {">", " ", "　", "\r", "\n"}

# 空行判定 "/^[ 　\r\n]*$/um"
BLANK_CHARS = {" ", "　", "\r", "\n"}

LEFT_DOUBLE, RIGHT_DOUBLE = "“", "”"
LEFT_SINGLE, RIGHT_SINGLE = "‘", "’"


@dataclass
class QuotationError:
    """一处引号错误（对齐原版 dumpErr 的一次调用）。

    line: 1 起的行号；char: 行内字符下标（0 起，对齐 PHP charKey）；
    msg: 与 PHP 原版完全一致的报错文案。
    """

    line: int
    char: int
    msg: str

    def to_dict(self) -> dict:
        return asdict(self)


class _DirectSkip(Exception):
    """对齐 PHP DirectSkipException：跳过当前行，继续处理下一行。"""


def _php_file_lines(content: str) -> List[str]:
    """复刻 PHP file() 的行切分：仅按 '\\n' 切分、行尾保留 '\\n'。

    - 文件末尾有 '\\n'：不产生末尾空元素（与 file() 一致）
    - 末行无 '\\n'：该行保留原样（无换行符）
    - '\\r' 保留在行内（CRLF 文件中行尾为 "\\r\\n"）
    """
    if content == "":
        return []
    parts = content.split("\n")
    if parts[-1] == "":
        parts.pop()
        return [p + "\n" for p in parts]
    return [p + "\n" for p in parts[:-1]] + [parts[-1]]


class QuotationChecker:
    """单遍全文件扫描的引号检查器（原版统计模式语义）。"""

    SEARCH_FOR_RD_LINES = SEARCH_FOR_RD_LINES

    def __init__(self) -> None:
        self.errors: List[QuotationError] = []
        # —— 对齐 QuotationContext 的可变状态 ——
        self.quote_stack: List[dict] = []          # [{'char': ..., 'pos': ...}]
        self.outer_left_single_keys: List[int] = []
        self.outer_right_single_keys: List[int] = []
        self.is_multi_line = False
        self.met_eol = False
        # —— 扫描游标 ——
        self.line_arr: List[str] = []
        self.line_count = 0
        self.line_key = 0
        self.char_arr: List[str] = []
        self.char_key = 0
        self.char = ""

    # ———————————————————————— 对外入口 ————————————————————————

    def check_text(self, text: str) -> List[QuotationError]:
        """对整段文本执行检查，返回错误列表（每处一条，按行序）。"""
        self.errors = []
        self._reset_line_state()
        self.line_arr = _php_file_lines(text)
        self.line_count = len(self.line_arr)
        self._process_lines()
        return self.errors

    def check_file(self, path: str | Path, encoding: str = "utf-8") -> List[QuotationError]:
        """对单个文件执行检查。文件读取为 utf-8 文本。"""
        with open(path, "r", encoding=encoding, newline="") as fh:
            text = fh.read()
        return self.check_text(text)

    # ———————————————————————— 主扫描循环 ————————————————————————

    def _process_lines(self) -> None:
        """对齐 processLines()：只处理含引号字符的行。"""
        for line_key, line in enumerate(self.line_arr):
            if line_key < 0:
                continue
            self.line_key = line_key
            self.char_arr = list(line)

            if not any(q in line for q in QUOTE_CHARS):
                continue

            try:
                self._process_characters_in_line()
            except _DirectSkip:
                # 对齐 handleLineException → resetLineState → break
                self._reset_line_state()
                continue

    def _process_characters_in_line(self) -> None:
        """对齐 processCharactersInLine()：逐字符跑五项检查。"""
        for k, ch in enumerate(self.char_arr):
            self.char_key = k
            self.char = ch
            self._check_left_singles()
            self._check_right_singles()
            self._check_left_doubles()
            self._check_right_doubles()
            self._check_eol()

    # ———————————————————————— 单引号 ————————————————————————

    def _check_left_singles(self) -> None:
        """对齐 checkLeftSingles()。"""
        if self.char != LEFT_SINGLE:
            return

        # 1. 收集最外层单引号（栈中无双引号时）
        has_double = any(item["char"] == LEFT_DOUBLE for item in self.quote_stack)
        if not has_double:
            self.outer_left_single_keys.append(self.char_key)

        # 2. 跨行段首延续判定：只是延续标记，不重复压栈
        if (
            self.is_multi_line
            and self.met_eol
            and self.quote_stack
            and self.quote_stack[-1]["char"] == LEFT_SINGLE
        ):
            self.quote_stack[-1]["pos"] = self.char_key
            self.met_eol = False
            return

        # 3. 单引号内直接嵌套独立单引号
        prev_char = self.char_arr[self.char_key - 1] if self.char_key - 1 >= 0 else ""
        top = self.quote_stack[-1] if self.quote_stack else None
        if top is not None and top["char"] == LEFT_SINGLE and prev_char != LEFT_SINGLE:
            self._dump_err("<左单引号前> 单引号内直接嵌套了独立单引号（应规范使用双引号）")

        # 4. 正常入栈
        self.quote_stack.append({"char": LEFT_SINGLE, "pos": self.char_key})
        self.met_eol = False

    def _check_right_singles(self) -> None:
        """对齐 checkRightSingles()。"""
        if self.char != RIGHT_SINGLE:
            return

        # 英文弯撇号过滤：两侧均为字母/数字/空格
        prev_char = self.char_arr[self.char_key - 1] if self.char_key - 1 >= 0 else ""
        next_char = self.char_arr[self.char_key + 1] if self.char_key + 1 < len(self.char_arr) else ""
        if prev_char in LETTERS and next_char in LETTERS:
            return

        if not self.quote_stack:
            self._dump_err("<右单引号前> 缺左单引号")

        top = self.quote_stack.pop()

        # 交叉校验：栈顶必须是左单引号
        if top["char"] != LEFT_SINGLE:
            self._dump_err("<右单引号前> 引号嵌套交叉错乱，内部双引号“未闭合")

        # 空单引号判断
        if self.char_key - top["pos"] == 1:
            self._dump_err("<右单引号前> 出现空引号‘’现象")

        # 收集最外层右单引号
        has_double = any(item["char"] == LEFT_DOUBLE for item in self.quote_stack)
        if not has_double:
            self.outer_right_single_keys.append(self.char_key)

        # 栈清空时，跨行状态彻底结束
        if not self.quote_stack:
            self.is_multi_line = False

    # ———————————————————————— 双引号 ————————————————————————

    def _check_left_doubles(self) -> None:
        """对齐 checkLeftDoubles()。"""
        if self.char != LEFT_DOUBLE:
            return

        prev_char = self.char_arr[self.char_key - 1] if self.char_key - 1 >= 0 else ""

        # 1. 跨行段首延续判定
        if (
            self.is_multi_line
            and self.met_eol
            and self.quote_stack
            and self.quote_stack[-1]["char"] == LEFT_DOUBLE
        ):
            self.quote_stack[-1]["pos"] = self.char_key
            self.met_eol = False
            return

        # 2. 双引号内直接嵌套独立双引号
        top = self.quote_stack[-1] if self.quote_stack else None
        if top is not None and top["char"] == LEFT_DOUBLE and prev_char != LEFT_DOUBLE:
            self._dump_err("<左双引号前> 双引号内直接嵌套了独立双引号（应规范使用单引号）")

        # 3. 正常入栈
        self.quote_stack.append({"char": LEFT_DOUBLE, "pos": self.char_key})
        self.met_eol = False

    def _check_right_doubles(self) -> None:
        """对齐 checkRightDoubles()。"""
        if self.char != RIGHT_DOUBLE:
            return

        if not self.quote_stack:
            self._dump_err("<右双引号前> 缺左双引号")

        top = self.quote_stack.pop()

        # 交叉校验：栈顶必须是左双引号
        if top["char"] != LEFT_DOUBLE:
            self._dump_err("<右双引号前> 引号嵌套交叉错乱，内部单引号‘未闭合")

        # 空引号判断
        if self.char_key - top["pos"] == 1:
            self._dump_err("<右双引号前> 出现空引号“”现象")

        if not self.quote_stack:
            self.is_multi_line = False

    # ———————————————————————— 行尾 / 跨行 ————————————————————————

    def _check_eol(self) -> None:
        """对齐 checkEOL()。fixSingles 恒为 False（检测模式），doFixSingles 为空操作。"""
        if self.char != "\n":
            return

        if self.quote_stack:
            # 只有最外层恰好 1 层引号未闭合时，才允许向下跨行探测
            if len(self.quote_stack) == 1:
                top_char = self.quote_stack[0]["char"]
                right_quote = RIGHT_DOUBLE if top_char == LEFT_DOUBLE else RIGHT_SINGLE
                self._check_missing_right_quote(top_char, right_quote)
                self.is_multi_line = True
            else:
                top = self.quote_stack[-1]
                type_ = "双" if top["char"] == LEFT_DOUBLE else "单"
                self._dump_err(f"<换行时> 存在未闭合的{type_}引号（多层嵌套不允许跨行）")

        # doFixSingles()：检测模式下为空操作
        self._reset_quotation_keys()
        self.met_eol = True

    def _check_missing_right_quote(self, left_quote: str = LEFT_DOUBLE, right_quote: str = RIGHT_DOUBLE) -> None:
        """对齐 checkMissingRightQuote()。"""
        quote_name = "双" if left_quote == LEFT_DOUBLE else "单"

        if self.line_key == self.line_count - 1:
            self._dump_err(f"<换行时> 缺右{quote_name}引号（已到文件末尾）")

        last_left_key = self.quote_stack[-1]["pos"] if self.quote_stack else 0
        if not self._check_left_quote_prev_char(last_left_key):
            self._dump_err(f"<换行时> 缺右{quote_name}引号，段首左{quote_name}引号的位置有误")

        if not self._search_for_right_quote(left_quote, right_quote):
            self._dump_err(f"<换行时> 缺右{quote_name}引号，且下方多行内都无法查找到右{quote_name}引号")

    def _check_left_quote_prev_char(
        self,
        left_quote_key: int,
        char_arr: Optional[List[str]] = None,
        prev_allowed: Optional[set] = None,
    ) -> bool:
        """对齐 checkLeftQuotePrevChar()：校验左引号前置字符的合法性。"""
        if not char_arr:
            char_arr = self.char_arr
        prev_k = max(left_quote_key - 1, 0)
        prev_char = char_arr[prev_k] if 0 <= prev_k < len(char_arr) else ""
        allowed = prev_allowed if prev_allowed is not None else DEFAULT_PREV_ALLOWED

        if left_quote_key > 0 and prev_char not in allowed:
            return False
        return True

    def _search_for_right_quote(self, left_quote: str = LEFT_DOUBLE, right_quote: str = RIGHT_DOUBLE) -> bool:
        """对齐 searchForRightQuote()：向下探测右引号。

        注意：保留了原版在 nextLineKey 越过文件末尾后，经 min(prevNextLineKey,
        lineCount-1) 回卷而【重复探测最后一行】的行为。
        """
        quote_name = "双" if left_quote == LEFT_DOUBLE else "单"
        found_right_quote = False
        next_line_has_left_quote = False
        prev_next_line_key = 0

        i = 1
        while i <= self.SEARCH_FOR_RD_LINES:
            if prev_next_line_key == 0:
                next_line_key = min(self.line_key + 1, self.line_count - 1)
            else:
                next_line_key = min(prev_next_line_key, self.line_count - 1)

            # do-while：跳过空行
            while True:
                if next_line_key >= self.line_count:
                    return found_right_quote  # break 2
                next_line = self.line_arr[next_line_key]
                next_line_key += 1
                is_blank = all(c in BLANK_CHARS for c in next_line) or next_line in ("\r\n", "\n")
                if not (is_blank and next_line_key < self.line_count):
                    break

            prev_next_line_key = next_line_key
            next_char_arr = list(next_line)
            next_left_quote_k = next_line.find(left_quote)

            if not next_char_arr:
                self._dump_err(f"<换行时> 缺右{quote_name}引号")

            # 隔行出现的左引号是否在行首（前置字符合法性）
            if next_left_quote_k != -1:
                if not self._check_left_quote_prev_char(next_left_quote_k, next_char_arr, NEXT_EXPR_ALLOWED):
                    self._dump_err(f"<换行时> 缺右{quote_name}引号，隔行出现左{quote_name}引号错位")

            # 统一风格校验
            if i == 1:
                if left_quote in next_line:
                    next_line_has_left_quote = True
            else:
                if left_quote in next_line and not next_line_has_left_quote:
                    self._dump_err(f"<换行时> 缺右{quote_name}引号，两行后却出现不应有的左{quote_name}引号")
                if left_quote not in next_line and next_line_has_left_quote:
                    self._dump_err(f"<换行时> 缺右{quote_name}引号，两行后却缺失应有的左{quote_name}引号")

            # 检查右引号（单引号需过滤英文撇号）
            if right_quote in next_line:
                if right_quote == RIGHT_SINGLE:
                    clean_line = _strip_apostrophes(next_line)
                    if RIGHT_SINGLE in clean_line:
                        found_right_quote = True
                        break
                else:
                    found_right_quote = True
                    break

            i += 1

        return found_right_quote

    # ———————————————————————— 状态与报错 ————————————————————————

    def _dump_err(self, err_msg: str) -> None:
        """对齐 dumpErr() 的统计模式分支：记录事件并抛 _DirectSkip 跳过当前行。"""
        self.errors.append(QuotationError(line=self.line_key + 1, char=self.char_key, msg=err_msg))
        raise _DirectSkip()

    def _reset_quotation_keys(self) -> None:
        """对齐 QuotationContext::resetQuotationKeys()：只有非跨行时才清空栈。"""
        if not self.is_multi_line:
            self.quote_stack = []
        self.outer_left_single_keys = []
        self.outer_right_single_keys = []

    def _reset_line_state(self) -> None:
        """对齐 QuotationContext::resetLineState()。"""
        self.quote_stack = []
        self.is_multi_line = False
        self.met_eol = False
        self._reset_quotation_keys()


def _strip_apostrophes(line: str) -> str:
    """对齐 preg_replace('/[a-zA-Z0-9]’[a-zA-Z0-9]/u', '', nextLine)。

    PHP preg_replace 默认替换全部匹配；正则无锚定、无重叠回溯（消费已匹配字符）。
    """
    out = []
    i = 0
    n = len(line)
    while i < n:
        if (
            i + 2 < n
            and line[i].isascii()
            and line[i].isalnum()
            and line[i + 1] == RIGHT_SINGLE
            and line[i + 2].isascii()
            and line[i + 2].isalnum()
        ):
            i += 3
        else:
            out.append(line[i])
            i += 1
    return "".join(out)


# ———————————————————————— 便捷函数 ————————————————————————

def check_text(text: str) -> List[QuotationError]:
    """对整段文本执行引号检查。"""
    return QuotationChecker().check_text(text)


def check_file(path: str | Path, encoding: str = "utf-8") -> List[QuotationError]:
    """对单个文件执行引号检查（utf-8 文本）。"""
    return QuotationChecker().check_file(path, encoding=encoding)
