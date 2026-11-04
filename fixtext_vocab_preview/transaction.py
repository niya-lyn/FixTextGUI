"""V1.1-D5 · 批量事务写入与整批撤销（数据层，不依赖 Qt）。

排期 §9.7 交付物①②③的落点：

* **一批一次落盘**。确认后把 D4 的 `write_list()` 整批写进 ``custom_vocab.json``：
  先在内存里把清单折成「提交后的整份条目表」，再**编码一次、原子替换一次**
  （``CustomVocab.replace_all``）。逐条 ``add()`` 会写 N 次文件，第 k 次失败就留下
  半批——这正是本卡要防的。
* **中途失败不落半批**。写之前先把「操作前」的字节留成还原点（顺带就是备份），
  写完从**磁盘重新读回来**逐项核对（整份字节 / 条数 / 每条内容 / 禁用集），
  任何一项对不上就按「操作前」字节整份回写，并把还原点撤掉、记一条未完成的记录。
* **整批撤销**。整批只占**一个**还原点，所以既有的撤销栈（``store.undo()`` /
  词库页「撤销」按钮 / Ctrl+Z / 历史面板「恢复到此刻」）不用改一行就能整批回退；
  :func:`undo_batch` 只是「一次调用把这一批退回去」的入口，它复用那两个既有原语，
  不另造第二套撤销体系。
* **写入前自动快照**。还原点由 ``SnapshotStore.begin`` 建，与单条新增 / 编辑 / 删除
  用的是同一份磁盘结构：历史面板可见、可「恢复到此刻」、也可退到它之前。

## 为什么复用 SnapshotStore / CustomVocab 而不自己写一套

还原点、操作历史、撤销栈是**同一份磁盘结构**（``snapshots/index.json``）。
自己再写一套「批量事务日志」，就会出现两个可以互相矛盾的真相：词库页的撤销栈
不知道这次导入，历史面板也看不见它。所以这里只做「写什么、怎么核对、失败怎么退」，
留痕与回退全部复用既有那条路。

## 与预演（D3/D4）的口径关系

:func:`plan_batch` 的折叠规则与 :func:`fixtext_vocab_preview.rehearsal.write_plan_entries`
逐条对齐（新增 → 追加一条；更新 → 改目标条目那一条的值；设为禁用 → 有目标就只禁用它，
没有才新增一条再禁用）。预演说「新增 X / 更新 Y / 禁用 Z」，真写就必须是同一组条目——
口径一旦分叉，用户在预览里看到的数字就成了摆设。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from fixtext_vocab import ACT_IMPORT_BATCH, ACT_IMPORT_FAILED

from . import messages as msg
from .groups import EFFECT_ADD, EFFECT_DISABLED, EFFECT_SKIPPED, EFFECT_UPDATE

__all__ = [
    "BatchWriteError", "human_reason", "plan_batch", "verify_batch",
    "write_batch", "undo_batch", "batch_label",
    "ACT_IMPORT_BATCH", "ACT_IMPORT_FAILED",
]

# 动作代号只有一处定义：``fixtext_vocab.ACT_IMPORT_BATCH`` / ``ACT_IMPORT_FAILED``
# （人话名字同在 ``fixtext_vocab.ACT_NAMES``）。这里只做转出，避免两份字符串各写一遍、
# 改一处忘一处的漂移。


class BatchWriteError(RuntimeError):
    """一次批量写入没完成。

    ``reason`` 已经是人话（界面直接显示，不再二次翻译）；``stage`` 说明卡在哪一步
    （``prepare`` 折叠清单 / ``write`` 落盘 / ``verify`` 写完核对 / ``rollback`` 回退），
    用于验收与排查，不上界面。
    """

    def __init__(self, reason: str, *, stage: str = "", detail: dict | None = None):
        super().__init__(reason)
        self.reason = str(reason)
        self.stage = str(stage)
        self.detail = dict(detail or {})


# ---------------------------------------------------------------------------
# 清单 → 提交后的整份条目表
# ---------------------------------------------------------------------------

def plan_batch(store, rows) -> dict:
    """把 ``write_list()`` 折成「提交后的整份条目表 + 要关掉的词条」。

    只在内存里折叠，一个字节都不写盘：真正落盘是下一步**一次**原子替换。
    折叠规则逐条对齐 ``rehearsal.write_plan_entries``（见模块头）。

    返回 ``entries``（提交后的完整条目表，顺序＝原顺序 + 新条目追加）、
    ``added`` / ``updated`` / ``disabled_pairs`` / ``skipped``、``before_count`` / ``new``。
    """
    rows = [dict(r) for r in (rows or [])]
    for i, r in enumerate(rows, start=1):
        if not str(r.get("word") or "").strip() or not str(r.get("value") or "").strip():
            raise BatchWriteError(msg.batch_row_incomplete(i), stage="prepare",
                                  detail=dict(line_no=r.get("line_no")))

    entries = [dict(e) for e in store.custom.entries()]
    before_count = len(entries)
    by_id = {int(e["id"]): e for e in entries}
    nid = max(by_id.keys(), default=0) + 1
    added: list[dict] = []
    updated: list[dict] = []
    disabled_pairs: list[tuple[str, str]] = []
    skipped: list[dict] = []

    for r in rows:
        effect = str(r.get("effect") or EFFECT_ADD)
        word = str(r.get("word") or "").strip()
        value = str(r.get("value") or "").strip()
        typ = str(r.get("typ") or "").strip() or "错词校正"
        pinyin = str(r.get("pinyin") or "").strip()
        target = int(r.get("update_target") or 0)

        if effect == EFFECT_SKIPPED:
            # 「跳过」不进写入清单是本卡的输入契约（`write_list()` 已经滤过一遍）。
            # 万一有人绕过去硬塞进来，这里也不写——与预演同一条闸。
            skipped.append(dict(line_no=r.get("line_no"), word=word, value=value))
            continue

        if effect == EFFECT_UPDATE:
            hit = by_id.get(target)
            if hit is None:
                raise BatchWriteError(msg.batch_update_target_missing(word), stage="prepare",
                                      detail=dict(line_no=r.get("line_no"), target=target))
            # 与 ``CustomVocab.update(target, value=...)`` 同口径：只改值，
            # 词 / 类型 / 注音 / 归属保持原样。
            hit["value"] = value
            updated.append(dict(hit))
            continue

        if effect == EFFECT_DISABLED and target:
            # 库里本来就有这一条：禁用的就是它，不能再写一条同词同值的重复条目
            # （写进去词库页会多出一行废数据，预演的 measured_new 也会多 1）。
            disabled_pairs.append((word, value))
            continue

        new = dict(id=nid, word=word, value=value, type=typ, pinyin=pinyin, book="",
                   created_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        entries.append(new)
        by_id[nid] = new
        nid += 1
        added.append(dict(new))
        if effect == EFFECT_DISABLED:
            disabled_pairs.append((word, value))

    return dict(entries=entries, added=added, updated=updated,
                disabled_pairs=disabled_pairs, skipped=skipped,
                before_count=before_count, new=len(entries) - before_count,
                write=len(added) + len(updated) + len(disabled_pairs))


# ---------------------------------------------------------------------------
# 写完核对（从磁盘读回来，不看内存）
# ---------------------------------------------------------------------------

def verify_batch(store, plan: dict, rows=None) -> dict:
    """写完从磁盘读回来逐项核对，返回 ``{ok, reason, checks}``。

    必须**真读盘**：内存里的 ``raw_bytes`` 已是「我以为写出去的字节」，
    拿它跟自己比永远对得上——那道闸等于没有。所以这里只看文件系统里的内容。

    核对四件事（前两项是「没落半批」，后两项是「写对了东西」）：

    1. 磁盘上的整份字节与本次要写的字节一致（原子替换真的生效，不是截断的文件）；
    2. 内容能读通、条目条数与提交表一致；
    3. 每一条新增 / 更新都在，且值就是清单里的值；
    4. 该关掉的词条确实关掉了（读禁用集接口，不是数文件）。
    """
    checks: dict[str, str] = {}
    want_raw = plan.get("raw")
    path = Path(store.custom.path)
    disk = _read_bytes(path)
    if disk is None:
        return dict(ok=False, reason=msg.verify_file_missing(), checks=checks)

    checks["whole_file"] = "ok" if disk == want_raw else "differs"
    if disk != want_raw:
        return dict(ok=False, reason=msg.verify_incomplete_write(), checks=checks)

    try:
        data = json.loads(disk.decode("utf-8"))
        filed = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
    except (UnicodeDecodeError, ValueError, AttributeError):
        checks["readable"] = "broken"
        return dict(ok=False, reason=msg.verify_unreadable(), checks=checks)

    checks["readable"] = "ok"
    if len(filed) != len(plan["entries"]):
        checks["count"] = f"{len(filed)}/{len(plan['entries'])}"
        return dict(ok=False,
                    reason=msg.verify_count_mismatch(len(filed), len(plan["entries"])),
                    checks=checks)

    got = {int(e.get("id") or 0): (str(e.get("word") or ""), str(e.get("value") or ""))
           for e in filed}
    for e in plan["entries"]:
        want = (str(e["word"]), str(e["value"]))
        if got.get(int(e["id"])) != want:
            checks["content"] = f"id={e['id']}"
            return dict(ok=False, reason=msg.verify_content_mismatch(str(e["word"])),
                        checks=checks)
    checks["content"] = "ok"

    for w, v in plan["disabled_pairs"]:
        if not store.states.is_disabled(w, v):
            checks["disabled"] = f"{w} → {v}"
            return dict(ok=False, reason=msg.verify_disabled_missing(w), checks=checks)
    checks["disabled"] = "ok" if plan["disabled_pairs"] else "n/a"
    return dict(ok=True, reason="", checks=checks)


# ---------------------------------------------------------------------------
# 一次事务写入
# ---------------------------------------------------------------------------

def write_batch(store, rows, *, label: str = "", source_name: str = "",
                verify: bool = True) -> dict:
    """把一整批词条写进自定义词库：一个还原点、一次落盘、写完自证。

    :param store: ``VocabStore``（唯一词库入口）
    :param rows: ``PreviewModel.write_list()`` 的输出
    :param label: 还原点 / 操作历史里的摘要（默认按条数拼）
    :param source_name: 这次导入来自哪张表（只进操作历史的详情，不上界面）
    :param verify: 写完是否读盘核对（正常路径必须开；关掉只用于排查）
    :return: ``{write, add, update, disabled, skipped, new, before_count, after_count,
                point_id, label, sha_before, sha_after, verify, identical}``

    失败一律抛 :class:`BatchWriteError`，并且**要么词库已回到导入前（还原点撤掉），
    要么还原点留着让用户还能撤销**——两种结局都在 ``exc.detail`` 里说清是哪种，
    不许出现「文件改了、又没人能退」的第三种。
    """
    plan = plan_batch(store, rows)                      # 折叠清单（可能抛人话错误）
    if plan["write"] <= 0:
        raise BatchWriteError(msg.batch_empty(), stage="prepare")

    label = label or batch_label(plan["write"])
    before_raw = store.custom.raw_bytes()               # 写前备份
    before_states = store.states.raw_bytes()
    before_sha = _sha_bytes(before_raw)

    # ① 写入前建快照——与单条操作同一个 SnapshotStore，历史面板立刻能看到这一条
    pid = store.snap.begin(label=label, act=ACT_IMPORT_BATCH, before_bytes=before_raw,
                           words_before=before_states)
    try:
        # ② 一次落盘：编码一次、原子替换一次。中途出错 → 要么旧文件完整，
        #    要么新文件完整，不存在「写了一半」的词库（其余靠下面的回退）。
        plan["raw"] = store.custom.replace_all(plan["entries"])
        if plan["disabled_pairs"]:
            store.states.set_enabled(plan["disabled_pairs"], enabled=False)
        # ③ 写完自证：从磁盘读回来核对，不看内存
        report = (verify_batch(store, plan, rows) if verify
                  else dict(ok=True, reason="", checks={}))
        if not report.get("ok"):
            raise BatchWriteError(report.get("reason") or msg.verify_generic(),
                                  stage="verify",
                                  detail=dict(checks=report.get("checks"))
                                  )
    except Exception as exc:                            # 含上面主动抛的核对失败
        _fail(store, exc, pid=pid, label=label, before_raw=before_raw,
              before_states=before_states, before_sha=before_sha, plan=plan,
              source_name=source_name)                  # 一律抛，不返回到这里
        raise                                          # pragma: no cover 防御性

    after_raw = store.custom.raw_bytes()
    rec = store.snap.commit(pid, after_bytes=after_raw, words_after=store.states.raw_bytes())
    store.snap.log_op(act=ACT_IMPORT_BATCH, summary=label, point_id=pid,
                      sha_before=rec.get("sha_before", before_sha),
                      sha_after=rec.get("sha_after", ""),
                      detail=dict(source=source_name, write=plan["write"],
                                  add=len(plan["added"]), update=len(plan["updated"]),
                                  disabled=len(plan["disabled_pairs"]),
                                  skipped=len(plan["skipped"]), new=plan["new"]))
    return dict(write=plan["write"],
                add=len(plan["added"]), update=len(plan["updated"]),
                disabled=len(plan["disabled_pairs"]), skipped=len(plan["skipped"]),
                new=plan["new"], before_count=plan["before_count"],
                after_count=plan["before_count"] + plan["new"],
                point_id=int(pid), label=label,
                sha_before=rec.get("sha_before", before_sha),
                sha_after=rec.get("sha_after", ""),
                verify=report,
                identical=bool(rec.get("sha_after") and
                               rec.get("sha_after") == _sha_bytes(after_raw)))


def _fail(store, exc, *, pid: int, label: str, before_raw: bytes, before_states: bytes,
          before_sha: str, plan: dict, source_name: str) -> None:
    """失败收尾：先把词库整份还原，再决定还原点是撤掉还是留着让用户撤销。"""
    reason = exc.reason if isinstance(exc, BatchWriteError) else human_reason(exc)
    stage = exc.stage if isinstance(exc, BatchWriteError) else "write"

    rollback_ok, rollback_err = _rollback(store, before_raw, before_states, before_sha)
    if rollback_ok:
        # 文件已逐字节回到导入前：这次尝试不留还原点（否则历史里会多一个
        # 「点了却什么都没变」的空时间点，撤销一次还在原地）。
        try:
            store.snap.abort(int(pid))
        except Exception:                               # noqa: BLE001 收尾失败不掩盖主因
            pass
        _log_failure(store, act=ACT_IMPORT_FAILED,
                     summary=msg.import_failed_log(label, reason),
                     before_sha=before_sha, source_name=source_name, stage=stage,
                     plan=plan, rolled_back=True)
        raise BatchWriteError(msg.failed(reason), stage=stage,
                              detail=dict(rolled_back=True, rollback_error="",
                                          byte_identical=(_disk_bytes_sha(store) == before_sha),
                                          write=plan["write"]))

    # 回退本身失败：不许假装成功。还原点留着（它的「操作前」字节就是导入前那份），
    # 用户仍能在词库页点「撤销」退回去。
    _log_failure(store, act=ACT_IMPORT_FAILED,
                 summary=msg.import_failed_manual_log(label),
                 before_sha=before_sha, source_name=source_name, stage=stage,
                 plan=plan, rolled_back=False, rollback_error=rollback_err)
    raise BatchWriteError(msg.failed_manual(reason), stage="rollback",
                          detail=dict(rolled_back=False, point_id=int(pid),
                                      rollback_error=rollback_err, write=plan["write"]))


def _log_failure(store, *, act: str, summary: str, before_sha: str, source_name: str,
                 stage: str, plan: dict, rolled_back: bool, rollback_error: str = "") -> None:
    """把这次「没写成」记进操作历史（记不上不影响结论：失败提示本身仍要给人看）。"""
    try:
        store.snap.log_op(act=act, summary=summary, sha_before=before_sha,
                          sha_after=_disk_bytes_sha(store),
                          detail=dict(source=source_name, stage=stage,
                                      rolled_back=bool(rolled_back),
                                      rollback_error=rollback_error,
                                      write=plan.get("write", 0)))
    except Exception:                                   # noqa: BLE001
        pass


def _rollback(store, before_raw: bytes, before_states: bytes, before_sha: str) -> tuple[bool, str]:
    """把词库与禁用集整份写回「操作前」字节，并**从磁盘**确认真的回去了。"""
    errs: list[str] = []
    try:
        store.states.restore(before_states)
    except Exception as exc:                            # noqa: BLE001
        errs.append(f"states:{type(exc).__name__}")
    try:
        store.custom.restore(before_raw)
    except Exception as exc:                            # noqa: BLE001
        errs.append(f"vocab:{type(exc).__name__}")
    try:
        disk = _read_bytes(Path(store.custom.path))
        same_file = disk == before_raw
        same_states = store.states.raw_bytes() == before_states
    except Exception as exc:                            # noqa: BLE001
        return False, f"verify:{type(exc).__name__}"
    ok = bool(same_file and same_states and _sha_bytes(disk or b"") == before_sha)
    return ok, "" if ok else (";".join(errs) or "字节未回到导入前")


def undo_batch(store, point_id: int) -> dict | None:
    """整批撤销：一次调用把这一批导入整批退回去（**复用既有撤销栈**）。

    两条既有原语按位置选，不走第三套逻辑：

    * 这一批就是最新一步 → ``store.undo()``（与词库页「撤销」按钮完全同一个动作）；
    * 后面又改过别的东西 → ``store.undo_to(index)``（把它及之后一并退回它之前）。

    两条路径都写回该还原点的「操作前」字节，所以撤销后的文件与导入前**逐字节**相同。
    返回 ``{label, sha, expected_sha, identical, point_id, via}``；找不到该点返回 ``None``。
    """
    point = store.snap.get(int(point_id))
    if point is None:
        return None
    newest = store.snap.newest_undoable()
    if newest is not None and int(newest["id"]) == int(point_id):
        rec = store.undo()
        if rec is None:
            return None
        return dict(rec, via="undo")

    alive = [r for r in store.snap.points() if not r["undone"]]
    idx = next((i for i, r in enumerate(alive) if int(r["id"]) == int(point_id)), None)
    if idx is None:
        return None
    rec = store.undo_to(int(idx))
    if rec is None:
        return None
    return dict(rec, via="undo_to")


# ---------------------------------------------------------------------------
# 人话
# ---------------------------------------------------------------------------

def batch_label(write: int) -> str:
    """还原点 / 操作历史里这一批的摘要（界面不出现任何内部路径或代号）。"""
    return msg.import_label(int(write))


def human_reason(exc: BaseException) -> str:
    """写失败时按异常类型给人的说法（不出现异常类名、文件名或技术细节）。"""
    import errno

    if isinstance(exc, BatchWriteError):
        return exc.reason
    if isinstance(exc, PermissionError):
        return msg.fail_permission()
    if isinstance(exc, OSError):
        code = getattr(exc, "errno", None)
        if code == errno.ENOSPC:
            return msg.fail_no_space()
        if code == errno.EROFS:
            return msg.fail_readonly()
        return msg.fail_io()
    return msg.fail_unknown()


def _read_bytes(path: Path) -> bytes | None:
    try:
        p = Path(path)
        if not p.is_file():
            return None
        return p.read_bytes()
    except OSError:
        return None


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _disk_bytes_sha(store) -> str:
    disk = _read_bytes(Path(store.custom.path))
    return _sha_bytes(disk) if disk is not None else ""
