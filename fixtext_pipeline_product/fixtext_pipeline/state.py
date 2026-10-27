"""阶段状态与断点恢复。

``state.json`` 是编排器唯一的续跑依据：

    {
      "version": 1,
      "config": {...},
      "stages": {
        "merge": {
          "status": "done",            # pending / running / done / failed / skipped
          "fingerprint": "sha256:...", # 输入指纹，输入变了就必须重跑
          "started_at": ..., "ended_at": ..., "elapsed_s": 3.21,
          "outputs": ["..."],          # 产物路径，恢复时逐个检查存在性
          "report": {...}              # 阶段自述的结果
        }
      }
    }

恢复规则（``--resume``，默认开）：

* 阶段 ``status == "done"`` 且 **指纹一致** 且 **全部产物仍存在** → 跳过；
* 任一条不满足 → 重跑该阶段（并把下游阶段的产物标记为过期）。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STATE_VERSION = 1


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    """文件 sha256（分块读，避免大文件进内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def fingerprint(parts: list[str]) -> str:
    """把若干字符串揉成一个稳定的指纹。"""
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return "sha256:" + h.hexdigest()


@dataclass
class StageState:
    name: str
    status: str = "pending"
    fingerprint: str = ""
    started_at: float | None = None
    ended_at: float | None = None
    elapsed_s: float | None = None
    outputs: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fingerprint": self.fingerprint,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "elapsed_s": self.elapsed_s,
            "outputs": list(self.outputs),
            "report": self.report,
            "error": self.error,
        }

    @staticmethod
    def from_dict(name: str, raw: dict[str, Any]) -> "StageState":
        return StageState(
            name=name,
            status=str(raw.get("status", "pending")),
            fingerprint=str(raw.get("fingerprint", "")),
            started_at=raw.get("started_at"),
            ended_at=raw.get("ended_at"),
            elapsed_s=raw.get("elapsed_s"),
            outputs=list(raw.get("outputs", [])),
            report=dict(raw.get("report", {})),
            error=str(raw.get("error", "")),
        )


class StateStore:
    """``state.json`` 的读写器。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict[str, Any] = {
            "version": STATE_VERSION,
            "config": {},
            "stages": {},
        }
        self._loaded = False

    def load(self) -> "StateStore":
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data = raw
                    self.data.setdefault("stages", {})
                    self.data.setdefault("config", {})
            except (OSError, json.JSONDecodeError):
                # 状态文件损坏时按「没有状态」处理，不让续跑变成阻塞点
                pass
        self._loaded = True
        return self

    def save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return self.path

    # ---- 阶段状态读写 ----

    def stage(self, name: str) -> StageState:
        raw = self.data.get("stages", {}).get(name)
        if not isinstance(raw, dict):
            return StageState(name=name)
        return StageState.from_dict(name, raw)

    def put_stage(self, state: StageState) -> None:
        self.data.setdefault("stages", {})[state.name] = state.to_dict()

    def mark(self, name: str, **kwargs: Any) -> StageState:
        st = self.stage(name)
        for key, value in kwargs.items():
            setattr(st, key, value)
        self.put_stage(st)
        return st

    def set_config(self, config_dict: dict[str, Any]) -> None:
        self.data["config"] = config_dict
        self.data["updated_at"] = time.time()

    @property
    def config(self) -> dict[str, Any]:
        return dict(self.data.get("config", {}))


def outputs_exist(outputs: list[str]) -> bool:
    """产物是否都还在（断点恢复的必要条件之一）。"""
    return all(Path(p).exists() for p in outputs)
