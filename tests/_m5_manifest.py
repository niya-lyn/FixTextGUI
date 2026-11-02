"""M5-T5.1 · 内置词库条数的**推导式**来源（测试专用辅助，非测试文件本身）。

背景
----
M5 分袋重构（commit 7fd0497）之后，内置词库的权威口径不再是「PHP 全量
304,255 条一次性铺平」，而是「按袋拆分 + 只展示可达袋」。因此任何写死
304,255 的断言都会失效，而直接抄实测值又会失去校验力（产品少接一袋、
测试也跟着抄少一个数，就再也发现不了）。

本模块把期望值写成**从 manifest 推导出来的式子**：

    builtin_total  ==  Σ(可达袋的 rule_count)
    可达袋 + 不可达袋 == manifest["rule_count"]   （分袋完整性）

这样一旦有人漏接/多接袋，断言给出的不是「数字对不上」，而是
「可达袋之和与展示总数不一致」这种能直接指认问题的差异。

口径依据
--------
* ``data/rules/bags/manifest.json``：每袋 ``rule_count`` 与 ``rule_count`` 总量；
* ``docs/M5-QC.2_词库袋接线修复报告.md`` §2.2「明确不可达（磁盘保留）」：
  ``punctuation``（已迁排版）、``postfix``、``temp`` 三袋不下发界面；
* ``fixtext_ui/fixtext_vocab.py`` 的 ``BAG_TO_TIER``：界面分级码 ↔ 袋 id 的
  唯一映射，``_load_from_bags`` 正是按它逐袋拼出展示数据。
"""

from __future__ import annotations

import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
BAGS_DIR = PKG / "data" / "rules" / "bags"
MANIFEST = BAGS_DIR / "manifest.json"

#: 修复报告 §2.2 明确不可达、磁盘保留的三袋（不挂界面分级）。
#: 用 manifest 的 id 名而不是数字，避免与 bag_code 混淆。
UNREACHABLE_BAGS = ("punctuation", "postfix", "temp")


def manifest() -> dict:
    """读分袋清单（内置词库条数的唯一权威来源）。"""
    return json.loads(MANIFEST.read_text("utf-8"))


def bag_counts() -> dict[str, int]:
    """袋 id → 规则条数。"""
    return {b["id"]: int(b["rule_count"]) for b in manifest()["bags"]}


def reachable_bags() -> list[str]:
    """界面上真正挂出来的袋：BAG_TO_TIER 的键。"""
    from fixtext_vocab import BAG_TO_TIER

    return list(BAG_TO_TIER)


def reachable_total() -> int:
    """可达袋的规则条数之和——内置词库展示总数应等于这个值。"""
    counts = bag_counts()
    return sum(counts[b] for b in reachable_bags())


def unreachable_total() -> int:
    """不可达袋的规则条数之和（磁盘保留、不展示）。"""
    counts = bag_counts()
    return sum(counts.get(b, 0) for b in UNREACHABLE_BAGS)


def assert_partition_complete() -> None:
    """分袋完整性：可达 + 不可达必须整除 manifest 的总条数。

    这条守住「没有任何一袋被静默丢掉」——只要有人新增/删除袋却没同步
    本文件的分类，这里立刻炸，而不是等某个数字断言莫名其妙对不上。
    """
    m = manifest()
    counts = bag_counts()
    covered = reachable_total() + unreachable_total()
    assert covered == int(m["rule_count"]), (
        f"分袋不完整：可达 {reachable_total()} + 不可达 {unreachable_total()} "
        f"= {covered}，manifest 总量 {m['rule_count']}，"
        f"差额 {int(m['rule_count']) - covered} 条未归类"
    )
    assert len(counts) == int(m["bag_count"]), (
        f"袋数不符：磁盘 {len(counts)} 个，manifest 记录 {m['bag_count']} 个"
    )
