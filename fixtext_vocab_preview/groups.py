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

## V1.1-D4 在这里加了什么

冲突组里的每一条现在可以带一个**处置**（`action`）：改值 / 跳过 / 设为禁用。
处置不是界面上贴的标签，而是**进 `_build` 的输入**——改过的值参与查重、跳过的
条目不占「前面已经有一条」的位置、设为禁用的条目算「会写进库」。因此处置后
整张表**自动重判**，用的还是上面那同一套判定，没有第二份比对逻辑。

为什么不把处置记在界面层：预览数字与真导入的数字必须同源。处置若只存在按钮状态里，
`counts()` 给的是处置前的数，写入清单给的是处置后的数——「预览说 N、写入变 N+k」
正是这么长出来的。
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

#: 冲突的三条处置（V1.1-D4）。常量放在模型这一层：处置是模型的输入，
#: 不是界面按钮的私有状态（见模块头「D4 在这里加了什么」）。
ACTION_EDIT = "edit"          # 改值：换一个正确写法，再按同一套查重重判
ACTION_SKIP = "skip"          # 跳过：这一条这次不写入
ACTION_DISABLE = "disable"    # 设为禁用：照常写进词库，但按禁用状态写

#: 处置的人话名字（界面按钮与状态文案共用一份，不各写一遍）
ACTION_NAMES: dict[str, str] = {
    ACTION_EDIT: "改值",
    ACTION_SKIP: "跳过",
    ACTION_DISABLE: "设为禁用",
}

#: 处置后的去向（V1.1-D4）。写入清单与影响预览只认这五个值：
#: 新增 / 更新 / 设为禁用 三类算「会写进词库」；跳过 与 未处置的冲突 不算。
EFFECT_ADD = "add"              # 库里没有 → 新增一条
EFFECT_UPDATE = "update"        # 同词异值 → 改掉库里那条的值（改值处置的直接结果）
EFFECT_DISABLED = "disabled"    # 照常写进词库，但按禁用状态写
EFFECT_SKIPPED = "skipped"      # 这次不写（跳过处置 / 逐条取消）
EFFECT_PENDING = "pending"      # 冲突还没处置：不算写入，等用户决定
EFFECT_REJECTED = "rejected"    # 格式不合格，写不进去

#: 去向的人话名字（影响预览的四个数字就用这四个）
EFFECT_NAMES: dict[str, str] = {
    EFFECT_ADD: "新增",
    EFFECT_UPDATE: "更新",
    EFFECT_DISABLED: "禁用",
    EFFECT_SKIPPED: "跳过",
}

#: 「同一次导入里前面已经出现」的命中用这个 id。真实自定义词条的 id 从 1 起
#: （`CustomVocab.add` 取 `max(default=0)+1`），所以 0 不可能与真条目相撞。
_PENDING_ID = 0

