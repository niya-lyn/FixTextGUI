"""M2-T2.9 P1-2 复核：7 个页面 + 首启向导的界面文案零技术名词扫描。

沿用的就是 T2.8 基线词表 `verify_m2t21.FORBIDDEN`（25 条正则，
`accept_t28.scan_wizard_leak` 用的同一份），扫描范围扩到左轨六入口
（导入 / 一键校正 / 检查问题 / 词库 / 导出 / 历史）+ 首页 + 向导三步。
控件树与源码文案字面量都扫（弹窗文案不在控件树里）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PKG / "pipeline"))
sys.path.insert(0, str(PKG / "pipeline" / "vendor"))

#: 界面文案里的字符串属性名（控件树里能读到的所有人类可读文本）
TEXT_ATTRS = ("text", "toolTip", "accessibleName",
              "accessibleDescription", "placeholderText", "windowTitle")


def _texts(widget) -> list[str]:
    from PySide6.QtWidgets import QWidget
    out: list[str] = []
    for w in [widget, *widget.findChildren(QWidget)]:
        for attr in TEXT_ATTRS:
            getter = getattr(w, attr, None)
            if callable(getter):
                try:
                    v = getter()
                except TypeError:            # 有些控件的同名方法带参数
                    continue
                if isinstance(v, str) and v.strip():
                    out.append(v)
    return out


def _source_literals() -> list[tuple[str, str]]:
    """源码里**用户可见**的中文字符串字面量。

    用 AST 只取真正的字符串常量，并剔除 docstring —— 源码注释与文档字符串
    允许出现技术词（工程师要看，用户看不到），词表只约束会被渲染成界面的文字。
    按行做正则会把 `build_qss.py` 这类文档字符串里的文件名也算成命中（假阳性）。
    """
    import ast
    import glob
    out: list[tuple[str, str]] = []
    # build_qss.py 的字符串是**样式表注释**（写进 qss 的 /* */ 里，不渲染成界面
    # 文字），按源码字面量扫会假阳性；它生成的 qss 由令牌校验把关。
    SKIP = {"build_qss.py"}
    for f in sorted(glob.glob(str(PKG / "fixtext_ui" / "*.py"))):
        if Path(f).name in SKIP:
            continue
        try:
            tree = ast.parse(Path(f).read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        docs: set[int] = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body:
                first = body[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docs.add(id(first.value))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docs
                    and re.search(r"[\u4e00-\u9fff]", node.value)):
                out.append((f"{Path(f).name}:{node.lineno}", node.value))
    return out


def main() -> int:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import verify_m2t21 as V
    from fixtext_tokens import ENTRIES, HOME_KEY
    import main_window as MW
    import first_run_wizard as W

    hits: list[dict] = []
    scanned = 0

    def scan(where: str, texts: list[str]) -> None:
        nonlocal scanned
        for t in texts:
            scanned += 1
            for pat in V.FORBIDDEN:
                m = re.search(pat, t)
                if m:
                    hits.append(dict(where=where, pattern=pat,
                                     matched=m.group(0), text=t[:120]))

    win = MW.MainWindow()
    win.show()
    scan(f"page:{HOME_KEY}", _texts(win))
    for key in [e["key"] for e in ENTRIES]:
        win.go(key)
        app.processEvents()
        scan(f"page:{key}", _texts(win.page(key) if hasattr(win, "page") else win))

    wiz = W.FirstRunWizard()
    for step in range(3):
        wiz.go_step(step)
        app.processEvents()
        scan(f"wizard:{step}", _texts(wiz))
    wiz.close()
    win.close()

    for where, lit in _source_literals():
        scan(f"src:{where}", [lit])

    rep = dict(passed=not hits, scanned=scanned,
               forbidden_patterns=len(V.FORBIDDEN),
               pages=[HOME_KEY] + [e["key"] for e in ENTRIES],
               hits=hits)
    out = PKG / "evidence" / "t29_scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"扫描 {scanned} 条文案 / 词表 {len(V.FORBIDDEN)} 项 / 页面 "
          f"{len(rep['pages'])} 个 → 命中 {len(hits)}")
    for h in hits[:10]:
        print("  ", h)
    print("P1-2 零露出:", "PASS" if not hits else "FAIL")
    return 0 if not hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
