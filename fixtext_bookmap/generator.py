"""专有词库生成的编排入口。

对应上游源码：FixText/src/app/Service/Diff/Extractor.php 的
``Extractor::generateBookMaps()``，以及
``App\\Trait\\FileWalkerTrait::walkFiles()`` 的目录遍历逻辑。

本模块是给上层编排器调用的稳定接口，核心能力：

- :meth:`BookMapGenerator.generate_book_maps` —— 遍历 booksFix 目录，
  逐本书生成 diff、提取专有词条、写入「书籍专有替换词库」词库表；
- :meth:`BookMapGenerator.generate_book_maps_for_files` —— 只处理指定文件
  （编排器已有文件清单时使用）；
- :meth:`BookMapGenerator.gen_replace_count_report` —— 专有词频率统计。
"""

from __future__ import annotations

import os

from .frequency import gen_replace_count_report
from .option import Option
from .wordmap import (
    gen_diff_words_map,
    get_filename,
    merge_to_book_map_file,
    remove_epub_merge_prefix_fn,
)

#: 上游 ``FileWalkerTrait::walkFiles()`` 默认只处理 .txt
DEFAULT_EXTENSIONS = (".txt",)


def iter_files(root: str, extensions=DEFAULT_EXTENSIONS):
    """递归遍历目录，返回 ``(所在目录, 文件名)`` 列表。

    对应上游 ``Util::recursiveFileActionHook()`` + ``Util::globOnlyFiles('*.txt')``：
    深度优先递归子目录，每个目录内只取匹配扩展名的文件。

    与上游唯一的差别：这里对文件做了排序（上游是文件系统顺序），
    以保证多次运行的结果可复现。
    """
    result = []
    if not os.path.isdir(root):
        return result
    for dir_path, dir_names, file_names in os.walk(root):
        dir_names.sort()
        for file_name in sorted(file_names):
            if file_name.lower().endswith(tuple(extensions)):
                result.append((dir_path, file_name))
    return result


class BookMapGenerator:
    """专有词库生成器。

    :param option: 选项，默认为上游 Option 的默认值。
    :param map_root: 上游 ``SCRIPT_DIR``，其下应存在 ``maps/书籍专有替换词库/``。
    """

    def __init__(self, option: Option | None = None, map_root: str = ".") -> None:
        self.option = option or Option()
        self.map_root = map_root

    # ------------------------------------------------------------------ #
    # 词库表生成
    # ------------------------------------------------------------------ #
    def generate_book_maps(
        self,
        book_fix_dir: str,
        book_dir: str,
        timestamp: float | None = None,
    ) -> dict:
        """遍历 ``book_fix_dir``，为每本书生成专有词库表。

        对应上游 ``Extractor::generateBookMaps()``。

        :param book_fix_dir: 提供词条 **before（改前）** 侧文本的目录，对应上游 ``BOOK_FIX_DIR``。
        :param book_dir: 提供词条 **after（改后）** 侧文本的目录，对应上游 ``BOOK_DIR``。
        :param timestamp: 写入时间点注释时使用的时间戳。
        :return: ``{"books": [...], "entries": {book_name: [...]}, "skipped": [...]}``
        """
        books = []
        entries = {}
        skipped = []

        for dir_path, file_name in iter_files(book_fix_dir):
            book_name = get_filename(file_name)
            book_fix_file = os.path.join(dir_path, file_name)

            rel = os.path.relpath(book_fix_file, book_fix_dir)
            book_file = os.path.join(book_dir, rel)
            if not os.path.isfile(book_file):
                # 文件不存在时不处理
                skipped.append(book_fix_file)
                continue

            patch_file = os.path.join(dir_path, f"【专有词条】{book_name}.patch")
            book_words = gen_diff_words_map(
                patch_file,
                book_fix_file,
                book_file,
                context_len=5,
                trim_orig_str=False,
                option=self.option,
            )

            # 同时检查并写入单独的书籍词库文件
            orig_book_name = remove_epub_merge_prefix_fn(book_name)
            merged = merge_to_book_map_file(
                orig_book_name, book_words, self.map_root, self.option, timestamp
            )

            entries[orig_book_name] = book_words
            books.append(
                {
                    "book": orig_book_name,
                    "source": book_fix_file,
                    "patch": patch_file,
                    "entry_count": len(book_words),
                    "merged": merged,
                }
            )

        return {"books": books, "entries": entries, "skipped": skipped}

    def generate_book_maps_for_files(
        self,
        pairs,
        timestamp: float | None = None,
    ) -> dict:
        """按给定清单生成词库表。

        :param pairs: ``[(fix 文件路径, 原文件路径), ...]``。
        :return: 同 :meth:`generate_book_maps`。
        """
        books = []
        entries = {}
        skipped = []

        for book_fix_file, book_file in pairs:
            book_name = get_filename(book_fix_file)
            patch_file = os.path.join(
                os.path.dirname(book_fix_file), f"【专有词条】{book_name}.patch"
            )
            if not os.path.isfile(book_file):
                skipped.append(book_fix_file)
                continue

            book_words = gen_diff_words_map(
                patch_file,
                book_fix_file,
                book_file,
                context_len=5,
                trim_orig_str=False,
                option=self.option,
            )
            orig_book_name = remove_epub_merge_prefix_fn(book_name)
            merged = merge_to_book_map_file(
                orig_book_name, book_words, self.map_root, self.option, timestamp
            )
            entries[orig_book_name] = book_words
            books.append(
                {
                    "book": orig_book_name,
                    "source": book_fix_file,
                    "patch": patch_file,
                    "entry_count": len(book_words),
                    "merged": merged,
                }
            )

        return {"books": books, "entries": entries, "skipped": skipped}

    # ------------------------------------------------------------------ #
    # 专有词频率统计
    # ------------------------------------------------------------------ #
    def gen_replace_count_report(
        self,
        book_dir: str,
        book_bak_dir: str,
        report_dir: str,
        temp_map_file: str,
    ) -> dict:
        """生成专有词频率统计报告（对应上游同名方法）。"""
        return gen_replace_count_report(
            book_dir,
            book_bak_dir,
            report_dir,
            temp_map_file,
            self.option,
        )
