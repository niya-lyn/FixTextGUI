"""专有词条提取与词库表生成。

对应上游源码：FixText/src/app/Service/Diff/Extractor.php
- ``Extractor::genDiffWordsMap()``      -> :func:`gen_diff_words_map`
- ``Extractor::mergeToBookMapFile()``   -> :func:`merge_to_book_map_file`
- ``Extractor::findBookNotesInsertPosition()`` -> :func:`find_book_notes_insert_position`
- ``Extractor::findClosingBracket()``   -> :func:`find_closing_bracket`
- ``Extractor::stripHtmlTag()``         -> :func:`strip_html_tag`
- ``Util::getWordsPrintStr()``          -> :func:`get_words_print_str`
- ``Map::getBookMapFileWithTags()``     -> :func:`get_book_map_file_with_tags`
"""

from __future__ import annotations

import datetime as _dt
import os
import re

from .option import Option
from .patcher import LITERAL_BACKSLASH_N, PatchAnalyzer, generate_patch
from .phpcompat import (
    php_preg_replace_multiline_start,
    php_rtrim,
    php_strip_tags,
    php_truthy,
    php_trim,
    trim_unicode_chars,
)
from .textdiff import extract_str_diff

#: 上游 ``Map::$bookMapTags``
BOOK_MAP_TAGS = ("【7】", "【8】", "【9】")

#: 词库子目录名（上游 Map::getMapFilepath('书籍专有替换词库')）
BOOK_MAP_DIRNAME = "书籍专有替换词库"

#: 新建词库文件的初始内容（上游 mergeToBookMapFile 中的字面量）
NEW_MAP_FILE_CONTENT = "<?php\n\nreturn [\n    'bookNotes' => [\n    ],\n];\n"

_BOOK_NOTES_RE = re.compile(rb"'bookNotes'\s*=>\s*\[")


# ---------------------------------------------------------------------- #
# 基础工具
# ---------------------------------------------------------------------- #
def get_filename(filename: str, remove_epub_merge_prefix: bool = False) -> str:
    """等价于上游 ``Util::getFilename()``（pathinfo PATHINFO_FILENAME）。"""
    base = os.path.basename(filename)
    # pathinfo 对以 "." 开头的文件返回空文件名
    if base.startswith(".") and base.count(".") == 1:
        name = ""
    else:
        name = os.path.splitext(base)[0]
    if remove_epub_merge_prefix:
        name = remove_epub_merge_prefix_fn(name)
    return name


def remove_epub_merge_prefix_fn(filename: str) -> str:
    """等价于上游 ``Util::removeEpubMergePrefix()``。"""
    return filename.replace("【EPUB 合并文件】", "")


def get_time_str(timestamp: float | None = None, with_date: bool = False) -> str:
    """等价于上游 ``Util::getTimeStr()``。

    :param timestamp: 为 None 时取当前时间（便于测试注入固定值）。
    """
    ts = _dt.datetime.now().timestamp() if timestamp is None else timestamp
    dt = _dt.datetime.fromtimestamp(ts)
    time_str = dt.strftime("%H:%M:%S")
    if with_date:
        time_str = dt.strftime("%Y-%m-%d") + " " + time_str
    return time_str


def get_book_map_file_with_tags(book_map_dir: str, book_name: str) -> str:
    """等价于上游 ``Map::getBookMapFileWithTags()``。

    优先匹配 ``书籍专有替换词库/<name>.php``；找不到时依次尝试
    ``【7】``/``【8】``/``【9】`` 前缀的同义文件；都没有则返回空串。
    """
    path = os.path.join(book_map_dir, f"{book_name}.php")
    if os.path.isfile(path):
        return path

    for tag in BOOK_MAP_TAGS:
        path = os.path.join(book_map_dir, f"{tag}{book_name}.php")
        if os.path.isfile(path):
            return path

    return ""


# ---------------------------------------------------------------------- #
# HTML 处理
# ---------------------------------------------------------------------- #
def strip_html_tag(s: str) -> str:
    """等价于上游 ``Extractor::stripHtmlTag()``。

    - 若字符串中既没有 ``<`` 也没有 ``>``，直接裁剪首尾空白（含全角空格）；
    - 否则先 ``strip_tags``，再按「第一个 ``>`` 之后」到「最后一个 ``<`` 之前」
      截取，最后 trim。
    """
    if ("<" not in s) and (">" not in s):
        return php_trim(trim_unicode_chars(s, " 　"))

    s = php_strip_tags(s)

    # 下列的两个判断在多数情况下无副作用，此处按上游原样复刻
    start = s.find(">")
    start = 0 if start == -1 else min(len(s) - 1, start + 1)

    end = s.rfind("<")
    end = len(s) if (end == -1 or end < start) else end

    # PHP: mb_substr($str, $start, max($end - $start, 1)) —— 第三参是「长度」
    return php_trim(s[start:start + max(end - start, 1)])


