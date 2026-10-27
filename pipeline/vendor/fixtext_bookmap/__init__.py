"""FixText 专有词库生成（Python 重实现）。

本包以独立模块的形式重实现了 FixText（PHP）的「专有词库生成」能力：
1. 专有词频率统计（替换次数报告）；
2. 词库表生成（``maps/书籍专有替换词库/<书名>.php``）。

规则严格以源码 PHP 实现为准（FixText/src/app/Service/Diff/Extractor.php
及 app/Util/{PatchAnalyzer,Util}.php），所有 PHP 特有语义均在
:mod:`fixtext_bookmap.phpcompat` 中显式复刻。

典型用法::

    from fixtext_bookmap import BookMapGenerator, Option

    gen = BookMapGenerator(option=Option(), map_root="/path/to/FixText")
    result = gen.generate_book_maps(
        book_fix_dir="/path/to/FixText/booksFix",
        book_dir="/path/to/FixText/books",
    )
"""

from __future__ import annotations

from .frequency import (
    SPLIT_MARK,
    build_replace_count_report,
    count_word_frequencies,
    custom_trim_diff,
    gen_replace_count_report,
    merge_reports_to_temp_map_file,
)
from .generator import BookMapGenerator, iter_files
from .option import Option
from .patcher import PatchAnalyzer, PatchError, generate_patch
from .textdiff import extract_str_diff
from .wordmap import (
    BOOK_MAP_DIRNAME,
    BOOK_MAP_TAGS,
    find_book_notes_insert_position,
    find_closing_bracket,
    gen_diff_words_map,
    get_book_map_file_with_tags,
    get_filename,
    get_time_str,
    get_words_print_str,
    merge_to_book_map_file,
    remove_epub_merge_prefix_fn,
    strip_html_tag,
)

__version__ = "1.0.0"

__all__ = [
    "BOOK_MAP_DIRNAME",
    "BOOK_MAP_TAGS",
    "BookMapGenerator",
    "Option",
    "PatchAnalyzer",
    "PatchError",
    "SPLIT_MARK",
    "build_replace_count_report",
    "count_word_frequencies",
    "custom_trim_diff",
    "extract_str_diff",
    "find_book_notes_insert_position",
    "find_closing_bracket",
    "gen_diff_words_map",
    "gen_replace_count_report",
    "generate_patch",
    "get_book_map_file_with_tags",
    "get_filename",
    "get_time_str",
    "get_words_print_str",
    "iter_files",
    "merge_reports_to_temp_map_file",
    "merge_to_book_map_file",
    "remove_epub_merge_prefix_fn",
    "strip_html_tag",
]
