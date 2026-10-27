"""阶段 5：专有词库生成（T1.5 ``fixtext_bookmap``）。

用「替换前 / 替换后」两份同名文本做差异比对，抽出这本书独有的词条，写进
``maps/书籍专有替换词库/<书名>.php``。

方向约定（最容易踩错的一点，与上游一致）：

* ``--book-fix-dir`` 侧 = 词条的 **before（改前）** 文本 → 本编排器给的是
  ``03_replace/before/``；
* ``--book-dir`` 侧 = 词条的 **after（改后）** 文本 → 本编排器给的是
  ``03_replace/after/``。

本编排器默认关闭「时间点注释」（上游默认开），这样同一份输入两次运行
产物逐字节一致，断点恢复时的指纹也稳定。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import dump_json
from .base import Stage, StageError


class BookMapStage(Stage):
    name = "bookmap"
    title = "专有词库生成（T1.5）"
    depends_on = ("replace",)

    def outputs(self) -> list[Path]:
        return [
            self.cfg.bookmap_file(),
            self.cfg.stage_dir(self.name) / "bookmap_report.json",
        ]

    def fingerprint(self) -> str:
        from ..state import sha256_file

        return self.fingerprint_of(
            f"before={sha256_file(self.cfg.replace_before())}",
            f"after={sha256_file(self.cfg.replace_after())}",
            f"add_current_time={self.cfg.bookmap_add_current_time}",
        )

    def run(self) -> dict[str, Any]:
        from fixtext_bookmap.generator import BookMapGenerator
        from fixtext_bookmap.option import Option

        map_root = self.ensure_dir(self.cfg.stage_dir(self.name))
        book_map_dir = self.ensure_dir(self.cfg.bookmap_dir())
        self.log.log(f"[bookmap] 词库表目录：{book_map_dir}")

        option = Option()
        option.add_current_time = self.cfg.bookmap_add_current_time

        generator = BookMapGenerator(option=option, map_root=str(map_root))
        before_dir = self.cfg.stage_dir("replace") / "before"
        after_dir = self.cfg.stage_dir("replace") / "after"
        self.log.log(f"[bookmap] 比对目录：before={before_dir} / after={after_dir}")

        result = generator.generate_book_maps(str(before_dir), str(after_dir))
        books = result.get("books", [])
        entries = result.get("entries", {})
        skipped = result.get("skipped", [])

        if not books:
            raise StageError(
                f"未生成任何专有词库表（skipped={len(skipped)}）；"
                "请确认替换前后目录里存在同名 .txt"
            )

        book_map_file = self.cfg.bookmap_file()
        report = {
            "map_root": str(map_root),
            "book_map_dir": str(book_map_dir),
            "books": books,
            "entry_counts": {k: len(v) for k, v in entries.items()},
            "skipped": skipped,
            "book_map_file": str(book_map_file),
            "book_map_exists": book_map_file.exists(),
            "book_map_bytes": book_map_file.stat().st_size if book_map_file.exists() else 0,
            "add_current_time": self.cfg.bookmap_add_current_time,
        }
        dump_json(self.cfg.stage_dir(self.name) / "bookmap_report.json", report)

        for book in books:
            self.log.log(
                f"[bookmap] 《{book.get('book')}》 词条 {book.get('entry_count')} 条，"
                f"写入={'成功' if book.get('merged') else '失败'}"
            )
            if book.get("patch"):
                self.log.log(f"[bookmap] patch 文件：{book['patch']}")
        return report
