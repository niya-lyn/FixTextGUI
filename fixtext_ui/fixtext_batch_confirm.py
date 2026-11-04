"""V1.1-E4 · 逐批确认与每批备份（数据层，无 Qt 依赖）
=================================================================

排期文档 §10.5 的两条交付物都靠这里兜底：

1. **索引 / 范围批量选择与「执行 / 跳过」交互**——按规则原序号（``Rule.index``）
   或一段序号范围挑选规则，再按「每批几条规则」切成分批清单，逐批可执行 / 跳过；
2. **每批替换前的备份与确认**——执行一批之前，把该批替换**前**的正文整份字节
   存进既有的还原点仓库（:class:`fixtext_snapshot.SnapshotStore`），并校验一次性
   确认凭证（``token``）后才允许落盘。

三条验收判据在这里是硬的
------------------------
* **未经确认不得落盘**：真正写文件的那个函数（``writer``）只可能在
  :meth:`BatchSession.execute` / :meth:`BatchSession.undo` 的末尾被调用一次，
  而这两个方法进门先查凭证。凭证由 :meth:`preview` / :meth:`prepare_undo` 签发，
  并对「签发时的正文指纹」做绑定——正文在别处被改过（指纹不符）时凭证作废，
  抛 :class:`StalePreview`，绝不拿过期预览去写盘。
* **跳过可回退**：跳过只改状态、不写盘（回退 = :meth:`resume_skip` 把这一批
  放回待执行，磁盘一个字节都没动过）。
* **每批可单独撤销**：已执行的任何一批都能单独撤回，不要求它是最后一批。
  撤回的做法是「从会话起始正文重放其余已执行批次」——逐批结果可复现，
  并且与那一批的备份字节交叉核对（对不上就如实报 ``mismatch``，不强行挑一边）。

为什么撤销要重放而不是只回写备份
--------------------------------
逐批执行是不连续的：先执行第 3 批、再执行第 1 批是允许的（界面按批序提示，
但不强制）。若只回写「某一批的备份」，就把在它之后执行的批次一起抹掉了。
重放法对任意一批都成立：``起始正文 → 按执行顺序逐批套用（跳过被撤的那批）``，
等于「把这批的改动摘掉、其余照旧」。只有被撤的那批是最后一批时，
重放结果才与它的备份逐字节相同——这时额外做一次核对，把「备份真的能还原」
这条也一并验掉。

与既有模块的关系
----------------
* 规则执行完全复用 ``fixtext_manual_search``（:class:`RuleSet` / ``Rule``），
  本模块不重新实现任何替换语义；
* 备份 / 还原点复用 ``fixtext_snapshot.SnapshotStore``（词库撤销用的同一个仓库），
  不另造一套快照格式；
* 本模块不写死任何界面文案，也不 import Qt——界面层（``manual_module.py``）
  只调用这里的公开方法。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from fixtext_manual_search import Rule, RuleSet, ScanResult
from fixtext_snapshot import SnapshotStore

# ---------------------------------------------------------------------------
# 状态名（界面只按这里的常量判断，不写字面量）
# ---------------------------------------------------------------------------

ST_PENDING = "pending"        # 待执行（还没预览 / 或预览作废）
ST_PREVIEWED = "previewed"    # 已预览，凭证在手，可执行
ST_EXECUTED = "executed"      # 已执行并落盘
ST_SKIPPED = "skipped"        # 已跳过（未落盘）

#: 备份目录名（放在书目录下，跟既有用户区同一个层级，不藏进系统目录）
BACKUP_DIRNAME = "batch_backups"

#: 一批最多给几个「改前 → 改后」示例（多了界面装不下，也不影响判据）
MAX_SAMPLES = 3

#: 示例上下文前后各取多少字符
SAMPLE_PAD = 24


class BatchError(RuntimeError):
    """本模块的业务错误：一律带人话原因，界面直接显示。"""


class ConfirmationRequired(BatchError):
    """没有有效确认凭证就想落盘——这条路径必须拦住，不能"先写再说"。"""

    def __init__(self, batch_id: int, reason: str):
        super().__init__(f"第 {batch_id} 批未经确认，不能写入：{reason}")


class StalePreview(BatchError):
    """凭证对应的正文已经不是当前正文了（中间有人改过），预览作废。"""

    def __init__(self, batch_id: int):
        super().__init__(f"第 {batch_id} 批的预览已过期（正文在预览之后被改过），请重新预览确认")


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------

def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_write(path: Path, raw: bytes) -> None:
    """原子写：同目录临时文件 → fsync → replace → fsync 目录（Unix）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".batch-", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        # Windows 不允许把目录当文件打开（os.open(目录) 抛 PermissionError），
        # 这一步失败会把已经成功的写入报成失败，所以只在类 Unix 上做。
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


