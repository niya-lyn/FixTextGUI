"""V1.1-E7 · 重复段落的处置状态机与按书持久化（界面侧，不依赖 Qt）

设计说明（一句话）
------------------
**处置记录随书存**——落在按书作用域的并列文件
``<用户区>/vocab/books/<书 id>/duplicate_marks.json``（与 ``book_vocab.json``、
``executed_rules.json`` 同级同目录，书 id 校验复用 C1 的同一个实现）；
不写全局配置，因为"哪一组重复要留、哪一组是误报"是这本书的正文决定的，
换一本书就换一套判断。

三条硬约束在这里落地
--------------------
1. **不提供自动删除**：本模块只有"标记 / 忽略"两态与"清回未处置"，
   没有、也不会有删除段落或改书稿的函数——书稿文本一个字节都不会被这里碰到；
2. **处置动作不碰原文**：写盘只发生在处置记录文件上，撤销只回写该文件；
   界面层验收用"处置前后书稿逐字节比对"来证明这条；
3. **可撤销**：每次处置都经既有还原点仓库留一份"处置前"的处置记录字节，
   撤销就是把那份字节原样写回（``identical`` 按字节核，不按指纹核）。

作用域还多一层：同一个组号在不同阈值下可能指不同的组
---------------------------------------------------
``group_id``（``E-1`` / ``S-1``）是**同一份检测结果内部**的稳定编号；阈值一变，
组号会重新分配。所以处置记录按「阈值 + 最短字数」再分一层
（:func:`scope_key`），不同阈值下的处置互不串味。

另外每条处置都存一份组成员签名（段序号 + 全文的摘要）。正文改动后签名对不上，
界面把这条处置显示成「正文已改动，这条处置不再生效」，而不是把处置错挂到
另一组同样叫 ``E-1`` 的段落上。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

import fixtext_book_scope as _bscope
from fixtext_snapshot import SnapshotStore

#: 处置记录文件名（与按书词库、已执行规则记忆并列）
MARKS_FILE = "duplicate_marks.json"

#: 文件版本 / 种类标记
MARKS_VERSION = 1
MARKS_KIND = "duplicate_paragraph_marks"

#: 两态 + 空态（空 = 未处置，用于「撤销」把一条清回去）
ST_NONE = ""
ST_MARKED = "marked"
ST_IGNORED = "ignored"

#: 合法状态集合（状态机唯一事实来源）
STATES = (ST_NONE, ST_MARKED, ST_IGNORED)

#: 界面人话
STATE_NAMES = {
    ST_NONE: "未处置",
    ST_MARKED: "已标记",
    ST_IGNORED: "已忽略",
}

#: 还原点 / 操作历史里的动作名（与每批替换的备份点并列但互不混淆）
ACT_DUPLICATE_MARK = "duplicate_mark"
ACT_DUPLICATE_RESTORE = "duplicate_restore"

#: 本模块认的还原点动作（撤销时只挑这两类）
_MARK_ACTS = (ACT_DUPLICATE_MARK, ACT_DUPLICATE_RESTORE)

#: 处置记录的还原点仓库目录名（与书稿编辑的 ``batch_backups`` 分开存）
BACKUP_DIRNAME = "duplicate_backups"


# ---------------------------------------------------------------------------
# 位置
# ---------------------------------------------------------------------------

def scope_key(threshold: float, min_chars: int) -> str:
    """处置作用域键：同一次检测的阈值 + 最短字数（两个数决定组号怎么分）。"""
    return f"t{float(threshold):.2f}-m{int(min_chars)}"


def marks_path(book_id: str, workspace: Path | str | None = None) -> Path | None:
    """这本书的处置记录位置（与按书词库并列同目录）。

    位置由 C1 的按书作用域算出来（:func:`fixtext_book_scope.executed_path`
    往下就是 ``book_vocab.book_vocab_path``），本模块不拼路径、不自己校验书 id；
    书 id 不合规 → ``None``（宁可不记，也不落到别的地方）。
    """
    bid = str(book_id or "").strip()
    if not bid:
        return None
    try:
        base = (_bscope.executed_path(bid, workspace=workspace)
                if workspace is not None else _bscope.executed_path(bid))
    except Exception:
        return None
    return Path(base).with_name(MARKS_FILE) if base else None


def book_id_of_text_path(text_path: str | Path | None) -> str:
    """正文路径 → 书 id（与书架、词库页、E5 记忆同一个口径：书所在目录名）。"""
    raw = str(text_path or "")
    if not raw:
        return ""
    try:
        return str(_bscope.normalize_book_id(Path(raw).resolve().parent.name))
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 规范字节 / 读 / 写
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".dpm-", suffix=".tmp")
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


def _record(obj: Any) -> dict | None:
    """把一条处置记录归一；状态不合法或没有组号 → ``None``（读文件时跳过）。"""
    if not isinstance(obj, dict):
        return None
    gid = str(obj.get("group_id") or "").strip()
    state = str(obj.get("state") or "").strip()
    if not gid or state not in STATES:
        return None
    return {
        "group_id": gid,
        "state": state,
        "at": str(obj.get("at") or ""),
        "signature": str(obj.get("signature") or ""),
        "occurrences": int(obj.get("occurrences") or 0),
        "paragraphs": [int(i) for i in (obj.get("paragraphs") or [])],
    }


def canonical_bytes(book_id: str, scopes: dict[str, dict[str, Any]]) -> bytes:
    """规范字节：作用域升序、组号升序、固定字段序——同一份处置永远同样字节。

    这样"处置前后比对"才有意义：同样的处置集合写两次，字节一定相同。
    """
    out_scopes: list[dict[str, Any]] = []
    for key in sorted(scopes):
        scope = dict(scopes.get(key) or {})
        raw_records = scope.get("records")
        # ``records`` 在内存里是「组号 → 记录」字典；离线读回来的老格式也可能是
        # 列表。两种都收，统一归一再按组号排序落盘。
        if isinstance(raw_records, dict):
            candidates: Iterable[Any] = list(raw_records.values())
        else:
            candidates = list(raw_records or [])
        records: dict[str, dict] = {}
        for rec in candidates:
            r = _record(rec)
            if r is not None:
                records[r["group_id"]] = r
        out_scopes.append({
            "scope": str(key),
            "threshold": float(scope.get("threshold") or 0.0),
            "min_chars": int(scope.get("min_chars") or 0),
            "groups": [records[g] for g in sorted(records) if records[g]["state"]],
        })
    payload = {
        "product": "FixText",
        "kind": MARKS_KIND,
        "version": MARKS_VERSION,
        "book_id": str(book_id or ""),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "note": "按书作用域下的重复段落处置（标记 / 忽略）；与 book_vocab.json 并列，不含任何正文",
        "scopes": out_scopes,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"


def read_file(path: Path | str | None) -> dict:
    """读处置记录：文件不存在 / 坏掉都按「没有处置」返回，不抛。"""
    info: dict[str, Any] = {"configured": False, "book_id": "", "scopes": {},
                            "sha256": "", "raw": b"", "error": ""}
    if not path:
        return info
    p = Path(path)
    if not p.is_file():
        return info
    try:
        raw = p.read_bytes()
    except OSError as exc:
        info["error"] = f"处置记录读不出来（{type(exc).__name__}）"
        return info
    info.update(configured=True, raw=raw, sha256=hashlib.sha256(raw).hexdigest())
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        info["error"] = "处置记录格式无法识别（原文件未被改动）"
        return info
    if not isinstance(data, dict):
        info["error"] = "处置记录结构异常（原文件未被改动）"
        return info
    info["book_id"] = str(data.get("book_id") or "")
    scopes: dict[str, dict[str, Any]] = {}
    for scope in data.get("scopes") or []:
        if not isinstance(scope, dict):
            continue
        key = str(scope.get("scope") or "")
        if not key:
            continue
        recs = {}
        for rec in scope.get("groups") or []:
            r = _record(rec)
            if r is not None and r["state"]:
                recs[r["group_id"]] = r
        scopes[key] = {
            "threshold": float(scope.get("threshold") or 0.0),
            "min_chars": int(scope.get("min_chars") or 0),
            "records": recs,
        }
    info["scopes"] = scopes
    return info


def write_file(path: Path | str, book_id: str,
               scopes: dict[str, dict[str, Any]]) -> dict:
    """写处置记录（规范字节 + 原子写）。返回写后的指纹与条数。"""
    p = Path(path)
    raw = canonical_bytes(book_id, scopes)
    _atomic_write(p, raw)
    total = sum(len((s.get("records") or {})) for s in scopes.values())
    return dict(path=str(p), book_id=str(book_id or ""), count=int(total),
                sha256=hashlib.sha256(raw).hexdigest(), raw=raw)


def states_of(scopes: dict[str, dict[str, Any]], key: str) -> dict[str, str]:
    """某个作用域下的「组号 → 状态」（空 = 这个作用域还没处置过）。"""
    scope = scopes.get(str(key)) or {}
    return {gid: rec.get("state") for gid, rec in (scope.get("records") or {}).items()}


def signature_of(pairs: Iterable[tuple[int, str]]) -> str:
    """组成员签名：段序号 + 段落全文的摘要（正文一改就对不上）。"""
    parts = sorted((int(i), str(t or "")) for i, t in (pairs or ()))
    blob = "\n".join(f"{i}\x1f{t}" for i, t in parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# 处置仓库（状态机 + 撤销）
# ---------------------------------------------------------------------------

class DuplicateMarks:
    """一本书的重复段落处置记录：读、写、清回、撤销。

    典型用法（界面层）::

        mk = DuplicateMarks(store_dir=<书目录>/duplicate_backups)
        bid = mk.bind(text_path)                    # 挂书 + 算书 id
        mk.states(threshold, min_chars)             # 该作用域的处置状态
        mk.set_state("E-1", ST_MARKED, ...)         # 标记
        mk.set_state("E-1", ST_NONE)                # 清回未处置
        mk.undo_last()                              # 撤销最近一次处置
    """

    def __init__(self, *, store_dir: str | Path | None = None,
                 workspace: str | Path | None = None) -> None:
        self._workspace = Path(workspace) if workspace else None
        self._store_dir = Path(store_dir) if store_dir else None
        self.book_id = ""
        #: 本次进程里「还原点 → 书 id」的直记（换新进程回查操作历史兜底）
        self._pt_books: dict[int, str] = {}

    # -- 挂书 / 位置 --------------------------------------------------------

    def bind(self, text_path: str | Path, *,
             store_dir: str | Path | None = None) -> str:
        """挂一本书：算出书 id 与还原点仓库目录。返回书 id（空 = 不可记）。"""
        if store_dir is not None:
            self._store_dir = Path(store_dir)
        elif self._store_dir is None and text_path:
            self._store_dir = Path(text_path).resolve().parent / BACKUP_DIRNAME
        self.book_id = book_id_of_text_path(text_path)
        return self.book_id

    def path(self) -> Path | None:
        return marks_path(self.book_id, workspace=self._workspace)

    def info(self) -> dict:
        return read_file(self.path())

    def _store(self) -> SnapshotStore:
        """还原点仓库：**每次操作新建一个实例**。

        ``SnapshotStore`` 只在构造时载入一次索引；长期持有同一个实例、又和
        别的页面共用目录，会让另一方的写入被旧内存状态覆盖。处置动作是离散的
        单步操作，每次现开现用最稳——这也让处置记录与书稿编辑互不干扰
        （后者用书目录下的 ``batch_backups``，本模块用 ``duplicate_backups``）。
        """
        d = self._store_dir or (Path(self.path()).parent / BACKUP_DIRNAME
                               if self.path() else None)
        if d is None:
            raise ValueError("还没有选中的书，不能记处置")
        return SnapshotStore(Path(d))

    def _raw(self) -> bytes:
        p = self.path()
        return _bscope.raw_bytes(p) if p else b""

    # -- 读 ----------------------------------------------------------------

    def scopes(self) -> dict[str, dict[str, Any]]:
        return dict(self.info().get("scopes") or {})

    def states(self, threshold: float, min_chars: int) -> dict[str, str]:
        """该作用域下的处置状态（组号 → ``marked`` / ``ignored``）。"""
        return states_of(self.scopes(), scope_key(threshold, min_chars))

    def records(self, threshold: float, min_chars: int) -> dict[str, dict]:
        """该作用域下的处置记录（含签名与时间，界面用它判「正文已改动」）。"""
        scope = self.scopes().get(scope_key(threshold, min_chars)) or {}
        return dict(scope.get("records") or {})

    def counts(self, threshold: float, min_chars: int) -> dict[str, int]:
        recs = self.records(threshold, min_chars)
        marked = sum(1 for r in recs.values() if r.get("state") == ST_MARKED)
        ignored = sum(1 for r in recs.values() if r.get("state") == ST_IGNORED)
        return {"marked": marked, "ignored": ignored, "total": len(recs)}

    # -- 写（状态机 + 还原点）----------------------------------------------

    def _require(self) -> tuple[str, Path]:
        bid = str(self.book_id or "").strip()
        if not bid:
            raise ValueError("这本书不能记处置（书所在目录名不合规）")
        p = self.path()
        if p is None:
            raise ValueError("这本书不能记处置（按书作用域算不出位置）")
        return bid, Path(p)

    def set_state(self, group_id: str, state: str, *,
                 threshold: float, min_chars: int,
                 signature: str = "", occurrences: int = 0,
                 paragraphs: Iterable[int] | None = None,
                 label: str = "") -> dict:
        """改一组的处置状态（状态机唯一入口）。

        ``state`` 只能取 :data:`STATES` 三值：``marked`` 标记 / ``ignored``
        忽略 / ``""`` 清回未处置。状态没变时**不写盘、不留还原点**（幂等）。
        """
        gid = str(group_id or "").strip()
        if not gid:
            raise ValueError("要处置的那一组没有编号")
        if state not in STATES:
            raise ValueError(f"处置只有「标记 / 忽略」两态，收到的是「{state}」")
        bid, p = self._require()
        key = scope_key(threshold, min_chars)
        scopes = self.scopes()
        scope = dict(scopes.get(key) or {"threshold": float(threshold),
                                         "min_chars": int(min_chars),
                                         "records": {}})
        recs = dict(scope.get("records") or {})
        old = dict(recs.get(gid) or {})
        old_state = str(old.get("state") or "")
        if old_state == state:
            return dict(changed=False, state=state, group_id=gid, point_id=0,
                        scope=key, count=len(recs), book_id=bid, identical=True)

        before = self._raw()
        if state == ST_NONE:
            recs.pop(gid, None)
        else:
            recs[gid] = {
                "group_id": gid,
                "state": state,
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "signature": str(signature or old.get("signature") or ""),
                "occurrences": int(occurrences or old.get("occurrences") or 0),
                "paragraphs": [int(i) for i in (paragraphs
                                                if paragraphs is not None
                                                else old.get("paragraphs") or [])],
            }
        scope["threshold"] = float(threshold)
        scope["min_chars"] = int(min_chars)
        scope["records"] = recs
        scopes[key] = scope

        store = self._store()
        pid = store.begin(label=label or _default_label(state, gid),
                          act=ACT_DUPLICATE_MARK, before_bytes=before)
        try:
            res = write_file(p, bid, scopes)
        except Exception:
            store.abort(pid)
            raise
        after = self._raw()
        store.commit(pid, after_bytes=after)
        self._pt_books[pid] = bid
        point = store.get(pid) or {}
        store.log_op(
            act=ACT_DUPLICATE_MARK, summary=label or _default_label(state, gid),
            point_id=pid,
            sha_before=str(point.get("sha_before") or ""),
            sha_after=str(point.get("sha_after") or ""),
            detail=dict(book_id=bid, scope=key, group_id=gid,
                        state_from=old_state, state_to=state,
                        count=len(recs), file_sha_after=res.get("sha256", "")),
        )
        return dict(changed=True, state=state, group_id=gid, point_id=pid,
                    scope=key, count=len(recs), book_id=bid,
                    sha256=res.get("sha256", ""), identical=False,
                    from_state=old_state)

    def clear_scope(self, *, threshold: float, min_chars: int,
                    label: str = "") -> dict:
        """把这个作用域的处置整批清回未处置（撤销那一整轮判断）。"""
        bid, p = self._require()
        key = scope_key(threshold, min_chars)
        scopes = self.scopes()
        scope = scopes.get(key) or {}
        recs = dict(scope.get("records") or {})
        if not recs:
            return dict(changed=False, point_id=0, count=0, book_id=bid, scope=key)
        before = self._raw()
        scope["records"] = {}
        scopes[key] = scope
        store = self._store()
        pid = store.begin(label=label or f"清回 {len(recs)} 组处置",
                          act=ACT_DUPLICATE_MARK, before_bytes=before)
        try:
            res = write_file(p, bid, scopes)
        except Exception:
            store.abort(pid)
            raise
        after = self._raw()
        store.commit(pid, after_bytes=after)
        self._pt_books[pid] = bid
        point = store.get(pid) or {}
        store.log_op(act=ACT_DUPLICATE_MARK, summary=label or f"清回 {len(recs)} 组处置",
                     point_id=pid,
                     sha_before=str(point.get("sha_before") or ""),
                     sha_after=str(point.get("sha_after") or ""),
                     detail=dict(book_id=bid, scope=key, cleared=len(recs),
                                 file_sha_after=res.get("sha256", "")))
        return dict(changed=True, point_id=pid, count=0, book_id=bid, scope=key,
                    cleared=len(recs), sha256=res.get("sha256", ""))

    # -- 撤销 --------------------------------------------------------------

    def _book_of_point(self, store: SnapshotStore, point_id: int) -> str:
        bid = self._pt_books.get(int(point_id), "")
        if bid:
            return bid
        for op in store.ops():
            if int(op.get("point_id") or 0) == int(point_id):
                got = str((op.get("detail") or {}).get("book_id") or "")
                if got:
                    return got
        return ""

    def _newest_point(self, store: SnapshotStore) -> dict | None:
        for row in sorted(store.points(), key=lambda r: int(r["id"]), reverse=True):
            if row.get("undone"):
                continue
            if str(row.get("act") or "") not in _MARK_ACTS:
                continue
            if store.before_bytes(int(row["id"])) is None:
                continue
            if not self._book_of_point(store, int(row["id"])):
                continue
            return row
        return None

    def can_undo(self) -> bool:
        try:
            return self._newest_point(self._store()) is not None
        except Exception:
            return False

    def undo_last(self) -> dict | None:
        """撤销最近一次处置：把处置记录写回该还原点的「处置前」字节。

        只认本模块的两类动作；``identical`` 按**字节**核（空文件没有指纹，
        与"空内容的指纹"混比会假报不一致）。
        """
        try:
            store = self._store()
        except Exception:
            return None
        row = self._newest_point(store)
        if row is None:
            return None
        pid = int(row["id"])
        raw = store.before_bytes(pid)
        if raw is None:
            return None
        bid = self._book_of_point(store, pid)
        if not bid:
            return None
        p = marks_path(bid, workspace=self._workspace)
        if p is None:
            return None
        _bscope.restore_bytes(p, raw)
        now = _bscope.raw_bytes(p)
        store.mark_undone(pid, True)
        self._pt_books.pop(pid, None)
        store.log_op(act=ACT_DUPLICATE_RESTORE,
                     summary=f"撤销「{row.get('label', '')}」", point_id=pid,
                     sha_before=str(row.get("sha_before") or ""),
                     sha_after=_bscope.sha_of(now),
                     detail=dict(book_id=bid, undone_point=pid))
        return dict(point_id=pid, book_id=bid,
                    label=str(row.get("label") or ""),
                    identical=bool(now == raw))

    def history(self, limit: int = 20) -> list[dict]:
        """处置时间线（与书稿编辑的还原点分开存放，界面能单列一块）。"""
        try:
            store = self._store()
        except Exception:
            return []
        rows: list[dict] = []
        for p in store.points():
            if str(p.get("act") or "") not in _MARK_ACTS:
                continue
            rows.append(dict(point_id=int(p["id"]),
                             label=str(p.get("label") or ""),
                             act=str(p.get("act") or ""),
                             time=str(p.get("time") or ""),
                             undone=bool(p.get("undone"))))
            if len(rows) >= limit:
                break
        return rows


def _default_label(state: str, group_id: str) -> str:
    if state == ST_MARKED:
        return f"标记重复组 {group_id}"
    if state == ST_IGNORED:
        return f"忽略重复组 {group_id}"
    return f"清回重复组 {group_id} 的处置"


__all__ = [
    "MARKS_FILE", "MARKS_VERSION", "MARKS_KIND", "BACKUP_DIRNAME",
    "ST_NONE", "ST_MARKED", "ST_IGNORED", "STATES", "STATE_NAMES",
    "ACT_DUPLICATE_MARK", "ACT_DUPLICATE_RESTORE",
    "scope_key", "marks_path", "book_id_of_text_path", "signature_of",
    "canonical_bytes", "read_file", "write_file", "states_of",
    "DuplicateMarks",
]
