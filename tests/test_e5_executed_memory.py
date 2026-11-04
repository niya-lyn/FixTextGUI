"""V1.1-E5 · 已执行规则记忆与按书排除的验收用例。

本卡的三条验收判据，每条都有机器可判定的用例：

1. **记忆不碰按书词库**（排期 §12.1「不得改 resolve_excluded 口径」）
   → ``test_memory_never_touches_book_vocab_bytes``：写入记忆前后
     ``book_vocab.json`` 逐字节不变，``resolve_excluded()`` 的八项判定全等，
     且 ``{盍->阖}`` 这条记忆**不出现在** effective / sources 里——
     记忆是规则维度的「跑过没」，不是内容维度的「词条禁用」。
2. **指纹跟着记忆走**（排期 §12.2「断点不能复用旧正文」）
   → ``test_fingerprint_tracks_write_and_clear``（写入→变、清回→逐字复原）/
     ``test_fingerprint_separates_books``（换书→分开）/
     ``test_clear_restores_executed_file_bytes``（清除后文件逐字节复原）。
3. **跨进程真的排除、跨书不串扰**（排期 §12.3）
   → ``test_new_process_excludes_executed_rule``：A 书执行后**新起一个进程**
     （真读盘）自动把那条规则排除、并给出人话原因；同一进程里 B 书照旧是候选。

另有三类结构性检查：

* 两个还原点仓库实例互覆 ``index.json`` 的缺陷不得回归
  → ``test_session_and_memory_share_one_store``（含 ``mem.store is s.store`` 断言）；
* 「说明」列必须把原因说出来、不能静默消失
  → ``test_rule_note_column_states_executed_reason``；
* 界面三个入口（清掉选中 / 清空本书 / 撤回上一次记忆变更）
  → ``test_ui_memory_card_three_entries``；
* 界面文案零技术词 → ``test_manual_module_texts_have_no_tech_terms``。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "fixtext_ui", ROOT / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import fixtext_batch_confirm as bc                        # noqa: E402
import fixtext_book_scope as bscope                       # noqa: E402
import fixtext_rule_memory as rmem                        # noqa: E402
from fixtext_pipeline import book_vocab as bv             # noqa: E402
from fixtext_pipeline import rule_keys                    # noqa: E402
from fixtext_pipeline import executed_rules as ex         # noqa: E402
from fixtext_ui import fixtext_manual_search as M         # noqa: E402

RULES = ROOT / "data" / "manual_search" / "rules.json"
SAMPLES = Path(__file__).resolve().parent / "samples"
SAMPLE_A = SAMPLES / "a_utf8_lf.txt"

#: 探针规则：执行记忆用它，按书排除用另一条——两者必须是不同维度。
PROBE_MARK = "{盍->阖}"
PROBE_WORD, PROBE_VALUE = "盍", "阖"
#: 按书词库里真实存在的一条内容键（与探针规则无关，证「记忆不混进排除集」）
EXCL_WORD, EXCL_VALUE = "告之", "告知"

#: 空 mark 集合的指纹（写入前 / 清回后都必须是这个值）
EMPTY_SHA = ex.executed_marks_sha(())

#: 只在本用例里改的用户区根（记忆文件落在临时目录，不污染包内 workspace）
@pytest.fixture()
def ws(tmp_path: Path, monkeypatch) -> Path:
    """把界面侧的用户区根指到临时目录（记忆文件与按书词库都落在这里）。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(bscope, "workspace_root", lambda: root)
    return root


@pytest.fixture()
def book_a(tmp_path: Path) -> Path:
    """A 书：文件夹名就是书 id（与书架口径一致）。"""
    p = tmp_path / "书A" / "book.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    # 末尾补一句带探针字的正文：让探针规则在这本书上真有命中，
    # 它才会进「候选」——「已执行过的不再进候选」才有可证伪的落点。
    p.write_text(SAMPLE_A.read_text(encoding="utf-8") + "\n他盍不早说？\n",
                 encoding="utf-8")
    return p


