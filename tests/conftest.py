"""pytest 共享夹具与路径配置。

测试中的「期望值」有两个来源，都不来自本 Python 实现本身：

1. ``tests/fixtures/*.json`` —— 由真实 PHP 8.5.8 运行上游 FixText 代码生成
   （见 ``scripts/gen_fixtures.php`` / ``gen_patch_fixtures.php`` /
   ``gen_core_fixtures.php`` / ``gen_map_fixtures.php``），
   避免「用自己的实现验证自己」的循环论证；
2. 真实 ``diff -u`` 产出的 patch 文本。

若夹具文件缺失，相关测试会 skip 并给出明确原因（不静默通过）。
"""

from __future__ import annotations

import json
import os
import sys

import pytest

# 让测试可以直接 import fixtext_bookmap（包在上一级目录）
PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load_fixture(name: str):
    path = os.path.join(FIXTURE_DIR, name)
    if not os.path.isfile(path):
        pytest.skip(f"夹具缺失: {path}（请先运行 scripts/gen_*_fixtures.php 生成）")
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def strip_tags_vectors():
    """由真实 PHP ``strip_tags()`` 生成的权威向量。"""
    return load_fixture("strip_tags_php.json")


@pytest.fixture(scope="session")
def patch_vectors():
    """真实 ``diff -u`` 文本 + 上游 PatchAnalyzer 的权威解析结果。"""
    return load_fixture("patch_analyzer_php.json")


@pytest.fixture(scope="session")
def core_vectors():
    """上游 Util 各核心函数的权威结果。"""
    return load_fixture("core_php.json")


@pytest.fixture(scope="session")
def map_vectors():
    """多行 ^ 替换、词库插入位置、词库合并的权威结果。"""
    return load_fixture("map_php.json")
