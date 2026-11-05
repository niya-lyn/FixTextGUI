"""V1.1-E9 全量回归 runner：逐文件独立进程 + 进度文件续跑（1 核防 OOM）。

用法：
    python tools/_e9_regress_runner.py            # 续跑（读 progress）
    python tools/_e9_regress_runner.py --fresh    # 清零重跑

单条 bash 调用上限 600s，跑到约 480s 自动退出，再次调用同一脚本续跑。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROGRESS = ROOT / "tools" / "_e9_regress_progress.jsonl"
ENV = dict(os.environ)
ENV.update({
    "QT_QPA_PLATFORM": "offscreen",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    "PYTHONPATH": (
        "/home/gem/.aily/.cli/py312/lib/python3.12/site-packages:"
        f"{ROOT}:{ROOT / 'fixtext_ui'}"),
})


def main() -> int:
    fresh = "--fresh" in sys.argv
    if fresh and PROGRESS.exists():
        PROGRESS.unlink()
    done: set[str] = set()
    if PROGRESS.exists():
        done = {ln.split("\t")[0] for ln in PROGRESS.read_text().splitlines()
                if "\t" in ln}

    files = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    todo = [f for f in files if f not in done]
    print(f"total={len(files)} done={len(done)} todo={len(todo)}", flush=True)

    t0 = time.time()
    failures: list[str] = []
    for name in todo:
        if time.time() - t0 > 480:
            print(f"[time-budget] stop here, resume by re-running", flush=True)
            break
        r = subprocess.run(
            [sys.executable, "-m", "pytest", f"tests/{name}", "-q",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=ROOT, env=ENV, capture_output=True, text=True, timeout=580)
        tail = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
        status = "PASS" if r.returncode == 0 else "FAIL"
        if r.returncode != 0:
            failures.append(name)
            err = (r.stdout + r.stderr).strip()[-2000:]
            print(f"[{status}] {name} :: {tail}\n{err}", flush=True)
        else:
            print(f"[{status}] {name} :: {tail}", flush=True)
        with PROGRESS.open("a", encoding="utf-8") as f:
            f.write(f"{name}\t{status}\t{tail}\n")

    remaining = [f for f in todo if f not in
                 {ln.split("\t")[0] for ln in PROGRESS.read_text().splitlines()
                  if "\t" in ln}]
    print(f"=== finished pass: failures={failures} remaining={len(remaining)}",
          flush=True)
    if remaining:
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
