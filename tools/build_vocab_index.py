"""M3-T3.1：内置词库分级索引构建（可复现、可追溯）。

词库管理页要把内置词库按「常规校正 / 标点规范 / 繁简转换」三级展示，
但 T0.2 的引擎产物 `before.json` / `after.json` 只有 before/after 一对值，
不带分级信息——分级只存在于迁移时的**变量归属**里（每个变量一个 flat 文件）。

本脚本从 T0.2 的 `dictionary/flat/*.json` 反推每条规则属于哪个变量，
再把变量折叠成三级，产出：

1. `data/rules/builtin_tiers.bin` —— 每条规则 1 字节（'1' / '2' / '3'），
   顺序与 `before.json` 严格一一对应，供数据层 O(1) 取分级；
2. `data/rules/builtin_marks.json` —— 每条规则的中文说明（`mark` 字段去花括号），
   空串表示该规则没有说明，供界面「类型」列展示；
3. `data/rules/builtin_index_meta.json` —— 来源留痕：来源目录、各变量条数、
   分级判据、校验（条数 / 逐条归属成功率 / 产物 sha256）。

分级判据（按优先级，全部来自数据本身，不靠人工猜测）：

- 来源变量属于 `2.繁转简词库*` → **3 繁简转换**
- 规则的 before 与 after **全部字符都是标点** → **2 标点规范**
- 规则的 `mark` 中文说明里出现标点类关键词（顿号 / 逗号 / 引号 / 句号 /
  问号 / 叹号 / 括号 / 破折号 / 省略号 / 书名号 / 标点）→ **2 标点规范**
  （例：`一、二，` → `一二，`，说明是「移除概数之中的顿号」，before 含数字
  所以纯标点判据抓不到，但语义上就是标点规范）
- 其余 → **1 常规校正**

用法：
    python3 tools/build_vocab_index.py --flat-dir <T0.2>/build/dictionary/flat
产物直接写进 `data/rules/`。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
RULES = PKG / "data" / "rules"

#: 视为「标点」的字符（中英文标点 + 常见空白对齐符）
PUNC_CHARS = set(
    "，。、；：？！“”‘’（）《》〈〉【】〔〕「」『』—…·,.;:?!\"'()[]<>-~/\\|"
    "　 \u3000\u00b7\u2026\u2014\u2018\u2019\u201c\u201d"
)

#: mark 里出现这些词，说明该规则语义属于「标点规范」
PUNC_KEYWORDS = (
    "标点", "引号", "顿号", "逗号", "句号", "问号", "叹号", "括号",
    "破折号", "省略号", "书名号",
)


def classify(var: str, before: str, after: str, mark: str) -> str:
    """按判据返回分级码 '1' / '2' / '3'。"""
    if var.startswith("2.繁转简词库"):
        return "3"
    if before and after and all(ch in PUNC_CHARS for ch in before) \
            and all(ch in PUNC_CHARS for ch in after):
        return "2"
    if any(k in (mark or "") for k in PUNC_KEYWORDS):
        return "2"
    return "1"


def load_flat(flat_dir: Path) -> list[tuple[str, str, str, str]]:
    """读全部 flat 变量文件，返回 [(before, after, var, mark)]（按变量名排序）。"""
    out: list[tuple[str, str, str, str]] = []
    used: list[str] = []
    #: `flat__meta__.json` 是迁移的元信息 dict，不是规则变量（没有 before/after），跳过
    files = [p for p in sorted(flat_dir.glob("flat_*.json"))
             if p.name != "flat__meta__.json"]
    if not files:
        raise SystemExit(f"没有找到 flat 变量文件：{flat_dir}")
    for path in files:
        stem = path.name[len("flat_"):-len(".json")]
        rows = json.load(open(path, encoding="utf-8"))
        if not isinstance(rows, list):
            raise SystemExit(f"变量文件不是规则数组：{path.name} -> {type(rows).__name__}")
        used.append(stem)
        for row in rows:
            mark = row.get("mark") or ""
            out.append((row["before"], row["after"], stem, str(mark)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flat-dir", required=True,
                    help="T0.2 产物目录 dictionary/flat（含 flat_*.json）")
    args = ap.parse_args()
    flat_dir = Path(args.flat_dir).expanduser().resolve()

    before = json.load(open(RULES / "before.json", encoding="utf-8"))
    after = json.load(open(RULES / "after.json", encoding="utf-8"))
    if len(before) != len(after):
        raise SystemExit(f"before/after 条数不一致：{len(before)} / {len(after)}")

    recs = load_flat(flat_dir)
    if len(recs) != len(before):
        raise SystemExit(
            f"flat 展开条数 {len(recs)} 与 before.json {len(before)} 不一致，"
            "两份数据不是同一次迁移产物")

    # 逐条归属：同一 (before, after) 可能出现多次，按变量剩余配额依次分配，
    # 保证「每条规则都能唯一落到一个变量」，不被共用 key 混淆。
    pool: dict[tuple[str, str], dict[str, int]] = {}
    per_var: dict[str, int] = {}
    for b, a, var, _mark in recs:
        pool.setdefault((b, a), {})
        pool[(b, a)][var] = pool[(b, a)].get(var, 0) + 1
        per_var[var] = per_var.get(var, 0) + 1

    marks: dict[str, str] = {}
    for b, a, _var, mark in recs:
        key = (b, a)
        if mark and key not in marks:
            marks[key] = mark

    tiers = bytearray(len(before))
    resolved = 0
    leftover = 0
    var_of_rule: list[str] = []
    for i, (b, a) in enumerate(zip(before, after)):
        bucket = pool.get((b, a)) or {}
        var = next((k for k, n in bucket.items() if n > 0), None)
        if var is None:
            continue
        bucket[var] -= 1
        resolved += 1
        var_of_rule.append(var)
        tiers[i] = ord(classify(var, b, a, marks.get((b, a), "")))
    leftover = sum(sum(v.values()) for v in pool.values())

    if resolved != len(before) or leftover:
        raise SystemExit(
            f"归属未闭合：成功 {resolved}/{len(before)}，剩余未消耗 {leftover}")

    marks_out = [marks.get((b, a), "") for b, a in zip(before, after)]
    tier_count = {t: 0 for t in "123"}
    for t in tiers:
        tier_count[chr(t)] += 1

    RULES.mkdir(parents=True, exist_ok=True)
    bin_path = RULES / "builtin_tiers.bin"
    bin_path.write_bytes(bytes(tiers))
    marks_path = RULES / "builtin_marks.json"
    marks_path.write_text(json.dumps(marks_out, ensure_ascii=False,
                                     separators=(",", ":")), encoding="utf-8")

    def sha(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    meta = dict(
        product="FixText M3-T3.1 内置词库分级索引",
        generated_by="tools/build_vocab_index.py",
        source_flat_dir=str(flat_dir),
        rules_before=str(RULES / "before.json"),
        rules_before_sha256=sha(RULES / "before.json"),
        rule_count=len(before),
        resolved=resolved,
        leftover=leftover,
        tier_total=tier_count,
        tiers_file=dict(path=str(bin_path.name),
                        bytes=bin_path.stat().st_size,
                        sha256=sha(bin_path)),
        marks_file=dict(path=str(marks_path.name),
                        bytes=marks_path.stat().st_size,
                        sha256=sha(marks_path),
                        non_empty=sum(1 for m in marks_out if m)),
        tier_names={"1": "常规校正", "2": "标点规范", "3": "繁简转换"},
        criterion=[
            "来源变量以 2.繁转简词库 开头 → 繁简转换",
            "before 与 after 全部字符都是标点 → 标点规范",
            "mark 说明含标点类关键词 → 标点规范",
            "其余 → 常规校正",
        ],
        per_var=dict(sorted(per_var.items())),
    )
    (RULES / "builtin_index_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"规则 {len(before)} 条全部归属成功（剩余未消耗 {leftover}）")
    print(f"分级：常规校正 {tier_count['1']} / 标点规范 {tier_count['2']} "
          f"/ 繁简转换 {tier_count['3']}")
    print(f"产物：{bin_path.name} {bin_path.stat().st_size} B, "
          f"{marks_path.name} {marks_path.stat().st_size} B, "
          f"有中文说明 {meta['marks_file']['non_empty']} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
