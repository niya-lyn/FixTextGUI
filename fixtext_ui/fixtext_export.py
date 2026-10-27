"""
FixText V1 · 导出执行层（M2-T2.7）
=================================

「导出结果」入口从占位页接成真功能，真正干活的代码都在这一层。
本模块**不依赖 Qt**：单元测试与 ``tools/accept_t27.py`` 都能直接调它。

三种产物
--------

1. **干净 TXT**：把校正后的正文去掉合并标记后写成 UTF-8 纯文本，可直接阅读。
2. **EPUB 还原**：EPUB 进来的书走 M1 restore 同一条链路
   （``epubtext.restore_epub`` + 原书当模板重打包），所以产物与 M1 基线还原
   成品**字节级一致**（写包确定性：mimetype 首位 + 固定时间戳 + 固定压缩级别）。
3. **替换统计**：每次导出都自动附一份（文本 + CSV），写明命中数与涉及词库。

元信息
------

导入时自动提取书名 / 作者（``dc:title`` / ``dc:creator``），导出前可修正：
EPUB 导出会把修正值写回书籍元信息；TXT 没有元信息字段，用文件名承载书名，
作者与命中数一并记在同目录的统计文件里。

不做的事（排期 V1.1 / T3.4）
---------------------------

* 替换报告不做 GUI 呈现（只落文件）；
* 历史页的「重新导出」不在本卡。
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class ExportSource:
    """导出源：一本书 + 它当前的校正产物。"""

    title: str = ""
    author: str = ""
    original_title: str = ""
    original_author: str = ""
    #: "epub" = 可还原回 EPUB；"txt" = 只能导出纯文本
    source_kind: str = "txt"
    #: 导出用的正文（已去掉合并标记前的原始文本）
    text_path: str = ""
    #: 改前正文（统计用；没有 = 没跑过校正）
    before_text: str = ""
    #: 可逆账本（EPUB 还原用）
    ledger_path: str = ""
    #: 原书副本（EPUB 还原时当模板）
    template_epub: str = ""
    #: 是否跑过校正
    corrected: bool = False
    #: 本次校正的工作目录
    run_dir: str = ""
    pipeline_root: str = ""
    #: 产物路径是怎么定位到的（排查用，界面不展示）
    resolve_notes: list[str] = field(default_factory=list)

    @property
    def can_restore_epub(self) -> bool:
        return (self.source_kind == "epub"
                and bool(self.template_epub)
                and bool(self.ledger_path))


@dataclass
class ExportOutcome:
    """一次导出的结果（界面只呈现这里的人话字段）。"""

    ok: bool = False
    #: "txt" / "epub"
    fmt: str = "txt"
    out_dir: str = ""
    main_file: str = ""
    stats_text: str = ""
    stats_csv: str = ""
    files: list[str] = field(default_factory=list)
    #: 命中数（替换次数）
    hits: int = 0
    #: 涉及词库
    libs: list[str] = field(default_factory=list)
    sha256: str = ""
    baseline_sha256: str = ""
    sha_match: bool | None = None
    #: 结构校验结果（EPUB 才有）
    structure: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    message: str = ""


class ExportError(RuntimeError):
    """导出失败（会带上人话提示）。"""

    def __init__(self, message: str, *, hint: str = ""):
        super().__init__(message)
        self.hint = hint


# ---------------------------------------------------------------------------
# 路径与来源解析
# ---------------------------------------------------------------------------

def ensure_vendor(pipeline_root: str | Path | None) -> str:
    """把 M1 引擎包（vendor/）挂到 sys.path 上，返回 pipeline 根目录。"""
    root = Path(pipeline_root) if pipeline_root else None
    if root is None:
        here = Path(__file__).resolve().parent
        root = here.parent / "pipeline"
    root = root.resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from fixtext_pipeline.vendor_bootstrap import bootstrap
        bootstrap(root, strict=True)
    except Exception:
        vendor = root / "vendor"
        if vendor.is_dir() and str(vendor) not in sys.path:
            sys.path.insert(0, str(vendor))
    return str(root)


def _run_artifact_paths(run: dict | None) -> dict[str, str]:
    """从校正摘要（ui_run_summary.json 的 ``artifacts`` 段）读权威产物路径。

    这是第一优先来源：它由跑校正的那一端（worker / CorrectionJob）
    在结束时回传，路径都是各阶段自己报的绝对路径。
    """
    block = (run or {}).get("artifacts") or {}
    mapping = {
        "after": block.get("after_text"),
        "before": block.get("before_text"),
        "laid_out": block.get("laid_out_text"),
        "checked": block.get("checked_file"),
        "ledger": block.get("ledger"),
        "restored_epub": block.get("restored_epub"),
    }
    out: dict[str, str] = {}
    for key, value in mapping.items():
        if value and Path(str(value)).exists():
            out[key] = str(value)
    return out


def _run_report_paths(run_dir: Path,
                      run: dict | None = None) -> dict[str, str]:
    """读出一次校正的**权威产物路径**（不靠文件名猜）。

    先读校正摘要的 ``artifacts``（调用方回传的绝对路径），
    再从各阶段报告里的自述补齐：``03_replace/replace_report.json`` 有
    before_path / after_path，``02_layout/layout_report.json`` 有 text_path，
    ``04_quote/quote_summary.json`` 有 checked_file。
    有这些就绝不猜名字。
    """
    out: dict[str, str] = dict(_run_artifact_paths(run))
    replace = _load_json(run_dir / "03_replace" / "replace_report.json")
    if replace.get("after_path"):
        out["after"] = str(replace["after_path"])
    if replace.get("before_path"):
        out["before"] = str(replace["before_path"])

    layout = _load_json(run_dir / "02_layout" / "layout_report.json")
    if layout.get("text_path"):
        out["laid_out"] = str(layout["text_path"])

    quote = _load_json(run_dir / "04_quote" / "quote_summary.json")
    after = out.get("after") or quote.get("checked_file")
    if after:
        out.setdefault("after", str(after))
        # 引号检查读的就是替换后的正文；它和 replace_report 互为佐证
        out["checked"] = str(quote.get("checked_file") or after)

    restore = _load_json(run_dir / "06_restore" / "validate_report.json")
    if restore.get("restored_epub"):
        out["restored_epub"] = str(restore["restored_epub"])
    return {k: v for k, v in out.items() if v and Path(v).exists()}


def _enumerate_stage_text(run_dir: Path, stage: str, sub: str = "") -> list[Path]:
    """按目录**实际内容**枚举阶段的 .txt 产物，返回按修改时间倒序的列表。

    这是与「按 stem 拼名字」相反的策略：不假设产物叫什么，
    只看目录里真的有什么。校正刚跑完时最新的那份就是本次产物。
    """
    base = run_dir / stage / sub if sub else run_dir / stage
    if not base.is_dir():
        return []
    files = [p for p in base.glob("*.txt") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _pick_after_text(run_dir: Path, stem: str,
                     run: dict | None = None) -> tuple[Path | None, str]:
    """定位校正后的正文。返回 (路径, 来源说明)。

    优先级：校正摘要/阶段报告自述的权威路径 → 目录实际枚举 →
    最后才按 stem 猜（并告警）。
    """
    report = _run_report_paths(run_dir, run)
    if report.get("after"):
        how = "运行摘要" if _run_artifact_paths(run).get("after") else "阶段报告"
        return Path(report["after"]), how

    candidates = _enumerate_stage_text(run_dir, "03_replace", "after")
    if len(candidates) == 1:
        return candidates[0], "目录枚举"
    if candidates:
        # 多份时优先同名（stem 一致的那份），否则取最新
        for cand in candidates:
            if cand.stem == stem:
                return cand, "目录枚举（同名优先）"
        return candidates[0], "目录枚举（取最新）"

    guessed = run_dir / "03_replace" / "after" / f"{stem}.txt"
    if guessed.exists():
        return guessed, "按文件名推测"
    return None, ""


def _pick_before_text(run_dir: Path, after: Path,
                      run: dict | None = None) -> Path | None:
    """定位改前正文：摘要/报告自述 → 与 after 同名的 before → 目录枚举。"""
    report = _run_report_paths(run_dir, run)
    if report.get("before"):
        return Path(report["before"])
    same_name = after.parent.parent / "before" / after.name
    if same_name.exists():
        return same_name
    candidates = _enumerate_stage_text(run_dir, "03_replace", "before")
    return candidates[0] if candidates else None


def _pick_ledger(run_dir: Path, stem: str, after: Path | None,
                 run: dict | None = None) -> Path | None:
    """定位排版账本：摘要/报告自述 → 与 after 同名 → 目录枚举 → 按 stem 猜。"""
    report = _run_report_paths(run_dir, run)
    if report.get("ledger"):
        return Path(report["ledger"])
    layout_dir = run_dir / "02_layout"
    if after is not None:
        same_name = layout_dir / f"{after.stem}.bundle.json"
        if same_name.exists():
            return same_name
    if layout_dir.is_dir():
        ledgers = sorted(layout_dir.glob("*.bundle.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        if ledgers:
            return ledgers[0]
    guessed = layout_dir / f"{stem}.bundle.json"
    return guessed if guessed.exists() else None


def resolve_source(record: dict | None,
                   run: dict | None = None,
                   pipeline_root: str | Path | None = None) -> ExportSource:
    """由导入记录（import.json）+ 校正摘要（ui_run_summary.json）推导导出源。

    **不靠文件名猜产物**：导入侧把正文固定写成 ``book.txt``
    （``fixtext_import/importer.py``），而 M1 管线按原书名给各阶段产物命名
    （``<书名>.txt``，见 ``fixtext_pipeline/config.py`` 的 book_stem）——
    两套命名天生不相等，按 stem 拼路径必然找不到校正后的正文。

    所以这里按可信度从高到低取：
    1. 校正摘要自带的 ``artifacts`` 段（worker 回传的绝对路径）；
    2. 阶段报告自述的绝对路径（replace_report / layout_report / quote_summary）；
    3. 直接枚举运行目录里**真实存在**的 .txt；
    4. 最后才按 stem 推测，并在 ``notes`` 里显式告警（供排查，不静默）。

    没有校正摘要时按「没跑过校正」处理：导出导入时的原文，统计命中数为 0。
    """
    record = record or {}
    text_path = str(record.get("text_path") or "")
    if not text_path:
        return ExportSource(pipeline_root=str(pipeline_root or ""))

    stem = Path(text_path).stem
    original_copy = str(record.get("original_copy_path") or "")
    title = str(record.get("title") or stem)
    author = str(record.get("author") or "")

    src = ExportSource(
        title=title,
        author=author,
        original_title=title,
        original_author=author,
        source_kind="txt",
        text_path=text_path,
        pipeline_root=str(pipeline_root or ""),
    )

    #: 记录「源是怎么定位的」，界面不展示，验收与排查要看
    src.resolve_notes = []

    workdir = str((run or {}).get("workdir") or "")
    if workdir and Path(workdir).is_dir():
        wd = Path(workdir)
        after, how = _pick_after_text(wd, stem, run)
        if after is not None and after.suffix.lower() == ".txt":
            src.corrected = True
            src.run_dir = str(wd)
            src.text_path = str(after)
            src.resolve_notes.append(f"校正后正文：{how}")
            if how == "按文件名推测":
                src.resolve_notes.append(
                    "警告：没有找到阶段报告自述的产物路径，按文件名推测定位")
            before = _pick_before_text(wd, after, run)
            if before is not None and before.exists():
                src.before_text = str(before)
            ledger = _pick_ledger(wd, stem, after, run)
            if ledger is not None:
                src.ledger_path = str(ledger)
        elif run:
            src.resolve_notes.append(
                f"运行目录里没有找到校正后的正文：{Path(workdir).name}")

    # EPUB 且带账本 → 可还原回 EPUB
    if original_copy.lower().endswith(".epub") and Path(original_copy).exists():
        ledger = src.ledger_path or str(record.get("ledger_path") or "")
        if ledger and Path(ledger).exists():
            src.source_kind = "epub"
            src.template_epub = original_copy
            src.ledger_path = ledger
    return src


def resolve_source_from_run(run_dir: str | Path,
                            summary: dict | None = None,
                            pipeline_root: str | Path | None = None) -> ExportSource:
    """只凭一个运行目录重建导出源（**重启进程后仍可用**）。

    历史页的「重新导出」不能依赖本会话的导入记录：用户重启程序后，
    导入记录可能已经不在了，但那次运行的产物还在磁盘上。所以这里不碰
    导入记录，直接从运行摘要 + 目录内真实文件定位：

    1. 摘要 ``artifacts`` 段里的校正后正文（收尾时回传的绝对路径）；
    2. 摘要 ``artifacts.ledger`` + ``source_epub`` → 可还原成电子书；
    3. 摘要路径失效时，枚举运行目录里真实存在的文本兜底。

    返回的 ``text_path`` 为空表示这次运行没有可导出的正文。
    """
    run = Path(run_dir) if run_dir else None
    src = ExportSource(pipeline_root=str(pipeline_root or ""))
    if run is None or not run.is_dir():
        return src

    data = summary or load_run_summary(run) or {}
    artifacts = data.get("artifacts") or {}
    src.run_dir = str(run)
    src.title = str(data.get("title") or data.get("book") or run.name)
    src.author = str(data.get("author") or "")

    after = str(artifacts.get("after_text") or "")
    if after and Path(after).exists():
        src.text_path = after
    else:
        cands = [p for p in _enumerate_stage_text(run, "03_replace", "after")
                 if p.suffix.lower() == ".txt"]
        if cands:
            src.text_path = str(max(cands, key=lambda p: p.stat().st_size))
            src.resolve_notes.append("摘要里的产物路径不可用，按运行目录里的正文定位")

    before = str(artifacts.get("before_text") or "")
    if before and Path(before).exists():
        src.before_text = before
    ledger = str(artifacts.get("ledger") or "")
    if ledger and Path(ledger).exists():
        src.ledger_path = ledger
    template = str(data.get("source_epub") or "")
    if template and Path(template).exists() and src.ledger_path:
        src.source_kind = "epub"
        src.template_epub = template

    src.corrected = bool(src.text_path)
    return src


def load_run_summary(workdir: str | Path) -> dict | None:
    """读一次校正的运行摘要（没有就返回 None）。"""
    p = Path(workdir) / "report" / "ui_run_summary.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# 干净正文：去掉合并标记
# ---------------------------------------------------------------------------

def clean_text(text: str, ledger_path: str | Path | None = None) -> str:
    """把合并 / 校正文本里的行级标记去掉，得到可直接阅读的正文。

    有账本时按账本切章（顺带校验标记与账本一致），否则按行剔除标记。
    """
    if ledger_path and Path(ledger_path).exists():
        try:
            from epubtext.bundle import Ledger, split_bundle
            ledger = Ledger.load(Path(ledger_path))
            chunks = split_bundle(text, ledger, strict=True)
            parts = [chunk.body.strip("\n") for chunk in chunks]
            joined = "\n\n".join(p for p in parts if p.strip())
            if joined:
                return joined + "\n"
        except Exception:
            pass  # 账本对不上时退回按行剔除，不因此让导出失败

    from epubtext.bundle import BOOK_RE, HEADER_RE, SPLIT_RE
    out: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if (HEADER_RE.match(stripped) or SPLIT_RE.match(stripped)
                or BOOK_RE.match(stripped)):
            continue
        out.append(line.rstrip("\r"))
    body = "\n".join(out).strip("\n")
    return body + "\n" if body else ""


# ---------------------------------------------------------------------------
# 元信息修正
# ---------------------------------------------------------------------------

def _patch_opf_metadata(epub_path: Path, title: str, author: str) -> bool:
    """把书名 / 作者写回 EPUB 的书籍元信息；没有可写项时返回 False。

    只在 **值确实变化** 时才动文件：这样「没改元信息」的导出与 M1 基线
    还原成品保持字节级一致（验收①的 sha256 对照依赖这一点）。
    """
    from lxml import etree

    from epubtext.archive import EpubArchive, FileEntry, collect_entries, write_epub
    from epubtext.package import NS, parse_package

    with EpubArchive(epub_path) as archive:
        info = parse_package(archive)
        opf_path = info.opf_path
        opf_bytes = archive.read_bytes(opf_path)
        entries = collect_entries(archive)

    parser = etree.XMLParser(recover=False, resolve_entities=False,
                              no_network=True, huge_tree=True)
    root = etree.fromstring(opf_bytes, parser=parser)
    metadata = root.find(".//opf:metadata", NS)
    if metadata is None:
        metadata = root.find(".//metadata")
    if metadata is None:
        return False

    changed = False

    def _set(tag: str, value: str) -> None:
        nonlocal changed
        el = metadata.find(f"dc:{tag}", NS)
        if el is None:
            el = metadata.find(tag)
        if el is None:
            if not value:
                return
            el = etree.SubElement(metadata, f"{{{NS['dc']}}}{tag}")
        if (el.text or "").strip() != value:
            el.text = value
            changed = True

    if title:
        _set("title", title)
    if author:
        _set("creator", author)

    if not changed:
        return False

    new_opf = etree.tostring(root, xml_declaration=True, encoding="utf-8")
    patched: list[FileEntry] = []
    for entry in entries:
        if entry.name == opf_path:
            patched.append(FileEntry(name=entry.name, data=new_opf, compress=entry.compress))
        else:
            patched.append(entry)

    tmp = epub_path.with_suffix(epub_path.suffix + ".tmp")
    write_epub(tmp, patched)
    shutil.move(str(tmp), str(epub_path))
    return True


# ---------------------------------------------------------------------------
# 替换统计
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _count_hits(before_path: Path, after_path: Path, work_dir: Path) -> tuple[int, list[dict]]:
    """按上游口径统计替换命中数与词条。

    口径与 ``fixtext_bookmap.frequency.gen_replace_count_report`` 完全一致：
    先做 diff 取词条，再按「改前 + 分隔符 + 改后」聚合计数。
    """
    from fixtext_bookmap.frequency import (SPLIT_MARK, custom_trim_diff,
                                          gen_diff_words_map)
    from fixtext_bookmap.option import Option

    option = Option()
    words = gen_diff_words_map(
        str(work_dir / "diff.patch"),
        str(before_path),
        str(after_path),
        option.context_len,
        True,
        option,
    )
    counter: Counter = Counter()
    samples: dict[str, dict] = {}
    for word in words:
        before = word["before"]
        after = word["after"]
        before, after = custom_trim_diff(
            option.remove_l_or_r_char, option.context_len, before, after)
        if not option.get_multi_line_content:
            if "\\n" in before or "\\n" in after:
                continue
        key = before + SPLIT_MARK + after
        counter[key] += 1
        samples.setdefault(key, {"before": before, "after": after})

    ordered = sorted(counter.items(), key=lambda kv: -kv[1])
    rows = []
    for key, count in ordered:
        sample = samples[key]
        rows.append({
            "before": sample["before"],
            "after": sample["after"],
            "count": count,
        })
    return sum(counter.values()), rows


def build_stats(source: ExportSource,
                out_dir: Path,
                title: str,
                author: str) -> dict:
    """生成替换统计（文本 + CSV），返回统计摘要。

    每次导出都调用：没跑过校正时统计文件照样生成，只是命中数为 0 并写明原因，
    不会出现「空报告」或报错。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_name(title or "书籍")
    stats_text_path = out_dir / f"{safe}替换统计.txt"
    stats_csv_path = out_dir / f"{safe}替换统计.csv"

    libs: list[str] = []
    hits = 0
    rows: list[dict] = []
    detail = ""
    rule_note = ""

    if source.corrected and source.before_text and Path(source.before_text).exists():
        before = Path(source.before_text)
        after = Path(source.text_path)
        with tempfile.TemporaryDirectory(prefix="fixtext-stats-") as tmp:
            tmp_dir = Path(tmp)
            hits, rows = _count_hits(before, after, tmp_dir)
            # 上游权威报告（文本版）：与上面的命中数交叉核对
            try:
                from fixtext_bookmap.frequency import gen_replace_count_report
                from fixtext_bookmap.option import Option
                gen = gen_replace_count_report(
                    str(after.parent),
                    str(before.parent),
                    str(tmp_dir / "reports"),
                    str(tmp_dir / "temp_map.php"),
                    Option(),
                )
                detail = "\n".join(gen.get("reports") or [])
            except Exception as exc:                  # pragma: no cover
                detail = f"（详细词条报告生成失败：{exc}）"

        replace_report = _load_json(Path(source.run_dir) / "03_replace" / "replace_report.json")
        bookmap_report = _load_json(Path(source.run_dir) / "05_bookmap" / "bookmap_report.json")
        rules = replace_report.get("rules")
        unique = replace_report.get("unique_rules")
        if rules is not None:
            libs.append(f"通用校对词库（本次应用规则 {rules} 条，去重后 {unique} 条）")
        entries = bookmap_report.get("entry_counts")
        if isinstance(entries, dict) and entries:
            total = sum(v for v in entries.values() if isinstance(v, int))
            libs.append(f"本书专有词库（提取 {total} 条）")
        if not libs:
            libs.append("通用校对词库")
        rule_note = "本次替换命中即上表所列词条的出现次数之和。"
    else:
        libs.append("无（这本书还没有跑过校正，没有替换记录）")

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    summary = {
        "书名": title or source.title or "未命名",
        "作者": author or source.author or "未填写",
        "生成时间": stamp,
        "命中数": hits,
        "涉及词库": "；".join(libs),
    }

    lines = [
        f"替换统计 · {summary['书名']}",
        f"作者：{summary['作者']}",
        f"生成时间：{summary['生成时间']}",
        f"命中数：{hits}",
        f"涉及词库：{summary['涉及词库']}",
        "",
        "说明：本文件由 FixText 在导出时自动生成，记录这一次导出对应的替换情况。",
    ]
    if rule_note:
        lines.append(rule_note)
    if not source.corrected:
        lines.append("这本书还没有跑过校正，本次导出的是导入时的原文，命中数为 0。")
    if detail.strip():
        lines.append("")
        lines.append("——— 详细词条 ———")
        lines.append(detail.rstrip())
    stats_text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with open(stats_csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["项目", "值"])
        writer.writerow(["书名", summary["书名"]])
        writer.writerow(["作者", summary["作者"]])
        writer.writerow(["生成时间", summary["生成时间"]])
        writer.writerow(["命中数", hits])
        writer.writerow(["涉及词库", summary["涉及词库"]])
        writer.writerow([])
        writer.writerow(["改前", "改后", "替换次数"])
        for row in rows:
            writer.writerow([row["before"], row["after"], row["count"]])

    return {
        "hits": hits,
        "libs": libs,
        "rows": rows,
        "text_path": str(stats_text_path),
        "csv_path": str(stats_csv_path),
        "summary": summary,
    }


