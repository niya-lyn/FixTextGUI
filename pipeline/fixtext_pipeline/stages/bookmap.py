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

#: 报告里「本书专有词条」的条数上限：``0`` 表示**不截断**。
#:
#: 曾经的 ``ENTRY_PREVIEW_MAX = 20`` 只把前 20 条塞进报告，界面据此显示
#: 20 条、而引擎实际抽出几千条 —— 这是「静默丢条」，用户勾了「全部加入」
#: 也只会写进 20 条。M3-T3.3 起改为全量落盘：预览条数 == 引擎产物条数。
#:
#: 只留在报告里会明显变大（约 5800 条约 550 KB），这个代价换的是
#: 「看到的条数就是真实的条数」，值得。真正的全量清单另存
#: ``book_entries.json``，界面与验收都以它为准。
ENTRY_PREVIEW_MAX = 0


# ---------------------------------------------------------------------------
# 词条整理：给界面用的「词条 / 类型 / 替换值 / 出现次数」
# ---------------------------------------------------------------------------

def classify_entry(before: str, after: str) -> str:
    """把一条差异粗分成用户看得懂的类型（只看形态，不做语义猜测）。

    * 改前后有一侧明显更短（差字数量达到较短一侧的三分之一）→「缺字漏字」
    * 长度差 ≤3 →「错词校正」（错字、别字、的/地/得）
    * 其余 →「专有名词」（这本书独有的写法，正是 T1.5 想抽的东西）

    只用「改前 / 改后」两串本身判断，不引入外部词典，
    同一批输入永远得到同一批类型（可复现）。
    """
    b, a = before.strip(), after.strip()
    if not b or not a or b == a:
        return "其他"
    lb, la = len(b), len(a)
    if abs(lb - la) >= max(2, min(lb, la) // 3):
        return "缺字漏字"
    return "错词校正" if abs(lb - la) <= 3 else "专有名词"


def _enrich_entries(raw: list) -> list[dict]:
    """引擎原始词条 → 预览清单行（**按「改前 + 改后」去重**，全量保留、不截断）。

    T1.5 是按上下文窗口抽差异的：同一处改动在相邻窗口里会各抽一次，
    所以引擎产物（``raw``）是「带重复的」。预览清单去重后才是一份用户
    真能逐条勾选的清单：

    * ``before`` / ``after`` —— 去掉首尾空白后的改前 / 改后（用户看到的词条）
    * ``type`` —— 形态分类（错词校正 / 缺字漏字 / 专有名词 / 其他）
    * ``count`` —— 这个差异在全书里出现了几次（= 同一对词条被抽中几次）

    条数关系：``len(清单)`` = 去重条数 ≤ 引擎原始条数；
    两者都写进报告，界面的「发现 N 条」用的是去重后的 N（用户真能加进去的条数）。
    """
    out: list[dict] = []
    index: dict[tuple[str, str], int] = {}
    for w in raw:
        before = str(w.get("before", "")).strip()
        after = str(w.get("after", "")).strip()
        if not before:
            continue
        key = (before, after or before)
        pos = index.get(key)
        if pos is not None:
            out[pos]["count"] += 1
            continue
        index[key] = len(out)
        out.append({
            "before": before,
            "after": after or before,
            "type": classify_entry(before, after),
            "count": 1,
        })
    return out


def _count_unique(entries: dict) -> int:
    """去重后的条数（与 :func:`_enrich_entries` 的清单长度一致）。"""
    return sum(len(_enrich_entries(arr or [])) for arr in entries.values())


def _assert_no_truncation(raw: dict, preview: dict) -> None:
    """硬门禁：引擎抽出的每一条都必须能在预览里找到落点，绝不静默丢条。

    判据是「条数守恒」而不是「长度相等」：预览是按（改前 + 改后）去重的，
    所以每条预览行的 ``count`` 之和必须正好等于引擎原始条数。少一条就报错。
    """
    for key, arr in raw.items():
        rows = preview.get(key) or []
        accounted = sum(int(r.get("count") or 0) for r in rows)
        want = sum(1 for w in (arr or []) if str(w.get("before", "")).strip())
        if accounted != want:
            raise StageError(
                f"专有词条对不上（{key}）：引擎抽出 {want} 条，预览清单只交代了 "
                f"{accounted} 条；M3-T3.3 起不允许截断或静默丢条"
            )
        seen = {(r.get("before"), r.get("after")) for r in rows}
        if len(seen) != len(rows):
            raise StageError(
                f"专有词条清单里有重复行（{key}）：{len(rows)} 行只有 {len(seen)} 种词条"
            )


class BookMapStage(Stage):
    name = "bookmap"
    title = "专有词库生成（T1.5）"
    depends_on = ("replace",)

    def outputs(self) -> list[Path]:
        return [
            self.cfg.bookmap_file(),
            self.cfg.stage_dir(self.name) / "bookmap_report.json",
            # 全量专有词清单：界面预览与验收都读它，缺了就要重跑
            self.cfg.stage_dir(self.name) / "book_entries.json",
        ]

    def fingerprint(self) -> str:
        from ..state import sha256_file

        # 比对用注音前正文（after_raw）；无注音时 after_raw 等同 after
        after_for_map = self.cfg.replace_after_raw()
        if not after_for_map.is_file():
            after_for_map = self.cfg.replace_after()
        return self.fingerprint_of(
            f"before={sha256_file(self.cfg.replace_before())}",
            f"after={sha256_file(after_for_map)}",
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
        # M5-EX.1：bookmap 用注音前 after_raw，避免「字[音]」进专有词差
        raw_dir = self.cfg.stage_dir("replace") / "after_raw"
        after_dir = raw_dir if (raw_dir / f"{self.cfg.book_stem}.txt").is_file() else (
            self.cfg.stage_dir("replace") / "after"
        )
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
        # 界面侧「本书专有词条」要给用户看真实条目，而不是编几条演示词。
        # M3-T3.3：不再截断——预览条数必须等于引擎实际产物条数，
        # 否则「整组加入」只能写进被截断的那几十条，属于静默丢条。
        # 每条都带「出现次数」（同一处改动在相邻上下文里会各抽一次，
        # 次数即该差异模式在全书里的命中数）与「类型」。
        entry_preview = {
            k: _enrich_entries(v or [])
            for k, v in entries.items()
        }
        # 全量清单单独落一份：报告本体保持可读，界面与验收都读这份，
        # 两者条数由 run() 末尾的断言锁死。
        book_entries_file = self.cfg.stage_dir(self.name) / "book_entries.json"
        dump_json(book_entries_file, dict(
            source="bookmap 阶段（T1.5 专有词提取引擎）实际产物",
            count_by_book={k: len(v) for k, v in entries.items()},
            entries=entry_preview,
        ))
        _assert_no_truncation(entries, entry_preview)
        report = {
            "map_root": str(map_root),
            "book_map_dir": str(book_map_dir),
            "books": books,
            "entry_counts": {k: len(v) for k, v in entries.items()},
            "entry_preview": entry_preview,
            "entries_total": sum(len(v) for v in entries.values()),
            "entries_unique": _count_unique(entries),
            "entries_file": str(book_entries_file),
            "truncated": False,
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
