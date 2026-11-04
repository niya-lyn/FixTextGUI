"""fixtext_vocab_import —— V1.1-D1 词库导入的来源解析与格式归一 + V1.1-D2 分批与不合格清单。

本包**只做解析、归一、切分**：把「用户粘的一段表格文本」或「拖进来的 csv / txt」
变成一份结构化的候选词条表，把人话错误说清楚（D1）；再把候选行切成
「能导入的」与「进清单的」，并按阈值分批给进度（D2）。

它**不写库**（D5 负责）、**不做冲突处置**（D4 负责）、**不做预览分组**（D3 负责）。
因此本包可以独立单测，不依赖 Qt，也不依赖装载层。

对外主入口：

    from fixtext_vocab_import import parse_text, parse_file, ColumnMapping

    sheet = parse_text(clipboard_text)          # 粘贴通道（D1）
    sheet = parse_file("words.csv")             # 文件通道（D1）

    from fixtext_vocab_import import prepare_import      # D2 联合入口
    prep = prepare_import(sheet)
    prep.rejects.summary_text()                 # 「N 行合格、M 行不合格：…」
    prep.rejects.write_export("清单.csv")        # 不合格清单导出
    for batch in prep.plan:                     # 只含合法行的分批计划
        ...

`sheet` 是 `ParsedSheet`：含表头判定、分隔符、列映射、原始行、以及解析失败原因
（人话，无异常栈、无英文术语）。
"""

from __future__ import annotations

from .escape import (
    CSV_ESCAPED_CHARS,
    contains_escaped_markers,
    restore_escaped_once,
    escape_escaped,
)
from .mapping import ColumnMapping, apply_mapping
from .parse import ParsedSheet, ParseError, parse_file, parse_text
from .dialect import DelimiterGuess, guess_delimiter
from .messages import (
    ImportMessages,
    human_error,
)
# V1.1-D2
from .batching import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_BATCH_THRESHOLD,
    Batch,
    BatchFailure,
    BatchPlan,
    BatchPolicy,
    BatchRunResult,
    ImportPrep,
    ProgressReport,
    plan_batches,
    prepare_from_rejects,
    prepare_import,
    run_batches,
)
from .rejects import (
    RejectList,
    RejectReason,
    RejectedRow,
    partition_rows,
    partition_sheet,
)

__all__ = [
    "CSV_ESCAPED_CHARS",
    "ColumnMapping",
    "DelimiterGuess",
    "ImportMessages",
    "ParseError",
    "ParsedSheet",
    "apply_mapping",
    "contains_escaped_markers",
    "escape_escaped",
    "guess_delimiter",
    "human_error",
    "parse_file",
    "parse_text",
    "restore_escaped_once",
    # D2 分批
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_BATCH_THRESHOLD",
    "Batch",
    "BatchFailure",
    "BatchPlan",
    "BatchPolicy",
    "BatchRunResult",
    "ImportPrep",
    "ProgressReport",
    "plan_batches",
    "prepare_from_rejects",
    "prepare_import",
    "run_batches",
    # D2 不合格清单
    "RejectList",
    "RejectReason",
    "RejectedRow",
    "partition_rows",
    "partition_sheet",
]
__version__ = "1.1.0"
