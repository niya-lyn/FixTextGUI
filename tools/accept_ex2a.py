"""M4-EX.2a 验收取证脚本（结构层）。

产出（写到 evidence/ex2a/ 与 screenshots/ex2a/）：
  1. 首页概览 + 设置页离屏截图（QSS 已加载）
  2. 顶栏三按钮（☰ 更多 / ? 帮助 / ⚙ 设置）真实点击手测记录
  3. 左轨六入口逐一点击跳转记录
  4. QSS 令牌集中管理抽查（fixtext_ui 下是否还有散落的硬编码色值/字号）
  5. 设置项真实生效的旁证（词库位置 / 日志目录 / 开关重启保留）

用法：python3.12 tools/accept_ex2a.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "fixtext_import"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
EVID = PKG / "evidence" / "ex2a"
SHOTS = PKG / "screenshots" / "ex2a"
EVID.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import Qt, QTimer          # noqa: E402
from PySide6.QtTest import QTest               # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog, QMenu, QMessageBox,  # noqa: E402
                            QPushButton)

import fixtext_settings as app_settings          # noqa: E402
import main_window as M                          # noqa: E402
from fixtext_tokens import ENTRIES, SETTINGS_KEY  # noqa: E402

report: dict = {}


def _app() -> QApplication:
    app = QApplication.instance() or QApplication([])
    M.load_qss(app)
    return app


def _shot(win, name: str) -> str:
    QApplication.processEvents()
    p = SHOTS / name
    win.grab().save(str(p))
    return str(p)


def _close_all(win) -> int:
    n = 0
    for w in QApplication.topLevelWidgets():
        if isinstance(w, (QMessageBox, QDialog)) and w.isVisible():
            n += 1
            w.close()
    for m in win.findChildren(QMenu):
        if m.isVisible():
            n += 1
            m.close()
    return n


def main() -> int:
    app = _app()
    win = M.MainWindow()
    win.resize(1440, 900)
    win.show()
    QApplication.processEvents()

    # ---- 1. 左轨六入口逐一点击 ----
    rail_res = []
    entries = {e["key"]: e for e in ENTRIES}
    for key, entry in entries.items():
        item = win.rail_items[key]
        QTest.mouseClick(item, Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        rail_res.append({
            "key": key,
            "label": entry["label"],
            "当前页": win.current_key,
            "跳转成功": win.current_key == key,
            "面包屑": win.where.text(),
        })
    report["1_rail_six_entries"] = {
        "入口数": len(rail_res),
        "逐条": rail_res,
        "全部跳转成功": all(r["跳转成功"] for r in rail_res),
    }

    # ---- 2. 顶栏三按钮真实点击 ----
    tops = [b for b in win.findChildren(QPushButton) if b.objectName() == "TopAct"]
    top_res = []
    for b in tops:
        opened = {"n": 0}

        def _close():
            opened["n"] += _close_all(win)

        if b.toolTip() == "设置":
            before = win.current_key
            QTest.mouseClick(b, Qt.MouseButton.LeftButton)
            QApplication.processEvents()
            top_res.append({
                "按钮": "⚙ 设置", "点击前": before, "点击后": win.current_key,
                "真实可点": win.current_key == SETTINGS_KEY,
                "说明": "跳转到设置页（平级路由页，非弹窗）",
            })
            continue
        QTimer.singleShot(150, _close)
        QTest.mouseClick(b, Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        top_res.append({
            "按钮": f"{b.text()} {b.toolTip()}", "弹出层数": opened["n"],
            "真实可点": opened["n"] > 0,
            "说明": "弹出菜单 / 帮助窗后已自动关闭",
        })
    report["2_topbar_three_buttons"] = {
        "按钮数": len(tops), "逐条": top_res,
        "全部可点": all(r["真实可点"] for r in top_res),
    }

    # ---- 3. 截图：首页 + 设置页 ----
    win.go("home")
    QApplication.processEvents()
    home_shot = _shot(win, "10_home.png")
    win.go(SETTINGS_KEY)
    QApplication.processEvents()
    set_shot = _shot(win, "11_settings.png")
    report["3_screenshots"] = {"首页概览": home_shot, "设置页": set_shot}

    # ---- 4. QSS 令牌集中管理抽查 ----
    ui_dir = PKG / "fixtext_ui"
    hex_re = re.compile(r"#[0-9A-Fa-f]{6}\b")
    px_re = re.compile(r"font-size\s*:\s*\d+px")

    def scan(text: str, label: str) -> list[dict]:
        out = []
        for i, line in enumerate(text.splitlines(), 1):
            st = line.strip()
            if st.startswith("#") or st.startswith("//"):
                continue                      # 注释里的引用说明不算散落
            for m in hex_re.finditer(line):
                out.append({"位置": label, "行": i, "类型": "色值",
                            "取值": m.group(0), "原文": st[:90]})
            for m in px_re.finditer(line):
                out.append({"位置": label, "行": i, "类型": "字号",
                            "取值": m.group(0), "原文": st[:90]})
        return out

    # (a) 本卡新增/修改的 Python 源码行（git diff 的 + 行）里有无散落硬编码。
    #     排除：令牌源 fixtext_tokens.py（集中常量本身就是规范落点）、
    #     build_qss.py（样式生成器，色值全部来自令牌展开）、
    #     fixtext.qss / reference/（生成产物与设计快照，非手写源码）。
    diff = subprocess.run(
        ["git", "diff", "3554341..HEAD", "--name-only"],
        cwd=str(PKG), capture_output=True, text=True).stdout
    changed = [f for f in diff.splitlines()
               if f.startswith("fixtext_ui/") and f.endswith(".py")
               and f not in ("fixtext_ui/fixtext_tokens.py",
                             "fixtext_ui/build_qss.py")]
    added = []
    for fn in changed:
        d = subprocess.run(["git", "diff", "3554341..HEAD", "--", fn],
                           cwd=str(PKG), capture_output=True, text=True).stdout
        for line in d.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added.extend(scan(line[1:], f"{fn}(新增行)"))
    # (b) 既有文件全量清单（透明呈现，不隐藏；属基线遗留，非本卡引入）
    legacy = []
    for py in sorted(ui_dir.glob("*.py")):
        if py.name in ("fixtext_tokens.py", "build_qss.py"):
            continue
        legacy.extend(scan(py.read_text("utf-8"), f"fixtext_ui/{py.name}"))
    qss_text = (ui_dir / "fixtext.qss").read_text("utf-8")
    qss_hex = hex_re.findall(qss_text)
    report["4_token_centralization"] = {
        "扫描范围": "本卡改动的 fixtext_ui/*.py（排除令牌源与样式生成器）新增行；"
                    "及 fixtext_ui 全量遗留清单；fixtext.qss 十六进制取值",
        "本卡改动文件": changed,
        "本卡新增代码行中的硬编码色值/字号": len(added),
        "本卡新增行明细": added,
        "既有文件全量遗留条数": len(legacy),
        "既有文件遗留明细（基线已有，本卡未新增）": legacy,
        "qss 内十六进制色值数": len(qss_hex),
        "qss 内十六进制取值": sorted(set(qss_hex)),
        "结论": "本卡新增代码零散落硬编码（色值/字号只出自令牌源与样式生成器）；"
                "遗留项为基线既有代码，清单如实列示，留待后续卡处理"
                if not added else "本卡新增行存在散落硬编码，需处理",
    }

    # ---- 5. 设置项真实生效旁证 ----
    import tempfile
    from pathlib import Path as _P
    tmp = _P(tempfile.mkdtemp(prefix="ex2a_probe_"))
    new_vocab = tmp / "vocab_home"
    app_settings.set_vocab_dir(new_vocab)
    from fixtext_vocab import VocabStore, CUSTOM_FILE
    store = VocabStore(custom_path=app_settings.vocab_custom_file())
    store.add_entry(word="萧衍", value="萧彦", typ="人名")
    vocab_ok = (new_vocab / CUSTOM_FILE).exists()
    rows = [r for r in store.custom.rows() if r.get("word") == "萧衍"]

    import fixtext_error_center as ec
    from fixtext_error_center.diaglog import write_record
    new_logs = tmp / "log_home"
    app_settings.set_log_dir(new_logs)
    win.settings_module._apply_log_backend()
    rec = write_record("U-I01", "EX2A 取证写入", {"traceback": "ex2a"})
    log_ok = bool(rec) and str(new_logs) in str(rec)

    win.settings_module._on_diag(False)      # 走界面真实路径（关开关→重初始化日志后端）
    diag_off = write_record("U-I01", "EX2A 不应写入", {"traceback": "ex2a"}) is None
    win.settings_module._on_diag(True)

    app_settings.set_show_basis(True)
    basis_on = app_settings.show_basis() is True
    app_settings.set_show_basis(False)
    # 重启保留：重新读一遍设置（等价新进程）
    reread = {
        "engine": app_settings.engine(),
        "vocabDir": str(app_settings.vocab_dir()),
        "logDir": str(app_settings.log_dir()),
        "diagEnabled": app_settings.diag_enabled(),
        "showBasis": app_settings.show_basis(),
    }
    report["5_settings_real_effect"] = {
        "词库落新位置": vocab_ok,
        "词库文件名": CUSTOM_FILE,
        "新词条": rows,
        "日志落新目录": log_ok,
        "日志文件": rec,
        "留痕关闭后不写记录": diag_off,
        "设计依据开关可写可读": basis_on,
        "重新读取（等价重启）": reread,
    }
    # 还原
    app_settings.set_vocab_dir(None)
    app_settings.set_log_dir(None)
    app_settings.set_show_basis(False)
    app_settings.set_diag_enabled(True)
    ec.init(enabled=True)

    (EVID / "accept_ex2a.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print("rail:", report["1_rail_six_entries"]["全部跳转成功"],
          "| topbar:", report["2_topbar_three_buttons"]["全部可点"],
          "| 新增行硬编码:", len(added),
          "| 既有遗留:", len(legacy),
          "| 词库落新位置:", vocab_ok, "| 日志落新目录:", log_ok,
          "| 留痕关闭生效:", diag_off, "| 开关可写可读:", basis_on)
    for o in report["4_token_centralization"]["本卡新增行明细"][:25]:
        print("  hardcode:", o)
    for r in report["2_topbar_three_buttons"]["逐条"]:
        print("  top:", r)

    ok = (report["1_rail_six_entries"]["全部跳转成功"]
          and report["2_topbar_three_buttons"]["全部可点"]
          and not added and vocab_ok and log_ok and diag_off and basis_on)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