#: 会真的写进词库的三种去向（影响预览里「将写入 N 条」就数这三种）
_WRITING_EFFECTS: tuple[str, ...] = (EFFECT_ADD, EFFECT_UPDATE, EFFECT_DISABLED)


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
    #: 处置（V1.1-D4）：空串 = 还没处置；否则是 ACTION_EDIT / ACTION_SKIP / ACTION_DISABLE
    action: str = ""
    #: 改值处置输入的新值（只有 ACTION_EDIT 会有内容）
    edited_value: str = ""
    #: 处置**之后**这条的去向（由 `_build` 重判后写定，界面与写入清单都读它）：
    #: add / update / disabled / skipped / pending / rejected
    effect: str = ""
    #: 更新处置要改的那条自定义词条 id（只有 effect == "update" 会有值）
    update_target: int = 0
    #: 处置状态的一句话（界面状态列直接用，不自己拼）
    action_note: str = ""

    # ----- 处置相关的派生值 -----

    @property
    def effective_value(self) -> str:
        """这一条**现在**会写进词库的替换值（改过值就是新值）。"""
        if self.action == ACTION_EDIT and self.edited_value.strip():
            return self.edited_value.strip()
        return self.value

    @property
    def edited(self) -> bool:
        return self.action == ACTION_EDIT

    @property
    def will_write(self) -> bool:
        """这条是否在写入清单里（新增 / 更新 / 设为禁用都算写入）。"""
        return self.effect in (EFFECT_ADD, EFFECT_UPDATE, EFFECT_DISABLED)

    @property
    def action_name(self) -> str:
        return ACTION_NAMES.get(self.action, "")

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
        #: 行号 → (处置, 改值的新值)。**处置的唯一定义处**：它进 `_build`，
        #: 不是界面按钮的附带状态（见模块头「D4 在这里加了什么」）。
        self._actions: dict[int, tuple[str, str]] = {}
        self.internal_duplicates = 0           # 同表内撞车的条数（自检用）
        self._build()

    # ----- 处置判定（每条的去向）-----

    def _decide(self, item: PreviewItem) -> None:
        """按「处置 + 查重结论」给这一条写定去向（`effect`）与一句状态文案。

        判定只在这里发生一次，`counts()` / `write_plan()` / 真实写入口读的都是
        这里写下的 `effect`——三处不可能给出不同的数。
        """
        from fixtext_vocab import KIND_SAME_BOTH, KIND_SAME_WORD

        same_both = [c for c in item.conflicts if c.get("kind") == KIND_SAME_BOTH]
        same_word = [c for c in item.conflicts if c.get("kind") == KIND_SAME_WORD]
        other_conflict = bool(item.conflicts) and not same_both and not same_word

        if item.action == ACTION_SKIP:
            # 跳过：仍然留在冲突组里（状态可见、可撤销），但不进写入清单。
            # 组别不动是为了守住 D3 的守恒断言：除了「取消」，没有条目会凭空消失。
            item.effect = EFFECT_SKIPPED
            item.action_note = msg.action_note_skip()
            return

        if item.action == ACTION_DISABLE:
            # 设为禁用：这条照样写进词库，但按禁用状态写。撞的车如果是库里的
            # 同词同值条目，禁用的就是库里那一条（不重复写一条一样的）；
            # 否则新增一条并置为禁用。两种情形都落到同一份禁用状态存储。
            item.effect = EFFECT_DISABLED
            item.update_target = self._disable_target(same_both, same_word)
            item.action_note = msg.action_note_disable(item.word, item.effective_value)
            return

        if item.action == ACTION_EDIT:
            if same_both:
                # 改值后与库里那条一模一样：写进去没有意义，按跳过记账
                item.effect = EFFECT_SKIPPED
                item.group = GROUP_CONFLICT
                item.action_note = msg.action_note_edit_still_exists(
                    item.word, item.effective_value)
            elif same_word:
                # 同词异值 → 改掉库里那条的值，这才是「更新」的字面意思
                item.effect = EFFECT_UPDATE
                item.update_target = int(same_word[0].get("id") or 0)
                item.action_note = msg.action_note_update(
                    item.word, item.value, item.effective_value)
            elif other_conflict:
                # 还剩「同值异词」这种撞车：改值没解决，继续等用户处置
                item.effect = EFFECT_PENDING
                item.group = GROUP_CONFLICT
                item.action_note = msg.action_note_edit_still_conflict(
                    item.effective_value)
            else:
                item.effect = EFFECT_ADD
                item.group = GROUP_NEW
                item.action_note = msg.action_note_edit_rejudged(
                    item.value, item.effective_value)
            return

        # 还没处置
        if item.conflicts:
            item.effect = EFFECT_PENDING
            item.action_note = msg.action_note_pending()
        else:
            item.effect = EFFECT_ADD
            item.action_note = ""

    @staticmethod
    def _disable_target(same_both: list[dict], same_word: list[dict]) -> int:
        """「设为禁用」要落在库里哪一条：优先同词同值，其次同词异值。"""
        for group in (same_both, same_word):
            for c in group:
                cid = int(c.get("id") or 0)
                if cid and cid != _PENDING_ID:
                    return cid
        return 0

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
        """把 D2 的分区结果按行序做成各组；引擎判定逐条递进（见模块头注释）。

        **处置是输入**：这一遍读 `self._actions`（改值的新值 / 跳过 / 设为禁用），
        把改过的值送进同一套查重、让跳过的那条不占「前面已经有一条」的位置，
        再给每条写定去向（`effect`）。分组与影响预览都从 `effect` 出来，
        所以处置之后整张表自动重判，不存在第二份数字。
        """
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
            act, edited = self._actions.get(line_no, ("", ""))
            if line_no in self._cancelled:
                # 取消掉的行**不参与查重递进**：它既不进任何一组，也不再占着
                # 「前面已经有一条」的位置。否则取消前一条、后一条仍被判成冲突，
                # 而真导入时那条会被写进去——预览数字就与实际结果对不上了。
                item = self._cancelled_item(line_no, rej)
                item.action, item.edited_value = act, edited
                item.effect = EFFECT_SKIPPED
                item.action_note = msg.cancel_note()
                items.append(item)
                continue
            if rej is not None:
                item = self._from_reject(rej)
                item.effect = EFFECT_REJECTED
                items.append(item)
                continue

            row = good_by_line[line_no]
            value = edited if (act == ACTION_EDIT and edited.strip()) else row.value
            hits_w = list(by_word.get(row.word, [])) + list(pending_word.get(row.word, []))
            hits_v = list(by_value.get(value, [])) + list(pending_value.get(value, []))
            conflicts = conflict_list(self.store.builtin, row.word, value, hits_w, hits_v)

            within = any(c.get("id") == _PENDING_ID for c in conflicts)
            item = PreviewItem(
                line_no=line_no, group=GROUP_CONFLICT if conflicts else GROUP_NEW,
                word=row.word, value=row.value, typ=row.typ, pinyin=row.pinyin,
                raw_line=self._raw_of(line_no),
                conflicts=list(conflicts), within_batch=within,
                action=act, edited_value=edited,
            )
            self._decide(item)
            if item.effect == EFFECT_PENDING and conflicts:
                if within:
                    internal_dups += 1
            if item.effect in _WRITING_EFFECTS:
                # 会写进库的条目（新增 / 更新 / 禁用）都当成"已在库中"，
                # 后面的同词同行才会被判成冲突。跳过与未处置的不占这个位置。
                pend = dict(id=_PENDING_ID, word=item.word, value=item.effective_value)
                pending_word.setdefault(item.word, []).append(pend)
                pending_value.setdefault(item.effective_value, []).append(pend)
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

    # ----- 冲突项处置（V1.1-D4）：改值 / 跳过 / 设为禁用 -----

    def set_action(self, line_no: int, action: str, value: str = "") -> PreviewItem | None:
        """给某条一个处置。**处置写进模型、随后整表重判**（不是只改按钮外观）。

        :param line_no: 原始行号（与 D1/D2 同口径）
        :param action: ``ACTION_EDIT`` / ``ACTION_SKIP`` / ``ACTION_DISABLE``；
                       传空串等于撤销处置
        :param value: 改值的新值（只有 ``ACTION_EDIT`` 用）
        :return: 重判之后这一条的新状态；行号不存在时返回 ``None``

        反复处置同一条是允许的（改值 → 再改成跳过 → 再撤销），每次都以最后一次为准：
        处置只记在 ``_actions`` 里，重判是无状态的纯计算。
        """
        line_no = int(line_no)
        if self.find(line_no) is None:
            return None
        action = (action or "").strip()
        if not action:
            self._actions.pop(line_no, None)
        elif action == ACTION_EDIT:
            new_value = str(value or "").strip()
            if not new_value:
                raise ValueError("改值要给出新的替换值")
            self._actions[line_no] = (ACTION_EDIT, new_value)
        elif action in (ACTION_SKIP, ACTION_DISABLE):
            self._actions[line_no] = (action, "")
        else:
            raise ValueError(f"未知的处置：{action}")
        # 处置过的条目不能再是「已取消」：两种状态混在一起会让账算不清
        if action:
            self._cancelled.discard(line_no)
        self._build()
        return self.find(line_no)

    def edit_value(self, line_no: int, new_value: str) -> PreviewItem | None:
        """改值处置（``set_action`` 的便捷写法，界面「改值」按钮直接用它）。"""
        return self.set_action(line_no, ACTION_EDIT, new_value)

    def skip(self, line_no: int) -> PreviewItem | None:
        """跳过处置：这一条这次不写入（但它仍留在冲突组里，状态可见、可撤销）。"""
        return self.set_action(line_no, ACTION_SKIP)

    def disable(self, line_no: int) -> PreviewItem | None:
        """设为禁用处置：这条照样写进词库，但按禁用状态写（与 B 组禁用同一份存储）。"""
        return self.set_action(line_no, ACTION_DISABLE)

    def clear_action(self, line_no: int) -> PreviewItem | None:
        """撤销单条的处置，回到「还没处置」的原样。"""
        return self.set_action(line_no, "")

    def restore_all_actions(self) -> int:
        """撤销全部处置（连同逐条取消一起回到刚打开预览时的样子）。"""
        n = len(self._actions) + len(self._cancelled)
        self._actions.clear()
        self._cancelled.clear()
        self._build()
        return n

    def action_of(self, line_no: int) -> str:
        return self._actions.get(int(line_no), ("", ""))[0]

    @property
    def dispositions(self) -> dict[int, str]:
        """行号 → 处置代号（界面状态列与验收记录都读这一份）。"""
        return {n: a for n, (a, _v) in self._actions.items()}

    def disposed_items(self, action: str | None = None) -> list[PreviewItem]:
        """已处置的条目（``action`` 为空时返回全部处置过的）。"""
        out = [it for it in self._items if it.action]
        if action:
            out = [it for it in out if it.action == action]
        return out

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

    # ----- 影响预览与写入清单（V1.1-D4 交付物②的数据面）-----

    def write_plan(self) -> dict:
        """「将写入 N 条：新增 X / 更新 Y / 禁用 Z / 跳过 S」的**唯一**来源。

        四个数字按每条的去向（`effect`）数出来，不是按组别数：
        组别讲的是「为什么落在这一组」，去向讲的是「这次会拿它做什么」。
        二次确认弹窗与预演对账读的都是这一个函数，所以两次给出同一个数。

        ``new`` 是「词库条目会**净增**几条」——与 ``add`` 不一定相等：
        设为禁用的那一条若撞的是库里已有的同词同值条目，禁用的是那一条本身
        （不新建），所以不计入 ``new``。预演对账用 ``new`` 与副本的条目差集比，
        两个口径必须一致，否则「新增」这一列永远差一条。
        """
        counts = {k: 0 for k in EFFECT_NAMES}
        pending = 0
        new_entries = 0
        for it in self._items:
            if it.line_no in self._cancelled:
                counts[EFFECT_SKIPPED] += 1        # 逐条取消 = 这次不写
                continue
            if it.effect in counts:
                counts[it.effect] += 1
                if it.effect == EFFECT_ADD:
                    new_entries += 1
                elif it.effect == EFFECT_DISABLED and not int(it.update_target or 0):
                    new_entries += 1
            elif it.effect == EFFECT_PENDING:
                pending += 1
        write_n = counts[EFFECT_ADD] + counts[EFFECT_UPDATE] + counts[EFFECT_DISABLED]
        return dict(
            write=write_n,
            add=counts[EFFECT_ADD],
            update=counts[EFFECT_UPDATE],
            disabled=counts[EFFECT_DISABLED],
            skipped=counts[EFFECT_SKIPPED],
            pending=pending,
            new=new_entries,
            total=len([it for it in self._items if it.line_no not in self._cancelled]),
        )

    def impact_text(self) -> str:
        """影响预览的一句话（二次确认正文直接用它，不自己拼数字）。"""
        p = self.write_plan()
        return msg.impact(p["write"], p["add"], p["update"], p["disabled"], p["skipped"])

    def pending_items(self) -> list[PreviewItem]:
        """还没处置的冲突（二次确认要拦着它：这种条目写不写都说不清）。"""
        return [it for it in self._items
                if it.line_no not in self._cancelled and it.effect == EFFECT_PENDING]

    def write_list(self) -> list[dict]:
        """写入清单（D5 的输入）：每条带词 / 值 / 类型 / 注音 / 去向 / 是否禁用。

        **跳过的不在里面**——「不进写入清单」的落点就是这个列表。
        设为禁用的在里面，且 ``disabled`` 为 True（这就是「带禁用标记」的落点）。
        更新也走 `update_target` 记下要改的那条 id，D5 据此改用 `update_entry`。
        """
        out: list[dict] = []
        for it in self._items:
            if it.line_no in self._cancelled or not it.will_write:
                continue
            out.append(dict(
                line_no=it.line_no,
                word=it.word,
                value=it.effective_value,
                typ=it.typ or "错词校正",
                pinyin=it.pinyin or "",
                effect=it.effect,
                action=it.action,
                disabled=(it.effect == EFFECT_DISABLED),
                update_target=int(it.update_target or 0),
            ))
        return out

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
