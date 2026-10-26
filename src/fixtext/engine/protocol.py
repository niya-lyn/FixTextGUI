"""Go 引擎子进程调用协议（协议版本 fixtext-engine/1）。

本模块只负责**协议对象的定义与静态校验**，不碰进程、不碰磁盘 IO 细节。
真正的子进程调度在 client.py，离线构建在 builder.py。

协议分两层，二者都要满足：

一、进程级调用契约（与 Go 引擎源码一一对应，不可改）
    replace_by_go <目标文件> <替换前.json> <替换后.json> <替换次数>
    - 目标文件被**原地改写**（os.WriteFile 回写同一路径），因此集成层必须先复制到临时工作区，
      绝不把调用方的原始文件交出去（承接排期 2.3 只读保护）；
    - 成功时 stdout 打印一行 `✓ 替换完成，共执行 N 次替换`，退出码 0；
    - 失败时 stderr 打印 `错误: ...`，退出码 1。

二、集成层请求 / 响应（本模块定义，调用方与引擎之间的稳定契约）
    EngineRequest → EngineResponse
    请求描述「用哪套规则、替换什么、几次」；响应携带结果摘要或带码错误。
    字段契约见 docs/T0.3-engine-protocol.md，本模块的 dataclass 是唯一实现源。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .errors import EngineError, EngineErrorCode

PROTOCOL_VERSION = "fixtext-engine/1"

# Go 引擎成功时 stdout 的固定前缀（源码 fmt.Printf("✓ 替换完成，共执行 %d 次替换\n")）
ENGINE_SUCCESS_PREFIX = "✓ 替换完成，共执行 "


class InputMode(StrEnum):
    """待替换文本的输入形态。"""

    MEMORY = "memory"  # 调用方给 str/bytes，集成层落临时文件
    FILE = "file"  # 调用方给路径，集成层复制到临时文件后替换


class OutputMode(StrEnum):
    """替换结果的交付形态。"""

    MEMORY = "memory"  # 结果读回内存，原始输入不动
    FILE = "file"  # 结果写到指定路径，原始输入不动
    IN_PLACE = "in_place"  # 结果覆盖输入文件（显式 opt-in，原文件不可恢复）


@dataclass
class RuleSet:
    """一套替换规则：替换前与替换后两个等长字符串数组。

    来源可以是内存数组，也可以是 T0.2 词库产物里的 before.json / after.json。
    校验口径与 Go 引擎 loadRules() 完全一致：数量相等、非空、JSON 是字符串数组。
    """

    before: list[str]
    after: list[str]
    source: str = "memory"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.before, list) or not isinstance(self.after, list):
            raise EngineError(
                EngineErrorCode.RULES_INVALID_JSON,
                "规则必须是字符串数组",
                {"before_type": type(self.before).__name__, "after_type": type(self.after).__name__},
            )
        if len(self.before) != len(self.after):
            raise EngineError(
                EngineErrorCode.RULES_LENGTH_MISMATCH,
                f"规则数量不匹配: 替换前={len(self.before)}, 替换后={len(self.after)}",
                {"before": len(self.before), "after": len(self.after), "source": self.source},
            )
        if not self.before:
            raise EngineError(
                EngineErrorCode.RULES_EMPTY,
                "替换规则为空",
                {"source": self.source},
            )

    def __len__(self) -> int:
        return len(self.before)

    @property
    def unique_before(self) -> int:
        return len(set(self.before))

    @classmethod
    def from_files(cls, before_path: Path | str, after_path: Path | str) -> RuleSet:
        """从 T0.2 词库产物读取规则对。"""
        import json

        before_p, after_p = Path(before_path), Path(after_path)
        for path in (before_p, after_p):
            if not path.exists():
                raise EngineError(
                    EngineErrorCode.RULES_MISSING,
                    f"规则文件不存在: {path.name}",
                    {"path": str(path)},
                )

        def _load(path: Path) -> list[str]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise EngineError(
                    EngineErrorCode.RULES_INVALID_JSON,
                    f"规则文件不是合法 JSON: {path.name}",
                    {"path": str(path), "error": str(exc)},
                ) from exc
            if not isinstance(data, list) or any(not isinstance(item, str) for item in data):
                raise EngineError(
                    EngineErrorCode.RULES_INVALID_JSON,
                    f"规则文件的顶层必须是字符串数组: {path.name}",
                    {"path": str(path), "top_type": type(data).__name__},
                )
            return data

        return cls(_load(before_p), _load(after_p), source=f"{before_p.name}+{after_p.name}")


@dataclass
class EngineRequest:
    """一次替换调用的完整描述。

    input_factory 是个零参可调用对象，返回 bytes 或 str；用于 MEMORY 输入。
    input_path 用于 FILE / IN_PLACE 输入。
    两者必须且只能给一个（按 input_mode 决定）。
    """

    rules: RuleSet
    count: int = 2
    input_mode: InputMode = InputMode.MEMORY
    input_data: bytes | str | None = None
    input_path: Path | None = None
    output_mode: OutputMode = OutputMode.MEMORY
    output_path: Path | None = None
    encoding: str = "utf-8"
    timeout_s: float = 300.0
    protocol: str = PROTOCOL_VERSION

    def validate(self) -> None:
        """静态校验：把所有可提前判定的非法入参挡在起子进程之前。"""
        if self.protocol != PROTOCOL_VERSION:
            raise EngineError(
                EngineErrorCode.ARGUMENT_INVALID,
                f"协议版本不支持: {self.protocol}",
                {"expected": PROTOCOL_VERSION, "got": self.protocol},
            )
        if not isinstance(self.count, int) or isinstance(self.count, bool) or self.count <= 0:
            raise EngineError(
                EngineErrorCode.ARGUMENT_INVALID,
                f"替换次数必须为正整数，当前: {self.count!r}",
                {"count": self.count},
            )
        if self.encoding.lower().replace("-", "") != "utf8":
            raise EngineError(
                EngineErrorCode.ARGUMENT_INVALID,
                f"仅支持 utf-8 编码，当前: {self.encoding}",
                {"encoding": self.encoding},
            )
        if not isinstance(self.timeout_s, (int, float)) or self.timeout_s <= 0:
            raise EngineError(
                EngineErrorCode.ARGUMENT_INVALID,
                f"超时必须为正数秒，当前: {self.timeout_s!r}",
                {"timeout_s": self.timeout_s},
            )
        if self.input_mode is InputMode.MEMORY and self.input_data is None:
            raise EngineError(
                EngineErrorCode.ARGUMENT_INVALID,
                "MEMORY 输入必须提供 input_data",
                {"input_mode": self.input_mode.value},
            )
        if self.input_mode is not InputMode.MEMORY and self.input_path is None:
            raise EngineError(
                EngineErrorCode.ARGUMENT_INVALID,
                "FILE / IN_PLACE 输入必须提供 input_path",
                {"input_mode": self.input_mode.value},
            )
        if self.output_mode is OutputMode.FILE and self.output_path is None:
            raise EngineError(
                EngineErrorCode.ARGUMENT_INVALID,
                "FILE 输出必须提供 output_path",
                {"output_mode": self.output_mode.value},
            )
        if self.output_mode is OutputMode.IN_PLACE and self.input_mode is not InputMode.FILE:
            raise EngineError(
                EngineErrorCode.ARGUMENT_INVALID,
                "IN_PLACE 输出要求输入来自 FILE",
                {"input_mode": self.input_mode.value, "output_mode": self.output_mode.value},
            )
        if self.rules is not None:
            self.rules.validate()


@dataclass
class EngineResult:
    """成功结果摘要。所有数值都是实测值，不含外推。"""

    bytes_in: int
    bytes_out: int
    chars_in: int
    chars_out: int
    sha256_in: str
    sha256_out: str
    rules: int
    unique_rules: int
    count: int
    elapsed_s: float
    exit_code: int
    engine_stdout: str
    engine_path: str
    changed: bool
    output_text: str | None = None

    def as_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        data = {
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "chars_in": self.chars_in,
            "chars_out": self.chars_out,
            "sha256_in": self.sha256_in,
            "sha256_out": self.sha256_out,
            "rules": self.rules,
            "unique_rules": self.unique_rules,
            "count": self.count,
            "elapsed_s": round(self.elapsed_s, 4),
            "exit_code": self.exit_code,
            "engine_stdout": self.engine_stdout,
            "engine_path": self.engine_path,
            "changed": self.changed,
        }
        if include_text:
            data["output_text"] = self.output_text
        return data


@dataclass
class EngineResponse:
    """对外统一响应：要么 ok + result，要么 !ok + error，二者互斥。"""

    ok: bool
    result: EngineResult | None = None
    error: EngineError | None = None
    protocol: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.ok and self.result is None:
            raise ValueError("ok=True 必须携带 result")
        if not self.ok and self.error is None:
            raise ValueError("ok=False 必须携带 error")

    @classmethod
    def success(cls, result: EngineResult) -> EngineResponse:
        return cls(ok=True, result=result)

    @classmethod
    def failure(cls, error: EngineError) -> EngineResponse:
        return cls(ok=False, error=error)

    def as_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "ok": self.ok,
            "result": self.result.as_dict(include_text=include_text) if self.result else None,
            "error": self.error.as_dict() if self.error else None,
        }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_engine_stdout(stdout: str, expected_count: int) -> int:
    """解析引擎 stdout 的摘要行，返回它自报的执行次数。

    退出码 0 但摘要行缺失或不符，属协议违约（E1005）——不能把「没输出」当成功。
    """
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith(ENGINE_SUCCESS_PREFIX):
            continue
        tail = line[len(ENGINE_SUCCESS_PREFIX) :]
        digits = tail.split(" ")[0]
        if not digits.isdigit():
            break
        reported = int(digits)
        if reported != expected_count:
            raise EngineError(
                EngineErrorCode.ENGINE_OUTPUT_UNEXPECTED,
                f"引擎自报替换次数 {reported} 与请求 {expected_count} 不一致",
                {"reported": reported, "expected": expected_count, "stdout": stdout[-400:]},
            )
        return reported
    raise EngineError(
        EngineErrorCode.ENGINE_OUTPUT_UNEXPECTED,
        "引擎退出码为 0 但未输出协议约定的完成摘要行",
        {"expected_prefix": ENGINE_SUCCESS_PREFIX, "stdout": stdout[-400:]},
    )


def request_to_dict(req: EngineRequest) -> dict[str, Any]:
    """把请求序列化成可落盘的审计记录（不含大文本正文，只留摘要）。"""
    body = req.input_data
    digest = None
    size = None
    if isinstance(body, str):
        raw = body.encode(req.encoding)
        digest, size = sha256_bytes(raw), len(raw)
    elif isinstance(body, bytes):
        digest, size = sha256_bytes(body), len(body)
    return {
        "protocol": req.protocol,
        "count": req.count,
        "encoding": req.encoding,
        "timeout_s": req.timeout_s,
        "input_mode": req.input_mode.value,
        "input_path": str(req.input_path) if req.input_path else None,
        "input_sha256": digest,
        "input_bytes": size,
        "output_mode": req.output_mode.value,
        "output_path": str(req.output_path) if req.output_path else None,
        "rules_source": req.rules.source,
        "rules": len(req.rules),
        "unique_rules": req.rules.unique_before,
    }


@dataclass
class ReplacementBatch:
    """批量替换的一次调用记录，便于上层做一次多文件替换并对齐错误。"""

    name: str
    response: EngineResponse
    extra: dict[str, Any] = field(default_factory=dict)