def _now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


# ---------------------------------------------------------------------------
# 批次
# ---------------------------------------------------------------------------

@dataclass
class Batch:
    """一批规则（批号从 1 开始，等于它在当前计划里的执行位次）。"""

    batch_id: int
    rules: tuple[Rule, ...]
    hits: int                    # 计划时这批评到的命中处数（扫描口径）
    state: str = ST_PENDING
    reason: str = ""             # 跳过原因（可空）
    #: 这一批的编号（跨重排稳定：重排批次后旧编号作废，界面据此提示）
    plan_epoch: int = 0

    @property
    def rule_indices(self) -> tuple[int, ...]:
        return tuple(r.index for r in self.rules)

    @property
    def marks(self) -> tuple[str, ...]:
        return tuple(r.mark for r in self.rules)

    @property
    def first_index(self) -> int:
        return self.rule_indices[0] if self.rules else 0

    @property
    def last_index(self) -> int:
        return self.rule_indices[-1] if self.rules else 0

    def label(self) -> str:
        """人话标题：单条规则直说，多条给序号区间。"""
        if not self.rules:
            return f"第 {self.batch_id} 批（空）"
        if len(self.rules) == 1:
            return f"第 {self.batch_id} 批 · 序号 {self.first_index}"
        return (f"第 {self.batch_id} 批 · 序号 {self.first_index}–{self.last_index}"
                f"（{len(self.rules)} 条）")


@dataclass
class BatchPreview:
    """一次预览的结果：执行这批会变成什么样，以及一次性确认凭证。"""

    batch_id: int
    token: str
    hits: int                              # 这批规则在**当前正文**上的命中处数
    changed_chars: int                     # 按「前后剥共同部分」估的改动块数（展示用）
    samples: list[tuple[str, str]] = field(default_factory=list)
    sha_before: str = ""
    sha_after: str = ""
    new_text: str = ""                     # 预览出的正文（不落盘，仅供界面比对）

    def as_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "token": self.token,
            "hits": self.hits,
            "changed_chars": self.changed_chars,
            "samples": list(self.samples),
            "sha_before": self.sha_before,
            "sha_after": self.sha_after,
        }


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------