@pytest.fixture()
def book_b(tmp_path: Path) -> Path:
    p = tmp_path / "书B" / "book.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(SAMPLE_A.read_text(encoding="utf-8") + "\n他盍不早说？\n",
                 encoding="utf-8")
    return p


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _memory_of(book: Path, ws: Path) -> rmem.RuleMemory:
    """按界面同一条口径建记忆：书目录下的 batch_backups + 临时用户区。"""
    mem = rmem.RuleMemory(store_dir=book.parent / bc.BACKUP_DIRNAME, workspace=ws)
    return mem


def _total(text: str) -> int:
    """在书上真跑一遍「盍→阖」，作为「改了几处」的实测值（不是编的）。"""
    return text.count(PROBE_WORD)


# ---------------------------------------------------------------------------
# 判据 1：记忆不碰按书词库，也不改 resolve_excluded 口径
# ---------------------------------------------------------------------------

def test_memory_never_touches_book_vocab_bytes(book_a: Path, ws: Path):
    """写入记忆前后：按书词库逐字节不变 + 八项判定全等 + 探针不在排除集里。"""
    bid = rmem.book_id_of_text_path(book_a)
    assert bid == "书A"

    # 先有一份按书词库（真实存在的一条内容键），再写记忆
    bkv = bv.book_vocab_path(bid, workspace=ws)
    bv.write_book_vocab(bkv, bid, [(EXCL_WORD, EXCL_VALUE)], reason="用例：按书排除")
    before_bytes = bkv.read_bytes()
    before_sha = _sha(bkv)

    global_disabled = [rule_keys.entry_key(EXCL_WORD, EXCL_VALUE),
                       rule_keys.entry_key("费劲思量", "费尽思量")]
    before = bv.resolve_excluded(global_disabled, bv.book_excluded_keys(bkv))

    text = book_a.read_text(encoding="utf-8")
    mem = _memory_of(book_a, ws)
    res = mem.remember(bid, [dict(mark=PROBE_MARK, batch=1, hits=_total(text), at="")])
    assert res["changed"] is True and res["marks_sha"] != EMPTY_SHA

    # ① 按书词库逐字节不变
    assert bkv.read_bytes() == before_bytes, "记忆写到了按书词库上"
    assert _sha(bkv) == before_sha

    # ② resolve_excluded 八项判定全等
    after = bv.resolve_excluded(global_disabled, bv.book_excluded_keys(bkv))
    for field in ("effective", "sources", "overlap", "global_only", "book_only",
                  "global_count", "book_count"):
        assert after[field] == before[field], f"resolve_excluded 的 {field} 被记忆影响了"
    assert after["policy"] == before["policy"]
    assert after["book_count"] == 1 and after["overlap"] == 1

    # ③ 记忆里的规则标识不出现在排除集里（规则维度 ≠ 内容维度）
    probe_key = rule_keys.entry_key(PROBE_WORD, PROBE_VALUE)
    assert probe_key not in after["effective"]
    assert probe_key not in after["sources"]
    assert PROBE_MARK not in after["effective"]
    assert PROBE_MARK not in after["sources"]


def test_executed_file_is_beside_book_vocab(book_a: Path, ws: Path):
    """两份按书文件同目录不同名：记忆没有搭在 book_vocab.json 里。"""
    bid = rmem.book_id_of_text_path(book_a)
    mem = _memory_of(book_a, ws)
    mem.remember(bid, [dict(mark=PROBE_MARK, batch=1, hits=1, at="")])

    ex_path = Path(mem.path_for(bid))
    bkv = bv.book_vocab_path(bid, workspace=ws)
    assert ex_path.name == ex.EXECUTED_RULES_FILE
    assert ex_path.parent == bkv.parent
    assert ex_path != bkv
    payload = json.loads(ex_path.read_text(encoding="utf-8"))
    assert payload["kind"] == ex.EXECUTED_RULES_KIND
    assert payload["marks"][0]["mark"] == PROBE_MARK
    # 按书词库根本没被创建（记忆不替它落盘）
    assert not bkv.exists()


# ---------------------------------------------------------------------------
# 判据 2：指纹跟着记忆走（写入 → 变化；清回 → 逐字复原；换书 → 分开）
# ---------------------------------------------------------------------------

