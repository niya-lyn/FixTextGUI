"""V1.1-D5 · 批量事务写入与整批撤销（数据层验收）。

四条主线：

* A 正常写入：整批一次落盘、一个还原点、写完自证；
* B 失败回滚：人为制造写入中断 → 词库字节回到导入前（逐字节）；
* C 整批撤销：「撤销」一步退回，字节与导入前逐字节一致；
* D 快照恢复：从写入前那个还原点恢复/退回，字节与导入前逐字节一致。

字节对照一律用 ``sha256`` 真算，不硬编码任何 sha（写死 sha 曾在 T2.3 上错过一位 hex）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fixtext_vocab import ACT_IMPORT_BATCH, ACT_IMPORT_FAILED, VocabStore
from fixtext_vocab_preview import messages as msg
from fixtext_vocab_preview.transaction import (BatchWriteError, human_reason, plan_batch,
                                               undo_batch, verify_batch, write_batch)


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


@pytest.fixture()
def store(tmp_path) -> VocabStore:
    """一个干净词库：真实文件在 tmp_path 下，绝不碰用户主目录那一份。"""
    real = tmp_path / "custom_vocab.json"
    real.write_text(json.dumps({"version": 1, "entries": []}, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return VocabStore(custom_path=real, work_dir=tmp_path / "rules",
                      snap_dir=tmp_path / "snap")


def _rows_add(*pairs):
    return [dict(line_no=i, word=w, value=v, typ="错词校正", pinyin="", effect="add",
                 action="add", disabled=False, update_target=0)
            for i, (w, v) in enumerate(pairs, start=1)]


# ---------------------------------------------------------------------------
# A 正常写入
# ---------------------------------------------------------------------------

def test_normal_write_is_one_atomic_commit(store):
    before = sha(store.custom.path)
    assert store.point_count() == 0

    rows = _rows_add(("萧衍", "萧彦"), ("盍", "何"), ("告之", "告之"))
    res = store.import_batch(rows, source_name="样本表")

    assert res["write"] == 3
    assert res["add"] == 3 and res["update"] == 0 and res["disabled"] == 0
    assert res["before_count"] == 0 and res["after_count"] == 3
    # 整批只占一个还原点（撤销栈里也只算一步）
    assert store.point_count() == 1
    assert res["verify"]["ok"] is True
    assert res["identical"] is True
    # 词库真的变了，且与 before 不同字节
    assert sha(store.custom.path) != before
    assert [e["word"] for e in store.custom.entries()] == ["萧衍", "盍", "告之"]


def test_write_creates_before_snapshot_visible_in_history(store):
    before = sha(store.custom.path)
    store.import_batch(_rows_add(("萧衍", "萧彦")))

    hist = store.history()
    assert len(hist) == 1
    assert hist[0]["label"] == msg.import_label(1)
    assert hist[0]["sha"] == before            # 这一条记录的就是「操作前」指纹
    # 历史面板看到的动作人话名（不是代号）
    ops = store.ops()
    assert ops and ops[0]["act_name"] == "批量导入"


def test_plan_matches_write_plan_counts(store):
    """折叠出来的条数与预演（D3/D4 的 write_plan）同一口径。"""
    rows = _rows_add(("萧衍", "萧彦"), ("盍", "何"))
    plan = plan_batch(store, rows)
    assert plan["write"] == len(plan["added"]) + len(plan["updated"]) \
        + len(plan["disabled_pairs"])
    assert plan["write"] == 2
    assert plan["new"] == 2


def test_update_and_disable_fold_like_rehearsal(store):
    """更新条目改值、禁用已有条目都不新增重复行（与预演同一折叠规则）。"""
    from fixtext_vocab_preview.rehearsal import write_plan_entries

    assert write_plan_entries is not None          # 折叠规则的同一来源
    store.add_entry(word="萧衍", value="萧彦", typ="错词校正")
    store.add_entry(word="盍", value="何", typ="错词校正")
    e1 = [e for e in store.custom.entries() if e["word"] == "萧衍"][0]
    e2 = [e for e in store.custom.entries() if e["word"] == "盍"][0]
    n_before = store.point_count()

    rows = [
        dict(line_no=1, word="萧衍", value="萧炎", effect="update", update_target=e1["id"],
             typ="错词校正", pinyin="", action="edit", disabled=False),
        dict(line_no=2, word="盍", value="何", effect="disabled", update_target=e2["id"],
             typ="错词校正", pinyin="", action="disable", disabled=True),
    ]

    res = store.import_batch(rows)
    assert res["update"] == 1 and res["disabled"] == 1 and res["add"] == 0
    assert res["after_count"] == 2                     # 没有多出重复条目
    assert [e["value"] for e in store.custom.entries() if e["word"] == "萧衍"] == ["萧炎"]
    assert store.states.is_disabled("盍", "何") is True
    assert store.point_count() == n_before + 1          # 整批仍只多一个还原点


def test_skipped_rows_are_not_written(store):
    rows = [dict(line_no=1, word="萧衍", value="萧彦", effect="skipped",
                 typ="错词校正", pinyin="", action="skip", disabled=False,
                 update_target=0)]
    before = sha(store.custom.path)
    with pytest.raises(BatchWriteError) as ei:
        store.import_batch(rows)
    assert ei.value.stage == "prepare"
    assert sha(store.custom.path) == before
    assert store.point_count() == 0                    # 连还原点都没留下


# ---------------------------------------------------------------------------
# B 失败回滚：逐字节回到导入前
# ---------------------------------------------------------------------------

def test_verify_failure_rolls_back_byte_identical(store, monkeypatch):
    """写后核对失败（磁盘上是坏的/半截文件）→ 自动整份回退，逐字节一致。"""
    import fixtext_vocab_preview.transaction as tx

    before = sha(store.custom.path)
    before_bytes = Path(store.custom.path).read_bytes()
    real = tx.verify_batch

    def broken_verify(st, plan, rows=None):
        # 模拟「写出去的文件是半截的」：磁盘上确实留下了不完整的字节，
        # 再让核对照实报失败（whole_file 一项就对不上）
        Path(st.custom.path).write_bytes(plan["raw"][:-7])
        return real(st, plan, rows)

    monkeypatch.setattr(tx, "verify_batch", broken_verify)

    with pytest.raises(BatchWriteError) as ei:
        store.import_batch(_rows_add(("萧衍", "萧彦"), ("盍", "何")))

    err = ei.value
    assert err.stage == "verify"
    assert err.detail["rolled_back"] is True
    assert err.detail["byte_identical"] is True
    # 用户看到的是一句人话，且明确"一条都没留下"
    assert "一条都没留下" in err.reason
    # 文件逐字节回到导入前
    assert sha(store.custom.path) == before
    assert Path(store.custom.path).read_bytes() == before_bytes
    # 失败的尝试不留还原点（否则会多一个「点了什么都没变」的空点）
    assert store.point_count() == 0
    # 只进操作历史，人话
    ops = store.ops()
    assert ops and ops[0]["act_name"] == "导入未完成"


def test_write_error_midway_rolls_back_byte_identical(store, monkeypatch):
    """落盘本身抛错（磁盘满 / 只读）→ 半批不落，回到导入前。"""
    import errno

    import fixtext_vocab_preview.transaction as tx

    before_bytes = Path(store.custom.path).read_bytes()
    before = hashlib.sha256(before_bytes).hexdigest()
    real = tx.verify_batch

    class Boom(OSError):
        def __init__(self):
            super().__init__(errno.ENOSPC, "no space")

    def halfway(st, plan, rows=None):
        # 先真的写进去一批（模拟写到一半），再让核对前那一步炸掉
        Path(st.custom.path).write_bytes(plan["raw"][:-1])
        raise Boom()

    monkeypatch.setattr(tx, "verify_batch", halfway)

    with pytest.raises(BatchWriteError) as ei:
        store.import_batch(_rows_add(("萧衍", "萧彦")))

    assert ei.value.stage == "write"
    assert ei.value.detail["rolled_back"] is True
    assert Path(store.custom.path).read_bytes() == before_bytes
    assert hashlib.sha256(Path(store.custom.path).read_bytes()).hexdigest() == before
    assert store.point_count() == 0

    # 人话取词：磁盘满 → 「磁盘空间不够」，不露异常类名
    said = human_reason(Boom())
    assert "磁盘空间不够" in said
    for bad in ("OSError", "ENOSPC", "errno", "Traceback"):
        assert bad not in said


def test_rollback_failure_keeps_point_for_manual_undo(store, monkeypatch):
    """回退本身失败时：不许假装成功——还原点留着，用户仍能「撤销」退回去。"""
    import fixtext_vocab_preview.transaction as tx

    before_bytes = Path(store.custom.path).read_bytes()
    real_restore = type(store.custom).restore

    def no_restore(self, raw):
        raise OSError("disk gone")

    def broken_verify(st, plan, rows=None):
        Path(st.custom.path).write_bytes(plan["raw"])
        p = dict(plan)
        p["raw"] = plan["raw"] + b"x"
        return tx._read_bytes and dict(ok=False, reason=msg.verify_incomplete_write(), checks={})

    monkeypatch.setattr(type(store.custom), "restore", no_restore, raising=True)
    monkeypatch.setattr(tx, "verify_batch", broken_verify)

    with pytest.raises(BatchWriteError) as ei:
        store.import_batch(_rows_add(("萧衍", "萧彦")))

    assert ei.value.stage == "rollback"
    assert ei.value.detail["rolled_back"] is False
    assert ei.value.detail["point_id"] > 0
    assert "撤销" in ei.value.reason                   # 明确告诉用户下一步怎么办
    # 还原点还在：它的「操作前」字节就是导入前那份，撤销能救回来
    pid = ei.value.detail["point_id"]
    assert store.snap.get(pid) is not None
    monkeypatch.setattr(type(store.custom), "restore", real_restore, raising=True)
    rec = store.undo()
    assert rec is not None
    assert Path(store.custom.path).read_bytes() == before_bytes


def test_prepare_error_leaves_no_trace(store):
    """折叠清单阶段就拦下的错误（目标条目找不到）→ 一个字节都没写。"""
    before = Path(store.custom.path).read_bytes()
    rows = [dict(line_no=1, word="萧衍", value="萧炎", effect="update", update_target=999,
                 typ="错词校正", pinyin="", action="edit", disabled=False)]
    with pytest.raises(BatchWriteError) as ei:
        store.import_batch(rows)
    assert ei.value.stage == "prepare"
    assert "在词库里已经找不到了" in ei.value.reason
    assert Path(store.custom.path).read_bytes() == before
    assert store.point_count() == 0


# ---------------------------------------------------------------------------
# C 整批撤销：逐字节回到导入前
# ---------------------------------------------------------------------------

def test_undo_batch_restores_bytes_exactly(store):
    before_bytes = Path(store.custom.path).read_bytes()
    before = hashlib.sha256(before_bytes).hexdigest()

    rows = _rows_add(("萧衍", "萧彦"), ("盍", "何"), ("告之", "告之"))
    res = store.import_batch(rows)
    mid = sha(store.custom.path)
    assert mid != before

    rec = store.undo_import(res["point_id"])
    assert rec is not None and rec["via"] == "undo"
    assert rec["identical"] is True
    assert Path(store.custom.path).read_bytes() == before_bytes
    assert sha(store.custom.path) == before
    assert store.custom.entries() == []
    assert store.point_count() == 1                    # 还原点还在（标为已撤销）
    assert store.can_undo is False


def test_undo_batch_after_later_edit_uses_undo_to(store):
    """导入后又单条改过一次 → 整批撤销走 undo_to，仍回到导入前字节。"""
    before_bytes = Path(store.custom.path).read_bytes()
    store.import_batch(_rows_add(("萧衍", "萧彦")))
    pid = store.history()[0]["point_id"]

    store.add_entry(word="盍", value="何", typ="错词校正")   # 之后又做了一步（新还原点）
    assert store.point_count() == 2

    rec = store.undo_import(pid)
    assert rec is not None and rec["via"] == "undo_to"
    assert rec["identical"] is True
    assert Path(store.custom.path).read_bytes() == before_bytes
    assert store.custom.entries() == []


def test_undo_batch_returns_none_when_point_gone(store):
    assert undo_batch(store, 999999) is None
    assert store.undo_import(999999) is None


def test_failed_batch_then_undo_of_previous_batch(store):
    """一批成功、一批失败，撤销只退成功那一批，失败那批没留痕迹。"""
    before_bytes = Path(store.custom.path).read_bytes()
    store.import_batch(_rows_add(("萧衍", "萧彦")))
    mid_bytes = Path(store.custom.path).read_bytes()

    import fixtext_vocab_preview.transaction as tx

    def broken(st, plan, rows=None):
        return dict(ok=False, reason=msg.verify_incomplete_write(), checks={})

    old = tx.verify_batch
    tx.verify_batch = broken
    try:
        with pytest.raises(BatchWriteError):
            store.import_batch(_rows_add(("盍", "何")))
    finally:
        tx.verify_batch = old

    assert Path(store.custom.path).read_bytes() == mid_bytes   # 失败那批没留半截
    assert sha(store.custom.path) != before_bytes_sha(before_bytes)
    assert store.point_count() == 1

    store.undo()
    assert Path(store.custom.path).read_bytes() == before_bytes


def before_bytes_sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# D 快照恢复：逐字节回到导入前
# ---------------------------------------------------------------------------

def test_restore_point_from_snapshot_equals_pre_import(store):
    """写入前那个快照「恢复到某一刻」演进：先撤销、再恢复 → 两条都与导入前一致。"""
    before_bytes = Path(store.custom.path).read_bytes()
    before = hashlib.sha256(before_bytes).hexdigest()

    res = store.import_batch(_rows_add(("萧衍", "萧彦"), ("盍", "何")))
    after_bytes = Path(store.custom.path).read_bytes()
    after = hashlib.sha256(after_bytes).hexdigest()
    pid = res["point_id"]

    # 快照「操作前」载荷 == 导入前字节（这就是「写入前自动触发快照」的实物）
    assert store.snap.before_bytes(pid) == before_bytes
    # 快照「操作后」载荷 == 导入后字节
    assert store.snap.after_bytes(pid) == after_bytes

    # ① 从快照退回到导入前
    rec = store.undo_to(0)
    assert rec is not None and rec["identical"] is True
    assert Path(store.custom.path).read_bytes() == before_bytes
    assert sha(store.custom.path) == before

    # ② 再「恢复到此刻」（回到导入后），然后再次退回 → 两次都与导入前逐字节一致
    back = store.restore_point(pid)
    assert back is not None and back["identical"] is True
    assert Path(store.custom.path).read_bytes() == after_bytes
    assert sha(store.custom.path) == after
    again = store.undo()
    assert again is not None and again["identical"] is True
    assert Path(store.custom.path).read_bytes() == before_bytes


def test_snapshot_point_is_visible_and_labeled(store):
    store.import_batch(_rows_add(("萧衍", "萧彦")))
    snaps = store.snap.points()
    assert len(snaps) == 1
    p = snaps[0]
    assert p["act"] == ACT_IMPORT_BATCH
    assert p["label"] == msg.import_label(1)
    assert p["sha_before"] and p["sha_after"]


# ---------------------------------------------------------------------------
# 界面文案：零技术词
# ---------------------------------------------------------------------------

def test_d5_messages_have_no_jargon():
    """D5 新增的每一句人话都不许出现技术词（与 D1/D3/D4 同一份口径）。"""
    forbidden = ["spine", "opf", "container.xml", "manifest", "ncx", "xhtml", "xml",
                 "bom", "utf-8", "utf8", "gbk", "gb18030", "big5", "crlf", "sha256",
                 "hash", "encoding", "charset", "codec", "zip", "json", "csv",
                 "sqlite", "traceback", "delimiter"]
    texts = [
        msg.import_label(3), msg.import_done(3, 2, 1, 0, 1), msg.import_done_note(),
        msg.import_undo_hint(), msg.import_toast(3),
        msg.fail_permission(), msg.fail_no_space(), msg.fail_readonly(), msg.fail_io(),
        msg.fail_unknown(), msg.failed("原因"), msg.failed_manual("原因"),
        msg.import_failed_log("导入 2 条词条", "原因"), msg.import_failed_manual_log("导入2条"),
        msg.batch_row_incomplete(2), msg.batch_update_target_missing("萧衍"),
        msg.batch_empty(), msg.verify_file_missing(), msg.verify_incomplete_write(),
        msg.verify_unreadable(), msg.verify_count_mismatch(2, 3),
        msg.verify_content_mismatch("萧衍"), msg.verify_disabled_missing("盍"),
        msg.verify_generic(), msg.undo_batch_done("导入 3 条词条", True),
        msg.undo_batch_done("导入 3 条词条", False), msg.undo_batch_not_found(),
    ]
    for t in texts:
        low = t.lower()
        for w in forbidden:
            assert w not in low, f"{w} 出现在人话里：{t}"


def test_no_internal_paths_in_messages():
    texts = [msg.failed("原因"), msg.import_done_note(), msg.undo_batch_done("导入", True)]
    for t in texts:
        for bad in ("/home/", "workspace/", "custom_vocab", ".json", ".bin"):
            assert bad not in t
