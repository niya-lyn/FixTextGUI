"""M4-T4.4 只读保护验收：原文件字节一致性自动化校验（含负向对照）。

验收口径（任务卡 §4.6 T4.4 / §2.3「只读保护」）：
    完整跑 导入 → 一键校正 → 导出，前后比对：
      ① 原书文件 sha256 不变
      ② data/rules 两份原件（before.json / after.json）sha256 不变
      ③ 用户区（workspace/vocab/）之外的用户文件不受影响

链路全部走产品自身的执行层（与界面同一批函数，非桩）：
    导入       fixtext_import.importer.import_book
    一键校正   fixtext_worker.CorrectionJob（M1 六阶段真相链路）
    导出       fixtext_export.export_book

负向对照（--negative）：
    在校正完成、导出之前，故意向「用户书所在目录」写入一个探针文件，
    模拟一处越界写路径；脚本必须判定 FAIL 并指认该文件。
    抓不到 = 校验是摆设，本脚本即自证无效。

运行：
    python3.12 tools/accept_t44.py              # 正向，期望 PASS
    python3.12 tools/accept_t44.py --negative   # 负向，期望 FAIL（抓出越界写）
产出：evidence/t44_evidence.json
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
EVID = PKG / "evidence"
RULES = PKG / "data" / "rules"
ENGINE = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin" / "replace_by_go-linux-amd64"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "pipeline"))
sys.path.insert(0, str(PKG / "pipeline" / "vendor"))
sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG / "tests"))

import _public_fixture as PF  # noqa: E402  M5-OS.1：公版 fixture 唯一来源

#: 用户自己的书放在「用户区之外」的独立目录，用它验证原文件不被改
RUN_ROOT = PKG.parent / "t44_runs"
USER_BOOK_DIR = PKG.parent / "t44_userdir"          #: 模拟用户的书籍文件夹（非产品目录）
WS = PKG.parent / "t44_ws"                          #: 导入工作区（<包根> 同级模拟）
export_dir = None


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def manifest(root: Path, skip: tuple[Path, ...] = ()) -> dict[str, str]:
    """目录树的 sha256 清单（用于「不受影响」比对）。"""
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(p == s or s in p.parents for s in skip):
            continue
        if "__pycache__" in p.parts or p.suffix in (".pyc", ".pyo"):
            continue
        out[str(p.relative_to(root))] = sha(p)
    return out


def diff(a: dict[str, str], b: dict[str, str]) -> dict[str, list[str]]:
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
    }


def prepare_book() -> Path:
    """把语料放到「用户自己的文件夹」里——这个目录全程只读，任何新增都算越界。"""
    USER_BOOK_DIR.mkdir(parents=True, exist_ok=True)
    src = PF.EPUB
    if not src.exists():
        src = PKG.parent / "in" / "paohuo.epub"
    dst = USER_BOOK_DIR / "paohuo.epub"
    if not dst.exists():
        shutil.copy2(src, dst)
    return dst


def run_chain(book: Path, negative: bool) -> dict:
    from fixtext_import.importer import ImportOptions, import_book
    from fixtext_worker import CorrectionJob
    import fixtext_export as fx

    ws = WS
    ws.mkdir(parents=True, exist_ok=True)
    runs_root = RUN_ROOT
    runs_root.mkdir(parents=True, exist_ok=True)
    out_dir = PKG.parent / "t44_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    rec: dict = {"book": str(book), "workspace": str(ws), "out_dir": str(out_dir)}

    # ---- 1. 导入 ----
    t0 = time.monotonic()
    res = import_book(book, ws, ImportOptions(epub_mode="direct"))
    rec["import"] = {"book_id": res.book_id, "chapters": res.chapters,
                     "source_unchanged": res.source_unchanged,
                     "sha_before": res.source_sha256_before,
                     "sha_after": res.source_sha256_after,
                     "seconds": round(time.monotonic() - t0, 2)}

    # ---- 2. 一键校正（M1 六阶段，产品同一链路）----
    workdir = runs_root / f"run-{int(time.time() * 1000)}"
    job = CorrectionJob(
        epub=Path(res.original_copy_path), workdir=workdir,
        rules_before=RULES / "before.json", rules_after=RULES / "after.json",
        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
        title=res.title or "示例书稿", author="",
        source_epub=book,
        custom_vocab_path=ws / "vocab" / "custom_vocab.json",
        derived_rules_dir=ws / "vocab" / "derived_rules",
    )
    t0 = time.monotonic()
    summary = job.run()
    rec["correction"] = {"ok": bool(summary), "seconds": round(time.monotonic() - t0, 2),
                         "workdir": str(workdir),
                         "stages": list((summary or {}).get("stage_elapsed", {})),
                         "hits": (summary or {}).get("hits"),
                         "restored": str(Path(summary["workdir"]) / "06_restore"
                                         / "paohuo_restored.epub") if summary else None}

    # ---- 3. 负向对照：故意越界写进「用户书所在目录」----
    if negative:
        probe = USER_BOOK_DIR / "t44_negative_probe.txt"
        probe.write_text("越界写探针：产品代码不应该写到这里\n", encoding="utf-8")
        rec["negative_probe"] = str(probe)

    # ---- 4. 导出 ----
    src = fx.resolve_source_from_run(workdir) if hasattr(fx, "resolve_source_from_run") else None
    if src is None:
        src = fx.resolve_source(rec=None, run=summary, pipeline_root=str(PKG / "pipeline"))
    t0 = time.monotonic()
    outcome = fx.export_book(src, str(out_dir), fmt="txt",
                             title=(summary or {}).get("title") or "示例书稿")
    rec["export"] = {"ok": bool(outcome.ok), "fmt": outcome.fmt,
                     "seconds": round(time.monotonic() - t0, 2),
                     "files": [Path(f).name for f in outcome.files],
                     "hits": outcome.hits}
    return rec


def main() -> int:
    negative = "--negative" in sys.argv
    EVID.mkdir(parents=True, exist_ok=True)
    for d in (RUN_ROOT, WS):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    probe = USER_BOOK_DIR / "t44_negative_probe.txt"
    probe.unlink(missing_ok=True)          # 负向探针每轮清理，保证「新增」可被复现

    book = prepare_book()
    rules = {"before.json": sha(RULES / "before.json"),
             "after.json": sha(RULES / "after.json")}

    #: ③ 用户区之外的用户文件：用户自己的书籍文件夹 + 用户区根以外的包根文件
    user_before = manifest(USER_BOOK_DIR)
    pkg_before = manifest(PKG, skip=(PKG / "workspace", PKG / "runs", PKG / "logs",
                                     PKG / "evidence", PKG / ".git", PKG / "tools",
                                     PKG / "tests"))
    book_sha_before = sha(book)

    rec = run_chain(book, negative)

    book_sha_after = sha(book)
    rules_after = {"before.json": sha(RULES / "before.json"),
                   "after.json": sha(RULES / "after.json")}
    user_after = manifest(USER_BOOK_DIR)
    pkg_after = manifest(PKG, skip=(PKG / "workspace", PKG / "runs", PKG / "logs",
                                    PKG / "evidence", PKG / ".git", PKG / "tools",
                                    PKG / "tests"))

    c1 = book_sha_after == book_sha_before
    c2 = rules_after == rules
    user_diff = {k: v for k, v in diff(user_before, user_after).items() if v}
    pkg_diff = {k: v for k, v in diff(pkg_before, pkg_after).items() if v}
    c3 = not user_diff and not pkg_diff
    checks = {
        "original_book_sha_unchanged": c1,
        "rules_sha_unchanged": c2,
        "user_files_outside_vocab_untouched": c3,
    }
    payload = {
        "generated_by": "tools/accept_t44.py",
        "mode": "negative" if negative else "positive",
        "book_sha": {"before": book_sha_before, "after": book_sha_after},
        "rules_sha": {"before": rules, "after": rules_after},
        "user_area_diff": user_diff,
        "pkg_area_diff": pkg_diff,
        "checks": checks,
        "chain": rec,
        "passed": all(checks.values()),
        #: 负向对照的期望与实得（脚本自证）
        "negative_expectation": ("必须 FAIL 并指认越界文件" if negative
                                 else "必须 PASS"),
        "negative_detected": (bool(user_diff.get("added")) if negative else None),
    }
    out = EVID / ("t44_evidence_negative.json" if negative else "t44_evidence.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"[模式] {'负向对照' if negative else '正向'}")
    print(f"[链路] 导入 {rec['import']['chapters']} 章 / "
          f"校正 {rec['correction']['seconds']}s hits={rec['correction']['hits']} / "
          f"导出 {rec['export']['files']}")
    print(f"① 原书 sha256 不变       : {c1}")
    print(f"② rules 两份原件 sha 不变 : {c2}")
    print(f"③ 用户区之外文件不受影响 : {c3}  user_diff={user_diff} pkg_diff={pkg_diff}")
    if negative:
        print(f"[负向] 期望 FAIL，实得 {'PASS(未抓到=校验无效)' if payload['passed'] else 'FAIL(已抓到)'}")
        print(f"[负向] 抓到的越界文件: {user_diff.get('added')}")
    print("T44:", "PASS" if payload["passed"] else "FAIL", "→", out.name)
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
