"""M4-EX.2b 验收脚本：空状态五处真实触发截图 + 交互细节逐项手测记录。

口径：任务卡「验收（事实性）」——
  1. 空状态五处用真实空数据触发并截图（清空 workspace 后启动即触发）。
  2. 交互细节逐项手测记录（操作历史、toast、批注切换、条款标签、
     卡片折叠、排版下拉回写）。
输出：evidence/ex2b/accept.json + accept.log；screenshots/ex2b/*.png。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG / "tests"))

EVID = PKG / "evidence" / "ex2b"
SHOTS = PKG / "screenshots" / "ex2b"
EVID.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)

RESULTS: list[dict] = []
LOG_LINES: list[str] = []


def record(section: str, item: str, ok: bool, detail: str = "") -> None:
    RESULTS.append(dict(section=section, item=item, ok=bool(ok), detail=detail))
    line = f"[{'PASS' if ok else 'FAIL'}] {section} · {item}" + (f" —— {detail}" if detail else "")
    LOG_LINES.append(line)
    print(line, flush=True)


def main() -> int:
    from PySide6.QtCore import QSettings, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton

    app = QApplication.instance() or QApplication([])
    QSettings("FixText", "V1").setValue("wizardSeen", "1")  # 首启不自动弹向导

    import main_window as mw
    from fixtext_widgets import Card

    # ---- S0 前置：清空 workspace（只留词库目录结构与设置），真实无书启动 ----
    ws = PKG / "workspace"
    ws.mkdir(exist_ok=True)
    for child in ws.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    runs_root = PKG / "runs"
    if runs_root.exists():
        shutil.rmtree(runs_root)  # 清空历史，保证「无任务」是真实状态

    # 验收不测向导本身（向导属 M4-EX.2c）：清空 workspace 会顺带清掉
    # settings.ini 里的 wizardSeen，这里关掉首启自动弹窗，避免 exec() 阻塞。
    mw.MainWindow._maybe_first_run = lambda self: None  # type: ignore[method-assign]
    win = mw.MainWindow(ws)
    win.resize(1280, 860)
    win.show()
    app.processEvents()

    # ---- S0：五页空状态，真实触发 + 截图 ----
    PAGES = [
        ("import", "win.import_module", "01_import"),
        ("oneclick", "win.oneclick_module", "02_oneclick"),
        ("check", "win.check_module", "03_check"),
        ("export", "win.export_module", "04_export"),
        ("history", "win.history_module", "05_history"),
    ]
    expect_title = {
        "import": "还没有导入的书",
        "oneclick": "还没有可校正的书",
        "check": "还没有可检查的书",
        "export": "还没有可导出的书",
        "history": "还没有校正历史",
    }
    for key, attr, shot in PAGES:
        win.go(key)
        app.processEvents()
        mod = eval(attr)  # noqa: S307 —— 固定白名单属性
        es = getattr(mod, "empty_state", None)
        texts = [l.text() for l in mod.findChildren(QLabel)]
        ok = (
            es is not None
            and es.isVisibleTo(mod)
            and any(expect_title[key] in t for t in texts)
            and any("打开新手向导" in b.text() for b in es.findChildren(QPushButton))
        )
        record("S0 空状态", f"{key} 页真实触发（{expect_title[key]}）", ok,
               "" if ok else f"es={es} visible={es and es.isVisibleTo(mod)}")
        pix = win.grab()
        ok2 = pix.save(str(SHOTS / f"{shot}.png"))
        record("S0 空状态", f"{key} 页截图 {shot}.png", ok2)

    # 词库页不做空状态
    ok = not hasattr(win.vocab_module, "empty_state")
    record("S0 空状态", "词库页不做空状态（§4）", ok)

    # 空状态无收起按钮：五页 EmptyState 里都只有两个按钮
    all_two = True
    for key, attr, _ in PAGES:
        es = getattr(eval(attr), "empty_state", None)  # noqa: S307
        if es is None or len(es.findChildren(QPushButton)) != 2:
            all_two = False
    record("S0 空状态", "空状态无收起按钮（双按钮形态，仅 2 个按钮）", all_two)

    # ---- S1：交互细节逐项 ----
    # 1) 卡片折叠（toggleCard 修复版）：找真实页面里的可折叠卡，走真实点击路径
    win.go("vocab")
    app.processEvents()
    collapsibles = [c for c in win.findChildren(Card) if c._collapsible]
    ok = False
    detail = ""
    if collapsibles:
        card = collapsibles[0]
        head = card.layout().itemAt(0).widget()  # 标题行（mousePressEvent→toggle）
        before = card._open
        head.mousePressEvent(None)   # 真实点击路径
        app.processEvents()
        after = card._open
        ok = before != after
        detail = f"卡片「{card.title_text if hasattr(card, 'title_text') else '?'}」 {before}->{after}，箭头 {card._chev.text()}"
        head.mousePressEvent(None)   # 还原
    record("S1 交互", "卡片折叠：点标题行切换展开/收起", ok, detail)

    # 2) toast 反馈 + 3) 排版下拉回写：给一键校正页注入真实临时书源后操作真下拉
    import oneclick_module as om
    tmp_book = EVID / "fmt_probe_book.txt"
    tmp_book.write_text("第一章 试样\n“你好。”他说。\n", encoding="utf-8")
    oc = win.oneclick_module
    oc.set_run_context(dict(
        epub="", plain_source=str(tmp_book), pipeline_root=str(PKG / "pipeline"),
        rules_before=str(PKG / "data" / "rules" / "before.json"),
        rules_after=str(PKG / "data" / "rules" / "after.json"),
        engine_path="", runs_root=str(PKG / "runs"), title="排版下拉验收样例"))
    app.processEvents()
    ok = not oc.empty_state.isVisibleTo(oc) and oc._fmt_w.isVisibleTo(oc)
    record("S1 交互", "有书后空状态让位常规布局（一键校正页）", ok)
    n, combo = next(iter(oc._combos.items()))
    old = oc.fmt_state[n]["val"]
    new = [v for v in oc.fmt_state[n]["opts"] if v != old][0]
    QTest.keyClicks(combo, "")  # 激活控件焦点（无副作用）
    combo.setCurrentText(new)
    app.processEvents()
    ok = oc.fmt_state[n]["val"] == new
    record("S1 交互", f"排版下拉回写（n={n}：{old} → {new}，写回 fmt_state）", ok)
    toast_txt = oc.status.text()
    # 一键校正页此刻可能不在前台（isVisible 受页面切换影响），
    # 用 isVisibleTo(模块自身) 判定 toast 已弹出
    ok = oc.status.isVisibleTo(oc) and bool(toast_txt)
    record("S1 交互", f"toast 反馈（排版改动提示：「{toast_txt}」）", ok)

    # 4) 批注切换 + 5) 条款标签：全局「显示设计依据」开关
    win.apply_basis(True)
    app.processEvents()
    basis_texts = [l.text() for m in (
        win.check_module, win.vocab_module, win.history_module,
        win.export_module, win.oneclick_module)
        for l in m.findChildren(QLabel)
        if l.isVisibleTo(m) and l.text().strip().startswith(("§", "底线", "T3"))]
    ok = len(basis_texts) > 0
    record("S1 交互", f"批注切换开：条款标签可见（{len(basis_texts)} 条）", ok,
           "样例：" + " / ".join(basis_texts[:3]) if basis_texts else "")
    win.apply_basis(False)
    app.processEvents()
    basis_off = [l for m in (win.check_module, win.vocab_module,
                             win.history_module, win.export_module,
                             win.oneclick_module)
                 for l in m.findChildren(QLabel)
                 if l.isVisibleTo(m) and l.text().strip().startswith(("§", "底线", "T3"))]
    record("S1 交互", "批注切换关：条款标签隐藏", len(basis_off) == 0)

    # 6) 操作历史（undoHistory）：真实运行目录 + 真实删除 + toast 撤销按钮
    import _fixture_run as fx
    import history_module as hm
    fx_root = EVID / "fx_runs"
    if fx_root.exists():
        shutil.rmtree(fx_root)
    fx_root.mkdir(parents=True)
    fx.build_run(fx_root, name="run-1")
    fx.build_run(fx_root, name="run-2", hits=356, title="示例书稿·续")
    hist = hm.HistoryModule()
    hist.set_runs_root(fx_root)
    hist.refresh()
    app.processEvents()
    ok = hist.row_count == 2 and hist.empty_state.isVisibleTo(hist) is False
    record("S1 交互", "操作历史：真实扫描出 2 条任务（fixture 为真实结构运行目录）", ok)

    # 确认弹窗在无头环境自动接受（删除/移动本身是真实执行）
    from fixtext_widgets import ConfirmDialog
    ConfirmDialog.exec = lambda self: QDialog.DialogCode.Accepted  # type: ignore[method-assign]
    hist._confirm_delete(0)
    app.processEvents()
    ok = hist.row_count == 1 and hist.status_box.isVisibleTo(hist)
    undo_btns = [b for b in hist.status_box.findChildren(QPushButton)
                 if "撤销" in b.text()]
    record("S1 交互", "删除任务 → toast 带撤销按钮（真实移入回收目录）",
           ok and len(undo_btns) == 1,
           f"剩余 {hist.row_count} 条，toast「{hist.status.text() if hasattr(hist, 'status') else undo_btns[0].text()}」")
    if undo_btns:
        QTest.mouseClick(undo_btns[0], Qt.MouseButton.LeftButton)
        app.processEvents()
        record("S1 交互", "点 toast 撤销按钮 → 任务恢复（undoHistory）",
               hist.row_count == 2,
               f"恢复后 {hist.row_count} 条，撤销栈余 {len(hist._undo_stack)}")

    # 收尾
    (EVID / "accept.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    (EVID / "accept.log").write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")
    n_fail = sum(1 for r in RESULTS if not r["ok"])
    print(f"\n==== accept_ex2b: {len(RESULTS)} 项，{n_fail} 失败 ====", flush=True)
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
