# -*- coding: utf-8 -*-
"""Windows 下原子写回归测试（M3-EX.1c）。

被测缺陷：`fixtext_vocab.py` 与 `fixtext_snapshot.py` 的 `_atomic_write`
在 `os.replace` 之后无条件打开目录 fsync。Windows 不允许把目录当文件打开，
`os.open(目录)` 抛 `PermissionError`；该语句在 `finally` 之外，于是已经成功
的写入被报成失败。

两处**失败表现不同**，测试按各自真实契约断言：
- 词库（`CustomVocab`）：异常直接向上抛出 → 用户看到「新增失败」，但文件其
  实已经写进去了；内存停在旧状态，下一次写入会以旧状态为基，**覆盖掉上一次
  的内容**（实测：加「萧衍」再加「王忠」，磁盘上只剩「王忠」）。
- 快照（`SnapshotStore`）：异常被 `_flush` / `_write_raw` 吞掉并记进
  `self.error` → 数据不丢，但 `VocabStore.warning()` 把它当告警显示在词库页
  顶部，用户会看到「还原点索引写入失败」。

跑法：QT_QPA_PLATFORM=offscreen python3.12 -m pytest tests/test_atomic_write_win.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (str(PKG), str(PKG / "pipeline"), str(PKG / "fixtext_ui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fixtext_ui import fixtext_snapshot as snap_mod  # noqa: E402
from fixtext_ui import fixtext_vocab as vocab_mod  # noqa: E402


class _NtOsShim:
    """冒充 Windows 的 os：name='nt'，打开目录必抛 PermissionError。"""

    def __init__(self) -> None:
        self._real = os
        self.dir_open_attempts = 0

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def name(self) -> str:
        return "nt"

    def open(self, path, flags, *a, **kw):
        if self._real.path.isdir(str(path)):
            self.dir_open_attempts += 1
            raise PermissionError(13, "Permission denied", str(path))
        return self._real.open(path, flags, *a, **kw)


class _NtCtx:
    """with nt(模块): … —— 只替换该模块看到的 os，不污染全局（pathlib 仍走真实 os）。"""

    def __init__(self, *modules):
        self.modules = modules

    def __enter__(self):
        self.shims = {}
        for m in self.modules:
            shim = _NtOsShim()
            self.shims[m.__name__] = (m, m.os)
            m.os = shim
        return self.shims

    def __exit__(self, *exc):
        for m, real in self.shims.values():
            m.os = real
        return False


@pytest.fixture()
def nt():
    return _NtCtx


# ---------------------------------------------------------------- 词库 ——

def test_vocab_write_succeeds_on_windows_without_real_dir_fsync(nt, tmp_path):
    """Windows 上新增词条应成功，且根本不尝试打开目录。"""
    path = tmp_path / "vocab" / "custom_vocab.json"
    with nt(vocab_mod) as shims:
        cat = vocab_mod.CustomVocab(path)
        cat.add(word="萧衍", value="萧衍之", typ="人名")
        assert cat.error == "", f"不应记下创建错误：{cat.error}"
        shim = shims[vocab_mod.__name__][0].os
        assert shim.dir_open_attempts == 0, (
            f"Windows 上不应尝试打开目录，实际尝试 {shim.dir_open_attempts} 次")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert [e["word"] for e in data["entries"]] == ["萧衍"]
    assert [e["word"] for e in cat.entries()] == ["萧衍"], "内存与磁盘必须一致"


def test_consecutive_vocab_writes_do_not_lose_earlier_entries(nt, tmp_path):
    """连续两次写入不能丢前一次——这是 Windows 上最致命的那一环。"""
    path = tmp_path / "vocab" / "custom_vocab.json"
    with nt(vocab_mod):
        cat = vocab_mod.CustomVocab(path)
        cat.add(word="萧衍", value="萧衍之", typ="人名")
        cat.add(word="王忠", value="王忠实", typ="人名")

    words = [e["word"] for e in json.loads(path.read_text(encoding="utf-8"))["entries"]]
    assert words == ["萧衍", "王忠"], f"两次写入应都在磁盘上，实际={words}"


def test_vocab_restore_and_delete_work_on_windows(nt, tmp_path):
    """撤销（restore 整份回写）与删除也走同一函数，必须一起可用。"""
    path = tmp_path / "vocab" / "custom_vocab.json"
    with nt(vocab_mod):
        cat = vocab_mod.CustomVocab(path)
        cat.add(word="萧衍", value="萧衍之", typ="人名")
        snap = cat.snapshot()
        cat.add(word="王忠", value="王忠实", typ="人名")
        cat.restore(snap)
        assert [e["word"] for e in cat.entries()] == ["萧衍"], "撤销应回到只有「萧衍」"
        rid = cat.entries()[0]["id"]
        cat.delete([rid])

    assert json.loads(path.read_text(encoding="utf-8"))["entries"] == []


# ---------------------------------------------------------------- 快照 ——

def test_snapshot_index_write_does_not_report_error_on_windows(nt, tmp_path):
    """Windows 上写还原点不应记下任何写入错误（否则词库页顶会挂告警）。"""
    with nt(snap_mod):
        store = snap_mod.SnapshotStore(tmp_path / "snaps")
        pid = store.begin(label="新增「萧衍」", act="add", before_bytes=b'{"v":1}')
        store.commit(pid, after_bytes=b'{"v":2}')
        assert store.error == "", f"不应记下还原点写入错误：{store.error}"

    assert store.point_count() == 1
    assert store.before_bytes(pid) == b'{"v":1}'
    assert store.after_bytes(pid) == b'{"v":2}'


def test_snapshot_survives_restart_on_windows(nt, tmp_path):
    """还原点必须在重启后仍在（索引真落盘），而不是只活在本进程内存里。"""
    snap_dir = tmp_path / "snaps"
    with nt(snap_mod):
        store = snap_mod.SnapshotStore(snap_dir)
        pid = store.begin(label="新增「萧衍」", act="add", before_bytes=b'{"v":1}')
        store.commit(pid, after_bytes=b'{"v":2}')

    reopened = snap_mod.SnapshotStore(snap_dir)      # 等价于新进程
    assert reopened.point_count() == 1, "重启后还原点应仍在"
    assert reopened.before_bytes(1) == b'{"v":1}'
    assert (snap_dir / "index.json").exists(), "索引文件必须真实存在"


# ------------------------------------------------- Posix 未被削弱（反向对照） -

def test_posix_still_fsyncs_directory(tmp_path):
    """修复只跳过 Windows；类 Unix 的目录 fsync 必须照旧执行。"""
    target = tmp_path / "vocab" / "custom_vocab.json"
    seen: list[int] = []
    real_fsync = os.fsync

    def spy(fd):
        try:
            if os.fstat(fd).st_mode & 0o040000:     # S_IFDIR
                seen.append(fd)
        except OSError:
            pass
        return real_fsync(fd)

    cat_holder: dict = {}
    vocab_mod_os = vocab_mod.os
    vocab_mod.os = type("P", (), dict(vocab_mod_os.__dict__) | {"fsync": staticmethod(spy)})
    try:
        cat_holder["cat"] = vocab_mod.CustomVocab(target)
        cat_holder["cat"].add(word="王忠", value="王忠实", typ="人名")
    finally:
        vocab_mod.os = vocab_mod_os

    assert seen, "posix 下应执行过目录 fsync——修复不能把 Unix 的可靠性一起删掉"
