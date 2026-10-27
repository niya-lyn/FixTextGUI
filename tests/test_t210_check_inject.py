"""M2-T2.10 检查页真实数据注入（入口③）。

验收点：把一次真实运行的引号报告注入页面后，清单条目数与报告声明的
error_count 一致，且分页不静默丢数据；没有运行时给空状态、不显示假数据。

数据来自 `tests/samples/` 里那份**真实跑出来的** 108 条引号报告
（《炮火弧线》788 章 / 108 问题），不是编造的样例。
"""
from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PKG / "fixtext_ui"))

import _fixture_run as fxr  # noqa: E402


@pytest.fixture()
def run_env():
    root = Path(tempfile.mkdtemp(prefix="t210_check_"))
    run = fxr.build_run(root)
    yield run
    fxr.cleanup(root)


def _module():
    import check_module
    return check_module.CheckModule()


def test_empty_state_has_no_fake_data(qapp):
    """未校正：空状态是人话引导，一条假数据都不能有。"""
    import fixtext_check as fc
    mod = _module()

    assert mod.has_data is False
    assert mod.probs == []

    data = fc.load_report("/nonexistent/run-x")
    assert data["ok"] is False
    assert data["found"] == 0
    assert data["items"] == []
    # 空状态文案是给用户看的，必须是完整人话句子
    assert "校正" in mod._empty_text()


def test_injected_report_matches_error_count(run_env, qapp):
    """注入真实报告：条目数 == error_count，且不是 first_errors 的 20 条上限。"""
    import fixtext_check as fc
    mod = _module()

    data = fc.load_report(run_env)
    mod.set_report(data)

    assert data["declared"] == 108, "真实报告声明的引号问题数应为 108"
    assert data["found"] == 108, "必须读到全量事件，不能只读 first_errors 的 20 条"
    assert data["consistent"] is True
    assert mod.has_data is True
    assert len(mod.probs) == data["declared"]


def test_pagination_covers_every_item(run_env, qapp):
    """分页要覆盖全部条目：逐页翻到底，条目集合必须等于全集。"""
    import math as _m

    import check_module as cm
    import fixtext_check as fc
    mod = _module()
    mod.set_report(fc.load_report(run_env))

    assert len(mod.probs) == 108
    assert mod.pages == _m.ceil(108 / cm.PAGE_SIZE) == 3, "108 条 / 每页 40 条应为 3 页"

    seen: list[int] = []
    for _ in range(mod.pages):
        start = mod._page * cm.PAGE_SIZE
        end = min(len(mod.probs), start + cm.PAGE_SIZE)
        seen.extend(range(start, end))
        mod.turn_page(1)

    assert sorted(seen) == list(range(108)), "翻页应覆盖全部 108 条，不静默丢数据"
    assert len(set(seen)) == len(seen), "同一条不应在分页里重复出现"


def test_marks_persist_across_reload(run_env, qapp):
    """复核进度落盘后在「重开页面」时还在（重启后处理进度不丢）。"""
    import fixtext_check as fc
    mod = _module()
    mod.set_report(fc.load_report(run_env))

    mod.select(0)
    mod.skip_here()
    assert mod._marks, "跳过一处后应写入复核标记"

    # 页面内部已把标记落盘；重开一个页面读回来必须一致
    saved = fc.load_marks(run_env)
    assert saved == mod._marks, "复核标记应写进运行目录"

    fresh = _module()
    fresh.set_report(fc.load_report(run_env))
    fresh.set_marks(saved)
    assert fresh._marks == mod._marks, "重开页面后复核标记应原样恢复"
