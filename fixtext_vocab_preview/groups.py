"""V1.1-D3 · 导入预览分组：新增 N / 冲突 M / 格式不合格 K。

本包只做**分组与取消**这两件事（§9.5 交付物 ①），不做冲突处置（D4）、
不做写入与撤销（D5）、不导出（D7）。它是**只读**的：整条链路不对用户真实
词库落盘，预演核对也只写词库文件的临时副本。

三组的来源各不相同，刻意不互相替代：

* **格式不合格 K** —— 直接取 D2 的 `RejectList`。不重算原因分类：
  那一层已经把 6 类原因、行号口径、条数守恒都钉住了，这里再判一次
  就会长出第二套口径，两边迟早不一致。
* **冲突 M** —— 必须来自既有查重实现（`fixtext_ui/fixtext_vocab.py` 的
  `conflict_list` / `exact_word` / `exact_value`，三种形态常量
  `KIND_SAME_BOTH` / `KIND_SAME_WORD` / `KIND_SAME_VALUE`）。这里**没有**
  一行自己的比对逻辑：命中的自定义条目和内置条目都交给同一个
  `conflict_list` 判定，与「新增前查重」是同一份实现。
* **新增 N** —— 剩下那些既合格、又查不出冲突的。

## 为什么"分批"要在这层出现

预览要让用户知道「按当前口径会分成几批」——但这个数字必须与真导入同源，
否则预览说 2 批、真导入切成 3 批。所以分批一律走 D2 的 `plan_batches`，
本层只声明，不自己算批大小。

## 为什么"同一份表里重复出现"算冲突而不是新增

表里第 5 行和第 40 行写得一模一样时，两条都"库里没有"，但只能进去一条。
如果预览把两条都算成新增，用户的账就是「预览说 N、写入变 N-1」——正是
验收判据点名要防的那类偏差。所以本层按**行序**递进查重：先出现的算新增，
后出现的算与「本次将要写入的前一条」冲突（`within_batch` 为 True）。
这个递进用的仍是既有查重实现的判定，只是把"将要写入的条目"也当成已被命中的一方。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from fixtext_vocab_import.batching import BatchPlan, BatchPolicy, plan_batches
from fixtext_vocab_import.rejects import RejectList, RejectedRow

from . import messages as msg

__all__ = [
    "GROUP_NEW",
    "GROUP_CONFLICT",
    "GROUP_REJECT",
    "GROUP_NAMES",
    "PreviewItem",
    "PreviewModel",
    "preview_from_sheet",
]

GROUP_NEW = msg.GROUP_NEW
GROUP_CONFLICT = msg.GROUP_CONFLICT
GROUP_REJECT = msg.GROUP_REJECT
GROUP_NAMES = msg.GROUP_NAMES

#: 「同一次导入里前面已经出现」的命中用这个 id。真实自定义词条的 id 从 1 起
#: （`CustomVocab.add` 取 `max(default=0)+1`），所以 0 不可能与真条目相撞。
_PENDING_ID = 0


@dataclass
class PreviewItem:
    """预览里的一行：分组结论 + 依据 + 能否取消后的状态。"""

    line_no: int                       # 原始行号（与 D1/D2 同口径，1 起）
    group: str                         # GROUP_NEW / GROUP_CONFLICT / GROUP_REJECT
    word: str = ""
    value: str = ""
    typ: str = ""
    pinyin: str = ""
    raw_line: str = ""
    #: 查重引擎给出的命中（仅冲突组非空）。每项含 kind / word / value / where / id。
    conflicts: list[dict] = field(default_factory=list)
    #: 冲突是不是「与本次导入里前面的某一条」撞车（不是与库里已有条目撞车）
    within_batch: bool = False
    #: 不合格原因的三段人话（仅不合格组非空）：分类 / 怎么改 / 补充说明
    reject_label: str = ""
    reject_advice: str = ""
    reject_note: str = ""
    cancelled: bool = False            # 用户取消过（取消后不进任何一组）

    # ----- 展示用 -----

    @property
    def kinds(self) -> list[str]:
        """这一条撞了哪几种形态（去重、保持引擎给出的顺序）。"""
        out: list[str] = []
        for c in self.conflicts:
            k = c.get("kind", "")
            if k and k not in out:
                out.append(k)
        return out

    @property
    def where_text(self) -> str:
        """冲突来自哪里（人话，最多列三处，不把命中全铺开）。"""
        names: list[str] = []
        for c in self.conflicts:
            where = "本次导入的前一条" if c.get("id") == _PENDING_ID else c.get("where", "")
            if where and where not in names:
                names.append(where)
        if not names:
            return ""
        if len(names) <= 3:
            return "、".join(names)
        return "、".join(names[:3]) + f" 等 {len(names)} 处"

    def label(self) -> str:
        """这一行为什么落在这个组（一行字，界面表格直接用）。"""
        if self.group == GROUP_REJECT:
            return self.reject_label
        if self.group == GROUP_CONFLICT:
            kinds = "、".join(self.kinds) or "与已有词条撞车"
            head = f"{kinds}"
            if self.within_batch:
                head += "（同一份表里前面已经有一条一样的）"
            where = self.where_text
            return head + (f"，来自{where}" if where else "")
        return "库里还没有，可以新增"

    def as_row(self) -> list[str]:
        """界面表格的一行：行号 / 错词 / 正确写法 / 说明。"""
        return [str(self.line_no), self.word, self.value, self.label()]


class PreviewModel:
    """一次导入的预览：三组条目 + 逐条取消 + 分批声明。

    **只读**：模型内部只读词库（走 `VocabStore` 的查重接口），不写任何文件。
    """

    def __init__(self, rejects: RejectList, store, policy: BatchPolicy | None = None,
                 *, raw_text: str = ""):
        self.rejects = rejects
        self.store = store
        self.policy = policy or BatchPolicy()
        #: 原文（行号 → 该行原文要用它，行号口径与 D1/D2 一致：物理行、1 起算）
        self.raw_text = raw_text or ""
        self._items: list[PreviewItem] = []
        self._cancelled: set[int] = set()      # 按原始行号记取消
        self.internal_duplicates = 0           # 同表内撞车的条数（自检用）
        self._build()

    # ----- 构建 -----

    def _base_indexes(self) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
        """自定义词库的两个索引（只是把已有条目按词 / 按值归位，不做判定）。"""
        by_word: dict[str, list[dict]] = {}
        by_value: dict[str, list[dict]] = {}
        for e in self.store.custom.entries():
            by_word.setdefault(e["word"], []).append(e)
            by_value.setdefault(e["value"], []).append(e)
        return by_word, by_value

    def _build(self) -> None:
        """把 D2 的分区结果按行序做成三组；引擎判定逐条递进（见模块头注释）。"""
        from fixtext_vocab import conflict_list   # 既有查重的唯一判定实现

        by_word, by_value = self._base_indexes()
        pending_word: dict[str, list[dict]] = {}
        pending_value: dict[str, list[dict]] = {}
        items: list[PreviewItem] = []

        # 不合格行先按行号归位（它们不参与查重，也不进批）
        reject_by_line = {r.line_no: r for r in self.rejects.rejects}
        order = sorted({row.line_no for row in self.rejects.good} | set(reject_by_line))

        good_by_line = {row.line_no: row for row in self.rejects.good}
        internal_dups = 0

        for line_no in order:
            rej = reject_by_line.get(line_no)
            if line_no in self._cancelled:
                # 取消掉的行**不参与查重递进**：它既不进任何一组，也不再占着
                # 「前面已经有一条」的位置。否则取消前一条、后一条仍被判成冲突，
                # 而真导入时那条会被写进去——预览数字就与实际结果对不上了。
                items.append(self._cancelled_item(line_no, rej))
                continue
            if rej is not None:
                items.append(self._from_reject(rej))
                continue

            row = good_by_line[line_no]
            word, value = row.word, row.value
            hits_w = list(by_word.get(word, [])) + list(pending_word.get(word, []))
            hits_v = list(by_value.get(value, [])) + list(pending_value.get(value, []))
            conflicts = conflict_list(self.store.builtin, word, value, hits_w, hits_v)

            within = any(c.get("id") == _PENDING_ID for c in conflicts)
            item = PreviewItem(
                line_no=line_no, group=GROUP_CONFLICT if conflicts else GROUP_NEW,
                word=word, value=value, typ=row.typ, pinyin=row.pinyin,
                raw_line=self._raw_of(line_no),
                conflicts=list(conflicts), within_batch=within,
            )
            if conflicts:
                if within:
                    internal_dups += 1
            else:
                # 将要写入的条目也当成"已在库中"，后面的同词同行才会被判成冲突
                pend = dict(id=_PENDING_ID, word=word, value=value)
                pending_word.setdefault(word, []).append(pend)
                pending_value.setdefault(value, []).append(pend)
            items.append(item)

        self._items = items
        self.internal_duplicates = internal_dups

    def _raw_of(self, line_no: int) -> str:
        lines = self.raw_text.split("\n")
        if 0 < line_no <= len(lines):
            return lines[line_no - 1]
        return ""

    def _cancelled_item(self, line_no: int, rej: RejectedRow | None) -> PreviewItem:
        """被取消的一行：仍留记录（能在「已取消」区看到、能恢复），但不属于任何组。"""
        if rej is not None:
            item = self._from_reject(rej)
        else:
            row = {r.line_no: r for r in self.rejects.good}[line_no]
            item = PreviewItem(line_no=line_no, group="", word=row.word, value=row.value,
                               typ=row.typ, pinyin=row.pinyin,
                               raw_line=self._raw_of(line_no))
        item.group = ""
        item.cancelled = True
        return item

    @staticmethod
    def _from_reject(rej: RejectedRow) -> PreviewItem:
        return PreviewItem(
            line_no=rej.line_no, group=GROUP_REJECT,
            word=rej.word, value=rej.value, typ=rej.typ, raw_line=rej.raw_line,
            reject_label=rej.detail, reject_advice=rej.reason.advice,
            reject_note=rej.cell_note,
        )

    # ----- 取消 / 恢复 -----

    def cancel(self, line_no: int) -> PreviewItem | None:
        """取消一条：它此后不出现在任何一组里（不是"标灰"——是真的不在分组里）。

        取消会**重判剩下那些行**：同一份表里靠前的重复行被取消后，靠后那条就
        变成新增了（它前面已经没有"将要写入的前一条"）。不重判的话预览会说
        「冲突」，而真导入会写进去——正是验收判据点名要防的偏差。
        """
        self._cancelled.add(int(line_no))
        self._build()
        return self.find(line_no)

    def restore(self, line_no: int) -> PreviewItem | None:
        """把取消过的一条放回分组（只影响本次预览，不动词库）。"""
        self._cancelled.discard(int(line_no))
        self._build()
        return self.find(line_no)

    def restore_all(self) -> int:
        n = len(self._cancelled)
        self._cancelled.clear()
        self._build()
        return n

    def find(self, line_no: int) -> PreviewItem | None:
        for it in self._items:
            if it.line_no == int(line_no):
                return it
        return None

    def is_cancelled(self, line_no: int) -> bool:
        return int(line_no) in self._cancelled

    @property
    def cancelled_lines(self) -> list[int]:
        return sorted(self._cancelled)

    @property
    def cancelled_items(self) -> list[PreviewItem]:
        """被取消的条目（界面「已取消」区要用它给出「全部恢复」）。"""
        return [self.find(n) for n in sorted(self._cancelled) if self.find(n) is not None]

    # ----- 分组视图（全部排除已取消）-----

    def effective(self, group: str | None = None) -> list[PreviewItem]:
        """当前**会进入分组**的条目（已取消的不在里面）。"""
        return [it for it in self._items
                if it.line_no not in self._cancelled
                and (group is None or it.group == group)]

    def groups(self) -> dict[str, list[PreviewItem]]:
        """三组的完整清单（空组也出现，界面据此显示「0 条」而不是缺一行）。"""
        return {name: self.effective(name) for name in GROUP_NAMES}

    def counts(self) -> dict[str, int]:
        """三组的条数（固定键序：新增 / 冲突 / 格式不合格）。"""
        out = {name: 0 for name in GROUP_NAMES}
        for it in self._items:
            if it.line_no in self._cancelled:
                continue
            out[it.group] = out.get(it.group, 0) + 1
        return out

    def total(self) -> int:
        return sum(self.counts().values())

    def conflict_kinds(self) -> dict[str, int]:
        """冲突按形态分布（形态名直接来自查重引擎的常量）。"""
        out: dict[str, int] = {}
        for it in self.effective(GROUP_CONFLICT):
            for k in it.kinds:
                out[k] = out.get(k, 0) + 1
        return out

    def conserved(self) -> bool:
        """自检：三组条数之和 = 未取消的条目数，且没有任何一条同时属于两组。"""
        seen: set[int] = set()
        for name in GROUP_NAMES:
            for it in self.effective(name):
                if it.line_no in seen or it.group != name:
                    return False
                seen.add(it.line_no)
        return len(seen) == len([it for it in self._items
                                 if it.line_no not in self._cancelled])

    # ----- 分批声明（与真导入同源）-----

    def effective_good_rows(self) -> list:
        """会进批的行（当前未被取消的合法行，按原始行序）。"""
        keep = {it.line_no for it in self.effective() if it.group != GROUP_REJECT}
        return [row for row in self.rejects.good if row.line_no in keep]

    def plan(self) -> BatchPlan:
        """按当前口径会切成几批——用的是 D2 的 `plan_batches`，不自己算。"""
        return plan_batches(self.effective_good_rows(), self.policy)

    def batch_note(self) -> str:
        plan = self.plan()
        return msg.batch_note(plan.batch_count, plan.policy.batch_size)

    def batch_count(self) -> int:
        return self.plan().batch_count

    # ----- 文案 -----

    def summary_text(self) -> str:
        c = self.counts()
        head = msg.summary(c[GROUP_NEW], c[GROUP_CONFLICT], c[GROUP_REJECT])
        if self.rejects.is_blocking():
            return msg.mapping_blocked(self.rejects.blocking_items())
        if self.total() == 0:
            return msg.all_cancelled() if self._cancelled else msg.nothing_ready()
        out = head
        if self._cancelled:
            out += " " + msg.cancelled(len(self._cancelled))
        return out + " " + self.batch_note()

    def group_note(self, name: str) -> str:
        return msg.GROUP_NOTES.get(name, "")


def preview_from_sheet(sheet, store, *, policy: BatchPolicy | None = None,
                       source_name: str = "") -> PreviewModel:
    """解析好的表 → 预览模型（D2 分区 + 既有查重引擎，两步都不另写）。"""
    from fixtext_vocab_import.rejects import partition_sheet

    rejects = partition_sheet(sheet, source_name=source_name)
    return PreviewModel(rejects, store, policy,
                        raw_text=getattr(sheet, "raw_text", ""))


def preview_from_rejects(rejects, store, *, policy: BatchPolicy | None = None,
                         raw_text: str = "") -> PreviewModel:
    """已有 D2 清单时只做分组（不合格行原样进组，不重算原因分类）。"""
    return PreviewModel(rejects, store, policy, raw_text=raw_text)
