#!/usr/bin/env python3
"""门禁静态检查：把《代码评审门禁》中可机器判定的条目落成脚本。

当前实现两条：
1. 禁用依赖扫描 —— flashtext 不得出现；pyahocorasick 只允许其迭代接口，
   不得使用 iter_long（排期文档 3.5 第 4 条：禁用 flashtext / iter_long）。
2. 结构约定 —— core / engine 层不得导入 PySide6（保证业务逻辑可无界面单测）。

排在脚本外的两条（PHP 闭包单独测试、strictMap 按数据清洗）属于评审人工核对项，
需在 T1.6 / T0.2 的产物上核验，骨架阶段无法判定，故只在门禁文档中登记。

用法：
    python scripts/check_gates.py [--root .]
退出码：0 = 全部通过；1 = 存在违规。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# 禁用库：导入的顶层模块名 -> 原因
FORBIDDEN_MODULES: dict[str, str] = {
    "flashtext": "flashtext 在 P0 验证中 win_rate=0，连排关键字漏替，禁止用作引擎实现",
}

# 禁用 API：(所属顶层模块, 禁用属性, 原因)
FORBIDDEN_APIS: tuple[tuple[str, str, str], ...] = (
    (
        "ahocorasick",
        "iter_long",
        "pyahocorasick.iter_long 失败吞字符（99.03% 窗口），禁止用作引擎实现",
    ),
    (
        "pyahocorasick",
        "iter_long",
        "pyahocorasick.iter_long 失败吞字符（99.03% 窗口），禁止用作引擎实现",
    ),
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
}
NO_QT_LAYERS = ("core", "engine")

_IMPORT_FROM_RE = re.compile(r"^\s*from\s+([\w.]+)\s+import\b")
_IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)")


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


def iter_python_files(root: Path):
    """遍历目录下的 Python 文件，跳过缓存与构建产物。"""
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def imported_roots(text: str) -> set[str]:
    """收集文件中出现过的导入顶层模块名。"""
    roots: set[str] = set()
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _IMPORT_FROM_RE.match(line) or _IMPORT_RE.match(line)
        if match:
            roots.add(match.group(1).split(".")[0])
    return roots


def check_file(path: Path, rel: str) -> list[Violation]:
    """按文件检查禁用依赖与禁用 API 用法。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    roots = imported_roots(text)
    violations: list[Violation] = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue

        for module, reason in FORBIDDEN_MODULES.items():
            if module in roots and re.match(rf"^\s*(?:from|import)\s+{re.escape(module)}\b", line):
                violations.append(Violation(rel, lineno, "forbidden-dep", reason))

        for module, attr, reason in FORBIDDEN_APIS:
            if module not in roots:
                continue
            # 仅当同一文件确实导入了该模块，才判定其迭代接口调用
            if re.search(rf"(?:\b|\.){re.escape(attr)}\s*\(", line) or re.search(
                rf"\.{re.escape(attr)}\b", line
            ):
                violations.append(Violation(rel, lineno, "forbidden-api", reason))

    # 去重（同一行可能同时命中调用式与属性式两条正则）
    unique: dict[tuple[int, str], Violation] = {}
    for item in violations:
        unique.setdefault((item.line, item.rule), item)
    return sorted(unique.values(), key=lambda v: (v.line, v.rule))


def check_forbidden_dependencies(root: Path) -> list[Violation]:
    """扫描禁用库与禁用 API 用法。"""
    violations: list[Violation] = []
    for path in iter_python_files(root):
        violations.extend(check_file(path, str(path.relative_to(root))))
    return violations


def check_layer_boundaries(root: Path) -> list[Violation]:
    """core / engine 层不得导入 GUI 框架，保证可无界面单测。"""
    package_root = root / "src" / "fixtext"
    if not package_root.is_dir():
        return []

    violations: list[Violation] = []
    for layer in NO_QT_LAYERS:
        layer_dir = package_root / layer
        if not layer_dir.is_dir():
            continue
        for path in iter_python_files(layer_dir):
            rel = str(path.relative_to(root))
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if re.match(r"^\s*(?:from|import)\s+PySide6\b", line):
                    violations.append(
                        Violation(
                            rel,
                            lineno,
                            "layer-boundary",
                            f"{layer} 层不得导入 PySide6（业务逻辑须可无界面单测）",
                        )
                    )
    return violations


def run(root: Path) -> int:
    violations = check_forbidden_dependencies(root) + check_layer_boundaries(root)
    if violations:
        print("门禁检查未通过：")
        for violation in violations:
            print("  " + violation.render())
        return 1
    print("门禁检查通过：无禁用依赖（flashtext / iter_long），core/engine 层无 GUI 依赖。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FixText 门禁静态检查")
    parser.add_argument("--root", default=".", help="工程根目录（默认当前目录）")
    args = parser.parse_args(argv)
    return run(Path(args.root).resolve())


if __name__ == "__main__":
    sys.exit(main())
