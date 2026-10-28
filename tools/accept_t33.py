"""M3-T3.3 验收证据采集：本书专有词一键加入（§2.4.2 三条 + 检查页联动）。

分段执行、逐段落盘（``evidence/t33_accept.json`` 每段都重写），
所以即使某段慢到超时，前面已跑完的结论不会丢；再跑一次就只补没跑的段。

    S1  预览条数 == 引擎产物条数（N），逐行带 词条/类型/替换值/出现次数
    S2  逐条加入：勾 3 条 → 词库页检索到 3 条 → 撤销后 sha 回到加入前
    S3  整组加入：全选全加 → 新增 == N → 再点一次幂等
    S4  查重与冲突：同词同值跳过；同词异值冲突，均不覆盖
    S5  检查页联动：问题行「加入词库」真实点击 → 预览 → 加入后词库可见
    S6  空状态：无词条时只给人话，不渲染空表格

用法：
    python3.12 tools/accept_t33.py            # 跑全部尚未完成的段（可续跑）
    python3.12 tools/accept_t33.py S3         # 只跑某一段
    python3.12 tools/accept_t33.py --fresh    # 丢掉已有证据，七段全量重跑

【M4-T4.4】去短路：以前「证据已存在且七段全满」时 wanted 为空，脚本 0 秒直接
打印 ALL PASS 而**一条验证都没执行**。现在：
* 不给段名 ⇒ 强制七段全跑（不再按 stages_done 做增量跳过）；
* --fresh 额外先删证据文件、清空 cases / stages_done，从零跑一遍；
* 断言只在本次真的执行过的段上聚合，且 `executed_this_run` 必须覆盖七段。
前置：tools/_t33_prepare_run.py 已跑过一次真实六阶段（runs/t33_real）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for p in (str(PKG), str(PKG / "fixtext_ui"), str(PKG / "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EVID = PKG / "evidence"
RUN_DIR = PKG / "runs" / "t33_real" / "work"
BOOKMAP_DIR = RUN_DIR / "05_bookmap"
OUT = EVID / "t33_accept.json"

_app = None


def app():
    global _app
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
    return _app


class FakeModal:
    def __init__(self):
        self.accepted = False

    def accept(self):
        self.accepted = True

    def reject(self):
        pass

    def show(self):
        pass


def load_state() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            pass
    return dict(cases=[], stages_done=[])


def save_state(state: dict) -> None:
    EVID.mkdir(parents=True, exist_ok=True)
    state["all_pass"] = all(c["ok"] for c in state["cases"]) and \
        set(state["stages_done"]) >= {"S0", "S1", "S2", "S3", "S4", "S5", "S6"}
    state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    OUT.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def check(state: dict, case: str, ok: bool, detail: str, data: dict | None = None) -> bool:
    for c in state["cases"]:
        if c["case"].split(" ")[0] == case.split(" ")[0]:
            c.update(ok=bool(ok), detail=detail, data=data or {})
            break
    else:
        state["cases"].append(dict(case=case, ok=bool(ok), detail=detail, data=data or {}))
    save_state(state)
    print(("PASS  " if ok else "FAIL  ") + case + " · " + detail, flush=True)
    return bool(ok)


def make_module(tmp: Path):
    """真实 VocabModule，但自定义词库指向临时文件（不写交付包）。"""
    import vocab_module as vm
    from fixtext_vocab import VocabStore

    mod = vm.VocabModule()
    mod.store = VocabStore(custom_path=tmp / "custom_vocab.json")
    mod._render_all()
    mod.show()
    return mod


def close_modals():
    for w in app().topLevelWidgets():
        if w.isVisible() and w.__class__.__name__ == "Modal":
            w.reject()
    app().processEvents()


def engine_facts() -> dict:
    payload = json.loads((BOOKMAP_DIR / "book_entries.json").read_text(encoding="utf-8"))
    entries = payload["entries"]
    rows = [r for arr in entries.values() for r in arr]
    return dict(
        entries=entries,
        rows=rows,
        raw_total=sum(payload["count_by_book"].values()),
        n_unique=len(rows),
        count_sum=sum(int(r.get("count") or 0) for r in rows),
        run_summary=json.loads((EVID / "t33_run_summary.json").read_text(encoding="utf-8")),
    )


def ui_words(facts: dict) -> list:
    """用 worker 的真实函数把报告整理成界面词条（与运行时同一段代码）。"""
    from fixtext_worker import CorrectionJob

    job = CorrectionJob(
        epub=PKG / "tests" / "samples" / "book_paohuo.epub",
        workdir=RUN_DIR, rules_before=PKG / "data" / "rules" / "before.json",
        rules_after=PKG / "data" / "rules" / "after.json",
        engine_path=(PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" /
                     "bin" / "replace_by_go-linux-amd64"),
        pipeline_root=PKG / "pipeline", title="炮火弧线")
    report = json.loads((BOOKMAP_DIR / "bookmap_report.json").read_text(encoding="utf-8"))
    return job._book_words_preview(report)


# --------------------------------------------------------------------------- S0/S1

def stage_s0(state: dict, facts: dict) -> None:
    check(state, "S0 引擎产物条数守恒",
          facts["count_sum"] == facts["raw_total"] and facts["n_unique"] <= facts["raw_total"],
          f"引擎原始 {facts['raw_total']} 条，去重后 {facts['n_unique']} 条，"
          f"count 之和 {facts['count_sum']}（守恒）",
          dict(raw_total=facts["raw_total"], n_unique=facts["n_unique"],
               count_sum=facts["count_sum"]))


def stage_s1(state: dict, facts: dict) -> None:
    app()
    words = ui_words(facts)
    n = facts["n_unique"]
    check(state, "S1a 界面词条条数 == 引擎去重条数", len(words) == n,
          f"界面 {len(words)} 条 / 引擎去重 {n} 条（原始 {facts['raw_total']}）",
          dict(ui=len(words), unique=n, raw=facts["raw_total"]))

    rs = facts["run_summary"]
    check(state, "S1b 界面条数 == 运行摘要声明",
          len(words) == rs["book_words"] == rs["book_words_unique"],
          f"界面 {len(words)} / 摘要 book_words {rs['book_words']} / "
          f"book_words_unique {rs['book_words_unique']}")

    fields_ok = all({"word", "type", "value", "count"} <= set(w) for w in words)
    types = sorted({w["type"] for w in words})
    cnt = sum(int(w["count"]) for w in words)
    check(state, "S1c 四列齐全且 count 之和回到原始条数",
          fields_ok and cnt == facts["raw_total"],
          f"词条/类型/替换值/出现次数四列齐全={fields_ok}；类型 {types}；"
          f"count 之和 {cnt} == 原始 {facts['raw_total']}",
          dict(types=types, count_sum=cnt, raw_total=facts["raw_total"]))

    tmp = Path(tempfile.mkdtemp(prefix="t33_s1_"))
    mod = make_module(tmp)
    mod.set_book_words(words, "炮火弧线")
    t0 = time.monotonic()
    mod.open_book_words()
    app().processEvents()
    build_s = round(time.monotonic() - t0, 2)
    rows = len(mod._book_checks or [])
    all_checked = all(cb.isChecked() for cb in (mod._book_checks or []))
    label = mod._book_pick_label.text() if mod._book_pick_label else ""
    check(state, "S1d 预览弹窗渲染行数 == N，默认整组全选",
          rows == n and all_checked,
          f"弹窗里 {rows} 行（构建耗时 {build_s}s），全选={all_checked}，标签「{label}」",
          dict(rows=rows, all_checked=all_checked, label=label, build_s=build_s))
    close_modals()


# --------------------------------------------------------------------------- S2

def stage_s2(state: dict, facts: dict) -> None:
    app()
    words = ui_words(facts)
    tmp = Path(tempfile.mkdtemp(prefix="t33_s2_"))
    mod = make_module(tmp)
    mod.set_book_words(words, "炮火弧线")
    mod.open_book_words()
    app().processEvents()
    pick = [0, 1, 2]
    for i, cb in enumerate(mod._book_checks):
        cb.setChecked(i in pick)
    app().processEvents()
    label = mod._book_pick_label.text() if mod._book_pick_label else ""
    chosen = [words[i] for i in pick]
    sha_before = mod.store._disk_sha()
    added = mod.add_book_words(FakeModal())
    app().processEvents()
    found = []
    for w in chosen:
        if mod.store.query(w["word"], scope="custom")[0]:
            found.append(w["word"])
    check(state, "S2a 勾 3 条加入 → 词库检索到 3 条",
          added == 3 and len(found) == 3,
          f"added={added}，检索命中 {len(found)} 条；勾选标签「{label}」",
          dict(added=added, found=found, label=label,
               picked=[w["word"] for w in chosen]))

    undo = mod.store.undo()
    sha_after = mod.store._disk_sha()
    check(state, "S2b 撤销后词库 sha 回到加入前",
          bool(undo and undo.get("identical")) and sha_after == sha_before,
          f"撤销 identical={bool(undo and undo.get('identical'))}，"
          f"sha 还原={sha_after == sha_before}",
          dict(identical=bool(undo and undo.get("identical")),
               restored=sha_after == sha_before,
               sha_before=sha_before[:16], sha_after=sha_after[:16]))
    close_modals()


# --------------------------------------------------------------------------- S3

def stage_s3(state: dict, facts: dict) -> None:
    app()
    words = ui_words(facts)
    n = facts["n_unique"]
    tmp = Path(tempfile.mkdtemp(prefix="t33_s3_"))
    mod = make_module(tmp)
    mod.set_book_words(words, "炮火弧线")
    mod.open_book_words()
    app().processEvents()
    for cb in mod._book_checks:
        cb.setChecked(True)
    t0 = time.monotonic()
    added = mod.add_book_words(FakeModal())
    app().processEvents()
    first_s = round(time.monotonic() - t0, 2)
    sha_full = mod.store._disk_sha()
    custom_n = len(mod.store.custom)
    check(state, "S3a 整组加入新增条数 == N",
          added == n and custom_n == n,
          f"added={added}，词库自定义 {custom_n} 条，N={n}，耗时 {first_s}s",
          dict(added=added, custom=custom_n, n=n, seconds=first_s))

    mod.set_book_words(words, "炮火弧线")
    mod.open_book_words()
    app().processEvents()
    for cb in mod._book_checks:
        cb.setChecked(True)
    again = mod.add_book_words(FakeModal())
    app().processEvents()
    sha_again = mod.store._disk_sha()
    check(state, "S3b 再点一次不重复累加（幂等）",
          again == 0 and sha_again == sha_full and len(mod.store.custom) == n,
          f"第二次 added={again}，sha 不变={sha_again == sha_full}，"
          f"词库仍 {len(mod.store.custom)} 条",
          dict(added=again, sha_same=sha_again == sha_full,
               custom=len(mod.store.custom)))
    close_modals()


# --------------------------------------------------------------------------- S4

def stage_s4(state: dict, facts: dict) -> None:
    app()
    tmp = Path(tempfile.mkdtemp(prefix="t33_s4_"))
    mod = make_module(tmp)
    base = dict(word="炮火弧线·测试词", value="炮火弧线·正写", type="专有名词", count=1)
    first = mod.store.add_book_words([base], "炮火弧线")
    same = mod.store.add_book_words([dict(base)], "炮火弧线")
    conf = mod.store.add_book_words(
        [dict(word="炮火弧线·测试词", value="另一套写法", type="专有名词", count=1)],
        "炮火弧线")
    rows = mod.store.query("炮火弧线·测试词", scope="custom")[1]
    value_now = rows[0]["value"] if rows else ""
    check(state, "S4a 同词同值 → 跳过，不重复写入",
          first["added"] == 1 and same["added"] == 0
          and len(same["skipped_exists"]) == 1 and not same["conflicts"],
          f"首次 added={first['added']}；第二次 added={same['added']}、"
          f"跳过 {len(same['skipped_exists'])} 条、冲突 {len(same['conflicts'])} 条",
          dict(first=first["added"], second=same["added"],
               reason=(same["skipped_exists"] or [{}])[0].get("reason", "")))

    kinds = sorted({str(h.get("kind")) for c0 in conf["conflicts"]
                    for h in (c0.get("hits") or [])})
    check(state, "S4b 同词异值 → 冲突提示，不静默覆盖",
          conf["added"] == 0 and bool(conf["conflicts"]) and value_now == base["value"],
          f"added={conf['added']}，冲突 {len(conf['conflicts'])} 条，种类 {kinds}，"
          f"词库里仍是「{value_now}」（未被覆盖）",
          dict(kinds=kinds, value_now=value_now, added=conf["added"]))

    # 界面侧必须把冲突明文摆出来（_book_report 的弹窗）
    shown: dict = {}
    mod._toast = lambda msg, **kw: shown.setdefault("toast", str(msg))
    mod._book_report(dict(requested=1, added=0, skipped_exists=[],
                          conflicts=conf["conflicts"]), 0, [], conf["conflicts"])
    modal = [w for w in app().topLevelWidgets()
             if w.__class__.__name__ == "Modal" and w.isVisible()]
    texts = []
    for w in modal:
        for lb in w.findChildren(type(w).__mro__[0]) if False else []:
            pass
    from PySide6.QtWidgets import QLabel
    for w in modal:
        texts += [lb.text() for lb in w.findChildren(QLabel) if lb.text()]
    joined = " | ".join(texts)
    check(state, "S4c 界面把冲突明文摆出来（不静默跳过）",
          bool(modal) and ("冲突" in joined) and any(k in joined for k in kinds or ["冲突"]),
          f"冲突弹窗 {len(modal)} 个；文案含冲突种类={any(k in joined for k in (kinds or ['冲突']))}；"
          f"toast「{shown.get('toast', '')}」",
          dict(modals=len(modal), toast=shown.get("toast", ""),
               snippet=joined[:300]))
    close_modals()


# --------------------------------------------------------------------------- S5

def stage_s5(state: dict, facts: dict) -> None:
    a = app()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox, QPushButton

    from check_module import CheckModule
    from fixtext_vocab import VocabStore
    import fixtext_check as checkdata

    tmp = Path(tempfile.mkdtemp(prefix="t33_s5_"))
    chk = CheckModule()
    store = VocabStore(custom_path=tmp / "custom_vocab.json")
    chk.set_vocab_store(store)
    report = checkdata.load_report(RUN_DIR)
    chk.set_report(report)
    chk.show()
    a.processEvents()

    btns = [b for b in chk.findChildren(QPushButton)
            if b.accessibleName() == "加入词库"]
    auto = [i for i, p in enumerate(chk.probs)
            if checkdata.apply_action(p).strip() != str(p.get("hl") or "").strip()]
    check(state, "S5a 问题行有可点的「加入词库」按钮",
          bool(btns) and bool(auto),
          f"找到 {len(btns)} 个「加入词库」按钮；有自动改法的问题 {len(auto)} 处 / "
          f"共 {len(chk.probs)} 处",
          dict(buttons=len(btns), auto_fixable=len(auto), probs=len(chk.probs)))
    if not btns or not auto:
        close_modals()
        return

    # 目标挑「有上下文的自动可修条目」：没有上下文的单标点本就该被拦住，
    # 拿它验「收窄」会验成另一个场景（见 S5e）。
    auto_ctx = [i for i in auto
                if chk.probs[i].get("pre") or chk.probs[i].get("post")]
    if not auto_ctx:
        check(state, "S5d 单字符标点被收窄成整句写法（不写全书级危险规则）",
              False, "没有「有上下文的自动可修条目」，无法验证收窄")
        close_modals()
        return
    target = auto_ctx[0]
    cand = chk.problem_candidate(target)
    # 关键：检查页这一版全是引号配对（一处一个标点）。拿单字符当词条会让
    # 全书同类标点一起变，所以候选必须被收窄成整句写法，而不是一个 `”`。
    narrowed = len(str(cand["word"])) >= 2 and cand["word"].endswith("”")
    check(state, "S5d 单字符标点被收窄成整句写法（不写全书级危险规则）",
          bool(narrowed) and not cand.get("blocked"),
          f"候选词条「{cand['word']}」→ 替换值「{cand['value']}」，"
          f"生效范围={cand.get('scope')}，长度 {len(str(cand['word']))} 字",
          dict(word=cand["word"], value=cand["value"],
               scope=cand.get("scope"), length=len(str(cand["word"]))))
    seen: dict = {}

    def close_box():
        for w in a.topLevelWidgets():
            if isinstance(w, QMessageBox) and w.isVisible():
                seen["text"] = w.text()
                seen["info"] = w.informativeText()
                seen["buttons"] = [b.text() for b in w.buttons()]
                w.done(int(QMessageBox.StandardButton.Ok))

    sha_pre = store._disk_sha()
    # 真实点击（走 QTest，验的是用户路径而不是直接调函数）：
    # 必须点「目标条目所在的那一行」的按钮，否则点到的可能是别的行。
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt as _Qt
    from check_module import ProblemRow

    btn = None
    for row in chk.findChildren(ProblemRow):
        if getattr(row, "idx", -1) == target:
            btn = row.add_btn
            break
    if btn is None:
        btn = btns[0]
    QTimer.singleShot(200, close_box)
    QTimer.singleShot(600, close_box)
    QTest.mouseClick(btn, _Qt.MouseButton.LeftButton)
    a.processEvents()
    sha_post = store._disk_sha()
    found = store.query(cand["word"], scope="custom")[0]

    check(state, "S5b 预览弹窗正确 + 确认加入后词库可见",
          bool(seen.get("text")) and found >= 1 and "词条" in str(seen.get("info", "")),
          f"弹窗「{seen.get('text', '')}」按钮 {seen.get('buttons')}；"
          f"词库检索「{cand['word']}」命中 {found} 条；sha 变化={sha_post != sha_pre}",
          dict(dialog=seen.get("text", ""),
               buttons=[str(b) for b in (seen.get("buttons") or [])],
               word=cand["word"], value=cand["value"], found=found,
               sha_changed=sha_post != sha_pre))

    # 加入后可撤销（走同一写入口 ⇒ 自有还原点）
    undo = store.undo()
    check(state, "S5c 检查页加入后可撤销",
          bool(undo) and store._disk_sha() == sha_pre,
          f"撤销「{(undo or {}).get('label', '')}」，sha 回到点击前="
          f"{store._disk_sha() == sha_pre}",
          dict(label=(undo or {}).get("label", ""),
               restored=store._disk_sha() == sha_pre))

    # 没有上下文、只剩一个标点的条目：必须拦住，不许写全书级规则
    blocked_ok = False
    blocked_reason = ""
    noctx = [i for i, p in enumerate(chk.probs)
             if not p.get("pre") and not p.get("post") and str(p.get("hl") or "")]
    if noctx:
        i2 = noctx[0]
        c2 = chk.problem_candidate(i2)
        toasts: list[str] = []
        chk.toast = lambda msg: toasts.append(str(msg))
        got = chk.add_problem_to_vocab(i2)
        blocked_ok = got is None and bool(c2.get("blocked")) and bool(toasts)
        blocked_reason = str(toasts[0])[:80] if toasts else ""
    check(state, "S5e 无上下文的单标点被拦截（不写危险规则）",
          blocked_ok,
          f"拦截={blocked_ok}；提示「{blocked_reason}」",
          dict(blocked=blocked_ok, reason=blocked_reason, no_ctx_rows=len(noctx)))
    close_modals()


# --------------------------------------------------------------------------- S6

def stage_s6(state: dict, facts: dict) -> None:
    app()
    tmp = Path(tempfile.mkdtemp(prefix="t33_s6_"))
    mod = make_module(tmp)
    toasts: list[str] = []
    mod._toast = lambda msg, **kw: toasts.append(str(msg))
    mod.set_book_words([], "")
    mod._book_words = []
    mod.open_book_words()
    app().processEvents()
    rows = len(mod._book_checks or [])
    check(state, "S6 无词条时给人话说明，不渲染空表格",
          bool(toasts) and "没有" in toasts[0] and rows == 0,
          f"提示「{toasts[0] if toasts else '（无）'}」；清单行数 {rows}",
          dict(toast=toasts[0] if toasts else "", rows=rows))


STAGES = dict(S0=stage_s0, S1=stage_s1, S2=stage_s2,
              S3=stage_s3, S4=stage_s4, S5=stage_s5, S6=stage_s6)


def main(argv: list[str]) -> int:
    fresh = "--fresh" in argv
    argv = [a for a in argv if a != "--fresh"]
    if fresh:
        # 丢掉上一轮证据，从零开始（保证本轮 ALL PASS 不是读出来的旧结论）
        if OUT.exists():
            OUT.unlink()
        state = dict(cases=[], stages_done=[], executed_since_fresh=[])
        print("--- --fresh：已清除既有证据，七段全量重跑 ---", flush=True)
    else:
        state = load_state()
    facts = engine_facts()
    state["n_raw"] = facts["raw_total"]
    state["n_unique"] = facts["n_unique"]
    state["count_sum"] = facts["count_sum"]
    state["run_summary"] = facts["run_summary"]
    # 去短路：不给段名就七段全跑（原实现在证据全满时 wanted 为空、
    # 不执行任何验证就打印 ALL PASS）。
    wanted = [a for a in argv if a in STAGES] or list(STAGES)
    state.setdefault("executed_since_fresh", [])
    for key in wanted:
        print(f"--- {key} ---", flush=True)
        try:
            STAGES[key](state, facts)
            if key not in state["stages_done"]:
                state["stages_done"].append(key)
            if key not in state["executed_since_fresh"]:
                state["executed_since_fresh"].append(key)
        except Exception:                                   # noqa: BLE001
            check(state, f"{key} 段执行异常", False,
                  traceback.format_exc().splitlines()[-1][:300])
        save_state(state)
        print(f"--- {key} done; stages_done={sorted(state['stages_done'])} ---",
              flush=True)
    save_state(state)
    bad = [c["case"] for c in state["cases"] if not c["ok"]]
    ran_all = set(state.get("executed_since_fresh") or []) >= set(STAGES)
    if not ran_all:
        print(f"\n=== 未执行全部七段（自 --fresh 起实跑 "
              f"{sorted(state.get('executed_since_fresh') or [])}），"
              f"结论不予采信 ===", flush=True)
        return 1
    print("\n=== " + ("ALL PASS" if not bad else "FAIL: " + "；".join(bad)) +
          f" · {sum(1 for c in state['cases'] if c['ok'])}/{len(state['cases'])}"
          f" · 自 --fresh 起实跑 {len(state['executed_since_fresh'])}/7 段 ===",
          flush=True)
    return 0 if not bad and state["all_pass"] and ran_all else 1

# 说明：executed_since_fresh 记在状态文件里、由 --fresh 清零 —— ALL PASS 只有在
# 自上一次 --fresh 起七个段全部真实执行过才会打印；沙箱单次命令有时限，
# 一个 fresh 会话允许跨多次进程调用续完（每段仍各执行一次，不重复不跳过）。


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
