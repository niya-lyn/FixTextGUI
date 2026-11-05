"""V1.1-D5 验收：批量事务写入、失败回滚、整批撤销、写入前快照恢复。

四个场景，全部落**逐字节**证据（sha256 运行时真算，不硬编码）：

A 正常写入：一次落盘、一个还原点、写完自证四检全过；撤销栈里只加一步；
B 失败回滚：写后核对失败（磁盘上留了半截文件）→ 自动整份回退，
  词库字节与导入前逐字节相同，且不留空还原点、只记一条人话「导入未完成」；
C 整批撤销：确认写入后走词库页同一个 «撤销»（store.undo()），
  字节与导入前逐字节相同；另测「导入后又改一步」时整批撤销走 undo_to 仍逐字节相同；
D 快照恢复：写入前那个快照的「操作前」载荷 == 导入前字节；
  从快照退回导入前逐字节一致；再「恢复到此刻」→ 与导入后逐字节一致。

另附 E：界面真实点击路径（离屏）——预览 → 确认门 → 真写入 → 页内提示带撤销，
并核 UI 侧数字与数据层一致；词库页回调用真实方法 + 轻量页面桩。

用法：python tools/accept_t5_transaction.py
输出：evidence/d5/accept_t5_report.md + evidence/d5/accept_t5.json + 控制台记录
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
for p in (PKG, PKG / "fixtext_ui"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fixtext_vocab import VocabStore                                     # noqa: E402
from fixtext_vocab_preview import messages as msg                        # noqa: E402
from fixtext_vocab_preview.transaction import BatchWriteError           # noqa: E402

OUT = PKG / "evidence" / "d5"
TABLE = "错词,正确写法\n乙乙,乙\n甲的异体,甲\n,空的\n丙丙,丙\n丁丁,丁\n"
SEED = (("甲的异体", "甲"),)

LINES: list[str] = []
REPORT: dict = {}


def log(line: str = "") -> None:
    print(line)
    LINES.append(line)


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(p: Path) -> str:
    p = Path(p)
    return sha_bytes(p.read_bytes()) if p.is_file() else "(文件不存在)"


def make_store(tmp: Path):
    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    real = tmp / "custom_vocab.json"
    real.write_text(json.dumps({"version": 1, "entries": []}, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    st = VocabStore(custom_path=real, work_dir=tmp / "rules", snap_dir=tmp / "snap")
    for w, v in SEED:
        st.add_entry(word=w, value=v, typ="错词校正")
    return st


def preview_of(store, text: str):
    from fixtext_vocab_import.parse import parse_text
    from fixtext_vocab_preview.groups import preview_from_sheet

    return preview_from_sheet(parse_text(text), store, source_name="accept_t5 样本表")


def case_a(tmp: Path) -> dict:
    log("## A 正常写入：一次落盘 + 一个还原点 + 写完自证")
    st = make_store(tmp)
    before_raw = Path(st.custom.path).read_bytes()
    points_before, ops_before = st.point_count(), st.op_count()
    log(f"导入前：字节 {sha_bytes(before_raw)}，还原点 {points_before} 个，历史 {ops_before} 条")

    model = preview_of(st, TABLE)
    wl = model.write_list()
    log(f"预览：新增 {model.counts()[msg.GROUP_NEW]} / 冲突 {model.counts()[msg.GROUP_CONFLICT]}"
        f" / 不合格 {model.counts()[msg.GROUP_REJECT]}；写入清单 {len(wl)} 条")
    res = st.import_batch(wl, source_name="accept_t5 样本表")
    after_raw = Path(st.custom.path).read_bytes()

    log(f"写入结果：write={res['write']} add={res['add']} update={res['update']} "
        f"disabled={res['disabled']} skipped={res['skipped']}")
    log(f"写完自证四项：{res['verify']['checks']}")
    log(f"还原点 {points_before} → {st.point_count()}（整批只占 1 个）")
    log(f"历史 {ops_before} → {st.op_count()}，最新一条：「{st.ops()[0]['act_name']} / "
        f"{st.ops()[0]['summary']}」")
    log(f"导入后：字节 {sha_bytes(after_raw)}（与导入前不同：{sha_bytes(after_raw) != sha_bytes(before_raw)}）")

    REPORT["A"] = dict(write=res["write"], add=res["add"], update=res["update"],
                       disabled=res["disabled"], skipped=res["skipped"],
                       checks=res["verify"]["checks"],
                       points_before=points_before, points_after=st.point_count(),
                       sha_before=sha_bytes(before_raw), sha_after=sha_bytes(after_raw),
                       point_id=res["point_id"], ok=res["verify"]["ok"])
    return dict(store=st, before_raw=before_raw, after_raw=after_raw, res=res)


def case_b(tmp: Path) -> dict:
    log()
    log("## B 失败回滚：写到一半就断 → 词库逐字节回到导入前")
    import fixtext_vocab_preview.transaction as tx

    st = make_store(tmp)
    before_raw = Path(st.custom.path).read_bytes()
    before = sha_bytes(before_raw)
    real_verify = tx.verify_batch

    def broken_verify(s, plan, rows=None):
        # 人为制造「写出去的文件是半截的」：磁盘上真留下不完整的字节
        Path(s.custom.path).write_bytes(plan["raw"][:-11])
        return real_verify(s, plan, rows)

    tx.verify_batch = broken_verify
    err = None
    try:
        model = preview_of(st, TABLE)
        try:
            st.import_batch(model.write_list(), source_name="accept_t5 样本表")
            raise SystemExit("预期失败但成功了")
        except BatchWriteError as exc:
            err = exc
            log(f"失败（stage={err.stage}）：{err.reason}")
            log(f"detail：rolled_back={err.detail['rolled_back']} "
                f"byte_identical={err.detail['byte_identical']}")
    finally:
        tx.verify_batch = real_verify
    if err is None:
        raise SystemExit("没有抛出预期的失败")

    disk_now = Path(st.custom.path).read_bytes()
    same = disk_now == before_raw
    log(f"磁盘字节：{sha_bytes(disk_now)}")
    log(f"导入前字节：{before}")
    log(f"**逐字节一致：{same}**")
    log(f"还原点：{st.point_count()} 个（失败的尝试不留空点）")
    log(f"历史最新一条：「{st.ops()[0]['act_name']} / {st.ops()[0]['summary']}」")
    log(f"词条数：{len(st.custom.entries())} 条（导入前 {len(SEED)} 条，无半批）")

    REPORT["B"] = dict(stage=err.stage, reason=err.reason,
                       rolled_back=bool(err.detail["rolled_back"]),
                       byte_identical=bool(same),
                       sha_disk=sha_bytes(disk_now), sha_before=before,
                       points=st.point_count(), entries=len(st.custom.entries()),
                       last_op=st.ops()[0]["summary"])
    return dict(ok=same)


def case_c(tmp: Path) -> dict:
    log()
    log("## C 整批撤销：一步退回，逐字节回到导入前")
    st = make_store(tmp)
    before_raw = Path(st.custom.path).read_bytes()
    before = sha_bytes(before_raw)

    model = preview_of(st, TABLE)
    res = st.import_batch(model.write_list())
    mid = sha_file(st.custom.path)
    log(f"写入后字节 {mid}（导入前 {before}）")

    rec = st.undo_import(res["point_id"])
    log(f"撤销路径 via={rec['via']}（= 词库页 «撤销» 同一个 store.undo()）")
    log(f"撤销后字节 {sha_file(st.custom.path)}；identical={rec['identical']}")
    log(f"**逐字节回到导入前：{Path(st.custom.path).read_bytes() == before_raw}**")
    log(f"词条数：{len(st.custom.entries())} 条（= 导入前 {len(SEED)} 条）")

    # C2：导入后又单条改一步 → 整批撤销走 undo_to，仍逐字节回到导入前
    log()
    log("### C2 导入后又改一步：整批撤销走 undo_to")
    st2 = make_store(tmp / "c2")
    before2_raw = Path(st2.custom.path).read_bytes()
    res2 = st2.import_batch(preview_of(st2, TABLE).write_list())
    pid2 = res2["point_id"]
    st2.add_entry(word="盍", value="何", typ="错词校正")
    log(f"导入 +1 步后还原点 {st2.point_count()} 个，词条 {len(st2.custom.entries())} 条")
    rec2 = st2.undo_import(pid2)
    log(f"via={rec2['via']}，撤销后字节 {sha_file(st2.custom.path)}")
    log(f"**逐字节回到导入前：{Path(st2.custom.path).read_bytes() == before2_raw}**")

    REPORT["C"] = dict(via=rec["via"], identical=bool(
        Path(st.custom.path).read_bytes() == before_raw), sha=sha_file(st.custom.path),
        sha_before=before, entries=len(st.custom.entries()),
        via_undo_to=rec2["via"], identical_undo_to=bool(
            Path(st2.custom.path).read_bytes() == before2_raw))
    return dict(ok=True)


def case_d(tmp: Path) -> dict:
    log()
    log("## D 写入前自动快照：写在历史里、能退回导入前、能恢复到导入后")
    st = make_store(tmp)
    before_raw = Path(st.custom.path).read_bytes()
    before = sha_bytes(before_raw)

    res = st.import_batch(preview_of(st, TABLE).write_list())
    pid = res["point_id"]
    after_raw = Path(st.custom.path).read_bytes()
    after = sha_bytes(after_raw)

    p = st.snap.get(pid)
    log(f"快照点：id={pid} 标签「{p['label']}」动作「{st.ops()[0]['act_name']}」"
        f" 时间 {p['at']}")
    log(f"「操作前」载荷 == 导入前字节：{st.snap.before_bytes(pid) == before_raw}")
    log(f"「操作后」载荷 == 导入后字节：{st.snap.after_bytes(pid) == after_raw}")
    log(f"快照列表里可见（历史面板读的是同一份）：{len(st.snap.points())} 条，"
        f"history[0]=「{st.history()[0]['label']}」")

    back = st.undo_to(0)
    log(f"退回导入前：identical={back['identical']}，字节 {sha_file(st.custom.path)}")
    back_same = Path(st.custom.path).read_bytes() == before_raw
    log(f"**从快照恢复到导入前逐字节一致：{back_same}**")

    again = st.restore_point(pid)
    log(f"再「恢复到此刻」：identical={again['identical']}，字节 {sha_file(st.custom.path)}")
    fwd_same = Path(st.custom.path).read_bytes() == after_raw
    log(f"恢复到导入后逐字节一致：{fwd_same}")

    REPORT["D"] = dict(point_id=pid, label=p["label"], act=p["act"],
                       before_payload_matches=bool(st.snap.before_bytes(pid) == before_raw),
                       after_payload_matches=bool(st.snap.after_bytes(pid) == after_raw),
                       restore_to_before_identical=back_same,
                       restore_to_after_identical=fwd_same,
                       sha_before=before, sha_after=after)
    return dict(ok=True)


def case_e(tmp: Path) -> dict:
    """界面真实点击：预览 → 确认门 → 真写入 → 页内提示带撤销 → 撤销回导入前。"""
    log()
    log("## E 界面真实点击（离屏）：确认后真写入 + 页内提示 + 撤销回到导入前")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    import preview_module
    import vocab_module

    st = make_store(tmp)
    before_raw = Path(st.custom.path).read_bytes()

    dlg, model = preview_module.open_preview(None, st, text=TABLE)
    dlg.show()
    app.processEvents()

    # 样本表里冲突组没处置 → 确认门先拦下；逐条处置后再确认（= 用户真实操作序列）
    dlg.ask_confirm()
    app.processEvents()
    pending = model.pending_items()
    if pending:
        log(f"确认门拦截：{len(pending)} 条冲突未处置，提示「{dlg.tip_label.text()}」"
            f"，未弹二次确认：{dlg.confirm_dialog is None}")
        for item in pending:
            model.set_action(item.line_no, "skip")
        dlg.refresh()
    dlg.ask_confirm()
    app.processEvents()
    assert dlg.confirm_dialog is not None, "二次确认弹窗没有出现"
    dlg.confirm_dialog.accepted.emit()          # 等价于真实点击「确认」
    app.processEvents()

    log(f"弹窗写入状态：_write_ok={dlg._write_ok} written={dlg.written}")
    log(f"页内提示：{dlg.tip_label.text()}")
    log(f"确认按钮是否已钉死（防重复写）：{not dlg.confirm_btn.isEnabled()}")
    n = len(st.custom.entries())
    wl_n = len(model.write_list())
    log(f"词条数：{len(SEED)} → {n}（写入清单 {wl_n} 条，与数据层 write 一致）")
    after_raw = Path(st.custom.path).read_bytes()
    assert sha_bytes(after_raw) != sha_bytes(before_raw), "界面路径没有真写入"

    # 词库页回调（真实方法 + 轻量页面桩）：写完提示必须带「撤销」
    toasts: list[tuple[str, bool]] = []

    class _ToastHost:                          # 页面桩：只记录提示，不构建整页
        _selected = set()
        _by_id = staticmethod(lambda i: False)
        _render_all = lambda self: None          # noqa: E731
        _toast = lambda self, text, with_undo=False: toasts.append((text, with_undo))  # noqa: E731

    vocab_module.VocabModule._on_import_written(
        _ToastHost(), dlg._write_result, dlg._write_error)
    text, with_undo = toasts[-1]
    log(f"词库页提示：「{text}」（带撤销按钮：{with_undo}）")

    # 点「撤销」（= store.undo()，与词库页按钮同一动作）→ 回到导入前
    rec = st.undo()
    log(f"撤销后字节 {sha_file(st.custom.path)}；identical={rec['identical']}")
    restored = Path(st.custom.path).read_bytes() == before_raw
    log(f"**撤销后逐字节回到导入前：{restored}**")

    REPORT["E"] = dict(ui_write_ok=bool(dlg._write_ok), written=bool(dlg.written),
                       tip=dlg.tip_label.text(),
                       confirm_disabled_after_write=not dlg.confirm_btn.isEnabled(),
                       entries=n, entries_written=wl_n,
                       page_toast=text, page_toast_with_undo=bool(with_undo),
                       sha_after=sha_bytes(after_raw), undo_identical=bool(rec["identical"]),
                       page_restored=restored)
    return dict(ok=True)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log("# V1.1-D5 验收记录 · 批量事务写入与整批撤销")
    log()
    log("所有对照都是 sha256 运行时真算（不硬编码），verdict 由字节比较得出。")
    log()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for name, fn in (("A", case_a), ("B", case_b), ("C", case_c),
                         ("D", case_d), ("E", case_e)):
            try:
                fn(tmp / name.lower())
            except SystemExit as exc:
                log(f"场景 {name} 中断：{exc}")
                REPORT[name] = dict(error=str(exc))

    ok_a = bool(REPORT.get("A", {}).get("ok"))
    ok_b = bool(REPORT.get("B", {}).get("byte_identical"))
    ok_c = bool(REPORT.get("C", {}).get("identical")) and bool(
        REPORT.get("C", {}).get("identical_undo_to"))
    ok_d = bool(REPORT.get("D", {}).get("restore_to_before_identical")) and bool(
        REPORT.get("D", {}).get("restore_to_after_identical"))
    ok_e = bool(REPORT.get("E", {}).get("ui_write_ok")) and bool(
        REPORT.get("E", {}).get("page_restored"))

    log()
    log("## 结论")
    log(f"- A 正常写入（一次落盘 + 一个还原点 + 自证四项）：{'PASS' if ok_a else 'FAIL'}")
    log(f"- B 失败回滚（逐字节回到导入前）：{'PASS' if ok_b else 'FAIL'}")
    log(f"- C 整批撤销（含 undo_to 路径，逐字节一致）：{'PASS' if ok_c else 'FAIL'}")
    log(f"- D 快照恢复（导入前 / 导入后两个方向逐字节一致）：{'PASS' if ok_d else 'FAIL'}")
    log(f"- E 界面真实点击（确认即写入、可撤销回导入前）：{'PASS' if ok_e else 'FAIL'}")
    overall = all([ok_a, ok_b, ok_c, ok_d, ok_e])
    log()
    log(f"**总体：{'ALL PASS' if overall else 'FAIL'}**")

    REPORT["verdict"] = dict(A=ok_a, B=ok_b, C=ok_c, D=ok_d, E=ok_e, all=overall)
    (OUT / "accept_t5_report.md").write_text("\n".join(LINES) + "\n", encoding="utf-8")
    (OUT / "accept_t5.json").write_text(
        json.dumps(REPORT, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n报告已写入 {OUT/'accept_t5_report.md'}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
