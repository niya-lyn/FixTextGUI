"""字符串差异截取。

对应上游源码：FixText/src/app/Util/Util.php 的 ``Util::extractStrDiff()``。
"""

from __future__ import annotations


def extract_str_diff(str1: str, str2: str, context_len: int = 0):
    """截取两个字符串的差异片段，并带上 ``context_len`` 长度的上下文。

    与上游完全一致的要点：
    - 两个字符串完全相同时返回空（上游返回 ``[]``，调用方据此 ``continue``）；
    - 正向定位第一个不同字符，反向定位最后一个不同字符；
    - 差异区间为闭区间，末尾位置可能被 ``diffStart - 1`` 兜底；
    - 截取范围按「字符（码点）」而非字节计算（上游用 mb_* 系列函数）。

    :return: ``(before, after)`` 二元组；两串相同时返回 ``None``。
    """
    if str1 == str2:
        return None

    chars1 = list(str1)
    chars2 = list(str2)
    len1 = len(chars1)
    len2 = len(chars2)
    min_len = min(len1, len2)

    # 正向查找：第一个不同字符的位置
    diff_start = min_len
    for i in range(min_len):
        if chars1[i] != chars2[i]:
            diff_start = i
            break

    # 反向查找：从尾部开始找第一个不同的字符
    diff_end1 = len1 - 1
    diff_end2 = len2 - 1
    while diff_end1 >= diff_start and diff_end2 >= diff_start:
        if chars1[diff_end1] != chars2[diff_end2]:
            break
        diff_end1 -= 1
        diff_end2 -= 1

    # 确保差异结束位置不小于差异开始位置的前一个位置
    diff_end1 = max(diff_end1, diff_start - 1)
    diff_end2 = max(diff_end2, diff_start - 1)

    # 计算需要提取的范围（包含上下文）
    extract_start1 = max(0, diff_start - context_len)
    extract_end1 = min(len1 - 1, diff_end1 + context_len)

    extract_start2 = max(0, diff_start - context_len)
    extract_end2 = min(len2 - 1, diff_end2 + context_len)

    before = "".join(chars1[extract_start1:extract_end1 + 1])
    after = "".join(chars2[extract_start2:extract_end2 + 1])
    return before, after
