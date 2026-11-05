"""报告文件的编码读取（只依赖标准库）。

为什么要单独写这一小段
----------------------

包里已经有编码识别（``fixtext_import.encoding.probe``），但它属于导入链路，
导入它的包入口会连带拉起 EPUB 解析等依赖（需要引擎包在 ``sys.path`` 上）。
本模块是纯解析层，要在**没有界面、没有引擎**的环境里也能独立跑测试，所以这里
只实现「把报告文件读成文本」这一件事，规则与 ``fixtext_import.encoding`` 同口径：

1. **有 BOM 就按 BOM**——报告是导出侧写的，``utf-8-sig`` 是它真实的写法。
2. **纯 ASCII** 直接按 UTF-8。
3. **严格解码**：UTF-8 整文件能解就取 UTF-8（报告的正常形态）。
4. UTF-8 解不了 → 依次试 GBK / GB18030 / Big5，用**可读性打分**仲裁
   （GB18030 是 GBK 超集，几乎什么字节都能解，只看能否解码会把繁体判成国标）。
5. 全都不行 → 按替换字符读，并明确告诉调用方「是按兜底读的」。

读取永远是**只读**的，不改动任何字节。
"""

from __future__ import annotations

import codecs
from pathlib import Path

#: 候选字符集（顺序即同分时的取舍优先级）
CANDIDATES: tuple[tuple[str, str], ...] = (
    ("utf-8", "通用格式"),
    ("gbk", "老式中文格式"),
    ("gb18030", "国标中文格式"),
    ("big5", "繁体中文格式"),
)

#: 「读起来像正常中文书稿」的判定线
PLAUSIBLE_SCORE = 0.6

#: 打分采样上限
SAMPLE_LIMIT = 20000


def _decode_head(path: Path, codec: str, limit: int = SAMPLE_LIMIT) -> str | None:
    """严格解出前面一段；有非法序列就返回 None。"""
    try:
        with path.open("rb") as fh:
            chunk = fh.read(limit * 4)
        return chunk.decode(codec)
    except (UnicodeDecodeError, LookupError):
        return None


def _can_decode_all(path: Path, codec: str) -> bool:
    """整文件严格解码（增量解码，不会把多字节字符切坏）。"""
    decoder = codecs.getincrementaldecoder(codec)("strict")
    try:
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(256 * 1024)
                if not chunk:
                    break
                decoder.decode(chunk)
        decoder.decode(b"", final=True)
        return True
    except (UnicodeDecodeError, LookupError):
        return False


def _plausibility(sample: str) -> float:
    """可读性打分：这些字符像不像正常书稿。

    只看「构成中文文本的比例」——汉字 / 全角标点 / ASCII 可读字符算合理，
    控制字符与私用区字符算不合理。与 ``fixtext_import.encoding`` 同一思路。
    """
    if not sample:
        return 0.0
    good = 0
    for ch in sample:
        cp = ord(ch)
        if 0x4E00 <= cp <= 0x9FFF:            # 汉字
            good += 1
        elif 0x3000 <= cp <= 0x303F:          # 中文标点
            good += 1
        elif 0xFF00 <= cp <= 0xFFEF:          # 全角
            good += 1
        elif ch in "\r\n\t":
            good += 1
        elif 0x20 <= cp <= 0x7E:              # 可见 ASCII
            good += 1
        elif cp in (0x2018, 0x2019, 0x201C, 0x201D, 0x2026, 0x2014):
            good += 1                          # 弯引号 / 省略号 / 破折号
    return good / len(sample)


def read_text(path: str | Path) -> tuple[str, str, str, bool]:
    """读报告文件。

    返回 ``(文本, 字符集码, 人话标签, 是否按兜底读)``。文件不存在或读不动时
    抛出 :class:`OSError` 子类，由调用方翻译成人话。
    """
    p = Path(path)
    raw_head = p.open("rb").read(4)
    # 1) BOM
    if raw_head.startswith(b"\xef\xbb\xbf"):
        return p.read_text(encoding="utf-8-sig"), "utf-8", "通用格式（带标记）", False
    if raw_head.startswith(b"\xff\xfe\x00\x00"):
        return p.read_text(encoding="utf-32"), "utf-32", "带标记的通用格式", False
    if raw_head.startswith(b"\xff\xfe"):
        return p.read_text(encoding="utf-16"), "utf-16", "带标记的通用格式", False

    # 2) 空文件 / 纯 ASCII
    try:
        head = p.open("rb").read(SAMPLE_LIMIT * 4)
    except OSError:
        raise
    if not head:
        return "", "utf-8", "通用格式", False

    # 3) UTF-8 整文件可解即取 UTF-8
    if _can_decode_all(p, "utf-8"):
        return p.read_text(encoding="utf-8"), "utf-8", "通用格式", False

    # 4) 其余候选按可读性仲裁
    decodable = [c for c, _l in CANDIDATES if _can_decode_all(p, c) and c != "utf-8"]
    if "gbk" in decodable and "gb18030" in decodable:
        decodable = [c for c in decodable if c != "gb18030"]
    if decodable:
        samples = {c: _decode_head(p, c) or "" for c in decodable}
        scores = {c: _plausibility(s) for c, s in samples.items()}
        order = {c: i for i, (c, _l) in enumerate(CANDIDATES)}
        best = sorted(decodable, key=lambda c: (-scores[c], order[c]))[0]
        return (p.read_text(encoding=best), best,
                dict((c, l) for c, l in CANDIDATES)[best], False)

    # 5) 兜底：按替换字符读，明确标记
    best = max(CANDIDATES, key=lambda cl: _plausibility(_decode_head(p, cl[0]) or ""))
    try:
        text = p.read_text(encoding=best[0], errors="replace")
    except LookupError:
        text = p.read_text(encoding="utf-8", errors="replace")
    return text, best[0], best[1], True
