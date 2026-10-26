"""T0.3 · Go 引擎集成层单测公共夹具。

要点：
1. 引擎二进制按需离线构建（本仓库 src/fixtext/engine/go_src/），构建失败则相关用例 skip，
   不把「没构建」伪装成「通过」；
2. 大文件用例（20MB 级）打 `slow` 标记，CI 默认也跑——它们才是逐字节一致性的真实证据；
3. 所有用例都在临时目录内作业，不碰仓库与用户文件。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="session")
def engine_bin() -> Path:
    """确保当前主机的引擎二进制存在，返回其路径。"""
    from fixtext.engine.builder import ensure_engine

    try:
        return ensure_engine()
    except Exception as exc:  # noqa: BLE001 - 构建不可用时让用例显式 skip
        pytest.skip(f"Go 引擎不可用：{exc}")


@pytest.fixture(scope="session")
def go_client(engine_bin: Path):
    from fixtext.engine import GoEngineClient

    return GoEngineClient(engine_bin)


@pytest.fixture(scope="session")
def t02_rules_dir() -> Path:
    """T0.2 词库产物里的替换规则目录（可用环境变量覆盖，供其它机器跑）。"""
    env = os.environ.get("FIXTEXT_T02_RULES_DIR")
    if env:
        return Path(env)
    candidate = Path(__file__).resolve().parent / "fixtures" / "rules"
    return candidate


@pytest.fixture(scope="session")
def small_rules() -> tuple[list[str], list[str]]:
    """小规则集：覆盖中文、多字节、重叠、首字符共用等典型形态。"""
    before = ["的地得", "翻的", "轻轻", "ＡＢ", "某甲"]
    after = ["X", "翻得", "轻", "AB", "某乙"]
    return before, after
