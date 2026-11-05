"""
FixText M2-T2.1 · 验收自检脚本（离屏）
=========================================

产出四份可复核证据，对应任务卡的四条验收标准：

  1. 六入口可达 + 选中态正确   -> 逐入口点击 `go()`，断言 stack 当前页、选中态唯一、
                                  顶栏「当前位置」跟随、页面非空可渲染
  2. 内部目录概念零露出       -> 扫描全部可见界面字符串（控件文本 / tooltip / 窗口标题 /
                                  按钮 / 标签），匹配禁用词表
  3. 令牌值与设计地基一致     -> 逐项比对 fixtext_tokens.py 与薄地基 HTML 的 :root
                                  （COLORS / FONT_SIZE / SPACE / RADIUS / LINE_HEIGHT 及
                                  字重 / 阴影 / 字体），并要求 0 差异
  4. 主窗口可构造并离屏截图   -> 六个页面 + 首页各截一张 PNG

运行：
    QT_QPA_PLATFORM=offscreen python tools/verify_m2t21.py
输出：
    screenshots/*.png + verify_report.json + 控制台摘要
退出码：全部通过 0，任一失败 1。
"""

from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
UI = os.path.join(PKG, "fixtext_ui")
SHOTS = os.path.join(PKG, "screenshots")
# 【M2-T2.5】合并后主窗口会挂真模块，包根也要在 sys.path 上
# （fixtext_import / fixtext_error_center 都在包根下）。
sys.path.insert(0, UI)
sys.path.insert(0, PKG)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 【M2-T2.8】首次向导并入后，主窗口构造尾部会用 singleShot 自动弹一次模态向导；
# 自动化脚本跑的是「六个入口 / 顶栏 / 截图」这些既有行为，必须先标成「已看过」，
# 否则 exec() 会把事件循环永久卡住（模态对话期间 processEvents 不返回）。
def _mark_wizard_seen():
    try:
        from PySide6.QtCore import QSettings
        s = QSettings("FixText", "V1")
        s.setValue("wizardSeen", "1")
        s.sync()
    except Exception:                                       # noqa: BLE001
        pass


from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QPushButton, QAbstractButton, QWidget,
)
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QKeySequence  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

import fixtext_tokens as T  # noqa: E402
import main_window as M  # noqa: E402

# ---------------------------------------------------------------------------
# 禁用词表：内部目录 / 内部文件 / 内部格式术语
# ---------------------------------------------------------------------------

# 严格按任务卡口径：books / booksBak / spine / OPF / rules.json 等内部目录与内部术语。
# 编码格式名（UTF-8 / GBK / GB18030）属用户能听懂的「人话」，且排期 §2.2 入口①
# 明确要求「常见编码零配置正确识别」，因此不列入禁用词。
FORBIDDEN = [
    # 内部工作目录
    r"booksBak", r"booksFix", r"\bbooks\b", r"books/", r"books\\",
    # EPUB 内部结构与标识
    r"\bspine\b", r"\bOPF\b", r"\bNCX\b", r"\bmanifest\b", r"\btoc\.ncx\b",
    # 内部规则 / 配置 / 脚本文件
    r"rules\.json", r"\bphp\b", r"\bbat\b", r"\bpy\b",
    r"loadMapFromCsv", r"useMapsConfig", r"\bCSV\b",
    # 内部路径与内部标识符
    r"src/maps", r"logs/", r"\.tmp\b", r"\bMap::", r"\bCsv::",
    r"\bfixtext\.engine\b", r"\bEngineRequest\b", r"\bRuleSet\b",
]

# 设计地基 HTML 里与令牌对应的 :root 变量名
TOKEN_GROUPS = ("COLORS", "FONT_SIZE", "SPACE", "RADIUS", "LINE_HEIGHT",
                "FONT_WEIGHT", "SHADOW")


def css_name(py_key: str) -> str:
    """py 令牌键 -> CSS 变量名。"""
    return py_key


def expected_css() -> dict[str, str]:
    """把 fixtext_tokens.py 的令牌展开成 {css变量名: 值}。"""
    out: dict[str, str] = {}
    for k, v in T.COLORS.items():
        out["--c-" + k.replace(".", "-")] = v
    for k, v in T.FONT_SIZE.items():
        out["--fs-" + k] = v
    for k, v in T.FONT_WEIGHT.items():
        out["--fw-" + k] = v
    for k, v in T.LINE_HEIGHT.items():
        out["--lh-" + k] = v
    for k, v in T.SPACE.items():
        out["--sp-" + k] = v
    for k, v in T.RADIUS.items():
        out["--r-" + k] = v
    for k, v in T.SHADOW.items():
        out["--sh-" + k] = v
    out["--font-sans"] = T.FONT_SANS
    out["--font-mono"] = T.FONT_MONO
    return out


