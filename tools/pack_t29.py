"""M2-T2.9 打包工具：把工作树打成可解包即用的 zip。

两件必须做对的事（否则独立质检会复现「执行位丢失 + git status 不干净」）：

1. **执行位进 zip**：`replace_by_go-linux-amd64` 必须记成 100755。Python
   `zipfile` 默认按文件系统当前的 mode 记录，而打包机（FUSE 工作区）上它可能
   只有 644，所以这里按「git 记录的 mode」显式写 `external_attr`。
2. **git status 干净**：有些文件系统（FUSE / 部分网盘挂载）解包时不恢复权限位，
   于是 git 会把 `100755 → 100644` 报成改动。仓库配置里写明 `core.fileMode=false`
   （`.git/config` 随包分发），这样解包后无论权限位是否被恢复，状态都是干净的。

用法：``python3 tools/pack_t29.py <输出.zip>``
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {"__pycache__", "t23_runs", "t27_runs", "runs", "workspace"}


def git_files() -> list[str]:
    """列出应进包的文件及 git 记录的 mode。

    必须用 ``-z``（NUL 分隔）：默认输出会把非 ASCII 路径加引号并转义成
    ``\345\244\250...``，按路径去开文件必然失败，解包后就表现为「文件被删」。
    """
    out = subprocess.run(["git", "ls-files", "-s", "-z"], cwd=PKG,
                         capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.split("\0"):
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        rows.append((path, int(meta.split()[0], 8)))
    # 未跟踪但应当随包分发的新文件（同样用 -z）
    extra = subprocess.run(["git", "ls-files", "-o", "--exclude-standard", "-z"],
                           cwd=PKG, capture_output=True, text=True,
                           check=True).stdout.split("\0")
    seen = {p for p, _ in rows}
    for path in extra:
        if path.strip() and path not in seen:
            rows.append((path, 0o100644))
    return rows


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python3 tools/pack_t29.py <输出.zip>")
        return 2
    out_zip = Path(sys.argv[1]).resolve()
    files = git_files()
    exec_bits = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path, mode in files:
            src = PKG / path
            if not src.is_file():
                continue
            if any(part in EXCLUDE_DIRS for part in Path(path).parts):
                continue
            # 目录条目交给各文件隐式创建；权限位按 git 记录写死
            rel = f"{PKG.name}/{path}"
            info = zipfile.ZipInfo(rel)
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3                     # unix，解包方才会应用 mode
            if mode & 0o111:
                exec_bits += 1
            zf.writestr(info, src.read_bytes())
        # .git 必须随包（客户要能 `git log` 看到小步提交历史）
        git_dir = PKG / ".git"
        if git_dir.is_dir():
            for item in git_dir.rglob("*"):
                if not item.is_file():
                    continue
                rel = f"{PKG.name}/{item.relative_to(PKG).as_posix()}"
                info = zipfile.ZipInfo(rel)
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                zf.writestr(info, item.read_bytes())
    size_mb = out_zip.stat().st_size / (1024 * 1024)
    print(f"打包完成：{out_zip.name}  {len(files)} 条目  {size_mb:.2f} MB  "
          f"带执行位文件 {exec_bits} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
