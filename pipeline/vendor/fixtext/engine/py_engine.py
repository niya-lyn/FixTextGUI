"""Python greedy 替换引擎（M4-T4.2 · 第二引擎 / Go 降级路径）。

排期 §3.1 定稿（2026-10-26）：**Go 默认 / Python 可选**。本模块是与
``GoEngineClient`` 同接口的纯 Python 实现——调用方拿到的仍是
``EngineRequest → EngineResponse``，replace 阶段按配置键 ``engine`` 选引擎，
切换对上层透明。

替换语义（排期 §3.1 硬门禁，与 Go ``strings.NewReplacer`` 一致）：

* **参数顺序优先（first-wins）**：同一 ``before`` 重复出现时取数组里**第一**条
  的 ``after``（建树 ``if not A.exists(b): A.add_word(b, i)``）；
  同一起点的多个命中按规则序号升序取最先者。
* **匹配失败前进 1 字符**：未命中位置的原字符原样保留（贪心选路天然等价）。
* **命中后跳到匹配结束**：``cursor = start + len(before)``。
* **不重叠**：``start < cursor`` 的命中直接丢弃。
* **生产两趟**：``count`` 默认 2，第二趟对第一趟结果再跑一次。
* **词库展开沿用 flattenMaps**：本引擎只消费 T0.2 产出的 before/after JSON
  数组（array_reverse + 字节长度降序的展开顺序已在文件里定死），不重排。

实现出处：P0 前置验证包（FixText_P0验证_真实语料复测_v2.zip）里已与 Go
**逐字节等价**（4 语料 × 单趟 + 两趟 SHA-256 全一致）的
``py_greedy_worker.py``——按本卡要求「先复用再改造」，核心选路逻辑逐行
保留，外面套上 ``EngineRequest → EngineResponse`` 协议层。

**明令禁止**（排期 §3.1 / 本卡评审门禁）：不得使用 flashtext，不得使用
pyahocorasick 的 ``iter_long``——前者语义不同（最长匹配、大小写处理），
后者是「最长不重叠」贪心，与 first-wins 语义冲突。

取消与超时：Go 引擎靠杀子进程取消；本引擎在进程内跑，通过模块级
``set_cancel_check`` 挂钩协作式取消（每 65536 个命中检查一次 + 每趟开始
检查），超时同理软中断——语义与 Go 路径对齐：取消 / 超时都不留半成品。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from .errors import EngineError, EngineErrorCode
from .protocol import (
    EngineRequest,
    EngineResponse,
    EngineResult,
    InputMode,
    OutputMode,
    sha256_bytes,
)

#: 取消检查的周期（处理多少个命中检查一次）
_CANCEL_CHECK_INTERVAL = 65536

#: 引擎自述标识（进报告与日志，与 Go 二进制路径区分）
PY_ENGINE_ID = "python:pyahocorasick-greedy"


class PyEngineCancelled(RuntimeError):
    """用户取消了 Python 引擎的替换（对应 Go 路径的杀子进程）。"""


# ---------------------------------------------------------------------------
# 协作式取消钩子（worker 在跑校正前挂上，跑完摘掉）
# ---------------------------------------------------------------------------

_cancel_check: Callable[[], bool] | None = None


def set_cancel_check(fn: Callable[[], bool] | None) -> None:
    """注册 / 注销取消检查函数（返回 True 表示用户请求取消）。"""
    global _cancel_check
    _cancel_check = fn


def _check_cancel() -> None:
    if _cancel_check is not None and _cancel_check():
        raise PyEngineCancelled("已终止替换引擎")


# ---------------------------------------------------------------------------
# 贪心替换核心（P0 已验证实现，语义见模块 docstring）
# ---------------------------------------------------------------------------

def _build_automaton(before: list[str]):
    """建 Aho-Corasick 自动机：重复 before 只留数组里第一条（first-wins）。

    对应 Go ``strings.NewReplacer`` 对重复 key 取首个 after 的语义。
    返回 (automaton, 有效规则下标数组)。
    """
    import ahocorasick

    A = ahocorasick.Automaton()
    keep: list[int] = []          # 自动机里的 value -> 原规则下标
    for i, b in enumerate(before):
        if not A.exists(b):
            A.add_word(b, len(keep))
            keep.append(i)
    A.make_automaton()
    return A, keep


def replace_greedy(A, text: str, blens: list[int], after: list[str],
                   *, deadline: float | None = None) -> tuple[str, int]:
    """一趟贪心替换：全量匹配 → 按起点（同起点按规则序）升序 → 不重叠选路。

    ``deadline`` 为绝对时间戳（time.monotonic 口径），到点抛超时。
    """
    matches = []
    for end, j in A.iter(text):
        matches.append((end - blens[j] + 1, j))
    matches.sort()
    out = []
    cursor = 0
    n = 0
    for start, j in matches:
        if start < cursor:
            continue
        n += 1
        if n % _CANCEL_CHECK_INTERVAL == 0:
            _check_cancel()
            if deadline is not None and time.monotonic() > deadline:
                raise EngineError(
                    EngineErrorCode.ENGINE_TIMEOUT,
                    f"Python 引擎替换超时，本趟已终止（已处理 {n} 个命中）",
                    {"processed_matches": n},
                )
        out.append(text[cursor:start])
        out.append(after[j])
        cursor = start + blens[j]
    out.append(text[cursor:])
    return "".join(out), n


# ---------------------------------------------------------------------------
# 客户端（与 GoEngineClient 同接口）
# ---------------------------------------------------------------------------

class PyGreedyEngineClient:
    """Python greedy 引擎：``run(EngineRequest) → EngineResponse``。

    与 ``GoEngineClient`` 的差异只在执行体（进程内 vs 子进程）：

    * 引擎可用性依赖 ``pyahocorasick`` 装没装（缺库 → E1006，人话提示装依赖），
      不依赖任何二进制文件——这正是它当降级引擎的原因；
    * IN_PLACE 输出与 Go 路径同样默认禁用（M4-T4.4 只读保护，口径一致）；
    * ``engine_path`` 字段填 ``PY_ENGINE_ID``，报告里据此区分引擎。
    """

    def __init__(self, *, default_timeout_s: float = 1800.0):
        self.default_timeout_s = default_timeout_s

    def run(self, request: EngineRequest) -> EngineResponse:
        """执行一次替换。所有失败都归一成 EngineResponse.failure(EngineError)。"""
        try:
            request.validate()
            return EngineResponse.success(self._run_or_raise(request))
        except EngineError as exc:
            return EngineResponse.failure(exc)
        except PyEngineCancelled:
            raise                      # 取消不落 EngineResponse，由 worker 归成 CorrectionCancelled
        except ImportError as exc:
            return EngineResponse.failure(
                EngineError(
                    EngineErrorCode.PY_ENGINE_UNAVAILABLE,
                    "Python 替换引擎依赖未安装（pyahocorasick）",
                    {
                        "error": str(exc),
                        "hint": "python -m pip install pyahocorasick（requirements.txt 已列）",
                    },
                )
            )
        except OSError as exc:
            return EngineResponse.failure(
                EngineError(
                    EngineErrorCode.ENGINE_UNKNOWN,
                    f"Python 引擎调用出现未归类 OSError: {exc.__class__.__name__}",
                    {"error": str(exc), "engine": PY_ENGINE_ID},
                )
            )

    # ---------------- 主流程 ----------------

    def _run_or_raise(self, request: EngineRequest) -> EngineResult:
        try:
            import ahocorasick  # noqa: F401 - 可用性检查，真正使用在 _build_automaton
        except ImportError as exc:
            raise EngineError(
                EngineErrorCode.PY_ENGINE_UNAVAILABLE,
                "Python 替换引擎依赖未安装（pyahocorasick）",
                {
                    "error": str(exc),
                    "hint": "python -m pip install pyahocorasick（requirements.txt 已列）",
                },
            ) from exc

        timeout_s = request.timeout_s or self.default_timeout_s
        deadline = time.monotonic() + timeout_s

        started = time.perf_counter()
        in_bytes, text = self._load_input(request)
        A, keep = _build_automaton(request.rules.before)
        blens = [len(request.rules.before[i]) for i in keep]
        after = [request.rules.after[i] for i in keep]

        _check_cancel()
        count = request.count
        n_total = 0
        for _pass in range(count):
            text, n = replace_greedy(A, text, blens, after, deadline=deadline)
            n_total = n
            _check_cancel()
            if time.monotonic() > deadline:
                raise EngineError(
                    EngineErrorCode.ENGINE_TIMEOUT,
                    f"Python 引擎替换超时（{timeout_s}s），本趟已终止",
                    {"timeout_s": timeout_s, "completed_passes": _pass},
                )
        elapsed = time.perf_counter() - started

        out_bytes = text.encode(request.encoding)
        return self._deliver_output(request, out_bytes, in_bytes, count, elapsed, n_total)

    # ---------------- 分步实现 ----------------

    def _load_input(self, request: EngineRequest) -> tuple[bytes, str]:
        if request.input_mode is InputMode.MEMORY:
            raw = (
                request.input_data.encode(request.encoding)
                if isinstance(request.input_data, str)
                else bytes(request.input_data)
            )
        else:
            src = Path(request.input_path)  # type: ignore[arg-type]
            if not src.exists():
                raise EngineError(
                    EngineErrorCode.INPUT_MISSING,
                    f"待替换文件不存在: {src.name}",
                    {"path": str(src)},
                )
            if not src.is_file():
                raise EngineError(
                    EngineErrorCode.INPUT_UNREADABLE,
                    f"待替换路径不是普通文件: {src.name}",
                    {"path": str(src), "is_dir": src.is_dir()},
                )
            try:
                raw = src.read_bytes()
            except OSError as exc:
                raise EngineError(
                    EngineErrorCode.INPUT_UNREADABLE,
                    f"读取待替换文件失败: {exc.__class__.__name__}",
                    {"path": str(src), "os_error": str(exc)},
                ) from exc
        try:
            return raw, raw.decode(request.encoding)
        except UnicodeDecodeError as exc:
            raise EngineError(
                EngineErrorCode.INPUT_UNREADABLE,
                "待替换文本不是合法 UTF-8",
                {"error": str(exc), "bytes": len(raw)},
            ) from exc

    def _deliver_output(
        self,
        request: EngineRequest,
        out_bytes: bytes,
        in_bytes: bytes,
        count: int,
        elapsed: float,
        n_matches: int,
    ) -> EngineResult:
        text: str | None = None
        if request.output_mode is OutputMode.MEMORY:
            text = out_bytes.decode(request.encoding, errors="strict")
        elif request.output_mode is OutputMode.FILE:
            dst = Path(request.output_path)  # type: ignore[arg-type]
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(out_bytes)
            except OSError as exc:
                raise EngineError(
                    EngineErrorCode.OUTPUT_WRITE_FAILED,
                    f"结果落盘失败: {exc.__class__.__name__}",
                    {"path": str(dst), "os_error": str(exc)},
                ) from exc
        else:  # IN_PLACE：与 Go 路径同一条只读保护防线
            if os.environ.get("FIXTEXT_ALLOW_IN_PLACE") != "1":
                raise EngineError(
                    EngineErrorCode.ARGUMENT_INVALID,
                    "原地覆盖输入文件已被禁用（只读保护）",
                    {
                        "input_path": str(request.input_path),
                        "output_mode": request.output_mode.value,
                        "hint": "产品链路请用 OutputMode.FILE 把结果落到本次运行目录；"
                                "确需原地覆盖时显式设 FIXTEXT_ALLOW_IN_PLACE=1",
                    },
                )
            dst = Path(request.input_path)  # type: ignore[arg-type]
            try:
                tmp = dst.with_name(dst.name + ".fixtext-tmp")
                tmp.write_bytes(out_bytes)
                os.replace(tmp, dst)
            except OSError as exc:
                raise EngineError(
                    EngineErrorCode.OUTPUT_WRITE_FAILED,
                    f"原地覆盖失败: {exc.__class__.__name__}",
                    {"path": str(dst), "os_error": str(exc)},
                ) from exc

        return EngineResult(
            bytes_in=len(in_bytes),
            bytes_out=len(out_bytes),
            chars_in=len(in_bytes.decode(request.encoding, errors="replace")),
            chars_out=len(out_bytes.decode(request.encoding, errors="replace")),
            sha256_in=sha256_bytes(in_bytes),
            sha256_out=sha256_bytes(out_bytes),
            rules=len(request.rules),
            unique_rules=request.rules.unique_before,
            count=count,
            elapsed_s=elapsed,
            exit_code=0,
            engine_stdout=f"✓ 替换完成，共执行 {count} 次替换（pyahocorasick 贪心，命中 {n_matches} 次/趟）",
            engine_path=PY_ENGINE_ID,
            changed=in_bytes != out_bytes,
            output_text=text,
        )
