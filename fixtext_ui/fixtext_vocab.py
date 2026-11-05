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
from fixtext_word_states import STATES_FILE_NAME, WordStateStore, entry_key

# ---------------------------------------------------------------------------
# 路径（仅本模块内部使用，界面层拿不到、也不展示）
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
# 包根统一由 fixtext_paths 解析（M4-T4.1b）：内置词库 data/rules 在包根，
# 冻结后按 __file__ 反推会指到程序内部目录，界面会报「词库文件未随程序提供」。
try:
    from fixtext_paths import pkg_root as _pkg_root

    PKG_ROOT = _pkg_root()
except Exception:                     # pragma: no cover
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

#: 分级代号 → 友好名（全部拆袋 + 自定义；与一键勾选 / 开关袋对齐）
TIER_NAMES = {
    "custom": "我的词库",
    "b1": "常规校正词库",
    "cjk": "CJK 恢复词库",
    "b3": "繁简转换词库",
    "b3r": "繁简转换激进词库",
    "extra": "的地得/象像加强",
    "ddd": "的地得词库",
    "dei2de": "「得」转「的」",
    "old_style": "旧式通假词库",
    "txt_format": "txtFormat 词库",
    "preprocess": "预处理词库",
    "strict": "严格校正词库",
    "zhuyin": "生僻字注音词库",
    "imported": "迁入的注释词条",
    # 磁盘有、界面不挂：punctuation（已迁排版）、postfix/temp（等后续功能）
}
#: 袋 id → 界面分级码（可达袋）
BAG_TO_TIER = {
    "normal": "b1",
    "cjk_recover": "cjk",
    "t2s": "b3",
    "t2s_radical": "b3r",
    "extra": "extra",
    "ddd": "ddd",
    "dei2de": "dei2de",
    "old_style": "old_style",
    "txt_format": "txt_format",
    "preprocess": "preprocess",
    "strict": "strict",
    "zhuyin": "zhuyin",
}
#: 界面分级码 → 合成 tiers 单字节（仅内存索引；1/3–6 兼容旧 flat；2 原标点已弃用）
TIER_TO_BYTE = {
    "b1": b"1",
    "b3": b"3",
    "preprocess": b"4",
    "strict": b"5",
    "zhuyin": b"6",
    "cjk": b"7",
    "extra": b"8",
    "old_style": b"9",
    "txt_format": b"A",
    "ddd": b"B",
    "dei2de": b"C",
    "b3r": b"F",
}
BUILTIN_TIER_CODE = {
    "1": "b1",
    "3": "b3",
    "4": "preprocess",
    "5": "strict",
    "6": "zhuyin",
    "7": "cjk",
    "8": "extra",
    "9": "old_style",
    "A": "txt_format",
    "B": "ddd",
    "C": "dei2de",
    "F": "b3r",
}
TIER_ORDER = [
    "custom", "b1", "cjk", "b3", "b3r",
    "extra", "ddd", "dei2de", "old_style", "txt_format",
    "preprocess", "strict", "zhuyin", "imported",
]

#: 迁入注释词条的虚拟分级（V1.1-T1.2 界面层）。
#: 这些词条不在 ``data/rules/`` 里（它们来自出厂迁入数据，默认禁用、等用户
#: 自行启用），所以**必须**单独占一个分级才可能在词库页被看见；
#: 它是只读分级：不能编辑 / 删除，只能改启用状态。
TIER_IMPORTED = "imported"
#: 迁入词条的 id 偏移：与内置（``-(idx+1)``）天然不撞。
IMPORTED_ID_BASE = 900000

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
ACT_ENABLE = "enable"
ACT_DISABLE = "disable"
ACT_CLEAR_DISABLED = "clear_disabled"
ACT_RESET_STATES = "reset_states"
ACT_BOOK_EXCLUDE = "book_exclude"
ACT_BOOK_INCLUDE = "book_include"
#: V1.1-D5：整批导入。整批只占一个还原点，所以撤销栈里它也只算一步。
ACT_IMPORT_BATCH = "import_batch"
#: 一次没写成的批量导入（已自动退回 / 或需用户手动退回），只进操作历史、不留还原点。
ACT_IMPORT_FAILED = "import_failed"

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
    ACT_ENABLE: "启用词条",
    ACT_DISABLE: "禁用词条",
    ACT_CLEAR_DISABLED: "清空禁用",
    ACT_RESET_STATES: "恢复默认状态",
    ACT_BOOK_EXCLUDE: "本书停用",
    ACT_BOOK_INCLUDE: "本书恢复",
    ACT_IMPORT_BATCH: "批量导入",
    ACT_IMPORT_FAILED: "导入未完成",
    "note": "标记",
}


class VocabDataError(RuntimeError):
    """真实词库不可用时的内部异常（界面层转成人话提示，不直接抛给用户）。"""


