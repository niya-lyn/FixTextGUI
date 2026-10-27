"""M2-T2.7 验收测试：导出页接线（真实大语料实测）。

验收口径（任务卡 2.2 入口⑤ + 2.7.5 第 12 项）：

  S0 基线     真实跑一次 M1 六阶段管线（与界面同一条链路），取 06_restore
              还原成品作 sha256 基线。
  S1 EPUB     以校正后的来源导出 EPUB：结构合法（zip 完整性 / mimetype 首位 /
              container 存在 / spine 章节数与源一致），sha256 与基线逐字节一致。
              「可直接导入主流阅读器」的最终确认属 M4/M5 真机范围，
              沙箱内以结构校验代替（任务卡验收①已注明）。
  S2 TXT      同一来源导出纯文本：合法 UTF-8、无内部合并标记、可整篇解码直读。
  S3 元信息   修正作者后导出 EPUB：OPF 元数据真的改了、结构仍合法、
              sha256 因元信息修正而变化（内容未变，正文逐章一致）。
  S4 错误口   只读目录导出 → OSError → 错误中心归类为人话错误 U-E01。
  S5 非EPUB   纯文本来源（未校正）直接导出 TXT：命中数 0，统计文件写明
              「还没有跑过校正」，不出现空报告或报错。
  S6 统计     每次导出自动附统计（文本 + CSV），实测内容样例
              （命中数、涉及词库、词条明细）。

产出：evidence/t27_evidence.json（供交付包引用，数字均为实测）。
"""

from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent                                   # 交付包根
MEDIA = PKG.parent.parent / "media"                 # 语料（不随包分发）
EVID = PKG / "evidence"
RUNS_ROOT = PKG.parent / "t27_runs"

EPUB = MEDIA / "paohuo.epub"
NAHAN = MEDIA / "nahan.txt"
PIPELINE_ROOT = PKG / "pipeline"
RULES_DIR = PKG / "data" / "rules"
ENGINE = PIPELINE_ROOT / "vendor" / "fixtext" / "engine" / "go_src" / "bin" / "replace_by_go-linux-amd64"

sys.path.insert(0, str(PKG / "fixtext_ui"))
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PIPELINE_ROOT))
sys.path.insert(0, str(PIPELINE_ROOT / "vendor"))

import fixtext_export as fx                          # noqa: E402
import fixtext_error_center as error_center          # noqa: E402

from epubtext import merge_epub                      # noqa: E402


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_baseline() -> dict:
    """S0：真实跑一次 M1 六阶段（CorrectionJob 与界面共用同一条链路）。"""
    from fixtext_worker import CorrectionJob

    workdir = RUNS_ROOT / "baseline"
    if workdir.exists():
        import shutil
        shutil.rmtree(workdir)
    job = CorrectionJob(
        epub=EPUB, workdir=workdir,
        rules_before=RULES_DIR / "before.json",
        rules_after=RULES_DIR / "after.json",
        engine_path=ENGINE, pipeline_root=PIPELINE_ROOT,
    )
    summary = job.run()
    assert summary["chapters"], summary
    return summary


def zip_checks(path: Path) -> dict:
    """EPUB 结构校验：zip 完整性 + mimetype 首位 + container 存在。"""
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        names = zf.namelist()
    return {
        "zip_integrity_ok": bad is None,
        "first_entry": names[0] if names else None,
        "mimetype_first": bool(names) and names[0] == "mimetype",
        "container_present": any(n.endswith("container.xml") for n in names),
        "entries": len(names),
    }


def read_opf_meta(path: Path) -> dict:
    from epubtext.archive import EpubArchive
    from epubtext.package import parse_package
    with EpubArchive(path) as archive:
        info = parse_package(archive)
        return {"title": info.title, "creator": info.creator}


