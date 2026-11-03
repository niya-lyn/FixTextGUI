"""词条启用 / 禁用：数据层与用户区可写文件（V1.1-T1.1）。

设计要点（排期 7.4 定稿，本模块是数据层，不做界面）：

* **禁用集单独存一个文件**：用户区 ``workspace/vocab/word_states.json``，
  与 ``custom_vocab.json`` 同一棵树；出厂词库 ``data/rules/`` 与出厂迁入数据
  ``data/word_states/builtin_states.json`` 全程只读。
* **禁用键用词条内容的哈希值定位**（``sha256(word + NUL + value)``），
  不依赖行号或顺序——内置词库恢复默认、文件重排都不会让禁用状态错位。
* 「恢复默认」与「清空禁用」是**两个独立操作**（界面第二卡接）：
  ``reset_to_default`` 把禁用集恢复成初始集（迁入词条 + 孤儿词条默认禁用）；
  ``clear_disabled`` 把禁用集清空（所有词条全部启用，包括迁入与孤儿词条）。
* 写操作本身不落还原点——还原点 / 撤销栈由 ``VocabStore``（fixtext_vocab）
  经 ``_run`` 骨架统一管理，本模块只提供 ``raw_bytes`` / ``restore`` 供其
  留存与写回「操作前 / 后」字节。

与管线侧 :mod:`fixtext_pipeline.word_states` 是同一契约的两份自包含实现
（``entry_key``、文件格式、默认路径必须逐字节一致），
``tests/test_word_states.py`` 的契约用例锁住这一点。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
try:
    from fixtext_paths import pkg_root as _pkg_root

    PKG_ROOT = _pkg_root()
except Exception:                     # pragma: no cover
    PKG_ROOT = HERE.parent

#: 出厂迁入数据（只读）：初始禁用集 = 迁入词条 + 孤儿词条
BUILTIN_STATES_PATH = PKG_ROOT / "data" / "word_states" / "builtin_states.json"
#: 用户区默认落点（与 custom_vocab.json 同一棵树）
CUSTOM_DIR = PKG_ROOT / "workspace" / "vocab"
STATES_FILE_NAME = "word_states.json"

#: 词条键分隔符（与管线侧契约一致，禁止单方面修改）
ENTRY_KEY_SEP = "\x00"
STATES_VERSION = 1


def entry_key(word: str, value: str) -> str:
    """词条内容键：``sha256(word + NUL + value)`` 的十六进制。

    用内容而不是行号 / 顺序定位，是禁用集能扛住「词库恢复默认、文件重排」
    的前提：只要词条内容不变，键就不变；内容变了，禁用状态自然不跟随。
    """
    raw = (str(word) + ENTRY_KEY_SEP + str(value)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".states-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _canonical(keys: Iterable[str]) -> bytes:
    obj = {"version": STATES_VERSION, "disabled": sorted(set(keys))}
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _normalize_pairs(pairs: Iterable) -> list[tuple[str, str]]:
    """把 (word, value) 元组或 {'word':..,'value':..} 字典统一成元组列表。"""
    out: list[tuple[str, str]] = []
    for p in pairs or []:
        if isinstance(p, dict):
            w, v = str(p.get("word", "")), str(p.get("value", ""))
        else:
            w, v = str(p[0]), str(p[1])
        out.append((w, v))
    return out


class WordStateStore:
    """词条启用 / 禁用的数据层门面（不依赖 Qt，可单测）。

    出厂侧（只读）：迁入词条清单 ``imported_entries``、孤儿词条 ``orphan_entries``、
    初始禁用集 ``initial_disabled_keys``。
    用户侧（可写文件 ``word_states.json``）：有效禁用集 ``effective_disabled``、
    读写 ``set_enabled`` / ``clear_disabled`` / ``reset_to_default``，以及供撤销栈
    用的 ``raw_bytes`` / ``restore``。
    """

    def __init__(self, *, builtin_path: Path | str | None = None,
                 writable_path: Path | str | None = None):
        self.builtin_path = Path(builtin_path) if builtin_path else BUILTIN_STATES_PATH
        self.path = Path(writable_path) if writable_path else CUSTOM_DIR / STATES_FILE_NAME
        self.error = ""
        self._builtin: dict | None = None

    # ------------------------------------------------------------------ 出厂侧

    @property
    def builtin(self) -> dict:
        """出厂迁入数据（缓存）。损坏 / 缺失时为空 dict，并记 ``error``。"""
        if self._builtin is None:
            try:
                self._builtin = json.loads(
                    self.builtin_path.read_bytes().decode("utf-8"))
                if not isinstance(self._builtin, dict):
                    self._builtin = {}
                    self.error = "迁入数据格式不正确"
            except (OSError, UnicodeDecodeError, ValueError):
                self._builtin = {}
                self.error = "迁入数据文件缺失或损坏"
        return self._builtin

    def imported_entries(self) -> list[dict]:
        """迁入词条清单：``word`` / ``value`` / ``src`` / ``line``（只读）。"""
        arr = self.builtin.get("entries") or []
        return [dict(e) for e in arr if isinstance(e, dict) and e.get("word")]

    def orphan_entries(self) -> list[dict]:
        """孤儿词条清单（误迁为在用的注释词，默认禁用）。"""
        arr = self.builtin.get("orphans") or []
        return [dict(e) for e in arr if isinstance(e, dict) and e.get("word")]

    def initial_disabled_keys(self) -> frozenset[str]:
        keys = {entry_key(e["word"], e.get("value", ""))
                for e in self.imported_entries()}
        keys.update(entry_key(o["word"], o.get("value", ""))
                    for o in self.orphan_entries())
        return frozenset(keys)

    # ------------------------------------------------------------------ 用户侧

    def _file_disabled(self) -> set[str] | None:
        """读用户区文件；``None`` = 文件不存在或不可解析（回落初始集）。"""
        try:
            raw = self.path.read_bytes()
            obj = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        if not isinstance(obj, dict):
            return None
        disabled = obj.get("disabled")
        if not isinstance(disabled, list) or any(not isinstance(k, str) for k in disabled):
            return None
        return set(disabled)

    def effective_disabled(self) -> frozenset[str]:
        """有效禁用集：用户区文件优先，缺失 / 损坏回落初始集（保守）。"""
        keys = self._file_disabled()
        if keys is None:
            return self.initial_disabled_keys()
        return frozenset(keys)

    def is_disabled(self, word: str, value: str) -> bool:
        return entry_key(word, value) in self.effective_disabled()

    def disabled_count(self) -> int:
        return len(self.effective_disabled())

    def sha(self) -> str:
        """有效禁用集的内容指纹（与管线侧 ``effective_disabled_sha`` 同值）。"""
        return hashlib.sha256(_canonical(self.effective_disabled())).hexdigest()

    # ---- 写操作（还原点由 VocabStore._run 统一管理，这里只写文件）----

    def _write_keys(self, keys: Iterable[str]) -> None:
        _atomic_write(self.path, _canonical(keys))

    def set_enabled(self, pairs: Iterable, *, enabled: bool) -> dict:
        """批量启用 / 禁用词条。返回 ``changed`` / ``unchanged`` 计数与操作后禁用总数。"""
        keys = set(self.effective_disabled())
        changed = 0
        unchanged = 0
        for w, v in _normalize_pairs(pairs):
            k = entry_key(w, v)
            if enabled:
                if k in keys:
                    keys.discard(k)
                    changed += 1
                else:
                    unchanged += 1
            else:
                if k not in keys:
                    keys.add(k)
                    changed += 1
                else:
                    unchanged += 1
        self._write_keys(keys)
        return dict(changed=changed, unchanged=unchanged,
                    disabled_total=len(keys))

    def clear_disabled(self) -> dict:
        """「清空禁用」：禁用集置空——所有词条（含迁入 / 孤儿）全部启用。"""
        self._write_keys(set())
        return dict(disabled_total=0)

    def reset_to_default(self) -> dict:
        """「恢复默认」：禁用集恢复初始集（迁入 + 孤儿词条默认禁用，其余启用）。"""
        keys = set(self.initial_disabled_keys())
        self._write_keys(keys)
        return dict(disabled_total=len(keys))

    # ------------------------------------------------------------------ 撤销栈接口

    def raw_bytes(self) -> bytes:
        """当前用户区文件的原始字节；文件不存在返回 ``b""``。"""
        try:
            return self.path.read_bytes()
        except OSError:
            return b""

    def restore(self, raw: bytes) -> None:
        """把 ``raw_bytes`` 留存的字节原样写回（空字节 = 删除文件回到「未写过」）。"""
        if not raw:
            try:
                self.path.unlink()
            except OSError:
                pass
            return
        _atomic_write(self.path, raw)

    # ------------------------------------------------------------------ 汇总

    def summary(self) -> dict:
        """给界面 / 报告用的只读汇总。"""
        effective = self.effective_disabled()
        initial = self.initial_disabled_keys()
        imported = self.imported_entries()
        return dict(
            imported_total=len(imported),
            orphan_total=len(self.orphan_entries()),
            initial_disabled=len(initial),
            disabled_total=len(effective),
            imported_disabled=sum(
                1 for e in imported if entry_key(e["word"], e.get("value", "")) in effective),
            has_user_file=self.path.is_file(),
            sha=self.sha(),
        )
