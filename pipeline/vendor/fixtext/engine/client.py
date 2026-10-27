"""Go 引擎子进程客户端：把 EngineRequest 落成一次真实进程调用。

只读保护（承接排期 2.3）：引擎是**原地改写**语义（os.WriteFile 回写目标路径），
所以本客户端永远先把内容复制到一次性临时工作区，引擎只许碰临时副本；
唯一例外是显式 `OutputMode.IN_PLACE`——那是调用方明确要求覆盖原文件的行为。

错误归类顺序（与 errors.map_engine_stderr 对齐）：
    找不到引擎 → E1001
    引擎不可执行（无 x 位 / 格式错 / Exec format error） → E1002
    超时（已 kill） → E1003
    非 0 退出 → 按 stderr 文案细化（E22xx / E21xx / E24xx），无匹配则 E1004
    退出 0 但无协议摘要行 → E1005
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .errors import EngineError, EngineErrorCode, map_engine_stderr
from .protocol import (
    EngineRequest,
    EngineResponse,
    EngineResult,
    InputMode,
    OutputMode,
    parse_engine_stdout,
    sha256_bytes,
)


class GoEngineClient:
    """一个 Go 引擎二进制的调用封装。默认引擎路径由 builder.ensure_engine() 提供。

    用法：
        client = GoEngineClient()                       # 用当前主机默认引擎
        resp = client.run(EngineRequest(rules=rs, input_data=text, count=2))
        if resp.ok: print(resp.result.sha256_out)
        else: print(resp.error.code)
    """

    def __init__(self, engine_path: Path | str | None = None, *, default_timeout_s: float = 300.0):
        if engine_path is None:
            from .builder import default_engine_path

            engine_path = default_engine_path()
        self.engine_path = Path(engine_path)
        self.default_timeout_s = default_timeout_s
        # 引擎缺失时的现场信息留到调用时机再抛，构造期不抛——
        # 这样调用方可以先构造 client，再在错误处理里统一拿码。
        self._missing_reason: str | None = None

    # ---------- 前置检查 ----------

    def _resolve_engine(self) -> Path:
        """把引擎路径解析成可执行文件，或抛出带码的 EngineError。"""
        path = self.engine_path
        if not path.exists():
            raise EngineError(
                EngineErrorCode.ENGINE_MISSING,
                f"引擎可执行文件不存在: {path}",
                {
                    "engine_path": str(path),
                    "hint": "python -m fixtext.engine.builder 可离线构建",
                },
            )
        if not path.is_file():
            raise EngineError(
                EngineErrorCode.ENGINE_NOT_EXECUTABLE,
                f"引擎路径不是普通文件: {path}",
                {"engine_path": str(path), "is_dir": path.is_dir()},
            )
        if os.name != "nt" and not os.access(path, os.X_OK):
            raise EngineError(
                EngineErrorCode.ENGINE_NOT_EXECUTABLE,
                f"引擎文件缺少执行位: {path.name}",
                {"engine_path": str(path), "mode": oct(path.stat().st_mode)},
            )
        return path

    # ---------- 主流程 ----------

    def run(self, request: EngineRequest) -> EngineResponse:
        """执行一次替换。所有失败都归一成 EngineResponse.failure(EngineError)。"""
        try:
            request.validate()
            return EngineResponse.success(self._run_or_raise(request))
        except EngineError as exc:
            return EngineResponse.failure(exc)
        except OSError as exc:
            return EngineResponse.failure(
                EngineError(
                    EngineErrorCode.ENGINE_UNKNOWN,
                    f"引擎调用出现未归类 OSError: {exc.__class__.__name__}",
                    {"error": str(exc), "engine_path": str(self.engine_path)},
                )
            )

    def _run_or_raise(self, request: EngineRequest) -> EngineResult:
        engine = self._resolve_engine()
        timeout_s = request.timeout_s or self.default_timeout_s

        workdir = Path(tempfile.mkdtemp(prefix="fixtext-engine-"))
        try:
            target_path, in_bytes = self._stage_input(request, workdir)
            before_path, after_path = self._stage_rules(request, workdir)

            cmd = [str(engine), str(target_path), str(before_path), str(after_path), str(request.count)]
            started = time.time()
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=timeout_s,
                    cwd=str(workdir),
                )
            except subprocess.TimeoutExpired as exc:
                raise EngineError(
                    EngineErrorCode.ENGINE_TIMEOUT,
                    f"引擎调用超时（{timeout_s}s），子进程已被强制终止",
                    {
                        "timeout_s": timeout_s,
                        "engine_path": str(engine),
                        "command": cmd,
                        "stdout_tail": _decode(exc.stdout)[-400:],
                        "stderr_tail": _decode(exc.stderr)[-400:],
                    },
                ) from exc
            except PermissionError as exc:
                raise EngineError(
                    EngineErrorCode.ENGINE_NOT_EXECUTABLE,
                    f"引擎文件无法执行: {exc}",
                    {"engine_path": str(engine), "os_error": str(exc)},
                ) from exc
            except OSError as exc:
                raise EngineError(
                    EngineErrorCode.ENGINE_NOT_EXECUTABLE,
                    f"启动引擎失败: {exc.__class__.__name__}: {exc}",
                    {"engine_path": str(engine), "os_error": str(exc)},
                ) from exc
            elapsed = time.time() - started

            stdout = _decode(proc.stdout)
            stderr = _decode(proc.stderr)
            if proc.returncode != 0:
                code = map_engine_stderr(stderr)
                raise EngineError(
                    code,
                    _first_error_line(stderr) or f"引擎以退出码 {proc.returncode} 结束",
                    {
                        "exit_code": proc.returncode,
                        "stderr_tail": stderr[-800:],
                        "stdout_tail": stdout[-400:],
                        "engine_path": str(engine),
                        "command": cmd,
                    },
                )

            reported = parse_engine_stdout(stdout, request.count)
            out_bytes = target_path.read_bytes()

            result = self._deliver_output(request, out_bytes, in_bytes, stdout, engine, elapsed)
            result.rules = len(request.rules)
            result.unique_rules = request.rules.unique_before
            result.count = reported
            return result
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # ---------- 分步实现 ----------

    def _stage_input(self, request: EngineRequest, workdir: Path) -> tuple[Path, bytes]:
        """把待替换文本落到临时工作区，返回 (临时路径, 原始字节)。"""
        if request.input_mode is InputMode.MEMORY:
            raw = (
                request.input_data.encode(request.encoding)
                if isinstance(request.input_data, str)
                else bytes(request.input_data)
            )
            return _write(workdir / "target.txt", raw), raw

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
        return _write(workdir / "target.txt", raw), raw

    def _stage_rules(self, request: EngineRequest, workdir: Path) -> tuple[Path, Path]:
        """把规则写成 Go 引擎要求的两个 JSON 字符串数组文件。"""
        import json

        before = workdir / "before.json"
        after = workdir / "after.json"
        _write(
            before,
            json.dumps(request.rules.before, ensure_ascii=False).encode("utf-8"),
        )
        _write(
            after,
            json.dumps(request.rules.after, ensure_ascii=False).encode("utf-8"),
        )
        return before, after

    def _deliver_output(
        self,
        request: EngineRequest,
        out_bytes: bytes,
        in_bytes: bytes,
        stdout: str,
        engine: Path,
        elapsed: float,
    ) -> EngineResult:
        """按 OutputMode 交付结果，并组装摘要。"""
        text: str | None = None
        if request.output_mode is OutputMode.MEMORY:
            try:
                text = out_bytes.decode(request.encoding)
            except UnicodeDecodeError as exc:
                raise EngineError(
                    EngineErrorCode.ENGINE_OUTPUT_UNEXPECTED,
                    "引擎输出不是合法 UTF-8",
                    {"error": str(exc), "bytes": len(out_bytes)},
                ) from exc
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
        else:  # IN_PLACE
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
            chars_in=_char_len(in_bytes, request.encoding),
            chars_out=_char_len(out_bytes, request.encoding),
            sha256_in=sha256_bytes(in_bytes),
            sha256_out=sha256_bytes(out_bytes),
            rules=len(request.rules),
            unique_rules=request.rules.unique_before,
            count=request.count,
            elapsed_s=elapsed,
            exit_code=0,
            engine_stdout=stdout.strip(),
            engine_path=str(engine),
            changed=in_bytes != out_bytes,
            output_text=text,
        )


def _write(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _decode(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    return raw.decode("utf-8", errors="replace")


def _char_len(raw: bytes, encoding: str) -> int:
    try:
        return len(raw.decode(encoding))
    except UnicodeDecodeError:
        return -1


def _first_error_line(stderr: str) -> str:
    """从 `错误: xxx` 里抽出可读第一行，供 message 使用。"""
    for line in stderr.splitlines():
        line = line.strip()
        if not line:
            continue
        for prefix in ("错误:", "错误："):
            if line.startswith(prefix):
                return line[len(prefix) :].strip()
        return line
    return ""
