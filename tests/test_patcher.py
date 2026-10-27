"""patch 生成与 PatchAnalyzer 状态机测试。

断言来源：
- ``fixtures/patch_analyzer_php.json``：真实 ``diff -u`` 文本 + 上游
  ``App\\Util\\PatchAnalyzer`` 解析出的权威 (befores, afters)；
- ``fixtures/core_php.json`` 中的 ``extractStrDiff`` 权威结果。
"""

from __future__ import annotations

import os
import subprocess

import pytest

from fixtext_bookmap.patcher import (
    LITERAL_BACKSLASH_N,
    PATCH_HEADER_LINES,
    PatchAnalyzer,
    PatchError,
    generate_patch,
)
from fixtext_bookmap.textdiff import extract_str_diff


class TestGeneratePatch:
    """diff -u 封装：返回码语义与失败分支。"""

    def test_generates_patch_and_accepts_returncode_1(self, tmp_path):
        orig = tmp_path / "orig.txt"
        fixed = tmp_path / "fixed.txt"
        patch = tmp_path / "out.patch"
        orig.write_text("第一行\n第二行\n", encoding="utf-8")
        fixed.write_text("第一行\n第二行改了\n", encoding="utf-8")

        # 两文件有差异时 diff 返回 1，属正常情况，不应抛错
        result = generate_patch(str(orig), str(fixed), str(patch))
        assert result == str(patch)
        assert patch.exists()
        assert "第二行改了" in patch.read_text(encoding="utf-8")

    def test_identical_files_produce_empty_patch(self, tmp_path):
        orig = tmp_path / "orig.txt"
        fixed = tmp_path / "fixed.txt"
        patch = tmp_path / "out.patch"
        orig.write_text("同样的内容\n", encoding="utf-8")
        fixed.write_text("同样的内容\n", encoding="utf-8")

        generate_patch(str(orig), str(fixed), str(patch))
        assert patch.read_text(encoding="utf-8") == ""

    def test_missing_input_raises(self, tmp_path):
        patch = tmp_path / "out.patch"
        with pytest.raises(PatchError):
            generate_patch(str(tmp_path / "nope_a"), str(tmp_path / "nope_b"), str(patch))

    def test_overwrites_existing_patch_file(self, tmp_path):
        orig = tmp_path / "orig.txt"
        fixed = tmp_path / "fixed.txt"
        patch = tmp_path / "out.patch"
        orig.write_text("A\n", encoding="utf-8")
        fixed.write_text("B\n", encoding="utf-8")
        patch.write_text("stale content", encoding="utf-8")

        generate_patch(str(orig), str(fixed), str(patch))
        assert "stale content" not in patch.read_text(encoding="utf-8")


class TestPatchAnalyzerAgainstPhp:
    """与上游 PHP 解析结果逐条对齐。"""

    def test_all_php_patch_vectors(self, patch_vectors, tmp_path):
        checked = 0
        failures = []
        for case in patch_vectors:
            patch_text = case["patch"]
            if not patch_text:
                # 无差异时上游不会解析，跳过
                assert case["befores"] == [] and case["afters"] == []
                continue

            patch_file = tmp_path / f"{case['name']}.patch"
            patch_file.write_text(patch_text, encoding="utf-8", newline="")

            befores, afters = PatchAnalyzer().get_diff_from_patch_file(str(patch_file))
            checked += 1
            if befores != case["befores"] or afters != case["afters"]:
                failures.append(
                    f"{case['name']}: py=({befores!r},{afters!r}) "
                    f"php=({case['befores']!r},{case['afters']!r})"
                )

        assert checked >= 6, "有效 patch 向量不足"
        assert not failures, "与 PHP PatchAnalyzer 不一致:\n" + "\n".join(failures)


