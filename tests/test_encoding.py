"""验收② 编码自动识别：UTF-8 / GBK / GB18030 零配置正确识别。

样本全部来自云盘已有语料《呐喊》的转码（见 tools/make_samples.py），
不是凭空构造的假数据。

判据说明：不看"能不能解码"（GB18030 几乎什么都能解），而是把识别结果解出的
正文与同一本书的 UTF-8 参照逐字比对——相似度低就说明字符集判错了。
"""

from __future__ import annotations

import difflib
import json

import pytest

from fixtext_import.encoding import decode_file, probe


def _manifest(samples_dir) -> dict[str, dict]:
    data = json.loads((samples_dir / "manifest.json").read_text(encoding="utf-8"))
    return {row["file"]: row for row in data["samples"]}


CASE_ORDER = [
    "a_utf8_lf.txt",
    "b_utf8_bom.txt",
    "c_utf8_crlf.txt",
    "d_gbk_crlf.txt",
    "e_gbk_lf.txt",
    "f_gb18030_4byte.txt",
    "g_mixed_newline.txt",
    "h_big5.txt",
    "i_empty.txt",
]


def _base_codec(codec: str) -> str:
    """utf-8-sig 归到 utf-8：两者是同一字符族，带标记只是多了文件头声明。"""
    return codec.replace("-sig", "")


@pytest.mark.parametrize("name", CASE_ORDER)
def test_encoding_identified(sample, samples_dir, name):
    """每个样本按 manifest 的期望字符集被识别出来。"""
    expected = _manifest(samples_dir)[name]["expected"]
    got = probe(sample(name))
    assert _base_codec(got.codec) == expected, (
        f"{name}: 期望 {expected}，实际 {got.codec}（依据：{got.evidence}）"
    )


def _normalized(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")


@pytest.mark.parametrize("name", ["b_utf8_bom.txt", "c_utf8_crlf.txt", "g_mixed_newline.txt"])
def test_utf8_variants_decode_identically(sample, name):
    """UTF-8 的各种变体（BOM / CRLF / 混合换行）解出的正文与参照完全一致。"""
    ref = _normalized(decode_file(sample("a_utf8_lf.txt"), "utf-8"))
    got = _normalized(decode_file(sample(name), probe(sample(name)).codec))
    assert got == ref, f"{name}: 与 UTF-8 参照不一致"


@pytest.mark.parametrize("name,dropped", [("d_gbk_crlf.txt", 58), ("e_gbk_lf.txt", 58),
                                          ("f_gb18030_4byte.txt", 58)])
def test_non_utf8_decodes_to_same_text(sample, name, dropped):
    """GBK / GB18030 解出的正文必须与 UTF-8 参照几乎逐字相同。

    允许的差异只有样本构造时**无法被该字符集表示**而被丢弃的字符数（manifest 记录），
    这是字符集的客观限制，不是识别错误。
    """
    ref = _normalized(decode_file(sample("a_utf8_lf.txt"), "utf-8"))
    result = probe(sample(name))
    got = _normalized(decode_file(sample(name), result.codec))
    assert "\ufffd" not in got, f"{name}: 出现替换符，说明字符集判错了"

    ratio = difflib.SequenceMatcher(None, ref, got, autojunk=False).ratio()
    assert ratio > 0.999, f"{name}: 与参照相似度仅 {ratio:.5f}，识别有误（{result.codec}）"

    # 差异量也要与 manifest 记录的丢弃字符数量级一致（防止"相似度虚高"）
    lost = len(ref) - len(got)
    assert abs(lost - dropped) <= dropped * 0.5, f"{name}: 丢字 {lost}，manifest 记 {dropped}"


def test_gb18030_not_confused_with_gbk(sample):
    """含 4 字节字符的 GB18030 不能被降级标成 GBK（GBK 解不了它）。"""
    r = probe(sample("f_gb18030_4byte.txt"))
    assert r.codec == "gb18030"
    assert r.certain, "GBK 解不了、GB18030 能解，这是事实性判定，应标记为确定"


def test_big5_not_misjudged_as_gb18030(sample):
    """Big5 繁体文件：GB18030 在技术上"能解"，但可读性仲裁必须选中 Big5。

    这是本轮踩到的真实坑：只靠"能否解码"会把繁体书判成国标编码。
    """
    r = probe(sample("h_big5.txt"))
    assert r.codec == "big5"
    assert r.scores["gb18030"] < r.scores["big5"], f"可读性打分应支持 Big5：{r.scores}"


def test_bom_detected_without_guessing(sample):
    """带标记文件的判定依据是文件头标记，不是猜测。"""
    r = probe(sample("b_utf8_bom.txt"))
    assert r.confidence == "bom"
    assert r.has_bom


def test_empty_file_is_handled(sample):
    r = probe(sample("i_empty.txt"))
    assert _base_codec(r.codec) == "utf-8"
    assert not r.has_bom


def test_probe_never_modifies_source(sample):
    """探测只读：前后 sha256 必须一致。"""
    from fixtext_import.textfile import sha256_file

    p = sample("d_gbk_crlf.txt")
    before = sha256_file(p)
    probe(p)
    decode_file(p, "gbk")
    assert sha256_file(p) == before
