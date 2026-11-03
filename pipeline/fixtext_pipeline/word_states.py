"""词条启用 / 禁用：管线侧只读视图（V1.1-T1.1 · T1.3 增补）。

设计要点（排期 7.4 定稿）：

* **禁用集单独存一个文件**，与出厂词库 ``data/rules/`` 完全分离——出厂词库
  只读的底线不动。可写文件在用户区 ``workspace/vocab/word_states.json``，
  与 ``custom_vocab.json`` 同一棵树。
* **禁用键用词条内容的哈希值定位**（``sha256(word + "\\x00" + value)``），
  不依赖行号或顺序——词库文件重排、恢复默认都不会让禁用状态错位。
* 管线侧**只读**：``effective_disabled_sha`` 进替换阶段指纹（断点恢复判据），
  保证「改了禁用状态但指纹不变 → 复用旧正文」不可能发生。
* **T1.3 起，禁用集真正作用于校正结果**：规则合成时（``vocab_bridge.compose``）
  按内容键剔除禁用词条，出厂侧与自定义侧一视同仁；指纹除禁用集内容外
  还纳入「实际下发的规则字节」（见 :mod:`vocab_bridge` 的 ``ruleset_sha``）。

本模块与上层 :mod:`fixtext_ui.fixtext_word_states` 是两棵自包含子树各自实现的
同一份契约（与 ``vocab_bridge`` / ``fixtext_vocab`` 的既有分层一致）：
``tests/test_word_states.py`` 里有契约一致性用例锁住两边 ``entry_key`` 与
默认路径必须逐字节相同。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from ._roots import pkg_root
from .rule_keys import ENTRY_KEY_SEP, entry_key
from .vocab_bridge import _ui_workspace

#: 禁用集可写文件名（落在用户区 ``workspace/vocab/`` 下）
STATES_FILE_NAME = "word_states.json"

#: 内置迁入数据（出厂只读）：PHP 注释词条 + 孤儿词条的初始禁用集来源
BUILTIN_STATES_REL = Path("data") / "word_states" / "builtin_states.json"

STATES_VERSION = 1

#: ``ENTRY_KEY_SEP`` / ``entry_key`` 从 :mod:`rule_keys` 直接再导出——
#: 键的算法只有一份，UI 侧与管线侧的契约用例锁的是这两个名字。


def builtin_states_path() -> Path:
    """出厂迁入数据位置（包根 ``data/word_states/builtin_states.json``）。"""
    return pkg_root() / BUILTIN_STATES_REL


def default_states_path() -> Path:
    """禁用集可写文件的默认位置（用户区 ``workspace/vocab/``，唯一一份）。"""
    return _ui_workspace() / "vocab" / STATES_FILE_NAME


# ---------------------------------------------------------------------------
# 出厂迁入数据（只读）
# ---------------------------------------------------------------------------

_builtin_cache: dict[Path, dict] = {}


def load_builtin_states(path: Path | str | None = None) -> dict:
    """读出厂迁入数据；损坏 / 缺失返回空 dict（不冒充、不抛）。"""
    p = Path(path) if path else builtin_states_path()
    if p in _builtin_cache:
        return _builtin_cache[p]
    data: dict = {}
    try:
        raw = p.read_bytes()
        obj = json.loads(raw.decode("utf-8"))
        if isinstance(obj, dict):
            data = obj
    except (OSError, UnicodeDecodeError, ValueError):
        data = {}
    _builtin_cache[p] = data
    return data


def initial_disabled_keys(path: Path | str | None = None) -> frozenset[str]:
    """初始禁用集 = 全部迁入词条 + 孤儿词条的内容键。

    迁入词条按口径本身就是「默认禁用、可见、可自行启用」；孤儿词条
    （PHP 注释态误迁为在用）也默认禁用。
    """
    data = load_builtin_states(path)
    keys = {
        entry_key(e.get("word", ""), e.get("value", ""))
        for e in data.get("entries") or []
        if isinstance(e, dict) and e.get("word")
    }
    keys.update(
        entry_key(o.get("word", ""), o.get("value", ""))
        for o in data.get("orphans") or []
        if isinstance(o, dict) and o.get("word")
    )
    return frozenset(keys)


# ---------------------------------------------------------------------------
# 禁用集（用户区可写文件）的读取与指纹
# ---------------------------------------------------------------------------

def canonical_bytes(keys: Iterable[str]) -> bytes:
    """禁用集的规范序列化（键排序 + 紧凑 JSON + 换行）——指纹就是它的 sha256。"""
    obj = {"version": STATES_VERSION, "disabled": sorted(set(keys))}
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"


def read_states_disabled(states_path: Path | str | None) -> set[str] | None:
    """读用户区禁用集文件的 ``disabled`` 键列表。

    返回 ``None`` 表示「文件不存在或不可解析」——此时有效禁用集回落到初始集
    （保守：不让一次坏文件把全部禁用词条悄悄启用）。解析成功返回键集合。
    """
    p = Path(states_path) if states_path else default_states_path()
    try:
        raw = p.read_bytes()
        obj = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    disabled = obj.get("disabled")
    if not isinstance(disabled, list) or any(not isinstance(k, str) for k in disabled):
        return None
    return set(disabled)


def effective_disabled(states_path: Path | str | None = None,
                       builtin_path: Path | str | None = None) -> frozenset[str]:
    """有效禁用集：用户区文件优先，缺失 / 损坏回落初始集。"""
    keys = read_states_disabled(states_path)
    if keys is None:
        return initial_disabled_keys(builtin_path)
    return frozenset(keys)


def effective_disabled_sha(states_path: Path | str | None = None,
                           builtin_path: Path | str | None = None) -> str:
    """有效禁用集的内容指纹（进替换阶段指纹，断点恢复判据）。"""
    return hashlib.sha256(canonical_bytes(effective_disabled(states_path, builtin_path))).hexdigest()
