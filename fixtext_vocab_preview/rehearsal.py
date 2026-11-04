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

__all__ = ["RehearsalResult", "write_new_entries", "rehearse"]


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


@dataclass
class RehearsalResult:
    """一次预演的实测结果与对账表（预览一列 / 实测一列 / 是否一致）。"""

    preview_new: int = 0
    preview_conflict: int = 0
    preview_reject: int = 0
    measured_new: int = 0             # 副本里真多出来的条目数
    measured_conflict: int = 0        # 写完后逐条复核仍判为冲突的条数
    measured_reject: int = 0          # D2 清单给出的不合格条数
    modified: int = 0                 # 新增之外被改动的条目数（应为 0）
    removed: int = 0                  # 被删掉的条目数（应为 0）
    before_count: int = 0
    after_count: int = 0
    good_rows: int = 0                # 参与分组的合法行数（不含已取消、不含不合格）
    real_sha_before: str = ""         # 用户真实词库（全程只读）
    real_sha_after: str = ""
    copy_sha_before: str = ""
    copy_sha_after: str = ""
    written_words: list[str] = field(default_factory=list)
    #: 取消掉的行号（这些条目不该出现在副本里）
    cancelled_lines: list[int] = field(default_factory=list)
    #: 副本里出现了、但预览说「不该写」的词（应为空）
    leaked: list[str] = field(default_factory=list)
    #: 预览算成冲突、写完复核却不冲突的行号（应为空）
    unconfirmed_conflicts: list[int] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        """三项数字逐项相等，且副本没有被改 / 被删 / 泄漏 / 冤判。"""
        return (self.measured_new == self.preview_new
                and self.measured_conflict == self.preview_conflict
                and self.measured_reject == self.preview_reject
                and self.modified == 0 and self.removed == 0
                and not self.leaked and not self.unconfirmed_conflicts)

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
    """
    from fixtext_vocab_preview.groups import GROUP_CONFLICT, GROUP_NEW, GROUP_REJECT

    counts = dict(preview_snapshot or model.counts())
    res = RehearsalResult(
        preview_new=counts.get(GROUP_NEW, 0),
        preview_conflict=counts.get(GROUP_CONFLICT, 0),
        preview_reject=counts.get(GROUP_REJECT, 0),
        cancelled_lines=list(model.cancelled_lines),
    )

    real_path: Path = model.store.custom.path
    res.real_sha_before = _sha(real_path)
    res.real_sha_after = res.real_sha_before        # 先置同值，收尾再真读一次

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
        before = _entry_signatures(store.custom.entries())
        res.before_count = len(before)

        targets = list(model.effective(GROUP_NEW))
        added = write_new_entries(store, targets)
        res.written_words = [e["word"] for e in added]

        after = _entry_signatures(store.custom.entries())
        res.after_count = len(after)
        res.copy_sha_after = _sha(copy_path)

        new_keys = set(after) - set(before)
        gone = set(before) - set(after)
        res.measured_new = len(new_keys)
        res.removed = len(gone)
        res.modified = sum(1 for k in (set(before) & set(after)) if before[k] != after[k])

        # 泄漏检查：副本里新增的每一条都必须能在「新增」组里找到同词同值的一行
        allowed = {(it.word, it.value) for it in targets}
        res.leaked = [f"{w} → {v}" for (w, v) in sorted(new_keys) if (w, v) not in allowed]

        # 冲突复核：写完之后逐条再问一次查重（单条接口，不是分组那条路径）。
        # 同表内重复的那条此时在库里已存在，所以也会被判为冲突——这是刻意的。
        for it in model.effective(GROUP_CONFLICT):
            if store.conflicts_for_add(it.word, it.value):
                res.measured_conflict += 1
            else:
                res.unconfirmed_conflicts.append(it.line_no)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    res.real_sha_after = _sha(real_path)
    return res


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""
