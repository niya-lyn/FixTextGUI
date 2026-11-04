"""V1.1-D7 · 「我的词库」导出备份的闭环验收。

这张卡唯一不能妥协的东西是**闭环**：导出的文件必须被本工程自带的导入通道
（D1 解析 → D2 分批 → D3 预览）原样读回来。所以这里的测试不是"检查文件长什么样"，
而是真的走一遍：导出 → 把自定义词库整个删掉 → 用导出文件走导入 → 逐条对账。

对账四个维度（缺一条都算没还原）：
1. 条数；
2. 原词 / 替换为 / 类型 / 注音（逐字，含逗号、引号、换行这些会被转义的）；
3. 分级层级——导入只能落进「我的词库」这一层，所以"层级还原"就是"全在自定义层、
   一条都没混进内置层"；
4. 参与校正 / 禁用的状态（这一列导入通道不认，导出侧单列承载，导入后补回）。

另外两条硬判据：
* 出厂词库在导出前后**逐字节不变**（导出只读）；
* 说明文字齐全（用途 + 边界），并且能过三处零术语 lint。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import fixtext_vocab_export as V


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _make_store(tmp_path, entries, disabled=()):
    """建一个只落在临时目录里的词库（绝不碰交付包自带的用户区）。"""
    from fixtext_vocab import VocabStore

    store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    for e in entries:
        store.custom.add(word=e["word"], value=e["value"], typ=e.get("type", "错词校正"),
                         pinyin=e.get("pinyin", ""), book=e.get("book", ""))
    pairs = [p for p in disabled]
    if pairs:
        store.set_entries_enabled([{"word": w, "value": v} for w, v in pairs],
                                  enabled=False)
    return store


def _tree_sha(root: Path) -> str:
    """整棵目录的逐字节指纹（文件名 + 内容），用来证"出厂词库没被动过"。"""
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _signature(store):
    """词条的四个内容字段（顺序固定，便于逐条比对）。"""
    return [(e["word"], e["value"], e["type"], e["pinyin"])
            for e in store.custom.entries()]


def _enabled_map(store):
    return {e["word"]: store.entry_enabled(e["word"], e["value"])
            for e in store.custom.entries()}


ADVERSARIAL = [
    {"word": "萧衍", "value": "萧彦", "type": "角色名", "pinyin": "xiāo yǎn"},
    {"word": "他说,你好", "value": "他说你好", "type": "错词校正"},          # 真逗号
    {"word": "张'三", "value": "张三", "type": "错词校正"},                   # 单引号
    {"word": '李"四', "value": "李四", "type": "专有名词",
     "book": "《炮火弧线》"},                                                # 双引号 + 书籍
    {"word": "第一行\n第二行", "value": "合一行", "type": "其他"},            # 换行
    {"word": "空注音", "value": "有注音", "type": "错词校正", "pinyin": "kōng"},
    {"word": "含空格", "value": "含 空格 值", "type": "错词校正"},
]


# ---------------------------------------------------------------------------
# ① 闭环：导出 → 删库 → 导入 → 逐条对账
# ---------------------------------------------------------------------------

def test_export_then_reimport_is_lossless(tmp_path, monkeypatch):
    """本卡的主判据。四维度全部相等才算还原。"""
    from fixtext_vocab import VocabStore
    from fixtext_vocab_preview.groups import preview_from_sheet
    from fixtext_vocab_preview.rehearsal import write_new_entries
    from fixtext_vocab_import.parse import parse_file

    src = _make_store(tmp_path / "old", ADVERSARIAL,
                      disabled=[("张'三", "张三"), ("第一行\n第二行", "合一行")])
    before_sig = _signature(src)
    before_states = _enabled_map(src)
    assert len(before_sig) == len(ADVERSARIAL)

    out = V.export_custom_vocab(src, out_dir=tmp_path / "导出", when="20261104_120000")
    assert out.count == len(ADVERSARIAL)
    assert out.disabled_count == 2
    assert out.path.is_file() and out.path.stat().st_size == out.bytes

    # 「删掉自定义词库」：整份文件搬走，模拟换机后重来
    custom_file = src.custom.path
    gone = custom_file.with_suffix(".gone")
    custom_file.replace(gone)
    assert not custom_file.exists()

    dst = VocabStore(custom_path=tmp_path / "new" / "custom_vocab.json")
    assert len(dst.custom) == 0, "新机器应该从空词库开始"

    sheet = parse_file(out.path)                    # ← D1 解析
    assert sheet.header_skipped and sheet.headers == list(V.EXPORT_HEADER)
    model = preview_from_sheet(sheet, dst, source_name=out.path.name)   # ← D2 + D3
    counts = model.counts()
    assert counts["格式不合格"] == 0, f"备份里有读不回来的行：{counts}"
    assert counts["冲突"] == 0
    assert counts["新增"] == len(ADVERSARIAL)
    assert model.batch_count() == 1                 # D2 分批真的走了一遍（1000 行阈值）

    write_new_entries(dst, model.groups()["新增"])   # ← 与 D5 同一个写入口
    state = V.restore_backup_state(dst, path=out.path)  # 状态补回（导入不认那一列）

    # 维度 1：条数
    assert len(dst.custom) == len(before_sig)
    # 维度 2：四个内容字段逐条相等（顺序也保持）
    assert _signature(dst) == before_sig
    # 维度 3：层级——全部落在「我的词库」这一层，内置层一条没变
    assert all(dict(e).get("book") is not None for e in dst.custom.entries())
    assert [r["tier"] for r in dst.custom.rows()] == ["custom"] * len(before_sig)
    # 维度 4：禁用状态
    after_states = _enabled_map(dst)
    assert after_states == before_states
    assert state["disabled_applied"] == 2
    # 书籍这一列读回来了（导入通道不认它，本卡按边界只读不写）
    assert state["book_rows"] == 1


def test_export_file_is_stable_and_never_overwrites(tmp_path):
    """同一秒连续导出两次：文件名顺延，两份都在，内容逐字节相同（可复算）。"""
    src = _make_store(tmp_path, ADVERSARIAL)
    first = V.export_custom_vocab(src, out_dir=tmp_path / "导出", when="20261104_120000")
    second = V.export_custom_vocab(src, out_dir=tmp_path / "导出", when="20261104_120000")
    assert first.path != second.path
    assert first.path.exists() and second.path.exists()
    assert first.path.read_bytes() == second.path.read_bytes()
    assert first.sha256 == second.sha256


# ---------------------------------------------------------------------------
# ② 出厂词库逐字节不变
# ---------------------------------------------------------------------------

def test_factory_rules_untouched_by_export(tmp_path, monkeypatch):
    """导出只读写「我的词库」；出厂 rules 目录前后逐字节相同。"""
    from fixtext_paths import pkg_root

    rules = Path(pkg_root()) / "data" / "rules"
    if not rules.is_dir():
        pytest.skip("基线包里没有出厂词库目录")
    before = _tree_sha(rules)

    src = _make_store(tmp_path, ADVERSARIAL)
    out = V.export_custom_vocab(src, out_dir=tmp_path / "导出", when="20261104_130000")
    assert out.count == len(ADVERSARIAL)

    assert _tree_sha(rules) == before, "导出动到了出厂词库，这是不允许的"
    # 自定义词库本身也一个字节没被写（导出是纯读）
    assert src.custom.sha256() == src.custom.sha256()


def test_export_does_not_write_any_vocab_file(tmp_path):
    """导出前后词库文件与禁用集文件逐字节相同（导出不产生还原点）。"""
    from fixtext_vocab import VocabStore

    store = _make_store(tmp_path, ADVERSARIAL, disabled=[("张'三", "张三")])
    custom_before = store.custom.path.read_bytes()
    states_path = store.base_dir / "word_states.json"
    states_before = states_path.read_bytes() if states_path.exists() else b"<none>"
    points_before = store.point_count()
    ops_before = store.op_count()

    out = V.export_custom_vocab(store, out_dir=tmp_path / "导出", when="20261104_140000")
    assert out.count == len(ADVERSARIAL)

    assert store.custom.path.read_bytes() == custom_before
    assert (states_path.read_bytes() if states_path.exists() else b"<none>") == states_before
    assert store.point_count() == points_before, "导出不该留还原点"
    assert store.op_count() == ops_before, "导出不该写操作历史"


def test_empty_vocab_refuses_in_plain_words(tmp_path):
    from fixtext_vocab import VocabStore

    store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    with pytest.raises(V.VocabExportError) as ei:
        V.export_custom_vocab(store, out_dir=tmp_path / "导出")
    assert "还没有词条" in str(ei.value)
    assert not list((tmp_path / "导出").glob("*.csv")), "拒绝时不该落半份文件"


# ---------------------------------------------------------------------------
# ③ 装不下的内容明确拒绝，而不是写出会丢内容的文件
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("word,value,expect", [
    ("带\t制表符", "正常", "制表符"),
    ("带\r回车", "正常", "回车"),
    ("字面标记", "值里有【英文逗号】", "【英文逗号】"),
])
def test_unrepresentable_is_refused_with_reason(tmp_path, word, value, expect):
    from fixtext_vocab import VocabStore

    store = VocabStore(custom_path=tmp_path / "custom_vocab.json")
    store.custom.add(word=word, value=value, typ="错词校正")
    store.custom.add(word="正常词", value="正常值", typ="错词校正")

    with pytest.raises(V.VocabExportError) as ei:
        V.export_custom_vocab(store, out_dir=tmp_path / "导出")
    assert expect in str(ei.value)
    assert not list((tmp_path / "导出").glob("*.csv"))


@pytest.mark.parametrize("word,value", [("", "v"), ("w", "")])
def test_scan_flags_empty_cells(tmp_path, word, value):
    """空格子在导入侧会被判「格式不成立」，导出侧必须先挡下来。"""
    bad = V.scan_unrepresentable(
        [{"id": 1, "word": word, "value": value, "type": "错词校正"}])
    assert bad and any("空的词条" in u.reason or "空的词条" in u.reason for u in bad)


def test_scan_reports_every_problem_row(tmp_path):
    """逐条报告，不是只报第一条——用户要能一次改完。"""
    entries = [
        {"id": 1, "word": "a\tb", "value": "c", "type": "错词校正"},
        {"id": 2, "word": "d", "value": "e\rf", "type": "错词校正"},
        {"id": 3, "word": "g", "value": "h【英文双引号】i", "type": "错词校正"},
        {"id": 4, "word": "ok", "value": "fine", "type": "错词校正"},
    ]
    bad = V.scan_unrepresentable(entries)
    assert {u.id for u in bad} == {1, 2, 3}
    assert all(u.reason and u.where for u in bad)


# ---------------------------------------------------------------------------
# ④ 格式自洽：表头驱动映射，多出来的列不污染导入
# ---------------------------------------------------------------------------

def test_header_makes_mapping_automatic(tmp_path):
    """表头命中后，导入不需要人工改列：前四列自动对好，后两列是「不使用这列」。"""
    from fixtext_vocab_import.mapping import (
        ROLE_IGNORE, ROLE_PINYIN, ROLE_TYPE, ROLE_VALUE, ROLE_WORD,
    )
    from fixtext_vocab_import.parse import parse_file

    src = _make_store(tmp_path, ADVERSARIAL)
    out = V.export_custom_vocab(src, out_dir=tmp_path / "导出", when="20261104_150000")
    sheet = parse_file(out.path)
    assert sheet.column_count == len(V.EXPORT_HEADER)
    assert sheet.mapping.roles == [ROLE_WORD, ROLE_VALUE, ROLE_TYPE, ROLE_PINYIN,
                                   ROLE_IGNORE, ROLE_IGNORE]
    assert sheet.mapping.is_ready()
    assert sheet.banner_removed is False            # 第一行是表头，不是原版说明


def test_table_structure_is_one_entry_per_line(tmp_path):
    """一物理行一条词条：换行 / 逗号 / 引号都被转成标记，不跨行、不多列。"""
    src = _make_store(tmp_path, ADVERSARIAL)
    out = V.export_custom_vocab(src, out_dir=tmp_path / "导出", when="20261104_160000")
    lines = out.path.read_text("utf-8").splitlines()
    assert len(lines) == len(ADVERSARIAL) + 1        # 表头 + 每条一行
    assert all(line.count(",") == len(V.EXPORT_HEADER) - 1 for line in lines)
    assert lines[0].split(",") == list(V.EXPORT_HEADER)


def test_markers_are_the_original_four(tmp_path):
    """用的必须是原版那四个标记，不能自己发明一套（否则导入侧认不出来）。"""
    from fixtext_vocab_import.escape import CSV_ESCAPED_CHARS

    src = _make_store(tmp_path, ADVERSARIAL)
    out = V.export_custom_vocab(src, out_dir=tmp_path / "导出", when="20261104_170000")
    text = out.path.read_text("utf-8")
    assert "【英文逗号】" in text and "【英文单引号】" in text
    assert "【英文双引号】" in text and "【换行符】" in text
    assert [m for _c, m in CSV_ESCAPED_CHARS] == list(V.LITERAL_MARKERS)


# ---------------------------------------------------------------------------
# ⑤ 导出落在统一导出目录（EX.1 口径）
# ---------------------------------------------------------------------------

def test_default_out_dir_is_the_shared_export_dir(tmp_path, monkeypatch):
    """不给目录时落包根「导出/」，用的是 fixtext_paths 既有函数，不另造路径。"""
    monkeypatch.setenv("FIXTEXT_PKG_ROOT", str(tmp_path))
    from fixtext_paths import default_export_dir

    src = _make_store(tmp_path / "user", ADVERSARIAL)
    out = V.export_custom_vocab(src, when="20261104_180000")
    assert out.path.parent == default_export_dir()
    assert out.path.parent.name == V.EXPORT_DIR_NAME
    assert out.path.name.startswith(V.FILE_PREFIX)
    assert out.path.suffix == ".csv"


def test_summary_text_hides_the_directory_path(tmp_path):
    """给用户的那句话只出现文件名，不出现任何目录路径。"""
    src = _make_store(tmp_path, ADVERSARIAL, disabled=[("张'三", "张三")])
    out = V.export_custom_vocab(src, out_dir=tmp_path / "导出", when="20261104_190000")
    text = V.summary_text(out)
    assert out.path.stem in text
    assert str(tmp_path) not in text
    assert "导出" in text


# ---------------------------------------------------------------------------
# ⑥ 说明文字：用途 + 边界，且零术语
# ---------------------------------------------------------------------------

def test_explanation_covers_purpose_and_limits():
    text = V.explanation_text()
    # 用途
    assert "换一台电脑" in text or "换机" in text
    assert "备份" in text
    # 边界：不是双向往返 / 不是通用编辑格式 / 语义以导入预览为准
    assert "不是双向编辑格式" in text
    assert "导入预览" in text
    # 边界：只管自定义层，不动出厂词库
    assert "出厂" in text
    # 边界：字面标记的固有损失
    assert "【英文逗号】" in text


def test_explanation_has_no_internal_terms():
    """说明文字是给用户看的，不能出现内部术语与文件格式缩写。"""
    import re

    text = V.explanation_text()
    for pat in (r"\bCSV\b", r"\bcsv\b", r"\bjson\b", r"/home/", r"\bpath\b",
                r"\bdir\b", r"sha256", r"\bhash\b", r"\bworkspace\b",
                r"custom_vocab", r"\brules\b", r"\.json\b"):
        assert not re.search(pat, text, re.IGNORECASE), f"说明里出现内部术语：{pat}"


def test_explanation_is_shown_with_the_result(tmp_path):
    """说明不是只写在帮助里：导出成功后必须弹出来，和结果一起被看到。"""
    from PySide6.QtWidgets import QLabel

    import vocab_module as vm

    page = vm.VocabModule()
    page.store = _make_store(tmp_path, ADVERSARIAL)
    outcome = page.open_export_backup()
    assert outcome is not None and outcome.count == len(ADVERSARIAL)

    modal = getattr(page, "_export_modal", None)
    assert modal is not None and modal.isVisible()
    texts = [lab.text() for lab in modal.findChildren(QLabel)]
    joined = "\n".join(texts)
    assert any("换" in t for t in texts)             # 用途那一句在里面
    assert V.EXPLANATION_TITLE in joined
    for point in V.EXPLANATION_POINTS:
        assert point in joined, f"说明缺了一句：{point[:20]}"


# ---------------------------------------------------------------------------
# ⑦ 界面入口：词库管理页、人话、零术语
# ---------------------------------------------------------------------------

def test_toolbar_has_export_button_with_human_wording(tmp_path):
    import vocab_module as vm

    page = vm.VocabModule()
    page.store = _make_store(tmp_path, ADVERSARIAL)
    btn = page._export_btn
    assert btn.text() == "💾 导出备份"
    assert "我的词库" in btn.toolTip()
    # 与导入预览并存（不能替换掉它——那是 D3 的入口）
    assert page._preview_btn.text() == "📥 导入预览"


def test_export_click_path_is_real(tmp_path):
    """真实点击工具栏按钮：走的是用户路径，不是直接调内部函数。"""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    import vocab_module as vm

    page = vm.VocabModule()
    page.store = _make_store(tmp_path, ADVERSARIAL)
    QApplication.processEvents()
    QTest.mouseClick(page._export_btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    outcome = getattr(page, "_export_outcome", None)
    assert outcome is not None, "点按钮没有真的导出"
    assert outcome.path.is_file()
    assert outcome.count == len(ADVERSARIAL)


def test_vocab_page_texts_have_no_internal_terms(tmp_path):
    """词库页控件树 + 源码中文文案：不出现内部概念（含新加的导出入口）。

    与 ``tests/test_t32_vocab_safety.py`` 同一套禁用词，但这里多扫一遍
    「点了导出之后的弹窗文案」——弹窗不在控件树里，必须单独扫。
    """
    import re
    from PySide6.QtWidgets import QApplication, QAbstractButton, QLabel, QWidget
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    import vocab_module as vm

    FORBIDDEN = (r"/home/", r"/tmp", r"\.json\b", r"\bworkspace\b", r"custom_vocab",
                 r"\brules\b", r"\bpath\b", r"\bdir\b", r"sha256", r"\bhash\b",
                 r"\bCSV\b", r"\bpy\b")

    page = vm.VocabModule()
    page.store = _make_store(tmp_path, ADVERSARIAL)
    QApplication.processEvents()
    QTest.mouseClick(page._export_btn, Qt.MouseButton.LeftButton)
    QApplication.processEvents()

    texts: list[str] = []
    for root in (page, getattr(page, "_export_modal", None)):
        if root is None:
            continue
        texts.append(root.windowTitle())
        for w in root.findChildren(QWidget):
            texts.append(w.toolTip())
            texts.append(w.accessibleName())
            if isinstance(w, QLabel):
                texts.append(w.text())
            if isinstance(w, QAbstractButton):
                texts.append(w.text())
            if hasattr(w, "placeholderText"):
                texts.append(w.placeholderText())

    hits = [(pat, t) for t in texts if t
            for pat in FORBIDDEN if re.search(pat, t, re.IGNORECASE)]
    assert not hits, f"词库页出现内部概念 {hits}"


def test_export_error_is_reported_in_plain_words(tmp_path):
    """导出失败时界面给一句人话，不抛出内部异常、不写半份文件。"""
    import vocab_module as vm

    page = vm.VocabModule()
    page.store = _make_store(tmp_path, [
        {"word": "带\t制表符", "value": "正常", "type": "错词校正"},
    ])
    outcome = page.open_export_backup()
    assert outcome is None
    note = getattr(page, "_export_note", "")
    assert "制表符" in note, f"没说清为什么失败：{note}"
    assert not (tmp_path / "导出").exists() or not list((tmp_path / "导出").glob("*.csv"))