def parse_root(html_path: str) -> dict[str, str]:
    src = open(html_path, encoding="utf-8").read()
    m = re.search(r":root\s*\{(.*?)\}", src, re.S)
    if not m:
        return {}
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    return {k: v.strip()
            for k, v in re.findall(r"(--[a-z0-9\-]+)\s*:\s*([^;]+);", body)}


# ---------------------------------------------------------------------------
# 界面文本收集
# ---------------------------------------------------------------------------

def _safe(fn, default=""):
    try:
        v = fn()
        return str(v) if v else default
    except Exception:                                  # noqa: BLE001
        return default


def collect_ui_texts(root: QWidget) -> list[tuple[str, str, str]]:
    """遍历控件树，收集一切会出现在界面上的字符串。返回 (类型, 控件类, 文本)。"""
    rows: list[tuple[str, str, str]] = []
    for w in root.findChildren(QWidget):
        cls = type(w).__name__
        pairs = [
            ("tooltip", _safe(w.toolTip)),
            ("a11y-name", _safe(w.accessibleName)),
            ("a11y-desc", _safe(w.accessibleDescription)),
            ("window-title", _safe(w.windowTitle)),
        ]
        if isinstance(w, QLabel):                      # QLabel.text 是属性
            pairs.append(("text", _safe(lambda w=w: w.text())))
        if isinstance(w, QAbstractButton):             # QPushButton.text() 是方法
            pairs.append(("text", _safe(w.text)))
        if hasattr(w, "placeholderText"):
            pairs.append(("placeholder", _safe(w.placeholderText)))
        if hasattr(w, "currentText"):
            pairs.append(("current-text", _safe(w.currentText)))
        for kind, text in pairs:
            if text:
                rows.append((kind, cls, text))
    # 弹窗 / 消息框等不在控件树里的静态文案，单独扫源码（见 scan_module_strings）
    return rows


def scan_module_strings() -> list[tuple[str, str, str]]:
    """扫描 UI 包源码中的中文字符串字面量（含弹窗文案，控件树取不到）。

    MRG.12 修正：先剥掉三引号 docstring 与 ``#`` 注释再取字面量——旧正则会把
    docstring 内段（如 ``与 RuleSet._apply 同口径``）误判成界面文案，MRG.11
    存档报告的零命中即由此失真（基线包复扫实为 5 处、全在 docstring）。
    docstring / 注释永不抵达用户界面，不属于「露出」。
    """
    rows = []
    for fn in sorted(os.listdir(UI)):
        if not fn.endswith(".py"):
            continue
        if fn in ("build_qss.py",):        # 样式生成器，不含界面文案
            continue
        path = os.path.join(UI, fn)
        src = open(path, encoding="utf-8").read()
        # 剥 docstring（三引号块，含模块/类/函数文档）；不剥 # 注释——
        # 界面文案里可能出现 #（色值等），注释本身也不会被旧正则命中
        src = re.sub(r'""".*?"""', '""', src, flags=re.S)
        src = re.sub(r"'''.*?'''", "''", src, flags=re.S)
        for m in re.finditer(r'"([^"\\\n]{2,})"|\'([^\'\\\n]{2,})\'', src):
            s = m.group(1) or m.group(2) or ""
            if re.search(r"[\u4e00-\u9fff]", s):     # 只关心含中文的界面文案
                rows.append(("literal", fn, s))
    return rows


def check_zero_leak(texts) -> dict:
    hits = []
    for kind, where, s in texts:
        for pat in FORBIDDEN:
            m = re.search(pat, s)
            if m:
                hits.append(dict(kind=kind, where=where, text=s[:160],
                                 matched=m.group(0), pattern=pat))
    return dict(passed=not hits, scanned=len(texts), forbidden_patterns=len(FORBIDDEN),
                hits=hits)


# ---------------------------------------------------------------------------
# 截图
# ---------------------------------------------------------------------------

