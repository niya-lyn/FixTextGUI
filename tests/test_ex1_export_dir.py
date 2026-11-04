"""V1.1-EX.1-R1 · 导出目录统一（单层口径）的单元测试。

口径来源：用户 2026-11-04 两轮拍板，以后一轮为准——
**「导出/历史记录/书名_时间戳/」**，书名与时间戳用下划线拼成**同一个单层
目录名**，不是「书名/时间戳」两层嵌套。

本文件锁四类事实（都是可以机器判定的，不含任何主观判断）：
1. 路径构造：`<导出根>/历史记录/<书名>_<YYYYMMDD_HHMMSS>`，两层父目录 +
   一个单层目录名；时间戳格式沿用旧口径但不带 `export_` 前缀；
2. 书名清洗：非法字符剔除、首尾空格与点号去掉、清完为空兜底「未命名」；
3. 同书多次导出 / 跨书不串扰：每次新时间戳目录、目录名随书名变；
4. 落地面：`HistoryModule._export_with` 真的把文件写进这条路径（不是只在
   路径函数上自证），且 `MainWindow.export_out_dir()` 与导出页同一个根。
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for p in (PKG, PKG / "fixtext_ui"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fixtext_paths as paths  # noqa: E402

STAMP_RE = re.compile(r"^\d{8}_\d{6}$")


# ---------------------------------------------------------------------------
# 1. 路径构造
# ---------------------------------------------------------------------------

def test_history_dir_is_one_flat_name_under_history(tmp_path):
    """`导出/历史记录/书名_时间戳` —— 父目录两层，目录名是一个单层字符串。"""
    d = paths.history_export_dir("炮火弧线", when="20261104_173025",
                                 export_root=tmp_path)
    assert d.parent.name == "历史记录"
    assert d.parent.parent == tmp_path
    assert d.name == "炮火弧线_20261104_173025"
    # 书名与时间戳之间只有一个下划线，没有「书名/时间戳」那层嵌套
    assert d.name.count("_") == 2
    assert len(d.relative_to(tmp_path).parts) == 2, \
        "历史导出目录应当是「历史记录/<单层目录名>」两层，不是三层"


def test_history_dir_defaults_to_package_export_root(monkeypatch, tmp_path):
    """不给导出根时，父目录就是包根下的 `导出/`（与导出页同一棵树）。"""
    monkeypatch.setenv(paths.ENV_PKG_ROOT, str(tmp_path))
    d = paths.history_export_dir("甲书", when="20261104_173025")
    assert d == tmp_path / "导出" / "历史记录" / "甲书_20261104_173025"
    assert d.parent.parent == paths.default_export_dir()


def test_timestamp_format_has_no_export_prefix():
    """时间戳格式沿用 `%Y%m%d_%H%M%S`，且不带旧的 `export_` 前缀。"""
    assert paths.HISTORY_STAMP_FORMAT == "%Y%m%d_%H%M%S"
    now = time.strftime(paths.HISTORY_STAMP_FORMAT)
    assert STAMP_RE.match(now), now
    d = paths.history_export_dir("甲书", when=now, export_root="/tmp/x")
    assert d.name == f"甲书_{now}"
    assert not d.name.startswith("export_")


@pytest.mark.parametrize("bad", ["2026-11-04 17:30:25", "20261104", "20261104_1730",
                                 "export_20261104_173025", ""])
def test_bad_timestamp_is_rejected(bad):
    """时间戳不合口径直接报错，不静默拼出一个畸形目录名。"""
    with pytest.raises(ValueError):
        paths.history_export_dir("甲书", when=bad, export_root="/tmp/x")


# ---------------------------------------------------------------------------
# 2. 书名清洗（用例逐条给出，报告里照抄）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("炮火弧线", "炮火弧线"),
    ("《炮火弧线》", "炮火弧线"),                 # 书名号只是包装，不该进目录名
    ('a/b\\c:d*e?f"g<h>i|j', "abcdefghij"),      # `\ / : * ? " < > |` 全部剔除
    ("  前后空格  ", "前后空格"),                  # 首尾空格
    ("...书名...", "书名"),                       # 首尾点号
    ("..  ..", "未命名"),                         # 只剩点号空白 → 兜底
    ("", "未命名"),                               # 空串 → 兜底
    ("   ", "未命名"),                            # 全空白 → 兜底
    ("???", "未命名"),                            # 全是非法字符 → 兜底
    ("a\nb\tc", "abc"),                           # 控制字符剔除
    ("a.b.c", "a.b.c"),                           # 中间的点是合法的，不动
])
def test_safe_dir_name(raw, expected):
    assert paths.safe_dir_name(raw) == expected


def test_safe_dir_name_truncates_without_trailing_dot():
    """超长书名截断后不能再制造一个以点结尾的目录名（Windows 会拒绝）。"""
    name = paths.safe_dir_name("甲" * 100)
    assert len(name) == paths.DIR_NAME_MAX
    assert not name.endswith(".")
    assert not name.endswith(" ")
    tail_dot = paths.safe_dir_name("甲" * (paths.DIR_NAME_MAX - 1) + "….")
    assert not tail_dot.endswith(".")


def test_empty_book_falls_back_to_unnamed_in_real_path(tmp_path):
    """清洗为空时，真实路径里也要出现「未命名」而不是空的目录名。"""
    d = paths.history_export_dir("???", when="20261104_173025", export_root=tmp_path)
    assert d.name == "未命名_20261104_173025"


# ---------------------------------------------------------------------------
# 3. 同书多次导出 / 跨书不串扰
# ---------------------------------------------------------------------------

def test_two_exports_in_same_second_get_two_directories(tmp_path):
    """同一本书连续两次导出（哪怕落在同一秒）→ 两个目录，不覆盖。"""
    a = paths.reserve_history_export_dir("甲书", export_root=tmp_path)
    b = paths.reserve_history_export_dir("甲书", export_root=tmp_path)
    assert a.is_dir() and b.is_dir()
    assert a != b
    assert a.name.startswith("甲书_") and b.name.startswith("甲书_")
    assert STAMP_RE.match(a.name.split("甲书_", 1)[1])
    assert STAMP_RE.match(b.name.split("甲书_", 1)[1])


def test_reserve_keeps_existing_directory_untouched(tmp_path):
    """已存在的目录不被复用、也不被清空：占位只新建空目录。"""
    first = paths.reserve_history_export_dir("甲书", export_root=tmp_path)
    (first / "甲书.txt").write_text("第一次导出的正文", encoding="utf-8")
    second = paths.reserve_history_export_dir("甲书", export_root=tmp_path)
    assert second != first
    assert (first / "甲书.txt").read_text(encoding="utf-8") == "第一次导出的正文"
    assert list(second.iterdir()) == [], "新目录必须是空的，供本次导出写入"


def test_different_books_do_not_collide(tmp_path):
    """换一本书 → 目录名里的书名不同（不同书不共用同一个目录）。"""
    a = paths.reserve_history_export_dir("甲书", export_root=tmp_path)
    b = paths.reserve_history_export_dir("乙书", export_root=tmp_path)
    assert a != b
    assert a.name.startswith("甲书_")
    assert b.name.startswith("乙书_")


def test_cleaned_book_names_that_collide_are_still_separated(tmp_path):
    """两本"清洗后同名"的书（`a/b` 与 `a:b`）也不会互相覆盖。"""
    a = paths.reserve_history_export_dir("a/b", export_root=tmp_path)
    b = paths.reserve_history_export_dir("a:b", export_root=tmp_path)
    assert a.name.startswith("ab_") and b.name.startswith("ab_")
    assert a != b


# ---------------------------------------------------------------------------
# 4. 落地面：历史页真的写进新目录
# ---------------------------------------------------------------------------

def _fake_source(tmp_path: Path, title: str):
    """造一个最小的导出源：一段正文 + 一个 txt 路径（不碰真实管线）。"""
    import fixtext_export as fx

    body = tmp_path / f"{title}.txt"
    body.write_text("这是正文。\n" * 20, encoding="utf-8")
    src = fx.ExportSource(text_path=str(body), title=title, source_kind="txt",
                          corrected=False)
    return src


@pytest.fixture()
def history_mod(qt_app, tmp_path):
    import history_module as hm

    mod = hm.HistoryModule()
    yield mod
    mod.deleteLater()


def test_history_export_with_lands_in_flat_timestamp_dir(history_mod, tmp_path):
    """`_export_with` 的实际落点：`<导出根>/历史记录/<书名>_<时间戳>/` 三件套。"""
    src = _fake_source(tmp_path, "甲书")
    out = history_mod._export_with(src, {"out_dir": str(tmp_path)}, "anchor",
                                   book="甲书")
    out_dir = Path(out.out_dir)
    assert out_dir.parent.name == "历史记录"
    assert out_dir.parent.parent == tmp_path
    assert out_dir.name.startswith("甲书_")
    assert STAMP_RE.match(out_dir.name.split("甲书_", 1)[1])
    assert Path(out.main_file).parent == out_dir
    # 三件套（正文 + 统计 txt + 统计 csv）平铺在同一个目录里，各自是文件不是子目录
    names = {Path(p).name for p in out.files}
    assert Path(out.main_file).name in names
    assert Path(out.stats_text).name in names
    assert Path(out.stats_csv).name in names
    assert all(Path(p).parent == out_dir for p in out.files)


def test_history_export_twice_makes_two_dirs_both_with_files(history_mod, tmp_path):
    """同一本书两次导出 → 两个目录，各含自己的三件套（旧的那份还在）。"""
    src = _fake_source(tmp_path, "甲书")
    first = history_mod._export_with(src, {"out_dir": str(tmp_path)}, "a", book="甲书")
    second = history_mod._export_with(src, {"out_dir": str(tmp_path)}, "a", book="甲书")
    d1, d2 = Path(first.out_dir), Path(second.out_dir)
    assert d1 != d2
    for d in (d1, d2):
        assert d.parent.name == "历史记录"
        assert len(list(d.iterdir())) >= 3, f"{d} 应至少有三件套"
    # 先导出的那份没被后一次清空或覆盖
    assert all(Path(p).exists() for p in first.files)


def test_history_export_uses_unknown_book_name_fallback(history_mod, tmp_path):
    """书名未知（空 / 只有符号）→ 目录名以「未命名」开头，不留空名。"""
    src = _fake_source(tmp_path, "正文")
    src.title = ""
    out = history_mod._export_with(src, {"out_dir": str(tmp_path)}, "a", book="")
    assert Path(out.out_dir).name.startswith("未命名_")


def test_history_export_without_ctx_root_uses_package_export(history_mod,
                                                             monkeypatch,
                                                             tmp_path):
    """没注入导出根时退回包根 `导出/`，不再落到运行目录旁的 `exported/`。"""
    monkeypatch.setenv(paths.ENV_PKG_ROOT, str(tmp_path))
    src = _fake_source(tmp_path, "甲书")
    out = history_mod._export_with(src, {}, "a", book="甲书")
    d = Path(out.out_dir)
    assert d.parent.parent == paths.default_export_dir()
    assert d.parent.name == "历史记录"
    # 老的「运行目录 + exported / export_<时间戳>」形态彻底不再出现
    assert "exported" not in d.parts
    assert not d.name.startswith("export_")


def test_main_window_export_root_matches_export_page(monkeypatch, tmp_path, qt_app):
    """`export_out_dir()` 与导出页默认目录同一个根（不是书旁边的「导出结果」）。"""
    import main_window as mw

    monkeypatch.setenv(paths.ENV_PKG_ROOT, str(tmp_path))
    win = mw.MainWindow(str(tmp_path / "workspace"))
    try:
        assert win.export_out_dir() == paths.default_export_dir()
        assert win.export_out_dir().name == "导出"
    finally:
        win.deleteLater()
