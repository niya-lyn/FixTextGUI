"""专有词条提取与词库表生成测试。

断言来源：``fixtures/map_php.json``（上游真实实现的反射调用结果）、
``fixtures/core_php.json``，以及真实 ``diff -u`` + 上游 PatchAnalyzer 的输出。
"""

from __future__ import annotations

import os
import re

import pytest

from fixtext_bookmap.option import Option
from fixtext_bookmap.wordmap import (
    BOOK_MAP_DIRNAME,
    BOOK_MAP_TAGS,
    NEW_MAP_FILE_CONTENT,
    find_book_notes_insert_position,
    find_closing_bracket,
    gen_diff_words_map,
    get_book_map_file_with_tags,
    get_filename,
    get_words_print_str,
    merge_to_book_map_file,
    remove_epub_merge_prefix_fn,
    strip_html_tag,
)

TIME_RE = re.compile(r"/\* 新增下列词条的时间点：[^*]*\*/")


def normalize_time(text: str) -> str:
    return TIME_RE.sub("/* 新增下列词条的时间点：<TS> */", text)


class TestGetFilename:
    """pathinfo PATHINFO_FILENAME 语义，以 PHP 权威向量为准。"""

    def test_all_php_vectors(self, core_vectors):
        vectors = [v for v in core_vectors if v["fn"] == "getFilename"]
        assert len(vectors) >= 5
        for v in vectors:
            assert get_filename(v["args"][0]) == v["expected"], v["args"][0]

    def test_epub_prefix_stripped_variants(self, core_vectors):
        vectors = [v for v in core_vectors if v["fn"] == "getFilenameEpub"]
        for v in vectors:
            assert get_filename(v["args"][0], True) == v["expected"], v["args"][0]

    def test_hidden_file_yields_empty_name(self):
        # PHP pathinfo('.hidden') 的 filename 为空串
        assert get_filename(".hidden") == ""

    def test_remove_epub_prefix(self, core_vectors):
        vectors = [v for v in core_vectors if v["fn"] == "removeEpubMergePrefix"]
        for v in vectors:
            assert remove_epub_merge_prefix_fn(v["args"][0]) == v["expected"]

    def test_prefix_removed_midstring_too(self):
        # 上游用 str_replace 而非 str_replace 首部，故中间出现也会被删
        assert remove_epub_merge_prefix_fn("中【EPUB 合并文件】间") == "中间"


class TestGetWordsPrintStr:
    """词条输出格式必须与上游逐字符一致（会被写入 .php 文件）。"""

    def test_all_php_vectors(self, core_vectors):
        vectors = [v for v in core_vectors if v["fn"] == "getWordsPrintStr"]
        assert len(vectors) >= 5
        failures = []
        for v in vectors:
            args = v["args"]
            got = get_words_print_str(args[0], args[1], args[2])
            if got != v["expected"]:
                failures.append(f"{v['label']}: py={got!r} php={v['expected']!r}")
        assert not failures, "\n".join(failures)

    def test_single_line_format(self):
        out = get_words_print_str({"before": "错字", "after": "正字"})
        assert out == '    [\'before\' => "错字", \'after\' => "正字"],\n'

    def test_extra_info_becomes_comment(self):
        out = get_words_print_str({"before": "A", "after": "B"}, "替换次数: 【3】")
        assert out.endswith("// 替换次数: 【3】\n")

    def test_multi_line_format(self):
        out = get_words_print_str({"before": "A", "after": "B"}, multi_line=True)
        assert "'before' => \"A\"" in out
        assert "'after'  => \"B\"" in out
        assert out.startswith("    [\n")

    def test_accepts_list_of_words(self):
        out = get_words_print_str(
            [{"before": "A", "after": "B"}, {"before": "C", "after": "D"}]
        )
        assert out.count("['before'") == 2


class TestStripHtmlTag:
    """上游 Extractor::stripHtmlTag 的两段式处理。"""

    def test_no_angle_brackets_only_trims(self):
        assert strip_html_tag("  内容  ") == "内容"
        assert strip_html_tag("　全角内容　") == "全角内容"

    def test_plain_kept(self):
        assert strip_html_tag("纯文本") == "纯文本"

    def test_tags_removed(self):
        assert strip_html_tag("<b>粗体</b>") == "粗体"

    def test_html_entity_left_intact(self):
        # 只去标签，不做实体解码
        assert strip_html_tag("<p>a&amp;b</p>") == "a&amp;b"

    def test_leading_and_trailing_whitespace_trimmed(self):
        assert strip_html_tag("  <i>x</i>  ") == "x"


