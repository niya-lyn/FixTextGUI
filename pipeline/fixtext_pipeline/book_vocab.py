"""按书专有词库（V1.1-C1）：数据形态、存储位置与按书排除集读取。

三级分离（这是本模块存在的全部理由）
--------------------------------------
1. **出厂只读层**：``data/rules/``（分袋词库）。任何卡都不许改写，本模块
   只读它——事实上本模块根本不碰它，规则池由 :mod:`bags` 提供。
2. **全局自定义层**：``workspace/vocab/custom_vocab.json``（用户自己加的词）
   与 ``workspace/vocab/word_states.json``（全局启用 / 禁用集，B 组的产物）。
   这两份**对所有书生效**。
3. **按书层**（本卡新增）：``workspace/vocab/books/<书 id>/book_vocab.json``，
   **一本书一份**。它只承载「这本书不要用的词条」（按书排除）；
   出厂词库与全局自定义词的**内容**不在这里复制，避免出现第二份词库。

为什么按书层只放排除、不放词条
--------------------------------
排期 8.2 第 2 条把接线面限定为「按书**排除**」；旧版 PHP 的
``excludedWords`` 也是一份排除集合（``Map.php``）。把「本书专用替换词条」
塞进同一个文件会让「谁排除了谁」和「谁新增了什么」两种语义混在一份数据里，
C2 的界面就要在一份文件上做两种互斥的增删，成本与风险都不必要。所以：

* 本期生效字段只有 ``excluded``（按书排除集）；
* 文件里留 ``entries`` 键位（默认空数组）**但不生效**，只作后续卡的数据落脚，
  读取时明确忽略并如实写进 ``ignored`` 说明——不做「定义了却悄悄生效」。

叠加判定（全局禁用 + 按书排除同时命中时以谁为准）
--------------------------------------------------
**全局禁用优先，排除只增不减。** 有效排除集是两边的**并集**：

    effective_excluded = 全局禁用 ∪ 按书排除

理由是可证伪的，不是口味：全局禁用是用户「这条词条对我不该参与校正」的
整体判定，B3 已把它写进阶段指纹与下发规则集；若按书层能把它「抵消」
（例如本书把一条全局禁用的词条标成可用），就等于开了一条绕过全局禁用的
暗路，且同一份全局禁用集在不同书上会给出相反行为，B3 的一致性立刻失效。
反过来，按书层**追加**排除是安全的：它只会让这本书少用一条词条，不可能
让别处多出来。

所以本模块**不提供**「按书启用」这个动作；一份按书文件里即使写了
``"enabled": true`` 也不会复活被全局禁用的词条——:func:`resolve_excluded`
把两边的命中来源逐条记进 ``sources``，``tests/test_c1_book_vocab.py`` 有
专门的判定用例把这条语义锁住。

未配置按书词库的书
------------------
``book_vocab_path`` 为 ``None`` 或文件不存在时，:func:`load_book_vocab` 返回
空排除集且 ``configured=False``；装载层拿到的按书排除集为空，**输出与 B3
收口时逐字节一致**（``tests/test_c1_book_vocab.py`` 有对照用例）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from .rule_keys import entry_key

#: 按书层目录名（用户区 ``workspace/vocab/`` 下的子目录）
BOOKS_SUBDIR = "books"

#: 单本书的按书词库文件名
BOOK_VOCAB_FILE = "book_vocab.json"

#: 按书词库文件版本
BOOK_VOCAB_VERSION = 1

#: 书 id 允许的字符：与 ``fixtext_import.importer._book_id`` 的产出对齐
#: （可读前缀 + 内容哈希前 8 位），并额外允许中文书名。
#: **不接受路径分隔符与点号**——书 id 会被拼进文件路径，必须挡住 ``..``。
_SAFE_BOOK_ID = re.compile(r"^[0-9A-Za-z_\u4e00-\u9fff-]{1,120}$")


class BookVocabError(RuntimeError):
    """按书词库不可用（调用方应降级为「按全局默认」并如实标注）。"""


# ---------------------------------------------------------------------------
# 存储位置
# ---------------------------------------------------------------------------

def normalize_book_id(book_id: str | None) -> str:
    """校验并归一书 id；非法（含路径分隔符 / ``..`` / 空）抛 :class:`BookVocabError`。

    书 id 是工作区里那本书的目录名（见 ``fixtext_ui.fixtext_shelf``），会被
    直接拼进按书词库路径，所以这里必须把它当不可信输入处理——一个
    ``../..`` 就能把按书词库写到用户区之外。
    """
    raw = str(book_id or "").strip()
    if not raw:
        raise BookVocabError("书 id 为空，无法定位按书词库")
    if not _SAFE_BOOK_ID.match(raw):
        raise BookVocabError(f"书 id 含不允许的字符：{raw!r}")
    return raw


def books_root(workspace: Path | str | None = None) -> Path:
    """按书层根目录：``<用户区>/vocab/books/``。"""
    if workspace is None:
        from .vocab_bridge import _ui_workspace

        workspace = _ui_workspace()
    return Path(workspace) / "vocab" / BOOKS_SUBDIR


def book_vocab_path(book_id: str, workspace: Path | str | None = None) -> Path:
    """一本书的按书词库位置：``<用户区>/vocab/books/<书 id>/book_vocab.json``。

    **一本书一份**：文件名固定，目录名就是书 id，不按书名猜、不带时间戳，
    同一本书永远是同一个路径（这是「不同按书配置下可复现」的前提）。
    """
    return books_root(workspace) / normalize_book_id(book_id) / BOOK_VOCAB_FILE


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> dict | None:
    try:
        raw = path.read_bytes()
    except (OSError, ValueError):
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _entry_pairs(obj: Any) -> tuple[str, str, str] | None:
    """把一条排除项归一成 ``(word, value, key)``；认不出就返回 None（不猜）。"""
    if isinstance(obj, str):
        # 只给键的简写形态：没有 word/value，C2 渲染不出内容，但过滤要能用
        key = obj.strip()
        return ("", "", key) if key else None
    if isinstance(obj, (tuple, list)):
        # ``(word, value)`` / ``(word, value, key)`` 元组形态（见 write_book_vocab 文档）
        if len(obj) not in (2, 3):
            return None
        word = str(obj[0] if obj[0] is not None else "").strip()
        value = str(obj[1] if obj[1] is not None else "").strip()
        key = str(obj[2]).strip() if len(obj) == 3 and obj[2] else ""
        if not key and word:
            key = entry_key(word, value)
        if not key:
            return None
        return (word, value, key)
    if not isinstance(obj, dict):
        return None
    word = str(obj.get("word") or "").strip()
    value = str(obj.get("value") or "").strip()
    key = str(obj.get("key") or "").strip()
    if not key and word:
        key = entry_key(word, value)
    if not key:
        return None
    return (word, value, key)


def load_book_vocab(path: Path | str | None) -> dict:
    """读一本书的按书词库；返回可直接进报告的摘要（**不抛异常**）。

    读不到 / 解析不了时按「没有按书配置」处理，并把原因写进 ``error``：
    按书词库坏掉不该让整本校正跑不起来，但必须让用户与证据看到它没生效。

    返回字段：

    * ``configured`` —— 文件是否存在且可解析（``False`` = 走全局默认）
    * ``book_id`` / ``path`` —— 事实来源
    * ``excluded_keys`` —— 按书排除集（``frozenset[str]``，内容键）
    * ``excluded`` —— 原始条目（含 word/value/reason，供 C2 渲染与人读证据）
    * ``ignored`` —— 文件里存在但本期**不生效**的键位说明（如 ``entries``）
    * ``sha256`` —— 文件内容指纹（进阶段指纹与缓存键）
    * ``error`` —— 无法读取 / 解析的原因（空串 = 正常）
    """
    out = dict(
        configured=True, book_id="", path="", excluded_keys=frozenset(),
        excluded=[], ignored=[], sha256="", error="", version=BOOK_VOCAB_VERSION,
    )
    if not path:
        out.update(configured=False, path="", error="")
        return out

    p = Path(path)
    out["path"] = str(p)
    try:
        raw = p.read_bytes()
    except (OSError, ValueError):
        out.update(configured=False, error="")
        return out                             # 没有配置：不是错误，是默认情形

    out["sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        out.update(configured=False, excluded_keys=frozenset(),
                   error=f"按书词库无法解析（{type(exc).__name__}），本书按全局默认处理")
        return out
    if not isinstance(data, dict):
        out.update(configured=False, excluded_keys=frozenset(),
                   error="按书词库结构异常，本书按全局默认处理")
        return out

    out["book_id"] = str(data.get("book_id") or "")
    keys: set[str] = set()
    entries: list[dict] = []
    bad = 0
    for obj in data.get("excluded") or []:
        pair = _entry_pairs(obj)
        if pair is None:
            bad += 1
            continue
        word, value, key = pair
        keys.add(key)
        entries.append(dict(word=word, value=value, key=key,
                            reason=str((obj or {}).get("reason") or "")
                            if isinstance(obj, dict) else ""))
    out["excluded_keys"] = frozenset(keys)
    out["excluded"] = entries

    ignored: list[str] = []
    # ``entries``（本书专用替换词条）本期不生效：读取时明确忽略并写清原因，
    # 不做「文件里有、悄悄起作用」的暗行为。
    extra = data.get("entries")
    if isinstance(extra, list) and extra:
        ignored.append(
            f"entries（本书专用词条）{len(extra)} 条本期不生效："
            "按书层只接排除，新增词条留给后续卡")
    out["ignored"] = ignored

    if bad:
        out["error"] = f"按书词库有 {bad} 条排除项无法识别，已忽略（其余照常生效）"
    if str(data.get("version") or "") and data.get("version") != BOOK_VOCAB_VERSION:
        out["version"] = data.get("version")
    return out


def book_excluded_keys(path: Path | str | None) -> frozenset[str]:
    """按书排除集（只取键）。未配置 / 坏文件 → 空集（走全局默认）。"""
    return load_book_vocab(path)["excluded_keys"]


def canonical_book_excluded(keys: Iterable[str] | None) -> bytes:
    """按书排除集的规范字节（键排序 + 紧凑 JSON + 换行）。"""
    obj = {"version": BOOK_VOCAB_VERSION, "bookExcluded": sorted(set(keys or ())), }
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"


def book_excluded_sha(keys: Iterable[str] | None) -> str:
    """按书排除集指纹（空集也给出确定值，便于进缓存键与阶段指纹）。"""
    return hashlib.sha256(canonical_book_excluded(keys)).hexdigest()


# ---------------------------------------------------------------------------
# 叠加判定：全局禁用 ∪ 按书排除
# ---------------------------------------------------------------------------

#: 叠加判定口径名（进报告，便于证据逐字核对）
OVERLAY_POLICY = "global_wins_union"

#: 叠加判定的人话说明（写进 run_report，不写界面）
OVERLAY_POLICY_NOTE = (
    "全局禁用与按书排除取并集（排除只增不减）；同一条同时命中时记为全局禁用，"
    "按书层不得抵消全局禁用"
)


def resolve_excluded(global_disabled: Iterable[str] | None,
                     book_excluded: Iterable[str] | None) -> dict:
    """把两层排除合成**有效排除集**，并逐条记下来源。

    返回：

    * ``effective`` —— 有效排除集（两层的并集）
    * ``sources`` —— ``{内容键: "global" | "book" | "both"}``
    * ``overlap`` —— 同时被全局禁用与按书排除的条数（判定用例核对这一项）
    * ``global_only`` / ``book_only`` —— 各自独占的条数
    * ``policy`` / ``policy_note`` —— 口径名与人话说明

    ``both`` 的条目在装载层按**全局禁用**记账（:data:`OVERLAY_POLICY`）：
    它对这本书生效的强度与原因里，全局禁用是那一层无法被本地配置推翻的判定。
    """
    g = frozenset(global_disabled or ())
    b = frozenset(book_excluded or ())
    sources: dict[str, str] = {}
    for k in g:
        sources[k] = "global"
    for k in b:
        sources[k] = "both" if k in sources else "book"
    return dict(
        effective=g | b,
        sources=sources,
        overlap=len(g & b),
        global_only=len(g - b),
        book_only=len(b - g),
        global_count=len(g),
        book_count=len(b),
        policy=OVERLAY_POLICY,
        policy_note=OVERLAY_POLICY_NOTE,
    )


# ---------------------------------------------------------------------------
# 写（C2 界面会用；C1 只保证数据形态可写、可回读一致）
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".bkv-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_book_vocab(path: Path | str, book_id: str,
                     excluded: Iterable[tuple[str, str] | dict | str],
                     *, reason: str = "") -> dict:
    """写一本书的按书词库（规范字节，同输入同字节）。

    ``excluded`` 接受 ``(word, value)`` 元组、``{"word":…,"value":…}`` 字典或
    现成的内容键字符串。排序按键升序 → 同一份排除集永远得到同样的字节，
    这是「同一本书在不同按书配置下可复现」的落盘侧前提。
    """
    p = Path(path)
    bid = normalize_book_id(book_id)
    items: list[dict] = []
    seen: set[str] = set()
    for obj in excluded or ():
        pair = _entry_pairs(obj)
        if pair is None:
            continue
        word, value, key = pair
        if key in seen:
            continue
        seen.add(key)
        items.append(dict(word=word, value=value, key=key, reason=str(reason or "")))
    items.sort(key=lambda e: e["key"])

    payload = dict(
        product="FixText",
        kind="book_vocab",
        version=BOOK_VOCAB_VERSION,
        book_id=bid,
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        note="按书层只承载本书的排除项；出厂词库与全局自定义词不在此复制",
        excluded=items,
        entries=[],
    )
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    _atomic_write(p, raw)
    return dict(path=str(p), book_id=bid, count=len(items),
                sha256=hashlib.sha256(raw).hexdigest(),
                excluded_keys=frozenset(seen))


def add_book_exclusion(path: Path | str, book_id: str,
                       word: str, value: str, *, reason: str = "") -> dict:
    """往按书词库里追加一条排除（已存在则幂等跳过）。"""
    current = load_book_vocab(path)
    pairs: list[Any] = [(e["word"], e["value"]) for e in current["excluded"]]
    pairs.append((word, value))
    out = write_book_vocab(path, book_id, pairs, reason=reason)
    out["added"] = entry_key(word, value) not in current["excluded_keys"]
    return out


def clear_book_vocab(path: Path | str, book_id: str) -> dict:
    """清空一本书的按书词库（文件保留，写成空排除集）。"""
    return write_book_vocab(path, book_id, [])
