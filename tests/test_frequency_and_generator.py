"""频率统计、generator 编排与端到端集成测试。"""

from __future__ import annotations

import os

import pytest

from fixtext_bookmap.frequency import (
    PUNCTUATION_CHARS,
    SPLIT_MARK,
    build_replace_count_report,
    count_word_frequencies,
    custom_trim_diff,
    gen_replace_count_report,
    merge_reports_to_temp_map_file,
)
from fixtext_bookmap.generator import DEFAULT_EXTENSIONS, BookMapGenerator, iter_files
from fixtext_bookmap.option import Option
from fixtext_bookmap.wordmap import BOOK_MAP_DIRNAME


class TestConstants:
    def test_split_mark(self):
        # 分隔符是上游字面量，改动会破坏报告解析
        assert SPLIT_MARK == "【FixText 替换为】"

    def test_punctuation_charset(self):
        assert PUNCTUATION_CHARS == "　，。“”…！？、"

    def test_default_extensions_only_txt(self):
        assert DEFAULT_EXTENSIONS == (".txt",)


class TestCountWordFrequencies:
    def test_counts_identical_entries(self):
        entries = [
            {"before": "地", "after": "的"},
            {"before": "地", "after": "的"},
            {"before": "甲", "after": "乙"},
        ]
        counter = count_word_frequencies(entries)
        assert counter["地" + SPLIT_MARK + "的"] == 2
        assert counter["甲" + SPLIT_MARK + "乙"] == 1

    def test_empty_entries(self):
        assert len(count_word_frequencies([])) == 0


class TestBuildReplaceCountReport:
    def test_threshold_filters(self):
        arr = ["A" + SPLIT_MARK + "B"] * 3 + ["C" + SPLIT_MARK + "D"]
        # threshold=1 时只保留出现 2 次以上的
        report = build_replace_count_report(arr, threshold=1, patch_filename="p.patch")
        assert "A" in report
        assert "'before' => \"C\"" not in report

    def test_totals_reported(self):
        arr = ["A" + SPLIT_MARK + "B"] * 3 + ["C" + SPLIT_MARK + "D"]
        report = build_replace_count_report(arr, threshold=0, patch_filename="p.patch")
        # 总替换次数 4，大于 0 的总替换次数也是 4
        assert "总替换次数：【4】" in report

    def test_sorted_descending(self):
        arr = ["少" + SPLIT_MARK + "X"] + ["多" + SPLIT_MARK + "Y"] * 5
        report = build_replace_count_report(arr, threshold=0, patch_filename="p.patch")
        assert report.index("多") < report.index("少")

    def test_quotes_escaped(self):
        arr = ['含"引号' + SPLIT_MARK + '改"后']
        report = build_replace_count_report(arr, threshold=0, patch_filename="p.patch")
        assert '\\"' in report

    def test_header_contains_filename(self):
        report = build_replace_count_report([], patch_filename="【替换次数报告】某书.patch")
        assert "【替换次数报告】某书.patch" in report


class TestCustomTrimDiff:
    def test_no_change_when_zero(self):
        assert custom_trim_diff(0, 3, "abcdef", "abcXYZ") == ("abcdef", "abcXYZ")

    def test_remove_head_when_long_enough(self):
        # context_len=3 -> 上限 5；长度 6 > 5 才裁剪
        before, after = custom_trim_diff(2, 3, "abcdef", "abcXYZ")
        assert before == "cdef"
        assert after == "cXYZ"

    def test_no_trim_when_short(self):
        # 长度 5 不大于上限 5，不裁
        assert custom_trim_diff(2, 3, "abcde", "abc12") == ("abcde", "abc12")

    def test_remove_tail(self):
        before, after = custom_trim_diff(-2, 3, "abcdef", "abcXYZ")
        assert before == "abcd"
        assert after == "abcX"


class TestMergeReportsToTempMapFile:
    def test_writes_php_array_skeleton(self, tmp_path):
        out = tmp_path / "maps" / "5.临时校对表.php"
        merge_reports_to_temp_map_file(["    // a.patch\n", "    // b.patch\n"], str(out))
        text = out.read_text(encoding="utf-8")
        assert text.startswith("<?php\n\n$tempMap = [\n")
        assert text.rstrip().endswith("];")
        assert "// ===========" in text

    def test_creates_parent_dir(self, tmp_path):
        out = tmp_path / "deep" / "nested" / "t.php"
        merge_reports_to_temp_map_file([], str(out))
        assert out.exists()


class TestIterFiles:
    def test_only_txt_and_sorted(self, tmp_path):
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "c.md").write_text("c", encoding="utf-8")

        got = [name for _dir, name in iter_files(str(tmp_path))]
        # 排序是可复现性保证（上游为文件系统顺序，属唯一有意差异）
        assert got == ["a.txt", "b.txt"]

    def test_recurses_subdirectories(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "x.txt").write_text("x", encoding="utf-8")
        got = [name for _dir, name in iter_files(str(tmp_path))]
        assert got == ["x.txt"]

    def test_missing_dir_returns_empty(self, tmp_path):
        assert iter_files(str(tmp_path / "nope")) == []


