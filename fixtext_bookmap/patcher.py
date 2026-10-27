"""patch 生成与解析。

对应上游源码：
- FixText/src/app/Util/Util.php           : ``Util::generatePatch()``
- FixText/src/app/Util/PatchAnalyzer.php  : ``PatchAnalyzer``

上游用 ``diff -u`` 生成 patch，再用 ``PatchAnalyzer`` 的状态机把 patch
还原成「before 列表 / after 列表」。本模块完整复刻该状态机，
包括若干容易被忽略的细节：

- 解析前先丢弃 patch 的前 2 行（文件头），规避文件名编码问题；
- 多行差异用 **字面量 ``\\n``（反斜杠 + n）** 拼接，不是真换行；
- 出现「相隔多行的单独 - 行 / + 行」时，会借用前一行上下文补齐；
- 行首 ``-``/``+`` 的剥离是 PHP 的 ``ltrim($line, '-'/'+')``（字符集语义），
  会剥掉**连续多个**同类符号。
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .phpcompat import (
    change_encoding_and_new_line_type,
    php_ltrim,
    php_truthy,
    php_trim,
)

#: 上游 PHP 单引号字符串 ``'\\n'`` 的实际内容：反斜杠 + n（两个字符）
LITERAL_BACKSLASH_N = "\\n"

#: patch 头部的行数（上游 ``array_slice($patchContent, 2)``）
PATCH_HEADER_LINES = 2


class PatchError(RuntimeError):
    """patch 解析失败（与上游 ``AppException`` 对应）。"""


def generate_patch(original_file: str, update_file: str, patch_file: str) -> str:
    """生成 unified diff 补丁文件。

    与上游 ``Util::generatePatch()`` 一致：执行 ``diff -u <original> <update>``
    并把标准输出重定向到 ``patch_file``。

    注意：``diff`` 在两文件存在差异时返回码为 1，属于正常情况，不视为错误。
    """
    if not os.path.exists(original_file) or not os.path.exists(update_file):
        raise PatchError(
            f"originalFile: {original_file} updateFile: {update_file} 路径有误"
        )

    if os.path.isfile(patch_file):
        os.unlink(patch_file)

    diff_cmd = shutil.which("diff")
    if diff_cmd is None:
        raise PatchError(
            "系统中找不到 diff 命令，无法生成 patch（上游同样依赖 GNU diff）"
        )

    with open(patch_file, "wb") as out:
        proc = subprocess.run(
            [diff_cmd, "-u", original_file, update_file],
            stdout=out,
            stderr=subprocess.PIPE,
        )
    if proc.returncode not in (0, 1):
        raise PatchError(
            f"diff 执行失败，返回码 {proc.returncode}: "
            f"{proc.stderr.decode('utf-8', errors='replace')}"
        )
    if not os.path.exists(patch_file):
        raise PatchError(f"patch: {patch_file} 生成 patch 失败")
    return patch_file


class PatchAnalyzer:
    """patch -> (befores, afters) 的状态机解析器。

    对应上游 ``App\\Util\\PatchAnalyzer``。
    """

    def __init__(self) -> None:
        # 单处差异的所有 - 行（如有跨行则合并成单行）
        self.before: list[str] = []
        # 单处差异的所有 + 行
        self.after: list[str] = []
        # 整个 patch 中的所有 - 行
        self.befores: list[str] = []
        # 整个 patch 中的所有 + 行
        self.afters: list[str] = []

        self.first_before_diff_line_key = 0
        self.first_after_diff_line_key = 0
        self.prev_is_before_diff_line = False

    # ------------------------------------------------------------------ #
    # 对外入口
    # ------------------------------------------------------------------ #
    def get_diff_from_patch_file(self, patch_filepath: str):
        """解析 patch 文件，返回 ``(befores, afters)``。"""
        with open(patch_filepath, "rb") as fh:
            raw = fh.read()

        # 上游： file($patchFilepath) -> implode('', array_slice($content, 2))
        # Python 的 split/join 语义与 PHP 的 file()/implode() 等价：
        # 逐行切分保留行尾 "\n"，丢弃前 2 行后再拼接。
        text = raw.decode("utf-8", errors="surrogateescape")
        parts = text.split("\n")
        content = "\n".join(parts[PATCH_HEADER_LINES:])

        content = change_encoding_and_new_line_type(content)

        # 强制最后有一行空行，确保对最后一处差异的提取操作可正常结束
        content = php_trim(content) + "\n"

        lines = content.split("\n")
        for line_key, line in enumerate(lines):
            self.process_line(line, line_key, lines)

        if len(self.befores) != len(self.afters):
            raise PatchError(f"{patch_filepath} 中的 before 与 after 数量不一致")

        return self.befores, self.afters

    # ------------------------------------------------------------------ #
    # 状态机
    # ------------------------------------------------------------------ #
    def process_line(self, line: str, line_key: int, lines: list) -> None:
        if self.is_before_diff_line(line):
            # 每个 - 行都直接提取，记录第一个 - 行的行号
            self.process_before_diff_line(line, line_key)
        elif self.before:
            # 单处差异的所有 - 行遍历完毕，遇到第一个非 - 行，结束对此处差异的提取
            self.process_end_of_before_diff(line, lines)

        if self.is_after_diff_line(line):
            # 每个 + 行都直接提取，记录第一个 + 行的行号
            self.process_after_diff_line(line, line_key, lines)
        elif self.after:
            # 单处差异的所有 + 行遍历完毕，遇到第一个非 + 行，结束对此处差异的提取
            self.process_end_of_after_diff(line, lines)

    @staticmethod
    def is_before_diff_line(line: str) -> bool:
        return line.startswith("-") and not line.startswith("--")

    @staticmethod
    def is_after_diff_line(line: str) -> bool:
        return line.startswith("+") and not line.startswith("++")

    def process_before_diff_line(self, line: str, line_key: int) -> None:
        if self.first_before_diff_line_key == 0:
            self.first_before_diff_line_key = line_key
        self.before.append(php_ltrim(line, "-"))

    def process_end_of_before_diff(self, line: str, lines: list) -> None:
        # 需要判断紧跟在最后一个 - 行之后的是否为 + 行
        if self.is_after_diff_line(line):
            # 若为 + 行，则将 before 内容先合并为单行，继续往下遍历 patch 内容
            self.befores.append(LITERAL_BACKSLASH_N.join(self.before))
            self.before = []
        else:
            # 若不为 + 行，说明双方存在相隔多行的内容差异（存在单独 - 行）
            # 需要提取 - 行的前后一行内容，生成比对结果
            idx = self.first_before_diff_line_key - 1
            if 0 <= idx < len(lines):
                prev_non_before_line = php_ltrim(lines[idx])
                self.before.insert(0, prev_non_before_line)
                self.after.append(prev_non_before_line)

            # 【这里是每处差异的处理出口】只有单独的 - 行，提取后结束处理
            self.collect_diff_lines(line)

        self.first_before_diff_line_key = 0

    def process_after_diff_line(self, line: str, line_key: int, lines: list) -> None:
        prev_line = lines[line_key - 1] if line_key - 1 >= 0 else ""
        if not self.prev_is_before_diff_line:
            self.prev_is_before_diff_line = self.is_before_diff_line(prev_line)

        if self.first_after_diff_line_key == 0:
            self.first_after_diff_line_key = line_key
        self.after.append(php_ltrim(line, "+"))

    def process_end_of_after_diff(self, line: str, lines: list) -> None:
        # 需要判断第一个 + 行的前一行是否为 - 行
        if self.prev_is_before_diff_line:
            # 【这里是每处差异的处理出口】
            # 若为 - 行，可直接将对应的 - 行内容和 + 行内容合并收集，结束此处差异提取
            last_before = self.befores.pop()
            last_before_list = last_before.split(LITERAL_BACKSLASH_N)
            if self.should_merge_as_multi_line(last_before_list, self.after):
                self.befores.extend(last_before_list)
                self.afters.extend(self.after)
            else:
                self.befores.append(LITERAL_BACKSLASH_N.join(last_before_list))
                self.afters.append(LITERAL_BACKSLASH_N.join(self.after))

            self.after = []
            self.first_after_diff_line_key = 0
            self.prev_is_before_diff_line = False
        else:
            # 若不为 - 行，说明双方存在相隔多行的差异内容（即存在单独的 + 行）
            # 则需要提取前后行内容生成比对结果
            idx = self.first_after_diff_line_key - 1
            if 0 <= idx < len(lines):
                prev_non_after_line = php_ltrim(lines[idx])
                self.after.insert(0, prev_non_after_line)
                self.before.append(prev_non_after_line)

            # 【这里是每处差异的处理出口】遍历完这一处差异的所有 + 行
            self.collect_diff_lines(line)
            self.first_after_diff_line_key = 0

    @staticmethod
    def should_merge_as_multi_line(before: list, after: list) -> bool:
        """判断是否应当「分行插入」而非「合并成一行插入」。

        前后行元素数量相等、且没有任何一行内容相同或一空一非空时才可以分行。
        """
        if len(before) != len(after):
            return False

        for bv, av in zip(before, after):
            # 如果存在相同内容行，可能是连续几段的上下文中只有细微的差异
            # 也只能先合并再插入
            if bv == av:
                return False

            # 如果有单独空行也只能合并之后再插入
            if (bv == "" and php_truthy(av)) or (php_truthy(bv) and av == ""):
                return False

        return True

    def collect_diff_lines(self, line: str) -> None:
        line = php_ltrim(line)
        self.before.append(line)
        self.after.append(line)

        self.befores.append(LITERAL_BACKSLASH_N.join(self.before))
        self.afters.append(LITERAL_BACKSLASH_N.join(self.after))

        self.before = []
        self.after = []
        self.prev_is_before_diff_line = False
