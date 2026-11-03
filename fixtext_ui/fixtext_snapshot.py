"""
FixText V1 · 词库还原点与操作历史（M3-T3.2）
============================================

.. note::
   另一个同名概念（运行阶段点恢复，M3-T3.4）在同目录的
   :mod:`fixtext_run_snapshot` 里。本模块管**词库文件**的还原点（撤销 / 恢复到
   某次写操作前后），那个管**运行产物**的阶段点（恢复到某阶段 / 从该点续跑）。
   两者职责不重叠，不要互相导入。

本模块**不依赖 Qt**，只负责「词库变更的还原点」的落盘与读取。
界面层（``vocab_module.py``）只通过这里的接口取列表、取字节，不碰目录。

为什么必须落盘
--------------
T3.1 的撤销栈在内存里：程序一关，还原点全没，用户再也回不到昨天的状态。
本模块把还原点做成**磁盘上的东西**：

* 每个还原点保存这次写操作**发生之前**和**发生之后**两份原始字节（整份复制，
  不重新序列化），并各记一个 sha256。于是两条判据都变成硬的：
  撤回 = 写回「操作前」字节，sha 与当初相同；
  恢复到此刻 = 写回「操作后」字节，sha 与当初相同。
* 操作历史按发生顺序追加，记下每次动作的时间点、摘要与前后内容摘要，
  供界面上的「历史与快照」面板展示，并与还原点 id 联动。

索引一次性 ``os.replace`` 落盘（要么全在、要么全不在），个别大块数据
（内置词库那一份）单独存文件并在索引里记它的 sha，读取时校验。

目录
----
默认 ``<包根>/workspace/vocab/snapshots/``——与自定义词库（``custom_vocab.json``）同属
用户区、不同子目录；与内置词库（``data/rules/``）完全分离。界面只显示
「历史与快照」，不出现任何路径。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import zlib
from pathlib import Path
from typing import Any

INDEX_NAME = "index.json"
INDEX_VERSION = 2

#: 还原点上限（超出的按最旧的淘汰，磁盘不会无限长）
MAX_POINTS = 200
#: 操作历史上限
MAX_OPS = 1000
#: 内置词库大块数据最多留几份（每份压缩后数 MB；只有「恢复默认」才会产生）
MAX_BUILTIN_BLOBS = 3


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _now() -> tuple[str, float]:
    epoch = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch)), epoch


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".snap-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        # 【M3-EX.1c】目录 fsync 只在类 Unix 上做。Windows 不允许把目录当文件
        # 打开（os.open(目录) 抛 PermissionError），而这条语句在 finally 之外，
        # 会连带把已经成功的写入报成失败——新增/合并/删除/恢复默认/撤销全废。
        # 数据本身在 os.replace 时已落盘，跳过目录 fsync 不影响可靠性。
        if os.name != "nt":
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


class SnapshotStore:
    """还原点 + 操作历史的磁盘仓库。

    一次写操作的标准用法::

        pid = store.begin(label="新增「萧衍」", act="add", before_bytes=改动前字节)
        ... 真正写词库 ...
        store.commit(pid, after_bytes=改动后字节)
    """

    def __init__(self, dir_path: Path | str, *, max_points: int = MAX_POINTS,
                 max_ops: int = MAX_OPS):
        self.dir = Path(dir_path)
        self.max_points = max(1, int(max_points))
        self.max_ops = max(10, int(max_ops))
        self.index_path = self.dir / INDEX_NAME
        self.error = ""
        self._state: dict[str, Any] = {"version": INDEX_VERSION, "seq": 0,
                                       "points": [], "ops": []}
        self._load()

    # ------------------------------------------------------------------ 载入 / 落盘

    def _load(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.error = f"还原点目录不可用（{type(exc).__name__}）"
            return
        if not self.index_path.is_file():
            return
        try:
            data = json.loads(self.index_path.read_text("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            # 索引坏了：保留原文件不动（不删用户的还原点），按空列表继续
            self.error = "还原点索引无法读取，已按空列表显示（原索引未被改动）"
            return
        if not isinstance(data, dict):
            self.error = "还原点索引结构异常"
            return
        self._state = {
            "version": int(data.get("version") or INDEX_VERSION),
            "seq": int(data.get("seq") or 0),
            "points": [p for p in (data.get("points") or []) if isinstance(p, dict)],
            "ops": [o for o in (data.get("ops") or []) if isinstance(o, dict)],
        }

    def _flush(self) -> None:
        raw = json.dumps(self._state, ensure_ascii=False, indent=1).encode("utf-8")
        try:
            _atomic_write(self.index_path, raw)
        except OSError as exc:
            self.error = f"还原点索引写入失败（{type(exc).__name__}）"

    # ------------------------------------------------------------------ 载荷读写

    def _write_payload(self, name: str, raw: bytes) -> str:
        self._write_raw(name, raw)
        return sha256_bytes(raw)

    def _write_raw(self, name: str, raw: bytes) -> None:
        try:
            _atomic_write(self.dir / name, raw)
        except OSError as exc:
            self.error = f"还原点数据写入失败（{type(exc).__name__}）"

    def _read_verified(self, name: str | None, want_sha: str) -> bytes | None:
        """读载荷并校验 sha——内容对不上就当它不存在，不让它冒充还原点。"""
        if not name:
            return None
        try:
            raw = (self.dir / name).read_bytes()
        except OSError:
            return None
        if want_sha and sha256_bytes(raw) != want_sha:
            return None
        return raw

    @staticmethod
    def pack_builtin(files: dict[str, bytes]) -> bytes:
        """内置词库多份文件打成一个压缩块（体积要省，还原时再拆开）。"""
        blob = json.dumps({k: v.hex() for k, v in files.items()}).encode("utf-8")
        return zlib.compress(blob, 9)

    @staticmethod
    def unpack_builtin(packed: bytes) -> dict[str, bytes]:
        data = json.loads(zlib.decompress(packed).decode("utf-8"))
        return {k: bytes.fromhex(v) for k, v in data.items()}

    # ------------------------------------------------------------------ 还原点

    def begin(self, *, label: str, act: str, before_bytes: bytes,
              builtin_before: dict[str, bytes] | None = None,
              builtin_sha_before: str = "",
              words_before: bytes | None = None) -> int:
        """写操作前调用：把「操作前」的状态留成还原点，返回还原点 id。

        ``words_before``（V1.1-T1.1）：词条启用 / 禁用集文件的原始字节。
        ``None`` = 这次操作不动禁用集（不落 words 载荷，撤销时也不碰）；
        ``b""`` = 操作前禁用集文件还不存在（撤销 = 删掉文件）。
        """
        self._state["seq"] = int(self._state.get("seq") or 0) + 1
        pid = self._state["seq"]
        at, epoch = _now()
        before_sha = self._write_payload(f"p{pid:05d}-before.bin", before_bytes)
        point: dict[str, Any] = {
            "id": pid,
            "label": str(label)[:120],
            "act": str(act),
            "at": at,
            "epoch": epoch,
            "sha_before": before_sha,
            "size_before": len(before_bytes),
            "before_payload": f"p{pid:05d}-before.bin",
            "sha_after": "",
            "size_after": 0,
            "after_payload": "",
            "undone": False,
            "builtin_sha_before": str(builtin_sha_before or ""),
            "builtin_sha_after": "",
        }
        if builtin_before:
            packed = self.pack_builtin(builtin_before)
            point["builtin_before"] = {
                "sha256": self._write_payload(f"p{pid:05d}-builtin.bin", packed),
                "payload": f"p{pid:05d}-builtin.bin",
                "files": {k: sha256_bytes(v) for k, v in builtin_before.items()},
            }
        if words_before is not None:
            point["words_before"] = {
                "sha256": self._write_payload(f"p{pid:05d}-words.bin", words_before),
                "payload": f"p{pid:05d}-words.bin",
            }
        self._state["points"].append(point)
        self._prune()
        self._flush()
        return pid

    def commit(self, point_id: int, *, after_bytes: bytes,
               builtin_after_is_factory: bool = False,
               builtin_sha_after: str = "",
               words_after: bytes | None = None) -> dict:
        """写操作成功后调用：把「操作后」的状态记进同一个还原点。

        返回 ``{sha_before, sha_after}``——两个 sha 分别对应「撤回后」和
        「恢复到此刻后」的文件指纹，验收时直接拿它们比对。
        """
        p = self._point(point_id)
        if p is None:
            return {}
        p["sha_after"] = self._write_payload(f"p{point_id:05d}-after.bin", after_bytes)
        p["size_after"] = len(after_bytes)
        p["after_payload"] = f"p{point_id:05d}-after.bin"
        p["builtin_after_factory"] = bool(builtin_after_is_factory)
        if builtin_sha_after:
            p["builtin_sha_after"] = str(builtin_sha_after)
        if words_after is not None:
            p["words_after"] = {
                "sha256": self._write_payload(f"p{point_id:05d}-words-after.bin", words_after),
                "payload": f"p{point_id:05d}-words-after.bin",
            }
        self._flush()
        return dict(sha_before=p.get("sha_before", ""), sha_after=p["sha_after"])

    def abort(self, point_id: int) -> None:
        """写操作失败时撤掉这个还原点（删行 + 删载荷），不留半截记录。"""
        p = self._point(point_id)
        if p is None:
            return
        self._state["points"] = [x for x in (self._state.get("points") or [])
                                 if int(x.get("id") or 0) != int(point_id)]
        for name in (p.get("before_payload"), p.get("after_payload"),
                     (p.get("builtin_before") or {}).get("payload"),
                     (p.get("words_before") or {}).get("payload"),
                     (p.get("words_after") or {}).get("payload")):
            if not name:
                continue
            try:
                (self.dir / name).unlink()
            except OSError:
                pass
        self._flush()

    def get(self, point_id: int) -> dict | None:
        p = self._point(point_id)
        return dict(p) if p else None

    def _point(self, point_id: int) -> dict | None:
        for p in self._state.get("points") or []:
            if int(p.get("id") or 0) == int(point_id):
                return p
        return None

    def before_bytes(self, point_id: int) -> bytes | None:
        p = self._point(point_id)
        if p is None:
            return None
        return self._read_verified(p.get("before_payload"), p.get("sha_before") or "")

    def after_bytes(self, point_id: int) -> bytes | None:
        p = self._point(point_id)
        if p is None or not p.get("after_payload"):
            return None
        return self._read_verified(p.get("after_payload"), p.get("sha_after") or "")

    def builtin_before(self, point_id: int) -> dict[str, bytes] | None:
        p = self._point(point_id)
        blob = (p or {}).get("builtin_before") or {}
        packed = self._read_verified(blob.get("payload"), blob.get("sha256") or "")
        if packed is None:
            return None
        try:
            return self.unpack_builtin(packed)
        except (ValueError, zlib.error):
            return None

    def builtin_after_is_factory(self, point_id: int) -> bool:
        return bool((self._point(point_id) or {}).get("builtin_after_factory"))

    def words_before(self, point_id: int) -> bytes | None:
        """该还原点的禁用集「操作前」字节；没动过禁用集的操作返回 ``None``。"""
        p = self._point(point_id)
        blob = (p or {}).get("words_before") or {}
        return self._read_verified(blob.get("payload"), blob.get("sha256") or "")

    def words_after(self, point_id: int) -> bytes | None:
        """该还原点的禁用集「操作后」字节；没动过禁用集的操作返回 ``None``。"""
        p = self._point(point_id)
        blob = (p or {}).get("words_after") or {}
        return self._read_verified(blob.get("payload"), blob.get("sha256") or "")

    def mark_undone(self, point_id: int, undone: bool = True) -> None:
        p = self._point(point_id)
        if p is None:
            return
        p["undone"] = bool(undone)
        self._flush()

    def mark_undone_newer_than(self, point_id: int) -> int:
        """恢复到更早的时间点后，比它更新的那些时间点已不在当前这条线上。"""
        n = 0
        for p in self._state.get("points") or []:
            if int(p.get("id") or 0) > int(point_id) and not p.get("undone"):
                p["undone"] = True
                n += 1
        if n:
            self._flush()
        return n

    def newest_alive(self) -> dict | None:
        """最近一个尚未被撤回的还原点（它的「操作后」状态就是当前状态）。"""
        alive = [p for p in (self._state.get("points") or []) if not p.get("undone")]
        if not alive:
            return None
        return max(alive, key=lambda p: int(p.get("id") or 0))

    def newest_undoable(self) -> dict | None:
        """最近一个还能撤回的还原点（撤回 = 写回它的「操作前」字节）。"""
        for p in sorted(self._state.get("points") or [],
                        key=lambda x: int(x.get("id") or 0), reverse=True):
            if p.get("undone"):
                continue
            if self.before_bytes(int(p["id"])) is None:
                continue
            return p
        return None

    def points(self, *, limit: int | None = None) -> list[dict]:
        """还原点列表（最新在前），只给界面需要的字段，不含任何路径。"""
        alive_head = self.newest_alive()
        head_id = int(alive_head["id"]) if alive_head else 0
        rows: list[dict] = []
        for p in self._state.get("points") or []:
            pid = int(p.get("id") or 0)
            rows.append(dict(
                id=pid,
                label=p.get("label", ""),
                act=p.get("act", ""),
                at=p.get("at", ""),
                time=str(p.get("at", ""))[11:19],
                epoch=p.get("epoch", 0),
                sha_before=p.get("sha_before", ""),
                sha_after=p.get("sha_after", ""),
                undone=bool(p.get("undone")),
                is_current=bool(pid == head_id),
                restorable=bool(self.after_bytes(pid) is not None),
                touches_builtin=bool(p.get("builtin_before") or p.get("builtin_after_factory")),
                builtin_sha_before=p.get("builtin_sha_before", ""),
                builtin_sha_after=p.get("builtin_sha_after", ""),
                touches_words=bool(p.get("words_before") or p.get("words_after")),
            ))
        rows.sort(key=lambda r: r["id"], reverse=True)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def point_count(self) -> int:
        return len(self._state.get("points") or [])

    # ------------------------------------------------------------------ 操作历史

    def log_op(self, *, act: str, summary: str, point_id: int | None = None,
               sha_before: str = "", sha_after: str = "",
               builtin_sha_before: str = "", builtin_sha_after: str = "",
               detail: dict | None = None) -> dict:
        at, epoch = _now()
        ops = self._state.setdefault("ops", [])
        op = {
            "id": len(ops) + 1,
            "act": str(act),
            "summary": str(summary)[:160],
            "at": at,
            "epoch": epoch,
            "point_id": point_id,
            "sha_before": sha_before,
            "sha_after": sha_after,
            "builtin_sha_before": builtin_sha_before,
            "builtin_sha_after": builtin_sha_after,
        }
        if detail:
            op["detail"] = detail
        ops.append(op)
        if len(ops) > self.max_ops:
            del ops[: len(ops) - self.max_ops]
        self._flush()
        return dict(op)

    def ops(self, *, limit: int | None = None) -> list[dict]:
        """操作历史（最新在前）。"""
        rows = [dict(o) for o in (self._state.get("ops") or [])]
        rows.reverse()
        if limit is not None:
            rows = rows[:limit]
        return rows

    def op_count(self) -> int:
        return len(self._state.get("ops") or [])

    # ------------------------------------------------------------------ 清理

    def _prune(self) -> None:
        pts: list[dict] = self._state.get("points") or []
        if len(pts) <= self.max_points:
            self._prune_builtin_blobs(pts)
            return
        drop = pts[: len(pts) - self.max_points]
        self._state["points"] = pts[len(pts) - self.max_points:]
        for p in drop:
            for name in (p.get("before_payload"), p.get("after_payload"),
                         (p.get("builtin_before") or {}).get("payload")):
                if not name:
                    continue
                try:
                    (self.dir / name).unlink()
                except OSError:
                    pass
        self._prune_builtin_blobs(self._state["points"])

    def _prune_builtin_blobs(self, pts: list[dict]) -> None:
        """内置词库大块数据只留最新几份，旧的删文件但保留还原点行（会标为不可还原）。"""
        with_blob = [p for p in pts if (p.get("builtin_before") or {}).get("payload")]
        with_blob.sort(key=lambda p: int(p.get("id") or 0), reverse=True)
        for p in with_blob[MAX_BUILTIN_BLOBS:]:
            blob = p["builtin_before"]
            try:
                (self.dir / blob["payload"]).unlink()
            except OSError:
                pass
            blob["pruned"] = True
