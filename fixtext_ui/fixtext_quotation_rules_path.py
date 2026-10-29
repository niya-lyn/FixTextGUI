# -*- coding: utf-8 -*-
"""检查页 / 一键校正共用的引号规则文件落点（M4-EX.6-R2/R3）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping


def quotation_rules_path_for(ctx: Mapping[str, Any] | None = None) -> Path:
    """用户区 ``workspace/quotation_fix_rules.json``（与检查页开关同一文件）。"""
    ws = None
    if ctx:
        for key in ("workspace", "workspace_root", "rules_dir"):
            if ctx.get(key):
                ws = Path(str(ctx[key]))
                break
        if ws is None and ctx.get("pipeline_root"):
            ws = Path(str(ctx["pipeline_root"])).parent / "workspace"
    if ws is None:
        try:
            from fixtext_paths import pkg_root
            ws = pkg_root() / "workspace"
        except Exception:
            ws = Path("workspace")

    vendor = None
    if ctx and ctx.get("pipeline_root"):
        vendor = Path(str(ctx["pipeline_root"])) / "vendor"
    if vendor is None or not vendor.is_dir():
        try:
            from fixtext_paths import pkg_root
            vendor = pkg_root() / "pipeline" / "vendor"
        except Exception:
            vendor = Path("pipeline") / "vendor"
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    from fixtext_quotation.rules import default_rules_path

    return default_rules_path(ws)
