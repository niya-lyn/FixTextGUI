#!/usr/bin/env python3
"""Rebuild FixText delivery-full-history repo (segment A zip snapshots + segment B graft)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CODE = REPO.parent
M5 = CODE / "FixText_M5-EX.1_运行模式优化_源码"
LIST_A = Path(__file__).resolve().parent / "delivery_segment_a.json"
T25 = "2b6640c"
KEEP_ROOT = {".git", "tools", "README.md", ".gitignore"}


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd, cwd=str(cwd or REPO), check=check, text=True,
        capture_output=True,
    )


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = run(["git", *args], check=check)
    if p.stdout:
        sys.stdout.write(p.stdout)
        if not p.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if p.returncode != 0 and p.stderr:
        sys.stderr.write(p.stderr)
    return p


def ensure_gitignore() -> None:
    gi = REPO / ".gitignore"
    text = (
        ".venv/\n__pycache__/\n*.pyc\n.idea/\n.pytest_cache/\n"
        "workspace/\nruns/\nlogs/\n_tmp_extract/\n"
    )
    gi.write_text(text, encoding="utf-8")


def content_root(extract_dir: Path) -> Path:
    kids = [p for p in extract_dir.iterdir() if p.name not in (".DS_Store", "__MACOSX")]
    if len(kids) == 1 and kids[0].is_dir():
        return kids[0]
    return extract_dir


def clear_worktree_for_replace() -> None:
    for p in REPO.iterdir():
        if p.name in KEEP_ROOT:
            continue
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()


def copy_tree(src: Path, dst: Path) -> None:
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in (".git", "__MACOSX")]
        rel = Path(root).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            if f.startswith("._"):
                continue
            shutil.copy2(Path(root) / f, target_dir / f)


def apply_zip(zip_path: Path, mode: str) -> None:
    with tempfile.TemporaryDirectory(prefix="ft_deliv_") as tmp:
        tmp_p = Path(tmp)
        print(f"extract {zip_path.name} ...", flush=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_p)
        root = content_root(tmp_p)
        if mode == "replace":
            clear_worktree_for_replace()
            copy_tree(root, REPO)
        elif mode == "overlay":
            copy_tree(root, REPO)
        else:
            raise SystemExit(f"unknown mode: {mode}")


def commit_all(message: str) -> None:
    ensure_gitignore()
    git("add", "-A")
    st = git("status", "--porcelain")
    if not (st.stdout or "").strip():
        marker = REPO / "tools" / "_delivery_markers.txt"
        with marker.open("a", encoding="utf-8") as f:
            f.write(message + "\n")
        git("add", "-A")
    git("commit", "-m", message)


def segment_a_done() -> bool:
    p = run(["git", "rev-parse", "--verify", "HEAD"], check=False)
    if p.returncode != 0:
        return False
    log = git("log", "--oneline", "--reverse").stdout or ""
    return "T0.1:" in log and "M2-T2.4:" in log


def segment_a() -> None:
    ensure_gitignore()
    items = json.loads(LIST_A.read_text(encoding="utf-8"))
    for it in items:
        zpath = CODE / it["zip"]
        if not zpath.is_file():
            raise SystemExit(f"missing zip: {zpath}")
        print(f"=== {it['id']} ({it['mode']}) {zpath.name} ===", flush=True)
        apply_zip(zpath, it["mode"])
        commit_all(it["message"])
    print("SEGMENT_A_DONE", flush=True)
    git("log", "--oneline", "--reverse")


def backup_meta(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if (REPO / "tools").exists():
        if (dest / "tools").exists():
            shutil.rmtree(dest / "tools")
        shutil.copytree(REPO / "tools", dest / "tools")
    for name in ("README.md", ".gitignore"):
        src = REPO / name
        if src.exists():
            shutil.copy2(src, dest / name)


def restore_meta(src: Path) -> None:
    if (src / "tools").exists():
        if (REPO / "tools").exists():
            shutil.rmtree(REPO / "tools")
        shutil.copytree(src / "tools", REPO / "tools")
    for name in ("README.md", ".gitignore"):
        s = src / name
        if s.exists():
            shutil.copy2(s, REPO / name)


def make_anchor(tip_a: str, meta_backup: Path) -> str:
    """Create commit with tree of T25, parent tip_a; reset master to it."""
    tree = git("rev-parse", f"{T25}^{{tree}}").stdout.strip()
    newc = subprocess.check_output(
        [
            "git", "commit-tree", tree, "-p", tip_a,
            "-m", "M2-T2.5 baseline: 四卡集成合并版（锚点树自 2b6640c）",
        ],
        cwd=str(REPO), text=True,
    ).strip()
    git("reset", "--hard", newc)
    restore_meta(meta_backup)
    ensure_gitignore()
    git("add", "-A")
    st = git("status", "--porcelain").stdout or ""
    if st.strip():
        git("commit", "-m", "chore: 保留交付全历史 README/工具与 gitignore")
    return git("rev-parse", "HEAD").stdout.strip()


def fallback_replay(anchor: str) -> None:
    git("checkout", "-B", "master", anchor)
    out = subprocess.check_output(
        ["git", "rev-list", "--reverse", f"{T25}..m5/master"],
        cwd=str(REPO), text=True,
    )
    commits = [c.strip() for c in out.splitlines() if c.strip()]
    for c in commits:
        parents = subprocess.check_output(
            ["git", "rev-list", "--parents", "-n", "1", c],
            cwd=str(REPO), text=True,
        ).split()
        ps = parents[1:]
        msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B", c],
            cwd=str(REPO), text=True,
        )
        subject = msg.splitlines()[0] if msg.strip() else c
        if len(ps) > 1:
            print(f"MERGE tree-snap {c[:8]} {subject[:70]}", flush=True)
            tree = subprocess.check_output(
                ["git", "rev-parse", f"{c}^{{tree}}"],
                cwd=str(REPO), text=True,
            ).strip()
            head = git("rev-parse", "HEAD").stdout.strip()
            newc = subprocess.check_output(
                ["git", "commit-tree", tree, "-p", head, "-p", ps[1], "-m", msg],
                cwd=str(REPO), text=True,
            ).strip()
            git("reset", "--hard", newc)
            continue
        r = run(["git", "cherry-pick", c], check=False)
        if r.returncode == 0:
            continue
        print(f"cherry-pick fail {c[:8]}; commit-tree fallback", flush=True)
        run(["git", "cherry-pick", "--abort"], check=False)
        tree = subprocess.check_output(
            ["git", "rev-parse", f"{c}^{{tree}}"],
            cwd=str(REPO), text=True,
        ).strip()
        head = git("rev-parse", "HEAD").stdout.strip()
        newc = subprocess.check_output(
            ["git", "commit-tree", tree, "-p", head, "-m", msg],
            cwd=str(REPO), text=True,
        ).strip()
        git("reset", "--hard", newc)


def segment_b() -> None:
    if not (M5 / ".git").exists():
        raise SystemExit(f"M5 worktree missing: {M5}")
    remotes = (git("remote").stdout or "").split()
    if "m5" not in remotes:
        git("remote", "add", "m5", str(M5))
    else:
        git("remote", "set-url", "m5", str(M5))
    git("fetch", "m5")

    tip_a = git("rev-parse", "HEAD").stdout.strip()
    print(f"A tip={tip_a}", flush=True)
    run(["git", "cat-file", "-t", T25], check=True)

    with tempfile.TemporaryDirectory(prefix="ft_meta_") as meta_tmp:
        meta_backup = Path(meta_tmp)
        backup_meta(meta_backup)
        # also keep a durable copy under CODE in case process restarts mid-rebase
        durable = CODE / "_tmp" / "_delivery_meta_backup"
        if durable.exists():
            shutil.rmtree(durable)
        backup_meta(durable)

        anchor = make_anchor(tip_a, meta_backup)
        print(f"anchor={anchor}", flush=True)

        r = run(
            ["git", "rebase", "--rebase-merges", "--onto", anchor, T25, "m5/master"],
            check=False,
        )
        if r.returncode != 0:
            print("REBASE_FAILED — fallback replay", flush=True)
            if r.stderr:
                sys.stderr.write(r.stderr)
            run(["git", "rebase", "--abort"], check=False)
            # restore tools before long fallback
            restore_meta(durable)
            fallback_replay(anchor)
            restore_meta(durable)
            git("add", "-A")
            st = git("status", "--porcelain").stdout or ""
            if st.strip():
                git("commit", "-m", "chore: 嫁接后恢复交付全历史工具")
        else:
            cur = git("rev-parse", "HEAD").stdout.strip()
            git("checkout", "-B", "master", cur)
            restore_meta(durable)
            git("add", "-A")
            st = git("status", "--porcelain").stdout or ""
            if st.strip():
                git("commit", "-m", "chore: 嫁接后恢复交付全历史工具")

    print("SEGMENT_B_DONE", flush=True)
    git("log", "--oneline", "--reverse")
    print("--- merges ---", flush=True)
    git("log", "--merges", "--oneline")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment", choices=["a", "b", "all"], default="all")
    args = ap.parse_args()
    os.chdir(REPO)
    # identity for commits
    run(["git", "config", "user.email", "fixtext-delivery@local"], check=False)
    run(["git", "config", "user.name", "FixText Delivery History"], check=False)

    if args.segment in ("a", "all"):
        if segment_a_done():
            print("segment A already present, skipping", flush=True)
        else:
            segment_a()
    if args.segment in ("b", "all"):
        segment_b()


if __name__ == "__main__":
    main()
