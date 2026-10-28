"""替换引擎错误码与异常类型。

设计原则（承接排期 3.5 门禁 b「异常不得静默」）：
1. 每个失败原因都有稳定的机器可读错误码，调用方按码分流，不解析自然语言；
2. 错误对象携带可复现的现场（引擎路径、命令、超时值、stderr 尾部），便于留痕；
3. 引擎自身把细节打在 stderr 上，集成层负责把 stderr 归类成码，不吞原始信息。

错误码分段：
    E1xxx  引擎进程层（找不到、无权限、超时、非 0 退出、输出不合协议）
    E2xxx  入参层（文本、规则、参数、输出落盘）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class EngineErrorCode:
    """错误码常量表。字符串码是稳定契约，不得随意改名。"""

    # 引擎进程层
    ENGINE_MISSING = "E1001"
    ENGINE_NOT_EXECUTABLE = "E1002"
    ENGINE_TIMEOUT = "E1003"
    ENGINE_FAILED = "E1004"
    ENGINE_OUTPUT_UNEXPECTED = "E1005"
    PY_ENGINE_UNAVAILABLE = "E1006"

    # 入参层
    INPUT_MISSING = "E2101"
    INPUT_UNREADABLE = "E2102"
    RULES_MISSING = "E2201"
    RULES_INVALID_JSON = "E2202"
    RULES_LENGTH_MISMATCH = "E2203"
    RULES_EMPTY = "E2204"
    ARGUMENT_INVALID = "E2301"
    OUTPUT_WRITE_FAILED = "E2401"

    # 未知失败（兜底，出现即说明有未归类路径）
    ENGINE_UNKNOWN = "E1900"


# 码 -> (简短名, 含义, 建议处置)
ERROR_CATALOG: dict[str, tuple[str, str, str]] = {
    EngineErrorCode.ENGINE_MISSING: (
        "ENGINE_MISSING",
        "引擎可执行文件不存在或未构建",
        "先执行 python -m fixtext.engine.builder 离线构建，或用 engine_path 指向已有二进制",
    ),
    EngineErrorCode.ENGINE_NOT_EXECUTABLE: (
        "ENGINE_NOT_EXECUTABLE",
        "引擎文件存在但无法执行（无执行权限、架构或格式不匹配）",
        "检查 chmod +x、目标平台是否与当前主机一致（Windows 二进制不能在 Linux 上直接跑）",
    ),
    EngineErrorCode.ENGINE_TIMEOUT: (
        "ENGINE_TIMEOUT",
        "引擎调用超时，子进程已被强制终止",
        "调大 timeout_s，或确认当前为 1 核环境、大文件两趟替换预期耗时",
    ),
    EngineErrorCode.ENGINE_FAILED: (
        "ENGINE_FAILED",
        "引擎以非 0 退出码结束",
        "看 EngineError.detail 里的 stderr 尾部，按映射码定位是规则还是文本问题",
    ),
    EngineErrorCode.ENGINE_OUTPUT_UNEXPECTED: (
        "ENGINE_OUTPUT_UNEXPECTED",
        "引擎退出码为 0，但 stdout 不符合协议摘要行约定",
        "引擎源码被改动或换了实现，需重新对齐协议（见 docs/T0.3-engine-protocol.md）",
    ),
    EngineErrorCode.PY_ENGINE_UNAVAILABLE: (
        "PY_ENGINE_UNAVAILABLE",
        "Python 替换引擎依赖未安装（pyahocorasick）",
        "python -m pip install pyahocorasick（requirements.txt 已列，实测 2.2.0）",
    ),
    EngineErrorCode.INPUT_MISSING: ("INPUT_MISSING", "待替换文本文件不存在", "检查路径拼写"),
    EngineErrorCode.INPUT_UNREADABLE: (
        "INPUT_UNREADABLE",
        "待替换文本存在但读取失败（权限、路径是目录、被占用）",
        "检查文件权限与是否被其它进程独占",
    ),
    EngineErrorCode.RULES_MISSING: (
        "RULES_MISSING",
        "替换前/后规则文件不存在",
        "确认 T0.2 词库产物 rules/before.json 与 rules/after.json 路径",
    ),
    EngineErrorCode.RULES_INVALID_JSON: (
        "RULES_INVALID_JSON",
        "规则文件不是合法的 JSON 字符串数组",
        "重新生成词库产物；常见原因是把规则写成了对象数组或用了非 UTF-8 编码",
    ),
    EngineErrorCode.RULES_LENGTH_MISMATCH: (
        "RULES_LENGTH_MISMATCH",
        "替换前与替换后规则数量不一致",
        "回到 T0.2 词库链路重新导出，逐条对齐 before/after",
    ),
    EngineErrorCode.RULES_EMPTY: (
        "RULES_EMPTY",
        "规则集为空",
        "至少提供一条规则；空规则集不构成一次有意义的替换",
    ),
    EngineErrorCode.ARGUMENT_INVALID: (
        "ARGUMENT_INVALID",
        "调用参数非法（如替换次数非正整数）",
        "count 必须是正整数，与 Go 引擎 parseArgs 的校验保持一致",
    ),
    EngineErrorCode.OUTPUT_WRITE_FAILED: (
        "OUTPUT_WRITE_FAILED",
        "结果落盘失败",
        "检查输出目录是否存在、可写，磁盘是否已满",
    ),
    EngineErrorCode.ENGINE_UNKNOWN: (
        "ENGINE_UNKNOWN",
        "未归类的引擎调用失败",
        "保留 detail 现场并补充一条归类规则",
    ),
}


@dataclass
class EngineError(Exception):
    """带错误码的引擎异常。

    fields:
        code     机器可读错误码（EngineErrorCode）
        message  人类可读说明
        detail   现场证据（stderr 尾部、命令、超时值等），不参与判定
    """

    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(f"[{self.code}] {self.message}")

    @property
    def name(self) -> str:
        return ERROR_CATALOG.get(self.code, ("UNKNOWN", "", ""))[0]

    @property
    def remedy(self) -> str:
        return ERROR_CATALOG.get(self.code, ("", "", ""))[2]

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "message": self.message,
            "remedy": self.remedy,
            "detail": self.detail,
        }


def error_catalog_table() -> list[dict[str, str]]:
    """把错误码表导出为结构化列表（供接口文档与自验脚本使用）。"""
    return [
        {"code": code, "name": name, "meaning": meaning, "remedy": remedy}
        for code, (name, meaning, remedy) in ERROR_CATALOG.items()
    ]


# Go 引擎 stderr 前缀 -> 错误码。顺序敏感：先匹配更具体的。
_STDERR_RULES: tuple[tuple[str, str], ...] = (
    ("规则数量不匹配", EngineErrorCode.RULES_LENGTH_MISMATCH),
    ("替换规则为空", EngineErrorCode.RULES_EMPTY),
    ("JSON 解析失败", EngineErrorCode.RULES_INVALID_JSON),
    ("读取替换前规则", EngineErrorCode.RULES_MISSING),
    ("读取替换后规则", EngineErrorCode.RULES_MISSING),
    ("读取文件失败", EngineErrorCode.INPUT_UNREADABLE),
    ("替换次数必须", EngineErrorCode.ARGUMENT_INVALID),
    ("参数数量错误", EngineErrorCode.ARGUMENT_INVALID),
    ("写入文件失败", EngineErrorCode.OUTPUT_WRITE_FAILED),
)


def map_engine_stderr(stderr: str, default: str = EngineErrorCode.ENGINE_FAILED) -> str:
    """把 Go 引擎的 stderr 文案归类为错误码。

    Go 侧文案见 src/fixtext/engine/go_src/replace_by_go.go 的 fmt.Errorf 分支；
    未命中任何前缀时回落到 default（引擎非 0 退出）。
    """
    for needle, code in _STDERR_RULES:
        if needle in stderr:
            return code
    return default
