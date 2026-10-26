"""bundle 格式测试：标记生成、切分校验、字节级可逆、异常检测。"""

from __future__ import annotations

import hashlib

import pytest

from epubtext.bundle import (
    BookRecord,
    ChapterRecord,
    Ledger,
    build_book_marker,
    build_header,
    build_split_marker,
    canonical_body,
    reconstruct_chapter_bytes,
    split_bundle,
    verify_bundle,
)
from epubtext.errors import BundleFormatError

NONCE = "0123456789abcdef"


def _record(index: int, path: str, raw: bytes, eol: str = "lf", tail: str = "", bom: bool = False) -> ChapterRecord:
    return ChapterRecord(
        index=index,
        path=path,
        label=f"第{index}章",
        media_type="application/xhtml+xml",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        eol=eol,
        tail=tail,
        bom=bom,
    )


def _ledger(records: list[ChapterRecord]) -> Ledger:
    return Ledger(nonce=NONCE, books=[BookRecord(source="a.epub", title="T", identifier="i", opf_path="o.opf", opf_dir="", sha256="x", chapters=records)])


def _bundle(records: list[ChapterRecord], bodies: list[str]) -> str:
    lines = [build_header(NONCE, 1, len(records)), build_book_marker(NONCE, 0, "T", "a.epub", len(records))]
    for record, body in zip(records, bodies):
        lines.append(build_split_marker(NONCE, record.index, record.path, record.label, record.size, record.sha256))
        lines.append(body)
        lines.append("")
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    return text


def test_marker_roundtrip_basic():
    raws = [b"<html>one</html>", b"<html>two</html>"]
    bodies = [r.decode() for r in raws]
    records = [_record(0, "a/1.xhtml", raws[0]), _record(1, "a/2.xhtml", raws[1])]
    text = _bundle(records, bodies)
    chunks = split_bundle(text, _ledger(records))
    assert len(chunks) == 2
    assert [chunk.marker["path"] for chunk in chunks] == ["a/1.xhtml", "a/2.xhtml"]
    for chunk, record, raw in zip(chunks, records, raws):
        assert reconstruct_chapter_bytes(chunk, record) == raw


def test_byte_exact_restore_with_trailing_newlines():
    """章末换行被剥掉，必须按账本补回，才能 sha256 一致。"""
    raws = [b"<html>x</html>\n", b"<html>y</html>\n\n", b"<html>z</html>"]
    records = [
        _record(0, "a.xhtml", raws[0], tail="\n"),
        _record(1, "b.xhtml", raws[1], tail="\n\n"),
        _record(2, "c.xhtml", raws[2], tail=""),
    ]
    bodies = [raw.rstrip(b"\r\n").decode() for raw in raws]
    text = _bundle(records, bodies)
    chunks = split_bundle(text, _ledger(records))
    for chunk, record, raw in zip(chunks, records, raws):
        assert reconstruct_chapter_bytes(chunk, record) == raw


def test_byte_exact_restore_crlf():
    """CRLF 原文在 TXT 里被统一成 LF，还原时必须置回 CRLF。"""
    raw = b"<html>\r\n<body>\r\n<p>x</p>\r\n</body>\r\n</html>\r\n"
    record = _record(0, "a.xhtml", raw, eol="crlf", tail="\r\n")
    body = raw.rstrip(b"\r\n").replace(b"\r\n", b"\n").decode()
    text = _bundle([record], [body])
    chunks = split_bundle(text, _ledger([record]))
    assert reconstruct_chapter_bytes(chunks[0], record) == raw


def test_byte_exact_restore_bom():
    raw = b"\xef\xbb\xbf<html>x</html>\n"
    record = _record(0, "a.xhtml", raw, tail="\r\n" if False else "\n", bom=True)
    text = _bundle([record], ["<html>x</html>"])
    chunks = split_bundle(text, _ledger([record]))
    assert reconstruct_chapter_bytes(chunks[0], record) == raw


def test_edited_content_is_detected_but_still_restorable():
    """正文被改动后仍应能还原（校对就是改字），但必须如实报告为已改动。"""
    raw = b"<html>original</html>\n"
    record = _record(0, "a.xhtml", raw, tail="\n")
    text = _bundle([record], ["<html>修正后的文本</html>"])
    chunks = split_bundle(text, _ledger([record]))
    report = verify_bundle(chunks, _ledger([record]))
    assert report[0]["unchanged"] is False
    restored = reconstruct_chapter_bytes(chunks[0], record)
    assert restored == b"<html>\xe4\xbf\xae\xe6\xad\xa3\xe5\x90\x8e\xe7\x9a\x84\xe6\x96\x87\xe6\x9c\xac</html>\n"


