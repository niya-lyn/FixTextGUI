"""M3-T3.1 词库五操作验收证据采集（真实数据、真实点击链路）。

产出 evidence/t31_vocab_evidence.json，报告里的每个数字都来自这里，不手写。

跑法：
    QT_QPA_PLATFORM=offscreen PYTHONPATH=<pkg>:<qt> python3.12 tools/accept_t31.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for p in (str(PKG), str(PKG / "fixtext_ui")):
    if p not in sys.path:
        sys.path.insert(0, p)

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EVID = PKG / "evidence"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeModal:
    def __init__(self):
        self.accepted = False

    def accept(self):
        self.accepted = True

    def reject(self):
        self.accepted = False

    def show(self):
        pass


class FakeCheck:
    def __init__(self, on=True):
        self._on = on

    def isChecked(self):
        return self._on


def main() -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import vocab_module as vm
    from fixtext_vocab import VocabStore, TIER_NAMES

    tmp = Path(tempfile.mkdtemp(prefix="t31_acc_"))
    custom_path = tmp / "custom_vocab.json"
    mod = vm.VocabModule()
    mod.store = VocabStore(custom_path=custom_path)
    mod._page = 0
    mod.search = ""
    mod.dict_, mod.tier = "custom", "custom"
    mod._render_all()
    mod.show()

    rep: dict = {}

    # ---- 数据层基线 ----
    counts = mod.store.counts()
    rep["builtin_total"] = mod.store.builtin_total
    rep["tier_counts"] = counts
    rep["builtin_self_check"] = mod.store.builtin.self_check()
    rep["custom_init"] = len(mod.store.custom)

    # ---- ① 检索命中真实数据 ----
    search = {}
    for q, scope in (("好象", "b1"), ("好象", "builtin"), ("萧", "builtin"), ("，", "b2")):
        total, _ = mod.store.query(q, scope=scope, limit=1)
        search[f"{q}@{scope}"] = total
    # 与 JSON 实算对照
    rules = PKG / "data" / "rules"
    before = json.loads((rules / "before.json").read_text("utf-8"))
    after = json.loads((rules / "after.json").read_text("utf-8"))
    q = "好象"
    rep["search_json_cross_check"] = dict(
        query=q,
        json_computed=sum(1 for i in range(len(before)) if q in before[i] or q in after[i]),
        data_layer=mod.store.query(q, scope="builtin", limit=1)[0],
    )
    rep["search"] = search
    # 界面命中数 = 数据层
    mod.search, mod.dict_, mod.tier = "好象", "all", "b1"
    mod._page = 0
    mod._render_entries()
    rep["ui_hit_for_haoxiang_b1"] = mod._hit_total
    mod.search, mod.dict_, mod.tier = "", "custom", "custom"
    mod._page = 0
    mod._render_entries()

    # ---- ② 新增：落盘 + 重启持久化 + 与内置分离 ----
    sha0 = sha(custom_path)
    mod._pending_add = dict(word="萧衍", value="萧彦", typ="角色名", pinyin="xiāo yǎn")
    mod.confirm_add(FakeModal())
    sha1 = sha(custom_path)
    restarted = VocabStore(custom_path=custom_path)
    rep["add"] = dict(
        sha_before=sha0, sha_after=sha1, file_changed=sha0 != sha1,
        custom_count=len(mod.store.custom),
        survives_restart=len(restarted.custom) == 1,
        restarted_word=restarted.custom.entries()[0]["word"] if restarted.custom.entries() else None,
        custom_path_parent=str(custom_path.parent),
        builtin_dir=str(mod.store.builtin.dir),
        physically_separate=custom_path.parent != mod.store.builtin.dir,
    )

    # ---- ③ 查重：两种冲突 ----
    both = mod.store.conflicts_for_add("萧衍", "萧彦")
    diff = mod.store.conflicts_for_add("萧衍", "别的替换")
    rep["dup"] = dict(
        same_word_same_value=[c["kind"] for c in both],
        same_word_diff_value=[c["kind"] for c in diff],
        both_triggered=any(c["kind"] == "同词同值" for c in both),
        diff_triggered=any(c["kind"] == "同词异值" for c in diff),
    )
    # 与内置词库撞车也要提示
    b_total, b_rows = mod.store.query("好象", scope="b1", limit=1)
    if b_rows:
        cw = mod.store.conflicts_for_add(b_rows[0]["word"], b_rows[0]["value"])
        rep["dup"]["builtin_conflict_hits"] = len(cw)
        rep["dup"]["builtin_conflict_where"] = sorted({c["where"] for c in cw})

    # ---- ④ 删除：预览→确认→撤销 sha 全等 ----
    mod.store.add_entry(word="甲词", value="甲替", typ="错词校正")
    mod.store.add_entry(word="乙词", value="乙替", typ="错词校正")
    mod._render_all()
    n_before = len(mod.store.custom)
    pre = sha(custom_path)
    ids = [e["id"] for e in mod.store.custom.entries() if e["word"] in ("甲词", "乙词")]
    mod._confirm_delete(ids)                       # 只出预览
    after_preview = sha(custom_path)
    res = mod.do_delete(ids)
    after_delete = sha(custom_path)
    count_after_delete = len(mod.store.custom)
    undo_rec = mod.store.undo()
    after_undo = sha(custom_path)
    rep["delete"] = dict(
        count_before=n_before, removed=res["removed"], count_after=count_after_delete,
        count_after_undo=len(mod.store.custom),
        preview_touched_file=after_preview != pre,
        delete_changed_file=after_delete != pre,
        undo_identical=undo_rec["identical"],
        undo_sha_equal=after_undo == pre,
        sha_before=pre, sha_after_undo=after_undo,
    )
    mod._render_all()

    # ---- ⑤ 合并：真实点击链路 预览→二次确认→写入→撤销 ----
    for w in ("丙", "丁", "戊"):
        mod.store.add_entry(word=w, value=f"{w}替", typ="错词校正")
    mod._render_all()
    n_merge = len(mod.store.custom)
    pre_m = sha(custom_path)
    sel = [e["id"] for e in mod.store.custom.entries()]
    mod._selected = set(sel)
    mod.open_merge()                               # 弹窗 1：预览清单
    step1_sha = sha(custom_path)
    parent = FakeModal()
    preview = mod.do_merge(parent, mod.store.custom.entries()[0]["word"])   # 弹窗 2：二次确认
    step2_sha = sha(custom_path)
    commit = mod._do_merge_commit(FakeModal(), sel, mod.store.custom.entries()[0]["word"])
    step3_sha = sha(custom_path)
    count_after_merge = len(mod.store.custom)
    undo_m = mod.store.undo()
    step4_sha = sha(custom_path)
    rep["merge"] = dict(
        count_before=n_merge, removed=commit["removed"], count_after=count_after_merge,
        count_after_undo=len(mod.store.custom),
        preview_pending=bool(preview and preview.get("pending")),
        preview_touched_file=step1_sha != pre_m,
        confirm_touched_file=step2_sha != pre_m,
        commit_changed_file=step3_sha != pre_m,
        undo_identical=undo_m["identical"],
        undo_sha_equal=step4_sha == pre_m,
        sha_before=pre_m, sha_after_undo=step4_sha,
    )

    # ---- 演示数据残留扫描 ----
    # 残留扫描分两种口径，都不看源码注释（注释里"不含演示数据"是声明，不是数据）：
    #   a) 渲染出来的界面文案（真实控件树里的文字）
    #   b) 硬编码演示条目的痕迹：虚构书名
    from PySide6.QtWidgets import QLabel as _QL, QWidget as _QW
    ghosts = ("星河彼端", "旧巷杂记", "萧景琰", "顾长明")
    ui_texts = [w.text() for w in mod.findChildren(_QL)]
    ui_hits = [(g, t[:80]) for t in ui_texts for g in ghosts if g in t]
    src_hits = []
    for f in sorted((PKG / "fixtext_ui").glob("*.py")):
        for i, line in enumerate(f.read_text("utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if code.strip().startswith(("\"\"\"", "'''")):
                continue
            for g in ghosts:
                if g in code:
                    src_hits.append(dict(file=f.name, line=i, pattern=g))
    rep["demo_residual"] = dict(
        scanned_ui_texts=len(ui_texts),
        ghost_patterns=list(ghosts),
        ui_hits=ui_hits,
        source_hardcoded_hits=src_hits,
        count=len(ui_hits) + len(src_hits),
    )

    # ---- 空状态文案 ----
    from PySide6.QtWidgets import QLabel
    empty = mod._empty_state()
    rep["empty_state"] = empty.text() if isinstance(empty, QLabel) else ""

    mod.close()

    EVID.mkdir(parents=True, exist_ok=True)
    out = EVID / "t31_vocab_evidence.json"
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    print(f"\n证据 -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
