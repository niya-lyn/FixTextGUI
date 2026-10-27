"""FixText V1 · 文本编码识别（T2.2）

目标：**零配置正确识别 UTF-8 / GBK / GB18030**，并把"我认出来的是什么"翻译成
用户可以理解的一句话（见 `messages.py`），不要求用户懂编码。

识别策略（按优先级，每一步都有明确依据）：

1. **BOM**：文件头带标记时直接取标记（UTF-8 with BOM / UTF-16 / UTF-32）。
   这是唯一不需要猜测的情况，BOM 是写入方自己留下的声明。
2. **纯 ASCII**：全文件只有英文，任何字符集解出来完全一致，按 UTF-8 处理。
3. **严格解码 + 可读性仲裁**：对每个候选字符集做整文件严格解码（增量解码器，
   任何非法序列即判失败），得到"能解的集合"；再按可读性打分选出"读起来最像
   中文书稿"的一方。
   - 为什么必须打分：GB18030 是 GBK 的超集，覆盖了几乎全部字节组合，
     Big5 文件用 GB18030 也能"解出来"——只靠"能否解码"会把繁体书判成国标。
     打分依据是"这些字符在正常书稿里会不会出现"（见 `text_plausibility`）。
   - 为什么能解就优先 GBK 而不标 GB18030：两者对 GBK 可表示的字节产出完全相同，
     标 GBK 才是与字节事实一致的描述；只有出现 GBK 无法解码的 4 字节字符时才标 GB18030。
4. 全部失败则返回低置信度结果，由上层用**人话**提示用户，不做静默乱码。

本模块只回答"字节按什么字符集解释"，不修改任何字节；写回统一由
`textfile.py` 负责（UTF-8 无 BOM + LF）。
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 候选字符集（顺序即语义优先级，用于同分时取舍）
# ---------------------------------------------------------------------------

CANDIDATES: tuple[tuple[str, str], ...] = (
    ("utf-8", "UTF-8"),
    ("gbk", "GBK"),
    ("gb18030", "GB18030"),
    ("big5", "Big5"),
)

LABELS = dict(CANDIDATES)

#: 探测块大小：读得快，且用增量解码器保证不会把多字节字符切坏
PROBE_CHUNK = 256 * 1024

#: 可读性打分采样上限（字符）
SAMPLE_LIMIT = 20000

#: UTF-8 判定为"确定是它"的可读性下限（低于此值才需要与 GBK 比对）
UTF8_CERTAIN_SCORE = 0.95

#: 仲裁时超过对手的最小领先幅度（防止两套都在 0.99 时来回摇摆）
ARBITRATE_MARGIN = 0.02

BOM_TABLE: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),   # 必须排在 UTF-16 LE 之前（前缀重叠）
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

_BOM_LABELS = {
    "utf-8-sig": "UTF-8",
    "utf-16-le": "UTF-16",
    "utf-16-be": "UTF-16",
    "utf-32-le": "UTF-32",
    "utf-32-be": "UTF-32",
}


@dataclass
class ProbeResult:
    """一次编码探测的结论与依据。"""

    codec: str
    label: str
    confidence: str                                   # bom | strict | scored | fallback
    has_bom: bool = False
    evidence: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def certain(self) -> bool:
        return self.confidence in {"bom", "strict"}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _iter_chunks(path: Path, chunk: int = PROBE_CHUNK):
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                return
            yield block


def can_decode(path: Path, codec: str) -> bool:
    """整文件严格解码是否成功（流式，内存不随文件线性增长）。"""
    try:
        decoder = codecs.getincrementaldecoder(codec)(errors="strict")
        for block in _iter_chunks(path):
            decoder.decode(block)
        decoder.decode(b"", final=True)
        return True
    except (UnicodeDecodeError, UnicodeError):
        return False


def sample_text(path: Path, codec: str, limit: int = SAMPLE_LIMIT) -> str:
    """取文件开头的一段文本样本（只读），用于可读性打分。"""
    decoder = codecs.getincrementaldecoder(codec)(errors="replace")
    parts: list[str] = []
    got = 0
    for block in _iter_chunks(path, 64 * 1024):
        piece = decoder.decode(block)
        parts.append(piece)
        got += len(piece)
        if got >= limit:
            break
    return "".join(parts)[:limit]


_GOOD_ASCII = frozenset(range(0x20, 0x7F))


def text_plausibility(sample: str) -> float:
    """可读性打分：正常中文/英文书稿接近 1.0；按错字符集解释出来的乱码明显偏低。

    记正分：常用汉字、扩展 A 区、中日韩标点、全角符号、通用标点、ASCII 可打印、换行。
    记负分：替换符 U+FFFD、私用区、扩展 B 区及以后、除 \\t\\r\\n 外的控制符
    —— 这些正是"字节被按错字符集解释"的典型落点。
    """
    if not sample:
        return 1.0
    good = 0.0
    bad = 0.0
    for ch in sample:
        o = ord(ch)
        if o == 0xFFFD:
            bad += 4
        elif o in (0x0A, 0x0D, 0x09):
            good += 1
        elif 0x4E00 <= o <= 0x9FFF or 0x3000 <= o <= 0x303F or 0xFF00 <= o <= 0xFFEF \
                or 0x2000 <= o <= 0x206F:
            good += 1
        elif 0x3400 <= o <= 0x4DBF:          # 扩展 A 区：GBK 确有收字，不算坏
            good += 0.8
        elif o in _GOOD_ASCII:
            good += 1
        elif 0xE000 <= o <= 0xF8FF:          # 私用区
            bad += 3
        elif o >= 0x20000:                   # 扩展 B 区及以后：书稿里几乎不出现
            bad += 2.5
        elif o < 0x20:                       # 控制符
            bad += 3
        else:
            good += 0.6
    total = good + bad
    return 1.0 if total <= 0 else good / total


def _bom_of(path: Path) -> tuple[str | None, bytes]:
    with path.open("rb") as fh:
        head = fh.read(4)
    for bom, codec in BOM_TABLE:
        if head.startswith(bom):
            return codec, bom
    return None, b""


def is_plain_ascii(path: Path) -> bool:
    """全文件是否只有 ASCII —— 这时 UTF-8 / GBK / GB18030 / Big5 解出来完全一样。"""
    for block in _iter_chunks(path, 512 * 1024):
        if block.translate(None, bytes(range(0x80))) != block:
            return False
    return True


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def probe(path: str | Path) -> ProbeResult:
    """识别文件的字符编码，返回结论 + 依据（可复算，不含随机打分）。"""
    path = Path(path)

    if path.stat().st_size == 0:
        return ProbeResult(
            codec="utf-8", label="UTF-8", confidence="strict",
            evidence=["文件为空，按 UTF-8 处理"],
        )

    bom_codec, bom_bytes = _bom_of(path)
    if bom_codec:
        label = _BOM_LABELS[bom_codec]
        return ProbeResult(
            codec=bom_codec, label=label, confidence="bom", has_bom=True,
            evidence=[f"文件开头有 {bom_bytes.hex(' ').upper()} 标记，按标记声明为 {label}"],
        )

    if is_plain_ascii(path):
        return ProbeResult(
            codec="utf-8", label="UTF-8", confidence="strict",
            evidence=["文件全部是英文字符，各字符集结果一致，按 UTF-8 处理"],
        )

    # 能严格解码的候选（utf-8 / gbk / gb18030 / big5）
    decodable = [codec for codec, _label in CANDIDATES if can_decode(path, codec)]
    evidence: list[str] = []

    if not decodable:
        # 没有任何常见字符集能完整解码：按可读性最高的那个给低置信度结论
        scored = {codec: text_plausibility(sample_text(path, codec)) for codec, _l in CANDIDATES}
        best = max(scored, key=lambda k: (scored[k], -[c for c, _ in CANDIDATES].index(k)))
        return ProbeResult(
            codec=best, label=LABELS[best], confidence="fallback",
            evidence=[f"没有任何常见字符集能完整解码，按可读性最高的 {LABELS[best]} 处理"
                      f"（可读性 {scored[best]:.2f}）"],
            scores=scored,
        )

    # GBK 与 GB18030 对 GBK 可表示的文本产出相同：能按 GBK 解就别标 GB18030
    if "gbk" in decodable and "gb18030" in decodable:
        decodable = [c for c in decodable if c != "gb18030"]

    scores = {codec: text_plausibility(sample_text(path, codec)) for codec in decodable}

    if "utf-8" in decodable and scores["utf-8"] >= UTF8_CERTAIN_SCORE:
        evidence.append(f"整文件可严格按 UTF-8 解码，可读性 {scores['utf-8']:.2f}")
        if len(decodable) > 1:
            others = "、".join(f"{LABELS[c]} {scores[c]:.2f}" for c in decodable if c != "utf-8")
            evidence.append(f"其它字符集也能解但读起来不成立（{others}），按 UTF-8 处理")
        return ProbeResult(codec="utf-8", label="UTF-8", confidence="strict",
                           evidence=evidence, scores=scores)

    # 需要仲裁：按可读性取最高，同分按 CANDIDATES 顺序（utf-8 优先）
    order = {codec: i for i, (codec, _l) in enumerate(CANDIDATES)}
    ranked = sorted(decodable, key=lambda c: (-scores[c], order[c]))
    winner = ranked[0]
    runner = ranked[1] if len(ranked) > 1 else None

    if runner is not None and scores[winner] - scores[runner] < ARBITRATE_MARGIN:
        # 领先幅度太小：退回候选顺序里更保守（更窄）的那个，避免赌
        winner = min([winner, runner], key=lambda c: order[c])

    confidence = "strict" if scores[winner] >= UTF8_CERTAIN_SCORE and winner == "utf-8" else "scored"
    if winner == "gbk" and "gbk" in decodable and _only_gbk_fits(path):
        confidence = "strict"
    if winner == "gb18030":
        confidence = "strict"          # GBK 解不了、它解得了 = 事实性判定

    detail = "、".join(f"{LABELS[c]} {scores[c]:.2f}" for c in ranked)
    evidence.append(f"能解码的字符集按可读性排序：{detail}；取 {LABELS[winner]}")
    return ProbeResult(codec=winner, label=LABELS[winner], confidence=confidence,
                       evidence=evidence, scores=scores)


def _only_gbk_fits(path: Path) -> bool:
    """UTF-8 严格解码失败、GBK 成功 —— 这是 GBK 的决定性证据。"""
    return not can_decode(path, "utf-8") and can_decode(path, "gbk")


def decode_file(path: str | Path, codec: str, errors: str = "replace") -> str:
    """用指定字符集把整文件读成字符串（只读，绝不改原字节）。"""
    decoder = codecs.getincrementaldecoder(codec)(errors=errors)
    parts: list[str] = []
    for block in _iter_chunks(Path(path)):
        parts.append(decoder.decode(block))
    parts.append(decoder.decode(b"", final=True))
    return "".join(parts)