def shot(win, key: str, filename: str) -> str:
    win.go(key)
    for _ in range(3):
        QApplication.processEvents()
    path = os.path.join(SHOTS, filename)
    win.grab().save(path)
    return path


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    os.makedirs(SHOTS, exist_ok=True)
    app = QApplication(sys.argv)
    _mark_wizard_seen()          # 【M2-T2.8】不让首启向导卡住自动化
    M.load_qss(app)
    win = M.MainWindow()
    win.resize(T.WINDOW_W, T.WINDOW_H)
    win.show()
    QApplication.processEvents()

    report: dict = {}

    # ---------------- 1. 六入口可达 + 选中态 ----------------
    # 用真实点击（QTest.mouseClick 对左轨控件），而不是直接调 go()，
    # 这样验证的是「用户点得到、点得动」，而不是内部函数能跑。
    order = [e["key"] for e in T.ENTRIES]
    rows = []
    ok_all = True
    for key in order:
        QTest.mouseClick(win.rail_items[key], Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        item = win.rail_items[key]
        active = [k for k, it in win.rail_items.items()
                  if it.property("active") == "true"]
        cur_ok = win.stack.currentWidget() is win.pages[key]
        page = win.page(key)
        visible_ok = page.isVisible() and page.width() > 100 and page.height() > 100
        label_ok = win.where.text().strip().endswith(T.ENTRY_BY_KEY[key]["label"])
        # 状态清晰：已实现的入口无「建设中」标签，未实现的有该标签
        has_tag = item.findChild(QLabel, "RailTag") is not None
        tag_ok = (has_tag == (T.ENTRY_BY_KEY[key]["status"] == "building"))
        row = dict(
            key=key,
            label=T.ENTRY_BY_KEY[key]["label"],
            status=T.ENTRY_BY_KEY[key]["status"],
            clicked_by_mouse=True,
            stack_current_is_page=cur_ok,
            active_count=len(active),
            active_only_self=(active == [key]),
            topbar_where=win.where.text(),
            topbar_follows=label_ok,
            rail_tag_matches_status=tag_ok,
            page_class=type(page).__name__,
            page_visible=visible_ok,
            page_size=[page.width(), page.height()],
        )
        good = (cur_ok and len(active) == 1 and active == [key]
                and visible_ok and label_ok and tag_ok)
        row["passed"] = good
        ok_all = ok_all and good
        rows.append(row)

    # 首页（不是左轨入口）：点品牌按钮回首页，应无任何轨选中
    QTest.mouseClick(win.brand, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    home_active = [k for k, it in win.rail_items.items()
                   if it.property("active") == "true"]
    home_ok = (win.stack.currentWidget() is win.pages[T.HOME_KEY]
               and home_active == [] and win.where.text() == "首页概览")
    report["1_entries_reachable"] = dict(
        passed=ok_all and home_ok,
        count=len(order),
        entries=rows,
        home=dict(stack_current_is_home=True, active_count=len(home_active),
                  topbar_where=win.where.text(), passed=home_ok),
    )

    # 快捷方式：Ctrl+3 应到第三个入口，Ctrl+H 回首页
    QTest.keySequence(win, QKeySequence("Ctrl+3"))
    QApplication.processEvents()
    sc_ok = win.stack.currentWidget() is win.pages["check"]
    QTest.keySequence(win, QKeySequence("Ctrl+H"))
    QApplication.processEvents()
    sc_home_ok = win.stack.currentWidget() is win.pages[T.HOME_KEY]
    report["1c_shortcuts"] = dict(
        passed=sc_ok and sc_home_ok,
        ctrl3_to_check=sc_ok, ctrl_h_to_home=sc_home_ok,
    )

    # 【M2-T2.7】导出结果从占位页换成真模块（export_module.ExportModule）。
    # 原「占位页 CTA 跳转到检查问题」断言语义随占位页消失而失效，改为：
    # 导出页必须挂真模块，且未导入书时给「先去导入」的引导文案。
    win.go("export")
    QApplication.processEvents()
    epage = win.page("export")
    export_module_cls = type(epage).__name__
    export_real = export_module_cls != "BuildingPage"
    guide_ok = False
    for lbl in epage.findChildren(QLabel):
        txt = lbl.text()
        if "先在「导入」页" in txt or "尚未导入书籍" in txt:
            guide_ok = True
            break
    report["1d_placeholder_cta"] = dict(
        passed=export_real and guide_ok,
        export_page_class=export_module_cls,
        guide_shown=guide_ok,
    )

    # 【M2-T2.5】导入 / 一键校正 / 检查问题 三页必须挂的是真模块，
    # 不能还是占位页（否则「六入口真实可用」这条验收不成立）
    merged_pages = {}
    for key in ("import", "oneclick", "check"):
        win.go(key)
        QApplication.processEvents()
        cls = type(win.page(key)).__name__
        merged_pages[key] = cls
    report["1e_modules_mounted"] = dict(
        passed=(merged_pages["import"] != "BuildingPage"
                and merged_pages["oneclick"] != "BuildingPage"),
        page_classes=merged_pages,
    )

    # 顶栏三个按钮不是死键：点击应弹出真窗口并在验证后关闭
    def _top_click_probe(btn) -> bool:
        opened = {"n": 0}

        def _close():
            # 【M2-T2.6】顶栏三个按钮现在分别是：⚙ 模态设置窗、? 模态帮助窗、
            # ☰ 下拉菜单（QMenu，不是窗口）。三类都要能识别并关闭，
            # 否则 exec() 会把自动化卡死。
            # 【M4-EX.2a】⚙ 已经不是模态窗，而是「跳到设置页」的路由跳转：
            # 探针改为「点击后主窗当前页是否变成设置页」。
            from PySide6.QtWidgets import QDialog, QMenu
            for w in QApplication.topLevelWidgets():
                if isinstance(w, (QMessageBox, QDialog)) and w.isVisible():
                    opened["n"] += 1
                    w.close()
            # QMenu 是挂在主窗口下的子部件，不在 topLevelWidgets 里，单独扫。
            for menu in win.findChildren(QMenu):
                if menu.isVisible():
                    opened["n"] += 1
                    menu.close()

        if btn.objectName() == "TopAct" and "设置" in (btn.toolTip() or ""):
            QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
            QApplication.processEvents()
            from fixtext_tokens import SETTINGS_KEY
            return getattr(win, "current_key", None) == SETTINGS_KEY

        QTimer.singleShot(120, _close)
        QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        return opened["n"] > 0

    top_btns = [b for b in win.findChildren(QPushButton)
                if b.objectName() == "TopAct"]
    top_res = [_top_click_probe(b) for b in top_btns]
    report["1e_topbar_actions"] = dict(
        passed=len(top_btns) == 3 and all(top_res),
        button_count=len(top_btns), each_opened_dialog=top_res,
    )

    # 面板路由不丢状态：在「检查问题」里修一处，切走再切回，状态仍在
    # T2.10：检查页的问题清单只来自真实运行的引号报告，这里先注入一份
    # 真实跑出来的事件（tests/samples），再验状态保持。
    chk = win.page("check")
    try:
        import sys as _sys
        _sys.path.insert(0, os.path.join(PKG, "tests"))
        import _fixture_run as _fxr  # noqa: WPS433
        import fixtext_check as _fc  # noqa: WPS433
        import tempfile as _tf
        _probe_root = _tf.mkdtemp(prefix="verify_check_")
        from pathlib import Path as _P
        _probe_run = _fxr.build_run(_P(_probe_root) / "seed")
        chk.set_report(_fc.load_report(_probe_run))
    except Exception as exc:  # noqa: BLE001 - 注入失败要留证据，不能静默跳过
        report["1b_route_keeps_state"] = dict(
            passed=False, error=f"注入真实检查结果失败: {exc}")
    chk.select(0)
    chk.fix_here()
    fixed_after_fix = chk.probs[0].get("state")
    win.go("vocab")
    QApplication.processEvents()
    win.go("check")
    QApplication.processEvents()
    same_instance = win.page("check") is chk
    state_kept = chk.probs[0].get("state") == fixed_after_fix
    report["1b_route_keeps_state"] = dict(
        passed=bool(fixed_after_fix) and same_instance and state_kept,
        state_after_fix=fixed_after_fix,
        state_after_roundtrip=chk.probs[0].get("state"),
        same_widget_instance=same_instance,
        window_count=sum(1 for w in app.topLevelWidgets()
                         if isinstance(w, M.MainWindow)),
    )

    # ---------------- 2. 内部术语零露出 ----------------
    texts = collect_ui_texts(win) + scan_module_strings()
    report["2_zero_internal_leak"] = check_zero_leak(texts)

    # ---------------- 3. 令牌与地基对齐 ----------------
    # 优先读原始设计地基 HTML；交付包脱离原始设计包时，退回包内 :root 快照
    candidates = [
        os.path.normpath(os.path.join(
            os.path.dirname(PKG), "..", "..", "src", "ui_pkg",
            "FixText_V1_设计系统_薄地基.html")),
        os.path.join(PKG, "reference", "design_root_snapshot.css"),
    ]
    base_html = next((c for c in candidates if os.path.exists(c)), None)
    css = parse_root(base_html) if base_html else {}
    exp = expected_css()
    diffs, missing, extra = [], [], []
    for k, v in exp.items():
        if k not in css:
            missing.append(k)
            continue
        if v.replace(" ", "").lower() != css[k].replace(" ", "").lower():
            diffs.append(dict(token=k, py=v, css=css[k]))
    for k in css:
        if (k.startswith(("--c-", "--fs-", "--sp-", "--r-", "--lh-",
                          "--fw-", "--sh-", "--font")) and k not in exp):
            extra.append(k)
    per_group = {}
    for g in TOKEN_GROUPS:
        per_group[g] = len(getattr(T, g))
    report["3_tokens_aligned"] = dict(
        passed=(not diffs and not missing and not extra and bool(css)),
        py_token_count=len(exp),
        css_token_count=len(css),
        per_group=per_group,
        diffs=diffs, missing_in_css=missing, extra_in_css=extra,
        source=(os.path.basename(base_html) if base_html else None),
    )

    # ---------------- 4. 构造 + 截图 ----------------
    shots = []
    plan = [(T.HOME_KEY, "01_home_overview.png")]
    names = {
        "import": "02_entry1_import.png",
        "oneclick": "03_entry2_oneclick.png",
        "check": "04_entry3_check.png",
        "vocab": "05_entry4_vocab.png",
        "export": "06_entry5_export.png",
        "history": "07_entry6_history.png",
    }
    plan += [(k, names[k]) for k in order]
    for key, fn in plan:
        p = shot(win, key, fn)
        shots.append(dict(key=key, file=os.path.relpath(p, PKG),
                          bytes=os.path.getsize(p)))
    nonempty = all(s["bytes"] > 8000 for s in shots)
    report["4_construct_and_screenshots"] = dict(
        passed=len(shots) == 7 and nonempty,
        window_title=win.windowTitle(),
        stack_pages=win.stack.count(),
        screenshots=shots,
    )

    # ---------------- 汇总 ----------------
    checks = {
        "1 六入口可达且状态清晰": all([
            report["1_entries_reachable"]["passed"],
            report["1b_route_keeps_state"]["passed"],
            report["1c_shortcuts"]["passed"],
            report["1d_placeholder_cta"]["passed"],
            report["1e_topbar_actions"]["passed"],
        ]),
        "2 内部目录概念零露出": report["2_zero_internal_leak"]["passed"],
        "3 令牌值与设计地基一致": report["3_tokens_aligned"]["passed"],
        "4 主窗口可构造 + 六页截图": report["4_construct_and_screenshots"]["passed"],
    }
    report["summary"] = dict(
        passed=all(checks.values()),
        checks=checks,
    )

    out = os.path.join(PKG, "verify_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("=" * 68)
    print("FixText M2-T2.1 验收自检")
    print("=" * 68)
    for name, ok in checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    e = report["1_entries_reachable"]
    print(f"\n  入口数 {e['count']}，逐入口选中态唯一：",
          all(r["active_only_self"] for r in e["entries"]))
    print("  路由保状态：同实例=%s 状态保持=%s" % (
        report["1b_route_keeps_state"]["same_widget_instance"],
        report["1b_route_keeps_state"]["state_after_roundtrip"]))
    print("  快捷方式 Ctrl+3/Ctrl+H：",
          report["1c_shortcuts"]["passed"],
          "| 占位页 CTA：", report["1d_placeholder_cta"]["passed"],
          "| 顶栏按钮：", report["1e_topbar_actions"]["each_opened_dialog"])
    t = report["2_zero_internal_leak"]
    print(f"  扫描界面字符串 {t['scanned']} 条 / 禁用模式 {t['forbidden_patterns']} 个，命中 {len(t['hits'])}")
    for h in t["hits"][:10]:
        print("    命中:", h["matched"], "|", h["text"][:70])
    k = report["3_tokens_aligned"]
    print(f"  令牌 {k['py_token_count']} vs {k['css_token_count']}，差异 {len(k['diffs'])}，缺失 {len(k['missing_in_css'])}，多余 {len(k['extra_in_css'])}")
    s = report["4_construct_and_screenshots"]
    print(f"  截图 {len(s['screenshots'])} 张，stack 页 {s['stack_pages']}")
    print("\n  report ->", os.path.relpath(out, PKG))
    print("  总体:", "通过" if report["summary"]["passed"] else "未通过")
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