# ---------------------------------------------------------------------- #
# 词条输出格式
# ---------------------------------------------------------------------- #
def get_words_print_str(words, extra_info: str = "", multi_line: bool = False) -> str:
    """等价于上游 ``Util::getWordsPrintStr()``。

    单行模式::

        ['before' => "X", 'after' => "Y"],

    多行模式::

        [
            'before' => "X",
            'after'  => "Y",
        ],

    :param words: 词条字典，或词条字典的列表。
    """
    if isinstance(words, dict):
        words = [words]

    result = ""
    for word in words:
        before = word["before"]
        after = word["after"]

        if multi_line:
            elements = []
            if isinstance(before, list):
                elements.append("'before' => " + '["' + '", "'.join(before) + '"]')
            else:
                elements.append("'before' => \"" + before + "\"")
            elements.append("'after'  => \"" + after + "\"")

            if "mark" in word:
                elements.append("'mark'   => \"" + word["mark"] + "\"")
            if "id" in word:
                elements.append("'id'     => \"" + word["id"] + "\"")

            inner = ",\n        ".join(elements)
            extra = f" // {extra_info}" if extra_info else ""
            result += f"    [\n        {inner}\n    ],{extra}\n"
        else:
            if isinstance(before, list):
                before_str = "'before' => " + '["' + '", "'.join(before) + '"]'
            else:
                before_str = "'before' => \"" + before + "\""

            after_str = ", 'after' => \"" + after + "\""
            mark_str = ", 'mark' => \"" + word["mark"] + "\"" if "mark" in word else ""
            id_str = ", 'id' => \"" + word["id"] + "\"" if "id" in word else ""

            result += (
                f"    [{before_str}{after_str}{mark_str}{id_str}],"
                + (f" // {extra_info}" if extra_info else "")
                + "\n"
            )

    return result


# ---------------------------------------------------------------------- #
# 词条提取
# ---------------------------------------------------------------------- #
def gen_diff_words_map(
    patch_filepath: str,
    before_filepath: str,
    after_filepath: str,
    context_len: int = 5,
    trim_orig_str: bool = False,
    option: Option | None = None,
) -> list:
    """从两个文本文件的差异中提取专有词条。

    等价于上游 ``Extractor::genDiffWordsMap()``。

    注意参数语义与「直觉」相反，但与上游一致：
    ``before_filepath`` 是 **改前** 的文本（上游 ``BOOK_FIX_DIR`` 侧），
    ``after_filepath`` 是 **改后** 的文本（上游 ``BOOK_DIR`` 侧）；
    产出的词条 ``before`` 取自改前文本，``after`` 取自改后文本。

    :return: 词条列表，每项为 ``{"before": str, "after": str}``。
    """
    option = option or Option()

    patch_dir = os.path.dirname(patch_filepath)
    if patch_dir and not os.path.isdir(patch_dir):
        os.makedirs(patch_dir, exist_ok=True)

    generate_patch(before_filepath, after_filepath, patch_filepath)
    befores, afters = PatchAnalyzer().get_diff_from_patch_file(patch_filepath)

    result_map = []
    for k, before in enumerate(befores):
        after = afters[k]

        # 若存在跨行内容，则直接使用整行，而不使用截取后的结果
        if (LITERAL_BACKSLASH_N not in before) and (LITERAL_BACKSLASH_N not in after):
            diff_ret = extract_str_diff(before, after, context_len)
            if not diff_ret:
                continue
            before, after = diff_ret

        if trim_orig_str:
            before = php_trim(trim_unicode_chars(before, " 　"))
            after = php_trim(trim_unicode_chars(after, " 　"))

        # 注意：PHP 的 ! 判断会把字符串 "0" 也当作假值，此处保持一致
        if not php_truthy(before) or not php_truthy(after):
            continue

        orig_before = before
        orig_after = after
        result_map.append({"before": before, "after": after})

        # 另存一份移除了 html 标签的备用
        if option.add_html_stripped_copy:
            before = strip_html_tag(before)
            after = strip_html_tag(after)
            if orig_before != before or orig_after != after:
                result_map.append({"before": before, "after": after})

    return result_map


