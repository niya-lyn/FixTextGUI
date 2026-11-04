"""已执行规则的 mark 记忆（V1.1-E5）：数据形态、落点与指纹。

为什么它**不是**按书词库的一部分
------------------------------------
C1 的按书文件 ``book_vocab.json`` 承载的是**词条排除项**，它的键是
:func:`fixtext_pipeline.rule_keys.entry_key` 算出来的 ``(原词, 替换值)``
内容键；而本卡记的是**规则标识 mark**（如 ``{盍->阖}``，见
``fixtext_ui.fixtext_manual_search`` 的 ``Rule.mark``），它是**规则维度**、
没有 ``(原词, 替换值)`` 二元组。

把 mark 塞进 ``excluded`` 会让 ``book_vocab.resolve_excluded()`` 把 mark 当成
一个内容键参与并集：``effective`` 里凭空多出若干条「排除词条」，
``overlap`` / ``global_only`` / ``book_only`` 三个统计全部失真，来源记账也
说不清「谁排除了谁」。所以本卡**在该书的按书作用域下加一份并列文件**
``workspace/vocab/books/<书 id>/executed_rules.json``：

* 与 ``book_vocab.json`` **同一级目录、同一份书 id 规范化**（复用
  :func:`book_vocab.book_vocab_path` 算出目录，不自己拼路径、不另造存储根）；
* 两份文件的字段互不重叠 —— ``book_vocab.json`` 一个字节都不受影响，
  ``resolve_excluded()`` 的口径天然不被污染（``tests/test_e5_executed_memory.py``
  有专门的对照用例把这条锁住）。

它也不进装载层
----------------
排期 §11.2 的「装载层唯一入口」（``vocab_bridge.compose()`` /
``bags.write_round_rules()``）管的是**词条过滤**；本卡要排除的是
**规则是否重跑**，属手动检索的规则选择层。因此 ``compose`` 里没有为本卡
增加任何过滤路径——本卡只提供：

1. 数据形态与读写（:func:`read_executed` / :func:`write_executed`）；
2. 一份**指纹**（:func:`executed_marks_sha`），供 ``ReplaceStage.fingerprint()``
   把「本书的记忆状态」算进装载缓存键（改了记忆 → 指纹变化 → 断点不拿旧正文
   当命中缓存；清回空 → 指纹复原）。

指纹只取 **mark 集合**，不带时间戳：同一份「哪些规则执行过」永远同一个指纹，
清除后必然回到写之前的那个值（这是「指纹复原」可被逐字核对的前提）。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from . import book_vocab

#: 并列文件名（与 ``book_vocab.json`` 同级同目录）
EXECUTED_RULES_FILE = "executed_rules.json"

#: 文件版本
EXECUTED_RULES_VERSION = 1

#: 文件种类标记（写进 payload，便于人读时分辨两份按书文件）
EXECUTED_RULES_KIND = "executed_rule_marks"


# ---------------------------------------------------------------------------
# 存储位置（复用 C1：书 id 规范化与按书目录都从 book_vocab 来）
# ---------------------------------------------------------------------------

def executed_rules_path(book_id: str,
                        workspace: Path | str | None = None) -> Path:
    """一本书的执行记忆位置：``<用户区>/vocab/books/<书 id>/executed_rules.json``。

    直接拿 C1 的 ``book_vocab.book_vocab_path`` 换算文件名，因此：

    * 书 id 校验 / 归一与 ``book_vocab.json`` **完全同一套**（非法书 id 同样抛
      :class:`book_vocab.BookVocabError`，不会把 ``../..`` 拼进路径）；
    * 两份文件必然落在同一个书目录下，作用域天然按书隔离。
    """
    return book_vocab.book_vocab_path(
        book_id, workspace=workspace).with_name(EXECUTED_RULES_FILE)


def executed_rules_path_of_book(book_vocab_path: Path | str | None) -> Path | None:
    """从 ``book_vocab.json`` 的位置换算出同目录的执行记忆位置。

    给「手里只有按书词库路径」的调用方用（如 ``ReplaceStage._book_vocab_path()``），
    免得再写一遍书 id 解析。没有按书词库路径 → ``None``（没有按书作用域就记不住）。
    """
    if not book_vocab_path:
        return None
    return Path(book_vocab_path).with_name(EXECUTED_RULES_FILE)


# ---------------------------------------------------------------------------
# 规范字节与指纹
# ---------------------------------------------------------------------------

def canonical_executed_marks(marks: Iterable[str] | None) -> bytes:
    """mark 集合的规范字节（排序 + 紧凑 JSON + 换行）——同一份集合永远同样字节。"""
    obj = {
        "version": EXECUTED_RULES_VERSION,
        "executedMarks": sorted({str(m) for m in (marks or ()) if str(m)}),
    }
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"


def executed_marks_sha(marks: Iterable[str] | None) -> str:
    """mark 集合指纹；空集也给出确定值（进缓存键与阶段指纹，可逐字核对）。"""
    return hashlib.sha256(canonical_executed_marks(marks)).hexdigest()


# ---------------------------------------------------------------------------
# 读
# ---------------------------------------------------------------------------

def _record(obj: Any) -> dict | None:
    """把一条记忆归一成 ``{mark, at, batch, hits, point_id, reason}``；认不出返回 None。"""
    if isinstance(obj, str):
        mark = obj.strip()
        return dict(mark=mark, at="", batch=0, hits=0, point_id=0, reason="") if mark else None
    if not isinstance(obj, dict):
        return None
    mark = str(obj.get("mark") or "").strip()
    if not mark:
        return None
    try:
        batch = int(obj.get("batch") or 0)
    except (TypeError, ValueError):
        batch = 0
    try:
        hits = int(obj.get("hits") or 0)
    except (TypeError, ValueError):
        hits = 0
    try:
        point_id = int(obj.get("point_id") or 0)
    except (TypeError, ValueError):
        point_id = 0
    return dict(mark=mark, at=str(obj.get("at") or ""), batch=batch, hits=hits,
                point_id=point_id, reason=str(obj.get("reason") or ""))


def read_executed(path: Path | str | None) -> dict:
    """读一本书的执行记忆；**不抛异常**（坏文件按「没有记忆」处理并把原因写进 ``error``）。

    返回：

    * ``configured`` —— 文件是否存在且可解析
    * ``book_id`` / ``path`` —— 事实来源
    * ``marks`` —— ``{mark: 记录}``（记录含时间 / 批号 / 命中数 / 还原点）
    * ``mark_set`` —— ``frozenset[str]``，选择层用它快速判断「是否执行过」
    * ``sha256`` —— 文件原始字节指纹
    * ``marks_sha`` —— **mark 集合**指纹（进阶段指纹的就是它）
    * ``error`` —— 无法解析的原因（空串 = 正常）
    """
    out = dict(configured=False, book_id="", path="", marks={}, mark_set=frozenset(),
               sha256="", marks_sha=executed_marks_sha(()), error="",
               version=EXECUTED_RULES_VERSION)
    if not path:
        return out
    p = Path(path)
    out["path"] = str(p)
    try:
        raw = p.read_bytes()
    except (OSError, ValueError):
        return out                            # 没有记忆：默认情形，不是错误

    out["sha256"] = hashlib.sha256(raw).hexdigest()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        out.update(configured=False,
                   error=f"执行记忆无法解析（{type(exc).__name__}），本书按「没有记忆」处理")
        return out
    if not isinstance(data, dict):
        out.update(configured=False, error="执行记忆结构异常，本书按「没有记忆」处理")
        return out

    out["book_id"] = str(data.get("book_id") or "")
    marks: dict[str, dict] = {}
    bad = 0
    for obj in data.get("marks") or []:
        rec = _record(obj)
        if rec is None:
            bad += 1
            continue
        marks[rec["mark"]] = rec
    out["marks"] = marks
    out["mark_set"] = frozenset(marks)
    out["marks_sha"] = executed_marks_sha(marks)
    out["configured"] = True
    if bad:
        out["error"] = f"执行记忆里有 {bad} 条无法识别，已忽略（其余照常生效）"
    ver = data.get("version")
    if ver not in (None, EXECUTED_RULES_VERSION):
        out["version"] = ver
    return out


def executed_mark_set(path: Path | str | None) -> frozenset[str]:
    """只取已执行 mark 集合（未配置 / 坏文件 → 空集）。"""
    return read_executed(path)["mark_set"]


def executed_sha_of_book(book_vocab_path: Path | str | None) -> str:
    """本书执行记忆的 mark 指纹（给阶段指纹用）：没有按书作用域 → 空集指纹。

    空集指纹是**确定值**而不是 ``"missing"``，这样「有按书作用域但还没执行过
    任何规则」与「没有按书作用域」两种情形下，指纹里这一项都不抖，断点恢复
    不会因为「第一次落了一条记忆」之外的原因反复重跑。
    """
    p = executed_rules_path_of_book(book_vocab_path)
    try:
        return executed_marks_sha(executed_mark_set(p))
    except Exception:                              # noqa: BLE001 - 指纹不能拖垮校正
        return executed_marks_sha(())


# ---------------------------------------------------------------------------
# 写（界面 / 手动检索层用；本卡只保证形态可写、可回读一致）
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".exr-", suffix=".tmp")
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


def write_executed(path: Path | str, book_id: str,
                   records: Iterable[dict | str]) -> dict:
    """写一本书的执行记忆（规范字节：同一份 mark 集合永远同样的字节）。

    ``records`` 接受 ``{"mark": …, "at": …, "batch": …, "hits": …}`` 字典或
    ``mark`` 字符串。按 mark 升序落盘 → 内容顺序稳定；``marks`` 与 ``mark_set``
    的去重由 mark 唯一性保证。
    """
    p = Path(path)
    bid = book_vocab.normalize_book_id(book_id)
    items: dict[str, dict] = {}
    for obj in records or ():
        rec = _record(obj)
        if rec is None:
            continue
        old = items.get(rec["mark"])
        if old is not None and old.get("at"):
            # 已有的记录更完整时保留它的时间，只补空字段（幂等重记不抹掉历史）
            for key in ("at", "reason"):
                if not rec.get(key) and old.get(key):
                    rec[key] = old[key]
            rec["batch"] = rec["batch"] or old.get("batch", 0)
            rec["hits"] = rec["hits"] or old.get("hits", 0)
            rec["point_id"] = rec["point_id"] or old.get("point_id", 0)
        items[rec["mark"]] = rec
    ordered = [items[m] for m in sorted(items)]

    payload = dict(
        product="FixText",
        kind=EXECUTED_RULES_KIND,
        version=EXECUTED_RULES_VERSION,
        book_id=bid,
        updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        note="按书作用域下的「已执行规则」记忆；与 book_vocab.json 并列，不进词条排除集",
        marks=ordered,
    )
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    _atomic_write(p, raw)
    return dict(path=str(p), book_id=bid, count=len(ordered),
                sha256=hashlib.sha256(raw).hexdigest(),
                mark_set=frozenset(items),
                marks_sha=executed_marks_sha(items))
