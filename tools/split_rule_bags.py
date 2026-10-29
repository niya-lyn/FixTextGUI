"""按 PHP 来源变量把内置大库拆成多袋（M5-EX.1 运行模式优化）。

依据与 ``build_vocab_index.py`` 相同：用 T0.2 ``dictionary/flat/*.json``
把 ``data/rules/before.json`` / ``after.json`` 的每一行唯一归属到一个
PHP map 变量，再折叠进产品袋。

产物（不改动原 ``before.json`` / ``after.json`` 全量包）：

    data/rules/bags/
        manifest.json          袋清单 + 对账
        <bag_id>/
            before.json
            after.json
            meta.json          本袋来源变量与条数
        builtin_bags.bin       与全量 before 同序，每条 1 字节袋码
        README.md

用法：
    python tools/split_rule_bags.py --flat-dir <T0.2>/build/dictionary/flat
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
RULES = PKG / "data" / "rules"
BAGS_DIR = RULES / "bags"

# 产品袋：id / 人话名 / 是否组合里锁定 / 是否仅由开关启用（不进组合列表）
# vars 为 flat 文件名去掉 flat_ 与 .json 后的 stem（与 builtin_index_meta.per_var 键一致）
BAG_SPECS: list[dict] = [
    {
        "id": "normal",
        "title": "常规校正",
        "locked": True,
        "via_switch": False,
        "default_on": True,
        "vars": ["1.自定义词库.php__normalMap"],
    },
    {
        "id": "preprocess",
        "title": "预处理",
        "locked": False,
        "via_switch": False,
        "default_on": False,
        "vars": [
            "1.自定义词库.php__preprocessMap",
            "1.自定义词库.php__extraPreprocessMap",
        ],
    },
    {
        "id": "strict",
        "title": "严格校正",
        "locked": False,
        "via_switch": True,
        "default_on": False,
        "vars": ["1.自定义词库.php__strictMap"],
    },
    {
        "id": "zhuyin",
        "title": "生僻字注音",
        "locked": False,
        "via_switch": True,
        "default_on": False,
        "vars": [
            "7.生僻字词库.php__shengpiziMap",
            "7.生僻字词库_扩展区_.php__cjkExtMap",
        ],
    },
    {
        "id": "punctuation",
        "title": "标点规范",
        "locked": False,
        "via_switch": False,
        "default_on": True,
        "vars": ["1.自定义词库.php__punctuationMap"],
        "note": "仅 punctuationMap 源变量；旧 tier=2 里靠 mark 判进「标点」的条目仍留在其来源袋",
    },
    {
        "id": "cjk_recover",
        "title": "CJK 恢复",
        "locked": False,
        "via_switch": False,
        "default_on": True,
        "vars": ["7.生僻字词库_扩展区_.php__cjkRecoverMap"],
    },
    {
        "id": "extra",
        "title": "的地得/象像加强",
        "locked": False,
        "via_switch": False,
        "default_on": False,
        "vars": ["1.自定义词库.php__extraMap"],
    },
    {
        "id": "old_style",
        "title": "旧式通假",
        "locked": False,
        "via_switch": False,
        "default_on": False,
        "vars": ["1.自定义词库_旧式、通假写法_.php__oldStyleMap"],
    },
    {
        "id": "t2s",
        "title": "繁简转换",
        "locked": False,
        "via_switch": False,
        "default_on": False,
        "vars": [
            "2.繁转简词库.php__t2sMap",
            "2.繁转简词库.php__t2sRadicalMap",
            "2.繁转简词库.php__radicalsSupplementMap",
        ],
    },
    {
        "id": "txt_format",
        "title": "txtFormat",
        "locked": False,
        "via_switch": False,
        "default_on": False,
        "vars": ["3.txtFormat 词库.php__txtFormatMap"],
    },
    {
        "id": "ddd",
        "title": "的地得",
        "locked": False,
        "via_switch": False,
        "default_on": False,
        "vars": [
            "4.的地得词库.php__dddMap",
            "4.的地得词库.php__accurateDddMap",
        ],
    },
    {
        "id": "dei2de",
        "title": "得转的",
        "locked": False,
        "via_switch": False,
        "default_on": False,
        "vars": ["4.的地得词库.php__dei2deMap"],
    },
    {
        "id": "postfix",
        "title": "后处理词库",
        "locked": False,
        "via_switch": False,
        "default_on": False,
        "vars": ["1.自定义词库.php__postFixMap"],
        "note": "PHP postFix 阶段；严格路径也会加载。接线时再定是否并进严格轮",
    },
    {
        "id": "temp",
        "title": "临时替换表",
        "locked": False,
        "via_switch": False,
        "default_on": False,
        "vars": ["5.临时校对表.php__tempMap"],
    },
]

# 跳过：空自定义袋、正则（flat_count=0，不进 before/after）
SKIP_VAR_PREFIXES = (
    "6.用户扩展词库.php__",
)
SKIP_VAR_SUFFIXES = (
    "__regexMap",
    "__extraRegexMap",
    "__strictRegexMap",
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_flat(flat_dir: Path) -> list[tuple[str, str, str]]:
    """返回 [(before, after, var_stem), ...]，跳过空/正则。"""
    out: list[tuple[str, str, str]] = []
    files = sorted(
        p for p in flat_dir.glob("flat_*.json") if p.name != "flat__meta__.json"
    )
    if not files:
        raise SystemExit(f"没有 flat 变量文件：{flat_dir}")
    for path in files:
        stem = path.name[len("flat_") : -len(".json")]
        if stem.startswith(SKIP_VAR_PREFIXES):
            continue
        if any(stem.endswith(s) for s in SKIP_VAR_SUFFIXES):
            continue
        if "RegexMap" in stem:
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise SystemExit(f"非数组：{path.name}")
        if not rows:
            continue
        for row in rows:
            out.append((row["before"], row["after"], stem))
    return out


def _var_to_bag() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for spec in BAG_SPECS:
        for var in spec["vars"]:
            if var in mapping:
                raise SystemExit(f"变量重复归属：{var}")
            mapping[var] = spec["id"]
    return mapping


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--flat-dir",
        required=True,
        help="T0.2 dictionary/flat 目录",
    )
    ap.add_argument(
        "--out-dir",
        default=str(BAGS_DIR),
        help="输出目录（默认 data/rules/bags）",
    )
    args = ap.parse_args()
    flat_dir = Path(args.flat_dir).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    before_path = RULES / "before.json"
    after_path = RULES / "after.json"
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    if len(before) != len(after):
        raise SystemExit(f"before/after 条数不一致：{len(before)} / {len(after)}")

    recs = _load_flat(flat_dir)
    if len(recs) != len(before):
        raise SystemExit(
            f"flat 展开条数 {len(recs)} 与 before.json {len(before)} 不一致 "
            f"（是否跳过了不该跳过的变量？）"
        )

    var_to_bag = _var_to_bag()
    unknown_vars = sorted({v for _b, _a, v in recs if v not in var_to_bag})
    if unknown_vars:
        raise SystemExit(f"有来源变量未编入任何袋：{unknown_vars}")

    pool: dict[tuple[str, str], dict[str, int]] = {}
    for b, a, var in recs:
        pool.setdefault((b, a), {})
        pool[(b, a)][var] = pool[(b, a)].get(var, 0) + 1

    bag_before: dict[str, list[str]] = {s["id"]: [] for s in BAG_SPECS}
    bag_after: dict[str, list[str]] = {s["id"]: [] for s in BAG_SPECS}
    bag_var_counts: dict[str, dict[str, int]] = {
        s["id"]: {v: 0 for v in s["vars"]} for s in BAG_SPECS
    }
    # 袋码：与 BAG_SPECS 顺序一致，1-based，写入 builtin_bags.bin
    bag_code = {s["id"]: i + 1 for i, s in enumerate(BAG_SPECS)}
    bags_bin = bytearray(len(before))

    resolved = 0
    for i, (b, a) in enumerate(zip(before, after)):
        bucket = pool.get((b, a)) or {}
        var = next((k for k, n in bucket.items() if n > 0), None)
        if var is None:
            raise SystemExit(f"第 {i} 条无法归属：{b!r} → {a!r}")
        bucket[var] -= 1
        bag_id = var_to_bag[var]
        bag_before[bag_id].append(b)
        bag_after[bag_id].append(a)
        bag_var_counts[bag_id][var] += 1
        bags_bin[i] = bag_code[bag_id]
        resolved += 1

    leftover = sum(sum(v.values()) for v in pool.values())
    if resolved != len(before) or leftover:
        raise SystemExit(
            f"归属未闭合：成功 {resolved}/{len(before)}，剩余 {leftover}"
        )

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    bags_meta = []
    total = 0
    for spec in BAG_SPECS:
        bid = spec["id"]
        n = len(bag_before[bid])
        total += n
        bag_dir = out_dir / bid
        bag_dir.mkdir()
        b_path = bag_dir / "before.json"
        a_path = bag_dir / "after.json"
        b_path.write_text(
            json.dumps(bag_before[bid], ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        a_path.write_text(
            json.dumps(bag_after[bid], ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        meta = {
            "id": bid,
            "title": spec["title"],
            "locked": spec["locked"],
            "via_switch": spec["via_switch"],
            "default_on": spec["default_on"],
            "rule_count": n,
            "vars": bag_var_counts[bid],
            "before_sha256": _sha256_file(b_path),
            "after_sha256": _sha256_file(a_path),
            "bag_code": bag_code[bid],
        }
        if spec.get("note"):
            meta["note"] = spec["note"]
        (bag_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        bags_meta.append(meta)

    if total != len(before):
        raise SystemExit(f"袋条数之和 {total} != 全量 {len(before)}")

    bin_path = out_dir / "builtin_bags.bin"
    bin_path.write_bytes(bytes(bags_bin))

    manifest = {
        "product": "FixText M5-EX.1 内置词库分袋",
        "card": "M5-EX.1",
        "generated_by": "tools/split_rule_bags.py",
        "source_flat_dir": str(flat_dir),
        "rules_before": str(before_path),
        "rules_before_sha256": _sha256_file(before_path),
        "rules_after_sha256": _sha256_file(after_path),
        "rule_count": len(before),
        "bag_count": len(BAG_SPECS),
        "bags_sum": total,
        "bags_bin": {
            "path": bin_path.name,
            "bytes": bin_path.stat().st_size,
            "sha256": _sha256_file(bin_path),
            "code_map": {s["id"]: bag_code[s["id"]] for s in BAG_SPECS},
        },
        "defaults_for_main_replace": [
            s["id"] for s in BAG_SPECS if s["default_on"] and not s["via_switch"]
        ],
        "switch_only_bags": [s["id"] for s in BAG_SPECS if s["via_switch"]],
        "locked_bags": [s["id"] for s in BAG_SPECS if s["locked"]],
        "bags": bags_meta,
        "compat": {
            "full_before_after_kept": True,
            "note": "全量 before/after.json 仍保留；新链路应改读 bags/ + compose",
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    readme = """# 内置词库分袋（bags）