# ---------------------------------------------------------------------- #
# 词库表生成
# ---------------------------------------------------------------------- #
def find_closing_bracket(content: bytes, start_pos: int):
    """在 ``content`` 中从 ``start_pos`` 起寻找与 ``[`` 配对的 ``]``。

    等价于上游 ``Extractor::findClosingBracket()``，对引号与转义敏感，
    且以 **字节** 为单位（与上游的 strlen/substr 保持一致）。

    :return: 配对 ``]`` 的字节下标；未找到返回 ``False``。
    """
    depth = 1
    pos = start_pos
    length = len(content)
    in_string = False
    string_char = b""
    escape = False

    while pos < length and depth > 0:
        char = content[pos:pos + 1]
        if escape:
            escape = False
        elif in_string:
            if char == b"\\":
                escape = True
            elif char == string_char:
                in_string = False
        else:
            if char == b'"' or char == b"'":
                in_string = True
                string_char = char
            elif char == b"[":
                depth += 1
            elif char == b"]":
                depth -= 1
        if depth > 0:
            pos += 1

    return pos if depth == 0 else False


def find_book_notes_insert_position(content: bytes):
    """定位 ``'bookNotes' => [ ... ]`` 词条区的插入位置。

    等价于上游 ``Extractor::findBookNotesInsertPosition()``：
    - 找到 ``'bookNotes' => [`` 的结束位置；
    - 找到与之配对的 ``]``，取中间内容按行扫描；
    - 找到最后一行同时含有 ``['before'`` 和 ``'after'`` 的行，插到该行之后；
    - 若一条已有词条都没有，则插到 ``[`` 之后的第一行起始处。

    :return: 字节下标；定位失败返回 ``False``。
    """
    m = _BOOK_NOTES_RE.search(content)
    if not m:
        return False
    section_start = m.end()

    section_end = find_closing_bracket(content, section_start)
    if section_end is False:
        return False

    section_content = content[section_start:section_end]
    lines = section_content.split(b"\n")

    # 逐行查找最后一个包含 ['before' ... 'after' 的行
    last_entry_line = -1
    for i, line in enumerate(lines):
        if b"['before'" in line and b"'after'" in line:
            last_entry_line = i

    if last_entry_line >= 0:
        offset = section_start
        for i in range(last_entry_line + 1):
            offset += len(lines[i]) + 1  # +1 对应 \n
        return offset

    # 无现有词条，插入到 [ 后的下一行起始处
    newline_pos = content.find(b"\n", section_start)
    return newline_pos + 1 if newline_pos != -1 else section_start


def merge_to_book_map_file(
    book_name: str,
    book_words: list,
    map_root: str,
    option: Option | None = None,
    timestamp: float | None = None,
) -> bool:
    """把词条合并进 ``书籍专有替换词库/<book_name>.php``。

    等价于上游 ``Extractor::mergeToBookMapFile()``。

    :param map_root: 上游 ``SCRIPT_DIR``（其下有 ``maps/`` 目录）。
    :param timestamp: 写入时间点注释时使用的时间戳（测试可注入固定值）。
    :return: 是否写入成功。
    """
    option = option or Option()

    if not book_words or "before" not in book_words[0]:
        return False

    book_map_dir = os.path.join(map_root, "maps", BOOK_MAP_DIRNAME)
    if not os.path.isdir(book_map_dir):
        return False

    book_map_file = get_book_map_file_with_tags(book_map_dir, book_name)
    if not book_map_file:  # 无文件则新建
        book_map_file = os.path.join(book_map_dir, f"{book_name}.php")
        with open(book_map_file, "w", encoding="utf-8", newline="") as fh:
            fh.write(NEW_MAP_FILE_CONTENT)

    for word in book_words:
        word["before"] = word["before"].replace('"', '\\"')  # html 代码中的引号需要转义
        word["after"] = word["after"].replace('"', '\\"')

    merge_content = ""
    if option.add_current_time:
        merge_content = (
            "    /* 新增下列词条的时间点：" + get_time_str(timestamp, True) + " */\n"
        )
    merge_content += get_words_print_str(book_words)
    merge_content = php_preg_replace_multiline_start(merge_content, "    ")
    merge_content = php_rtrim(merge_content) + "\n"

    with open(book_map_file, "rb") as fh:
        content = fh.read()

    if b"'bookNotes' => " not in content:
        content = content.replace(
            b"\n];", b"\n    'bookNotes' => [\n    ],\n];"
        )

    insert_pos = find_book_notes_insert_position(content)
    if insert_pos is False:
        return False

    content = (
        content[:insert_pos]
        + merge_content.encode("utf-8")
        + content[insert_pos:]
    )
    with open(book_map_file, "wb") as fh:
        fh.write(content)
    return True
