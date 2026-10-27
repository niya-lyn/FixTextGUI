"""M3-T3.2 五条易用性底线 + 时间线可视化 验收证据采集（真实数据、真实点击链路）。

产出：
    evidence/t32_safety_evidence.json   机器可读证据
    M3-T3.2_验收报告.md                  报告（每个数字都由本脚本实测填写）

跑法：
    QT_QPA_PLATFORM=offscreen PYTHONPATH=<pkg>:<qt> python3.12 tools/accept_t32.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for p in (str(PKG), str(PKG / "fixtext_ui")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EVID = PKG / "evidence"
FORBIDDEN = [
    r"/home/", r"/tmp", r"\.json\b", r"\bsnapshots?\b", r"\bworkspace\b",
    r"custom_vocab", r"\brules\b", r"\bindex\.json\b", r"[A-Za-z]:\\\\",
    r"\bpath\b", r"\bdir\b", r"sha256", r"\bhash\b",
]


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeModal:
    def __init__(self):
        self.accepted = False
    def accept(self):
        self.accepted = True
    def reject(self):
        self.accepted = False
    def show(self):
        pass


def ui_texts(widget) -> list[str]:
    from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget
    out = []
    for w in widget.findChildren(QWidget):
        for attr in ("toolTip", "accessibleName", "accessibleDescription",
                     "placeholderText", "currentText"):
            try:
                v = getattr(w, attr)
                v = v() if callable(v) else v
            except Exception:
                continue
            if isinstance(v, str) and v:
                out.append(v)
        if isinstance(w, QLabel):
            out.append(w.text())
        if isinstance(w, QAbstractButton):
            out.append(w.text())
    t = getattr(widget, "windowTitle", "")
    if isinstance(t, str) and t:
        out.append(t)
    return [x for x in out if x]


def scan(texts: list[str]) -> list[dict]:
    hits = []
    for t in texts:
        for pat in FORBIDDEN:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                hits.append(dict(pattern=pat, matched=m.group(0), text=t[:120]))
    return hits


def main() -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import vocab_module as vm
    from fixtext_vocab import VocabStore

    tmp = Path(tempfile.mkdtemp(prefix="t32_acc_"))
    custom_path = tmp / "custom_vocab.json"
    mod = vm.VocabModule()
    mod.store = VocabStore(custom_path=custom_path)
    mod._page = 0
    mod.search = ""
    mod.dict_, mod.tier = "custom", "custom"
    mod._render_all()
    mod.show()

    st = mod.store
    rep: dict = {}

    # ===== 底线① 误删可撤销：三次写 + 三步撤销 =====
    s0 = sha(custom_path)
    mod.store.add_entry(word="甲", value="甲替", typ="错词校正"); s1 = sha(custom_path)
    mod.store.add_entry(word="乙", value="乙替", typ="错词校正"); s2 = sha(custom_path)
    mod.store.add_entry(word="丙", value="丙替", typ="错词校正"); s3 = sha(custom_path)
    steps = []
    for i, want in enumerate([s2, s1, s0], 1):
        rec = mod._undo_only() if hasattr(mod, "_undo_only") else st.undo()
        got = sha(custom_path)
        steps.append(dict(step=i, label=rec["label"], identical=rec["identical"],
                          sha_got=got, sha_expected=want, match=got == want))
    rep["undo_chain"] = dict(sha_states=[s0, s1, s2, s3], steps=steps,
                             all_match=all(s["match"] for s in steps))

    # 删除 / 合并 的撤销也各来一次（界面上被撤销的那个动作）
    st.add_entry(word="丁", value="丁替", typ="错词校正")
    st.add_entry(word="戊", value="戊替", typ="错词校正")
    pre_del = sha(custom_path)
    ids = [e["id"] for e in st.custom.entries()]
    pv_sha = (mod._confirm_delete(ids), sha(custom_path))[1]
    res_del = mod.do_delete(ids)
    rec_del = st.undo()
    rep["undo_delete"] = dict(
        preview_touched_file=pv_sha != pre_del,
        removed=res_del["removed"], count_after_undo=len(st.custom),
        undo_identical=rec_del["identical"],
        sha_before=pre_del, sha_after_undo=sha(custom_path),
        sha_equal=sha(custom_path) == pre_del,
    )
    for w in ("己", "庚", "辛"):
        st.add_entry(word=w, value=f"{w}替", typ="错词校正")
    pre_merge = sha(custom_path)
    sel = [e["id"] for e in st.custom.entries()]
    res_merge = st.merge_entries(sel, "己")
    rec_merge = st.undo()
    rep["undo_merge"] = dict(
        removed=res_merge["removed"], count_after_undo=len(st.custom),
        undo_identical=rec_merge["identical"],
        sha_before=pre_merge, sha_after_undo=sha(custom_path),
        sha_equal=sha(custom_path) == pre_merge,
    )

    # ===== 底线② 改错可恢复：恢复第 N 个快照 =====
    st.add_entry(word="壬", value="壬替", typ="错词校正")
    st.add_entry(word="癸", value="癸替", typ="错词校正")
    pts = st.timeline(limit=50)
    N = 2
    nth = [p for p in pts if p["id"] == N][0]
    live = sha(custom_path)
    rec_rp = st.restore_point(N)
    got = sha(custom_path)
    rep["restore_point"] = dict(
        chosen_point=N, label=nth["label"], time=nth["time"],
        sha_of_snapshot_record=nth["sha_after"], sha_of_file_after_restore=got,
        identical_flag=rec_rp["identical"], equal=got == nth["sha_after"],
        sha_live_before_restore=live, sha_payload_recheck=hashlib.sha256(
            st.snap.after_bytes(N)).hexdigest(),
        point_count=st.point_count(),
    )
    mod._render_all()

    # ===== 底线③ 不暴露文件：词库页文案零命中 =====
    mod._toggle_ops()
    mod.open_restore_default()
    texts = ui_texts(mod)
    hits = scan(texts)
    src_rows = []
    src = (PKG / "fixtext_ui" / "vocab_module.py").read_text("utf-8")
    for m in re.finditer(r'"([^"\\\n]{2,})"|\'([^\'\\\n]{2,})\'', src):
        s = m.group(1) or m.group(2) or ""
        if re.search(r"[\u4e00-\u9fff]", s):
            src_rows.append(s)
    src_hits = scan(src_rows)
    rep["zero_exposure"] = dict(scanned_ui_texts=len(texts),
                                scanned_source_literals=len(src_rows),
                                forbidden_patterns=len(FORBIDDEN),
                                ui_hits=hits, source_hits=src_hits,
                                count=len(hits) + len(src_hits),
                                files_custom=str(custom_path.parent != st.builtin.dir),
                                custom_builtin_separate=custom_path.parent != st.builtin.dir)

    # ===== 底线④ 批量先预览（新增 + 恢复默认）=====
    pre_add = sha(custom_path)
    mod._pending_add = dict(word="子", value="子替", typ="错词校正", pinyin="")
    mod.confirm_add(FakeModal())
    rep["preview_add"] = dict(sha_before_preview=pre_add, sha_after_confirm=sha(custom_path),
                              file_changed=sha(custom_path) != pre_add,
                              count=len(st.custom))

    blob = dict(st.builtin.read_factory_bytes())
    blob["builtin_marks.json"] = b'{"tampered": true}'
    st.builtin.write_work_bytes(blob)
    tampered = st.builtin.combined_sha()
    custom_pre = sha(custom_path)
    pv = mod.open_restore_default()
    after_preview_builtin = st.builtin.combined_sha()
    out = mod.do_restore_default(mv=FakeModal())
    rep["restore_default"] = dict(
        preview_already_default=pv["already_default"],
        preview_changed_files=pv["changed_files"],
        preview_touched_builtin=after_preview_builtin != tampered,
        preview_touched_custom=sha(custom_path) != custom_pre,
        builtin_sha_before=tampered,
        builtin_sha_factory=st.builtin.factory_combined_sha(),
        builtin_sha_after=st.builtin.combined_sha(),
        back_to_factory=st.builtin.combined_sha() == st.builtin.factory_combined_sha(),
        custom_sha_before=custom_pre, custom_sha_after=sha(custom_path),
        custom_untouched=sha(custom_path) == custom_pre,
        identical_to_factory=out["identical_to_factory"], ui_ok=out["ok"],
        custom_entries=len(st.custom),
    )
    undo_def = st.undo()
    rep["restore_default"]["undo_builtin_restored"] = undo_def["builtin_restored"]
    rep["restore_default"]["undo_builtin_sha"] = st.builtin.combined_sha()
    rep["restore_default"]["undo_builtin_equals_tampered"] = st.builtin.combined_sha() == tampered

    # ===== 底线⑤ 分级存储 =====
    fac_before = st.builtin.factory_shas()
    st.add_entry(word="丑", value="丑替", typ="错词校正")
    rep["tiering"] = dict(
        custom_dir_name=custom_path.parent.name,
        custom_file=str(custom_path.name),
        builtin_dir_name=st.builtin.dir.name,
        separate=custom_path.parent != st.builtin.dir,
        builtin_files=sorted(fac_before),
        factory_files_unchanged=st.builtin.factory_shas() == fac_before,
        work_copy_used=st.builtin.has_work_copy(),
    )

    # ===== 时间线与操作历史：换新进程仍在 =====
    n_pts, n_ops = st.point_count(), st.op_count()
    fresh = VocabStore(custom_path=custom_path)
    rows = fresh.ops(limit=5)
    rep["persistence"] = dict(
        point_count_before=n_pts, point_count_after_restart=fresh.point_count(),
        op_count_before=n_ops, op_count_after_restart=fresh.op_count(),
        same_points=fresh.point_count() == n_pts,
        same_ops=fresh.op_count() == n_ops,
        latest_ops=[dict(time=r["time"], act=r["act_name"], summary=r["summary"]) for r in rows],
        timeline_first_is_current=fresh.timeline()[0]["is_current"],
        index_on_disk=st.snap.index_path.is_file(),
        payload_files=sorted(p.name for p in st.snap.dir.glob("*.bin"))[:4],
        payload_count=len(list(st.snap.dir.glob("*.bin"))),
        undo_after_restart_identical=(lambda: (lambda r: r["identical"] if r else None)(fresh.undo()))(),
    )

    # 时间线渲染（1:1 原型语义）
    from PySide6.QtWidgets import QLabel, QWidget
    mod._render_all()
    snap_rows = []
    for w in mod.findChildren(QWidget, "SnapItem"):
        labels = [c.text() for c in w.findChildren(QLabel)]
        btns = [c.text() for c in w.findChildren(QWidget)
                if c.metaObject().className() == "QPushButton"]
        snap_rows.append(dict(labels=labels, buttons=btns))
    rep["timeline_ui"] = dict(
        rendered=len(snap_rows),
        first=snap_rows[0] if snap_rows else None,
        second=snap_rows[1] if len(snap_rows) > 1 else None,
        newest_has_current_marker=bool(snap_rows and any("· 当前" in t for t in snap_rows[0]["labels"])),
        newest_has_no_restore_btn=bool(snap_rows and "恢复到此" not in snap_rows[0]["buttons"]),
        others_have_restore_btn=all("恢复到此" in r["buttons"] for r in snap_rows[1:]),
        op_summary=mod._op_summary.text(),
    )

    mod.close()

    EVID.mkdir(parents=True, exist_ok=True)
    out_json = EVID / "t32_safety_evidence.json"
    out_json.write_text(json.dumps(rep, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print(f"\n证据 -> {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
