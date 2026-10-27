"""FixText V1 · 文本规整与写盘（T2.2）

只有两件事：把读出来的文本**统一成一种形态**（UTF-8、无 BOM、LF 换行），
以及把结果写进内部工作区。任何情况下都不回写用户的原文件。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

STANDARD_ENCODING = "utf-8"
STANDARD_NEWLINE = "\n"


@dataclass
class NormalizedText:
    text: str
    had_bom: bool
    newline_kind: str        # "lf" | "crlf" | "cr" | "mixed"
    newline_changed: bool
    replaced_chars: int = 0  # 无法按该字符集解释的字节数（→ U+FFFD）


def detect_newline(text: str) -> str:
    """判断换行形态：lf / crlf / cr / mixed（无换行按 lf）。"""
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    kinds = [name for name, n in (("crlf", crlf), ("cr", cr), ("lf", lf)) if n > 0]
    if not kinds:
        return "lf"
    return kinds[0] if len(kinds) == 1 else "mixed"


def normalize(text: str) -> NormalizedText:
    """统一换行为 LF，剥掉残留 BOM，记录改了什么。"""
    had_bom = text.startswith("\ufeff")
    if had_bom:
        text = text[1:]
    kind = detect_newline(text)
    replaced = text.count("\ufffd")
    if kind == "lf":
        changed = False
        out = text
    else:
        changed = True
        out = text.replace("\r\n", "\n").replace("\r", "\n")
    return NormalizedText(
        text=out, had_bom=had_bom, newline_kind=kind,
        newline_changed=changed, replaced_chars=replaced,
    )


def sha256_file(path: str | Path, chunk: int = 1024 * 1024) -> str:
    """文件内容哈希（流式，不把整文件读进内存）。"""
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_text_atomic(path: str | Path, text: str) -> None:
    """原子写：先写同目录临时文件再 rename，中途失败不留半个文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding=STANDARD_ENCODING, newline=STANDARD_NEWLINE)
    os.replace(tmp, path)


def copy_verbatim(src: str | Path, dst: str | Path, chunk: int = 1024 * 1024) -> tuple[str, str]:
    """按字节复制原文件到工作区，返回 (源 sha256, 目标 sha256)。"""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    h_src = hashlib.sha256()
    h_dst = hashlib.sha256()
    tmp = dst.with_suffix(dst.suffix + ".part")
    with src.open("rb") as fi, tmp.open("wb") as fo:
        while True:
            block = fi.read(chunk)
            if not block:
                break
            h_src.update(block)
            fo.write(block)
            h_dst.update(block)
    os.replace(tmp, dst)
    return h_src.hexdigest(), h_dst.hexdigest()
