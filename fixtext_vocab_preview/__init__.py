"""V1.1-D3 · 导入预览（三组分组 + 逐条取消 + 预演核对）；V1.1-D4 · 冲突处置 + 影响预览。

**只读**：整包不对用户词库落盘。冲突判定走既有查重（`fixtext_vocab`），
不合格行取 D2 的 `RejectList`，分批声明取 D2 的 `plan_batches`——三处都不另写。
D4 加进来的三种处置（改值 / 跳过 / 设为禁用）也只喂给同一套分组与查重重判，
不另造判定；设为禁用的存储走 `fixtext_vocab` 的 word_states 唯一入口。
"""

from __future__ import annotations

from .groups import (ACTION_DISABLE, ACTION_EDIT, ACTION_NAMES, ACTION_SKIP,
                     EFFECT_ADD, EFFECT_DISABLED, EFFECT_NAMES, EFFECT_PENDING,
                     EFFECT_REJECTED, EFFECT_SKIPPED, EFFECT_UPDATE, GROUP_CONFLICT,
                     GROUP_NAMES, GROUP_NEW, GROUP_REJECT, PreviewItem, PreviewModel,
                     preview_from_rejects, preview_from_sheet)
from .rehearsal import (RehearsalResult, rehearse, write_new_entries,
                        write_plan_entries)

__all__ = [
    "GROUP_NEW", "GROUP_CONFLICT", "GROUP_REJECT", "GROUP_NAMES",
    "PreviewItem", "PreviewModel", "preview_from_sheet", "preview_from_rejects",
    "RehearsalResult", "rehearse", "write_new_entries",
    # D4：三种处置与每条的去向
    "ACTION_EDIT", "ACTION_SKIP", "ACTION_DISABLE", "ACTION_NAMES",
    "EFFECT_ADD", "EFFECT_UPDATE", "EFFECT_DISABLED", "EFFECT_SKIPPED",
    "EFFECT_PENDING", "EFFECT_REJECTED", "EFFECT_NAMES",
    "write_plan_entries",
]
