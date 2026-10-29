"""M4-EX.3a 验收：两本书实测 + 单书动线回归 + 顶栏当前书跳转。

全部跑真实界面路径（导入 → 书架 → 设为当前 → 顶栏 → 重启恢复 → 点击跳书架），
不做"调内部函数"式的假验证：

1. 用**真实导入链路**（fixtext_import.importer）把两本书导进工作区 —— 不是手写
   import.json 造数据，书架看到的就是用户导入的那两本。
2. 「重启」用**独立子进程**重新构建 MainWindow（同进程重建挡不住内存态残留）。
3. 「点击顶栏」用 QTest.mouseClick 真点控件，而不是调 go()。

用法：python3.12 tools/accept_ex3a.py [--pkg <包根>] [--out <输出目录>]
退出码 0 = 全部通过。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
DEFAULT_PKG = HERE.parent

CHECKS: list[tuple[str, str, bool, str]] = []


def record(key: str, label: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((key, label, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {key} {label}" + (f" —— {detail}" if detail else ""))


def _make_books(src_root: Path, out: Path) -> tuple[Path, Path]:
    """造两个可直接导入的真实书源（一个 TXT、一个两章 EPUB）。"""
    txt = out / "北岭旧事.txt"
    txt.write_text("第一章 起风\n\n那年冬天的雪下得很大。\n" * 40, encoding="utf-8")

    import zipfile
    epub = out / "南川杂记.epub"
    with zipfile.ZipFile(epub, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0" encoding="utf-8"?>'
                   '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
                   'unique-identifier="bid"><metadata '
                   'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   '<dc:title>南川杂记</dc:title><dc:creator>某人</dc:creator>'
                   '<dc:identifier id="bid">urn:uuid:ex3a</dc:identifier>'
                   '<dc:language>zh-CN</dc:language></metadata><manifest>'
                   '<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/>'
                   '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
                   '</manifest><spine toc="ncx">'
                   '<itemref idref="c1"/><itemref idref="c2"/></spine></package>')
        z.writestr("OEBPS/toc.ncx",
                   '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" '
                   'version="2005-1"><navMap>'
                   '<navPoint id="n1" playOrder="1"><navLabel><text>第一章 山雨</text>'
                   '</navLabel><content src="c1.xhtml"/></navPoint>'
                   '<navPoint id="n2" playOrder="2"><navLabel><text>第二章 归途</text>'
                   '</navLabel><content src="c2.xhtml"/></navPoint></navMap></ncx>')
        for i, name in enumerate(("第一章 山雨", "第二章 归途"), start=1):
            z.writestr(f"OEBPS/c{i}.xhtml",
                       '<?xml version="1.0" encoding="utf-8"?>'
                       '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                       f'<title>{name}</title></head><body><h1>{name}</h1>'
                       '<p>' + "山道上的雾一直没散。" * 30 + '</p></body></html>')
    return txt, epub


def _child_probe(pkg: Path, ws: Path) -> dict:
    """独立子进程：只构建 MainWindow，报顶栏书名与当前书记录（= 重启）。"""
    code = r"""
import json, os, sys
sys.path[:0] = [os.environ["FX_Q"], str(os.environ["FX_PKG"]),
                os.path.join(os.environ["FX_PKG"], "fixtext_ui")]
