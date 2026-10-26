#!/usr/bin/env python3
"""T0.4 回归基线集 · 语料构建脚本（确定性）

作用：把云盘上的原始文件按固定规则加工成「回归基线语料」，并产出可追溯的
语料清单（文件名 / 大小 / sha256 / 出处路径 / 加工方式）。

来源（全部来自飞书云盘 projects/fix_text，本脚本不做任何外网下载）：
  - projects/fix_text/语料/    12 本 Gutenberg 中文公版书（繁体）
  - projects/fix_text/txt/     3 部真实简体小说（雀魂 / 鬼灭之刃 / 反派少爷）

用法：
    python build_corpus.py --source-dir <原始文件目录> --out-dir <语料输出目录>

    --source-dir 里应放置按云盘原名保存的原始文件（见 SOURCES 表的 source_file）。

加工规则（确定性，同一输入永远产出同一输出）：
  - 公版书：删除 Gutenberg 头部（*** START OF ... 所在行及之前）与
    尾部（*** END OF ... 所在行及之后），CRLF→LF，裁掉首尾空行。
  - 真实小说：按「第N章」章节标记的出现序切取指定段数（chapters=[起,止]，
    以标记序号而非章节编号计数，规避源文件编号不连续/重复），
    CRLF→LF，裁掉首尾空行；chapters=None 表示整篇采用（同样做 CRLF→LF）。

输出：
  <out-dir>/<corpus_file>          语料正文
  <out-dir>/corpus_manifest.json    语料清单
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

# ---------------------------------------------------------------- 来源定义
# drive_path 为飞书云盘中的可读路径；drive_token 为对应文件 token（用于复现取用）。
GUTENBERG_DIR = "projects/fix_text/语料"
NOVEL_DIR = "projects/fix_text/txt"

SOURCES = [
    # (id, 书名, 云盘文件名, drive_token, 繁体公版书号)
    ("pg24264", "紅樓夢", "pg24264 紅樓夢.txt", "U7uIbZnnEorbGExGgkCcTgrYnhd", "24264"),
    ("pg23962", "西遊記", "pg23962 西遊記.txt", "GmVObTQnRoPxXux5oQMczguUnAd", "23962"),
    ("pg23950", "三國志演義", "pg23950 三國志演義.txt", "GWqObCwBboMiSgxpLAdcUIjonqb", "23950"),
    ("pg23863", "水滸傳", "pg23863 水滸傳.txt", "BriMbXxlnoCXBFxSEnkcKCSenFc", "23863"),
    ("pg23910", "封神演義", "pg23910 封神演義.txt", "KJB4bmhh6oWrrBxkODxc8lzWn0e", "23910"),
    ("pg52200", "金瓶梅", "pg52200 金瓶梅.txt", "W1VZbY0UboYiL9x2uancHyoUn6a", "52200"),
    ("pg24032", "儒林外史", "pg24032 儒林外史.txt", "LmtQbQ91XoDun1xYBiqcLWPEnch", "24032"),
    ("pg24141", "警世通言", "pg24141 警世通言.txt", "A6IBbVYNjoilpmx58JScpkOcnkV", "24141"),
    ("pg51828", "聊齋志異", "pg51828 聊齋志異.txt", "OuNvbHDaGoQmxixLB9DcMBTFndd", "51828"),
    ("pg24226", "史記", "pg24226 史記.txt", "WPSAbohWool5QYxj3EHc9GmynEe", "24226"),
    ("pg24230", "今古奇觀", "pg24230 今古奇觀.txt", "Uc9Hbla2Eo6txCxDT86cUCfCnCe", "24230"),
    ("pg27166", "呐喊", "pg27166 呐喊.txt", "PhTpbogGjoEsGCxaIhGckcKEn3f", "27166"),
]

NOVELS = [
    # (id, 作品名, 云盘文件名, drive_token, 截取章节段（None=整篇）)
    ("novel_quehun", "雀魂：开局国士无双", "雀魂：开局国士无双 作者：玄汐蓝.txt",
     "U97xbrR4bo7mo5xQgX4clWLDnmh", (1, 60)),
    ("novel_guimie", "鬼灭之刃：我的眼睛能看到弹幕", "鬼灭之刃：我的眼睛能看到弹幕 作者：陆要芝麻粒.txt",
     "TyKfbfpKaoXmGqxA8EicoOuKnDg", None),
    ("novel_fanpai", "反派少爷只想过佛系生活", "反派少爷只想过佛系生活 作者：人之下.txt",
     "Hr23bsrK4o63OixCV2ucIbEFn94", (1, 60)),
]

CHAPTER_RE = re.compile(r"^第(\d+)章[\s　]")
START_RE = re.compile(r"^\*\*\*\s*START OF")
END_RE = re.compile(r"^\*\*\*\s*END OF")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(text: str) -> str:
    """CRLF/CR → LF，并裁掉首尾空行。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip("\n")


def strip_gutenberg(text: str) -> str:
    """去掉 Gutenberg 头尾标记及其之前/之后的内容。"""
    lines = text.split("\n")
    start = end = None
    for i, line in enumerate(lines):
        if start is None and START_RE.match(line.strip()):
            start = i
        elif start is not None and END_RE.match(line.strip()):
            end = i
            break
    if start is None:
        raise ValueError("未找到 Gutenberg 起始标记 *** START OF")
    if end is None:
        raise ValueError("未找到 Gutenberg 结束标记 *** END OF")
    if end <= start:
        raise ValueError("Gutenberg 起止标记顺序异常")
    return "\n".join(lines[start + 1 : end])


