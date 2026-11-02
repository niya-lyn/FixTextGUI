"""M3-T3.3 界面侧：专有词预览清单 + 检查页联动（§2.4.2 第 2/3/4 条）。

数据层（条数守恒、去重、冲突记账）在 ``test_t31_book_words.py`` 里锁着；
这里只锁界面这一层，且都验**真实控件**而不是内部函数：

1. 预览清单四列（词条 / 类型 / 替换值 / 出现次数）+ 整组全选
2. 清单条数 == 传入条数（不截断），勾选计数实时更新
3. 空状态：没人话表格，只给人话提示
4. 冲突结果必须明文摆到界面（不许静默跳过）
5. 检查页「＋词库」按钮存在、可点，且单标点会被拦截不写
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

IK = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(IK / "fixtext_ui"), str(IK), str(IK / "pipeline")]


def _words(n: int) -> list[dict]:
    return [dict(word=f"书中词{i}", value=f"正写{i}", type="专有名词",
                 count=i + 1, note="本书专有词") for i in range(n)]


def _store(tmp: Path):
    from fixtext_vocab import VocabStore
    return VocabStore(custom_path=tmp / "custom_vocab.json")


def _module(tmp: Path):
    from vocab_module import VocabModule
    mod = VocabModule()
    mod.store = _store(tmp)
    mod._render_all()
    return mod


@pytest.fixture()
def tmpdir_():
    return Path(tempfile.mkdtemp(prefix="t33_ui_"))


def test_preview_lists_every_row_with_four_columns(qapp, tmpdir_):
    """清单必须有「加入 / 词条 / 类型 / 替换值 / 出现次数」五列且行数 == 传入条数。"""
    mod = _module(tmpdir_)
    words = _words(120)
    mod.set_book_words(words, "示例书稿")
    mod.open_book_words()
    qapp.processEvents()

    assert len(mod._book_checks) == 120, "预览清单不得截断，传入几条就列几条"
    labels = [lb.text() for lb in mod._book_pick_label.parent().findChildren(
        type(mod._book_pick_label))]
    assert any("已勾选" in t and "120" in t for t in labels), labels

    # 四列的表头真的画出来了
    heads = {lb.text() for lb in mod.window().findChildren(type(mod._book_pick_label))}
    for col in ("词条", "类型", "替换值", "出现次数"):
        assert col in heads, f"缺列：{col}（现有 {sorted(heads)}）"


def test_select_all_toggle_and_counter(qapp, tmpdir_):
    """整组全选勾选框能双向联动：取消一个 → 全选框自己取消；再全选 → 全部勾上。"""
    mod = _module(tmpdir_)
    mod.set_book_words(_words(6), "书")
    mod.open_book_words()
    qapp.processEvents()

    assert all(cb.isChecked() for cb in mod._book_checks)
    assert mod._book_all_cb.isChecked()

    mod._book_checks[2].setChecked(False)
    qapp.processEvents()
    assert mod._book_all_cb.isChecked() is False
    assert "已勾选 5" in mod._book_pick_label.text()

    mod._book_all_cb.setChecked(True)
    qapp.processEvents()
    assert all(cb.isChecked() for cb in mod._book_checks)
    assert "已勾选 6" in mod._book_pick_label.text()


def test_empty_book_words_shows_human_toast_not_empty_table(qapp, tmpdir_):
    """没有可加入词条：只给人话，不渲染清单、不弹空表格。"""
    mod = _module(tmpdir_)
    seen: list[str] = []
    mod._toast = lambda msg, **kw: seen.append(str(msg))
    mod.set_book_words([], "")
    mod._book_words = []
    mod._book_checks = []
    mod.open_book_words()
    qapp.processEvents()

    assert seen and "没有" in seen[0]
    assert not mod._book_checks, "空状态下不得渲染任何清单行"


def test_add_book_words_writes_and_undoable(qapp, tmpdir_):
    """勾选加入 → 真写进词库 → 撤销后 sha 回到加入前。"""
    mod = _module(tmpdir_)
    mod.set_book_words(_words(3), "书")
    mod.open_book_words()
    qapp.processEvents()
    sha0 = mod.store._disk_sha()

    class _M:
        accepted = False

        def accept(self):
            _M.accepted = True

    added = mod.add_book_words(_M())
    qapp.processEvents()
    assert added == 3 and _M.accepted
    total, rows = mod.store.query("书中词0", scope="custom")
    assert total == 1 and rows[0]["value"] == "正写0"

    rec = mod.store.undo()
    assert rec and rec.get("identical")
    assert mod.store._disk_sha() == sha0


def test_conflict_is_shown_on_screen_not_silently_skipped(qapp, tmpdir_):
    """同词异值：不写入，且冲突明细必须出现在界面弹窗里（不是只吞掉）。"""
    mod = _module(tmpdir_)
    mod.store.add_book_words(
        [dict(word="测试词", value="正写", type="专有名词")], "书")
    mod._toast = lambda msg, **kw: None

    mod._book_report(dict(requested=1, added=0, skipped_exists=[],
                          conflicts=[dict(word="测试词", value="另一写法",
                                          hits=[dict(kind="同词异值",
                                                     where="我的词库")])]),
                     0, [], [dict(word="测试词", value="另一写法",
                                  hits=[dict(kind="同词异值", where="我的词库")])])
    qapp.processEvents()

    from PySide6.QtWidgets import QLabel
    texts = []
    for w in qapp.topLevelWidgets():
        if w.__class__.__name__ == "Modal" and w.isVisible():
            texts += [lb.text() for lb in w.findChildren(QLabel) if lb.text()]
            w.reject()
    joined = " | ".join(texts)
    assert "冲突" in joined and "同词异值" in joined, joined
    # 词库里仍是原值，未被覆盖
    rows = mod.store.query("测试词", scope="custom")[1]
    assert rows[0]["value"] == "正写"


def test_check_page_has_add_button_and_blocks_single_punctuation(qapp):
    """检查页问题行有「＋词库」按钮；单标点无上下文时必须拦住不写。"""
    from check_module import CheckModule

    chk = CheckModule()
    # 注入一个最小但「合法」的报告：has_data 要求 report.ok 为真，
    # 否则所有逐处操作都会走空状态引导分支（这里要验的是加入词库）。
    chk.report = dict(ok=True, book="书", found=1)
    chk.probs = [dict(line=1, char=0, pre="", hl="”", post="",
                      type="缺左引号", action=dict(mode="prepend", char="“"))]
    seen: list[str] = []
    chk.toast = lambda msg: seen.append(str(msg))
    chk.set_vocab_store(_store(Path(tempfile.mkdtemp())))

    cand = chk.problem_candidate(0)
    assert cand["blocked"], "单标点、无上下文必须被判定为不可加入"

    got = chk.add_problem_to_vocab(0)
    assert got is None and seen and "标点" in seen[0]
    assert chk.vocab_store.query("”", scope="custom")[0] == 0, "不得写进危险规则"


def test_check_page_narrows_punctuation_to_whole_sentence(qapp):
    """有上下文时，候选收窄成整句写法，而不是单个引号。"""
    from check_module import CheckModule

    chk = CheckModule()
    chk.report = dict(ok=True, book="书", found=1)
    chk.probs = [dict(line=9, char=0, pre="他说这句话",
                      hl="”", post="然后走了。", type="缺左引号",
                      action=dict(mode="prepend", char="“"))]
    cand = chk.problem_candidate(0)
    assert cand["word"] == "他说这句话”", cand
    assert cand["value"] == "他说这句话“”", cand
    assert cand["scope"] == "整句"
    assert not cand["blocked"]


def test_check_page_add_button_goes_through_same_store(qapp):
    """检查页加入与词库页是同一写入口：写进去就能在词库里检索到、并能撤销。"""
    from check_module import CheckModule

    chk = CheckModule()
    chk.report = dict(ok=True, book="书", found=1)
    chk.probs = [dict(line=9, char=0, pre="他说这句话",
                      hl="”", post="然后走了。", type="缺左引号",
                      action=dict(mode="prepend", char="“"))]
    store = _store(Path(tempfile.mkdtemp()))
    chk.set_vocab_store(store)
    sha0 = store._disk_sha()

    # 顶掉会阻塞离屏事件循环的确认弹窗：直接按「确认」分支的行为验证写入口
    import check_module as cmod
    orig = cmod.QMessageBox
    try:
        class _Box:
            class Icon:
                Question = 0

            class StandardButton:
                Cancel = 2
                Ok = 1

            def __init__(self, *a, **k):
                self._a = a

            def setWindowTitle(self, *a):
                pass

            setIcon = setText = setInformativeText = setWindowTitle

            def setStandardButtons(self, *a):
                pass

            def button(self, *a):
                class _B:
                    def setText(self, *a):
                        pass
                return _B()

            def setDefaultButton(self, *a):
                pass

            def exec(self):
                return 1

        cmod.QMessageBox = _Box
        res = chk.add_problem_to_vocab(0)
    finally:
        cmod.QMessageBox = orig

    assert res and res["added"] == 1
    assert store.query("他说这句话”", scope="custom")[0] == 1
    rec = store.undo()
    assert rec and store._disk_sha() == sha0