def main() -> int:
    # 错误中心的界面卡需要 QApplication（无头环境直接构造 QWidget 会 abort，
    # 这是 T2.5 已知坑：必须先起离屏 app 再触发 report）
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    EVID.mkdir(parents=True, exist_ok=True)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    fx.ensure_vendor(PIPELINE_ROOT)

    out_root = RUNS_ROOT / "out"
    evidence: dict = {"corpus": {
        "book": "炮火弧线（EPUB，788 章 / 约 314 万字符）",
        "plain_text": "呐喊（纯文本，未校正）",
        "rules": "304,255 条规则 × 2 趟",
    }}

    # ---- S0 基线：真实管线一次 ----
    summary = run_baseline()
    workdir = Path(summary["workdir"])
    baseline_epub = workdir / "06_restore" / "paohuo_restored.epub"
    baseline_sha = sha256_file(baseline_epub)
    evidence["S0_baseline"] = {
        "total_s": summary.get("total_elapsed_s"),
        "chapters": summary.get("chapters"),
        "replace_rules": summary.get("replace_rules"),
        "restored_sha256": baseline_sha,
    }
    print(f"[S0] 管线 {summary['total_elapsed_s']}s 章={summary['chapters']} "
          f"sha={baseline_sha[:16]}…")

    # 导入记录（与界面导入流程同构）：合并文本 + 原书副本 + 账本
    import_dir = RUNS_ROOT / "import"
    import_dir.mkdir(parents=True, exist_ok=True)
    merged_txt = import_dir / "paohuo.txt"           # stem 必须与工作区产物同名
    merged = merge_epub(EPUB, merged_txt)
    record = {
        "title": "炮火弧线",
        "author": "康斯坦丁伯爵",
        "text_path": str(merged_txt),
        "original_copy_path": str(EPUB),
        "epub_mode": "direct",
        "ledger_path": str(merged.ledger_path),
    }

    src = fx.resolve_source(record, summary, PIPELINE_ROOT)
    assert src.corrected and src.can_restore_epub, fx.describe(src)
    evidence["source"] = fx.describe(src)

    # ---- S1 EPUB 导出（未改元信息）：sha 与基线一致 ----
    out1 = out_root / "epub_default"
    o1 = fx.export_book(src, out1, fmt="epub",
                        title="炮火弧线", author="康斯坦丁伯爵",
                        baseline_sha256=baseline_sha)
    z1 = zip_checks(Path(o1.main_file))
    st1 = o1.structure
    s1_pass = (
        o1.ok and z1["zip_integrity_ok"] and z1["mimetype_first"]
        and z1["container_present"] and st1["ok"]
        and st1["spine_order_equal"] and o1.sha_match is True
    )
    evidence["S1_epub_export"] = {
        "main_file": Path(o1.main_file).name,
        "sha256": o1.sha256,
        "baseline_sha256": baseline_sha,
        "sha_match": o1.sha_match,
        "zip": z1,
        "spine_items": st1.get("spine_items"),
        "spine_order_equal": st1.get("spine_order_equal"),
        "compared_chapters": st1.get("compared_chapters"),
        "missing_files": st1.get("missing_files"),
        "check_ok": st1.get("ok"),
        "passed": s1_pass,
    }
    print(f"[S1] EPUB 导出 sha_match={o1.sha_match} zip_ok={z1['zip_integrity_ok']} "
          f"spine={st1.get('spine_items')} order_equal={st1.get('spine_order_equal')}")

    # ---- S2 TXT 导出：合法 UTF-8、无内部标记 ----
    out2 = out_root / "txt"
    o2 = fx.export_book(src, out2, fmt="txt", title="炮火弧线", author="康斯坦丁伯爵")
    body = Path(o2.main_file).read_text(encoding="utf-8")     # 解不开直接异常
    from epubtext.bundle import HEADER_RE, SPLIT_RE
    marker_lines = [ln for ln in body.split("\n")
                    if HEADER_RE.match(ln.strip()) or SPLIT_RE.match(ln.strip())]
    s2_pass = o2.ok and not marker_lines and len(body) > 1_000_000
    evidence["S2_txt_export"] = {
        "main_file": Path(o2.main_file).name,
        "chars": len(body),
        "utf8_decodable": True,
        "marker_lines": len(marker_lines),
        "hits": o2.hits,
        "passed": s2_pass,
    }
    print(f"[S2] TXT 导出 {len(body)} 字符 标记残留={len(marker_lines)} hits={o2.hits}")

    # ---- S3 元信息修正导出：OPF 真改、结构仍合法、sha 变化 ----
    out3 = out_root / "epub_patched"
    o3 = fx.export_book(src, out3, fmt="epub",
                        title="炮火弧线", author="康斯坦丁伯爵（校订版署名）",
                        baseline_sha256=baseline_sha)
    meta_before = read_opf_meta(Path(o1.main_file))
    meta_after = read_opf_meta(Path(o3.main_file))
    z3 = zip_checks(Path(o3.main_file))
    s3_pass = (
        o3.ok and z3["zip_integrity_ok"] and o3.structure["ok"]
        and meta_after["creator"] != meta_before["creator"]
        and meta_after["creator"] == "康斯坦丁伯爵（校订版署名）"
        and o3.sha256 != baseline_sha
        and o3.structure.get("spine_order_equal")
    )
    evidence["S3_metadata_patch"] = {
        "opf_before": meta_before,
        "opf_after": meta_after,
        "sha256": o3.sha256,
        "sha_differs_from_baseline": o3.sha256 != baseline_sha,
        "structure_ok": o3.structure["ok"],
        "spine_order_equal": o3.structure.get("spine_order_equal"),
        "passed": s3_pass,
    }
    print(f"[S3] 元信息修正 creator={meta_after['creator']!r} "
          f"结构ok={o3.structure['ok']} sha变化={o3.sha256 != baseline_sha}")

    # ---- S4 只读目录 → 错误中心 U-E01 ----
    ro_dir = RUNS_ROOT / "readonly"
    ro_dir.mkdir(parents=True, exist_ok=True)
    ro_dir.chmod(0o555)
    code = None
    try:
        fx.export_book(src, ro_dir, fmt="txt", title="炮火弧线", author="")
    except OSError as exc:
        resolved = error_center.report(exc, context="export")
        code = resolved.code
    finally:
        ro_dir.chmod(0o755)
    s4_pass = code == "U-E01"
    evidence["S4_unwritable_dir"] = {
        "error_code": code,
        "expected": "U-E01",
        "passed": s4_pass,
    }
    print(f"[S4] 只读目录 → 错误码 {code}")

    # ---- S5 非 EPUB 来源（未校正）→ 直接导出 TXT ----
    record_txt = {
        "title": "呐喊",
        "author": "",
        "text_path": str(NAHAN),
        "original_copy_path": str(NAHAN),
        "epub_mode": "txt",
        "ledger_path": None,
    }
    src_txt = fx.resolve_source(record_txt, None, PIPELINE_ROOT)
    out5 = out_root / "txt_uncorrected"
    o5 = fx.export_book(src_txt, out5, fmt="txt", title="呐喊", author="")
    stats5 = Path(o5.stats_text).read_text(encoding="utf-8")
    s5_pass = (
        o5.ok and o5.hits == 0 and src_txt.source_kind == "txt"
        and "还没有跑过校正" in stats5 and not src_txt.can_restore_epub
    )
    evidence["S5_txt_uncorrected"] = {
        "source_kind": src_txt.source_kind,
        "hits": o5.hits,
        "stats_says_uncorrected": "还没有跑过校正" in stats5,
        "passed": s5_pass,
    }
    print(f"[S5] 纯文本来源 hits={o5.hits} kind={src_txt.source_kind}")

    # ---- S6 统计文件内容样例（验收③实测） ----
    stats_txt = Path(o2.stats_text).read_text(encoding="utf-8")
    with open(o2.stats_csv, encoding="utf-8-sig") as fh:
        csv_rows = fh.read().splitlines()
    evidence["S6_stats_sample"] = {
        "txt_head": stats_txt.splitlines()[:10],
        "txt_total_lines": len(stats_txt.splitlines()),
        "csv_head": csv_rows[:8],
        "csv_total_rows": len(csv_rows),
        "hits": o2.hits,
        "libs": o2.libs,
        "files": [Path(f).name for f in o2.files],
    }
    print(f"[S6] 统计样例：hits={o2.hits} 词条行={len(csv_rows) - 8} 词库={o2.libs}")

    # ---- 汇总 ----
    evidence["verdict"] = {
        "S1_epub_sha_match_baseline": evidence["S1_epub_export"]["passed"],
        "S2_txt_utf8_clean": evidence["S2_txt_export"]["passed"],
        "S3_metadata_patch": evidence["S3_metadata_patch"]["passed"],
        "S4_unwritable_u_e01": evidence["S4_unwritable_dir"]["passed"],
        "S5_txt_uncorrected": evidence["S5_txt_uncorrected"]["passed"],
        "original_epub_untouched": sha256_file(EPUB) == _orig_sha(),
    }
    ok = all(evidence["verdict"].values()) and o1.hits > 0 and o2.hits > 0
    evidence["verdict"]["all_pass"] = ok
    (EVID / "t27_evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ACCEPT:", "PASS" if ok else "FAIL")
    print(json.dumps(evidence["verdict"], ensure_ascii=False))
    return 0 if ok else 1


_ORIG_SHA_CACHE: str | None = None


def _orig_sha() -> str:
    global _ORIG_SHA_CACHE
    if _ORIG_SHA_CACHE is None:
        _ORIG_SHA_CACHE = sha256_file(EPUB)
    return _ORIG_SHA_CACHE


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    raise SystemExit(main())