class TestBookMapGeneratorIntegration:
    """端到端：真实双文件 -> diff -> 词条 -> 词库文件。"""

    def _setup(self, tmp_path):
        books = tmp_path / "books"
        booksFix = tmp_path / "booksFix"
        root = tmp_path / "root"
        for d in (books, booksFix, root / "maps" / BOOK_MAP_DIRNAME):
            d.mkdir(parents=True)

        # 原文 -> 校正后：的/地 误用 + 一处错别字
        (books / "测试书.txt").write_text(
            "他慢慢的走过来\n这是必须的\n", encoding="utf-8"
        )
        (booksFix / "测试书.txt").write_text(
            "他慢慢地走过来\n这是必须地\n", encoding="utf-8"
        )
        return str(books), str(booksFix), str(root)

    def test_end_to_end_generates_map_file(self, tmp_path):
        books, booksFix, root = self._setup(tmp_path)
        gen = BookMapGenerator(Option(), map_root=root)
        result = gen.generate_book_maps(booksFix, books)

        assert len(result["books"]) == 1
        assert result["skipped"] == []
        book = result["books"][0]
        assert book["book"] == "测试书"
        assert book["merged"] is True
        assert book["entry_count"] > 0

        map_file = os.path.join(root, "maps", BOOK_MAP_DIRNAME, "测试书.php")
        assert os.path.isfile(map_file)
        text = open(map_file, encoding="utf-8").read()
        assert "'bookNotes' => [" in text
        assert "['before'" in text

    def test_patch_file_created_next_to_fix(self, tmp_path):
        books, booksFix, root = self._setup(tmp_path)
        BookMapGenerator(Option(), map_root=root).generate_book_maps(booksFix, books)
        # 上游 patch 落在 booksFix 目录内
        assert os.path.isfile(os.path.join(booksFix, "【专有词条】测试书.patch"))

    def test_missing_original_is_skipped(self, tmp_path):
        books, booksFix, root = self._setup(tmp_path)
        with open(os.path.join(booksFix, "孤儿.txt"), "w", encoding="utf-8") as fh:
            fh.write("无对应原文\n")
        result = BookMapGenerator(Option(), map_root=root).generate_book_maps(
            booksFix, books
        )
        assert len(result["skipped"]) == 1
        assert result["skipped"][0].endswith("孤儿.txt")

    def test_repeated_run_is_idempotent_in_entry_set(self, tmp_path):
        """重复运行只会追加同样词条，词条集合不因重跑而改变。"""
        books, booksFix, root = self._setup(tmp_path)
        gen = BookMapGenerator(Option(), map_root=root)
        first = gen.generate_book_maps(booksFix, books)
        second = gen.generate_book_maps(booksFix, books)
        # entries 是 {书名: [词条...]}，两次运行应完全一致
        assert first["entries"] == second["entries"]
        assert list(first["entries"]) == list(second["entries"])

    def test_generate_for_explicit_pairs(self, tmp_path):
        books, booksFix, root = self._setup(tmp_path)
        fix_file = os.path.join(booksFix, "测试书.txt")
        orig_file = os.path.join(books, "测试书.txt")
        result = BookMapGenerator(Option(), map_root=root).generate_book_maps_for_files(
            [(fix_file, orig_file)]
        )
        assert len(result["books"]) == 1
        assert result["books"][0]["entry_count"] > 0

    def test_replace_count_report_end_to_end(self, tmp_path):
        books, booksFix, root = self._setup(tmp_path)
        report_dir = os.path.join(root, "logs", "report")
        temp_map = os.path.join(root, "maps", "5.临时校对表.php")
        out = gen_replace_count_report(booksFix, books, report_dir, temp_map)

        assert "测试书" in out["entries"]
        assert os.path.isfile(temp_map)

        # 与上游一致：【替换次数报告】<书>.patch 里是原始 diff，不是统计正文
        report_file = os.path.join(report_dir, "【替换次数报告】测试书.patch")
        assert os.path.isfile(report_file)

        # out["reports"] 是各本书统计报告的正文列表
        assert len(out["reports"]) == 1
        assert "总替换次数" in out["reports"][0]

        # 统计正文（含替换次数）写入汇总的临时校对表
        temp_text = open(temp_map, encoding="utf-8").read()
        assert temp_text.startswith("<?php")
        assert "总替换次数" in temp_text
        assert "替换次数: 【" in temp_text
        # 报告里记录的统计总量必须与实际词条数口径一致
        assert "【2】" in temp_text


class TestDirectionConvention:
    """固化「哪个目录取 before 侧」的约定。

    上游 ``Extractor::generateBookMaps()`` 调用
    ``genDiffWordsMap($patch, $bookFixFile, $bookFile)``，因此
    ``BOOK_FIX_DIR``（booksFix）提供词条的 before 侧、``BOOK_DIR``（books）
    提供 after 侧。两个目录传反会让词条方向整体颠倒，
    且结果仍是「合法」词库文件——不会报错，只会静默产出反向替换词条。
    """

    def test_book_fix_dir_supplies_before_side(self, tmp_path):
        book_fix = tmp_path / "booksFix"
        book = tmp_path / "books"
        root = tmp_path / "root"
        book_fix.mkdir()
        book.mkdir()
        os.makedirs(os.path.join(root, "maps", BOOK_MAP_DIRNAME), exist_ok=True)

        # 改前：繁体；改后：简体（与真实基线的方向一致）
        with open(os.path.join(book_fix, "测试书.txt"), "w", encoding="utf-8") as fh:
            fh.write("第一回　說楔子敷陳大義\n")
        with open(os.path.join(book, "测试书.txt"), "w", encoding="utf-8") as fh:
            fh.write("第一回　说楔子敷陈大义\n")

        option = Option()
        option.add_current_time = False
        result = BookMapGenerator(option, map_root=str(root)).generate_book_maps(
            str(book_fix), str(book)
        )

        entries = result["entries"]["测试书"]
        assert entries, "应当提取到词条"
        assert any("說楔子敷陳大義" in e["before"] for e in entries)
        assert any("说楔子敷陈大义" in e["after"] for e in entries)
        # 方向反了：before 侧出现简体、after 侧出现繁体
        assert not any("说楔子敷陈大义" in e["before"] for e in entries)
        assert not any("說楔子敷陳大義" in e["after"] for e in entries)
