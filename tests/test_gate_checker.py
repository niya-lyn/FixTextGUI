"""门禁脚本自身的行为测试：确保禁用项真能被拦住（而不是永远返回通过）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "fixtext_check_gates", PROJECT_ROOT / "scripts" / "check_gates.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # 必须先注册到 sys.modules，dataclass 解析依赖 cls.__module__ 可查
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gates = _load_module()


def test_clean_tree_passes() -> None:
    assert gates.run(PROJECT_ROOT) == 0


def test_detects_flashtext_import(tmp_path: Path) -> None:
    target = tmp_path / "bad_engine.py"
    target.write_text("from flashtext import KeywordProcessor\n", encoding="utf-8")
    violations = gates.check_forbidden_dependencies(tmp_path)
    assert len(violations) == 1
    assert violations[0].rule == "forbidden-dep"


def test_detects_iter_long_usage(tmp_path: Path) -> None:
    target = tmp_path / "bad_matcher.py"
    target.write_text(
        "import ahocorasick\n"
        "\n"
        "def walk(automaton, text):\n"
        "    for end_index, value in automaton.iter_long(text):\n"
        "        yield end_index, value\n",
        encoding="utf-8",
    )
    violations = gates.check_forbidden_dependencies(tmp_path)
    assert [v.rule for v in violations] == ["forbidden-api"]
    assert violations[0].line == 4


def test_comment_mention_is_not_violation(tmp_path: Path) -> None:
    target = tmp_path / "doc_only.py"
    target.write_text("# 禁止使用 flashtext 与 iter_long，见评审门禁\nVALUE = 1\n", encoding="utf-8")
    assert gates.check_forbidden_dependencies(tmp_path) == []


def test_iter_short_is_allowed(tmp_path: Path) -> None:
    target = tmp_path / "ok_matcher.py"
    target.write_text(
        "import ahocorasick\n"
        "\n"
        "def walk(automaton, text):\n"
        "    for end_index, value in automaton.iter(text):\n"
        "        yield end_index, value\n",
        encoding="utf-8",
    )
    assert gates.check_forbidden_dependencies(tmp_path) == []


def test_detects_gui_import_in_core_layer(tmp_path: Path) -> None:
    layer = tmp_path / "src" / "fixtext" / "core"
    layer.mkdir(parents=True)
    (layer / "leaky.py").write_text("from PySide6.QtCore import QObject\n", encoding="utf-8")
    violations = gates.check_layer_boundaries(tmp_path)
    assert len(violations) == 1
    assert violations[0].rule == "layer-boundary"
