"""阶段基类。

一个阶段 = 一个可独立落盘、可独立续跑的步骤。每个阶段必须实现：

* ``outputs()``   —— 声明本阶段会产出哪些文件（恢复时逐个检查存在性）
* ``fingerprint()`` —— 输入指纹；输入变了就必须重跑
* ``run()``       —— 真正的干活逻辑，返回一个可 JSON 化的报告字典
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import PipelineConfig
from ..logsetup import StageLogger
from ..state import fingerprint


class StageError(RuntimeError):
    """阶段失败：带人类可读原因，编排器据此中止或继续。"""


class Stage:
    """阶段基类。"""

    name: str = ""
    title: str = ""
    depends_on: tuple[str, ...] = ()

    def __init__(self, cfg: PipelineConfig, logger: StageLogger):
        self.cfg = cfg
        self.log = logger

    # ---- 子类实现 ----

    def outputs(self) -> list[Path]:
        raise NotImplementedError

    def fingerprint(self) -> str:
        raise NotImplementedError

    def run(self) -> dict[str, Any]:
        raise NotImplementedError

    # ---- 工具 ----

    def fingerprint_of(self, *parts: str) -> str:
        """把若干输入描述揉成阶段指纹。"""
        return fingerprint([self.name, *parts])

    def ensure_dir(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def relative(self, path: Path) -> str:
        """把绝对路径转成相对工作目录的短路径（日志里好看）。"""
        try:
            return str(Path(path).relative_to(self.cfg.workdir))
        except ValueError:
            return str(path)
