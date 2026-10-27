#!/usr/bin/env python3
"""打包交付物。

产出两个 zip：

1. ``FixText_M1-T1.1_一键校正编排器_v1.zip`` —— 编排器源码 + vendor 引擎 + 工具 + 测试 + README
2. ``FixText_M1-T1.1_炮火弧线全链路产物_v1.zip`` —— 《炮火弧线》全链路的各阶段产物、
   日志、状态与报告（不含输入原件，词库与原书另行在云盘）

用法::

    python tools/package.py --product-dir product --run-dir runs/paohuo_final --out dist
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

#: 打包时排除的目录名
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git", ".mypy_cache", ".ruff_cache"}
#: 打包时排除的文件名后缀
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".tmp"}


def _should_skip(path: Path) -> bool:
    if path.suffix in EXCLUDE_SUFFIX:
        return True
    return any(part in EXCLUDE_DIRS for part in path.parts)


def add_tree(zf: zipfile.ZipFile, root: Path, arc_prefix: str) -> int:
    """把目录树打进 zip，返回写入的文件数。"""
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _should_skip(rel):
            continue
        zf.write(path, arcname=f"{arc_prefix}/{rel.as_posix()}")
        count += 1
    return count


def build_product_zip(product_dir: Path, out_dir: Path) -> Path:
    out = out_dir / "FixText_M1-T1.1_一键校正编排器_v1.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        n = add_tree(zf, product_dir, "fixtext_pipeline_product")
        # 顶层再放一份 README，方便直接点开看
        readme = product_dir / "README.md"
        if readme.is_file():
            zf.write(readme, arcname="README.md")
    print(f"[product] {out.name}  文件数={n}  体积={out.stat().st_size:,} 字节")
    return out


def build_run_zip(run_dir: Path, out_dir: Path, name: str) -> Path:
    out = out_dir / name
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        n = add_tree(zf, run_dir, "run")
    print(f"[run]     {out.name}  文件数={n}  体积={out.stat().st_size:,} 字节")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--product-dir", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--run-name", default="FixText_M1-T1.1_炮火弧线全链路产物_v1.zip")
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()

    out_dir = Path(args.out)
    build_product_zip(Path(args.product_dir), out_dir)
    build_run_zip(Path(args.run_dir), out_dir, args.run_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
