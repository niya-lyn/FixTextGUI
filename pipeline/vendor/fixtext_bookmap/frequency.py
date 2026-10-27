"""专有词频率统计（替换次数报告）。

对应上游源码：FixText/src/app/Service/Diff/Extractor.php
- ``Extractor::genReplaceCountReport()``     -> :func:`gen_replace_count_report`
- ``Extractor::customTrimDiff()``            -> :func:`custom_trim_diff`
- ``Extractor::writeToReports()``             -> :func:`build_replace_count_report`
- ``Extractor::mergeReportsToTempMapFile()`` -> :func:`merge_reports_to_temp_map_file`

上游语义：统计的是「同一处差异模式在整本书中出现了多少次」，
即对词条 ``before【FixText 替换为】after`` 做计数（``array_count_values``），
而不是统计词条字符串在正文中出现的次数。
"""

from __future__ import annotations

import os
from collections import Counter

from .option import Option
from .patcher import LITERAL_BACKSLASH_N
from .phpcompat import trim_unicode_chars
from .wordmap import gen_diff_words_map, get_filename, get_words_print_str

#: 上游 ``writeToReports()`` 中用于拼接词条的分隔符
SPLIT_MARK = "【FixText 替换为】"

#: 上游 ``trimPunctuations`` 使用���字符集
PUNCTUATION_CHARS = "　，。“”…！？、"


def custom_trim_diff(
    rm_l_or_r_char: int, context_len: int, before: str, after: str
):
    """等价于上游 ``Extractor::customTrimDiff()``。

    :param rm_l_or_r_char: >0 移除头部；<0 移除尾部；0 不处理。
    :param context_len: 上下文长度，用于计算 ``contextLen * 2 - 1`` 的上限。
    """
    before_len = len(before)
    after_len = len(after)
    context_limit_len = context_len * 2 - 1

    if rm_l_or_r_char > 0:  # 移除首部
        before = before[rm_l_or_r_char:] if before_len > context_limit_len else before
        after = after[rm_l_or_r_char:] if after_len > context_limit_len else after
    elif rm_l_or_r_char < 0:  # 移除尾部
        before = before[:rm_l_or_r_char] if before_len > context_limit_len else before
        after = after[:rm_l_or_r_char] if after_len > context_limit_len else after

    return before, after


def count_word_frequencies(entries: list) -> Counter:
    """统计词条的出现频次。

    :param entries: :func:`gen_diff_words_map` 产出的词条列表。
    :return: ``Counter``，键为 ``before + SPLIT_MARK + after``，值为出现次数。
    """
    counter: Counter = Counter()
    for entry in entries:
        counter[entry["before"] + SPLIT_MARK + entry["after"]] += 1
    return counter


def build_replace_count_report(
    report_arr: list, threshold: int = 0, patch_filename: str = ""
) -> str:
    """等价于上游 ``Extractor::writeToReports()`` 的文本产出部分。

    :param report_arr: 已经拼接过分隔符的词条字符串列表。
    :param threshold: 只输出重复次数大于该值的词条。
    """
    counter = Counter(report_arr)
    replace_total_count = sum(counter.values())

    # 只汇报替换次数大于下限值的内容
    filtered = {k: v for k, v in counter.items() if v > threshold}
    report_total_count = sum(filtered.values())

    # arsort：按次数降序；PHP 8 的排序是稳定的，故同频次保持插入顺序
    ordered = sorted(filtered.items(), key=lambda kv: -kv[1])

    # 注意：PHP heredoc 结尾的空行在解析后只剩一个换行符，
    # 因此这里与上游一致，header 之后直接接第一条词条。
    result = (
        f"    // {patch_filename}\n"
        "\n"
        f"    // 总替换次数：【{replace_total_count}】 | 重复次数大于 {threshold} 的总替换次数：【{report_total_count}】\n"
        f"    // 下方只显示替换次数大于 {threshold} 的内容\n"
    )

    report_arr_count = len(ordered)
    report_num = 1
    for report_key, count in ordered:
        before, after = report_key.split(SPLIT_MARK, 1)
        before = before.replace('"', '\\"')
        after = after.replace('"', '\\"')
        info = f"替换次数: 【{count}】 | 序号：【{report_num}/{report_arr_count}】"
        result += get_words_print_str({"before": before, "after": after}, info)
        report_num += 1

    return result


def merge_reports_to_temp_map_file(reports: list, temp_map_file: str) -> str:
    """等价于上游 ``Extractor::mergeReportsToTempMapFile()``。

    :param reports: 各本书的报告文本列表。
    :param temp_map_file: 上游 ``TEMP_MAP_FILE``（``maps/5.临时校对表.php``）。
    """
    whole_map = ""
    for report_content in reports:
        whole_map += "\n    // ===========\n" + report_content

    result = "<?php\n\n"
    result += "$tempMap = [\n"
    result += whole_map
    result += "];\n"

    dir_name = os.path.dirname(temp_map_file)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(temp_map_file, "w", encoding="utf-8", newline="") as fh:
        fh.write(result)
    return temp_map_file


def gen_replace_count_report(
    book_dir: str,
    book_bak_dir: str,
    report_dir: str,
    temp_map_file: str,
    option: Option | None = None,
) -> dict:
    """生成「专有词频率统计」报告。

    等价于上游 ``Extractor::genReplaceCountReport()``。

    :param book_dir: 校正后的书籍目录（**after** 侧文本，对应上游 ``BOOK_DIR``）。
    :param book_bak_dir: 校正前的书籍目录（**before** 侧文本，对应上游 ``BOOK_BAK_DIR``）。
    :param report_dir: patch / 报告的输出目录。
    :param temp_map_file: 汇总报告的临时词库文件路径。
    :return: 统计结果字典：``{"reports": [...], "entries": {book: [...]} }``
    """
    option = option or Option()

    reports: list[str] = []
    all_entries: dict[str, list] = {}

    for root, _dirs, files in os.walk(book_dir):
        for file_name in sorted(files):
            if not file_name.endswith(".txt"):
                continue

            book_name = get_filename(file_name)
            book_file = os.path.join(root, file_name)

            rel = os.path.relpath(book_file, book_dir)
            book_bak_file = os.path.join(book_bak_dir, rel)

            if not os.path.isfile(book_bak_file):
                continue

            patch_file = os.path.join(report_dir, f"【替换次数报告】{book_name}.patch")
            os.makedirs(report_dir, exist_ok=True)

            book_words = gen_diff_words_map(
                patch_file,
                book_bak_file,
                book_file,
                option.context_len,
                True,
                option,
            )
            all_entries[book_name] = book_words

            report_arr = []
            for word in book_words:
                before = word["before"]
                after = word["after"]

                before, after = custom_trim_diff(
                    option.remove_l_or_r_char, option.context_len, before, after
                )

                if option.trim_punctuations:
                    before = trim_unicode_chars(before, PUNCTUATION_CHARS)
                    after = trim_unicode_chars(after, PUNCTUATION_CHARS)

                if not option.get_multi_line_content:
                    if (
                        LITERAL_BACKSLASH_N in before
                        or LITERAL_BACKSLASH_N in after
                    ):
                        continue

                report_arr.append(before + SPLIT_MARK + after)

            reports.append(
                build_replace_count_report(
                    report_arr,
                    option.replace_count_threshold,
                    get_filename(patch_file),
                )
            )

    merge_reports_to_temp_map_file(reports, temp_map_file)
    return {"reports": reports, "entries": all_entries}
