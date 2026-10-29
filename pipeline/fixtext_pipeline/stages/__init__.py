"""M1 各引擎的阶段实现。"""

from __future__ import annotations

from .base import Stage, StageCancelled, StageError
from .merge import MergeStage
from .layout import LayoutStage
from .replace import (
    ReplaceStage,
    ReplacePreprocessStage,
    ReplaceStrictStage,
    ReplaceZhuyinStage,
)
from .quote import QuoteStage
from .bookmap import BookMapStage
from .restore import RestoreStage

#: 阶段名 -> 阶段类（顺序即执行顺序）
STAGES = {
    MergeStage.name: MergeStage,
    LayoutStage.name: LayoutStage,
    ReplacePreprocessStage.name: ReplacePreprocessStage,
    ReplaceStrictStage.name: ReplaceStrictStage,
    ReplaceStage.name: ReplaceStage,
    ReplaceZhuyinStage.name: ReplaceZhuyinStage,
    QuoteStage.name: QuoteStage,
    BookMapStage.name: BookMapStage,
    RestoreStage.name: RestoreStage,
}

__all__ = [
    "Stage",
    "StageError",
    "StageCancelled",
    "STAGES",
    "MergeStage",
    "LayoutStage",
    "ReplaceStage",
    "ReplacePreprocessStage",
    "ReplaceStrictStage",
    "ReplaceZhuyinStage",
    "QuoteStage",
    "BookMapStage",
    "RestoreStage",
]
