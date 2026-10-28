# -*- coding: utf-8 -*-
"""probe_atomic_write —— 证明 _atomic_write 在 Windows 上不再因「目录 fsync」崩溃。

背景（M3-EX.1c）
----------------
`fixtext_ui/fixtext_vocab.py` 与 `fixtext_ui/fixtext_snapshot.py` 各有一份
`_atomic_write()`，流程是「临时文件 → os.replace → 打开目录 fsync」。最后
这一步是类 Unix 专有写法：Windows 不允许把目录当文件打开，`os.open(目录)`
直接抛 `PermissionError`。而它写在 `finally` 之外（finally 只清理临时文件），
所以 `os.replace` 已经把数据写成功了，函数却仍抛异常 → 上层把「已写入」
报成「失败」。后果：词库新增/合并/删除/恢复默认、以及快照的撤销/重做，
在 Windows 上全部不可用。

做法
----
不全局改 `os.name`（那会让 pathlib 改用 WindowsPath，把 `/tmp/x` 拼成
`\\tmp\\x`，探针自己先崩——这是探针缺陷，不是被测代码缺陷）。改为**只替换
被测模块看到的 `os`**：name 报 "nt"，且 os.open(目录) 抛 PermissionError，
其余行为委托真实 os。

判据
----
A  nt 模式下词库写入应成功且内容正确（修复前必然抛 PermissionError）
A2 nt 模式下应**零次**尝试打开目录（证明是主动跳过，不是碰巧没走到）
B  nt 模式下快照写入应成功
C  posix 模式下目录 fsync 仍执行一次（证明修复没有把 Unix 的可靠性一起删掉）

运行：python3.12 tools/probe_atomic_write.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for p in (str(PKG), str(PKG / "pipeline"), str(PKG / "fixtext_ui")):
    if p not in sys.path:
        sys.path.insert(0, p)

from fixtext_ui import fixtext_snapshot as snap_mod  # noqa: E402
from fixtext_ui import fixtext_vocab as vocab_mod  # noqa: E402

_fails: list[str] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ← {detail}" if detail else ""))
    if not ok:
        _fails.append(name)


class _NtOsShim:
    """冒充 Windows 的 os：name='nt'，且打开目录必抛 PermissionError。"""

    def __init__(self) -> None:
        import os as _real
        self._real = _real
        self.dir_open_attempts = 0
        self.dir_fsync_calls = 0

    def __getattr__(self, name):          # 其余全部委托真实 os
        return getattr(self._real, name)

    @property
    def name(self) -> str:                # 关键：让被测代码以为自己在 Windows
        return "nt"

    def open(self, path, flags, *a, **kw):
        if self._real.path.isdir(str(path)):
            self.dir_open_attempts += 1   # 记一次「试图打开目录」
            raise PermissionError(13, "Permission denied", str(path))
        return self._real.open(path, flags, *a, **kw)

    def fsync(self, fd):
        self.dir_fsync_calls += 1
        return self._real.fsync(fd)


class _PosixOsShim:
    """对照组：仍是 posix，但按 fd 区分「目录 fsync」与「文件 fsync」。"""

    def __init__(self) -> None:
        import os as _real
        self._real = _real
        self.opened_dirs = 0
        self.dir_fsync_calls = 0
        self.file_fsync_calls = 0
        self._dir_fds: set[int] = set()

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def name(self) -> str:
        return "posix"

    def open(self, path, flags, *a, **kw):
        fd = self._real.open(path, flags, *a, **kw)
        try:
            if self._real.fstat(fd).st_mode & 0o040000:   # S_IFDIR
                self.opened_dirs += 1
                self._dir_fds.add(fd)
        except OSError:
            pass
        return fd

    def fsync(self, fd):
        if fd in self._dir_fds:
            self.dir_fsync_calls += 1
        else:
            self.file_fsync_calls += 1
        return self._real.fsync(fd)

    def close(self, fd):
        self._dir_fds.discard(fd)
        return self._real.close(fd)


def _run(module, shim, fn):
    """把 module.os 换成 shim，跑完还原。返回 (异常 or None, shim)。"""
    real_os = module.os
    module.os = shim
    exc = None
    try:
        fn()
    except BaseException as e:            # noqa: BLE001 — 要连 PermissionError 一起接住
        exc = e
    finally:
        module.os = real_os
    return exc, shim


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="probe_atomic_"))
    print(f"临时目录: {tmp}\n")

    # ---- A / A2：词库写入（nt 模式） ----
    vocab_path = tmp / "vocab_nt" / "custom_vocab.json"
    holder: dict = {}

    def _vocab_case():
        v = vocab_mod.CustomVocab(vocab_path)
        holder["vocab"] = v
        holder["added"] = v.add(word="加布里", value="加布里埃尔", typ="人名")
        holder["entries_before"] = len(v.entries())
        v.add(word="萧衍", value="萧衍之", typ="人名")
        holder["entries_after"] = len(v.entries())
        holder["snap"] = v.snapshot()
        holder["error"] = getattr(v, "error", "")

    exc, shim = _run(vocab_mod, _NtOsShim(), _vocab_case)
    check(exc is None and not holder.get("error"),
          "A nt 模式写词库成功且未记错误",
          "无异常" if exc is None else f"抛异常 {type(exc).__name__}: {exc}")
    if exc is not None:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
    check(getattr(shim, "dir_open_attempts", -1) == 0,
          "A2 nt 模式下未尝试打开目录",
          f"尝试={getattr(shim, 'dir_open_attempts', '?')}")
    if exc is None:
        data = json.loads(vocab_path.read_text(encoding="utf-8"))
        words = [e["word"] for e in data.get("entries") or []]
        check(words == ["加布里", "萧衍"], "A3 落盘内容正确",
              f"entries={words}")
        mem = [e["word"] for e in holder["vocab"].entries()]
        check(mem == words, "A4 内存与磁盘一致（不会「写进去了但界面还显示旧的」）",
              f"内存={mem} 磁盘={words}")

    # ---- B：快照写入（nt 模式） ----
    snap_dir = tmp / "snap_nt"
    payload = b'{"entries": [{"id": 1, "word": "x", "value": "y"}]}'
    got: dict = {}

    def _snap_case():
        store = snap_mod.SnapshotStore(snap_dir)
        pid = store.begin(label="新增「萧衍」", act="add", before_bytes=payload)
        got["pid"] = pid
        got["commit"] = store.commit(pid, after_bytes=payload)
        got["count"] = store.point_count()
        got["before"] = store.before_bytes(pid)
        got["after"] = store.after_bytes(pid)
        got["error"] = getattr(store, "error", "")

    exc_b, shim_b = _run(snap_mod, _NtOsShim(), _snap_case)
    check(exc_b is None and not got.get("error"),
          "B nt 模式写快照（还原点）成功且未记错误",
          f"异常={exc_b!r} error={got.get('error')!r}")
    if exc_b is not None:
        traceback.print_exception(type(exc_b), exc_b, exc_b.__traceback__)
    check(getattr(shim_b, "dir_open_attempts", -1) == 0,
          "B2 nt 模式下未尝试打开目录",
          f"尝试={getattr(shim_b, 'dir_open_attempts', '?')}")
    if exc_b is None:
        check(got.get("count", 0) >= 1, "B3 还原点已写入", f"count={got.get('count')}")
        check(got.get("before") == payload and got.get("after") == payload,
              "B4 往返字节一致（撤回/恢复拿得到原字节）",
              f"before_ok={got.get('before') == payload} after_ok={got.get('after') == payload}")

    # ---- C：posix 模式仍做目录 fsync（防「顺手把 Unix 可靠性删了」） ----
    vocab_posix = tmp / "vocab_posix" / "custom_vocab.json"

    def _posix_case():
        v = vocab_mod.CustomVocab(vocab_posix)
        v.add(word="王忠", value="王忠实", typ="人名")

    exc_c, shim_c = _run(vocab_mod, _PosixOsShim(), _posix_case)
    check(exc_c is None and shim_c.dir_fsync_calls >= 1,
          "C posix 模式仍执行目录 fsync（Unix 可靠性未被顺手删掉）",
          f"异常={exc_c!r} 目录fsync={shim_c.dir_fsync_calls} 文件fsync={shim_c.file_fsync_calls}")

    print()
    if _fails:
        print(f"PROBE_ATOMIC_WRITE: FAIL ({len(_fails)}/{len(_fails) + 0} 项未过) -> {_fails}")
        return 1
    print("PROBE_ATOMIC_WRITE: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