def conflict_list(builtin, word: str, value: str,
                  custom_word_hits: list[dict],
                  custom_value_hits: list[dict]) -> list[dict]:
    """冲突判定的唯一实现（模块级，单条与批量两条入口都调它）。

    判定口径逐字沿用既有 `conflicts_for_add`：
    * 自定义里**同词**：值相同 → 同词同值，否则同词异值；
    * 自定义里**同值但不同词** → 同值异词；
    * 内置里**同词**（`exact_word`）同上规则；
    * 内置里**同值但不同词**（`exact_value`）→ 同值异词。

    三重形态常量 `KIND_SAME_BOTH` / `KIND_SAME_WORD` / `KIND_SAME_VALUE`
    就在本模块顶部定义，界面的分组标签直接用它们，不另造说法。
    """
    out: list[dict] = []
    for e in custom_word_hits:
        kind = KIND_SAME_BOTH if e["value"] == value else KIND_SAME_WORD
        out.append(dict(kind=kind, word=e["word"], value=e["value"],
                        where=TIER_NAMES["custom"], id=e["id"]))
    for e in custom_value_hits:
        if e["word"] == word:
            continue
        out.append(dict(kind=KIND_SAME_VALUE, word=e["word"], value=e["value"],
                        where=TIER_NAMES["custom"], id=e["id"]))
    for r in builtin.exact_word(word):
        kind = KIND_SAME_BOTH if r["value"] == value else KIND_SAME_WORD
        out.append(dict(kind=kind, word=r["word"], value=r["value"],
                        where=TIER_NAMES[r["dict"]], id=r["id"]))
    for r in builtin.exact_value(value):
        if r["word"] == word:
            continue
        out.append(dict(kind=KIND_SAME_VALUE, word=r["word"], value=r["value"],
                        where=TIER_NAMES[r["dict"]], id=r["id"]))
    return out


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


