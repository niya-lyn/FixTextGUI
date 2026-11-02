"""M5-OS.1 · 公版 fixture 的**唯一事实来源**（测试与验收脚本共用的只读辅助）。

为什么要有这个文件
------------------
仓库原先的约 16 个文件把测试绑在一本盗版站来源的网文样本上，并顺手把它的
特征数字（788 章 / 108 处引号问题 / 5100 命中）写死在断言里。样本删掉之后，
如果只是「换一个样本 + 抄一个新的数字」，就等于把同样的毛病换个壳继续存在：
产品哪天少跑一章、少报一处，测试也会跟着抄少一个数，从此再也发现不了。

所以这里只做两件事：

1. **路径唯一**：fixture 的路径只在这里出现一次，别处都从这里取；
2. **数字推导**：期望值一律读 ``fixture_run_meta.json``——那份文件由
   ``tools/make_fixture_meta.py`` 在 fixture 上**真实跑一次**生成，记录的是
   这一轮运行自己产出的章数 / 命中数 / 引号问题数 / 成品指纹。

断言于是写成「与本轮运行自己的产物一致」，而不是「与某个记下来的数字一致」。

fixture 出处
------------
``tests/samples/book_public_domain.epub`` 由 ``tools/build_fixture_epub.py``
从 Project Gutenberg eBook #51828《聊齋志異》（蒲松齡，公有领域）现场合成，
不含任何版权作品。
"""
from __future__ import annotations

import json
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PKG = TESTS.parent
SAMPLES = TESTS / "samples"

#: 公版 fixture 本体（文件名不带任何原书名）。
EPUB = SAMPLES / "book_public_domain.epub"

#: fixture 的真实运行记录（章数 / 命中数 / 引号问题数 / 成品指纹）。
META = SAMPLES / "fixture_run_meta.json"

#: 引号检查页用例的数据源：同一轮运行导出的报告与正文行。
QUOTE_REPORT = SAMPLES / "fixture_quote_report.json"
QUOTE_LINES = SAMPLES / "fixture_quote_lines.txt"

#: 合成脚本（报告里要指得出「这个 fixture 是怎么来的」）。
BUILD_SCRIPT = PKG / "tools" / "build_fixture_epub.py"

#: fixture 在报告 / 元数据里的人话书名（不是任何版权作品的标题）。
TITLE = "聊齋志異（公有領域選篇）"


def meta() -> dict:
    """读 fixture 的真实运行记录。

    缺文件就直接失败——那说明 fixture 没生成或没跑过，
    此时任何「期望值」都是编的，宁可让用例红，也不要静默放行。
    """
    if not META.is_file():
        raise FileNotFoundError(
            f"缺少 fixture 运行记录 {META.name}；"
            "先跑 tools/make_fixture_meta.py 生成它")
    return json.loads(META.read_text("utf-8"))


def chapters() -> int:
    """这本书的章数（含封面页）——取自本轮真实运行，不是写死的数字。"""
    return int(meta()["chapters"])


def quote_errors() -> int:
    """本轮运行实际报出的引号问题数。"""
    return int(meta()["quote_errors"])


def hits() -> int:
    """本轮运行的实际替换命中数。"""
    return int(meta()["hits"])


def restored_sha256() -> str:
    """本轮运行自己还原出来的成品指纹。"""
    return str(meta()["restored_sha256"])


def missing_reason() -> str:
    """缺 fixture 时给用例看的 skip 原因（人话，不夹技术细节）。"""
    if not EPUB.is_file():
        return "缺少公版测试样本（可用 tools/build_fixture_epub.py 现场合成）"
    if not META.is_file():
        return "缺少样本运行记录（先跑 tools/make_fixture_meta.py）"
    return ""


def available() -> bool:
    """fixture 与其运行记录是否都在。"""
    return EPUB.is_file() and META.is_file()
