"""
FixText V1 · 词库真实数据层（M3-T3.1）
=====================================

本模块**不依赖 Qt**，只负责词库的读取、检索、查重与写入。界面层
（``vocab_module.py``）只通过这里的接口取数，不自己拼路径、不自己写文件。

分级存储（§2.4.1 底线⑤ · 自定义与内置物理分离）
------------------------------------------------
* **内置词库（只读）**：``data/rules/before.json`` + ``after.json`` 两份平行数组，
  每条规则占同一下标。所属分级由 ``data/rules/builtin_tiers.bin``（每条 1 字节：
  ``1`` 常规校正 / ``2`` 标点规范 / ``3`` 繁简转换）给出，出处与校验值见
  ``data/rules/builtin_index_meta.json``。内置词库全程**不写**。
* **自定义词库（可写）**：独立的 ``workspace/vocab/custom_vocab.json``，与内置词库
  既不在同一目录、也不是同一份文件；界面只显示友好名「我的词库」，不露路径。

写入安全
--------
* 写文件一律「临时文件 + fsync + os.replace + fsync 目录」，避免半截文件。
* 每次改动前把**原始字节**整份留在撤销记录里；撤销时把原始字节原样写回，
  因此撤销后的文件与改动前逐字节一致（sha256 相同，可自证）。
* 内置词库不进撤销记录——它本来就不写，撤销只需要还原自定义词库那一份文件。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

# ---------------------------------------------------------------------------
# 路径（仅本模块内部使用，界面层拿不到、也不展示）
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parent
RULES_DIR = PKG_ROOT / "data" / "rules"

BUILTIN_BEFORE = "before.json"
BUILTIN_AFTER = "after.json"
BUILTIN_TIERS = "builtin_tiers.bin"

#: 自定义词库目录（与内置词库 ``data/rules/`` 完全不同的一棵子树）
CUSTOM_DIR = HERE / "workspace" / "vocab"
CUSTOM_FILE = "custom_vocab.json"

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
# 内置词库（只读，按需生成行，不为 30 万条建 dict 列表）
# ---------------------------------------------------------------------------

class BuiltinVocab:
    """内置词库：两份平行数组 + 每条的 1 字节分级码。"""

    def __init__(self, rules_dir: Path | str | None = None):
        self.dir = Path(rules_dir) if rules_dir else RULES_DIR
        self._before: list[str] | None = None
        self._after: list[str] | None = None
        self._tiers: bytes | None = None
        self._meta: dict = {}
        self._available = False
        self.error = ""
        self._load()

    # ----- 载入 -----

    def _load(self) -> None:
        before = self.dir / BUILTIN_BEFORE
        after = self.dir / BUILTIN_AFTER
        tiers = self.dir / BUILTIN_TIERS
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
        meta_path = self.dir / "builtin_index_meta.json"
        if meta_path.is_file():
            try:
                self._meta = json.loads(meta_path.read_text("utf-8"))
            except (OSError, ValueError):
                self._meta = {}
        self._available = True

    # ----- 基本信息 -----

    @property
    def available(self) -> bool:
        return self._available

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
    """界面层唯一入口：分级检索、查重、写入与回滚都在这里。"""

    def __init__(self, *, custom_path: Path | str | None = None,
                 rules_dir: Path | str | None = None):
        self.builtin = BuiltinVocab(rules_dir)
        self.custom = CustomVocab(custom_path)
        self._undo: list[dict] = []

    # ----- 一律量 -----

    def counts(self) -> dict[str, int]:
        out = {"custom": len(self.custom)}
        out.update(self.builtin.tier_counts())
        return out

    @property
    def builtin_total(self) -> int:
        return len(self.builtin)

    def warning(self) -> str:
        return self.custom.error or self.builtin.error

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

    # ----- 写入（先留快照，再改文件）-----

    def _begin(self, label: str) -> None:
        self._undo.append(dict(label=label, raw=self.custom.snapshot(),
                               sha=self.custom.sha256(),
                               time=time.strftime("%H:%M:%S"),
                               at=time.time()))

    def add_entry(self, *, word: str, value: str, typ: str, pinyin: str = "",
                  book: str = "") -> dict:
        self._begin(f"新增「{word.strip()}」")
        return self.custom.add(word=word, value=value, typ=typ, pinyin=pinyin, book=book)

    def update_entry(self, rid: int, *, word: str | None = None, value: str | None = None,
                     typ: str | None = None, pinyin: str | None = None) -> dict:
        self._begin(f"编辑「{word.strip() if word else rid}」")
        return self.custom.update(rid, word=word, value=value, typ=typ, pinyin=pinyin)

    def delete_entries(self, ids: Iterable[int]) -> dict:
        ids = [int(i) for i in ids]
        self._begin(f"删除 {len(ids)} 条")
        return self.custom.delete(ids)

    def merge_entries(self, ids: Iterable[int], target_word: str) -> dict:
        self._begin(f"合并为「{target_word}」")
        return self.custom.merge(ids, target_word)

    # ----- 撤销 -----

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> dict | None:
        if not self._undo:
            return None
        rec = self._undo.pop()
        self.custom.restore(rec["raw"])
        return dict(label=rec["label"], sha=self.custom.sha256(),
                    expected_sha=rec["sha"], identical=self.custom.sha256() == rec["sha"])

    def history(self, limit: int = 12) -> list[dict]:
        """变更记录（最新在前），供「历史与快照」列表展示。

        只给界面需要的字段：标签、时间、以及这条记录对应的还原点是否仍可用。
        """
        out: list[dict] = []
        for i, rec in enumerate(reversed(self._undo)):
            if len(out) >= limit:
                break
            out.append(dict(index=i, label=rec["label"], time=rec.get("time", ""),
                            sha=rec.get("sha", "")))
        return out

    def undo_to(self, index: int) -> dict | None:
        """把自定义词库还原到「历史与快照」里第 ``index`` 条记录的原始字节。

        记录按最新在前编号（与 :meth:`history` 一致）。还原后，比它更新的
        记录随之失效（它们描述的状态已不存在），这条记录也一并出栈。
        """
        total = len(self._undo)
        if index < 0 or index >= total:
            return None
        pos = total - 1 - int(index)
        rec = self._undo[pos]
        self.custom.restore(rec["raw"])
        del self._undo[pos:]
        return dict(label=rec["label"], sha=self.custom.sha256(),
                    expected_sha=rec["sha"], identical=self.custom.sha256() == rec["sha"])

    def push_snapshot(self, label: str) -> None:
        """给「本来就不用写文件」的动作也留一个回滚点（保持撤销语义一致）。"""
        self._begin(label)
