"""阶段日志。

每个阶段一个日志文件（``logs/<序号>_<阶段名>.log``），同时把内容回显到终端；
总运行日志写在 ``logs/run.log``。阶段内所有 ``print`` 也会被收进阶段日志，
因此「日志落盘」不依赖各阶段自觉调用 log()。
"""

from __future__ import annotations

import io
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


class _Tee(io.TextIOBase):
    """把写入同时送到多个流。"""

    def __init__(self, *streams: TextIO):
        self._streams = streams

    def write(self, data: str) -> int:  # type: ignore[override]
        for stream in self._streams:
            try:
                stream.write(data)
                stream.flush()
            except (ValueError, OSError):
                pass
        return len(data)

    def flush(self) -> None:  # type: ignore[override]
        for stream in self._streams:
            try:
                stream.flush()
            except (ValueError, OSError):
                pass

    def isatty(self) -> bool:  # type: ignore[override]
        return False


class StageLogger:
    """阶段日志器：``log()`` 写结构化行，``info()`` 写普通文本。"""

    def __init__(self, path: Path, *, echo: bool = True, console: TextIO | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")
        self._echo = echo
        self._console = console if console is not None else sys.stdout

    def log(self, message: str) -> None:
        self._fh.write(message.rstrip("\n") + "\n")
        self._fh.flush()
        if self._echo:
            self._console.write(message.rstrip("\n") + "\n")
            self._console.flush()

    def info(self, message: str) -> None:
        self.log(message)

    def close(self) -> None:
        try:
            self._fh.close()
        except (OSError, ValueError):
            pass

    def __enter__(self) -> "StageLogger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@contextmanager
def capture_output(logger: StageLogger) -> Iterator[None]:
    """把阶段内的 stdout/stderr 收进阶段日志，同时仍然回显到终端。"""
    original_out, original_err = sys.stdout, sys.stderr
    sink = _Tee(logger._fh, logger._console)
    sys.stdout = sink  # type: ignore[assignment]
    sys.stderr = _Tee(logger._fh, original_err)  # type: ignore[assignment]
    try:
        yield
    finally:
        sys.stdout = original_out
        sys.stderr = original_err
