"""
FixText V1 · 词库真实数据层（M3-T3.1 / M3-T3.2）
================================================

本模块**不依赖 Qt**，只负责词库的读取、检索、查重与写入。界面层
（``vocab_module.py``）只通过这里的接口取数，不自己拼路径、不自己写文件。

分级存储（§2.4.1 底线⑤ · 自定义与内置物理分离）
------------------------------------------------
* **内置词库**：出厂状态是 ``data/rules/before.json`` + ``after.json`` 两份平行数组，
  每条规则占同一下标，所属分级由 ``builtin_tiers.bin``（每条 1 字节：
  ``1`` 常规校正 / ``2`` 标点规范 / ``3`` 繁简转换）给出，出处与校验值见
  ``builtin_index_meta.json``。出厂文件**永不改写**；程序运行时读的是可写工作副本
  ``<包根>/workspace/vocab/rules/``（首次需要时才由出厂文件复制而来），
  「恢复默认词库」就是把工作副本逐字节还原为出厂内容。
* **自定义词库（可写）**：独立的 ``<包根>/workspace/vocab/custom_vocab.json``，与内置词库
  既不在同一目录、也不是同一份文件；界面只显示友好名「我的词库」，不露路径。

写入安全
--------
* 写文件一律「临时文件 + fsync + os.replace + fsync 目录」，避免半截文件。
* 每次改动前把**原始字节**整份留在还原点里（落盘，见 ``fixtext_snapshot.py``）；
  还原时把原始字节原样写回，因此还原后的文件与改动前逐字节一致（sha256 相同，可自证）。
* 操作历史与还原点同盘持久化：换一个新进程仍然读得到，不是界面内存里的临时列表。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

from fixtext_snapshot import SnapshotStore

# ---------------------------------------------------------------------------
# 路径（仅本模块内部使用，界面层拿不到、也不展示）
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
RULES_DIR = PKG_ROOT / "data" / "rules"

BUILTIN_BEFORE = "before.json"
BUILTIN_AFTER = "after.json"
BUILTIN_TIERS = "builtin_tiers.bin"
BUILTIN_MARKS = "builtin_marks.json"
BUILTIN_META = "builtin_index_meta.json"
BUILTIN_FILES = (BUILTIN_BEFORE, BUILTIN_AFTER, BUILTIN_TIERS, BUILTIN_MARKS, BUILTIN_META)

#: 用户区目录（与内置词库 ``data/rules/`` 完全不同的一棵子树）。
#: M4-T4.4：用户区统一在**包根** ``workspace/`` 下，不再落在代码目录
#: ``fixtext_ui/workspace/``——代码目录只放程序，用户数据跟着包根走。
CUSTOM_DIR = PKG_ROOT / "workspace" / "vocab"
CUSTOM_FILE = "custom_vocab.json"
#: 内置词库的可写工作副本（只在「恢复默认」等需要改写时才用）
WORK_RULES_DIR = "rules"
#: 还原点与操作历史
SNAP_DIR = "snapshots"

#: 分级代号 → 友好名（内置三级 + 自定义）
TIER_NAMES = {
    "custom": "我的词库",
    "b1": "常规校正词库",
    "b2": "标点规范词库",
    "b3": "繁简转换词库",
}
BUILTIN_TIER_CODE = {"1": "b1", "2": "b2", "3": "b3"}
TIER_ORDER = ["custom", "b1", "b2", "b3"]

#: 词条类型（新增时可选；内置词条的类型取自分级名）
ENTRY_TYPES = ["错词校正", "角色名", "专有名词", "其他"]

#: 命中 / 冲突的三种形态（文案直接取自排期 §2.4.1 的查重口径）
KIND_SAME_BOTH = "同词同值"
KIND_SAME_WORD = "同词异值"
KIND_SAME_VALUE = "同值异词"

#: 变更动作代号（操作历史与还原点都记这个，界面自己翻译成人话）
ACT_ADD = "add"
ACT_EDIT = "edit"
ACT_DELETE = "delete"
ACT_MERGE = "merge"
ACT_BOOK = "book"
ACT_RESTORE_DEFAULT = "restore_default"
ACT_RESTORE_POINT = "restore_point"
ACT_UNDO = "undo"

#: 动作代号 → 人话（操作历史面板直接用这个，不把代号给用户看）
ACT_NAMES = {
    ACT_ADD: "新增",
    ACT_EDIT: "编辑",
    ACT_DELETE: "删除",
    ACT_MERGE: "合并",
    ACT_BOOK: "加入专有词",
    ACT_RESTORE_DEFAULT: "恢复默认",
    ACT_RESTORE_POINT: "恢复到时间点",
    ACT_UNDO: "撤销",
    "note": "标记",
}


class VocabDataError(RuntimeError):
    """真实词库不可用时的内部异常（界面层转成人话提示，不直接抛给用户）。"""


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _dump_canonical(obj: Any) -> bytes:
    """稳定序列化：同样的内容永远得到同样的字节（撤销才能逐字节比对）。"""
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    return (text + "\n").encode("utf-8")


def _atomic_write(path: Path, raw: bytes) -> None:
    """原子写：临时文件同目录 → fsync → replace → fsync 目录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".vocab-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
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


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------------
# 内置词库（出厂只读 + 可写工作副本）
# ---------------------------------------------------------------------------

