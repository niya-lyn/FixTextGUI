"""主窗口骨架结构验证：六入口、面板数量、路由联动。"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from fixtext.app import build_application, create_main_window  # noqa: E402
from fixtext.common.app_meta import ENTRY_LABELS  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return build_application([])


@pytest.mark.gui
def test_six_entries_present(qapp) -> None:
    window = create_main_window()
    assert window._nav.count() == 6
    labels = [window._nav.item(i).text() for i in range(window._nav.count())]
    assert labels == list(ENTRY_LABELS)
    window.close()


@pytest.mark.gui
def test_panel_count_matches_entries(qapp) -> None:
    window = create_main_window()
    assert window._stack.count() == len(ENTRY_LABELS)
    window.close()


@pytest.mark.gui
@pytest.mark.parametrize("index", [0, 2, 5])
def test_entry_switch_updates_stack(qapp, index: int) -> None:
    window = create_main_window()
    window.select_entry(index)
    assert window.current_entry_index() == index
    assert window._stack.currentIndex() == index
    window.close()


@pytest.mark.gui
def test_out_of_range_select_is_noop(qapp) -> None:
    window = create_main_window()
    window.select_entry(0)
    window.select_entry(99)
    assert window.current_entry_index() == 0
    window.close()
