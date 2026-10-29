"""验收③ 概念暴露 lint：界面与文案里不得出现内部技术词。

这条测试是验收③的机器可判定形式：把所有给用户看的字符串（`messages` 全部
返回值 + 界面控件文本）扫一遍，出现任一技术词即失败。

注意：**源码注释与 docstring 允许出现**（工程师需要，用户看不到），
所以这里只扫"会被渲染成界面文字"的内容。
"""

from __future__ import annotations

import inspect
import re

import pytest

from fixtext_import import messages as M

#: 用户界面绝不允许出现的词（大小写不敏感）
FORBIDDEN = [
    "spine",
    "opf",
    "container.xml",
    "manifest",
    "ncx",
    "xhtml",
    "xml",
    "bom",
    "utf-8",
    "utf8",
    "gbk",
    "gb18030",
    "big5",
    "crlf",
    "sha256",
    "hash",
    "encoding",
    "charset",
    "codec",
    "zip",
]

#: 少数例外：`messages` 里明确说明"导出成同样的电子书"用 EPUB 是产品名，
#: 用户在导入页已经知道这个词（拖放区就写着支持 EPUB）。其余一律不许。
ALLOWED_WORDS = {"epub", "txt"}


def _human_strings() -> list[tuple[str, str]]:
    """把 messages 里所有不带必需参数的函数调一遍，收集返回的文案。"""
    out: list[tuple[str, str]] = []
    for name, fn in vars(M).items():
        if not inspect.isfunction(fn) or name.startswith("_"):
            continue
        params = inspect.signature(fn).parameters
        if any(p.default is p.empty for p in params.values()):
            continue                     # 需要外部数据的函数单独测
        value = fn()
        if isinstance(value, str):
            out.append((name, value))
        elif isinstance(value, tuple):
            out.extend((name, v) for v in value if isinstance(v, str))
    return out


@pytest.mark.parametrize("name,text", _human_strings(), ids=lambda v: v if isinstance(v, str) else "")
def test_messages_have_no_tech_terms(name, text):
    low = text.lower()
    hits = [w for w in FORBIDDEN if w in low and w not in ALLOWED_WORDS]
    assert not hits, f"messages.{name}() 出现技术词 {hits}：{text}"


def test_dynamic_messages_have_no_tech_terms():
    """带参数的文案（编码说明、错误等）也要过 lint。"""
    cases = [
        M.encoding_note("utf-8", True),
        M.encoding_note("gbk", True),
        M.encoding_note("gbk", False),
        M.encoding_note("gb18030", True),
        M.encoding_note("big5", False),
        M.newline_note(True),
        M.newline_note(False),
        M.epub_merged_note(788),
        M.big_file_note(35.0),
        M.epub_broken("坏包"),
        M.unsupported_type(),
        M.empty_file(),
        M.not_a_book(),
        M.too_many_files(3),
    ]
    for text in cases:
        low = text.lower()
        hits = [w for w in FORBIDDEN if w in low and w not in ALLOWED_WORDS]
        assert not hits, f"文案出现技术词 {hits}：{text}"


def test_encoding_label_is_human():
    """编码的对外说法必须是"人话标签"，不能是字符集名。"""
    for codec in ("utf-8", "gbk", "gb18030", "big5", "utf-16"):
        label = M.encoding_label(codec)
        assert label and label not in ("utf-8", "gbk", "gb18030", "big5")
        assert not re.search(r"[a-zA-Z]{2,}[\-\d]", label)


def test_ui_widget_texts_have_no_tech_terms(qt_app, tmp_path):
    """真实构建界面并把所有控件文本扫一遍（含标签、按钮、提示）——验收③的界面侧证据。"""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QLabel, QPushButton, QRadioButton, QWidget

    from import_module import ImportModule

    module = ImportModule(tmp_path / "ws")

    # M5-EX.3：无导入向导；扫拖放区 + 进度/结果卡 + 安全说明即可
    texts: list[str] = []
    for w in module.findChildren(QWidget):
        for attr in ("text", "placeholderText", "toolTip"):
            if hasattr(w, attr):
                value = getattr(w, attr)
                if isinstance(value, str) and value:
                    texts.append(value)
        if isinstance(w, (QLabel, QPushButton, QRadioButton)) and w.windowTitle():
            texts.append(w.windowTitle())

    bad: list[tuple[str, list[str]]] = []
    for t in texts:
        low = t.lower()
        hits = [w for w in FORBIDDEN if w in low and w not in ALLOWED_WORDS]
        if hits:
            bad.append((t, hits))

    module.shutdown()
    assert not bad, f"界面文本出现技术词：{bad}"