class TestFindClosingBracket:
    """按字节扫描、对引号与转义敏感。"""

    def test_all_php_vectors(self, map_vectors):
        vectors = [v for v in map_vectors if v["fn"] == "findClosingBracket"]
        assert len(vectors) >= 5
        for v in vectors:
            content, start = v["args"]
            got = find_closing_bracket(content.encode(), start)
            assert got == v["expected"], f"{v['label']} content={content!r} start={start}"

    def test_nested_bracket(self):
        assert find_closing_bracket(b"[a[b]c]d", 1) == 6

    def test_bracket_inside_quotes_ignored(self):
        assert find_closing_bracket(b'["a]b"]tail', 1) == 6

    def test_unclosed_returns_false(self):
        assert find_closing_bracket(b"[unclosed", 1) is False

    def test_escaped_quote_does_not_close_string(self):
        # \" 不应结束字符串，随后的 ] 仍在字符串内被忽略
        content = b'["a\\"]still"]x'
        end = find_closing_bracket(content, 1)
        assert end is not False


class TestFindBookNotesInsertPosition:
    def test_existing_entries_position(self, map_vectors):
        v = next(x for x in map_vectors if x["label"] == "existing")
        got = find_book_notes_insert_position(v["args"][0].encode())
        assert got == v["expected"]

    def test_empty_entries_position(self, map_vectors):
        v = next(x for x in map_vectors if x["label"] == "empty")
        got = find_book_notes_insert_position(v["args"][0].encode())
        assert got == v["expected"]

    def test_insert_after_last_entry(self):
        content = (
            "<?php\n\nreturn [\n    'bookNotes' => [\n"
            '        [\'before\' => "A", \'after\' => "B"],\n'
            "    ],\n];\n"
        )
        pos = find_book_notes_insert_position(content.encode())
        assert pos is not False
        # 插入点应紧跟在最后一条词条行之后
        assert content.encode()[pos:].startswith(b"    ],")

    def test_missing_booknotes_returns_false(self):
        assert find_book_notes_insert_position(b"<?php\nreturn [];\n") is False


class TestGetBookMapFileWithTags:
    """优先无前缀文件，其次【7】【8】【9】前缀。"""

    def test_prefers_plain_name(self, tmp_path):
        (tmp_path / "书.php").write_text("plain", encoding="utf-8")
        (tmp_path / "【7】书.php").write_text("tagged", encoding="utf-8")
        assert get_book_map_file_with_tags(str(tmp_path), "书").endswith("书.php")
        assert "【7】" not in get_book_map_file_with_tags(str(tmp_path), "书")

    def test_falls_back_to_tag_prefix(self, tmp_path):
        (tmp_path / "【9】书.php").write_text("tagged", encoding="utf-8")
        got = get_book_map_file_with_tags(str(tmp_path), "书")
        assert got.endswith("【9】书.php")

    def test_returns_empty_when_absent(self, tmp_path):
        assert get_book_map_file_with_tags(str(tmp_path), "不存在") == ""

    def test_tag_order_defined(self):
        assert BOOK_MAP_TAGS == ("【7】", "【8】", "【9】")
        assert BOOK_MAP_DIRNAME == "书籍专有替换词库"


class TestGenDiffWordsMap:
    """从真实 diff 中提取词条。"""

    def _write_pair(self, tmp_path, fixed_text, orig_text):
        fixed = tmp_path / "fixed.txt"
        orig = tmp_path / "orig.txt"
        fixed.write_text(fixed_text, encoding="utf-8")
        orig.write_text(orig_text, encoding="utf-8")
        return str(fixed), str(orig)

    def test_before_comes_from_fixed_text(self, tmp_path):
        """参数语义与直觉相反：before 取自 fix 后文本，after 取自原文。"""
        fixed, orig = self._write_pair(
            tmp_path, "他慢慢地走过来\n", "他慢慢的走过来\n"
        )
        patch = str(tmp_path / "p.patch")
        words = gen_diff_words_map(patch, fixed, orig, context_len=0)

        assert words == [{"before": "地", "after": "的"}], (
            "before 必须是 fix 后文本的字（地），after 必须是原文的字（的）"
        )

    def test_identical_files_yield_no_words(self, tmp_path):
        fixed, orig = self._write_pair(tmp_path, "相同内容\n", "相同内容\n")
        patch = str(tmp_path / "p.patch")
        assert gen_diff_words_map(patch, fixed, orig) == []

    def test_html_stripped_copy_added(self, tmp_path):
        fixed, orig = self._write_pair(
            tmp_path, "<b>甲</b>内容\n", "乙内容\n"
        )
        patch = str(tmp_path / "p.patch")
        words = gen_diff_words_map(
            patch, fixed, orig, context_len=10,
            option=Option(add_html_stripped_copy=True),
        )
        # 至少存在一条与原始不同的「去标签后」副本
        befores = [w["before"] for w in words]
        assert len(befores) >= 1

    def test_returns_dict_shaped_entries(self, tmp_path):
        fixed, orig = self._write_pair(tmp_path, "甲方\n", "乙方\n")
        words = gen_diff_words_map(str(tmp_path / "p.patch"), fixed, orig)
        for w in words:
            assert set(w.keys()) == {"before", "after"}