class BuiltinVocab:
    """内置词库：两份平行数组 + 每条的 1 字节分级码。

    出厂文件（``data/rules/``）只读、永不改写；若 ``work_dir`` 下存在一份完整的
    工作副本，则优先读它——这样「恢复默认词库」才有真实可写、可还原的对象。
    """

    def __init__(self, rules_dir: Path | str | None = None,
                 work_dir: Path | str | None = None):
        self.dir = Path(rules_dir) if rules_dir else RULES_DIR
        self.work_dir = Path(work_dir) if work_dir else None
        self._before: list[str] | None = None
        self._after: list[str] | None = None
        self._tiers: bytes | None = None
        self._meta: dict = {}
        self._available = False
        self._source = self.dir
        self.error = ""
        self._load()

    # ----- 载入 -----

    def _active_dir(self) -> Path:
        """工作副本**五份文件齐全**时读它，否则一律读出厂文件。

        为什么要五份都齐：工作副本少一份分级索引时，条数与分级码对不上，
        只能把全部词条当成「常规校正」——分级会静默走样。宁可判定这份副本
        不完整、退回读出厂文件，也不让分级悄悄变。
        """
        if self.work_dir is None:
            return self.dir
        if all((self.work_dir / n).is_file() for n in BUILTIN_FILES):
            return self.work_dir
        return self.dir

    def _load(self) -> None:
        self._available = False
        self.error = ""
        self._source = self._active_dir()
        before = self._source / BUILTIN_BEFORE
        after = self._source / BUILTIN_AFTER
        tiers = self._source / BUILTIN_TIERS
        if not before.is_file() or not after.is_file():
            self.error = "内置词库文件未随程序一起提供"
            return
        try:
            self._before = json.loads(before.read_text("utf-8"))
            self._after = json.loads(after.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            self.error = f"内置词库读取失败（{type(exc).__name__}）"
            self._before = self._after = None
            return
        if not isinstance(self._before, list) or not isinstance(self._after, list):
            self.error = "内置词库结构异常"
            self._before = self._after = None
            return
        if len(self._before) != len(self._after):
            self.error = "内置词库两侧条数不一致"
            self._before = self._after = None
            return
        raw = _read_bytes(tiers)
        if raw is None or len(raw) != len(self._before):
            # 没有分级索引时全部归入常规校正（只读浏览仍然可用）
            raw = b"1" * len(self._before)
        self._tiers = raw
        meta_path = self._source / BUILTIN_META
        if meta_path.is_file():
            try:
                self._meta = json.loads(meta_path.read_text("utf-8"))
            except (OSError, ValueError):
                self._meta = {}
        self._available = True

    def reload(self) -> None:
        self._load()

    # ----- 出厂状态 / 工作副本 -----

    def factory_shas(self) -> dict[str, str]:
        """出厂各文件的 sha256（用来证明「恢复默认」真的回到了初始状态）。"""
        out: dict[str, str] = {}
        for name in BUILTIN_FILES:
            raw = _read_bytes(self.dir / name)
            if raw is not None:
                out[name] = _sha256_bytes(raw)
        return out

    def current_shas(self) -> dict[str, str]:
        """当前正在读的那一份（工作副本或出厂）各文件 sha256。"""
        out: dict[str, str] = {}
        for name in BUILTIN_FILES:
            raw = _read_bytes(self._source / name)
            if raw is not None:
                out[name] = _sha256_bytes(raw)
        return out

    def combined_sha(self) -> str:
        """把各文件 sha 拼起来再取一次，作为「这一份内置词库」的整体指纹。"""
        shas = self.current_shas()
        blob = "\n".join(f"{k}={shas[k]}" for k in sorted(shas)).encode("utf-8")
        return _sha256_bytes(blob)

    def factory_combined_sha(self) -> str:
        shas = self.factory_shas()
        blob = "\n".join(f"{k}={shas[k]}" for k in sorted(shas)).encode("utf-8")
        return _sha256_bytes(blob)

    def has_work_copy(self) -> bool:
        """工作副本是否完整可用（五份文件齐全 + 分级条数对得上）。"""
        if not self.work_dir:
            return False
        if not all((self.work_dir / n).is_file() for n in BUILTIN_FILES):
            return False
        raw = _read_bytes(self.work_dir / BUILTIN_TIERS)
        before = _read_bytes(self.work_dir / BUILTIN_BEFORE)
        if raw is None or before is None:
            return False
        try:
            n = len(json.loads(before.decode("utf-8")))
        except (UnicodeDecodeError, ValueError):
            return False
        return len(raw) == n

    def read_work_bytes(self) -> dict[str, bytes]:
        """当前生效那一份的全部字节（还原默认前先留一份，撤销才回得去）。"""
        out: dict[str, bytes] = {}
        for name in BUILTIN_FILES:
            raw = _read_bytes(self._source / name)
            if raw is not None:
                out[name] = raw
        return out

    def write_work_bytes(self, files: dict[str, bytes]) -> None:
        """把给定字节写进工作副本（原子写每个文件），随后重载。"""
        if self.work_dir is None:
            raise VocabDataError("内置词库没有可写的工作副本")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        for name, raw in files.items():
            _atomic_write(self.work_dir / name, raw)
        self.reload()

    def restore_from_factory(self) -> dict:
        """把工作副本逐字节还原为出厂内容（这就是「恢复默认词库」的真正动作）。"""
        if self.work_dir is None:
            raise VocabDataError("内置词库没有可写的工作副本")
        before_sha = self.combined_sha()
        factory = self.read_factory_bytes()
        if not factory:
            raise VocabDataError("出厂词库文件缺失，无法恢复")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        for name, raw in factory.items():
            _atomic_write(self.work_dir / name, raw)
        self.reload()
        after_sha = self.combined_sha()
        return dict(
            sha_before=before_sha,
            sha_after=after_sha,
            factory_sha=self.factory_combined_sha(),
            identical_to_factory=after_sha == self.factory_combined_sha(),
            files=len(factory),
        )

    def read_factory_bytes(self) -> dict[str, bytes]:
        out: dict[str, bytes] = {}
        for name in BUILTIN_FILES:
            raw = _read_bytes(self.dir / name)
            if raw is not None:
                out[name] = raw
        return out

    # ----- 基本信息 -----

    @property
    def available(self) -> bool:
        return self._available

    @property
    def source(self) -> Path:
        return self._source

    def __len__(self) -> int:
        return len(self._before or [])

    @property
    def meta(self) -> dict:
        return dict(self._meta)

    def tier_counts(self) -> dict[str, int]:
        out = {"b1": 0, "b2": 0, "b3": 0}
        if not self._tiers:
            return out
        counts: dict[int, int] = {}
        for code in self._tiers:
            counts[code] = counts.get(code, 0) + 1
        for code, n in counts.items():
            key = BUILTIN_TIER_CODE.get(chr(code))
            if key:
                out[key] += n
        return out

    def tier_of(self, idx: int) -> str:
        if not self._tiers:
            return "b1"
        code = chr(self._tiers[idx])
        return BUILTIN_TIER_CODE.get(code, "b1")

    def word_at(self, idx: int) -> str:
        return self._before[idx]  # type: ignore[index]

    def value_at(self, idx: int) -> str:
        return self._after[idx]  # type: ignore[index]

    # ----- 取数 -----

    def row(self, idx: int) -> dict:
        """生成一行（id 用负数，与自定义词条的正 id 天然区分）。"""
        dict_code = self.tier_of(idx)
        return dict(
            id=-(idx + 1),
            word=self.word_at(idx),
            value=self.value_at(idx),
            type=TIER_NAMES[dict_code].replace("词库", ""),
            pinyin="",
            dict=dict_code,
            tier="builtin",
            books=[],
        )

    def iter_rows(self) -> Iterator[dict]:
        for i in range(len(self)):
            yield self.row(i)

    def self_check(self) -> tuple[bool, str]:
        """内置三份文件的自洽检查：条数一致、分级码只含 1/2/3。

        返回 ``(是否通过, 说明)``。只读，不修任何东西。
        """
        if not self._available:
            return False, self.error or "内置词库不可用"
        n_before = len(self._before or [])
        n_after = len(self._after or [])
        if n_before != n_after:
            return False, f"两侧条数不一致（{n_before} / {n_after}）"
        if not self._tiers or len(self._tiers) != n_before:
            return False, f"分级索引条数与词条不一致（{len(self._tiers or b'')} / {n_before}）"
        bad = {c for c in set(self._tiers) if c not in (0x31, 0x32, 0x33)}
        if bad:
            return False, "分级索引含未知取值"
        return True, ""

    # ----- 检索 -----

    def search_count(self, query: str, dict_code: str | None = None) -> int:
        """命中条数（原词或替换值包含 query，大小写不敏感）。"""
        q = query.strip()
        if not q:
            return len(self) if dict_code in (None, "all", "builtin") else self.tier_counts().get(dict_code, 0)
        ql = q.lower()
        n = 0
        before, after, tiers = self._before or [], self._after or [], self._tiers or b""
        for i in range(len(before)):
            if dict_code not in (None, "all", "builtin"):
                want = TIER_NAMES[dict_code]
                if TIER_NAMES.get(BUILTIN_TIER_CODE.get(chr(tiers[i]), ""), "") != want:
                    continue
            w, v = before[i], after[i]
            if q in w or q in v or ql in w.lower() or ql in v.lower():
                n += 1
        return n

    def search(self, query: str, *, dict_code: str | None = None,
               limit: int | None = None, offset: int = 0) -> tuple[int, list[dict]]:
        """返回 (命中总数, 本页行)。总数是**全量**命中数，与文件实际条数一致。"""
        q = query.strip()
        ql = q.lower()
        before, after, tiers = self._before or [], self._after or [], self._tiers or b""
        only_tier = dict_code not in (None, "all", "builtin")
        total = 0
        rows: list[dict] = []
        want_code = dict_code if only_tier else None
        for i in range(len(before)):
            if only_tier and BUILTIN_TIER_CODE.get(chr(tiers[i]), "b1") != want_code:
                continue
            w, v = before[i], after[i]
            if q and not (q in w or q in v or ql in w.lower() or ql in v.lower()):
                continue
            if total >= offset and (limit is None or len(rows) < limit):
                rows.append(self.row(i))
            total += 1
        return total, rows

    # ----- 精确查重（新增前的冲突检测）-----

    def exact_word(self, word: str, limit: int = 5) -> list[dict]:
        """内置词库里与原词完全相同的条目。"""
        before = self._before or []
        hits: list[dict] = []
        for i in range(len(before)):
            if before[i] == word:
                hits.append(self.row(i))
                if len(hits) >= limit:
                    break
        return hits

    def exact_value(self, value: str, limit: int = 5) -> list[dict]:
        after = self._after or []
        hits: list[dict] = []
        for i in range(len(after)):
            if after[i] == value:
                hits.append(self.row(i))
                if len(hits) >= limit:
                    break
        return hits

# ---------------------------------------------------------------------------
# 自定义词库（可写，独立文件）
# ---------------------------------------------------------------------------

class CustomVocab:
    """「我的词库」：独立 JSON 文件，原子的、可逐字节回滚的写入。"""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else (CUSTOM_DIR / CUSTOM_FILE)
        self._entries: list[dict] = []
        self._raw: bytes = b""
        self.error = ""
        self._load_or_init()

    # ----- 读写 -----

    def _load_or_init(self) -> None:
        raw = _read_bytes(self.path)
        if raw is None:
            # 首次使用：落一份内容为空的规范文件，之后撤销永远有字节可比
            raw = self._encode([])
            try:
                _atomic_write(self.path, raw)
            except OSError as exc:
                self.error = f"自定义词库无法创建（{type(exc).__name__}）"
                self._raw = raw
                return
        self._raw = raw
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.error = "自定义词库内容无法解析，已按空词库显示（原文件未被改动）"
            self._entries = []
            return
        entries = data.get("entries") if isinstance(data, dict) else None
        self._entries = [self._normalize(e) for e in (entries or []) if isinstance(e, dict)]

    @staticmethod
    def _normalize(e: dict) -> dict:
        return dict(
            id=int(e.get("id") or 0),
            word=str(e.get("word") or ""),
            value=str(e.get("value") or ""),
            type=str(e.get("type") or ENTRY_TYPES[0]),
            pinyin=str(e.get("pinyin") or ""),
            book=str(e.get("book") or ""),
            created_at=str(e.get("created_at") or ""),
        )

    def _encode(self, entries: list[dict]) -> bytes:
        payload = dict(
            product="FixText",
            kind="custom_vocab",
            version=1,
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            count=len(entries),
            entries=entries,
        )
        return _dump_canonical(payload)

    def reload(self) -> None:
        self._load_or_init()

    # ----- 查询 -----

    def entries(self) -> list[dict]:
        return [dict(e) for e in self._entries]

    def __len__(self) -> int:
        return len(self._entries)

    def sha256(self) -> str:
        return _sha256_bytes(self._raw)

    def raw_bytes(self) -> bytes:
        return self._raw

    def row(self, e: dict) -> dict:
        return dict(id=e["id"], word=e["word"], value=e["value"], type=e["type"],
                    pinyin=e["pinyin"], dict="custom", tier="custom",
                    books=[e["book"]] if e["book"] else [])

    def rows(self) -> list[dict]:
        return [self.row(e) for e in self._entries]

    def by_word(self, word: str) -> list[dict]:
        return [e for e in self._entries if e["word"] == word]

    def by_value(self, value: str) -> list[dict]:
        return [e for e in self._entries if e["value"] == value]

    def search(self, query: str, *, limit: int | None = None,
               offset: int = 0) -> tuple[int, list[dict]]:
        q = query.strip()
        ql = q.lower()
        total = 0
        rows: list[dict] = []
        for e in self._entries:
            w, v = e["word"], e["value"]
            if q and not (q in w or q in v or ql in w.lower() or ql in v.lower()):
                continue
            if total >= offset and (limit is None or len(rows) < limit):
                rows.append(self.row(e))
            total += 1
        return total, rows

    # ----- 写入（调用方负责先查重 / 先预览）-----

    def add(self, *, word: str, value: str, typ: str, pinyin: str = "",
            book: str = "") -> dict:
        word, value = word.strip(), value.strip()
        if not word or not value:
            raise VocabDataError("原词与替换值都不能为空")
        nid = max((e["id"] for e in self._entries), default=0) + 1
        entry = dict(id=nid, word=word, value=value, type=typ or ENTRY_TYPES[0],
                     pinyin=(pinyin or "").strip(), book=book or "",
                     created_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        self._commit(self._entries + [entry])
        return dict(entry)

    def update(self, rid: int, *, word: str | None = None, value: str | None = None,
               typ: str | None = None, pinyin: str | None = None) -> dict:
        """改一条自定义词条（原型「编辑」按钮的真实落点）。"""
        rid = int(rid)
        target = next((e for e in self._entries if e["id"] == rid), None)
        if target is None:
            raise VocabDataError("要修改的词条不存在")
        new = dict(target)
        if word is not None:
            new["word"] = word.strip() or target["word"]
        if value is not None:
            new["value"] = value.strip() or target["value"]
        if typ:
            new["type"] = typ
        if pinyin is not None:
            new["pinyin"] = pinyin.strip()
        if not new["word"] or not new["value"]:
            raise VocabDataError("原词与替换值都不能为空")
        self._commit([new if e["id"] == rid else e for e in self._entries])
        return dict(new)

    def delete(self, ids: Iterable[int]) -> dict:
        drop = {int(i) for i in ids}
        kept = [e for e in self._entries if e["id"] not in drop]
        removed = len(self._entries) - len(kept)
        self._commit(kept)
        return dict(removed=removed, left=len(kept))

    def merge(self, ids: Iterable[int], target_word: str) -> dict:
        """把选中的同组词条并为一条：保留 ``target_word`` 那条，其余移除。"""
        target_ids = {int(i) for i in ids}
        group = [e for e in self._entries if e["id"] in target_ids]
        if len(group) < 2:
            raise VocabDataError("至少要选中 2 条自定义词条才能合并")
        keeper = next((e for e in group if e["word"] == target_word), None)
        if keeper is None:
            raise VocabDataError("合并目标不在选中的词条里")
        drop = {e["id"] for e in group if e["id"] != keeper["id"]}
        kept = [e for e in self._entries if e["id"] not in drop]
        self._commit(kept)
        return dict(removed=len(drop), left=len(kept), target=keeper["word"])

    def _commit(self, entries: list[dict]) -> None:
        raw = self._encode(entries)
        _atomic_write(self.path, raw)
        self._entries = [self._normalize(e) for e in entries]
        self._raw = raw

    # ----- 撤销：原始字节整份回写 -----

    def snapshot(self) -> bytes:
        return self._raw

    def restore(self, raw: bytes) -> None:
        _atomic_write(self.path, raw)
        self._raw = raw
        try:
            data = json.loads(raw.decode("utf-8"))
            entries = data.get("entries") if isinstance(data, dict) else []
            self._entries = [self._normalize(e) for e in (entries or []) if isinstance(e, dict)]
        except (UnicodeDecodeError, ValueError):
            self._entries = []


# ---------------------------------------------------------------------------
# 统一门面
# ---------------------------------------------------------------------------

class VocabStore:
    """界面层唯一入口：分级检索、查重、写入、还原点与操作历史都在这里。

    所有写操作都走同一条路：``_begin`` 先把「操作前」的原始字节留成还原点
    （落盘，见 :mod:`fixtext_snapshot`），再真正写文件，最后 ``_commit`` 记下
    「操作后」的字节。于是两条判据都变成硬的：

    * 撤回一步 → 写回该还原点的「操作前」字节，文件 sha 与当初相同；
    * 恢复到此刻 → 写回该还原点的「操作后」字节，文件 sha 与当初相同。

    还原点与操作历史都在 ``snapshots/index.json`` 里，换一个新进程照样读得到。
    """

    def __init__(self, *, custom_path: Path | str | None = None,
                 rules_dir: Path | str | None = None,
                 work_dir: Path | str | None = None,
                 snap_dir: Path | str | None = None,
                 max_points: int | None = None):
        explicit = custom_path is not None
        self.custom = CustomVocab(custom_path)
        # 传了自定义路径（测试 / 便携模式）时，工作副本与还原点都放在同一棵
        # 临时子树里，绝不碰交付包自带的用户区。
        base_dir = self.custom.path.parent if explicit else CUSTOM_DIR
        self.builtin = BuiltinVocab(
            rules_dir,
            work_dir=Path(work_dir) if work_dir else (base_dir / WORK_RULES_DIR))
        snap = Path(snap_dir) if snap_dir else (base_dir / SNAP_DIR)
        self.snap = SnapshotStore(snap, **({"max_points": max_points} if max_points else {}))

    # ----- 一律量 -----

    def counts(self) -> dict[str, int]:
        out = {"custom": len(self.custom)}
        out.update(self.builtin.tier_counts())
        return out

    @property
    def builtin_total(self) -> int:
        return len(self.builtin)

    def warning(self) -> str:
        return self.custom.error or self.builtin.error or self.snap.error

    # ----- 检索 -----

    def query(self, query: str, *, scope: str = "all",
              offset: int = 0, limit: int | None = None) -> tuple[int, list[dict]]:
        """按分级检索真实词库，返回 (命中总数, 本页行)。"""
        scope = scope or "all"
        if scope == "custom":
            return self.custom.search(query, limit=limit, offset=offset)
        if scope in ("b1", "b2", "b3"):
            return self.builtin.search(query, dict_code=scope, limit=limit, offset=offset)
        if scope == "builtin":
            return self.builtin.search(query, limit=limit, offset=offset)
        # all：自定义在前（少量、可写），内置在后
        c_total, c_rows = self.custom.search(query)
        b_total = self.builtin.search_count(query)
        total = c_total + b_total
        rows: list[dict] = []
        if offset < c_total:
            take = None if limit is None else max(0, limit)
            rows.extend(c_rows[offset:take if take is None else offset + take])
        need = None if limit is None else limit - len(rows)
        if need is None or need > 0:
            b_offset = max(0, offset - c_total)
            _, b_rows = self.builtin.search(query, offset=b_offset, limit=need)
            rows.extend(b_rows)
        return total, rows

    def row_by_id(self, rid: int) -> dict | None:
        rid = int(rid)
        if rid > 0:
            for e in self.custom.entries():
                if e["id"] == rid:
                    return self.custom.row(e)
            return None
        idx = -rid - 1
        if 0 <= idx < self.builtin_total:
            return self.builtin.row(idx)
        return None

    # ----- 查重 -----

    def conflicts_for_add(self, word: str, value: str) -> list[dict]:
        """新增前的冲突清单：同词同值 / 同词异值 / 同值异词，内置与自定义都查。"""
        word, value = word.strip(), value.strip()
        out: list[dict] = []
        for e in self.custom.by_word(word):
            kind = KIND_SAME_BOTH if e["value"] == value else KIND_SAME_WORD
            out.append(dict(kind=kind, word=e["word"], value=e["value"],
                            where=TIER_NAMES["custom"], id=e["id"]))
        for e in self.custom.by_value(value):
            if e["word"] == word:
                continue
            out.append(dict(kind=KIND_SAME_VALUE, word=e["word"], value=e["value"],
                            where=TIER_NAMES["custom"], id=e["id"]))
        for r in self.builtin.exact_word(word):
            kind = KIND_SAME_BOTH if r["value"] == value else KIND_SAME_WORD
            out.append(dict(kind=kind, word=r["word"], value=r["value"],
                            where=TIER_NAMES[r["dict"]], id=r["id"]))
        for r in self.builtin.exact_value(value):
            if r["word"] == word:
                continue
            out.append(dict(kind=KIND_SAME_VALUE, word=r["word"], value=r["value"],
                            where=TIER_NAMES[r["dict"]], id=r["id"]))
        return out

    def dup_groups(self) -> list[dict]:
        """「我的词库」内部的重复，以及与内置词库撞车的条目。"""
        groups: list[dict] = []
        entries = self.custom.entries()

        by_word: dict[str, list[dict]] = {}
        by_value: dict[str, list[dict]] = {}
        for e in entries:
            by_word.setdefault(e["word"], []).append(e)
            by_value.setdefault(e["value"], []).append(e)

        for w, arr in by_word.items():
            if len(arr) > 1:
                kinds = {KIND_SAME_BOTH if e["value"] == arr[0]["value"] else KIND_SAME_WORD for e in arr}
                kind = KIND_SAME_BOTH if kinds == {KIND_SAME_BOTH} else KIND_SAME_WORD
                groups.append(dict(kind=kind, key=w,
                                   items=[self.custom.row(e) for e in arr]))
        for v, arr in by_value.items():
            if len(arr) > 1 and len({e["word"] for e in arr}) > 1:
                groups.append(dict(kind=KIND_SAME_VALUE, key=v,
                                   items=[self.custom.row(e) for e in arr]))
        for e in entries:
            for r in self.builtin.exact_word(e["word"]):
                if r["value"] == e["value"]:
                    kind = KIND_SAME_BOTH
                else:
                    kind = KIND_SAME_WORD
                groups.append(dict(kind=f"与内置冲突·{kind}", key=e["word"],
                                   items=[self.custom.row(e), r]))
                break
        return groups

    # ----- 写操作的公共骨架：先落还原点，再写，最后记「操作后」-----

    def _disk_sha(self) -> str:
        """从磁盘重新读一次自定义词库的 sha——自证用，不用内存里的缓存。"""
        raw = _read_bytes(self.custom.path)
        return _sha256_bytes(raw) if raw is not None else ""

    def _begin(self, *, label: str, act: str, touches_builtin: bool = False) -> int:
        return self.snap.begin(
            label=label, act=act, before_bytes=self.custom.raw_bytes(),
            builtin_before=self.builtin.read_work_bytes() if touches_builtin else None,
            builtin_sha_before=self.builtin.combined_sha() if touches_builtin else "")

    def _commit(self, pid: int, *, act: str, summary: str, sha_before: str,
                detail: dict | None = None,
                builtin_sha_before: str = "", builtin_sha_after: str = "",
                builtin_factory: bool = False) -> dict:
        rec = self.snap.commit(pid, after_bytes=self.custom.raw_bytes(),
                               builtin_after_is_factory=builtin_factory,
                               builtin_sha_after=builtin_sha_after)
        self.snap.log_op(act=act, summary=summary, point_id=pid,
                         sha_before=rec.get("sha_before", sha_before),
                         sha_after=rec.get("sha_after", ""),
                         builtin_sha_before=builtin_sha_before,
                         builtin_sha_after=builtin_sha_after,
                         detail=detail)
        return dict(point_id=pid,
                    sha_before=rec.get("sha_before", sha_before),
                    sha_after=rec.get("sha_after", ""))

    def _run(self, *, label: str, act: str, summary: str, write,
             touches_builtin: bool = False, detail: dict | None = None) -> tuple[dict, dict]:
        """一次写操作的标准流程；写失败就把还原点撤掉，不留半截记录。"""
        sha_before = self._disk_sha()
        b_sha_before = self.builtin.combined_sha() if touches_builtin else ""
        pid = self._begin(label=label, act=act, touches_builtin=touches_builtin)
        try:
            result = write()
        except Exception:
            self.snap.abort(pid)
            raise
        b_sha_after = self.builtin.combined_sha() if touches_builtin else ""
        meta = self._commit(pid, act=act, summary=summary, sha_before=sha_before,
                            detail=detail, builtin_sha_before=b_sha_before,
                            builtin_sha_after=b_sha_after,
                            builtin_factory=(touches_builtin and
                                             b_sha_after == self.builtin.factory_combined_sha()))
        return result, meta

    # ----- 五个写操作（界面必须先预览确认，这里只负责写）-----

    def add_entry(self, *, word: str, value: str, typ: str, pinyin: str = "",
                  book: str = "") -> dict:
        label = f"新增「{word.strip()}」"
        result, meta = self._run(
            label=label, act=ACT_ADD, summary=label,
            write=lambda: self.custom.add(word=word, value=value, typ=typ,
                                          pinyin=pinyin, book=book),
            detail=dict(word=word.strip(), value=value.strip(), typ=typ))
        return dict(result, point_id=meta["point_id"], sha_after=meta["sha_after"])

    def update_entry(self, rid: int, *, word: str | None = None, value: str | None = None,
                     typ: str | None = None, pinyin: str | None = None) -> dict:
        old = self.row_by_id(int(rid)) or {}
        label = f"编辑「{word.strip() if word else old.get('word') or rid}」"
        result, meta = self._run(
            label=label, act=ACT_EDIT, summary=label,
            write=lambda: self.custom.update(rid, word=word, value=value,
                                             typ=typ, pinyin=pinyin),
            detail=dict(id=int(rid), before_value=old.get("value", ""),
                        after_value=value))
        return dict(result, point_id=meta["point_id"], sha_after=meta["sha_after"])

    def delete_entries(self, ids: Iterable[int]) -> dict:
        ids = [int(i) for i in ids]
        label = f"删除 {len(ids)} 条"
        result, meta = self._run(
            label=label, act=ACT_DELETE, summary=label,
            write=lambda: self.custom.delete(ids), detail=dict(ids=ids))
        return dict(result, point_id=meta["point_id"], sha_after=meta["sha_after"])

    def merge_entries(self, ids: Iterable[int], target_word: str) -> dict:
        ids = [int(i) for i in ids]
        label = f"合并为「{target_word}」"
        result, meta = self._run(
            label=label, act=ACT_MERGE, summary=label,
            write=lambda: self.custom.merge(ids, target_word),
            detail=dict(ids=ids, target=target_word))
        return dict(result, point_id=meta["point_id"], sha_after=meta["sha_after"])

    def add_book_words(self, words: list[dict], book: str = "") -> dict:
        """本书专有词批量加入（一次还原点覆盖整批，撤销时整批一起回去）。

        查重是硬的（§2.4.3 底线的延伸）：

        * 与已有词条**同词同值** → 已存在，跳过，记进 ``skipped_exists``
        * 与已有词条**同词异值 / 同值异词** → 冲突，跳过，记进 ``conflicts``
          （带冲突种类与命中处，界面必须显示出来，不静默覆盖）
        * 同一批里重复出现 → 只写第一条，记进 ``skipped_exists``

        返回 ``added`` / ``skipped_exists`` / ``conflicts`` / ``requested``，
        界面据此给出「加入几条、跳过几条、为什么跳过」。幂等：同一批再点一次
        ``added`` = 0，已有词条一条都不会被改写（sha 不变）。
        """
        label = f"加入 {len(words)} 条专有词"

        def _write() -> dict:
            added = 0
            skipped_exists: list[dict] = []
            conflicts: list[dict] = []
            seen: set[tuple[str, str]] = set()
            for w in words:
                word = str(w.get("word") or "").strip()
                if not word:
                    continue
                value = str(w.get("value") or word).strip() or word
                typ = str(w.get("type") or "专有名词").strip() or "专有名词"
                key = (word, value)
                if key in seen:
                    skipped_exists.append(dict(word=word, value=value,
                                               reason="这一批里重复出现，只写第一条"))
                    continue
                seen.add(key)
                hits = self.conflicts_for_add(word, value)
                if hits:
                    same = [h for h in hits if h.get("kind") == KIND_SAME_BOTH]
                    if same and len(same) == len(hits):
                        skipped_exists.append(dict(
                            word=word, value=value,
                            reason=f"《{book}》里已有同词同值的词条" if book
                                   else "词库里已有同词同值的词条"))
                    else:
                        conflicts.append(dict(word=word, value=value,
                                              hits=list(hits)))
                    continue
                self.custom.add(word=word, value=value, typ=typ, book=book)
                added += 1
            return dict(added=added, requested=len(words),
                        skipped_exists=skipped_exists, conflicts=conflicts)

        result, meta = self._run(
            label=label, act=ACT_BOOK, summary=label, write=_write,
            detail=dict(book=book, requested=len(words)))
        return dict(result, point_id=meta["point_id"], sha_after=meta["sha_after"])

    # ----- 恢复默认词库（只重置内置，自定义原样保留）-----

    def preview_restore_default(self) -> dict:
        """恢复默认的预览：真正动手前先算清楚会影响什么，界面拿它做二次确认。

        只读，不写任何文件——调用前后文件 sha、还原点条数都不变。
        """
        cur = self.builtin.current_shas()
        fac = self.builtin.factory_shas()
        diff = [n for n in sorted(fac) if cur.get(n) != fac.get(n)]
        return dict(
            builtin_sha_before=self.builtin.combined_sha(),
            builtin_sha_factory=self.builtin.factory_combined_sha(),
            already_default=not diff,
            changed_files=len(diff),
            file_count=len(fac),
            total_entries=self.builtin_total,
            tier_counts=self.builtin.tier_counts(),
            custom_entries=len(self.custom),
            custom_untouched=True,
            undoable=True,
            has_work_copy=self.builtin.has_work_copy(),
        )

    def restore_default(self) -> dict:
        """把内置词库逐字节还原为出厂内容；自定义词条条目与字节都不动。"""
        custom_before = self._disk_sha()
        result, meta = self._run(
            label="恢复默认词库", act=ACT_RESTORE_DEFAULT,
            summary="恢复默认词库（自定义保留）",
            write=self.builtin.restore_from_factory, touches_builtin=True,
            detail=dict(custom_entries=len(self.custom)))
        custom_after = self._disk_sha()
        return dict(
            point_id=meta["point_id"],
            sha_before=meta["sha_before"],
            sha_after=meta["sha_after"],
            custom_sha_before=custom_before,
            custom_sha_after=custom_after,
            custom_untouched=custom_before == custom_after,
            builtin_sha_before=result["sha_before"],
            builtin_sha_after=result["sha_after"],
            factory_sha=result["factory_sha"],
            identical_to_factory=result["identical_to_factory"],
            files=result["files"],
        )

    # ----- 还原点 / 操作历史 -----

    def timeline(self, limit: int | None = None) -> list[dict]:
        """时间线（最新在前）：每一次变更的时间点与摘要，供界面渲染。"""
        rows = self.snap.points(limit=limit)
        out = []
        for r in rows:
            item = dict(r)
            item["time"] = str(r.get("at", ""))[11:19] or str(r.get("at", ""))
            item["act_name"] = ACT_NAMES.get(r.get("act", ""), "变更")
            out.append(item)
        return out

    def ops(self, limit: int | None = None) -> list[dict]:
        """操作历史（最新在前）：每次变更的时间点、摘要、前后指纹。"""
        out = []
        for o in self.snap.ops(limit=limit):
            item = dict(o)
            item["time"] = str(o.get("at", ""))[11:19] or str(o.get("at", ""))
            item["act_name"] = ACT_NAMES.get(o.get("act", ""), "变更")
            out.append(item)
        return out

    def current_point_id(self) -> int:
        """当前状态对应的还原点 id（没有则为 0）——时间线与操作历史共用。"""
        head = self.snap.newest_alive()
        return int(head["id"]) if head else 0

    def point_count(self) -> int:
        return self.snap.point_count()

    def op_count(self) -> int:
        return self.snap.op_count()

    @property
    def can_undo(self) -> bool:
        return self.snap.newest_undoable() is not None

    def undo(self) -> dict | None:
        """撤回最近一次写操作：写回它的「操作前」字节。"""
        p = self.snap.newest_undoable()
        if p is None:
            return None
        pid = int(p["id"])
        raw = self.snap.before_bytes(pid)
        if raw is None:                     # 载荷丢了就不冒充能撤销
            return None
        expected = p.get("sha_before", "")
        self.custom.restore(raw)
        blob = self.snap.builtin_before(pid)
        builtin_ok = True
        if blob:
            try:
                self.builtin.write_work_bytes(blob)
            except VocabDataError:
                builtin_ok = False
        self.snap.mark_undone(pid, True)
        now = self._disk_sha()
        self.snap.log_op(act=ACT_UNDO, summary=f"撤销「{p.get('label', '')}」",
                         point_id=pid, sha_before=now, sha_after=now,
                         detail=dict(undone_point=pid))
        return dict(label=p.get("label", ""), sha=now, expected_sha=expected,
                    identical=bool(now and now == expected),
                    point_id=pid, builtin_restored=builtin_ok)

    def history(self, limit: int = 12) -> list[dict]:
        """变更记录（最新在前）——与「历史与快照」列表一一对应。

        只列仍可回退的还原点：撤回过的、或已被更早时间点覆盖的，不再出现。
        每行给 ``index``（按最新在前编号）、``label``、``time``、``sha``
        （这一条对应的「操作前」指纹），``undo_to(index)`` 用的就是这个编号。
        """
        alive = [r for r in self.snap.points() if not r["undone"]]
        out: list[dict] = []
        for i, r in enumerate(alive):
            if len(out) >= limit:
                break
            out.append(dict(index=i, label=r["label"], time=r["time"],
                            sha=r["sha_before"], sha_after=r["sha_after"],
                            point_id=r["id"], is_current=r["is_current"]))
        return out

    def undo_to(self, index: int) -> dict | None:
        """把词库还原到「历史与快照」里第 ``index`` 条记录之前的状态。

        记录按最新在前编号（与 :meth:`history` 一致）。还原后，比它更新的
        记录随之失效——它们描述的那条线已不存在。
        """
        alive = [r for r in self.snap.points() if not r["undone"]]
        if index < 0 or index >= len(alive):
            return None
        row = alive[int(index)]
        pid = int(row["id"])
        raw = self.snap.before_bytes(pid)
        if raw is None:
            return None
        expected = row.get("sha_before", "")
        self.custom.restore(raw)
        blob = self.snap.builtin_before(pid)
        if blob:
            try:
                self.builtin.write_work_bytes(blob)
            except VocabDataError:
                pass
        newer = self.snap.mark_undone_newer_than(pid)
        self.snap.mark_undone(pid, True)
        now = self._disk_sha()
        self.snap.log_op(act=ACT_UNDO, summary=f"退回到「{row['label']}」之前",
                         point_id=pid, sha_before=now, sha_after=now,
                         detail=dict(undone_point=pid, undone_newer=newer))
        return dict(label=row["label"], sha=now, expected_sha=expected,
                    identical=bool(now and now == expected),
                    point_id=pid, undone_newer=newer)

    def restore_point(self, point_id: int) -> dict | None:
        """「恢复到此刻」：把该时间点的「操作后」状态原样写回。"""
        p = self.snap.get(int(point_id))
        if p is None:
            return None
        pid = int(point_id)
        raw = self.snap.after_bytes(pid)
        if raw is None:
            return None
        expected = p.get("sha_after", "")
        self.custom.restore(raw)
        builtin_applied = False
        if self.snap.builtin_after_is_factory(pid):
            try:
                self.builtin.restore_from_factory()
                builtin_applied = True
            except VocabDataError:
                pass
        newer = self.snap.mark_undone_newer_than(pid)
        self.snap.mark_undone(pid, False)
        now = self._disk_sha()
        self.snap.log_op(act=ACT_RESTORE_POINT,
                         summary=f"恢复到 {str(p.get('at', ''))[11:19]}",
                         point_id=pid, sha_before=now, sha_after=now,
                         detail=dict(point_id=pid, undone_newer=newer))
        return dict(point_id=pid, label=p.get("label", ""),
                    at=p.get("at", ""), sha=now, expected_sha=expected,
                    identical=bool(now and now == expected),
                    builtin_applied=builtin_applied, undone_newer=newer)

    def push_snapshot(self, label: str) -> int:
        """给「本来就不用写文件」的动作也留一个时间点（时间线不出现空洞）。"""
        return int(self.snap.begin(label=label, act="note",
                                   before_bytes=self.custom.raw_bytes()))

    def flush(self) -> None:
        self.snap._flush()