class BatchSession:
    """一本书的一次逐批替换过程。

    生命周期::

        s = BatchSession(rs, text, target_path=book_path)
        s.scan()                        # 只统计，不落盘
        s.select_range(0, 60)          # 按规则序号范围挑选
        s.plan(chunk=1)                # 切批
        pv = s.preview(1)              # 预览第 1 批（签发凭证）
        s.execute(1, pv.token)         # 备份 → 校验凭证 → 落盘
        s.undo(1, s.prepare_undo(1))   # 单独撤回第 1 批

    ``writer`` 是**唯一**的落盘出口：默认原子写 ``target_path``；测试可以换成一个
    计数用的假函数，用来证明「未经确认一次都没调用过」。
    """

    def __init__(
        self,
        ruleset: RuleSet,
        text: str,
        *,
        target_path: str | Path | None = None,
        store: SnapshotStore | None = None,
        store_dir: str | Path | None = None,
        label: str = "",
        writer: Callable[[str], None] | None = None,
    ) -> None:
        self.ruleset = ruleset
        self.base_text = text
        self.text = text
        self.target_path = str(target_path) if target_path else ""
        self.label = str(label or "")
        self._writer = writer
        self._external_writer = writer is not None

        if store is not None:
            self.store = store
        else:
            if store_dir is None:
                if not self.target_path:
                    raise BatchError("没有书目录，不能建备份")
                store_dir = Path(self.target_path).parent / BACKUP_DIRNAME
            self.store = SnapshotStore(store_dir)

        self.scan_result: ScanResult | None = None
        self.selected: list[int] = []
        self.batches: list[Batch] = []
        self.chunk = 1
        self._epoch = 0
        self._previews: dict[int, BatchPreview] = {}
        self._undo_tokens: dict[int, str] = {}
        self.applied_order: list[int] = []
        self._points: dict[int, dict[str, Any]] = {}
        self.written_once = False

    # -- 落盘出口 ---------------------------------------------------------

    def _write_text(self, text: str) -> None:
        """唯一的落盘出口：不在这里之外调用任何写文件。"""
        self.written_once = True
        if self._writer is not None:
            self._writer(text)
            return
        if not self.target_path:
            raise BatchError("这本书没有可写回的正文路径")
        _atomic_write(Path(self.target_path), text.encode("utf-8"))
        self.written_once = True

    # -- 扫描与挑选 -------------------------------------------------------

    def scan(self) -> ScanResult:
        """统计每条规则在当前正文上的命中数（只读）。"""
        self.scan_result = self.ruleset.scan(self.text)
        return self.scan_result

    def hits_of(self, index: int) -> int:
        if self.scan_result is None:
            self.scan()
        assert self.scan_result is not None
        for h in self.scan_result.hits:
            if h.rule.index == index:
                return h.count
        raise IndexError(f"规则序号越界：{index}")

    def nonzero_indices(self) -> list[int]:
        if self.scan_result is None:
            self.scan()
        assert self.scan_result is not None
        return [h.rule.index for h in self.scan_result.hits if h.count]

    def select_indices(self, indices: Sequence[int]) -> list[int]:
        """按规则原序号挑选（去重、按原表顺序排好，顺序是执行语义的一部分）。"""
        n = len(self.ruleset)
        picked = sorted({int(i) for i in indices if 0 <= int(i) < n})
        self.selected = picked
        self._invalidate_plan()
        return list(picked)

    def select_range(self, start: int, stop: int, *, nonzero_only: bool = False) -> list[int]:
        """按序号区间挑选（含 ``stop``，闭区间；``stop`` 可以大于最大序号）。"""
        n = len(self.ruleset)
        lo = max(0, int(start))
        hi = min(n - 1, int(stop))
        if hi < lo:
            self.selected = []
            self._invalidate_plan()
            return []
        idx = list(range(lo, hi + 1))
        if nonzero_only:
            alive = set(self.nonzero_indices())
            idx = [i for i in idx if i in alive]
        self.selected = idx
        self._invalidate_plan()
        return list(idx)

    def select_all_hits(self, *, limit: int | None = None) -> list[int]:
        """选中全部有命中的规则（可选只取前 ``limit`` 条）。"""
        idx = self.nonzero_indices()
        if limit is not None:
            idx = idx[: max(0, int(limit))]
        self.selected = idx
        self._invalidate_plan()
        return list(idx)

    def clear_selection(self) -> None:
        self.selected = []
        self._invalidate_plan()

    # -- 切批 -------------------------------------------------------------

    def _invalidate_plan(self) -> None:
        """挑选变了 → 旧批次与旧凭证全部作废（凭证绑定批次，不能跨计划复用）。"""
        self.batches = []
        self._previews.clear()
        self._undo_tokens.clear()
        self._epoch += 1

    def plan(self, chunk: int = 1) -> list[Batch]:
        """把已选规则按每批 ``chunk`` 条切成批次（按规则原序号顺序）。"""
        self.chunk = max(1, int(chunk))
        rules = [self.ruleset.get(i) for i in self.selected]
        batches: list[Batch] = []
        for k in range(0, len(rules), self.chunk):
            group = tuple(rules[k:k + self.chunk])
            hits = sum(self.hits_of(r.index) for r in group)
            batches.append(Batch(batch_id=len(batches) + 1, rules=group,
                                 hits=hits, plan_epoch=self._epoch))
        self.batches = batches
        self._previews.clear()
        self._undo_tokens.clear()
        return list(batches)

    def batch(self, batch_id: int) -> Batch:
        for b in self.batches:
            if b.batch_id == int(batch_id):
                return b
        raise BatchError(f"没有第 {batch_id} 批（当前计划共 {len(self.batches)} 批）")

    # -- 预览 -------------------------------------------------------------

    def _compose(self, batch_ids: Sequence[int]) -> str:
        """从起始正文重放给定批次（按给出的顺序），返回新正文。"""
        text = self.base_text
        for bid in batch_ids:
            for rule in self.batch(bid).rules:
                text = self.ruleset.apply_rule(rule, text)
        return text

    @staticmethod
    def _diff_blocks(before: str, after: str) -> int:
        """改动块数（剥共同前后缀后的残段数，展示口径）。"""
        if before == after:
            return 0
        lo = 0
        limit = min(len(before), len(after))
        while lo < limit and before[lo] == after[lo]:
            lo += 1
        hi_b, hi_a = len(before), len(after)
        while hi_b > lo and hi_a > lo and before[hi_b - 1] == after[hi_a - 1]:
            hi_b -= 1
            hi_a -= 1
        return 1 if (hi_b > lo or hi_a > lo) else 0

    def _samples(self, batch: Batch, text: str) -> list[tuple[str, str]]:
        """取前几处「改前 → 改后」示例（真实匹配位置，带上下文截取）。

        说明：截取片段是为了界面上看得见；片段两侧留了 ``SAMPLE_PAD`` 个字符，
        足以让规则依赖的前后文成立。真正落盘的内容永远是**全文**套用结果
        （``preview`` / ``execute`` 用的都是全文，不是片段），示例只用于判断。
        """
        out: list[tuple[str, str]] = []
        for rule in batch.rules:
            if len(out) >= MAX_SAMPLES:
                break
            try:
                pat = self.ruleset.compiled(rule)
            except Exception:                          # noqa: BLE001 - 编译失败由 E3 校验登记
                continue
            found = 0
            for m in pat.finditer(text):
                if found >= MAX_SAMPLES - len(out):
                    break
                found += 1
                start = max(0, m.start() - SAMPLE_PAD)
                end = min(len(text), m.end() + SAMPLE_PAD)
                snippet = text[start:end]
                local = pat.sub(self._replacement(rule), snippet)
                out.append((snippet, local))
        return out

    @staticmethod
    def _replacement(rule: Rule) -> Any:
        """取规则的替换物（模板或回调），与 RuleSet._apply 同口径。"""
        from fixtext_manual_search import CALLBACKS   # noqa: PLC0415 - 同包内常量

        if rule.is_callback:
            fn = CALLBACKS.get(rule.callback_id or "")
            if fn is None:
                raise BatchError(f"规则 {rule.mark} 的回调实现缺失（拒绝静默降级）")
            return fn
        return rule.template() or ""

    def preview(self, batch_id: int) -> BatchPreview:
        """只读预览某一批，并签发一次性确认凭证（**不落盘**）。"""
        b = self.batch(batch_id)
        if b.state == ST_EXECUTED:
            raise BatchError(f"第 {batch_id} 批已经执行过了")
        before = self.text
        after = before
        for rule in b.rules:
            after = self.ruleset.apply_rule(rule, after)
        sha_before = sha256_bytes(before.encode("utf-8"))
        sha_after = sha256_bytes(after.encode("utf-8"))
        token = uuid.uuid4().hex
        pv = BatchPreview(
            batch_id=b.batch_id,
            token=token,
            hits=sum(sum(1 for _ in self.ruleset.compiled(r).finditer(before)) for r in b.rules),
            changed_chars=self._diff_blocks(before, after),
            samples=self._samples(b, before),
            sha_before=sha_before,
            sha_after=sha_after,
            new_text=after,
        )
        self._previews[b.batch_id] = pv
        b.state = ST_PREVIEWED
        b.reason = ""
        self._undo_tokens.pop(b.batch_id, None)
        return pv

    # -- 跳过 / 回退 -------------------------------------------------------

    def skip(self, batch_id: int, reason: str = "") -> Batch:
        """跳过这一批：只改状态，**不写盘**（回退见 :meth:`resume_skip`）。"""
        b = self.batch(batch_id)
        if b.state == ST_EXECUTED:
            raise BatchError(f"第 {batch_id} 批已经执行，不能跳过（要撤请用撤销）")
        b.state = ST_SKIPPED
        b.reason = str(reason or "")
        self._previews.pop(b.batch_id, None)
        return b

    def resume_skip(self, batch_id: int) -> Batch:
        """跳过回退：这一批回到待执行，磁盘未被动过。"""
        b = self.batch(batch_id)
        if b.state != ST_SKIPPED:
            raise BatchError(f"第 {batch_id} 批不是跳过状态，无需回退")
        b.state = ST_PENDING
        b.reason = ""
        return b

    # -- 执行 -------------------------------------------------------------

    @staticmethod
    def _text_sha(path: str) -> str:
        try:
            return sha256_bytes(Path(path).read_bytes())
        except OSError:
            return ""

    def _check_gate(self, batch_id: int, token: str | None) -> BatchPreview:
        """进门检查：凭证存在、属于这一批、与当前正文指纹一致，且状态允许。"""
        b = self.batch(batch_id)
        if b.plan_epoch != self._epoch:
            raise StalePreview(b.batch_id)
        pv = self._previews.get(b.batch_id)
        if not token or pv is None or token != pv.token:
            raise ConfirmationRequired(b.batch_id, "缺少这一批的预览确认")
        if b.state != ST_PREVIEWED:
            raise ConfirmationRequired(b.batch_id, "这一批不处于待执行状态")
        if sha256_bytes(self.text.encode("utf-8")) != pv.sha_before:
            self._previews.pop(b.batch_id, None)
            b.state = ST_PENDING
            raise StalePreview(b.batch_id)
        # 磁盘正文也要与预览时的正文一致：被别人改过就不能拿旧预览写
        if self.target_path and not self._external_writer:
            disk = self._text_sha(self.target_path)
            if disk and disk != pv.sha_before:
                self._previews.pop(b.batch_id, None)
                b.state = ST_PENDING
                raise StalePreview(b.batch_id)
        return pv

    def execute(self, batch_id: int, token: str | None, *, detail: str = "") -> dict[str, Any]:
        """执行这一批：先备份再落盘（备份失败则整批不写）。"""
        b = self.batch(batch_id)
        pv = self._check_gate(batch_id, token)
        before_raw = self.text.encode("utf-8")
        label = self.label or "当前书"
        pid = self.store.begin(
            label=f"{label} · {b.label()}",
            act="batch_replace",
            before_bytes=before_raw,
        )
        try:
            self._write_text(pv.new_text)
        except Exception as exc:                        # noqa: BLE001 - 写失败要留证据
            # 写失败：撤掉这个还原点，不留半截记录；状态回到待执行，凭证作废
            self.store.abort(pid)
            self._previews.pop(b.batch_id, None)
            b.state = ST_PENDING
            raise BatchError(f"第 {batch_id} 批写回失败：{type(exc).__name__}") from exc

        rec = self.store.commit(pid, after_bytes=pv.new_text.encode("utf-8"))
        self.text = pv.new_text
        b.state = ST_EXECUTED
        b.reason = ""
        if b.batch_id not in self.applied_order:
            self.applied_order.append(b.batch_id)
        self._points[b.batch_id] = {
            "point_id": pid,
            "sha_before": rec.get("sha_before", pv.sha_before),
            "sha_after": rec.get("sha_after", pv.sha_after),
            "hits": pv.hits,
            "at": _now_text(),
            # 执行这一批**当时**的已执行序列：撤销要拿它判断「备份能不能逐字节核对」
            "prefix": list(self.applied_order),
        }
        self._previews.pop(b.batch_id, None)
        self.store.log_op(
            act="batch_replace",
            summary=f"执行 {b.label()}（{pv.hits} 处）{('：' + detail) if detail else ''}",
            point_id=pid,
            sha_before=rec.get("sha_before", ""),
            sha_after=rec.get("sha_after", ""),
            detail={"batch": b.batch_id, "rules": list(b.rule_indices), "hits": pv.hits},
        )
        return {
            "batch_id": b.batch_id,
            "point_id": pid,
            "hits": pv.hits,
            "sha_before": rec.get("sha_before", ""),
            "sha_after": rec.get("sha_after", ""),
            "text": self.text,
        }

    # -- 撤销 -------------------------------------------------------------

    def _text_without(self, batch_id: int) -> str:
        """把某一批从「已执行序列」里摘掉后重放，得到应恢复成正的文字。"""
        rest = [b for b in self.applied_order if b != int(batch_id)]
        return self._compose(rest)

    def prepare_undo(self, batch_id: int) -> str:
        """为撤销签发凭证（撤销同样会写盘，因此同样要确认）。"""
        b = self.batch(batch_id)
        if b.state != ST_EXECUTED:
            raise BatchError(f"第 {batch_id} 批没有执行过，没有可撤销的改动")
        token = uuid.uuid4().hex
        self._undo_tokens[b.batch_id] = token
        return token

    def undo(self, batch_id: int, token: str | None) -> dict[str, Any]:
        """单独撤销某一批（不要求它是最后一批）。"""
        b = self.batch(batch_id)
        want = self._undo_tokens.get(b.batch_id)
        if not token or want is None or token != want:
            raise ConfirmationRequired(b.batch_id, "缺少这一批的撤销确认")
        if b.state != ST_EXECUTED:
            raise BatchError(f"第 {batch_id} 批当前不在已执行状态")
        target = self._text_without(b.batch_id)
        target_sha = sha256_bytes(target.encode("utf-8"))
        point = self._points.get(b.batch_id) or {}

        # 交叉核对只在「能核对」的时候做：这一批的备份是**它执行当时**那条线上的
        # 正文——若之后又撤过更早的批次，当前这条线已经不同，备份本来就不该等于
        # 重放结果（那是正常状态，不是不一致）。判断条件是「剩下的已执行批次
        # 恰好等于该批执行时的前缀再减去它自己」，此时重放结果必须与备份
        # 逐字节相同；对不上就是真的不一致，如实报出来。
        rest = [x for x in self.applied_order if x != b.batch_id]
        prefix = [int(x) for x in (point.get("prefix") or [])]
        mismatch = ""
        backup_exact = False
        if prefix and rest == prefix[:-1]:
            backup = self.store.before_bytes(int(point.get("point_id", 0))) \
                if point.get("point_id") else None
            if backup is not None:
                backup_exact = True
                if sha256_bytes(backup) != target_sha:
                    mismatch = "重放结果与该批备份不一致"

        cur_raw = self.text.encode("utf-8")
        pid = self.store.begin(
            label=f"{self.label or '当前书'} · 撤销 {b.label()}",
            act="batch_undo",
            before_bytes=cur_raw,
        )
        try:
            self._write_text(target)
        except Exception as exc:                        # noqa: BLE001
            self.store.abort(pid)
            raise BatchError(f"第 {batch_id} 批撤销写回失败：{type(exc).__name__}") from exc
        rec = self.store.commit(pid, after_bytes=target.encode("utf-8"))

        self.text = target
        b.state = ST_PENDING
        if b.batch_id in self.applied_order:
            self.applied_order.remove(b.batch_id)
        self._undo_tokens.pop(b.batch_id, None)
        if point.get("point_id"):
            self.store.mark_undone(int(point["point_id"]), True)
            self._points.pop(b.batch_id, None)
        self.store.log_op(
            act="batch_undo",
            summary=f"撤销 {b.label()}",
            point_id=pid,
            sha_before=rec.get("sha_before", ""),
            sha_after=rec.get("sha_after", ""),
            detail={"batch": b.batch_id, "mismatch": mismatch},
        )
        return {
            "batch_id": b.batch_id,
            "point_id": pid,
            "sha_before": rec.get("sha_before", ""),
            "sha_after": rec.get("sha_after", ""),
            "mismatch": mismatch,
            "backup_exact": backup_exact,
            "text": self.text,
        }

    def last_executed(self) -> int | None:
        """最后执行的批号（没有则为 ``None``）；界面据此决定「撤销上一批」按钮。"""
        return self.applied_order[-1] if self.applied_order else None

    def undo_last(self, token: str | None = None) -> dict[str, Any]:
        """撤销最后执行的那一批。凭证仍须由 :meth:`prepare_undo` 先签发。

        不做「自动签发并立刻消费」——那等于没有确认关口，撤销一样会写盘。
        """
        bid = self.last_executed()
        if bid is None:
            raise BatchError("还没有执行过任何批次，没有可撤销的改动")
        return self.undo(bid, token)

    # -- 只读状态 ---------------------------------------------------------

    def backups(self, *, limit: int | None = 60) -> list[dict[str, Any]]:
        """本会话产生的备份点（最新在前），只给界面需要的字段。"""
        rows = []
        mine = {int(v.get("point_id", 0)) for v in self._points.values()}
        for p in self.store.points(limit=limit):
            if int(p["id"]) in mine or p.get("act") in ("batch_replace", "batch_undo"):
                rows.append(dict(
                    point_id=int(p["id"]),
                    label=str(p.get("label", "")),
                    act=str(p.get("act", "")),
                    at=str(p.get("at", "")),
                    time=str(p.get("time", "")),
                    undone=bool(p.get("undone")),
                    sha_before=str(p.get("sha_before", "")),
                    sha_after=str(p.get("sha_after", "")),
                ))
        return rows

    def summary(self) -> dict[str, Any]:
        counts = {ST_PENDING: 0, ST_PREVIEWED: 0, ST_EXECUTED: 0, ST_SKIPPED: 0}
        for b in self.batches:
            counts[b.state] = counts.get(b.state, 0) + 1
        return {
            "rules": len(self.ruleset),
            "selected": len(self.selected),
            "batches": len(self.batches),
            "chunk": self.chunk,
            "scanned_chars": len(self.text),
            "total_hits": int(self.scan_result.total) if self.scan_result else 0,
            "hit_rules": len(self.nonzero_indices()) if self.scan_result else 0,
            "states": counts,
            "executed_batches": list(self.applied_order),
            "written": bool(self.written_once),
        }