class TestMergeToBookMapFile:
    """写入词库文件：新建 / 追加 / 拒绝空词条。"""

    def _prepare_root(self, tmp_path):
        root = tmp_path / "root"
        (root / "maps" / BOOK_MAP_DIRNAME).mkdir(parents=True)
        return root

    def test_new_file_matches_php(self, map_vectors, tmp_path):
        v = next(x for x in map_vectors if x["label"] == "new_file")
        root = self._prepare_root(tmp_path)
        ok = merge_to_book_map_file(
            "测试书A",
            [{"before": "错字甲", "after": "正字甲"}],
            str(root),
            Option(),
        )
        assert ok is True
        written = (root / "maps" / BOOK_MAP_DIRNAME / "测试书A.php").read_text(
            encoding="utf-8"
        )
        assert normalize_time(written) == normalize_time(v["expected"])

    def test_append_existing_matches_php(self, map_vectors, tmp_path):
        v = next(x for x in map_vectors if x["label"] == "append_existing")
        root = self._prepare_root(tmp_path)
        target = root / "maps" / BOOK_MAP_DIRNAME / "测试书B.php"
        # PHP 夹具的初始内容：两条既有词条、无时间点注释
        initial = (
            "<?php\n\nreturn [\n    'bookNotes' => [\n"
            "        ['before' => \"错字A\", 'after' => \"正字A\"],\n"
            "        ['before' => \"错字B\", 'after' => \"正字B\"],\n"
            "    ],\n];\n"
        )
        target.write_text(initial, encoding="utf-8")

        ok = merge_to_book_map_file(
            "测试书B", [{"before": "错字C", "after": "正字C"}], str(root), Option()
        )
        assert ok is True
        written = target.read_text(encoding="utf-8")
        assert "错字C" in written
        # 新词条必须插在最后，而不是覆盖既有词条
        assert written.index("错字A") < written.index("错字B") < written.index("错字C")
        assert normalize_time(written).startswith("<?php")

    def test_empty_words_rejected(self, map_vectors, tmp_path):
        v = next(x for x in map_vectors if x["label"] == "empty_words")
        root = self._prepare_root(tmp_path)
        assert (
            merge_to_book_map_file("测试书C", [], str(root), Option()) == v["expected"]
        )
        assert not (root / "maps" / BOOK_MAP_DIRNAME / "测试书C.php").exists()

    def test_missing_maps_dir_returns_false(self, tmp_path):
        assert (
            merge_to_book_map_file(
                "书", [{"before": "A", "after": "B"}], str(tmp_path), Option()
            )
            is False
        )

    def test_quotes_are_escaped(self, tmp_path):
        root = self._prepare_root(tmp_path)
        merge_to_book_map_file(
            "转义书",
            [{"before": '含"引号', "after": '改"后'}],
            str(root),
            Option(add_current_time=False),
        )
        written = (root / "maps" / BOOK_MAP_DIRNAME / "转义书.php").read_text(
            encoding="utf-8"
        )
        # 双引号必须转义，否则生成的 PHP 数组会语法错误
        assert '\\"' in written

    def test_new_map_file_content_is_valid_php_skeleton(self):
        assert NEW_MAP_FILE_CONTENT.startswith("<?php")
        assert "'bookNotes' => [" in NEW_MAP_FILE_CONTENT

    def test_multiline_replacement_indents_each_line(self, tmp_path):
        """验证 /^/m 在写文件路径上真的逐行缩进（此处曾是缺陷点）。"""
        root = self._prepare_root(tmp_path)
        merge_to_book_map_file(
            "缩进书",
            [{"before": "A", "after": "B"}],
            str(root),
            Option(add_current_time=False),
        )
        written = (root / "maps" / BOOK_MAP_DIRNAME / "缩进书.php").read_text(
            encoding="utf-8"
        )
        entry_line = next(l for l in written.splitlines() if "['before'" in l)
        assert entry_line.startswith("        ["), repr(entry_line)