def test_nonce_mismatch_rejected():
    records = [_record(0, "a.xhtml", b"<html>x</html>")]
    text = _bundle(records, ["<html>x</html>"]).replace(NONCE, "ffffffffffffffff", 1)
    with pytest.raises(BundleFormatError, match="nonce"):
        split_bundle(text, _ledger(records))


def test_declared_count_mismatch_rejected():
    records = [_record(0, "a.xhtml", b"<html>x</html>")]
    text = _bundle(records, ["<html>x</html>"]).replace(f"chapters=1", "chapters=9", 1)
    with pytest.raises(BundleFormatError, match="不一致"):
        split_bundle(text, _ledger(records))


def test_missing_marker_rejected():
    """少一个章节标记必须报错，而不是静默把两段正文塞进同一章。"""
    raw1, raw2 = b"<html>a</html>", b"<html>b</html>"
    records = [_record(0, "a.xhtml", raw1), _record(1, "b.xhtml", raw2)]
    text = _bundle(records, ["<html>a</html>", "<html>b</html>"])
    marker2 = build_split_marker(NONCE, 1, "b.xhtml", "第1章", len(raw2), records[1].sha256)
    text = text.replace(marker2 + "\n", "")
    with pytest.raises(BundleFormatError, match="数量不一致"):
        split_bundle(text, _ledger(records))


def test_swapped_marker_path_rejected():
    """两个标记互换位置（数量仍对）必须被 path 比对拦住。"""
    raw1, raw2 = b"<html>a</html>", b"<html>b</html>"
    records = [_record(0, "a.xhtml", raw1), _record(1, "b.xhtml", raw2)]
    text = _bundle(records, ["<html>a</html>", "<html>b</html>"])
    m1 = build_split_marker(NONCE, 0, "a.xhtml", "第0章", len(raw1), records[0].sha256)
    m2 = build_split_marker(NONCE, 1, "b.xhtml", "第1章", len(raw2), records[1].sha256)
    swapped = build_split_marker(NONCE, 0, "b.xhtml", "第0章", len(raw1), records[0].sha256)
    swapped2 = build_split_marker(NONCE, 1, "a.xhtml", "第1章", len(raw2), records[1].sha256)
    text = text.replace(m1, swapped).replace(m2, swapped2)
    with pytest.raises(BundleFormatError, match="顺序被破坏"):
        split_bundle(text, _ledger(records))


def test_duplicate_marker_index_rejected():
    """重复标记会导致数量对但索引不连续。"""
    raw1, raw2 = b"<html>a</html>", b"<html>b</html>"
    records = [_record(0, "a.xhtml", raw1), _record(1, "b.xhtml", raw2)]
    text = _bundle(records, ["<html>a</html>", "<html>b</html>"])
    m2 = build_split_marker(NONCE, 1, "b.xhtml", "第1章", len(raw2), records[1].sha256)
    dup = build_split_marker(NONCE, 0, "b.xhtml", "第0章", len(raw2), records[1].sha256)
    text = text.replace(m2, dup)
    with pytest.raises(BundleFormatError, match="索引不连续"):
        split_bundle(text, _ledger(records))


def test_missing_header_rejected():
    records = [_record(0, "a.xhtml", b"<html>x</html>")]
    text = build_split_marker(NONCE, 0, "a.xhtml", "x", 17, records[0].sha256) + "\n<html>x</html>\n"
    with pytest.raises(BundleFormatError, match="头部"):
        split_bundle(text, _ledger(records))


def test_crlf_converted_text_still_splits():
    """外部工具把整份 TXT 改成 CRLF 后，切分必须仍然正确。"""
    raw = b"<html>a</html>\n"
    record = _record(0, "a.xhtml", raw, tail="\n")
    text = _bundle([record], ["<html>a</html>"])
    crlf_text = text.replace("\n", "\r\n")
    chunks = split_bundle(crlf_text.replace("\r\n", "\n"), _ledger([record]))
    assert len(chunks) == 1
    assert reconstruct_chapter_bytes(chunks[0], record) == raw


def test_canonical_body_strips_one_separator_only():
    assert canonical_body("abc\n") == "abc"
    assert canonical_body("abc") == "abc"
    assert canonical_body("abc\n\n") == "abc\n"


def test_ledger_json_roundtrip(tmp_path):
    records = [_record(0, "OEBPS/第1章.xhtml", b"<html/>")]
    ledger = _ledger(records)
    path = ledger.save(tmp_path / "x.bundle.json")
    loaded = Ledger.load(path)
    assert loaded.nonce == NONCE
    assert loaded.chapters[0].path == "OEBPS/第1章.xhtml"
    assert loaded.chapters[0].sha256 == records[0].sha256


def test_ledger_rejects_unknown_format(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"format":"other/1","nonce":"x","books":[]}', encoding="utf-8")
    with pytest.raises(BundleFormatError, match="格式"):
        Ledger.load(path)
