"""V1.1-D3 · 导入预览（三组分组 + 逐条取消 + 预演核对）。

**只读**：整包不对用户词库落盘。冲突判定走既有查重（`fixtext_vocab`），
不合格行取 D2 的 `RejectList`，分批声明取 D2 的 `plan_batches`——三处都不另写。
"""

from __future__ import annotations

from .groups import (GROUP_CONFLICT, GROUP_NEW, GROUP_NAMES, GROUP_REJECT,
                     PreviewItem, PreviewModel, preview_from_rejects,
                     preview_from_sheet)
from .rehearsal import RehearsalResult, rehearse, write_new_entries

__all__ = [
    "GROUP_NEW", "GROUP_CONFLICT", "GROUP_REJECT", "GROUP_NAMES",
    "PreviewItem", "PreviewModel", "preview_from_sheet", "preview_from_rejects",
    "RehearsalResult", "rehearse", "write_new_entries",
]
