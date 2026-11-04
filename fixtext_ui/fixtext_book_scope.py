"""V1.1-C2 · 按书词库的界面侧衔接（不依赖 Qt）。

排期 8.3 的第 1 条交付物是界面入口，但**按书层的读写一律不得另造路径**：
C1 已经把「一本书一份、只承载排除项、规范字节」全部做在
``fixtext_pipeline.book_vocab`` 里。本模块只做三件事：

1. 把管线包挂进 ``sys.path`` 并按 C1 的同一套规则算出这本书的按书文件位置
   （``book_vocab.book_vocab_path``）——界面自己不拼路径；
2. 读：``book_vocab.load_book_vocab``；
3. 写：``book_vocab.write_book_vocab``（新增 / 移出都走它，传整份排除集）。

另外提供「按书文件的原始字节」读写，供撤销栈把按书层的改动和全局词库的改动
记进同一条还原点（还原时逐字节写回，sha 相同才算真的回去了）。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _pkg_root() -> Path:
    try:
        from fixtext_paths import pkg_root as _root

        return Path(_root())
    except Exception:                                   # pragma: no cover
        return _HERE.parent


def pipeline_book_vocab():
    """按 C1 的模块取按书数据层（懒加载：词库页首次用到时才挂管线包）。"""
    root = _pkg_root() / "pipeline"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from fixtext_pipeline import book_vocab as bv

    return bv


def workspace_root() -> Path:
    """用户区根目录（与管线侧同一棵：包根 ``workspace/``）。"""
    try:
        from fixtext_pipeline.vocab_bridge import _ui_workspace

        return Path(_ui_workspace())
    except Exception:                                   # pragma: no cover
        return _pkg_root() / "workspace"


def book_path(book_id: str) -> Path | None:
    """这本书的按书文件位置；书 id 不合规时返回 ``None``（不猜、不兜底）。"""
    bid = str(book_id or "").strip()
    if not bid:
        return None
    try:
        return Path(pipeline_book_vocab().book_vocab_path(bid, workspace=workspace_root()))
    except Exception:
        return None


def normalize_book_id(book_id: str) -> str:
    """校验 / 归一书 id（不合规直接抛出，由调用方给人话）。"""
    return str(pipeline_book_vocab().normalize_book_id(book_id))


def load(path: Path | str | None) -> dict:
    """读按书词库（C1 的 ``load_book_vocab``：坏文件降级不阻断）。"""
    if not path:
        return dict(configured=False, book_id="", path="", excluded_keys=frozenset(),
                    excluded=[], ignored=[], sha256="", error="", version=1)
    return pipeline_book_vocab().load_book_vocab(Path(path))


def excluded_pairs(info: dict) -> list[tuple[str, str]]:
    """把按书条目折成 ``(word, value)`` 清单，供「改一条再写回」用。"""
    out: list[tuple[str, str]] = []
    for e in info.get("excluded") or []:
        out.append((str(e.get("word") or ""), str(e.get("value") or "")))
    return out


def write_excluded(path: Path | str, book_id: str, pairs, *, reason: str = "") -> dict:
    """按 C1 数据层写整份排除集（规范字节：同一份清单永远同样的字节）。"""
    return pipeline_book_vocab().write_book_vocab(Path(path), book_id, pairs, reason=reason)


def key_of(word: str, value: str) -> str:
    """词条内容键（C1 与全局层同一个实现，不在这里重算算法）。"""
    return str(pipeline_book_vocab().entry_key(word, value))


def raw_bytes(path: Path | str | None) -> bytes:
    """按书文件当前原始字节；文件不存在时返回 ``b""``（撤销 = 删掉它）。"""
    if not path:
        return b""
    try:
        return Path(path).read_bytes()
    except OSError:
        return b""


def restore_bytes(path: Path | str | None, raw: bytes) -> None:
    """把按书文件写回 ``raw``；``raw`` 为空 = 操作前它还不存在 → 删掉。"""
    if not path:
        return
    p = Path(path)
    if not raw:
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".c2tmp")
    tmp.write_bytes(raw)
    tmp.replace(p)


def sha_of(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest() if raw else ""
