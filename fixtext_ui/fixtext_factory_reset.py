"""软件初始化（M5-EX.6）：强制清理运行产物，回到刚装好时的空状态。

清理范围（只动用户区 / 运行产物，不动源码、引擎、出厂词库 ``data/rules``）：

* ``workspace/`` 下全部内容（已导入的书、词库工作副本、settings.ini）
* ``runs/`` 校正与历史运行目录
* ``logs/`` 诊断日志
* ``导出/`` 包根默认导出目录里的成品

设置文件（含 ``FIXTEXT_SETTINGS_FILE`` 覆盖）一并清空，使引擎 / 日志路径 /
向导「已看过」等全部回到默认。
"""

from __future__ import annotations

import shutil
from pathlib import Path


def _wipe_dir_contents(root: Path) -> bool:
    """删掉目录内所有子项；目录本身保留（不存在则创建）。返回是否动过。"""
    root = Path(root)
    touched = False
    if root.exists():
        for child in list(root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=False)
            else:
                child.unlink(missing_ok=True)
            touched = True
    root.mkdir(parents=True, exist_ok=True)
    return touched


def reset_settings_file() -> Path:
    """清空并删除用户区设置文件，返回其路径。"""
    import fixtext_settings as settings

    path = settings.settings_path()
    try:
        s = settings.AppSettings()
        s.clear()
        s.sync()
    except Exception:  # noqa: BLE001
        pass
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def reset_all_products(*, workspace: Path, pkg_root: Path) -> list[str]:
    """执行磁盘清理，返回已处理位置的人话列表（供界面提示）。"""
    workspace = Path(workspace)
    pkg_root = Path(pkg_root)
    done: list[str] = []

    if _wipe_dir_contents(workspace):
        done.append(f"工作区（{workspace}）")
    else:
        workspace.mkdir(parents=True, exist_ok=True)
        done.append(f"工作区（{workspace}，已就绪）")

    for name, label in (
        ("runs", "校正与历史记录"),
        ("logs", "诊断日志"),
        ("导出", "导出成品"),
    ):
        target = pkg_root / name
        _wipe_dir_contents(target)
        done.append(f"{label}（{target}）")

    settings_path = reset_settings_file()
    done.append(f"设置（{settings_path}）")
    return done


__all__ = ["reset_all_products", "reset_settings_file", "_wipe_dir_contents"]