from PySide6.QtWidgets import QApplication
import fixtext_settings
app = QApplication([])
_qs = fixtext_settings.AppSettings()
_qs.setValue("wizardSeen", "1")
_qs.sync()
import main_window as mw
w = mw.MainWindow(workspace=os.environ["FX_WS"])
print("@@RESULT@@" + json.dumps({
    "chip": w.book_chip.name.full_text(),
    "chip_tip": w.book_chip.toolTip(),
    "empty": w.book_chip.property("empty"),
    "record_title": (w._import_record or {}).get("title", ""),
    "key": w.current_key,
}, ensure_ascii=False))
"""
    from accept_env import qt_site_packages  # noqa: PLC0415
    qsite = qt_site_packages()
    env = dict(os.environ)
    env.update({
        "FX_PKG": str(pkg), "FX_WS": str(ws), "QT_QPA_PLATFORM": "offscreen",
        "FX_Q": qsite,
    })
    proc = subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True, timeout=180)
    for line in proc.stdout.splitlines():
        if line.startswith("@@RESULT@@"):
            return json.loads(line[len("@@RESULT@@"):])
    raise RuntimeError(f"子进程没报结果：\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr[-2000:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg", default=str(DEFAULT_PKG))
    ap.add_argument("--out", default=str(HERE.parent / "evidence" / "ex3a"))
    args = ap.parse_args()
    pkg = Path(args.pkg).resolve()
    out = Path(args.out).resolve()
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    from accept_env import qt_site_packages  # noqa: PLC0415
    _path_front = [str(pkg), str(pkg / "fixtext_ui")]
    _q = qt_site_packages()
    if _q:
        _path_front.append(_q)
    sys.path[:0] = _path_front

    tmp = Path(tempfile.mkdtemp(prefix="ex3a_"))
    ws = tmp / "workspace"
    ws.mkdir()
    src_dir = tmp / "src"
    src_dir.mkdir()
    # 设置文件隔离：本脚本自己的当前书记录，不污染包内配置
    os.environ["FIXTEXT_SETTINGS_FILE"] = str(tmp / "settings.ini")

    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    import fixtext_settings
    app = QApplication.instance() or QApplication([])
    # 首启向导 exec() 会阻塞（M2-T2.5 已知坑），且 M4-T4.4 后向导标记
    # 存在用户区设置文件里：预置「已看过」，等价于真实用户首启之后的常驻状态。
    _qs = fixtext_settings.AppSettings()
    _qs.setValue("wizardSeen", "1")
    _qs.sync()

    import main_window as mw
    import fixtext_shelf as S
    from fixtext_import.importer import import_book, ImportOptions

    txt_src, epub_src = _make_books(src_dir, src_dir)

    # ---------------------------------------------------------------- S1 导入两本
    r1 = import_book(txt_src, ws, ImportOptions())
    r2 = import_book(epub_src, ws, ImportOptions(epub_mode="direct"))
    books = S.list_books(ws)
    record("S1a", "导入两本书后工作区确有 2 本", len(books) == 2,
           f"book_ids={[b.book_id for b in books]}")
    record("S1b", "两本书名都来自真实导入记录",
           {b.title for b in books} == {txt_src.stem, "南川杂记"},
           f"titles={[b.title for b in books]}")

    # ---------------------------------------------------------------- S2 书架
    win = mw.MainWindow(workspace=ws)
    win.show()
    win.go("import")
    app.processEvents()
    panel = win.import_module.shelf
    rows = panel.rows
    record("S2a", "导入页书架列出两本", len(rows) == 2, f"rows={len(rows)}")
    fields = [(r.name.full_text(), r.meta.text()) for r in rows]
    record("S2b", "每行都有书名/格式/大小/导入时间",
           all("《" in n and "》" in n and " · " in m and "月" in m for n, m in fields),
           f"{fields}")
    record("S2c", "当前标记只有一处（最近导入的那本）",
           len([r for r in rows if r.property("current") == "true"]) == 1,
           f"current={[r.book.book_id for r in rows if r.property('current') == 'true']}")
    record("S2d", "「已导出」没有出现（本卡无写入方，不放假状态）",
           all(r.status.text() == "" for r in rows),
           f"status={[r.status.text() for r in rows]}")
    record("S2e", "工作区卡展开 + 空状态收起",
           win.import_module.workspace_card.isVisibleTo(win.import_module)
           and not win.import_module.empty_state.isVisibleTo(win.import_module))

    # ---------------------------------------------------------------- S3 设 B 为当前
    b_book = [b for b in books if b.title == "南川杂记"][0]
    a_book = [b for b in books if b.title != "南川杂记"][0]
    # 先确认起点是 A（TXT 后导入 → 最近），把 B 设为当前
    target = [r for r in panel.rows if r.book.book_id == b_book.book_id][0]
    if target.action_btn is None:
        # 起点已是 B：先切到 A 再切回 B，保证"S3 是用户主动切换"这个动作真实发生
        other = [r for r in panel.rows if r.book.book_id == a_book.book_id][0]
        other.action_btn.click()
        app.processEvents()
        target = [r for r in panel.rows if r.book.book_id == b_book.book_id][0]
    before_texts = [r.name.full_text() for r in panel.rows]
    target.action_btn.click()
    app.processEvents()
    record("S3a", "点「设为当前」后书架当前标记移到 B",
           panel.current_id() == b_book.book_id,
           f"current_id={panel.current_id()} 期望={b_book.book_id}")
    record("S3b", "切换后各书名文字零位移",
           [r.name.full_text() for r in panel.rows] == before_texts)
    record("S3c", "选择已落设置文件",
           S.stored_current_id() == b_book.book_id,
           f"stored={S.stored_current_id()}")
    record("S3d", "「当前」是标识、非当前行是「设为当前」主操作按钮",
           any(r.badge is not None and r.badge.text() == "当前" for r in panel.rows)
           and any(r.action_btn is not None and r.action_btn.text() == "设为当前"
                   for r in panel.rows))

    # ---------------------------------------------------------------- S4 顶栏
    record("S4a", "顶栏书名变成 B", win.book_chip.name.full_text() == "南川杂记",
           f"chip={win.book_chip.name.full_text()!r}")
    record("S4b", "顶栏仍是常驻显示（未因切页隐藏）",
           win.book_chip.isVisibleTo(win))
    long_tip = win.book_chip.toolTip()
    record("S4c", "顶栏 tooltip 给完整书名", long_tip.startswith("南川杂记"),
           f"tooltip={long_tip!r}")

    # ---------------------------------------------------------------- S5 点顶栏跳书架
    # 先离开导入页（去一键校正页），验证点击顶栏真的会切回来
    win.go("oneclick")
    cur_before = win.current_key
    QTest.mouseClick(win.book_chip, Qt.MouseButton.LeftButton)
    app.processEvents()
    record("S5a", "点击顶栏走既有 go() 路由到导入页",
           win.current_key == "import" and cur_before != "import",
           f"{cur_before} → {win.current_key}")
    active = [r for r in win.import_module.shelf.rows if r.property("current") == "true"]
    record("S5b", "跳到书架后 B 行高亮",
           len(active) == 1 and active[0].book.book_id == b_book.book_id,
           f"active={[r.book.book_id for r in active]}")

    # 截图：导入页书架（B 为当前）
    win.resize(1280, 860)
    app.processEvents()
    shot = out / "01_shelf_two_books.png"
    win.grab().save(str(shot))
    record("S5c", "导入页书架截图已落盘", shot.exists() and shot.stat().st_size > 8000,
           f"{shot.name} {shot.stat().st_size if shot.exists() else 0}B")

    # ---------------------------------------------------------------- S6 重启仍为 B
    probe = _child_probe(pkg, ws)
    record("S6a", "重启（独立子进程）后顶栏仍是 B",
           probe.get("chip") == "南川杂记", f"chip={probe.get('chip')!r}")
    record("S6b", "重启后当前书记录仍是 B",
           probe.get("record_title") == "南川杂记",
           f"record_title={probe.get('record_title')!r}")

    # ---------------------------------------------------------------- S7 单书动线
    ws1 = tmp / "workspace_single"
    ws1.mkdir()
    win1 = mw.MainWindow(workspace=ws1)
    win1.show()
    # 单书：导入一本 → 自动成为当前（不用用户再选一次）
    import_book(txt_src, ws1, ImportOptions())
    win1._on_book_ready(str(ws1 / S.list_books(ws1)[0].book_id / "book.txt"))
    app.processEvents()
    single = S.list_books(ws1)
    record("S7a", "只导入一本时自动设为当前（单书动线不退化）",
           len(single) == 1 and S.stored_current_id() == single[0].book_id
           and win1.book_chip.name.full_text() == single[0].title,
           f"chip={win1.book_chip.name.full_text()!r} stored={S.stored_current_id()!r}")
    steps = getattr(win1.oneclick_module, "current_step", None)
    record("S7b", "一键校正页已拿到这本书的运行上下文（导入完可直接往下走）",
           win1.oneclick_module.run_context is not None,
           f"run_context={'有' if win1.oneclick_module.run_context else '无'}")

    # ---------------------------------------------------------------- S8 无书占位
    ws0 = tmp / "workspace_empty"
    ws0.mkdir()
    win0 = mw.MainWindow(workspace=ws0)
    win0.show()
    record("S8a", "无书时顶栏中性占位 + 导入页空状态",
           win0.book_chip.property("empty") == "true"
           and win0.book_chip.name.text() == "未选择书"
           and win0.import_module.empty_state.isVisibleTo(win0.import_module),
           f"chip={win0.book_chip.name.text()!r}")
    QTest.mouseClick(win0.book_chip, Qt.MouseButton.LeftButton)
    app.processEvents()
    record("S8b", "无书时点顶栏同样跳书架", win0.current_key == "import",
           f"key={win0.current_key}")

    # ---------------------------------------------------------------- 汇总
    (out / "accept_ex3a.log").write_text(
        "\n".join(f"{k}\t{'PASS' if ok else 'FAIL'}\t{label}\t{detail}"
                  for k, label, ok, detail in CHECKS), encoding="utf-8")
    failed = [c for c in CHECKS if not c[2]]
    print(f"\n共 {len(CHECKS)} 项，失败 {len(failed)} 项")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)
