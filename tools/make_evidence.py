"""生成验收证据报告（T2.2）

跑真实导入，把所有验收需要的数字落成 JSON + 可读摘要：
- 每条样本的编码识别结果与依据
- TXT / EPUB 的 sha256 三元组对照
- 章节预览清单样本

用法：PYTHONPATH=.:ui_kit:<pyside6> python3 tools/make_evidence.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import fixtext_import as fi  # noqa: E402
from fixtext_import.encoding import probe  # noqa: E402
from fixtext_import.textfile import sha256_file  # noqa: E402

SAMPLES = ROOT / "tests" / "samples"
OUT = ROOT / "evidence"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    manifest = {r["file"]: r for r in
                json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))["samples"]}

    encoding_rows = []
    for name, meta in manifest.items():
        path = SAMPLES / name
        r = probe(path)
        encoding_rows.append({
            "file": name,
            "bytes": path.stat().st_size,
            "expected": meta["expected"],
            "identified": r.codec,
            "label_human": __import__("fixtext_import.messages", fromlist=["m"]).encoding_label(r.codec),
            "confidence": r.confidence,
            "certain": r.certain,
            "has_bom": r.has_bom,
            "pass": r.codec.replace("-sig", "") == meta["expected"],
            "evidence": r.evidence,
            "scores": {k: round(v, 4) for k, v in r.scores.items()},
            "note": meta.get("note", ""),
        })

    tmp = Path(tempfile.mkdtemp(prefix="fixtext_evidence_"))
    imports = []
    try:
        for src_name, epub_mode in (("d_gbk_crlf.txt", "text"),
                                    ("book_paohuo.epub", "direct")):
            src = tmp / src_name
            shutil.copyfile(SAMPLES / src_name, src)
            before = sha256_file(src)
            ws = tmp / f"ws_{src_name}"
            result = fi.import_book(src, ws, fi.ImportOptions(epub_mode=epub_mode))
            imports.append({
                "file": src_name,
                "kind": result.source_suffix,
                "epub_mode": result.epub_mode,
                "sha256_before": result.source_sha256_before,
                "sha256_after": result.source_sha256_after,
                "sha256_workspace_copy": result.workspace_copy_sha256,
                "sha256_now_on_disk": sha256_file(src),
                "all_equal": (result.source_sha256_before == result.source_sha256_after
                              == result.workspace_copy_sha256 == before == sha256_file(src)),
                "encoding": result.encoding_label,
                "encoding_codec": result.encoding_codec,
                "newline_kind": result.newline_kind,
                "newline_changed": result.newline_changed,
                "chapters": result.chapters,
                "text_chars": result.text_chars,
                "text_bytes": result.text_bytes,
                "elapsed_ms": result.elapsed_ms,
                "human_notes": result.human_notes,
            })

        preview = fi.chapter_preview(SAMPLES / "book_paohuo.epub")
        chapters = [{"index": c.index, "title": c.title, "chars": c.chars}
                    for c in preview.chapters[:10]]
        preview_row = {
            "file": "book_paohuo.epub",
            "title": preview.title,
            "chapter_count": len(preview.chapters),
            "order_ok": preview.order_ok,
            "has_toc": preview.has_toc,
            "first_10": chapters,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    report = {
        "task": "M2-T2.2 拖放导入与编码识别",
        "encoding_matrix": encoding_rows,
        "encoding_pass": f"{sum(1 for r in encoding_rows if r['pass'])}/{len(encoding_rows)}",
        "imports": imports,
        "chapter_preview": preview_row,
    }
    (OUT / "evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# M2-T2.2 验收证据", ""]
    lines.append(f"## ① 编码识别矩阵（{report['encoding_pass']} 通过）")
    lines.append("")
    lines.append("| 样本 | 字节 | 期望 | 识别 | 置信度 | 人话说法 | 结果 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in encoding_rows:
        lines.append(
            f"| {r['file']} | {r['bytes']:,} | {r['expected']} | {r['identified']} | "
            f"{r['confidence']} | {r['label_human']} | {'PASS' if r['pass'] else 'FAIL'} |")
    lines.append("")
    lines.append("## ② 原文件 sha256 三元对照")
    lines.append("")
    for r in imports:
        lines.append(f"### {r['file']}（{r['kind']} · {r['epub_mode']}）")
        lines.append("")
        lines.append(f"- 导入前 sha256：`{r['sha256_before']}`")
        lines.append(f"- 导入后 sha256：`{r['sha256_after']}`")
        lines.append(f"- 工作区副本 sha256：`{r['sha256_workspace_copy']}`")
        lines.append(f"- 磁盘复查 sha256：`{r['sha256_now_on_disk']}`")
        lines.append(f"- 四者一致：**{'是' if r['all_equal'] else '否'}**")
        lines.append(f"- 识别：{r['encoding']}（{r['encoding_codec']}）· 换行 {r['newline_kind']}"
                     f" · 共 {r['chapters']} 章 · 正文 {r['text_chars']:,} 字"
                     f" · 耗时 {r['elapsed_ms']} ms")
        lines.append("")
    lines.append("## ③ 章节预览样本")
    lines.append("")
    lines.append(f"- 书名：{preview_row['title']}")
    lines.append(f"- 章节数：{preview_row['chapter_count']}")
    lines.append(f"- 顺序与目录一致：{preview_row['order_ok']}")
    lines.append(f"- 有目录信息：{preview_row['has_toc']}")
    lines.append("")
    for c in preview_row["first_10"]:
        lines.append(f"  - 第 {c['index']} 章　{c['title']}（{c['chars']:,} 字）")
    lines.append("")
    (OUT / "evidence.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"编码通过 {report['encoding_pass']}")
    print("imports all_equal:", [r["all_equal"] for r in imports])
    print("wrote", OUT / "evidence.md")


if __name__ == "__main__":
    main()