def _fingerprint(tmp_path: Path, *, book_id: str, book_vocab_path: Path | None):
    """按 C1 的口径造一个只跑 replace 的阶段，取它的指纹。"""
    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.logsetup import StageLogger
    from fixtext_pipeline.stages.replace import ReplaceStage

    epub = tmp_path / "probe.epub"
    epub.parent.mkdir(parents=True, exist_ok=True)
    epub.write_bytes(b"PK\x03\x04empty")
    work = tmp_path / "run"
    work.mkdir(parents=True, exist_ok=True)
    custom = tmp_path / "custom.json"
    if not custom.is_file():
        custom.write_text('{"entries": []}', encoding="utf-8")
    cfg = PipelineConfig(
        epub=epub, workdir=work,
        rules_before=ROOT / "data" / "rules" / "before.json",
        rules_after=ROOT / "data" / "rules" / "after.json",
        engine_path=tmp_path / "fake_engine",
        stages=("replace",), resume=True, force=False,
        custom_vocab_path=custom,
        derived_rules_dir=tmp_path / "derived",
        word_states_path=None,
        book_id=book_id,
        book_vocab_path=book_vocab_path,
    )
    log = StageLogger(cfg.paths.stage_log("replace"), echo=False)
    return ReplaceStage(cfg, log)


def test_fingerprint_tracks_write_and_clear(book_a: Path, ws: Path, tmp_path: Path,
                                          monkeypatch):
    """写入记忆 → 指纹变；清回空 → 指纹逐字复原（缓存不会复用旧正文）。"""
    bid = rmem.book_id_of_text_path(book_a)
    bkv = bv.book_vocab_path(bid, workspace=ws)
    bv.write_book_vocab(bkv, bid, [(EXCL_WORD, EXCL_VALUE)])

    stage = _fingerprint(tmp_path, book_id=bid, book_vocab_path=bkv)
    parts: list[str] = []
    real = type(stage).fingerprint_of

    def spy(self, *args):
        parts.extend(str(a) for a in args)
        return real(self, *args)

    monkeypatch.setattr(type(stage), "fingerprint_of", spy)

    fp0 = stage.fingerprint()
    # 指纹的分区串里真的带了 done=（不是只有 sha 不可观测）
    assert any(str(p).startswith("book=") and f"done={EMPTY_SHA}" in str(p)
               for p in parts), parts

    mem = _memory_of(book_a, ws)
    mem.remember(bid, [dict(mark=PROBE_MARK, batch=1, hits=1, at="")])
    parts.clear()
    fp1 = stage.fingerprint()
    assert fp1 != fp0
    assert any(f"done={mem.marks_sha(bid)}" in str(p) for p in parts), parts

    mem.clear(bid)
    assert mem.marks_sha(bid) == EMPTY_SHA
    fp2 = stage.fingerprint()
    assert fp2 == fp0, "清回之后指纹没有逐字复原"

    # 另一条规则进来 → 又是新指纹（不是只有「空 / 非空」两态）
    mem.remember(bid, [dict(mark="{漱漱->簌簌}", batch=2, hits=3, at="")])
    fp3 = _fingerprint(tmp_path, book_id=bid, book_vocab_path=bkv).fingerprint()
    assert fp3 not in (fp0, fp1)


def test_fingerprint_separates_books(book_a: Path, book_b: Path, ws: Path,
                                     tmp_path: Path):
    """同样一条记忆，两本书的指纹各自分开（按书作用域不串扰）。"""
    bid_a = rmem.book_id_of_text_path(book_a)
    bid_b = rmem.book_id_of_text_path(book_b)
    bkv_a = bv.book_vocab_path(bid_a, workspace=ws)
    bkv_b = bv.book_vocab_path(bid_b, workspace=ws)
    bv.write_book_vocab(bkv_a, bid_a, [])
    bv.write_book_vocab(bkv_b, bid_b, [])

    mem_a = _memory_of(book_a, ws)
    mem_a.remember(bid_a, [dict(mark=PROBE_MARK, batch=1, hits=1, at="")])

    sha_a = mem_a.marks_sha(bid_a)
    # B 书没记过：指纹里的 done= 是空集，A 书则不是
    assert mem_a.marks(bid_b) == frozenset()
    assert sha_a != mem_a.marks_sha(bid_b)
    fp_a = _fingerprint(tmp_path / "a", book_id=bid_a, book_vocab_path=bkv_a).fingerprint()
    fp_b = _fingerprint(tmp_path / "b", book_id=bid_b, book_vocab_path=bkv_b).fingerprint()
    # 指纹是整串 sha，两本书的 id 不同 → 指纹必然不同（且 done= 一项也各是各的）
    assert fp_a != fp_b
    assert mem_a.marks_sha(bid_a) != mem_a.marks_sha(bid_b)


def test_clear_restores_executed_file_bytes(book_a: Path, ws: Path):
    """清除一次记忆变更后，记忆文件按还原点逐字节复原（不是「看起来空」）。"""
    bid = rmem.book_id_of_text_path(book_a)
    mem = _memory_of(book_a, ws)
    p = Path(mem.path_for(bid))

    cur = [dict(mark=PROBE_MARK, batch=1, hits=2, at="")]
    mem.remember(bid, cur)
    first = p.read_bytes()
    first_sha = _sha(p)
    assert ex.executed_mark_set(p) == frozenset({PROBE_MARK})

    # 第二次变更：再加一条
    mem.remember(bid, [dict(mark="{漱漱->簌簌}", batch=2, hits=3, at="")])
    mixed = _sha(p)
    assert mixed != first_sha

    # 撤回上一次 → 回到第一次那份字节
    res = mem.undo_last()
    assert res is not None
    assert _sha(p) == first_sha, "撤回记忆变更没有逐字节复原"
    assert p.read_bytes() == first
    assert ex.executed_mark_set(p) == frozenset({PROBE_MARK})
    assert res["identical"] is True


# ---------------------------------------------------------------------------
# 判据 3：跨进程真的排除；跨书不串扰
# ---------------------------------------------------------------------------

_CHILD = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    sys.path[:0] = [%(root)r, %(ui)r, %(pipe)r]
    import fixtext_book_scope as bscope
    bscope.workspace_root = lambda: Path(%(ws)r)          # 用例用的临时用户区
    import fixtext_batch_confirm as bc
    import fixtext_rule_memory as rmem
    from fixtext_manual_search import load_rules

    rules = load_rules(%(rules)r)
    out = {}
    for name, path in (("A", %(a)r), ("B", %(b)r)):
        book = Path(path)
        bid = rmem.book_id_of_text_path(book)
        mem = rmem.RuleMemory(store_dir=book.parent / bc.BACKUP_DIRNAME)
        s = bc.BatchSession(rules, book.read_text(encoding="utf-8"),
                            target_path=book, memory=mem, book_id=bid)
        s.scan()
        probe = rules.rules[0].index
        picked = s.select_all_hits()          # 只选有命中的（A 书执行后探针已无命中）
        s.select_all_hits(skip_executed=False)
        auto = s.select_all_hits()            # 回到默认口径，excluded 反映记忆
        # 用户手动勾选这条探针（就是「我要重跑」的路径）→ 应被记忆挡下并给原因
        manual = s.select_indices([probe], skip_executed=True)
        out[name] = dict(
            book_id=bid,
            picked=picked,
            excluded=s.excluded_indices,
            auto=auto,
            manual=manual,
            manual_excluded=s.excluded_indices,
            reason=s.executed_reason(probe),
            probe_index=probe,
            probe_mark=rules.rules[0].mark,
        )
        out[name]["marks"] = sorted(mem.marks(bid))
    print(json.dumps(out, ensure_ascii=False))
    """
)


def test_new_process_excludes_executed_rule(book_a: Path, book_b: Path, ws: Path):
    """A 书执行过之后：**新进程**读盘就把那条规则排除、并给出人话原因；B 书照旧。"""
    bid_a = rmem.book_id_of_text_path(book_a)
    bid_b = rmem.book_id_of_text_path(book_b)

    # A 书真跑一批（走 E4 的会话 + E5 的记忆）
    rules = M.load_rules(RULES)
    mem = _memory_of(book_a, ws)
    s = bc.BatchSession(rules, book_a.read_text(encoding="utf-8"),
                        target_path=book_a, memory=mem, book_id=bid_a)
    s.scan()
    picked = s.select_indices([rules.rules[0].index], skip_executed=True)
    assert picked == [rules.rules[0].index]
    s.plan(1)
    pv = s.preview(1)
    rec = s.execute(1, pv.token)
    assert rec["memory"]["changed"] is True, rec["memory"]
    assert rec["memory"]["marks_added"] == 1
    assert mem.marks(bid_a) == frozenset({rules.rules[0].mark})

    # 新进程：真读盘（不借本进程的内存状态）
    script = _CHILD % dict(root=str(ROOT), ui=str(ROOT / "fixtext_ui"),
                           pipe=str(ROOT / "pipeline"), ws=str(ws),
                           rules=str(RULES), a=str(book_a), b=str(book_b))
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, timeout=120, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    a = out["A"]
    assert a["book_id"] == bid_a
    assert a["marks"] == [rules.rules[0].mark], "新进程没读到盘上的执行记录"
    # 手动勾选这条已执行过的规则 → 被挡下，并给出人话原因
    assert a["manual"] == [], "新进程没有把那一条排除掉"
    assert a["probe_index"] in a["manual_excluded"]
    assert a["reason"], "排除没有给出人话原因"
    assert "已经执行过" in a["reason"] and "第 1 批" in a["reason"]

    b = out["B"]
    assert b["marks"] == [], "B 书读到了 A 书的记忆（串书了）"
    assert b["manual"] == [b["probe_index"]], "B 书不该被 A 书的执行记录影响"
    assert b["manual_excluded"] == []
    assert b["reason"] == ""


# ---------------------------------------------------------------------------
# 结构性检查：一个还原点仓库、说明列、三个入口、零技术词
# ---------------------------------------------------------------------------

def test_session_and_memory_share_one_store(qt_app, book_a: Path, ws: Path):
    """界面挂书后：会话与记忆**同一个** SnapshotStore 实例（同一份 index.json）。"""
    pytest.importorskip("PySide6")
    import manual_module as mm

    mod = mm.ManualModule()
    mod._confirm_hook = lambda title, note: False
    mod.set_book(str(book_a), "书A")
    mod.scan_book(silent=True)
    s, mem = mod.session, mod.memory
    assert s is not None and mem is not None
    assert mem.store is s.store, "两个还原点仓库实例会互相覆盖 index.json"
    assert s.store.dir.name == bc.BACKUP_DIRNAME
    assert s.store.dir.parent == book_a.parent

    # 各自写一次，二者都能在同一个 index.json 里看到（没被对方覆盖）
    before = {p["id"] for p in s.store.points()}
    mem.remember(mod.book_id, [dict(mark=PROBE_MARK, batch=1, hits=1, at="")])
    after_mem = {p["id"] for p in s.store.points()}
    assert after_mem - before
    mod.shutdown()


def test_rule_note_column_states_executed_reason(qt_app, book_a: Path, ws: Path):
    """清单的「说明」列把原因写出来——已执行的规则不静默消失。"""
    pytest.importorskip("PySide6")
    import manual_module as mm

    bid = rmem.book_id_of_text_path(book_a)
    mem = _memory_of(book_a, ws)
    mem.remember(bid, [dict(mark=PROBE_MARK, batch=2, hits=3, at="")])

    model = mm.RulePickModel()
    model.set_rules(M.load_rules(RULES).rules)
    model.set_executed(mem.records(bid))
    idx = model.index(0, model.COL_NOTE)
    text = model.data(idx, mm.Qt.ItemDataRole.DisplayRole) or ""
    assert "已经执行过这条规则" in text
    assert "第 2 批" in text and "当时改了 3 处" in text

    # 没记过的规则不带这句话（原因只挂在它自己那条上）
    other = model.data(model.index(1, model.COL_NOTE), mm.Qt.ItemDataRole.DisplayRole) or ""
    assert "已经执行过这条规则" not in other


def test_ui_memory_card_three_entries(qt_app, book_a: Path, ws: Path):
    """卡片三个入口都走既有还原点仓库：清掉选中 / 清空本书 / 撤回上一次。"""
    pytest.importorskip("PySide6")
    import manual_module as mm

    mod = mm.ManualModule()
    answers = iter([True] * 6)
    mod._confirm_hook = lambda title, note: next(answers, False)
    mod.set_book(str(book_a), "书A")
    bid = mod.book_id
    mem = mod.memory
    assert mem is not None and bid == "书A"

    # 先记两条，卡片有行
    mem.remember(bid, [dict(mark=PROBE_MARK, batch=1, hits=3, at=""),
                       dict(mark="{漱漱->簌簌}", batch=2, hits=1, at="")])
    mod._refresh_memory()
    assert mod.memory_model.rowCount() == 2
    assert mod.memory_clear_all_btn.isEnabled()
    assert mod.memory_undo_btn.isEnabled()

    # ① 清掉选中（选第一行）
    mod.memory_view.selectRow(0)
    mod.clear_memory_picked()
    assert len(mem.marks(bid)) == 1
    assert "已清掉" in mod.last_message()

    # ② 撤回上一次记忆变更（把刚清掉的那条恢复回来）
    mod.undo_memory()
    assert len(mem.marks(bid)) == 2
    assert "已撤回" in mod.last_message()

    # ③ 清空本书
    mod.clear_memory_all()
    assert mem.marks(bid) == frozenset()
    assert mod.memory_model.rowCount() == 0
    assert "已清空" in mod.last_message()

    # 三个动作都在同一个 index.json 的操作历史里，动作名可核对
    acts = {row["act"] for row in mem.store.ops()}
    assert rmem.ACT_RULE_EXECUTED in acts
    assert rmem.ACT_RULE_MEMORY_CLEAR in acts
    assert rmem.ACT_RULE_MEMORY_RESTORE in acts
    mod.shutdown()


FORBIDDEN = [
    "spine", "opf", "container.xml", "manifest", "ncx", "xhtml", "xml", "bom",
    "utf-8", "utf8", "gbk", "gb18030", "big5", "crlf", "sha256", "hash",
    "encoding", "charset", "codec", "zip", "json",
]
ALLOWED_WORDS = {"epub", "txt"}


def test_manual_module_texts_have_no_tech_terms(qt_app, book_a: Path, ws: Path):
    """记忆卡与说明列的人话文案里不出现技术词。"""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QLabel, QPushButton, QWidget

    import manual_module as mm

    bid = rmem.book_id_of_text_path(book_a)
    mem = _memory_of(book_a, ws)
    mem.remember(bid, [dict(mark=PROBE_MARK, batch=1, hits=2, at="")])

    mod = mm.ManualModule()
    mod._confirm_hook = lambda title, note: False
    mod.set_book(str(book_a), "书A")
    mod.pick_nonzero()
    mod._refresh_memory()

    texts: list[str] = []
    for w in mod.findChildren(QWidget):
        for attr in ("text", "placeholderText", "toolTip", "windowTitle"):
            value = getattr(w, attr, "")
            if isinstance(value, str) and value:
                texts.append(value)
        if isinstance(w, (QLabel, QPushButton)):
            for extra in ("accessibleName", "accessibleDescription"):
                value = getattr(w, extra, "")
                if isinstance(value, str) and value:
                    texts.append(value)
    # 说明列的实际渲染文本也在扫描范围内
    texts.append(mod.rule_model.data(mod.rule_model.index(0, mod.rule_model.COL_NOTE),
                                     mm.Qt.ItemDataRole.DisplayRole) or "")
    texts.append(mod.memory_note.text())
    bad = []
    for t in texts:
        low = t.lower()
        hits = [x for x in FORBIDDEN if x in low and x not in ALLOWED_WORDS]
        if hits:
            bad.append((t[:80], hits))
    mod.shutdown()
    assert not bad, f"界面文本出现技术词：{bad}"
