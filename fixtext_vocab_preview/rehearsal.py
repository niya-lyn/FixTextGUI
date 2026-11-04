"""V1.1-D3 · 预演写：拿词库文件的**临时副本**跑一次真写入，核对预览数字。

验收判据要的是「预览说 N，写入不能变 N+k」。嘴上保证没用，所以这里做一次
真写入——只是写进副本：

1. 把用户的词库文件**按字节**复制到临时目录（原文件全程只读，前后指纹必须相同）；
2. 在副本上建一个指向副本的 `VocabStore`，用**D5 将采用的同一个写入口**
   （:func:`write_new_entries`，逐条走 `CustomVocab.add`，D5 再加事务与撤销）；
3. 三列数字各自有**独立来源**，不是把预览数字抄一遍：

   * 新增实测：写入前后副本的条目差集（真的多了几条）；
   * 冲突实测：写完之后，对每条「冲突」重新调一次 `conflicts_for_add`
     —— 这是查重的单条公共接口，与预览分组走的是同一个引擎但**另一条调用路径**，
     它若说「不冲突」，说明预览把一条能写的算成了冲突；
   * 不合格实测：直接取 `RejectList.counts()`（D2 的原始清单，不是预览分组的结果）。

4. 三列逐项比对，并检查副本有没有被改 / 被删 / 冒出不该写的条目。

**为什么要真写而不是"数一数"。** 数是按自己的理解数的，写是代码真做了；
只有真写才能抓到「预览里算新增、写的时候被挡下」这类错位。

**为什么副本，不是内存模拟。** 内存里造一份列表比对，验的是"我以为的写入"，
不是"写入的真实效果"；副本上跑的是同一份写入代码、同一条序列化路径
（含 id 分配、字段补齐、规范化），差别只在文件位置。

范围边界：本模块只做**核对**。它不落用户词库、不留还原点、不做整批撤销
（D5 负责）。副本用完即删。
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from fixtext_vocab import CustomVocab, VocabStore

__all__ = ["RehearsalResult", "write_new_entries", "write_plan_entries", "rehearse"]


def write_new_entries(store: VocabStore, items) -> list[dict]:
    """**D5 将采用的写入口**：把预览里「新增」那一组的条目逐条写进词库。

    刻意只做这一件事、不加事务与撤销——那是 D5 的范围。这里保持最朴素的
    写法（逐条 `CustomVocab.add`），因为预演核对要验的正是「真实写入的条数」，
    多包一层逻辑就多一个"预演和真导入不同"的可能。

    字段口径与 D1 的映射结果一致（word / value / typ / pinyin），
    `book` 留空（按书清单属于 C 组，不在这条链里）。
    """
    added: list[dict] = []
    for it in items:
        added.append(store.custom.add(
            word=it.word, value=it.value, typ=it.typ or "错词校正",
            pinyin=it.pinyin or "", book="",
        ))
    return added


def write_plan_entries(store: VocabStore, items) -> dict:
    """D4 的写入清单在**临时副本**上的一条条落法（D5 实现事务写入时照这个口径）。

    与 :func:`write_new_entries` 的差别只有一处，但它正是 D4 的核心：

    * 新增（``EFFECT_ADD``）→ ``custom.add``；
    * 更新（``EFFECT_UPDATE``）→ ``custom.update(目标 id, value=新值)``，
      这才是「改值」处置在数据上的真实效果，不是再加一条；
    * 设为禁用（``EFFECT_DISABLED``）→ 该写的那条照写，然后把它的
      启用状态关掉：**走 ``store.states``（word_states 唯一入口）**，
      与词库页里 B 组词条关掉开关完全同一份存储、同一个语义。

    范围边界：这里不做事务、不留还原点（D5 负责）；它只是把清单落下去，
    好让预演能独立数出「真写了几条、几条真被禁用」。
    """
    from fixtext_vocab_preview.groups import EFFECT_ADD, EFFECT_DISABLED, EFFECT_UPDATE

    added: list[dict] = []
    updated: list[dict] = []
    disabled_pairs: list[tuple[str, str]] = []
    for it in items:
        effect = getattr(it, "effect", EFFECT_ADD)
        word = getattr(it, "word", "")
        value = getattr(it, "effective_value", getattr(it, "value", ""))
        if effect == EFFECT_UPDATE:
            target = int(getattr(it, "update_target", 0) or 0)
            updated.append(store.custom.update(target, value=value))
            continue
        if effect == EFFECT_DISABLED and int(getattr(it, "update_target", 0) or 0):
            # 库里本来就有同词同值这一条：禁用的就是那一条，不能再加一条一样的
            # （加进去会变成两条同词同值的重复条目，词库页会多出一行废数据）。
            disabled_pairs.append((word, value))
            continue
        added.append(store.custom.add(
            word=word, value=value, typ=getattr(it, "typ", "") or "错词校正",
            pinyin=getattr(it, "pinyin", "") or "", book="",
        ))
        if effect == EFFECT_DISABLED:
            disabled_pairs.append((word, value))
    result = dict(added=added, updated=updated, disabled_pairs=disabled_pairs)
    if disabled_pairs:
        result["state"] = store.set_entries_enabled(disabled_pairs, enabled=False)
    return result


@dataclass
class RehearsalResult:
    """一次预演的实测结果与对账表（预览一列 / 实测一列 / 是否一致）。"""

    preview_new: int = 0
    preview_conflict: int = 0
    preview_reject: int = 0
    #: D4 的四个数（预览侧，来自 `PreviewModel.write_plan()`）
    preview_write: int = 0
    preview_update: int = 0
    preview_disabled: int = 0
    preview_skipped: int = 0
    measured_new: int = 0             # 副本里真多出来的条目数
    measured_conflict: int = 0        # 写完后逐条复核仍判为冲突的条数
    measured_reject: int = 0          # D2 清单给出的不合格条数
    #: D4 的实测侧：真改了几条的值 / 真被禁用的条目数 / 真写进去的总条数
    measured_update: int = 0
    measured_disabled: int = 0
    measured_write: int = 0
    measured_skipped: int = 0
    #: 副本里禁用集的变化（用 word_states 的接口读，不是自己数文件）
    copy_disabled_before: int = 0
    copy_disabled_after: int = 0
    #: 设为禁用处置的目标词条，是否真落进了禁用集（逐条实证）
    disabled_ok: list[str] = field(default_factory=list)
    disabled_failed: list[str] = field(default_factory=list)
    modified: int = 0                 # 新增之外被改动的条目数（应为 0）
    removed: int = 0                  # 被删掉的条目数（应为 0）
    before_count: int = 0
    after_count: int = 0
    good_rows: int = 0                # 参与分组的合法行数（不含已取消、不含不合格）
    real_sha_before: str = ""         # 用户真实词库（全程只读）
    real_sha_after: str = ""
    #: 用户真实的禁用/解除状态文件（D4 新增维度）是否全程没被碰过
    real_states_untouched: bool = False
    copy_sha_before: str = ""
    copy_sha_after: str = ""
    written_words: list[str] = field(default_factory=list)
    #: 真写进副本的「词 → 值」对（D4 用：改值处置要证「写进去的是新值」）
    written_pairs: list[str] = field(default_factory=list)
    #: 取消掉的行号（这些条目不该出现在副本里）
    cancelled_lines: list[int] = field(default_factory=list)
    #: 副本里出现了、但预览说「不该写」的词（应为空）
    leaked: list[str] = field(default_factory=list)
    #: 预览算成冲突、写完复核却不冲突的行号（应为空）
    unconfirmed_conflicts: list[int] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        """几项数字逐项相等，且副本没有被改 / 被删 / 泄漏 / 冤判。

        D3 的三项（新增 / 冲突 / 不合格）保持原样；D4 追加三项（更新 / 禁用 / 跳过），
        它们各自都有独立来源——不去抄预览数字。任何一项对不上都判「不一致」。
        """
        return (self.measured_new == self.preview_new
                and self.measured_conflict == self.preview_conflict
                and self.measured_reject == self.preview_reject
                and self.measured_update == self.preview_update
                and self.measured_disabled == self.preview_disabled
                and self.measured_skipped == self.preview_skipped
                and self.modified == 0 and self.removed == 0
                and not self.leaked and not self.unconfirmed_conflicts
                and not self.disabled_failed)

    @property
    def real_untouched(self) -> bool:
        """用户真实词库一个字节都没动（这是"只读预览"的硬底线）。"""
        return self.real_sha_before == self.real_sha_after and bool(self.real_sha_before)

    def diff_columns(self) -> list[tuple[str, int, int, str]]:
        """对账表：项目 / 预览数字 / 预演实测数字 / 是否一致。"""
        def verdict(a: int, b: int) -> str:
            return "一致" if a == b else "不一致"

        return [
            ("新增", self.preview_new, self.measured_new, verdict(self.preview_new, self.measured_new)),
            ("冲突", self.preview_conflict, self.measured_conflict,
             verdict(self.preview_conflict, self.measured_conflict)),
            ("格式不合格", self.preview_reject, self.measured_reject,
             verdict(self.preview_reject, self.measured_reject)),
            ("更新", self.preview_update, self.measured_update,
             verdict(self.preview_update, self.measured_update)),
            ("禁用", self.preview_disabled, self.measured_disabled,
             verdict(self.preview_disabled, self.measured_disabled)),
            ("跳过", self.preview_skipped, self.measured_skipped,
             verdict(self.preview_skipped, self.measured_skipped)),
            ("被改动", 0, self.modified, verdict(0, self.modified)),
            ("被删除", 0, self.removed, verdict(0, self.removed)),
        ]

    def text(self) -> str:
        head = "对账结果：" if self.identical else "对账发现不一致："
        body = "、".join(f"{name} 预览 {pv} / 实测 {mv}"
                        for name, pv, mv, _ in self.diff_columns()[:3])
        tail = ("用户词库全程未改动（前后指纹相同）。"
                if self.real_untouched else "注意：用户词库的指纹变了，这不该发生。")
        extra = ""
        if self.leaked:
            extra += f" 副本里多出 {len(self.leaked)} 条不该写的词。"
        if self.unconfirmed_conflicts:
            extra += f" 有 {len(self.unconfirmed_conflicts)} 条被判为冲突、复核却不冲突。"
        return f"{head}{body}。{extra}{tail}"


def _entry_signatures(entries: list[dict]) -> dict[tuple[str, str], tuple]:
    """按 (词, 值) 记签名——**不做判定，只做对账**：多 / 少 / 被改三类都能看出来。"""
    return {(e["word"], e["value"]): (e["type"], e["pinyin"], e["book"]) for e in entries}


def rehearse(model, *, preview_snapshot: dict | None = None) -> RehearsalResult:
    """在词库文件的临时副本上做一次真写入，与预览数字对账。

    :param model: `PreviewModel`
    :param preview_snapshot: 提前拍下的预览数字（不传就取当前状态）。
                             传它是为了证明「对账用的是预览当时的数字」。

    六项数字各自有独立来源（D3 三项 + D4 三项），没有一项是抄预览的：

    * 新增 = 副本里真多出来的条目 id 数；
    * 冲突 = 写完逐条再问一次单条查重接口；
    * 不合格 = D2 清单的统计；
    * 更新 = 按 id 比对，值真的变了的条数（排除新增带来的键变化）；
    * 禁用 = 副本里禁用集的人数变化（读 word_states 接口，不是数文件）；
    * 跳过 = 被跳过/取消的条目里，确实没出现在副本新增集合里的条数。
    """
    from fixtext_vocab_preview.groups import (EFFECT_ADD, EFFECT_DISABLED, EFFECT_SKIPPED,
                                              EFFECT_UPDATE, GROUP_CONFLICT, GROUP_NEW,
                                              GROUP_REJECT)

    plan = model.write_plan() if hasattr(model, "write_plan") else {}
    counts = dict(preview_snapshot or model.counts())
    # 「新增」这一列的预览侧必须与实测**同口径**：实测量的是"副本里真多出来的条目 id"。
    # 禁用处置若库里没有同词同值那条，它也是真被 add 的新条目；若有，禁用的是那一条、
    # 不新建。这两种情形 `write_plan()` 的 `new` 都已算好，直接用，不自己再数一遍。
    #
    # 但**显式传了 preview_snapshot** 时一律以快照为准：那是调用方"拍下"的一组数字，
    # 用途正是验"对账确实拿它比"（D3 用它造一个人为调高的数字，看会不会被识破）。
    # 快照只有组别三项，此时「新增」就回落到组别数，不拿 plan 去覆盖它。
    if preview_snapshot:
        preview_new = counts.get(GROUP_NEW, 0)
    else:
        preview_new = int(plan.get("new", counts.get(GROUP_NEW, 0)))
    res = RehearsalResult(
        preview_new=preview_new,
        preview_conflict=counts.get(GROUP_CONFLICT, 0),
        preview_reject=counts.get(GROUP_REJECT, 0),
        preview_write=int(plan.get("write", 0)),
        preview_update=int(plan.get("update", 0)),
        preview_disabled=int(plan.get("disabled", 0)),
        preview_skipped=int(plan.get("skipped", 0)),
        cancelled_lines=list(model.cancelled_lines),
    )

    real_path: Path = model.store.custom.path
    res.real_sha_before = _sha(real_path)
    res.real_sha_after = res.real_sha_before        # 先置同值，收尾再真读一次
    real_states_path = getattr(getattr(model.store, "states", None), "path", None)
    states_sha_before = _sha(real_states_path) if real_states_path else ""

    # 不合格条数：直接取 D2 清单的统计（按原因分类汇总），不经过预览分组
    res.measured_reject = int(sum(model.rejects.counts().values()))
    res.good_rows = len(model.effective_good_rows())

    tmp = Path(tempfile.mkdtemp(prefix="preview_rehearsal_"))
    try:
        copy_path = tmp / "custom_vocab.json"
        if real_path.is_file():
            shutil.copyfile(real_path, copy_path)   # 按字节复制
        else:
            # 用户还没建过词库：让副本自己按与真实库同一套规范落一份空文件
            CustomVocab(copy_path)

        store = VocabStore(custom_path=copy_path, work_dir=tmp / "rules",
                           snap_dir=tmp / "snap")

        res.copy_sha_before = _sha(copy_path)
        before = {e["id"]: (e["word"], e["value"], e["type"], e["pinyin"], e["book"])
                  for e in store.custom.entries()}
        res.before_count = len(before)
        res.copy_disabled_before = store.states.disabled_count()

        targets = list(model.write_list())
        items = [it for it in model._items if it.will_write
                 and it.line_no not in model.cancelled_lines]
        outcome = write_plan_entries(store, items)
        res.written_words = [e["word"] for e in outcome["added"]]
        res.written_pairs = [f"{e['word']} → {e['value']}"
                             for e in list(outcome["added"]) + list(outcome["updated"])]

        after = {e["id"]: (e["word"], e["value"], e["type"], e["pinyin"], e["book"])
                 for e in store.custom.entries()}
        res.after_count = len(after)
        res.copy_sha_after = _sha(copy_path)

        added_ids = set(after) - set(before)
        gone_ids = set(before) - set(after)
        res.measured_new = len(added_ids)
        res.removed = len(gone_ids)
        # 更新 = 同一个 id 上值真的变了；新增不算（它是新 id，不在交集里）
        updated_ids = {int(getattr(it, "update_target", 0) or 0) for it in items
                       if getattr(it, "effect", "") == EFFECT_UPDATE}
        res.measured_update = sum(
            1 for i in (set(before) & set(after))
            if before[i][:2] != after[i][:2] and i in updated_ids)
        res.modified = sum(
            1 for i in (set(before) & set(after))
            if before[i] != after[i] and i not in updated_ids)

        # 禁用实测：读副本的禁用集（与词库页 B 组开关同一份存储、同一个接口）
        res.copy_disabled_after = store.states.disabled_count()
        res.measured_disabled = max(0, res.copy_disabled_after - res.copy_disabled_before)
        for it in items:
            if getattr(it, "effect", "") != EFFECT_DISABLED:
                continue
            if store.states.is_disabled(it.word, it.effective_value):
                res.disabled_ok.append(f"{it.word} → {it.effective_value}")
            else:
                res.disabled_failed.append(f"{it.word} → {it.effective_value}")

        # 跳过实测：被跳过 / 取消的条目，必须一条都没出现在副本的新增集合里
        added_keys = {(after[i][0], after[i][1]) for i in added_ids}
        skipped_absent = 0
        for it in model._items:
            skipped = (it.line_no in model.cancelled_lines
                       or getattr(it, "effect", "") == EFFECT_SKIPPED)
            if not skipped:
                continue
            if (it.word, it.effective_value) not in added_keys:
                skipped_absent += 1
        res.measured_skipped = skipped_absent

        # 写入总量实测：新增 + 更新（禁用与新增共用同一次 add，不重复计）
        res.measured_write = res.measured_new + res.measured_update
        allowed = {(d["word"], d["value"]) for d in targets
                   if d["effect"] in (EFFECT_ADD, EFFECT_DISABLED)}
        res.leaked = [f"{w} → {v}" for (w, v) in sorted(added_keys) if (w, v) not in allowed]

        # 冲突复核：写完之后逐条再问一次查重（单条接口，不是分组那条路径）。
        # 同表内重复的那条此时在库里已存在，所以也会被判为冲突——这是刻意的。
        for it in model.effective(GROUP_CONFLICT):
            if store.conflicts_for_add(it.word, it.effective_value):
                res.measured_conflict += 1
            else:
                res.unconfirmed_conflicts.append(it.line_no)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    res.real_sha_after = _sha(real_path)
    res.real_states_untouched = (
        (_sha(real_states_path) if real_states_path else "") == states_sha_before)
    return res


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""
