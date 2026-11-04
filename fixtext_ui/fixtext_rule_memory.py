"""V1.1-E5 · 已执行规则的可管理记忆（界面侧，不依赖 Qt）

排期 §10.6 的两条交付物在这里接上：

* **交付物①「已执行规则的 mark 记忆」**：某条手动检索规则在某本书上执行过
  之后被记住，下次在同一本书上自动排除、不再重复提示重跑；
* **交付物②「与 C 组按书词库的联动接线」**：记忆的作用域**按书隔离**，
  落点复用 C1 已交付的按书数据层，不另造存储根。

落点与语义（本卡最要紧的一处取舍）
----------------------------------
C1 的 ``book_vocab.json`` 承载的是**词条排除项**，键是
``entry_key(word, value)`` 的内容键；本卡记的是**规则标识** ``Rule.mark``
（如 ``{盍->阖}``），是规则维度、没有 ``(原词, 替换值)`` 二元组。

所以本模块**在同一个按书作用域目录下另放一份并列文件**
``<按书作用域>/executed_rules.json``：

* 位置由 :func:`fixtext_book_scope.executed_path` 算，它往下就是 C1 的
  ``book_vocab.book_vocab_path``——书 id 校验与作用域目录**同一个实现**，
  这里不拼路径、不算键；
* ``book_vocab.json`` 一个字节都不受影响，``resolve_excluded()`` 的并集口径
  天然不被污染（``overlap`` / ``global_only`` / ``book_only`` 三个来源统计
  全部照旧）。

不装载层
--------
排期 §11.2 的「装载层唯一入口」（``vocab_bridge.compose()`` /
``bags.write_round_rules()``）管的是**词条过滤**。本卡排除的是**规则是否
重跑**，属规则选择层：这里没有给 ``compose`` 加任何过滤路径，只在
:class:`fixtext_batch_confirm.BatchSession` 的挑选方法上接一层「已执行过的
先不选」，并把指纹喂给 ``ReplaceStage.fingerprint()``。

记账走既有体系
--------------
写入 / 清除 / 撤回都经 :class:`fixtext_snapshot.SnapshotStore`——与 E4 每批
备份同一个仓库、同一份 ``index.json``、同一套「还原点 + 操作历史」，不另造
一套撤销。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import fixtext_book_scope as _bscope
from fixtext_snapshot import SnapshotStore

#: 还原点 / 操作历史里的动作名（与 E4 的 ``batch_replace`` / ``batch_undo`` 并列）
ACT_RULE_EXECUTED = "rule_memory_mark"
ACT_RULE_MEMORY_CLEAR = "rule_memory_clear"
ACT_RULE_MEMORY_RESTORE = "rule_memory_restore"

#: 本模块认的还原点动作（撤回时只挑这几类，绝不碰每批替换的备份点）
_MEMORY_ACTS = (ACT_RULE_EXECUTED, ACT_RULE_MEMORY_CLEAR, ACT_RULE_MEMORY_RESTORE)


def executed_rules_module():
    """懒加载管线侧的数据层（与按书词库属于同一个包，不另建模块树）。"""
    return _bscope.pipeline_executed_rules()


def file_name() -> str:
    """并列文件名（唯一事实来源在管线侧数据层的常量里）。"""
    return str(executed_rules_module().EXECUTED_RULES_FILE)


def book_id_of_text_path(text_path: str | Path | None) -> str:
    """正文路径 → 书 id（与书架、词库页同一个口径：书所在目录名）。

    不合规的书 id（C1 安全字符集之外）返回空串——宁可不记，也不把记忆
    落到别的地方去（界面把它翻成人话，不静默降级）。
    """
    raw = str(text_path or "")
    if not raw:
        return ""
    try:
        name = Path(raw).resolve().parent.name
        return str(_bscope.normalize_book_id(name))
    except Exception:
        return ""


class RuleMemory:
    """一本书的「已执行规则」记忆：读、写、清、撤回，全部经既有还原点仓库。

    典型用法（界面层）::

        mem = RuleMemory(store_dir=<书目录>/batch_backups)
        bid = mem.bind(text_path)              # 挂书 + 算书 id
        mem.marks(bid)                         # 已执行过的规则标识（空集 = 没记过）
        mem.remember(bid, [{...}])             # 执行完一批后追加
        mem.forget(bid, marks)                 # 撤掉某几条
        mem.clear(bid)                         # 整本清空
        mem.undo_last()                        # 撤回最近一次记忆变更
    """

    def __init__(self, *, store: SnapshotStore | None = None,
                 store_dir: str | Path | None = None,
                 workspace: str | Path | None = None) -> None:
        self._workspace = Path(workspace) if workspace else None
        self.store = store if store is not None else (
            SnapshotStore(Path(store_dir)) if store_dir is not None else None)
        #: 本次进程里「还原点 → 书 id」的直记（换新进程时回查操作历史兜底）
        self._pt_books: dict[int, str] = {}

    # -- 位置 -------------------------------------------------------------

    def path_for(self, book_id: str) -> Path | None:
        """这本书的执行记忆位置（按书作用域内、与 ``book_vocab.json`` 并列）。"""
        bid = str(book_id or "").strip()
        if not bid:
            return None
        try:
            p = (_bscope.executed_path(bid, workspace=self._workspace)
                 if self._workspace is not None else _bscope.executed_path(bid))
        except Exception:
            return None
        return Path(p) if p else None

    def bind(self, text_path: str | Path, *, store_dir: str | Path | None = None) -> str:
        """挂一本书：算出书 id 与这份记忆所属的还原点仓库。返回书 id（空 = 不可记）。

        还原点仓库默认跟着书目录走（``<书目录>/batch_backups``），与 E4 每批
        备份**同一个目录**——同一套历史，不分裂成两份。
        """
        if store_dir is not None:
            self.store = SnapshotStore(Path(store_dir))
        elif self.store is None and text_path:
            self.store = SnapshotStore(Path(text_path).resolve().parent / "batch_backups")
        return book_id_of_text_path(text_path)

    # -- 读 ---------------------------------------------------------------

    def info(self, book_id: str) -> dict:
        """这本书的记忆详情（文件不存在 / 坏掉都按「没有记忆」返回，不抛）。"""
        base = executed_rules_module()
        p = self.path_for(book_id)
        if p is None:
            return dict(configured=False, book_id=str(book_id or ""), path="",
                        marks={}, mark_set=frozenset(),
                        marks_sha=base.executed_marks_sha(()), sha256="", error="")
        return base.read_executed(p)

    def marks(self, book_id: str) -> frozenset[str]:
        """已执行过的规则标识集合（没有记忆 → 空集）。"""
        return self.info(book_id)["mark_set"]

    def records(self, book_id: str) -> dict[str, dict]:
        return dict(self.info(book_id)["marks"])

    def marks_sha(self, book_id: str) -> str:
        """mark 集合指纹（与 ``ReplaceStage.fingerprint()`` 里那一项同一算法）。"""
        return str(self.info(book_id)["marks_sha"])

    @staticmethod
    def reason(rec: dict | None) -> str:
        """给界面的排除原因（人话，不提文件、不提内部标识）。"""
        rec = rec or {}
        bits = ["这本书上已经执行过这条规则"]
        batch = int(rec.get("batch") or 0)
        hits = int(rec.get("hits") or 0)
        if batch:
            bits.append(f"第 {batch} 批")
        if hits:
            bits.append(f"当时改了 {hits} 处")
        return "，".join(bits) + "；默认不再重复提示，需要再跑可以手动勾选"

    def rows(self, book_id: str) -> list[dict]:
        """界面用的行清单（mark 升序），带人话原因、不含任何路径。"""
        recs = self.records(book_id)
        out: list[dict] = []
        for mark in sorted(recs):
            rec = recs[mark]
            out.append(dict(mark=mark,
                            batch=int(rec.get("batch") or 0),
                            hits=int(rec.get("hits") or 0),
                            at=str(rec.get("at") or ""),
                            point_id=int(rec.get("point_id") or 0),
                            reason=self.reason(rec)))
        return out

    # -- 写（一律经既有还原点 + 操作历史）-----------------------------------

    def _raw(self, book_id: str) -> bytes:
        p = self.path_for(book_id)
        return _bscope.raw_bytes(p) if p else b""

    def _require(self, book_id: str, what: str) -> tuple[str, Path]:
        bid = str(book_id or "").strip()
        if not bid:
            raise ValueError(f"{what}这本书不能记执行记录（书 id 不合规）")
        p = self.path_for(bid)
        if p is None:
            raise ValueError(f"{what}这本书不能记执行记录（按书作用域算不出位置）")
        if self.store is None:
            raise ValueError(f"{what}还没有选中的书，不能记执行记录")
        return bid, Path(p)

    def _apply(self, *, book_id: str, act: str, label: str, mutate,
               detail: dict | None = None) -> dict:
        """写一次记忆：留还原点 → 改文件 → 提交 → 记操作历史。

        ``mutate(old_marks) -> 新记录字典``。记忆本来就一样时**不写文件、
        不留还原点**（重复执行同一批不会把历史刷成一串空条目）。
        """
        bid, p = self._require(book_id, "")
        base = executed_rules_module()
        before = self._raw(bid)
        old = base.read_executed(p)
        records = mutate(dict(old["marks"]))
        new_set = frozenset(records)
        if new_set == old["mark_set"]:
            return dict(changed=False, count=len(new_set), point_id=0, book_id=bid,
                        marks_sha=old["marks_sha"], sha256=old["sha256"],
                        mark_set=new_set, added=frozenset(), removed=frozenset())

        pid = self.store.begin(label=label, act=act, before_bytes=before)
        try:
            res = base.write_executed(p, bid, list(records.values()))
        except Exception:
            self.store.abort(pid)
            raise
        after = self._raw(bid)
        self.store.commit(pid, after_bytes=after)
        added = frozenset(new_set - old["mark_set"])
        removed = frozenset(old["mark_set"] - new_set)
        self._pt_books[pid] = bid
        point = self.store.get(pid) or {}
        self.store.log_op(
            act=act, summary=label, point_id=pid,
            sha_before=str(point.get("sha_before") or ""),
            sha_after=str(point.get("sha_after") or ""),
            detail=dict(book_id=bid, marks=sorted(new_set),
                        added=sorted(added), removed=sorted(removed),
                        count=len(new_set), **(detail or {}),
                        file_sha_before=str(old.get("sha256") or ""),
                        file_sha_after=_bscope.sha_of(after)),
        )
        return dict(changed=True, count=len(new_set), point_id=pid, book_id=bid,
                    marks_sha=str(res.get("marks_sha") or ""),
                    sha256=str(res.get("sha256") or ""),
                    mark_set=new_set, added=added, removed=removed)

    def remember(self, book_id: str, items: Iterable[dict | str], *,
                 label: str = "") -> dict:
        """追加一批「已执行」记忆（同 mark 只留一条，重复执行幂等）。"""
        incoming: list[dict] = []
        for obj in items or ():
            rec = dict(mark=str(obj).strip()) if isinstance(obj, str) else dict(obj)
            if str(rec.get("mark") or "").strip():
                incoming.append(rec)
        if not incoming:
            return dict(changed=False, count=len(self.marks(book_id)), point_id=0,
                        book_id=str(book_id or ""), marks_sha=self.marks_sha(book_id),
                        added=frozenset(), removed=frozenset())

        def _mutate(old: dict[str, dict]) -> dict[str, dict]:
            out = dict(old)
            for obj in incoming:
                mark = str(obj.get("mark") or "").strip()
                rec = dict(out.get(mark) or {})
                rec["mark"] = mark
                for key in ("at", "batch", "hits", "point_id"):
                    if obj.get(key) not in (None, ""):
                        rec[key] = obj[key]
                rec.setdefault("at", "")
                rec.setdefault("batch", 0)
                rec.setdefault("hits", 0)
                rec.setdefault("point_id", 0)
                out[mark] = rec
            return out

        return self._apply(book_id=book_id, act=ACT_RULE_EXECUTED,
                           label=label or f"记录 {len(incoming)} 条已执行规则",
                           mutate=_mutate, detail=dict(source="batch_confirm"))

    def forget(self, book_id: str, marks: Iterable[str], *,
               label: str = "") -> dict:
        """撤掉某几条记忆（撤回那一批 / 只清一条时用；其余记忆保留）。"""
        drop = {str(m) for m in (marks or ()) if str(m)}
        if not drop:
            return dict(changed=False, count=len(self.marks(book_id)), point_id=0,
                        book_id=str(book_id or ""), marks_sha=self.marks_sha(book_id),
                        added=frozenset(), removed=frozenset())

        def _mutate(old: dict[str, dict]) -> dict[str, dict]:
            return {k: v for k, v in old.items() if k not in drop}

        return self._apply(book_id=book_id, act=ACT_RULE_MEMORY_CLEAR,
                           label=label or f"清除 {len(drop)} 条执行记录",
                           mutate=_mutate, detail=dict(source="manual"))

    def clear(self, book_id: str, *, label: str = "") -> dict:
        """整本清空（清空后这些规则重新回到候选）。"""
        return self.forget(book_id, sorted(self.marks(book_id)),
                           label=label or "清空本书的执行记录")

    # -- 撤回（只撤回本模块自己的还原点）-----------------------------------

    def _book_of_point(self, point_id: int) -> str:
        """还原点属于哪本书：先查本次进程的直记，再回查既有操作历史。

        还原点的 ``book_id`` 槽位是留给按书词库字节的（C1/C2 的撤销靠它写回
        ``book_vocab.json``），本卡不动那份语义；记忆点的书 id 记在**操作历史**
        的 ``detail`` 里，换一个新进程照样反查得到。
        """
        bid = self._pt_books.get(int(point_id), "")
        if bid:
            return bid
        if self.store is None:
            return ""
        for op in self.store.ops():
            if op.get("point_id") == int(point_id):
                got = str((op.get("detail") or {}).get("book_id") or "")
                if got:
                    return got
        return ""

    def _newest_memory_point(self) -> dict | None:
        if self.store is None:
            return None
        for row in sorted(self.store.points(), key=lambda r: int(r["id"]), reverse=True):
            if row.get("undone"):
                continue
            if str(row.get("act") or "") not in _MEMORY_ACTS:
                continue
            if self.store.before_bytes(int(row["id"])) is None:
                continue
            if not self._book_of_point(int(row["id"])):
                continue
            return row
        return None

    def can_undo(self) -> bool:
        return self._newest_memory_point() is not None

    def undo_last(self) -> dict | None:
        """撤回最近一次记忆变更：把这份文件写回该还原点的「操作前」字节。

        只认 ``rule_memory_*`` 三类动作——每批替换的备份点与它共用同一个仓库
        （``batch_backups``），绝不能在这里被当成记忆变更来回写。
        """
        row = self._newest_memory_point()
        if row is None or self.store is None:
            return None
        pid = int(row["id"])
        raw = self.store.before_bytes(pid)
        if raw is None:
            return None
        book_id = self._book_of_point(pid)
        if not book_id:
            return None
        p = self.path_for(book_id)
        if p is None:
            return None
        _bscope.restore_bytes(p, raw)
        now = self._raw(book_id)
        self.store.mark_undone(pid, True)
        self._pt_books.pop(pid, None)
        self.store.log_op(act=ACT_RULE_MEMORY_RESTORE,
                          summary=f"撤回「{row.get('label', '')}」",
                          point_id=pid,
                          sha_before=str(row.get("sha_before") or ""),
                          sha_after=_bscope.sha_of(now),
                          detail=dict(book_id=book_id, undone_point=pid))
        return dict(point_id=pid, book_id=book_id,
                    label=str(row.get("label") or ""),
                    marks_sha=self.marks_sha(book_id),
                    # 「回到写之前」按**字节**核：空文件没有 sha（""）而还原点存的是
                    # sha256(b"")，两套口径混比会假报不一致。
                    identical=bool(now == raw))

    def history(self, limit: int = 20) -> list[dict]:
        """本模块产生的时间线（与既有「历史与快照」同一份仓库，不另造）。"""
        if self.store is None:
            return []
        rows: list[dict] = []
        for p in self.store.points():
            if str(p.get("act") or "") not in _MEMORY_ACTS:
                continue
            rows.append(dict(point_id=int(p["id"]),
                             label=str(p.get("label") or ""),
                             act=str(p.get("act") or ""),
                             time=str(p.get("time") or ""),
                             undone=bool(p.get("undone")),
                             book_id=self._book_of_point(int(p["id"]))))
            if len(rows) >= limit:
                break
        return rows
