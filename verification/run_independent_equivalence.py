#!/usr/bin/env python3
"""独立等价性复核：不依赖 PHP 解释器，用「语料 + PHP 冻结输出」重跑本模块。

背景
----
上游 ``Extractor::generateBookMaps()`` 的入参顺序是
``genDiffWordsMap(patch, booksFix, books)``，即 before 侧取 booksFix、after 侧取 books。
方向约定经实测确认：before = 繁体原稿，after = 简体校正后。

本脚本的输入不是任何自造样本，而是 T0.4 回归基线集里已经冻结的物料：

- ``baseline/corpus/*.txt``       —— 12 本公版书 + 3 部真实小说，繁体原稿（before 侧）
- ``baseline/expected/php/*.txt`` —— PHP 后端跑出的简体校正结果（after 侧）

Python 侧重新生成词库，再与「真实 PHP 8.5.8 运行产出的词库文件」的 sha256 逐份比对。
参照哈希存于 ``reference_hashes.json``，其中还留有 儒林外史 的 PHP 参照产物原件
（``reference_samples/``），可自校验「产物文件 ↔ 记录哈希」的一致性。

用法::

    python3 verification/run_independent_equivalence.py \
        --baseline <FixText_T0.4_回归基线集_v1>/baseline \
        --out verification/independent_result.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PKG_ROOT)

from fixtext_bookmap.generator import BookMapGenerator  # noqa: E402
from fixtext_bookmap.option import Option  # noqa: E402


def sha256_file(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def count_entries(path: str) -> int:
    with open(path, "rb") as fh:
        return fh.read().count(b"['before'")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, help="T0.4 baseline 目录")
    parser.add_argument("--out", default=None, help="结果 JSON 输出路径")
    parser.add_argument(
        "--ref", default=os.path.join(HERE, "reference_hashes.json")
    )
    args = parser.parse_args(argv)

    corpus = os.path.join(args.baseline, "corpus")
    expected = os.path.join(args.baseline, "expected", "php")
    refs = json.load(open(args.ref, encoding="utf-8"))["files"]

    names = sorted(
        f[:-4] for f in os.listdir(corpus)
        if f.endswith(".txt") and f != "corpus_manifest.json"
    )

    tmp = tempfile.mkdtemp(prefix="fxbookmap_verify_")
    try:
        fixdir = os.path.join(tmp, "booksFix")
        bookdir = os.path.join(tmp, "books")
        maproot = os.path.join(tmp, "maproot")
        for d in (fixdir, bookdir, os.path.join(maproot, "maps", "书籍专有替换词库")):
            os.makedirs(d, exist_ok=True)

        for n in names:
            shutil.copy(os.path.join(corpus, n + ".txt"), os.path.join(fixdir, n + ".txt"))
            shutil.copy(os.path.join(expected, n + ".txt"), os.path.join(bookdir, n + ".txt"))

        # 比对时关闭时间点注释：两次运行的时间戳不同属预期差异，上游参照也未写该注释。
        option = Option()
        option.add_current_time = False
        gen = BookMapGenerator(option=option, map_root=maproot)
        result = gen.generate_book_maps(fixdir, bookdir)

        rows = []
        for n in names:
            out = os.path.join(maproot, "maps", "书籍专有替换词库", n + ".php")
            row = {"book": n, "exists": os.path.isfile(out)}
            if row["exists"]:
                row["sha256"] = sha256_file(out)
                row["entries"] = count_entries(out)
                row["bytes"] = os.path.getsize(out)
            ref = refs.get(n, {})
            row["ref_sha256"] = ref.get("sha256")
            row["ref_entries"] = ref.get("entries")
            row["identical"] = (
                row["exists"]
                and row.get("sha256") == ref.get("sha256")
                and row.get("entries") == ref.get("entries")
            )
            rows.append(row)

        summary = {
            "corpora": len(names),
            "identical": sum(1 for r in rows if r["identical"]),
            "different": sum(1 for r in rows if not r["identical"]),
            "entries_total": sum(r.get("entries") or 0 for r in rows),
            "skipped_files": result.get("skipped", []),
            "all_identical": all(r["identical"] for r in rows),
        }
        payload = {"summary": summary, "files": rows}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0 if summary["all_identical"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
