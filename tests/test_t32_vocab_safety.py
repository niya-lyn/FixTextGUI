"""M3-T3.2 词库安全底线（排期 §2.4.3 五条）+「恢复到任意时间点」的可视化入口。

与 T3.1 两份测试的分工：

* ``test_t31_vocab_store.py`` / ``test_t31_vocab_ui.py`` —— 验五操作本身；
* 本文件 —— 只验**安全底线**，每条底线至少一个用例，判据全是实测的
  文件指纹（sha256）或真实控件文本，不看函数返回值自报。

五条底线与时间线的对应关系：

① 误删可撤销      → ``test_undo_chain_three_writes_sha_back``
② 改错可恢复      → ``test_restore_to_nth_point_sha_matches``
③ 不暴露文件      → ``test_vocab_page_exposes_no_paths_or_concepts``
④ 批量先预览      → ``test_preview_add_does_not_touch_file`` /
                     ``test_preview_restore_default_does_not_touch_builtin``
⑤ 分级存储        → ``test_custom_and_builtin_are_physically_separate``
   时间线可视化    → ``test_timeline_and_ops_persist_across_restart``（落盘，非内存）
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from fixtext_ui.fixtext_vocab import VocabStore
from fixtext_ui.fixtext_snapshot import SnapshotStore


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeModal:
    """替身模态窗：只提供 accept / reject / show 三个副作用。"""

    def __init__(self):
        self.accepted = False

    def accept(self):
        self.accepted = True

    def reject(self):
        self.accepted = False

    def show(self):
        pass


@pytest.fixture()
def store(tmp_path):
    """自定义词库、内置工作副本、还原点都落在同一个临时子树里。"""
    return VocabStore(custom_path=tmp_path / "custom_vocab.json")


@pytest.fixture()
def mod(qapp, tmp_path):
    import vocab_module as vm

    m = vm.VocabModule()
    m.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    m._page = 0
    m.search = ""
    m.dict_, m.tier = "custom", "custom"
    m._render_all()
    yield m
    m.close()


# ---------------------------------------------------------------------------
# 底线① 误删可撤销：连续三次写操作，逐步撤销，每步 sha 回到对应前态
# ---------------------------------------------------------------------------

def test_undo_chain_three_writes_sha_back(store):
    cfg = store.custom.path

    s0 = _sha(cfg)
    store.add_entry(word="甲", value="甲替", typ="错词校正")
    s1 = _sha(cfg)
    store.add_entry(word="乙", value="乙替", typ="错词校正")
    s2 = _sha(cfg)
    store.add_entry(word="丙", value="丙替", typ="错词校正")
    s3 = _sha(cfg)

    assert len({s0, s1, s2, s3}) == 4, "三次写操作应产生四个互不相同的文件指纹"

    u1 = store.undo()
    assert u1["identical"] is True
    assert _sha(cfg) == s2

    u2 = store.undo()
    assert u2["identical"] is True
    assert _sha(cfg) == s1

    u3 = store.undo()
    assert u3["identical"] is True
    assert _sha(cfg) == s0

    assert len(store.custom) == 0
    assert all(u["label"] for u in (u1, u2, u3))


def test_delete_undo_restores_byte_identical(store):
    for w in ("甲词", "乙词"):
        store.add_entry(word=w, value=f"{w}替", typ="错词校正")
    before = _sha(store.custom.path)
    ids = [e["id"] for e in store.custom.entries()]
    store.delete_entries(ids)
    assert _sha(store.custom.path) != before
    rec = store.undo()
    assert rec["identical"] is True
    assert _sha(store.custom.path) == before
    assert len(store.custom) == 2


def test_merge_undo_restores_byte_identical(store):
    for w in ("丙", "丁", "戊"):
        store.add_entry(word=w, value=f"{w}替", typ="错词校正")
    before = _sha(store.custom.path)
    ids = [e["id"] for e in store.custom.entries()]
    store.merge_entries(ids, "丙")
    assert len(store.custom) == 1
    rec = store.undo()
    assert rec["identical"] is True
    assert _sha(store.custom.path) == before
    assert len(store.custom) == 3


def test_no_undo_left_on_empty_history(store):
    assert store.can_undo is False
    assert store.undo() is None


# ---------------------------------------------------------------------------
# 底线② 改错可恢复：恢复第 N 个快照，文件 sha == 该快照记录
# ---------------------------------------------------------------------------

def test_restore_to_nth_point_sha_matches(store):
    cfg = store.custom.path
    store.add_entry(word="甲", value="甲替", typ="错词校正")   # 还原点 1
    store.add_entry(word="乙", value="乙替", typ="错词校正")   # 还原点 2
    store.add_entry(word="丙", value="丙替", typ="错词校正")   # 还原点 3
    live_sha = _sha(cfg)

    points = {p["id"]: p for p in store.timeline(limit=20)}
    assert sorted(points) == [1, 2, 3], "每次写操作都应留一个还原点"

    nth = 2                                        # 选第 2 个快照
    recorded = points[nth]["sha_after"]
    assert recorded and recorded != live_sha

    rec = store.restore_point(nth)
    measured = _sha(cfg)
    assert rec["identical"] is True
    assert measured == recorded == rec["expected_sha"]
    assert len(store.custom) == 2, "第 2 个快照当时只有两条词"

    # 与快照载荷本身再对一次：记录的「操作后」字节也要 sha 一致
    raw = store.snap.after_bytes(nth)
    assert hashlib.sha256(raw).hexdigest() == recorded


def test_restore_point_is_idempotent(store):
    cfg = store.custom.path
    store.add_entry(word="甲", value="甲替", typ="错词校正")
    want = _sha(cfg)
    store.add_entry(word="乙", value="乙替", typ="错词校正")
    store.restore_point(1)
    first = _sha(cfg)
    store.restore_point(1)
    assert _sha(cfg) == first == want


def test_undo_to_moves_back_before_point(store):
    cfg = store.custom.path
    s0 = _sha(cfg)
    store.add_entry(word="甲", value="甲替", typ="错词校正")
    store.add_entry(word="乙", value="乙替", typ="错词校正")
    # 历史最新在前：index 0 是第 2 次操作，index 1 是第 1 次
    hist = store.history()
    assert [h["index"] for h in hist] == [0, 1]
    rec = store.undo_to(1)
    assert rec["identical"] is True
    assert _sha(cfg) == s0, "退回第一条记录之前 == 最初状态"


# ---------------------------------------------------------------------------
# 底线③ 不暴露文件：词库页全部文案零命中
# ---------------------------------------------------------------------------

FORBIDDEN = [
    r"/home/", r"/tmp", r"\.json\b", r"\bsnapshots?\b", r"\bworkspace\b",
    r"custom_vocab", r"\brules\b", r"\bindex\.json\b", r"[A-Za-z]:\\\\",
    r"\bpath\b", r"\bdir\b", r"sha256", r"\bhash\b",
]


def _ui_texts(widget) -> list[str]:
    from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

    out: list[str] = []
    for w in widget.findChildren(QWidget):
        for attr in ("toolTip", "accessibleName", "accessibleDescription",
                     "placeholderText", "currentText"):
            try:
                v = getattr(w, attr)
                v = v() if callable(v) else v
            except Exception:               # pragma: no cover
                continue
            if isinstance(v, str) and v:
                out.append(v)
        if isinstance(w, QLabel):
            out.append(w.text())
        if isinstance(w, QAbstractButton):
            out.append(w.text())
    for attr in ("windowTitle",):
        v = getattr(widget, attr, "")
        if isinstance(v, str) and v:
            out.append(v)
    return [t for t in out if t]


def test_vocab_page_exposes_no_paths_or_concepts(mod):
    # 先造出时间线 / 操作历史 / 恢复默认预览，把这几块新面板都渲染出来
    mod.store.add_entry(word="甲", value="甲替", typ="错词校正")
    mod.store.add_entry(word="乙", value="乙替", typ="错词校正")
    mod._render_all()
    mod._toggle_ops()
    mod.open_restore_default()

    texts = _ui_texts(mod)
    assert len(texts) > 60, f"扫到的文案太少，扫描口径可能失效：{len(texts)}"

    hits = []
    for t in texts:
        for pat in FORBIDDEN:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                hits.append((pat, m.group(0), t[:120]))
    assert not hits, f"词库页文案出现内部概念 {hits}"


def test_vocab_module_source_literals_have_no_concepts():
    """弹窗文案不在控件树里，扫词库页源码的中文字符串字面量。

    只扫 ``vocab_module.py``——本卡的范围就是词库页；别的页面的文案属
    各自卡片的验收口径（导出页 / 导入页另有 lint），在这里扫会把它们的
    历史问题当成本卡的问题。
    """
    here = Path(__file__).resolve().parent.parent / "fixtext_ui"
    rows = []
    for f in [here / "vocab_module.py"]:
        src = f.read_text("utf-8")
        for m in re.finditer(r'"([^"\\\n]{2,})"|\'([^\'\\\n]{2,})\'', src):
            s = m.group(1) or m.group(2) or ""
            if re.search(r"[\u4e00-\u9fff]", s):
                rows.append((f.name, s))
    assert rows, "没扫到中文文案，扫描口径失效"
    hits = [(n, s) for n, s in rows
            for pat in FORBIDDEN if re.search(pat, s, re.IGNORECASE)]
    assert not hits, f"源码文案出现内部概念 {hits}"


# ---------------------------------------------------------------------------
# 底线④ 批量先预览：预览阶段一个字节都不写，确认后才写
# ---------------------------------------------------------------------------

def test_preview_add_does_not_touch_file(qapp, tmp_path):
    import vocab_module as vm

    m = vm.VocabModule()
    m.store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    m._page = 0
    m.search = ""
    m.dict_, m.tier = "custom", "custom"
    m._render_all()
    try:
        before = _sha(m.store.custom.path)
        m.preview_add(FakeModal(), "甲", "甲替", "错词校正", "")
        assert _sha(m.store.custom.path) == before, "预览阶段不应写文件"
        assert len(m.store.custom) == 0
        assert m.store.point_count() == 0, "预览阶段也不应留还原点"

        modal = FakeModal()
        m.confirm_add(modal)
        assert _sha(m.store.custom.path) != before
        assert len(m.store.custom) == 1
        assert modal.accepted is True
    finally:
        m.close()


def test_preview_restore_default_does_not_touch_builtin(store):
    # 先让工作副本与出厂版本不同（模拟内置词库被改动过）
    work = store.builtin.work_dir
    files = store.builtin.read_factory_bytes()
    blob = dict(files)
    blob["builtin_marks.json"] = b'{"tampered": true}'
    store.builtin.write_work_bytes(blob)
    changed_sha = store.builtin.combined_sha()
    assert changed_sha != store.builtin.factory_combined_sha()

    custom_sha = _sha(store.custom.path)
    pv = store.preview_restore_default()
    assert pv["already_default"] is False
    assert pv["changed_files"] >= 1
    assert pv["custom_untouched"] is True
    assert store.builtin.combined_sha() == changed_sha, "预览不应动内置词库"
    assert _sha(store.custom.path) == custom_sha, "预览不应动自定义词库"
    assert store.point_count() == 0, "预览不应留还原点"

    res = store.restore_default()
    assert res["identical_to_factory"] is True
    assert store.builtin.combined_sha() == store.builtin.factory_combined_sha()
    assert res["custom_untouched"] is True
    assert _sha(store.custom.path) == custom_sha


def test_restore_default_is_undoable(store):
    blob = dict(store.builtin.read_factory_bytes())
    blob["builtin_marks.json"] = b'{"tampered": true}'
    store.builtin.write_work_bytes(blob)
    tampered = store.builtin.combined_sha()

    res = store.restore_default()
    assert store.builtin.combined_sha() == store.builtin.factory_combined_sha()

    rec = store.undo()
    assert rec["builtin_restored"] is True
    assert store.builtin.combined_sha() == tampered, "撤销应把内置词库也还原回去"
    assert store.snap.get(res["point_id"])["undone"] is True


def test_restore_default_ui_two_step(mod):
    """界面入口：先出预览（不写），再确认执行。"""
    path = mod.store.builtin.work_dir
    blob = dict(mod.store.builtin.read_factory_bytes())
    blob["builtin_marks.json"] = b'{"tampered": true}'
    mod.store.builtin.write_work_bytes(blob)
    tampered = mod.store.builtin.combined_sha()
    custom_before = _sha(mod.store.custom.path)

    pv = mod.open_restore_default()                  # 只弹预览
    assert pv["already_default"] is False
    assert mod.store.builtin.combined_sha() == tampered, "UI 预览阶段不应写"

    out = mod.do_restore_default(mv=FakeModal())     # 二次确认后执行
    assert out["ok"] is True
    assert mod.store.builtin.combined_sha() == mod.store.builtin.factory_combined_sha()
    assert _sha(mod.store.custom.path) == custom_before
    assert path.is_dir()


# ---------------------------------------------------------------------------
# 底线⑤ 分级存储：自定义与内置物理分离，且界面不给路径
# ---------------------------------------------------------------------------

def test_custom_and_builtin_are_physically_separate(store):
    custom_dir = store.custom.path.parent
    builtin_dir = store.builtin.dir
    assert custom_dir != builtin_dir
    assert builtin_dir.is_dir()
    # 自定义写入不碰内置任何文件
    builtin_before = {n: _sha(builtin_dir / n) for n in sorted(
        p.name for p in builtin_dir.glob("*"))}
    store.add_entry(word="甲", value="甲替", typ="错词校正")
    builtin_after = {n: _sha(builtin_dir / n) for n in sorted(
        p.name for p in builtin_dir.glob("*"))}
    assert builtin_before == builtin_after


def test_builtin_factory_files_never_rewritten(store):
    factory = {n: _sha(store.builtin.dir / n) for n in store.builtin.factory_shas()}
    store.add_entry(word="甲", value="甲替", typ="错词校正")
    assert store.builtin.factory_shas() == factory


# ---------------------------------------------------------------------------
# 时间线 + 操作历史：落盘，换新进程仍在
# ---------------------------------------------------------------------------

def test_timeline_and_ops_persist_across_restart(tmp_path):
    path = tmp_path / "custom_vocab.json"
    first = VocabStore(custom_path=path)
    first.add_entry(word="甲", value="甲替", typ="错词校正")
    first.add_entry(word="乙", value="乙替", typ="错词校正")
    first.delete_entries([first.custom.entries()[0]["id"]])
    n_points = first.point_count()
    n_ops = first.op_count()
    assert n_points == 3 and n_ops == 3

    # 全新实例 = 全新进程读同一块盘
    second = VocabStore(custom_path=path)
    assert second.point_count() == n_points
    assert second.op_count() == n_ops
    rows = second.ops()
    assert [r["act_name"] for r in rows] == ["删除", "新增", "新增"]
    assert all(r["time"] for r in rows), "每条操作历史都要有时间点"
    assert all(r["summary"] for r in rows), "每条操作历史都要有摘要"
    assert second.timeline()[0]["is_current"] is True


def test_snapshot_index_is_on_disk(store):
    store.add_entry(word="甲", value="甲替", typ="错词校正")
    idx = store.snap.index_path
    assert idx.is_file(), "还原点索引必须落盘"
    data = json.loads(idx.read_text("utf-8"))
    assert data["points"] and data["ops"]
    payloads = [p for p in store.snap.dir.iterdir() if p.suffix == ".bin"]
    assert len(payloads) == 2, "每次写操作应有「操作前」「操作后」两个载荷"
    assert {p.name for p in payloads} == {"p00001-before.bin", "p00001-after.bin"}


def test_new_instance_can_undo_across_restart(tmp_path):
    path = tmp_path / "custom_vocab.json"
    first = VocabStore(custom_path=path)
    first.add_entry(word="甲", value="甲替", typ="错词校正")
    want = _sha(path)

    second = VocabStore(custom_path=path)
    rec = second.undo()
    assert rec["identical"] is True
    assert _sha(path) != want
    assert len(second.custom) == 0


def test_ops_link_to_restore_points(store):
    store.add_entry(word="甲", value="甲替", typ="错词校正")
    store.add_entry(word="乙", value="乙替", typ="错词校正")
    for op in store.ops():
        assert op["point_id"], "每条操作历史都要能指回一个时间点"
        assert store.snap.get(op["point_id"]) is not None


# ---------------------------------------------------------------------------
# 界面：时间线渲染（1:1 原型语义）
# ---------------------------------------------------------------------------

def _snap_rows(mod) -> list:
    from PySide6.QtWidgets import QLabel, QWidget

    rows = []
    for w in mod.findChildren(QWidget, "SnapItem"):
        labels = [c.text() for c in w.findChildren(QLabel)]
        btns = [c.text() for c in w.findChildren(QWidget)
                if c.metaObject().className() == "QPushButton"]
        rows.append((labels, btns))
    return rows


def test_timeline_renders_newest_first_without_restore_link(mod):
    mod.store.add_entry(word="甲", value="甲替", typ="错词校正")
    mod.store.add_entry(word="乙", value="乙替", typ="错词校正")
    mod._render_all()
    rows = _snap_rows(mod)
    assert len(rows) == 2
    # 第一条是最新的，带「· 当前」且不给「恢复到此」
    assert any("· 当前" in t for t in rows[0][0])
    assert "恢复到此" not in rows[0][1]
    # 第二条给「恢复到此」
    assert "恢复到此" in rows[1][1]
    assert any("删除" in t or "新增" in t for t in rows[1][0])


def test_timeline_empty_state_copy(mod):
    from PySide6.QtWidgets import QLabel

    mod._render_snaps()
    texts = [w.text() for w in mod.findChildren(QLabel)]
    assert any("还没有可恢复的时间点" in t for t in texts)
    assert any("会自动留一份" in t for t in texts)


def test_timeline_restore_button_restores_point(mod):
    cfg = mod.store.custom.path
    mod.store.add_entry(word="甲", value="甲替", typ="错词校正")
    want = _sha(cfg)
    mod.store.add_entry(word="乙", value="乙替", typ="错词校正")
    mod._render_all()
    mod.restore_point(1)
    assert _sha(cfg) == want, "「恢复到此」应把文件写回该时间点当时的样子"
    assert mod.status.text() == "已恢复到所选时间点"


def test_op_history_panel_rows(mod):
    mod.store.add_entry(word="甲", value="甲替", typ="错词校正")
    mod.store.delete_entries([mod.store.custom.entries()[0]["id"]])
    mod._render_all()
    assert "共 2 次变更" in mod._op_summary.text()
    mod._toggle_ops()
    assert mod._op_toggle.text() == "收起"