由 `tools/split_rule_bags.py` 从 T0.2 flat + 全量 `before/after.json` 生成。

## 约定

| 袋 id | 组合勾选 | 说明 |
|---|---|---|
| `normal` | **锁定必选** | PHP `normalMap` |
| `preprocess` | 可选，默认关 | PHP 预处理；勿与「跳过排版」混淆 |
| `strict` | **不进组合**，严格开关 | PHP `strictMap` |
| `zhuyin` | **不进组合**，注音开关 | `shengpiziMap` + `cjkExtMap` |
| 其余 | 可选 | 见 `manifest.json` |

- `builtin_bags.bin`：与全量 `before.json` **同序**，每条 1 字节袋码（见 manifest `code_map`）。
- 全量 `data/rules/before.json` / `after.json` **未改**，旧链路仍可用。
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    print(f"全量 {len(before)} 条 → {len(BAG_SPECS)} 袋，合计 {total}")
    for m in bags_meta:
        flag = []
        if m["locked"]:
            flag.append("锁定")
        if m["via_switch"]:
            flag.append("仅开关")
        if m["default_on"]:
            flag.append("默认开")
        print(f"  [{m['id']}] {m['title']}: {m['rule_count']}  "
              f"{','.join(flag) or '-'}")
    print(f"产物目录：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
