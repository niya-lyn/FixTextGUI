"""Go 引擎离线构建。

约束（T0.3 卡硬要求）：
- **全程离线**：显式 `GOPROXY=off`、`GOTOOLCHAIN=local`、`GOFLAGS=-mod=mod`；
  Go 引擎只 import 5 个标准库（encoding/json、fmt、os、strconv、strings），源码包内
  既无 go.mod 也无 go.sum，因此不需要任何外部模块，off 不会导致构建失败。
- **1 核沙箱**：固定 `-p 1`，不用并行编译把内存与 CPU 打满。
- **CGO 关闭**：`CGO_ENABLED=0`，纯 Go 静态产物，Windows 交叉编译不需要 mingw/gcc。

产物放置：默认写到 `engine/go_src/bin/`，文件名带平台后缀，便于同时存在多平台二进制。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import EngineError, EngineErrorCode

GO_SRC_DIR = Path(__file__).resolve().parent / "go_src"
GO_ENTRY = "replace_by_go.go"
BIN_DIR = GO_SRC_DIR / "bin"

# 引擎源码的 import 清单（T0.3a 盘点结论），builder 启动时用它做一次零依赖自检
EXPECTED_STDLIB_IMPORTS = ("encoding/json", "fmt", "os", "strconv", "strings")


@dataclass
class BuildResult:
    ok: bool
    target: str
    output: Path | None
    seconds: float
    command: list[str]
    stdout: str
    stderr: str
    size_bytes: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "target": self.target,
            "output": str(self.output) if self.output else None,
            "seconds": round(self.seconds, 3),
            "command": self.command,
            "stdout_tail": self.stdout[-1500:],
            "stderr_tail": self.stderr[-1500:],
            "size_bytes": self.size_bytes,
        }


def host_target() -> str:
    """当前主机对应的 go 目标串：linux-amd64 / darwin-arm64 / windows-amd64 …"""
    goos = {"win32": "windows", "cygwin": "windows"}.get(sys.platform, sys.platform)
    machine = (os.uname().machine if hasattr(os, "uname") else "amd64") or "amd64"
    goarch = {"x86_64": "amd64", "aarch64": "arm64", "arm64": "arm64", "i386": "386"}.get(machine, "amd64")
    return f"{goos}-{goarch}"


def offline_env(goos: str | None = None, goarch: str | None = None) -> dict[str, str]:
    """离线构建环境：关掉代理、关掉工具链自动下载、关掉 CGO、限制并行度。"""
    env = os.environ.copy()
    env.update(
        {
            "GOPROXY": "off",
            "GOTOOLCHAIN": "local",
            "GOFLAGS": "-mod=mod",
            "CGO_ENABLED": "0",
            "GOWORK": "off",
        }
    )
    if goos:
        env["GOOS"] = goos
    if goarch:
        env["GOARCH"] = goarch
    return env


def check_go_available() -> str:
    """确认 go 工具链在 PATH 上，返回版本串。缺失即 E1001（引擎工具链缺失）。"""
    go = shutil.which("go")
    if not go:
        raise EngineError(
            EngineErrorCode.ENGINE_MISSING,
            "未找到 go 工具链",
            {"path": os.environ.get("PATH", "")},
        )
    proc = subprocess.run([go, "version"], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise EngineError(
            EngineErrorCode.ENGINE_NOT_EXECUTABLE,
            "go version 执行失败",
            {"stderr": proc.stderr[-400:]},
        )
    return proc.stdout.strip()


def check_zero_external_deps() -> list[str]:
    """解析 Go 源码的 import 块，返回实际的 import 路径列表。

    同时确认包内没有 go.sum：有 go.sum 就意味着引入过外部模块，与 T0.3a 结论冲突，
    构建前先拦下来，避免带着预期外的依赖联网。
    """
    source = (GO_SRC_DIR / GO_ENTRY).read_text(encoding="utf-8")
    imports: list[str] = []
    in_block = False
    for raw in source.splitlines():
        line = raw.strip()
        if line.startswith("import ("):
            in_block = True
            continue
        if in_block and line == ")":
            break
        if in_block and line:
            path = line.split('"')[1] if '"' in line else ""
            if path:
                imports.append(path)
        elif line.startswith('import "') and '"' in line[8:]:
            imports.append(line[8:].split('"')[0])

    for extra in ("go.sum", "go.work"):
        if (GO_SRC_DIR / extra).exists():
            raise EngineError(
                EngineErrorCode.ARGUMENT_INVALID,
                f"引擎目录存在 {extra}，与零外网依赖前提冲突，拒绝构建",
                {"file": str(GO_SRC_DIR / extra)},
            )
    third_party = [p for p in imports if "." in p.split("/")[0]]
    if third_party:
        raise EngineError(
            EngineErrorCode.ARGUMENT_INVALID,
            "引擎源码引入了非标准库模块，离线构建前提不成立",
            {"imports": imports, "third_party": third_party},
        )
    return imports


def build(
    *,
    goos: str | None = None,
    goarch: str | None = None,
    output: Path | str | None = None,
    ldflags: str = "",
) -> BuildResult:
    """离线编译 Go 引擎。

    goos/goarch 省略时按当前主机；Windows 交叉编译传 goos="windows"（默认 amd64）。
    """
    check_zero_external_deps()
    go = shutil.which("go")
    if not go:
        raise EngineError(EngineErrorCode.ENGINE_MISSING, "未找到 go 工具链", {})

    target = f"{goos or host_target().split('-')[0]}-{goarch or 'amd64'}"
    suffix = ".exe" if target.startswith("windows") else ""
    out_path = Path(output) if output else BIN_DIR / f"replace_by_go-{target}{suffix}"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [go, "build", "-p", "1", "-trimpath"]
    if ldflags:
        cmd += ["-ldflags", ldflags]
    cmd += ["-o", str(out_path), GO_ENTRY]

    env = offline_env(
        goos or target.split("-")[0],
        goarch or target.split("-")[1],
    )
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(GO_SRC_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    seconds = time.time() - started
    result = BuildResult(
        ok=proc.returncode == 0 and out_path.exists(),
        target=target,
        output=out_path if out_path.exists() else None,
        seconds=seconds,
        command=cmd,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        size_bytes=out_path.stat().st_size if out_path.exists() else 0,
    )
    if not result.ok:
        raise EngineError(
            EngineErrorCode.ENGINE_FAILED,
            "go build 失败",
            result.as_dict(),
        )
    chmod_executable(result.output)
    return result


def chmod_executable(path: Path | None) -> None:
    """非 Windows 目标补执行位。"""
    if path is None or path.suffix == ".exe":
        return
    mode = path.stat().st_mode
    path.chmod(mode | 0o111)


def default_engine_path() -> Path:
    """当前主机对应的默认引擎路径（构建产物）。"""
    suffix = ".exe" if sys.platform.startswith("win") else ""
    return BIN_DIR / f"replace_by_go-{host_target()}{suffix}"


def ensure_engine(*, rebuild: bool = False) -> Path:
    """保证当前主机有可用引擎，返回路径。构建产物缺失时才编译（避免无谓重编译）。"""
    path = default_engine_path()
    if rebuild or not path.exists():
        target = host_target()
        goos, goarch = target.split("-")
        build(goos=goos, goarch=goarch, output=path)
    chmod_executable(path)
    return path


def main(argv: list[str] | None = None) -> int:
    """命令行入口：python -m fixtext.engine.builder [--windows] [--both] [--rebuild]"""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="离线构建 Go 替换引擎")
    parser.add_argument("--windows", action="store_true", help="只交叉编译 Windows 目标")
    parser.add_argument("--both", action="store_true", help="同时编译当前主机与 Windows 目标")
    parser.add_argument("--goarch", default="amd64", help="目标架构（默认 amd64）")
    parser.add_argument("--rebuild", action="store_true", help="强制重编译")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    try:
        print(f"Go 工具链: {check_go_available()}")
        imports = check_zero_external_deps()
        print(f"引擎 import: {len(imports)} 个，全部标准库 -> {imports}")

        targets: list[tuple[str, str]] = []
        if args.both:
            host = host_target().split("-")
            targets = [(host[0], host[1]), ("windows", args.goarch)]
        elif args.windows:
            targets = [("windows", args.goarch)]
        else:
            host = host_target().split("-")
            targets = [(host[0], host[1])]

        results = []
        for goos, goarch in targets:
            res = build(goos=goos, goarch=goarch)
            results.append(res)
            if args.json:
                print(json.dumps(res.as_dict(), ensure_ascii=False))
            else:
                print(f"[OK] {res.target:15s} {res.seconds:6.2f}s {res.size_bytes:>10,} B  -> {res.output}")
        return 0
    except EngineError as exc:
        detail = exc.as_dict()
        print(f"[FAIL] {detail['code']} {detail['message']}", file=sys.stderr)
        if args.json:
            print(json.dumps(detail, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