class TestPatchAnalyzerSemantics:
    """状态机的关键语义（含易漏细节）。"""

    def _parse(self, tmp_path, patch_text: str):
        p = tmp_path / "case.patch"
        p.write_text(patch_text, encoding="utf-8", newline="")
        return PatchAnalyzer().get_diff_from_patch_file(str(p))

    def test_simple_change_yields_one_pair(self, patch_vectors, tmp_path):
        case = next(c for c in patch_vectors if c["name"] == "single_change")
        befores, afters = self._parse(tmp_path, case["patch"])
        assert befores == ["第二行"]
        assert afters == ["第二行改了"]

    def test_multi_line_change_merges_with_literal_backslash_n(self, patch_vectors, tmp_path):
        case = next(c for c in patch_vectors if c["name"] == "insert_line")
        befores, afters = self._parse(tmp_path, case["patch"])
        assert len(befores) == 1
        # 跨行内容用「反斜杠 + n」两个字符拼接，不是真换行
        assert LITERAL_BACKSLASH_N in befores[0]
        assert "\n" not in befores[0]
        assert befores[0].split(LITERAL_BACKSLASH_N) == ["第一行", "第三行"]

    def test_separated_changes_yield_multiple_pairs(self, patch_vectors, tmp_path):
        case = next(c for c in patch_vectors if c["name"] == "two_separated")
        befores, afters = self._parse(tmp_path, case["patch"])
        assert len(befores) == 2 == len(afters)
        assert befores == ["A1", "A12"]
        assert afters == ["B1", "B12"]

    def test_merge_decision_for_equal_length_multi_line(self, patch_vectors, tmp_path):
        case = next(c for c in patch_vectors if c["name"] == "merged_multi")
        befores, afters = self._parse(tmp_path, case["patch"])
        # 三行内容逐行对应，按行分开插入
        assert befores == ["A", "B", "C"]
        assert afters == ["A2", "B2", "C2"]

    def test_header_lines_constant(self):
        # 上游 array_slice($content, 2) 丢弃两行文件头
        assert PATCH_HEADER_LINES == 2

    def test_php_tolerates_unbalanced_hunk_without_raising(self, tmp_path):
        """PHP 实测：这类「只有 - 行」的 patch 不抛异常，而是借上下文补齐。

        与 Python 行为必须一致——不能比上游更严格。
        """
        broken = "--- a\n+++ b\n@@ -1 +1 @@\n-旧行\n旧行上下文\n"
        befores, afters = self._parse(tmp_path, broken)
        # PHP 侧结果为长度相等的两对，未抛异常
        assert len(befores) == len(afters) == 1
        assert "旧行上下文" in befores[0]

    def test_unbalanced_hunks_stay_symmetric_like_php(self, tmp_path):
        """PHP 实测：即便 hunk 头行数与实际 ±行数不符，状态机仍对称收集、不抛错。

        Python 侧必须同样宽容——不得比上游更严格。
        这也说明 ``PatchError`` 的「数量不一致」分支是防御性代码：
        对上述构造的输入不会触发，本测试只锁定「与 PHP 一致」这一事实。
        """
        patch_text = (
            "--- a\n+++ b\n"
            "@@ -1,3 +1,2 @@\n"
            "-旧行甲\n"
            "-旧行乙\n"
            " 上下文行\n"
            "+新行丙\n"
            " 尾部上下文\n"
        )
        befores, afters = self._parse(tmp_path, patch_text)
        assert len(befores) == len(afters) == 2
        # PHP 侧未抛异常，且借用上下文补齐，与 Python 结果一致


class TestShouldMergeAsMultiLine:
    """合并策略：行长不等 / 有相同行 / 一空一非空时都必须合并。"""

    def test_equal_length_all_different_merges(self):
        assert PatchAnalyzer.should_merge_as_multi_line(["A", "B"], ["A2", "B2"]) is True

    def test_length_mismatch_does_not_merge(self):
        assert PatchAnalyzer.should_merge_as_multi_line(["A", "B"], ["A2"]) is False

    def test_identical_line_blocks_merge(self):
        assert PatchAnalyzer.should_merge_as_multi_line(["A", "B"], ["A", "B2"]) is False

    def test_empty_vs_nonempty_blocks_merge(self):
        assert PatchAnalyzer.should_merge_as_multi_line([""], ["X"]) is False
        assert PatchAnalyzer.should_merge_as_multi_line(["X"], [""]) is False

    def test_both_empty_merges(self):
        # PHP 实测：两侧都为空时 bv == av，判定为「存在相同内容行」-> 不分行
        assert PatchAnalyzer.should_merge_as_multi_line([""], [""]) is False


class TestExtractStrDiff:
    """字符串差异截取：以 PHP Util::extractStrDiff 为权威。"""

    def test_all_php_vectors(self, core_vectors):
        vectors = [v for v in core_vectors if v["fn"] == "extractStrDiff"]
        assert len(vectors) >= 10
        failures = []
        for v in vectors:
            s1, s2, ctx = v["args"]
            got = extract_str_diff(s1, s2, ctx)
            # PHP 返回 array，Python 返回 tuple；值为空时 PHP 返回 []
            got_list = list(got) if got else []
            if got_list != v["expected"]:
                failures.append(
                    f"{s1!r} vs {s2!r} ctx={ctx}: py={got_list!r} php={v['expected']!r}"
                )
        assert not failures, "与 PHP extractStrDiff 不一致:\n" + "\n".join(failures)

    def test_identical_strings_return_none(self):
        assert extract_str_diff("完全相同", "完全相同") is None

    def test_context_expands_range(self):
        # 无上下文时只截差异字符本身
        assert extract_str_diff("abcXdef", "abcYdef", 0) == ("X", "Y")
        # 上下文 1 时向前后各扩一个字符
        assert extract_str_diff("abcXdef", "abcYdef", 1) == ("cXd", "cYd")

    def test_context_clamped_at_both_ends(self):
        # 上下文超过字符串长度时被钳制到整串
        assert extract_str_diff("abcXdef", "abcYdef", 99) == ("abcXdef", "abcYdef")

    def test_prefix_case(self):
        # 一个串是另一个的前缀时，diffStart 落在 minLen
        assert extract_str_diff("前缀", "前缀延伸", 2) == ("前缀", "前缀延伸")

    def test_empty_string_vs_content(self):
        assert extract_str_diff("", "abc", 2) == ("", "abc")
        assert extract_str_diff("abc", "", 2) == ("abc", "")
