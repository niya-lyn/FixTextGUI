"""生成 GBK / GB18030 / Big5 / 换行 / BOM 样本（全部由云盘已有语料转码而来，不引入外部内容）。

用法：
    python3 tools/make_samples.py <语料目录> <输出目录>

注意：真实语料里含少量 GBK 无法编码的字符（如 U+2022 项目符号），
构造 GBK 样本时**只保留该字符集能表示的字符**并记录丢弃字符数——
这样样本是"真实的 GBK 文件"，而不是强行 replace 出 '?' 的假样本。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _encodable_only(text: str, codec: str) -> tuple[str, int]:
    """返回 (只含该字符集可表示字符的文本, 丢弃字符数)。"""
    kept: list[str] = []
    dropped = 0
    for ch in text:
        try:
            ch.encode(codec)
        except UnicodeEncodeError:
            dropped += 1
            continue
        kept.append(ch)
    return "".join(kept), dropped


def build(corpus_dir: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"samples": []}

    src = corpus_dir / "nahan.txt"          # 鲁迅《呐喊》：短篇，便于逐字核对
    raw = src.read_text(encoding="utf-8")
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    raw = raw.replace("\r\n", "\n")

    def emit(name: str, data: bytes, expect: str, note: str, dropped: int = 0) -> None:
        p = out_dir / name
        p.write_bytes(data)
        item = {
            "file": name,
            "bytes": len(data),
            "expected": expect,
            "note": note,
            "source": src.name,
        }
        if dropped:
            item["dropped_chars"] = dropped
        manifest["samples"].append(item)

    emit("a_utf8_lf.txt", raw.encode("utf-8"), "utf-8", "原文转 LF")
    emit("b_utf8_bom.txt", b"\xef\xbb\xbf" + raw.encode("utf-8"), "utf-8", "UTF-8 带 BOM")
    emit("c_utf8_crlf.txt", raw.replace("\n", "\r\n").encode("utf-8"), "utf-8", "UTF-8 + CRLF")

    gbk_text, gbk_dropped = _encodable_only(raw, "gbk")
    emit("d_gbk_crlf.txt", gbk_text.replace("\n", "\r\n").encode("gbk"),
         "gbk", "GBK 编码 + CRLF（Windows 常见）", gbk_dropped)
    emit("e_gbk_lf.txt", gbk_text.encode("gbk"), "gbk", "GBK 编码 + LF", gbk_dropped)

    # GB18030：追加 GBK 无法编码的字符（4 字节区），确保判定为 GB18030 而不是 GBK
    rare = "𠀀𠀁𠀂𪚥"
    gb18030_text = gbk_text[:5000] + "\n\n罕见字样例：" + rare + "\n" + gbk_text[5000:]
    data = gb18030_text.encode("gb18030")
    try:
        gb18030_text.encode("gbk")
        raise SystemExit("样例构造失败：GBK 竟能编码 4 字节字符")
    except UnicodeEncodeError:
        pass
    emit("f_gb18030_4byte.txt", data, "gb18030", "GB18030 含 4 字节字符（GBK 无法编码）", gbk_dropped)

    # 混合换行：CRLF 与 LF 交错
    lines = raw.split("\n")
    half = len(lines) // 2
    mixed_text = "\r\n".join(lines[:half]) + "\n" + "\n".join(lines[half:])
    emit("g_mixed_newline.txt", mixed_text.encode("utf-8"), "utf-8", "CRLF 与 LF 混用")

    # Big5：取一段繁体语料（聊斋）转码，同样只保留 Big5 可表示字符
    tc = (corpus_dir / "liaozhai.txt").read_text(encoding="utf-8").replace("\r\n", "\n")[:20000]
    big5_text, big5_dropped = _encodable_only(tc, "big5")
    emit("h_big5.txt", big5_text.encode("big5"), "big5", "繁体 Big5 编码", big5_dropped)

    emit("i_empty.txt", b"", "utf-8", "空文件")

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    corpus = Path(sys.argv[1])
    out = Path(sys.argv[2])
    m = build(corpus, out)
    for s in m["samples"]:
        extra = f" 丢弃{s['dropped_chars']}字符" if s.get("dropped_chars") else ""
        print(f"{s['file']:22} {s['bytes']:>8} 期望={s['expected']:8}{extra}  {s['note']}")
