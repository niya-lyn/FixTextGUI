#!/usr/bin/env python3
"""打包自检入口（M4-T4.1b）：让冻结后的程序自己报出关键事实。

Windows 侧构建完成后，在包目录里执行：

    FixText.exe --self-check

输出全部是人话 + 可核对的键值，不打印内部路径，用来回答四个问题：

1. 程序认的「包根」是不是可执行文件所在的目录（打包后路径解析是否成立）；
2. 出厂词库（``data/rules``）与 Go 替换引擎是否都在、能不能真跑一次替换；
3. 界面样式表在不在；
4. **新用户首次启动会不会看到新手向导**（``opens_on_first_run()``）——
   这条是打包正确性的关键断言：包内若夹带 ``workspace/settings.ini``
   且带 ``wizardSeen=1``，新用户就永远看不到向导。

用 ``FixText.exe --self-check`` 运行；退码 0 = 全部通过。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _pkg_root() -> Path:
    try:
        from fixtext_paths import pkg_root  # noqa: PLC0415

        return Path(pkg_root())
    except Exception:                                   # noqa: BLE001
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return Path(__file__).resolve().parent


def _check_rules(root: Path) -> dict:
    rules = root / "data" / "rules"
    need = ["before.json", "after.json", "builtin_tiers.bin",
            "builtin_marks.json", "builtin_index_meta.json"]
    missing = [n for n in need if not (rules / n).is_file()]
    return {
        "dir": "data/rules",
        "exists": rules.is_dir(),
        "missing": missing,
        "ok": rules.is_dir() and not missing,
    }


def _check_engine(root: Path) -> dict:
    """真跑一次替换：引擎是「就地改文件」的子进程，能跑通才算可用。"""
    try:
        import main_window as mw  # noqa: PLC0415

        # 引擎按平台取：直接复用 T4.1c 的 engine_selector（本卡不另实现）
        eng = mw.MainWindow._pick_engine()
        if eng is None:
            return {"ok": False, "error": "本平台没有可用的替换引擎"}
        exe = Path(eng)
    except Exception as exc:                            # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    info = {
        "name": exe.name,
        "present": exe.is_file(),
        "executable_bit": os.access(str(exe), os.X_OK) if exe.is_file() else False,
        "ok": False,
    }
    if not exe.is_file():
        return info

    import tempfile                                    # noqa: PLC0415

    # 在临时目录里做一次最小替换（引擎会就地改目标文件，不能拿真书试）
    with tempfile.TemporaryDirectory() as td:
        t = Path(td) / "probe.txt"
        b = Path(td) / "before.json"
        a = Path(td) / "after.json"
        t.write_text("甲乙丙\n", encoding="utf-8")
        b.write_text('["甲"]', encoding="utf-8")
        a.write_text('["乙"]', encoding="utf-8")
        try:
            try:
                from fixtext_pipeline.winproc import hidden_kwargs as _hidden
                _win = _hidden()
            except Exception:  # noqa: BLE001
                _win = {}
            proc = subprocess.run(
                [str(exe), str(t), str(b), str(a), "1"],
                capture_output=True, text=True, timeout=60,
                stdin=subprocess.DEVNULL,
                **_win,
            )
            info["probe_rc"] = proc.returncode
            info["probe_msg"] = ((proc.stdout or "") + (proc.stderr or "")).strip()[:200]
            if proc.returncode == 0:
                out = t.read_text(encoding="utf-8")
                info["replaced_ok"] = out.startswith("乙")
                # 通过：跑得起来 + 真的把「甲」换成了「乙」
                info["ok"] = info["replaced_ok"]
        except Exception as exc:                        # noqa: BLE001
            info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _check_wizard(root: Path) -> dict:
    """新用户首次启动会不会看到向导 —— 打包正确性的关键断言。"""
    settings_file = root / "workspace" / "settings.ini"
    carried = settings_file.is_file()
    carried_text = ""
    if carried:
        try:
            carried_text = settings_file.read_text(encoding="utf-8", errors="replace")
        except Exception:                               # noqa: BLE001
            carried_text = ""
    try:
        from first_run_wizard import opens_on_first_run  # noqa: PLC0415

        opens = bool(opens_on_first_run())
        err = None
    except Exception as exc:                            # noqa: BLE001
        opens, err = None, f"{type(exc).__name__}: {exc}"
    return {
        "opens_on_first_run": opens,
        "settings_carried_in_package": carried,
        "settings_snippet": carried_text.strip()[:160],
        "error": err,
        # 通过条件：包内没有夹带用户区设置，且向导判定为「会弹」
        "ok": opens is True and not carried,
    }


def _check_qss(root: Path) -> dict:
    try:
        import main_window as mw  # noqa: PLC0415

        p = Path(mw.QSS_PATH)
        size = p.stat().st_size if p.is_file() else 0
        return {"present": p.is_file(), "bytes": size, "ok": p.is_file() and size > 1000}
    except Exception as exc:                            # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _check_workspace_dir(root: Path) -> dict:
    """包根 workspace/ 目录是否存在——解压后**不该**有（首次启动才生成）。"""
    ws = root / "workspace"
    items: list[str] = []
    if ws.is_dir():
        for p in sorted(ws.rglob("*")):
            items.append(p.relative_to(ws).as_posix())
            if len(items) >= 10:
                break
    return {
        "present": ws.is_dir(),
        "items": items,
        # 允许为空目录（构建脚本不建它；有内容即视为夹带）
        "ok": not items,
    }


def _check_no_py_residue(root: Path) -> dict:
    """包内不该有源码 .py —— 既防泄漏也防「跑的是源码不是冻结产物」。"""
    hits: list[str] = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(("workspace/", "runs/", "logs/")):
            continue
        hits.append(rel)
        if len(hits) >= 10:
            break
    return {"count": len(hits), "sample": hits, "ok": not hits}


def main() -> int:
    root = _pkg_root()
    checks = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "pkg_root": str(root),
        "pkg_root_is_exe_dir": root == Path(sys.executable).resolve().parent,
        "rules": _check_rules(root),
        "engine": _check_engine(root),
        "qss": _check_qss(root),
        "wizard": _check_wizard(root),
        "workspace_dir": _check_workspace_dir(root),
        "no_py_residue": _check_no_py_residue(root),
    }
    ok = (
        checks["frozen"]
        and checks["pkg_root_is_exe_dir"]
        and checks["rules"]["ok"]
        and checks["engine"]["ok"]
        and checks["qss"]["ok"]
        and checks["wizard"]["ok"]
        and checks["workspace_dir"]["ok"]
        and checks["no_py_residue"]["ok"]
    )
    checks["passed"] = bool(ok)
    text = json.dumps(checks, ensure_ascii=False, indent=2)
    # 先落盘再 print（P2-7）：绿色版 console=False 时 stdout 常接不到，
    # 文件才是可靠证据；print 失败不能挡退码。
    argv = sys.argv[1:]
    out_err = ""
    if "--self-check-out" in argv:
        i = argv.index("--self-check-out")
        if i + 1 < len(argv):
            try:
                Path(argv[i + 1]).write_text(text, encoding="utf-8")
            except Exception as exc:                     # noqa: BLE001
                out_err = f"（结果文件写入失败：{type(exc).__name__}: {exc}）"
    try:
        print(text)
        if out_err:
            print(out_err)
    except Exception:                                   # noqa: BLE001
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