def _read_bytes(path: Path) -> bytes | None:
    """读普通文件字节；缺文件或路径是目录时返回 None（勿把 bags/ 当文件读）。"""
    try:
        if not path.is_file():
            return None
        return path.read_bytes()
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
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
        # V1.1-D3：精确查重的惰性索引（词 → 下标列表）。30 万条词库上逐条线性
        # 扫一遍约 6.6ms，预览上千行就是十几秒；建一次索引 179ms、之后一次查
        # 0.13µs。**索引只换查法、不换判定**——`exact_word` / `exact_value`
        # 仍是「原词逐字相等」并按下标升序、最多 limit 条，同名多条的行为不变
        # （等价性由 tests/test_d3_preview_groups.py 用全量对拍钉住）。
        # 惰性建：不查重就不付这份 179ms；载入 / 还原后置空，下次重建。
        self._word_index: dict[str, list[int]] | None = None
        self._value_index: dict[str, list[int]] | None = None
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

    def _bags_dir(self) -> Path | None:
        """出厂或工作副本下的 bags/；有 manifest 才算可用。"""
        for root in (self.work_dir, self.dir):
            if root is None:
                continue
            cand = Path(root) / "bags"
            if (cand / "manifest.json").is_file():
                return cand
        # 出厂 bags 也可能只在 rules_dir/bags（无工作副本）
        cand = self.dir / "bags"
        if (cand / "manifest.json").is_file():
            return cand
        return None

    def _load_from_bags(self, bags_dir: Path) -> bool:
        """按袋目录拼成平行数组 + 分级码（只读展示用）。"""
        before: list[str] = []
        after: list[str] = []
        tier_bytes = bytearray()
        loaded = 0
        for bag_id, tier_code in BAG_TO_TIER.items():
            bpath = bags_dir / bag_id / "before.json"
            apath = bags_dir / bag_id / "after.json"
            if not (bpath.is_file() and apath.is_file()):
                continue
            try:
                b = json.loads(bpath.read_text("utf-8"))
                a = json.loads(apath.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(b, list) or not isinstance(a, list) or len(b) != len(a):
                continue
            marker = TIER_TO_BYTE.get(tier_code, b"1")
            before.extend(str(x) for x in b)
            after.extend(str(x) for x in a)
            tier_bytes.extend(marker * len(b))
            loaded += 1
        if loaded == 0 or not before:
            return False
        self._before = before
        self._after = after
        self._tiers = bytes(tier_bytes)
        # 展示内容来自 bags，但指纹 / 恢复默认 / 工作副本仍以 flat 五件套为据。
        # 若把 _source 指到 bags 目录，current_shas 会对目录拼 before.json → 空指纹，
        # 再对目录本身 read_bytes 会触发 IsADirectoryError / PermissionError。
        self._source = self._active_dir()
        try:
            self._meta = json.loads((bags_dir / "manifest.json").read_text("utf-8"))
        except (OSError, ValueError):
            self._meta = {"source": "bags"}
        self._meta = dict(self._meta)
        self._meta["vocab_source"] = "bags"
        self._meta["bags_dir"] = str(bags_dir)
        self._available = True
        return True

    def _load(self) -> None:
        self._available = False
        self.error = ""
        # 索引跟着数组走：任何一次（重新）载入都作废旧的索引
        self._word_index = None
        self._value_index = None
        # M5-EX.1：优先按袋目录展示（常规/标点/繁简 + 预处理/严格/注音）
        bags_dir = self._bags_dir()
        if bags_dir is not None and self._load_from_bags(bags_dir):
            return

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
        out = {k: 0 for k in TIER_NAMES if k != "custom"}
        if not self._tiers:
            return out
        counts: dict[int, int] = {}
        for code in self._tiers:
            counts[code] = counts.get(code, 0) + 1
        for code, n in counts.items():
            key = BUILTIN_TIER_CODE.get(chr(code))
            if key:
                out[key] = out.get(key, 0) + n
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
        allowed = {ord(k) for k in BUILTIN_TIER_CODE}
        bad = {c for c in set(self._tiers) if c not in allowed}
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

    def _index_of(self, kind: str) -> dict[str, list[int]]:
        """惰性构建并返回「文字 → 下标列表」索引（`kind` 取 `word` / `value`）。

        一次遍历建全表（30 万条约 179ms），之后每次查是字典命中原词，
        直接把精确查重从「每次线性扫全库」降到常数级。
        下标天然按升序追加，所以取前 `limit` 个与线性扫描「遇到就收、
        收满即停」的顺序**完全一致**——这是判定等价的关键，不是巧合。
        """
        if kind == "word":
            if self._word_index is None:
                idx: dict[str, list[int]] = {}
                for i, w in enumerate(self._before or []):
                    idx.setdefault(w, []).append(i)
                self._word_index = idx
            return self._word_index
        if self._value_index is None:
            idx2: dict[str, list[int]] = {}
            for i, v in enumerate(self._after or []):
                idx2.setdefault(v, []).append(i)
            self._value_index = idx2
        return self._value_index

    @staticmethod
    def _first_hits(index: dict[str, list[int]], key: str, limit: int) -> list[int]:
        """按线性扫描同一口径取「前 limit 个下标」。

        刻意与旧的线性实现逐字对齐（含边界）：旧写法是「先收一条、再看够不够
        limit」，所以 `limit <= 0` 时命中一条即停，返回 **1** 条而不是 0 条。
        这里照抄这个边界，不趁机「顺手修正」——查重结果关系到用户词库写不写，
        口径不许在执行层悄悄变化。
        """
        take = int(limit) if int(limit) >= 1 else 1
        return list(index.get(key, ())[:take])

    def exact_word(self, word: str, limit: int = 5) -> list[dict]:
        """内置词库里与原词完全相同的条目。"""
        hits = self._first_hits(self._index_of("word"), word, limit)
        return [self.row(i) for i in hits]

    def exact_value(self, value: str, limit: int = 5) -> list[dict]:
        """内置词库里与替换值完全相同的条目。"""
        hits = self._first_hits(self._index_of("value"), value, limit)
        return [self.row(i) for i in hits]

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

    def merge(self, ids: Iterable[int], target_word: str | None = None,
              *, keep_id: int | None = None) -> dict:
        """把同组词条并为一条：保留指定那条，其余移除。

        保留哪条有两种指定方式（V1.1-EX.2R 起查重清单组内「选一保留」用后一种）：

        * ``keep_id``：按词条 id 指定（同词异值组里用户选的是「哪一条」，
          这组词条原词相同、靠 id 才能区分）；
        * ``target_word``：按原词指定（同词同值组里任一条等价，按原词即可）。

        两条都不给时按组内第一条保留。
        """
        target_ids = {int(i) for i in ids}
        group = [e for e in self._entries if e["id"] in target_ids]
        if len(group) < 2:
            raise VocabDataError("至少要选中 2 条自定义词条才能合并")
        if keep_id is not None:
            keeper = next((e for e in group if e["id"] == int(keep_id)), None)
            if keeper is None:
                raise VocabDataError("要保留的那条不在这一组里")
        elif target_word is not None:
            keeper = next((e for e in group if e["word"] == target_word), None)
            if keeper is None:
                raise VocabDataError("合并目标不在选中的词条里")
        else:
            keeper = group[0]
        drop = {e["id"] for e in group if e["id"] != keeper["id"]}
        kept = [e for e in self._entries if e["id"] not in drop]
        self._commit(kept)
        return dict(removed=len(drop), left=len(kept), target=keeper["word"],
                    kept_value=keeper["value"], kept_id=keeper["id"])

    def _commit(self, entries: list[dict]) -> None:
        self.replace_all(entries)               # 单条写与整批写共用同一份落盘实现

    def replace_all(self, entries: list[dict]) -> bytes:
        """整批替换：把 ``entries`` 一次编码、一次原子替换落盘，返回写出去的字节。

        与逐条 ``add()`` 的区别是**落盘次数**：逐条写 N 次，中途失败就留下半批；
        这里只写一次，磁盘上要么是旧文件、要么是完整的新文件（本卡「不落半批」的
        第一道闸；第二道是调用方写完再读盘核对）。

        与 ``_commit`` 不是两条实现：``_commit`` 现在就走这里，编码 / 原子写 /
        内存同步只有这一份，两处不会漂移。
        """
        raw = self._encode([self._normalize(e) for e in entries])
        _atomic_write(self.path, raw)
        self._entries = [self._normalize(e) for e in entries]
        self._raw = raw
        return raw

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
        # 词条启用 / 禁用（V1.1-T1.1）：禁用集文件与自定义词库同一棵用户区子树，
        # 出厂迁入数据（data/word_states/）与内置词库一样全程只读。
        self.states = WordStateStore(writable_path=base_dir / STATES_FILE_NAME)
        # 迁入词条行缓存（V1.1-T1.2）：5841 行每次重建太浪费，且它们的
        # 词 / 替换值来自出厂只读数据，构造一次即可复用。
        self._imported_rows_cache: list[dict] | None = None
        # 按书词库（V1.1-C2）：当前书的 id。默认空 = 没有选中的书，
        # 界面走空状态；按书文件的位置见 :meth:`_book_path_for`。
        self._book_id = ""
        # 用户区里「词库这一层」的根（自定义 / 禁用集 / 按书清单都长在它下面）。
        # 默认 = 包内用户区的 vocab 目录；显式传自定义位置（测试 / 便携）时
        # 跟着那棵树走，绝不串到交付包自带的用户区。
        self.base_dir = base_dir

    # ----- 一律量 -----

    def counts(self) -> dict[str, int]:
        out = {"custom": len(self.custom)}
        out.update(self.builtin.tier_counts())
        # 迁入注释词条（V1.1-T1.2）：不在 data/rules/ 里，单独计入自己的分级
        out[TIER_IMPORTED] = len(self.imported_rows())
        return out

    @property
    def builtin_total(self) -> int:
        return len(self.builtin)

    def warning(self) -> str:
        return self.custom.error or self.builtin.error or self.snap.error or self.states.error

    # ----- 词条启用 / 禁用：呈现层接口（V1.1-T1.2）-----

    def imported_rows(self) -> list[dict]:
        """迁入注释词条的行清单（只读、默认禁用、可启用；不改出厂数据）。

        这些词条**不在** ``data/rules/`` 里——它们由 T1.1 的数据层迁入，
        默认不参与校正。给它们稳定的负 id（``-IMPORTED_ID_BASE - 序号``），
        与内置（``-(idx+1)``）和自定义（正 id）三者互不相撞。
        """
        if self._imported_rows_cache is not None:
            return [dict(r) for r in self._imported_rows_cache]
        rows: list[dict] = []
        for i, e in enumerate(self.states.imported_entries()):
            rows.append(dict(
                id=-(IMPORTED_ID_BASE + i + 1),
                word=e["word"],
                value=str(e.get("value") or ""),
                type="注释词条",
                pinyin="",
                dict=TIER_IMPORTED,
                tier=TIER_IMPORTED,
                books=[],
                src=str(e.get("src") or ""),
            ))
        self._imported_rows_cache = rows
        return [dict(r) for r in rows]

    def imported_row_by_id(self, rid: int) -> dict | None:
        rid = int(rid)
        idx = -rid - IMPORTED_ID_BASE - 1
        cache = self._imported_rows_cache
        if cache is None:
            cache = self.imported_rows()
        return dict(cache[idx]) if 0 <= idx < len(cache) else None

    def mark_states(self, rows: list[dict]) -> list[dict]:
        """给每行补上启用 / 禁用状态（``enabled`` 布尔 + ``state`` 人话）。

        界面只读这两个字段，不自己算哈希：一眼看清「这条现在参不参与校正」。
        """
        eff = self.states.effective_disabled()
        out: list[dict] = []
        for r in rows:
            r = dict(r)
            on = entry_key(r["word"], r.get("value", "")) not in eff
            r["enabled"] = on
            r["state"] = "启用" if on else "禁用"
            out.append(r)
        return out

    def states_for_rows(self, rows: list[dict]) -> dict[int, bool]:
        """``row id → 是否启用``（供界面在重建行时批量取状态）。"""
        eff = self.states.effective_disabled()
        return {int(r["id"]): entry_key(r["word"], r.get("value", "")) not in eff
                for r in rows}

    # ----- 检索 -----

    def query(self, query: str, *, scope: str = "all",
              offset: int = 0, limit: int | None = None) -> tuple[int, list[dict]]:
        """按分级检索真实词库，返回 (命中总数, 本页行)。"""
        scope = scope or "all"
        if scope == "custom":
            return self.custom.search(query, limit=limit, offset=offset)
        if scope == TIER_IMPORTED:
            return self._imported_search(query, offset=offset, limit=limit)
        if scope in BAG_TO_TIER.values():
            return self.builtin.search(query, dict_code=scope, limit=limit, offset=offset)
        if scope == "builtin":
            return self.builtin.search(query, limit=limit, offset=offset)
        # all：自定义在前（少量、可写），内置在后；迁入词条默认禁用、
        # 且只读，不混进「全部」里搅乱命中数（用户用左侧分级单独查看）
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

    def _imported_search(self, query: str, *, offset: int = 0,
                         limit: int | None = None) -> tuple[int, list[dict]]:
        """迁入注释词条的检索（与内置 / 自定义同一套「双向包含」口径）。

        「双向」= 原词或替换值里包含关键词，大小写不敏感——和用户在内置分级
        搜索时的预期一致，不需要为迁入词条再学一种查法。
        """
        q = (query or "").strip()
        ql = q.lower()
        total = 0
        rows: list[dict] = []
        for r in self.imported_rows():
            w, v = r["word"], r["value"]
            if q and not (q in w or q in v or ql in w.lower() or ql in v.lower()):
                continue
            if total >= offset and (limit is None or len(rows) < limit):
                rows.append(r)
            total += 1
        return total, rows

    def row_by_id(self, rid: int) -> dict | None:
        rid = int(rid)
        if rid > 0:
            for e in self.custom.entries():
                if e["id"] == rid:
                    return self.custom.row(e)
            return None
        # 迁入注释词条占 -IMPORTED_ID_BASE 之后的号段（V1.1-T1.2）
        if rid < -IMPORTED_ID_BASE:
            return self.imported_row_by_id(rid)
        idx = -rid - 1
        if 0 <= idx < self.builtin_total:
            return self.builtin.row(idx)
        return None

    # ----- 查重 -----

    def conflicts_for_add(self, word: str, value: str) -> list[dict]:
        """新增前的冲突清单：同词同值 / 同词异值 / 同值异词，内置与自定义都查。"""
        return self._conflicts_from_hits(
            str(word or "").strip(), str(value or "").strip(),
            self.custom.by_word(str(word or "").strip()),
            self.custom.by_value(str(value or "").strip()),
        )

    def _conflicts_from_hits(self, word: str, value: str,
                             custom_word_hits: list[dict],
                             custom_value_hits: list[dict]) -> list[dict]:
        """冲突判定的**唯一实现**：给「已命中的自定义条目」出冲突清单。

        `conflicts_for_add`（查一条）与 `conflicts_for_add_many`（预览查一批）
        都调这里，所以两条路径不可能给出不同的结论——批量版只把「查库」动作
        批量化（自定义词库建一次索引、内置走 `exact_word` 的索引），判定本身
        一字未改。V1.1-D3 的冲突分组因此是**既有查重引擎**的结论，不是另写一套。
        """
        return conflict_list(self.builtin, word, value,
                             custom_word_hits, custom_value_hits)

    def conflicts_for_add_many(self, pairs: Iterable[tuple[str, str]]) -> list[list[dict]]:
        """批量查重：与 `conflicts_for_add` 逐条同口径，返回每条一份冲突清单。

        预览要对成百上千条候选一次查重，逐条调 `conflicts_for_add` 会在自定义
        词库上反复全表扫（30 万条内置词库已改成索引查，自定义仍是线性）。
        这里只把「自定义词库的两个索引」建一次，判定交给
        :meth:`_conflicts_from_hits` —— 同一份实现，不存在第二套比对逻辑。
        """
        by_word: dict[str, list[dict]] = {}
        by_value: dict[str, list[dict]] = {}
        for e in self.custom.entries():
            by_word.setdefault(e["word"], []).append(e)
            by_value.setdefault(e["value"], []).append(e)
        out: list[list[dict]] = []
        for word, value in pairs:
            w, v = str(word or "").strip(), str(value or "").strip()
            out.append(self._conflicts_from_hits(w, v,
                                                 by_word.get(w, []),
                                                 by_value.get(v, [])))
        return out

    def dup_groups(self) -> list[dict]:
        """「我的词库」内部的重复，以及与内置词库撞车的条目。

        V1.1-EX.2R：**不再产出「同值异词」分组**（用户拍板）。两个不同的原词
        映射到同一个替换值，在替换阶段是可用的规则（引擎按原词匹配，替换值
        相同并不冲突），把它当重复会让用户去"合并"两条语义完全不同的词条。
        保留三类：

        * ``同词同值``（同一原词、同一替换值 → 真重复，可一键去重）
        * ``同词异值``（同一原词、不同替换值 → 必须选一条保留）
        * ``与内置冲突·<上述两类>``（自定义词条与内置词库同词）

        ``KIND_SAME_VALUE`` 常量仍保留：单条新增 / 批量导入的冲突提示里，
        「这条的原词和库里某条替换值撞了」依然需要告诉用户（那是提示，不是
        查重清单里的重复分组）。
        """
        groups: list[dict] = []
        entries = self.custom.entries()

        by_word: dict[str, list[dict]] = {}
        for e in entries:
            by_word.setdefault(e["word"], []).append(e)

        for w, arr in by_word.items():
            if len(arr) > 1:
                kinds = {KIND_SAME_BOTH if e["value"] == arr[0]["value"] else KIND_SAME_WORD for e in arr}
                kind = KIND_SAME_BOTH if kinds == {KIND_SAME_BOTH} else KIND_SAME_WORD
                groups.append(dict(kind=kind, key=w,
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

    def _begin(self, *, label: str, act: str, touches_builtin: bool = False,
               touches_words: bool = False) -> int:
        return self.snap.begin(
            label=label, act=act, before_bytes=self.custom.raw_bytes(),
            builtin_before=self.builtin.read_work_bytes() if touches_builtin else None,
            builtin_sha_before=self.builtin.combined_sha() if touches_builtin else "",
            words_before=self.states.raw_bytes() if touches_words else None)

    def _commit(self, pid: int, *, act: str, summary: str, sha_before: str,
                detail: dict | None = None,
                builtin_sha_before: str = "", builtin_sha_after: str = "",
                builtin_factory: bool = False,
                touches_words: bool = False) -> dict:
        rec = self.snap.commit(pid, after_bytes=self.custom.raw_bytes(),
                               builtin_after_is_factory=builtin_factory,
                               builtin_sha_after=builtin_sha_after,
                               words_after=self.states.raw_bytes() if touches_words else None)
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
             touches_builtin: bool = False, touches_words: bool = False,
             detail: dict | None = None) -> tuple[dict, dict]:
        """一次写操作的标准流程；写失败就把还原点撤掉，不留半截记录。"""
        sha_before = self._disk_sha()
        b_sha_before = self.builtin.combined_sha() if touches_builtin else ""
        pid = self._begin(label=label, act=act, touches_builtin=touches_builtin,
                          touches_words=touches_words)
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
                                             b_sha_after == self.builtin.factory_combined_sha()),
                            touches_words=touches_words)
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

    def merge_entries(self, ids: Iterable[int], target_word: str | None = None,
                      *, keep_id: int | None = None) -> dict:
        """合并同组词条（保留一条，其余移除）。

        ``keep_id`` 按 id 指定保留哪条（查重清单同词异值组的「选一保留」走这个），
        ``target_word`` 按原词指定（同词同值组里任一条等价）。整组只占一个还原点，
        撤销即整组回到原样。
        """
        ids = [int(i) for i in ids]
        label = f"合并 {len(ids)} 条重复词条"
        result, meta = self._run(
            label=label, act=ACT_MERGE, summary=label,
            write=lambda: self.custom.merge(ids, target_word, keep_id=keep_id),
            detail=dict(ids=ids, target=target_word,
                        keep_id=int(keep_id) if keep_id is not None else None))
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

    # ----- V1.1-D5：整批导入（事务写入 + 整批撤销）-----

    def import_batch(self, rows, *, label: str = "", source_name: str = "",
                     verify: bool = True) -> dict:
        """把一整批词条写进自定义词库（一个还原点、一次落盘、写完自证）。

        ``rows`` 就是预览页 ``write_list()`` 的输出（D4 的输入契约）。
        写失败抛 :class:`fixtext_vocab_preview.transaction.BatchWriteError`，
        且词库已退回导入前（或还原点留着可撤销），不会落半批。

        留痕全部复用既有那条路：还原点进 ``SnapshotStore``（历史面板可见）、
        操作历史用 ``ACT_IMPORT_BATCH``、撤销走 ``undo()`` / ``undo_to()``——
        本卡不另造撤销体系。
        """
        from fixtext_vocab_preview.transaction import write_batch

        return write_batch(self, rows, label=label, source_name=source_name,
                           verify=verify)

    def undo_import(self, point_id: int) -> dict | None:
        """整批撤销：一次把这一批导入退回导入前（复用既有撤销栈的两条原语）。"""
        from fixtext_vocab_preview.transaction import undo_batch

        return undo_batch(self, int(point_id))

    # ----- 词条启用 / 禁用（V1.1-T1.1 数据层；界面在第二卡接）-----

    def set_entries_enabled(self, pairs: Iterable, *, enabled: bool) -> dict:
        """批量启用 / 禁用词条（走撤销栈；``pairs`` 为 (word, value) 或字典列表）。

        界面第二卡的消费入口：勾选 / 取消勾选词条后调这里。
        返回 ``changed`` / ``unchanged`` / ``disabled_total`` / ``point_id``。
        """
        pairs = list(pairs)
        act = ACT_ENABLE if enabled else ACT_DISABLE
        n = len(pairs)
        label = (f"启用 {n} 条词条" if enabled else f"禁用 {n} 条词条") if n != 1 else None
        if n == 1:
            p0 = pairs[0]
            w = p0.get("word") if isinstance(p0, dict) else p0[0]
            label = f"启用「{w}」" if enabled else f"禁用「{w}」"
        result, meta = self._run(
            label=label, act=act, summary=label, touches_words=True,
            write=lambda: self.states.set_enabled(pairs, enabled=enabled),
            detail=dict(count=n, enabled=enabled))
        return dict(result, point_id=meta["point_id"], sha_after=meta["sha_after"])

    def clear_disabled_entries(self) -> dict:
        """「清空禁用」：禁用集置空——所有词条（含迁入 / 孤儿）全部启用。

        与「恢复默认状态」是两个独立操作（排期 7.4 定稿），各自可撤销。
        """
        result, meta = self._run(
            label="清空禁用", act=ACT_CLEAR_DISABLED, summary="清空禁用（全部词条启用）",
            touches_words=True, write=self.states.clear_disabled,
            detail=dict())
        return dict(result, point_id=meta["point_id"], sha_after=meta["sha_after"])

    def reset_word_states_default(self) -> dict:
        """「恢复默认状态」：禁用集恢复初始集（迁入 + 孤儿词条默认禁用）。

        注意与 :meth:`restore_default`（内置词库逐字节还原出厂）的区别：
        那个只管词库文件，这个只管启用 / 禁用状态，互不牵连。
        """
        result, meta = self._run(
            label="恢复默认状态", act=ACT_RESET_STATES,
            summary="恢复默认状态（迁入与孤儿词条默认禁用）",
            touches_words=True, write=self.states.reset_to_default,
            detail=dict())
        return dict(result, point_id=meta["point_id"], sha_after=meta["sha_after"])

    def entry_enabled(self, word: str, value: str) -> bool:
        """词条当前是否参与校正（数据层读接口，界面第二卡直接消费）。"""
        return not self.states.is_disabled(word, value)

    def set_rows_enabled(self, rows: Iterable[dict], *, enabled: bool) -> dict:
        """按行（dict 带 ``word`` / ``value``）批量改启用状态，走撤销栈。

        界面「选中后启用 / 禁用」与行内单个开关共用这一个入口——两条路径
        落的是同一份还原点、同一种操作历史文案，撤销行为完全一致。
        """
        pairs = [{"word": r["word"], "value": r.get("value", "")} for r in rows]
        return self.set_entries_enabled(pairs, enabled=enabled)

    def toggle_row_enabled(self, row: dict) -> dict:
        """单条词条的开关：已启用 → 禁用，已禁用 → 启用。"""
        on = self.entry_enabled(row["word"], row.get("value", ""))
        return self.set_rows_enabled([row], enabled=not on)

    def word_states_summary(self) -> dict:
        """启用 / 禁用状态的只读汇总（迁入数 / 禁用数 / 是否有用户区文件）。"""
        return self.states.summary()

    # ----- 按书词库（V1.1-C2；读写一律转调 C1 数据层，不另造第二套）-----

    def set_book(self, book_id: str) -> None:
        """记住「当前书」：按书排除都落在这本书自己的清单里。

        书 id 不合规（C1 的安全字符集之外）直接抛 :class:`VocabDataError`，
        由界面转成人话——绝不静默落到别的地方。
        """
        bid = str(book_id or "").strip()
        if not bid:
            self._book_id = ""
            return
        try:
            import fixtext_book_scope as _bscope

            bid = _bscope.normalize_book_id(bid)
        except Exception as exc:
            raise VocabDataError(f"这本书不能建按书清单（{type(exc).__name__}）") from exc
        self._book_id = bid

    def book_id(self) -> str:
        return self._book_id

    def _book_path_for(self, book_id: str = "") -> Path | None:
        """按书文件位置：``<词库根>/books/<书 id>/book_vocab.json``。

        默认（包内用户区）时它与管线侧 C1 推算的是同一个位置；显式指定
        自定义位置（测试 / 便携）时跟着那棵树走。空书 id 返回 ``None``。
        """
        bid = str(book_id or self._book_id or "").strip()
        if not bid or "/" in bid or "\\" in bid or bid in (".", ".."):
            return None
        return self.base_dir / "books" / bid / "book_vocab.json"

    def book_scope_info(self) -> dict:
        """读当前书的按书清单（C1 的 ``load_book_vocab``：坏文件降级不阻断）。"""
        import fixtext_book_scope as _bscope

        return _bscope.load(self._book_path_for())

    def book_scope_rows(self) -> list[dict]:
        """当前书排除清单的行（word / value / reason / key），供界面渲染。"""
        info = self.book_scope_info()
        rows: list[dict] = []
        for e in info.get("excluded") or []:
            rows.append(dict(word=str(e.get("word") or ""),
                             value=str(e.get("value") or ""),
                             reason=str(e.get("reason") or "")))
        return rows

    def _run_book(self, *, label: str, act: str, summary: str, write, detail: dict | None = None):
        """按书写操作的标准流程：与全局词库共用同一条还原点 / 操作历史。"""
        import fixtext_book_scope as _bscope

        p = self._book_path_for()
        if p is None:
            raise VocabDataError("还没有选中的书")
        before = _bscope.raw_bytes(p)
        pid = self.snap.begin(label=label, act=act, before_bytes=self.custom.raw_bytes(),
                              book_before=before, book_id=self._book_id)
        try:
            result = write()
        except Exception:
            self.snap.abort(pid)
            raise
        self.snap.commit(pid, after_bytes=self.custom.raw_bytes(),
                         book_after=_bscope.raw_bytes(p))
        self.snap.log_op(act=act, summary=summary, point_id=pid, detail=detail)
        return result, dict(point_id=pid)

    def set_book_excluded(self, word: str, value: str, *, excluded: bool,
                          reason: str = "") -> dict:
        """把一条词条加入 / 移出**当前书**的排除清单（走撤销栈）。

        ``excluded=True``：这本书不再校正这条词条（其余书不受影响）；
        ``excluded=False``：恢复参与，回到全局默认行为。
        幂等：状态没变时不写文件、不留还原点。
        """
        import fixtext_book_scope as _bscope

        word = str(word or "").strip()
        value = str(value or "").strip()
        if not word:
            raise VocabDataError("请填写原词")
        if not self._book_id:
            raise VocabDataError("还没有选中的书")
        p = self._book_path_for()
        info = _bscope.load(p)
        key = _bscope.key_of(word, value)
        already = key in info["excluded_keys"]
        if already == bool(excluded):
            return dict(changed=False, point_id=0, excluded=already,
                        count=len(info.get("excluded") or []), book_id=self._book_id)
        pairs = _bscope.excluded_pairs(info)
        label = f"本书{'停用' if excluded else '恢复'}「{word}」"

        def _write() -> dict:
            if excluded:
                new_pairs = list(pairs) + [(word, value)]
            else:
                new_pairs = [(w, v) for (w, v) in pairs
                             if _bscope.key_of(w, v) != key]
            return _bscope.write_excluded(p, self._book_id, new_pairs, reason=reason)

        result, meta = self._run_book(
            label=label, act=(ACT_BOOK_EXCLUDE if excluded else ACT_BOOK_INCLUDE),
            summary=label, write=_write,
            detail=dict(word=word, value=value, excluded=bool(excluded),
                        book_id=self._book_id))
        return dict(changed=True, point_id=meta["point_id"], excluded=bool(excluded),
                    count=int(result.get("count") or 0), book_id=self._book_id,
                    sha_after=result.get("sha256") or "")

    def _restore_book_bytes(self, book_id: str, raw: bytes) -> None:
        """把某本书的按书文件写回 ``raw``（空字节 = 当初不存在 → 删掉）。"""
        import fixtext_book_scope as _bscope

        p = self._book_path_for(book_id)
        if p is None:
            return
        _bscope.restore_bytes(p, raw)

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
        words = self.snap.words_before(pid)
        if words is not None:
            self.states.restore(words)
        book = self.snap.book_before(pid)
        if book is not None:
            # 按书清单的还原点自己记着属于哪本书——撤销发生在切书之后
            # 也写回当初那本书，绝不污染当前书。
            self._restore_book_bytes(str(p.get("book_id") or ""), book)
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
        words = self.snap.words_before(pid)
        if words is not None:
            self.states.restore(words)
        book = self.snap.book_before(pid)
        if book is not None:
            self._restore_book_bytes(str(row.get("book_id") or ""), book)
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
        words = self.snap.words_after(pid)
        if words is not None:
            self.states.restore(words)
        book = self.snap.book_after(pid)
        if book is not None:
            self._restore_book_bytes(str(p.get("book_id") or ""), book)
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