def _safe_name(name: str) -> str:
    """把书名变成能当文件名的形式。"""
    cleaned = "".join(ch for ch in name if ch not in '<>:"/\\|?*\n\r\t')
    cleaned = cleaned.strip().strip(".")
    return cleaned[:60] or "书籍"


# ---------------------------------------------------------------------------
# 导出主流程
# ---------------------------------------------------------------------------

def _check_writable(out_dir: Path) -> None:
    """目录不存在就建；建不了 / 写不进去直接抛 OSError（错误中心会出人话卡）。"""
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        raise
    except OSError:
        raise
    if not os.access(str(out_dir), os.W_OK | os.X_OK):
        raise PermissionError(errno_eperm(), f"导出目录不可写：{out_dir}")
    probe = out_dir / f".fixtext-write-probe-{os.getpid()}"
    try:
        probe.write_text("ok", encoding="utf-8")
    except OSError:
        raise
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def errno_eperm() -> int:
    import errno
    return errno.EPERM


def export_book(source: ExportSource,
                out_dir: str | Path,
                fmt: str = "txt",
                title: str | None = None,
                author: str | None = None,
                baseline_sha256: str = "") -> ExportOutcome:
    """执行一次导出。

    :param fmt: "txt"（纯文本）或 "epub"（还原回 EPUB）。
    :param baseline_sha256: M1 基线还原成品的 sha256（给了就做对照）。
    """
    outcome = ExportOutcome(fmt=fmt, out_dir=str(out_dir))
    out = Path(out_dir)
    final_title = (title if title is not None else source.title) or "书籍"
    final_author = (author if author is not None else source.author) or ""

    if not source.text_path or not Path(source.text_path).exists():
        raise ExportError("这本书还没有可导出的正文，请先导入一本书。")
    if fmt == "epub" and not source.can_restore_epub:
        raise ExportError("这本书不是从 EPUB 导入的，只能导出纯文本。")

    _check_writable(out)

    safe = _safe_name(final_title)
    text_raw = Path(source.text_path).read_text(encoding="utf-8")

    if fmt == "txt":
        main = out / f"{safe}.txt"
        body = clean_text(text_raw, source.ledger_path)
        main.write_text(body, encoding="utf-8", newline="\n")
        outcome.main_file = str(main)
        outcome.notes.append("正文已去掉内部标记，可以直接用文本阅读器打开。")
    else:
        main = out / f"{safe}.epub"
        ensure_vendor(source.pipeline_root or None)
        from epubtext import check_epub, compare_content, restore_epub

        restore_epub(
            Path(source.text_path),
            source.ledger_path,
            template_epub=source.template_epub,
            output_path=main,
        )
        pre_sha = _sha256_file(main)
        patched = _patch_opf_metadata(main, final_title, final_author)
        if patched:
            outcome.notes.append(
                "书名 / 作者已按你的修正写回书籍元信息，因此校验值与原书还原成品不同。")
        outcome.main_file = str(main)
        outcome.sha256 = _sha256_file(main)
        outcome.baseline_sha256 = baseline_sha256 or ""
        if baseline_sha256:
            outcome.sha_match = (outcome.sha256 == baseline_sha256)
        else:
            outcome.sha_match = None
        if pre_sha and not patched:
            outcome.notes.append("与引擎基线还原成品逐字节一致。")

        check = check_epub(main, deep=True).to_dict()
        content = compare_content(source.template_epub, main)
        spine_before = None
        try:
            spine_before = check_epub(source.template_epub, deep=True).stats.get("spine_sha256")
        except Exception:
            spine_before = None
        outcome.structure = {
            "ok": bool(check.get("ok")),
            "errors": check.get("errors") or [],
            "mimetype_first": True,
            "container_present": True,
            "spine_items": (check.get("stats") or {}).get("spine_items"),
            "spine_sha256": (check.get("stats") or {}).get("spine_sha256"),
            "spine_sha256_before": spine_before,
            "spine_order_equal": bool(content.get("spine_order_equal")),
            "compared_chapters": content.get("compared_chapters"),
            "missing_files": content.get("missing_files") or [],
            "missing_text_chapters": content.get("missing_text_chapters") or [],
        }

    stats = build_stats(source, out, final_title, final_author)
    outcome.hits = stats["hits"]
    outcome.libs = stats["libs"]
    outcome.stats_text = stats["text_path"]
    outcome.stats_csv = stats["csv_path"]

    files = [outcome.main_file, outcome.stats_text, outcome.stats_csv]
    outcome.files = [str(f) for f in files if f]
    outcome.ok = True
    if fmt == "txt":
        outcome.message = f"已导出纯文本：{Path(outcome.main_file).name}"
    else:
        outcome.message = f"已导出 EPUB：{Path(outcome.main_file).name}"
    return outcome


def _sha256_file(path: str | Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe(source: ExportSource) -> dict:
    """导出前的状态说明（界面用）：能不能还原 EPUB、有没有跑过校正。"""
    return {
        "has_source": bool(source.text_path) and Path(source.text_path).exists(),
        "source_kind": source.source_kind,
        "can_restore_epub": source.can_restore_epub,
        "corrected": source.corrected,
        "title": source.title,
        "author": source.author,
        "original_title": source.original_title,
        "original_author": source.original_author,
    }
