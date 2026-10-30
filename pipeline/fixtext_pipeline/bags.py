"""内置词库分袋读写与合成（M5-EX.1）。

出厂 ``data/rules/bags/`` 由 ``tools/split_rule_bags.py`` 生成；本模块只读袋文件，
把选定袋拼成引擎可用的 before/after，并可按需前置「我的词库」。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import vocab_bridge

#: 主替换锁定袋（界面勾选但不可取消）
LOCKED_MAIN_BAG = "normal"

#: 与常规同锁：扩展区字形恢复（修编码/比对），主轮强制并入
SILENT_WITH_NORMAL: tuple[str, ...] = ("cjk_recover",)

#: 一键组合勾选 ↔ 袋 id（不含 preprocess/strict/zhuyin：那三袋走独立开关与独立轮）
#: 故意不映射：postfix/temp（等正则 / 临时表）；punctuation（已迁排版 formatting）
UI_BAG_MAP = {
    "b1": "normal",
    "cjk": "cjk_recover",
    "b3": "t2s",
    "b3r": "t2s_radical",
    "extra": "extra",
    "ddd": "ddd",
    "dei2de": "dei2de",
    "old_style": "old_style",
    "txt_format": "txt_format",
}

#: 非 UI 调用时的默认勾选（对齐界面：锁定袋 + 默开袋）
DEFAULT_SELECTED_BAGS = ("b1", "custom", "cjk", "b3", "ddd", "old_style")

SWITCH_BAGS = {
    "preprocess": "preprocess",
    "strict": "strict",
    "zhuyin": "zhuyin",
}


class BagsError(RuntimeError):
    """分袋规则不可用。"""


def bags_root(pkg: Path | None = None) -> Path:
    if pkg is None:
        from ._roots import pkg_root

        pkg = pkg_root()
    return Path(pkg) / "data" / "rules" / "bags"


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    root = root or bags_root()
    path = root / "manifest.json"
    if not path.is_file():
        raise BagsError(f"缺少分袋清单：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BagsError("manifest.json 格式错误")
    return data


def load_bag(bag_id: str, root: Path | None = None) -> tuple[list[str], list[str]]:
    root = root or bags_root()
    bdir = root / bag_id
    before_p = bdir / "before.json"
    after_p = bdir / "after.json"
    if not (before_p.is_file() and after_p.is_file()):
        raise BagsError(f"词库袋缺失或不完整：{bag_id}")
    before = json.loads(before_p.read_text(encoding="utf-8"))
    after = json.loads(after_p.read_text(encoding="utf-8"))
    if not isinstance(before, list) or not isinstance(after, list):
        raise BagsError(f"词库袋 {bag_id} 不是数组")
    if len(before) != len(after):
        raise BagsError(
            f"词库袋 {bag_id} 两侧条数不一致（{len(before)} vs {len(after)}）"
        )
    return [str(x) for x in before], [str(x) for x in after]


def concat_bags(bag_ids: Sequence[str], root: Path | None = None) -> tuple[list[str], list[str]]:
    """按给定顺序拼接多袋（同 before 可重复；引擎 first-wins 取先出现的）。"""
    root = root or bags_root()
    seen: set[str] = set()
    ordered: list[str] = []
    for bid in bag_ids:
        bid = str(bid).strip()
        if not bid or bid in seen:
            continue
        seen.add(bid)
        ordered.append(bid)
    if not ordered:
        raise BagsError("未选择任何词库袋")
    before: list[str] = []
    after: list[str] = []
    for bid in ordered:
        b, a = load_bag(bid, root)
        before.extend(b)
        after.extend(a)
    return before, after


def main_bag_ids(selected_ui: Iterable[str] | None = None) -> list[str]:
    """主替换袋列表：常规+CJK 锁定并入 + 勾选映射袋（不含开关独占的三轮）。"""
    ids = [LOCKED_MAIN_BAG]
    for silent in SILENT_WITH_NORMAL:
        if silent not in ids:
            ids.append(silent)
    for code in selected_ui or ():
        # b1 / cjk 已由锁定路径装入；custom 走 compose，不进袋 id
        if code in ("custom", "b1", "cjk"):
            continue
        bag = UI_BAG_MAP.get(str(code))
        if bag and bag not in ids:
            ids.append(bag)
    return ids


def write_round_rules(
    bag_ids: Sequence[str],
    out_dir: Path | str,
    *,
    custom_path: Path | str | None = None,
    include_custom: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    """写出一轮替换用的 before/after；主轮可 include_custom。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    before, after = concat_bags(bag_ids, root)
    if include_custom:
        entries, err = vocab_bridge.load_custom_entries(custom_path) if custom_path else ([], "")
        composed = vocab_bridge.compose(before, after, entries)
        before = composed["before"]
        after = composed["after"]
        stats = composed["stats"]
        custom_error = err
    else:
        stats = dict(
            base_rules=len(before),
            custom_input=0,
            custom_applied=0,
            total_rules=len(before),
            skipped_empty=[],
            skipped_identity=[],
            skipped_duplicate=[],
            short_custom=[],
            applied_words=[],
        )
        custom_error = ""

    b_path = out / vocab_bridge.DERIVED_BEFORE
    a_path = out / vocab_bridge.DERIVED_AFTER
    raw_b = json.dumps(before, ensure_ascii=False).encode("utf-8")
    raw_a = json.dumps(after, ensure_ascii=False).encode("utf-8")
    vocab_bridge._atomic_write(b_path, raw_b)
    vocab_bridge._atomic_write(a_path, raw_a)
    meta = dict(
        kind="bag_round_rules",
        bag_ids=list(bag_ids),
        include_custom=bool(include_custom),
        custom_error=custom_error,
        before_path=str(b_path),
        after_path=str(a_path),
        **stats,
    )
    (out / "round_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta
