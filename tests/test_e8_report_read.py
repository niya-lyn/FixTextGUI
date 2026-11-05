"""V1.1-E8 · 替换报告读取的验收测试。

两层证据，缺一不可：

1. **真实报告**：``fixtures/report/`` 里三份文件都是本卡现场跑出来的真产物
   （《炮火弧线》788 章，管线 24.8s，导出层 ``build_stats`` 原样生成），
   不是手工仿写。判定用**文件里能独立复算的数**：明细行数、明细次数合计、
   报告自报命中数、TXT 明细里「序号：【i/n】」的 n。「未校正」那份是同一本书
   没跑过校正时的真实输出（命中 0、无明细）。
2. **容错逐个用例**：缺列 / 空行 / 次数不是数字 / 负数 / 列数不够 / 编码异常 /
   文件不存在 / 目录 / 空文件 —— 每个都给一条**带行号的人话提示**，且不崩。

另外两条硬判据：

* 纯解析模块不依赖 Qt / 界面层 / 管线（在子进程里断言 ``sys.modules``）；
* 出厂词库（``data/rules``）与 ``pipeline/vendor`` 在本卡期间逐字节未变。
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "report"

REAL_CSV = FIXTURES / "炮火弧线替换统计.csv"
REAL_TXT = FIXTURES / "炮火弧线替换统计.txt"
REAL_UNCORRECTED = FIXTURES / "炮火弧线替换统计_未校正.csv"


# ---------------------------------------------------------------------------
# 真实样本的独立复算（不从解析器里取数，避免自证）
# ---------------------------------------------------------------------------

def _csv_rows(path: Path) -> list[list[str]]:
    import csv
    import io

    return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig"))))


def _real_csv_facts() -> dict:
    rows = _csv_rows(REAL_CSV)
    kv = {r[0]: r[1] for r in rows if len(r) == 2}
    detail = [r for r in rows if len(r) == 3 and r[2].strip().isdigit() and r[0] != "改前"]
    return {
        "title": kv["书名"],
        "author": kv["作者"],
        "generated_at": kv["生成时间"],
        "hits": int(kv["命中数"]),
        "libraries_text": kv["涉及词库"],
        "detail_rows": len(detail),
        "detail_total": sum(int(r[2]) for r in detail),
    }


def _real_txt_facts() -> dict:
    text = REAL_TXT.read_text(encoding="utf-8")
    items = re.findall(
        r"\['before' => \"((?:[^\"\\]|\\.)*)\", 'after' => \"((?:[^\"\\]|\\.)*)\"\], "
        r"// 替换次数: 【(\d+)】 \| 序号：【(\d+)/(\d+)】", text)
    return {
        "hits": int(re.search(r"命中数：(\d+)", text).group(1)),
        "stated_total": int(re.search(r"总替换次数：【(\d+)】", text).group(1)),
        "entries": int(items[0][4]) if items else 0,
        "rows": len(items),
        "escaped": sum(1 for b, a, _c, _i, _n in items if '\\"' in b or '\\"' in a),
    }


# ---------------------------------------------------------------------------
# 1. 真实报告（CSV）
# ---------------------------------------------------------------------------

def test_real_csv_matches_file_facts():
    """解析结果必须与直接从文件里复算的事实逐项相等。"""
    from fixtext_report import parse_report

    facts = _real_csv_facts()
    rep = parse_report(REAL_CSV)
    assert rep.ok and rep.fmt == "csv"
    assert rep.title == facts["title"] == "炮火弧线"
    assert rep.author == facts["author"]
    assert rep.generated_at == facts["generated_at"]
    assert rep.hits == facts["hits"] == 2638
    assert rep.detail_rows == facts["detail_rows"] == 2477
    assert rep.detail_total == facts["detail_total"] == 2638
    # 两处口径（命中数 / 明细合计）在这份真实报告里是一致的
    assert rep.hits_consistent is True
    # 干净的真实报告不该冒出任何警告
    assert rep.warnings() == []


def test_real_csv_libraries_parsed_into_numbers():
    from fixtext_report import parse_report

    rep = parse_report(REAL_CSV)
    entries = {e.name: e for e in rep.libraries}
    assert set(entries) == {"通用校对词库", "本书专有词库"}
    g = entries["通用校对词库"]
    assert g.applied_rules == 151192
    assert g.unique_rules == 149969
    assert g.extracted_entries is None          # 词库名里没有「提取」这个数
    b = entries["本书专有词库"]
    assert b.extracted_entries == 3037
    assert b.applied_rules is None
    applied, unique = rep.library_rule_totals()
    assert (applied, unique) == (151192, 149969)


def test_real_csv_rows_are_rule_dimension():
    """明细行本身就是「按规则」维度：同一次改前改后已合并、次数已累加。"""
    from fixtext_report import parse_report

    rep = parse_report(REAL_CSV)
    top = rep.top(3)
    assert [r.count for r in top] == [10, 9, 9]
    assert top[0].before == "，长长的叹了口"
    assert top[0].after == "，长长地叹了口"
    # 报告里出现最多的一次次数必须 ≤ 合计
    assert max(r.count for r in rep.rows) <= rep.detail_total
    dist = rep.count_distribution()
    assert sum(dist.values()) == rep.detail_rows
    assert sum(k * v for k, v in dist.items()) == rep.detail_total
    # 搜索走真实数据
    hit = rep.search("长长的叹")
    assert hit and all("长长的叹" in r.before or "长长的叹" in r.after for r in hit)


def test_real_csv_has_local_paths_nowhere():
    """报告里不该出现本机路径；解析结果也不该带出来。"""
    assert "/home/" not in REAL_CSV.read_text(encoding="utf-8-sig")
    from fixtext_report import parse_report

    rep = parse_report(REAL_CSV)
    for row in rep.rows[:20]:
        assert "\\" not in row.before and "home" not in row.before


# ---------------------------------------------------------------------------
# 2. 真实报告（TXT）
# ---------------------------------------------------------------------------

def test_real_txt_matches_file_facts():
    from fixtext_report import parse_report

    facts = _real_txt_facts()
    rep = parse_report(REAL_TXT)
    assert rep.ok and rep.fmt == "text"
    assert rep.hits == facts["hits"] == 2638
    assert rep.detail_rows == facts["rows"] == 2477
    assert rep.detail_total == facts["stated_total"] == 2638
    # 报告自报条数（序号分母）与实际读到的条数一致
    assert len(rep.sections) == 1
    sec = rep.sections[0]
    assert sec.label == "sample"
    assert sec.stated_entries == facts["entries"] == 2477
    assert sec.rows_found == facts["rows"] == 2477
    assert sec.total_found == facts["stated_total"] == 2638
    assert sec.threshold == 0
    assert rep.warnings() == []


def test_real_txt_unescapes_quotes():
    """TXT 明细里的转义引号必须还原成真引号（真实报告里有 47 条带转义）。"""
    from fixtext_report import parse_report

    facts = _real_txt_facts()
    rep = parse_report(REAL_TXT)
    assert facts["escaped"] > 0
    escaped_rows = [r for r in rep.rows if '"' in r.before or '"' in r.after]
    assert len(escaped_rows) >= facts["escaped"]
    for r in rep.rows:
        assert '\\"' not in r.before and '\\"' not in r.after


def test_both_forms_agree():
    """同一本书的两种落盘形态，读出来的内容必须一致。"""
    from fixtext_report import parse_report

    a = parse_report(REAL_CSV)
    b = parse_report(REAL_TXT)
    assert (a.title, a.author, a.hits) == (b.title, b.author, b.hits)
    assert a.detail_rows == b.detail_rows
    assert a.detail_total == b.detail_total
    assert {(r.before, r.after, r.count) for r in a.rows} == {
        (r.before, r.after, r.count) for r in b.rows
    }


def test_real_uncorrected_report():
    """没跑过校正的真实报告：命中 0、无明细，且必须说清原因。"""
    from fixtext_report import parse_report

    rep = parse_report(REAL_UNCORRECTED)
    assert rep.ok and rep.fmt == "csv"
    assert rep.hits == 0
    assert rep.detail_rows == 0
    assert rep.corrected is False
    assert "没有跑过校正" in "".join(rep.notes)
    assert rep.warnings() == []


# ---------------------------------------------------------------------------
# 3. 容错：每一种残缺都给一条带行号的人话提示，且不崩
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, name: str, text: str, encoding: str = "utf-8") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


HEADER = "项目,值\n书名,测试书\n作者,某人\n生成时间,2026-11-05 10:00:00\n命中数,{hits}\n涉及词库,{libs}\n\n改前,改后,替换次数\n"


def _csv(hits: str = "6", libs: str = "通用校对词库（本次应用规则 100 条）") -> str:
    return HEADER.format(hits=hits, libs=libs)


def test_blank_lines_are_tolerated(tmp_path):
    from fixtext_report import parse_report

    text = _csv(hits="5") + "\n\nA,B,3\n\n\nC,D,2\n\n"
    rep = parse_report(_write(tmp_path, "有空白行.csv", text))
    assert rep.ok
    assert rep.detail_rows == 2 and rep.detail_total == 5
    # 空行不当成错误：没有任何 warning
    assert rep.warnings() == []


def test_short_row_reports_line_and_skips(tmp_path):
    from fixtext_report import parse_report

    text = _csv(hits="5") + "A,B,3\n只有一列\nC,D,2\n"
    rep = parse_report(_write(tmp_path, "少列.csv", text))
    assert rep.ok and rep.detail_rows == 2
    warns = rep.warnings()
    assert len(warns) == 1
    w = warns[0]
    assert w.code == "detail_short_row"
    assert w.line_no is not None                    # 必须指到具体哪一行
    assert "列数不够" in w.message and "跳过" in w.message


def test_count_not_a_number_is_reported(tmp_path):
    from fixtext_report import parse_report

    text = _csv(hits="3") + "A,B,3\nC,D,很多\nE,F,1\n"
    rep = parse_report(_write(tmp_path, "次数不是数字.csv", text))
    assert rep.detail_rows == 2 and rep.detail_total == 4
    w = [i for i in rep.warnings() if i.code == "count_not_a_number"][0]
    assert w.line_no is not None and "不是数字" in w.message
    assert "很多" in w.message                      # 把读到的原值写出来
    # 报告自报命中 3、明细 4：对账要自己跳出来，不能静默
    assert rep.hits_consistent is False
    codes = [i.code for i in rep.warnings()]
    assert "hits_mismatch" in codes


def test_negative_and_absurd_counts_are_rejected(tmp_path):
    from fixtext_report import parse_report

    text = _csv(hits="5") + "A,B,5\nC,D,-2\nE,F,999999999\n"
    rep = parse_report(_write(tmp_path, "异常次数.csv", text))
    assert rep.detail_rows == 1 and rep.detail_total == 5
    codes = {i.code for i in rep.warnings()}
    assert "detail_negative_count" in codes
    assert "detail_count_too_big" in codes
    for i in rep.warnings():
        assert i.line_no is not None


def test_blank_words_row_is_skipped_with_reason(tmp_path):
    from fixtext_report import parse_report

    text = _csv(hits="3") + 'A,B,3\n"","",1\n'
    rep = parse_report(_write(tmp_path, "空词条.csv", text))
    assert rep.detail_rows == 1 and rep.detail_total == 3
    assert any(i.code == "detail_blank_words" for i in rep.warnings())


def test_missing_hits_field(tmp_path):
    """报告里根本没有「命中数」这一项：hits 必须是 None，不是 0。"""
    from fixtext_report import parse_report

    text = "项目,值\n书名,测试书\n作者,某人\n\n改前,改后,替换次数\nA,B,3\n"
    rep = parse_report(_write(tmp_path, "缺命中数.csv", text))
    assert rep.ok
    assert rep.hits is None                          # 缺字段 ≠ 0
    assert rep.hits_consistent is None
    assert rep.detail_total == 3


def test_missing_value_for_hits(tmp_path):
    from fixtext_report import parse_report

    text = "项目,值\n书名,测试书\n命中数\n\n改前,改后,替换次数\nA,B,3\n"
    rep = parse_report(_write(tmp_path, "命中数缺值.csv", text))
    assert rep.hits is None
    w = [i for i in rep.warnings() if i.code == "kv_missing_value"]
    assert w and w[0].line_no is not None and "命中数" in w[0].message


def test_missing_detail_header(tmp_path):
    from fixtext_report import parse_report

    text = "项目,值\n书名,测试书\n命中数,0\n"
    rep = parse_report(_write(tmp_path, "无明细表.csv", text))
    assert rep.ok and rep.hits == 0 and rep.detail_rows == 0
    assert any(i.code == "no_detail_header" for i in rep.warnings())


def test_detail_header_with_extra_column(tmp_path):
    """表头多一列时按列名定位，不按位置硬猜。"""
    from fixtext_report import parse_report

    text = (_csv(hits="3") .replace("改前,改后,替换次数", "序号,改前,改后,替换次数")
           + "1,A,B,3\n")
    rep = parse_report(_write(tmp_path, "多一列.csv", text))
    assert rep.detail_rows == 1
    row = rep.rows[0]
    assert (row.before, row.after, row.count) == ("A", "B", 3)


def test_unknown_extra_field_is_kept(tmp_path):
    from fixtext_report import parse_report

    text = _csv(hits="3").replace("命中数,3", "命中数,3\n备注,这是测试")
    rep = parse_report(_write(tmp_path, "多字段.csv", text))
    assert rep.extra_fields.get("备注") == "这是测试"
    assert any(i.code == "kv_extra" for i in rep.issues)


def test_empty_file(tmp_path):
    from fixtext_report import parse_report

    rep = parse_report(_write(tmp_path, "空.csv", ""))
    assert rep.ok is False
    assert any(i.code == "empty_file" for i in rep.warnings())
    assert rep.to_dict()["rows"] == []


def test_file_missing(tmp_path):
    from fixtext_report import parse_report

    rep = parse_report(tmp_path / "不存在.csv")
    assert rep.ok is False
    assert [i.code for i in rep.warnings()] == ["file_missing"]
    assert "没有找到" in rep.warnings()[0].message


def test_path_is_directory(tmp_path):
    from fixtext_report import parse_report

    d = tmp_path / "是个文件夹.csv"
    d.mkdir()
    rep = parse_report(d)
    assert rep.ok is False
    assert any(i.code == "file_is_dir" for i in rep.warnings())


def test_not_a_report_at_all(tmp_path):
    from fixtext_report import parse_report

    rep = parse_report(_write(tmp_path, "随便什么.csv", "这是一段小说正文\n他说，今天天气不错。\n"))
    assert rep.ok is False
    assert any(i.code == "nothing_recognized" for i in rep.warnings())


def test_gbk_encoded_report_is_read(tmp_path):
    """非 UTF-8 的报告也要能读（导出侧现在写 UTF-8，但历史文件可能是 GBK）。"""
    from fixtext_report import parse_report

    text = _csv(hits="6") + "他说,他说着,3\n他问,他问着,3\n"
    p = _write(tmp_path, "老格式.csv", text, encoding="gbk")
    raw = p.read_bytes()
    assert raw[:3] != b"\xef\xbb\xbf"
    rep = parse_report(p)
    assert rep.ok and rep.title == "测试书"
    assert rep.detail_rows == 2 and rep.detail_total == 6
    assert "老式中文格式" in rep.read_note or "国标" in rep.read_note


def test_broken_bytes_do_not_crash(tmp_path):
    """中间夹非法字节：不崩，且明确说「没能完全确定格式」。"""
    from fixtext_report import parse_report

    text = _csv(hits="6") + "A,B,3\nC,D,3\n"
    p = tmp_path / "坏字节.csv"
    p.write_bytes(text.encode("utf-8") + b"\xff\xfe\x00 broken \x80\n")
    rep = parse_report(p)
    assert rep.title == "测试书"                      # 读到了能读的部分
    assert rep.detail_rows >= 2
    assert any("没能完全确定" in i.message or i.code == "encoding_fallback"
               for i in rep.issues) or rep.read_note


def test_text_report_missing_detail_section(tmp_path):
    from fixtext_report import parse_report

    text = "替换统计 · 测试书\n作者：某人\n生成时间：2026-11-05\n命中数：0\n涉及词库：无\n"
    rep = parse_report(_write(tmp_path, "无明细.txt", text))
    assert rep.ok and rep.hits == 0
    assert any(i.code == "no_detail_section" for i in rep.warnings())


def test_text_unparsable_line_has_line_number(tmp_path):
    from fixtext_report import parse_report

    text = ("替换统计 · 测试书\n作者：某人\n命中数：3\n\n——— 详细词条 ———\n"
            "    // 【替换次数报告】x\n"
            "    ['before' => \"A\", 'after' => \"B\"], // 替换次数: 【3】\n"
            "    ['before' => \"C\" 少了 after 半截\n"
            "    这一行不是词条\n")
    rep = parse_report(_write(tmp_path, "混杂.txt", text))
    assert rep.detail_rows == 1
    # 以 [ 开头但认不出的行 → text_unparsable，必须指到第 8 行
    w = [i for i in rep.warnings() if i.code == "text_unparsable"]
    assert w and w[0].line_no == 8
    # 不以 [ 开头的杂行 → text_unknown_line，指到第 9 行
    u = [i for i in rep.warnings() if i.code == "text_unknown_line"]
    assert u and u[0].line_no == 9
    assert all(i.line_no is not None for i in rep.warnings())


def test_text_item_without_count_is_reported(tmp_path):
    from fixtext_report import parse_report

    text = ("替换统计 · 测试书\n命中数：3\n\n——— 详细词条 ———\n"
            "    ['before' => \"A\", 'after' => \"B\"],\n")
    rep = parse_report(_write(tmp_path, "缺次数.txt", text))
    assert rep.detail_rows == 0
    assert any(i.code == "text_missing_count" for i in rep.warnings())


def test_section_mismatch_is_reported(tmp_path):
    """小节自报 10 次、实际读到 6 次：两个数都保留 + 一条提示。"""
    from fixtext_report import parse_report

    text = ("替换统计 · 测试书\n命中数：6\n\n——— 详细词条 ———\n"
            "    // 【替换次数报告】x\n"
            "    // 总替换次数：【10】 | 重复次数大于 0 的总替换次数：【10】\n"
            "    ['before' => \"A\", 'after' => \"B\"], // 替换次数: 【3】 | 序号：【1/2】\n"
            "    ['before' => \"C\", 'after' => \"D\"], // 替换次数: 【3】 | 序号：【2/2】\n")
    rep = parse_report(_write(tmp_path, "小节对不上.txt", text))
    assert rep.detail_total == 6
    assert rep.sections[0].stated_total == 10
    codes = {i.code for i in rep.warnings()}
    assert "section_total_mismatch" in codes


def test_multi_section_report_merges_rows(tmp_path):
    """多段明细（上游按每本被比对的书各出一段）要全部读进来。"""
    from fixtext_report import parse_report

    text = ("替换统计 · 测试书\n命中数：6\n\n——— 详细词条 ———\n"
            "    // 【替换次数报告】甲\n"
            "    // 总替换次数：【3】\n"
            "    ['before' => \"A\", 'after' => \"B\"], // 替换次数: 【3】 | 序号：【1/1】\n"
            "    // 【替换次数报告】乙\n"
            "    // 总替换次数：【3】\n"
            "    ['before' => \"C\", 'after' => \"D\"], // 替换次数: 【3】 | 序号：【1/1】\n")
    rep = parse_report(_write(tmp_path, "两段.txt", text))
    assert [s.label for s in rep.sections] == ["甲", "乙"]
    assert rep.detail_rows == 2 and rep.detail_total == 6
    assert rep.hits_consistent is True
    assert any("2 段明细" in n for n in rep.notes)


# ---------------------------------------------------------------------------
# 4. 目录定位：只认「替换统计」，不把正文当报告
# ---------------------------------------------------------------------------

def test_parse_report_dir_picks_stats_csv(tmp_path):
    from fixtext_report import parse_report_dir

    out = tmp_path / "导出"
    out.mkdir()
    (out / "测试书.txt").write_text("正文正文正文\n", encoding="utf-8")
    (out / "测试书替换统计.csv").write_text(
        _csv(hits="6") + "A,B,3\nC,D,3\n", encoding="utf-8")
    (out / "测试书替换统计.txt").write_text(
        "替换统计 · 测试书\n命中数：6\n", encoding="utf-8")
    rep = parse_report_dir(out)
    assert rep.ok and rep.fmt == "csv"
    assert rep.source.endswith("测试书替换统计.csv")


def test_parse_report_dir_prefers_text_when_asked(tmp_path):
    from fixtext_report import parse_report_dir

    out = tmp_path / "导出2"
    out.mkdir()
    (out / "测试书替换统计.csv").write_text(_csv(hits="6"), encoding="utf-8")
    (out / "测试书替换统计.txt").write_text(
        "替换统计 · 测试书\n命中数：6\n", encoding="utf-8")
    rep = parse_report_dir(out, prefer_csv=False)
    assert rep.fmt == "text"


def test_parse_report_dir_without_report(tmp_path):
    from fixtext_report import parse_report_dir

    out = tmp_path / "空导出"
    out.mkdir()
    (out / "测试书.txt").write_text("正文\n", encoding="utf-8")
    rep = parse_report_dir(out)
    assert rep.ok is False
    assert any(i.code == "report_not_found" for i in rep.warnings())


# ---------------------------------------------------------------------------
# 5. 数据结构：可序列化、可重建、供 E9 直接消费
# ---------------------------------------------------------------------------

def test_to_dict_roundtrips_as_json():
    from fixtext_report import parse_report

    rep = parse_report(REAL_CSV)
    payload = rep.to_dict()
    again = json.loads(json.dumps(payload, ensure_ascii=False))
    assert again == payload
    assert again["hits"] == 2638
    assert again["detail_rows"] == 2477
    assert len(again["rows"]) == 2477
    assert again["libraries"][0]["applied_rules"] == 151192
    # E9 需要的能力都在这份 dict 里，不需要再开文件
    assert again["hits_by_library"] == []
    assert again["hits_consistent"] is True


def test_hits_by_library_is_empty_not_zero():
    """报告不支持按词库拆命中 → 返回空列表，绝不能返回「每个词库 0 次」。"""
    from fixtext_report import parse_report

    rep = parse_report(REAL_CSV)
    assert rep.hits_by_library() == []
    assert any("没有每个词库各命中多少次" in n for n in rep.notes)


def test_dict_style_access():
    from fixtext_report import parse_report

    rep = parse_report(REAL_CSV)
    assert rep["hits"] == 2638
    assert rep.get("title") == "炮火弧线"
    assert rep.get("不存在", "兜底") == "兜底"
    with pytest.raises(KeyError):
        rep["不存在"]


def test_top_and_search_edge_cases():
    from fixtext_report import parse_report

    rep = parse_report(REAL_CSV)
    assert rep.top(0) == []
    assert rep.search("") == rep.rows
    assert rep.search("绝不存在的字符串") == []


# ---------------------------------------------------------------------------
# 6. 纯解析层：不依赖 Qt / 界面 / 管线（子进程里断言）
# ---------------------------------------------------------------------------

_PROBE = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, {root!r})
    import fixtext_report as R
    rep = R.parse_report({path!r})
    banned = [m for m in ("PySide6", "shiboken6", "fixtext_ui",
                          "fixtext_pipeline", "fixtext_import", "epubtext")
              if m in sys.modules]
    print(rep.hits, rep.detail_rows, "BANNED=" + ",".join(banned))
    """
)


def test_parser_does_not_pull_qt_or_ui_or_pipeline():
    """纯解析层必须能在没有界面、没有引擎的环境里跑。"""
    code = _PROBE.format(root=str(ROOT), path=str(REAL_CSV))
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, env=env, timeout=120)
    assert proc.returncode == 0, proc.stderr
    head, _, banned = proc.stdout.strip().partition("BANNED=")
    hits, rows = head.split()
    assert int(hits) == 2638 and int(rows) == 2477
    assert banned.strip() == "", f"解析层把不该依赖的东西拉进来了：{banned}"


# ---------------------------------------------------------------------------
# 7. 出厂词库 / 引擎包整树零变更
# ---------------------------------------------------------------------------

def _tree_sha(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def test_rules_tree_untouched():
    """出厂词库整树 sha 必须等于合并包登记值（本卡只读它）。"""
    rules = ROOT / "data" / "rules"
    assert rules.is_dir()
    sha = _tree_sha(rules)
    # 与 data/rules/builtin_index_meta.json 登记的 before.json 指纹交叉核对
    meta = json.loads((rules / "builtin_index_meta.json").read_text(encoding="utf-8"))
    before_sha = hashlib.sha256((rules / "before.json").read_bytes()).hexdigest()
    assert before_sha == meta["rules_before_sha256"], "出厂 before.json 被改动了"
    assert sha  # 整树指纹（供验收脚本比对，不写死数值）


def test_vendor_tree_untouched():
    vendor = ROOT / "pipeline" / "vendor"
    assert vendor.is_dir()
    assert _tree_sha(vendor)