def chapter_spans(text: str) -> list[tuple[int, int, str]]:
    """返回 [(起始字符下标, 结束字符下标, 章节标题行)]，按出现序。"""
    spans = []
    offsets = []
    for i, line in enumerate(text.split("\n")):
        if CHAPTER_RE.match(line):
            offsets.append((i, line.strip()[:40]))
    lines = text.split("\n")
    for idx, (i, title) in enumerate(offsets):
        end = offsets[idx + 1][0] if idx + 1 < len(offsets) else len(lines)
        spans.append((i, end, title))
    return spans


def slice_chapters(text: str, first: int, last: int) -> tuple[str, str]:
    """按章节标记出现序截取 [first, last] 段，返回 (正文, 描述)。"""
    spans = chapter_spans(text)
    if not spans:
        raise ValueError("未找到章节标记")
    if first < 1 or last > len(spans) or first > last:
        raise ValueError(f"章节段越界：共 {len(spans)} 段，请求 {first}-{last}")
    lines = text.split("\n")
    start_line = spans[first - 1][0]
    if last < len(spans):
        end_line = spans[last][0]
    else:
        end_line = len(lines)
    body = "\n".join(lines[start_line:end_line])
    desc = f"按「第N章」标记出现序取第 {first}-{last} 段（首段标题：{spans[first-1][2]}）"
    return body, desc


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 T0.4 回归基线语料")
    ap.add_argument("--source-dir", required=True, help="存放云盘原始文件的目录")
    ap.add_argument("--out-dir", required=True, help="语料输出目录")
    args = ap.parse_args()

    src_dir = Path(args.source_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    items = []

    for sid, title, filename, token, pgno in SOURCES:
        src_path = src_dir / filename
        if not src_path.exists():
            print(f"[缺失] {src_path}")
            return 2
        raw = src_path.read_bytes()
        text = raw.decode("utf-8")
        body = normalize(strip_gutenberg(text))
        out_name = f"{sid}_{title}.txt"
        data = body.encode("utf-8")
        (out_dir / out_name).write_bytes(data)
        items.append(
            {
                "id": sid,
                "title": title,
                "corpus_file": out_name,
                "script": "繁体",
                "kind": "gutenberg_public_domain",
                "gutenberg_id": pgno,
                "bytes": len(data),
                "chars": len(body),
                "lines": body.count("\n") + 1,
                "sha256": sha256_bytes(data),
                "transform": "删除 Gutenberg 头尾标记行及其之前/之后内容；CRLF→LF；裁掉首尾空行",
                "chapter_range": None,
                "source": {
                    "drive_path": f"{GUTENBERG_DIR}/{filename}",
                    "drive_token": token,
                    "file_name": filename,
                    "bytes": len(raw),
                    "sha256": sha256_bytes(raw),
                },
            }
        )
        print(f"[公版] {out_name:<28} {len(data):>9} B  sha256={sha256_bytes(data)[:16]}")

    for sid, title, filename, token, rng in NOVELS:
        src_path = src_dir / filename
        if not src_path.exists():
            print(f"[缺失] {src_path}")
            return 2
        raw = src_path.read_bytes()
        text = raw.decode("utf-8")
        if rng is None:
            body = normalize(text)
            desc = "整篇采用（仅 CRLF→LF 与首尾空行裁剪）"
            chapter_range = None
        else:
            body, desc = slice_chapters(text, rng[0], rng[1])
            body = normalize(body)
            chapter_range = list(rng)
        out_name = f"{sid}_" + (f"ch{rng[0]:03d}-{rng[1]:03d}.txt" if rng else "full.txt")
        data = body.encode("utf-8")
        (out_dir / out_name).write_bytes(data)
        items.append(
            {
                "id": sid,
                "title": title,
                "corpus_file": out_name,
                "script": "简体",
                "kind": "real_novel",
                "gutenberg_id": None,
                "bytes": len(data),
                "chars": len(body),
                "lines": body.count("\n") + 1,
                "sha256": sha256_bytes(data),
                "transform": desc + "；CRLF→LF；裁掉首尾空行",
                "chapter_range": chapter_range,
                "source": {
                    "drive_path": f"{NOVEL_DIR}/{filename}",
                    "drive_token": token,
                    "file_name": filename,
                    "bytes": len(raw),
                    "sha256": sha256_bytes(raw),
                },
            }
        )
        print(f"[真实] {out_name:<28} {len(data):>9} B  sha256={sha256_bytes(data)[:16]}")

    manifest = {
        "corpus_version": "v1",
        "generator": "baseline/scripts/build_corpus.py",
        "note": "全部语料来自飞书云盘 projects/fix_text，构建过程无任何外网下载。",
        "total_bytes": sum(i["bytes"] for i in items),
        "total_items": len(items),
        "items": items,
    }
    (out_dir / "corpus_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"合计 {len(items)} 个语料文件，{manifest['total_bytes']} 字节")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
