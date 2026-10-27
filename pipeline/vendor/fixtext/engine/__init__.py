"""替换引擎层：Go 子进程后端（默认引擎）。

本层只暴露子进程调用协议，不含任何替换语义实现——替换语义由 Go 引擎负责，
Python 侧只做参数校验、临时工作区隔离、结果交付与错误码归类。

T0.3 范围：Go 集成层（协议 + 客户端 + 离线构建）。
Python greedy 引擎本体属 M1，不在本层。
"""

from __future__ import annotations

from .client import GoEngineClient
from .errors import ERROR_CATALOG, EngineError, EngineErrorCode, error_catalog_table, map_engine_stderr
from .protocol import (
    ENGINE_SUCCESS_PREFIX,
    PROTOCOL_VERSION,
    EngineRequest,
    EngineResponse,
    EngineResult,
    InputMode,
    OutputMode,
    RuleSet,
    parse_engine_stdout,
    request_to_dict,
)

__all__ = [
    "ERROR_CATALOG",
    "ENGINE_SUCCESS_PREFIX",
    "EngineError",
    "EngineErrorCode",
    "EngineRequest",
    "EngineResponse",
    "EngineResult",
    "GoEngineClient",
    "InputMode",
    "OutputMode",
    "PROTOCOL_VERSION",
    "RuleSet",
    "error_catalog_table",
    "map_engine_stderr",
    "parse_engine_stdout",
    "request_to_dict",
]
