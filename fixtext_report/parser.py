"""替换报告的解析（V1.1-E8 交付物①）。

支持 V1 导出时落下的**两种真实形态**（都在 ``fixtext_ui/fixtext_export.py``
的 ``build_stats`` 里生成，本模块的解析口径按该函数逐行对齐）：

A. ``<书名>替换统计.csv``
   带 BOM（``utf-8-sig``）、CRLF 换行、``csv.writer`` 默认的引号规则。结构是
   **两段**，中间用一行空行隔开::

       项目,值
       书名,炮火弧线
       作者,未填写
       生成时间,2026-11-05 13:18:04
       命中数,2638
       涉及词库,通用校对词库（本次应用规则 151192 条，去重后 149969 条）；本书专有词库（提取 3037 条）
       <空行>
       改前,改后,替换次数
       ，长长的叹了口,，长长地叹了口,10
       ...

B. ``<书名>替换统计.txt``
   无 BOM、LF 换行。前 5 行是「字段：值」，然后一段说明，最后是
   「——— 详细词条 ———」之后的分段明细（PHP 数组字面量风格，带转义）::

       替换统计 · 炮火弧线
       作者：未填写
       生成时间：...
       命中数：2638
       涉及词库：...
       ...
       ——— 详细词条 ———
           // 【替换次数报告】sample
           // 总替换次数：【2638】 | 重复次数大于 0 的总替换次数：【2638】
           // 下方只显示替换次数大于 0 的内容
           ['before' => "，长长的叹了口", 'after' => "，长长地叹了口"], // 替换次数: 【10】 | 序号：【1/2477】

解析原则
--------

* **不崩、不静默。** 缺列 / 空行 / 数字不是数字 / 编码异常，都记一条
  :class:`~.model.Issue`（带行号、缺什么、怎么处理了），继续往下读。
* **不猜数。** 报告没写的字段留 ``None``；同一量在两处不一致时两个数都保留，
  另出一条提示。
* **不摊派。** 报告没有按词库拆命中数，就不编一个（理由见 ``model.py``）。
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from .model import (
    DETAIL_COLUMNS,
    FMT_CSV,
    FMT_TEXT,
    KEY_AUTHOR,
    KEY_GENERATED_AT,
    KEY_HITS,
    KEY_LIBRARIES,
    KEY_TITLE,
    LEVEL_INFO,
    LEVEL_WARNING,
    Issue,
    Report,
    Row,
    Section,
    make_report,
    summarize_libraries,
)
from .textread import read_text

#: 能认出「这是替换报告」的最小特征：至少要有这两列中的一列
_REQUIRED_HINT = ("改前", "命中数")

#: TXT 明细段的分隔标题（导出侧原样写的就是这一串）
_TEXT_DETAIL_MARK = "——— 详细词条 ———"

#: TXT 明细节标题（每段一个）
_SECTION_LABEL = re.compile(r"//\s*【替换次数报告】\s*(.*)")

#: 段落自报总量
_SECTION_TOTAL = re.compile(r"总替换次数：【(\d+)】")

#: 段落自报条数（序号里的分母）
_SECTION_ENTRIES = re.compile(r"序号：【\d+/(\d+)】")

#: 段落生效下限
_SECTION_THRESHOLD = re.compile(r"重复次数大于\s*(\d+)")

#: 单条明细：['before' => "X", 'after' => "Y"], // 替换次数: 【N】 | 序号：【i/n】
_TEXT_ITEM = re.compile(
    r"\['before'\s*=>\s*\"((?:[^\"\\]|\\.)*)\",\s*"
    r"'after'\s*=>\s*\"((?:[^\"\\]|\\.)*)\"\],?\s*"
    r"//\s*替换次数:\s*【(\d+)】"
)

#: 多行写法（上游 multi_line 分支，理论上报告里不会出现，防御式支持）
_TEXT_ITEM_MULTI = re.compile(
    r"\[(?:\s*'before'\s*=>\s*\"((?:[^\"\\]|\\.)*)\",\s*"
    r"'after'\s*=>\s*\"((?:[^\"\\]|\\.)*)\"[^\]]*?)\],?\s*"
    r"(?://\s*替换次数:\s*【(\d+)】)?"
)

_TEXT_ESCAPE = (("\\\"", '"'), ("\\\\", "\\"), ("\\n", "\n"), ("\\t", "\t"))

#: 明细里能容忍的最大次数（超过多半是列错位读进来的年份之类）
_MAX_REASONABLE_COUNT = 10_000_000


class ReportParseError(RuntimeError):
    """报告完全读不动（找不到文件 / 目录为空）。不常用：多数异常走 ``Report.ok=False``。"""


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def parse_report(path: str | Path) -> Report:
    """读一份替换报告（``.csv`` 或 ``.txt``），自动按扩展名选解析器。

    不抛异常：读不动就返回 ``ok=False`` + ``issues``。扩展名不认识时先按 CSV
    试，认出「改前/改后」表头再按 CSV，否则按文本。
    """
    p = Path(path)
    if not p.exists():
        rep = make_report(fmt="", source=str(p), total_lines=0)
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="file_missing",
            message=f"没有找到这份报告文件：{p.name}。如果刚导出过，可能被移动到别处或删除了。",
            detail=str(p)))
        return rep
    if p.is_dir():
        rep = make_report(fmt="", source=str(p), total_lines=0)
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="file_is_dir",
            message=f"「{p.name}」是一个文件夹，不是报告文件，请选择报告文件本身。",
            detail=str(p)))
        return rep

    suffix = p.suffix.lower()
    try:
        text, codec, label, fallback = read_text(p)
    except OSError as exc:
        rep = make_report(fmt="", source=str(p), total_lines=0)
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="file_unreadable",
            message=f"这份报告打不开（{exc.strerror or exc.__class__.__name__}）。"
                    "它可能正在被别的程序占用，或者没有读取权限。",
            detail=f"{exc.__class__.__name__}: {exc}"))
        return rep

    total_lines = len(text.splitlines())
    if suffix == ".csv":
        rep = parse_csv_text(text)
        rep.fmt = FMT_CSV
    elif suffix in (".txt", ".text", ""):
        rep = parse_text_text(text)
        rep.fmt = FMT_TEXT
    else:
        # 扩展名不认识：看内容里有没有 CSV 的两列表头
        head = "\n".join(text.splitlines()[:12])
        if head.lstrip("\ufeff").startswith("项目") or "改前,改后" in head:
            rep = parse_csv_text(text)
            rep.fmt = FMT_CSV
        else:
            rep = parse_text_text(text)
            rep.fmt = FMT_TEXT

    rep.source = str(p)
    rep.total_lines = total_lines
    rep.read_note = _read_note(label, fallback, codec)
    if fallback:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="encoding_fallback",
            message="这份报告的字符格式没能完全确定，我按最可能的一种读了出来；"
                    "个别字可能显示不正常，但数字和词条仍然可用。",
            detail=f"codec={codec}"))
    _finalize(rep)
    return rep


def parse_report_dir(directory: str | Path, *, prefer_csv: bool = True) -> Report:
    """在一个目录里找同名的那份报告。

    导出侧把三份文件放在同一目录：``<书名>.txt`` / ``<书名>替换统计.txt`` /
    ``<书名>替换统计.csv``。这里只认「替换统计」，避免把正文当报告。
    """
    d = Path(directory)
    if not d.is_dir():
        rep = make_report(fmt="", source=str(d), total_lines=0)
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="dir_missing",
            message=f"没有找到这个文件夹：{d.name}。",
            detail=str(d)))
        return rep

    csvs = sorted(d.glob("*替换统计.csv"))
    txts = sorted(d.glob("*替换统计.txt"))
    picked: Path | None = None
    if prefer_csv and csvs:
        picked = csvs[0]
    elif txts:
        picked = txts[0]
    elif csvs:
        picked = csvs[0]

    if picked is None:
        rep = make_report(fmt="", source=str(d), total_lines=0)
        other = sorted(p.name for p in d.glob("*替换统计*"))
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="report_not_found",
            message=("这个文件夹里没有「替换统计」报告。"
                     if not other else
                     f"这个文件夹里的报告文件名认不出来：{'、'.join(other[:3])}。"),
            detail=str(d)))
        return rep
    return parse_report(picked)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def parse_csv_text(text: str) -> Report:
    """解析 ``<书名>替换统计.csv`` 的文本内容。"""
    lines = text.splitlines()
    rep = make_report(fmt=FMT_CSV, source="", total_lines=len(lines))
    if not text.strip():
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="empty_file",
            message="这份报告是空的，里面没有任何内容。可以在导出后重新生成一份。"))
        return rep

    # csv 需要行号：自己切行再喂给 reader，才能把行号带进提示
    records = _csv_records(text)
    if not records:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="no_rows",
            message="这份报告里没有可读的行。"))
        return rep

    _fill_csv(rep, records)
    return rep


def _csv_records(text: str) -> list[tuple[int, list[str]]]:
    """逐行读 CSV，返回 ``(行号, 字段列表)``。

    用标准 ``csv`` 模块以正确处理引号内的逗号 / 换行；行号取「这条记录结束的
    物理行」。空行保留（调用方要知道那里是分隔），但这里直接跳过连续空行。
    """
    reader = csv.reader(io.StringIO(text, newline=""))
    records: list[tuple[int, list[str]]] = []
    try:
        for fields in reader:
            records.append((reader.line_num, fields))
    except csv.Error as exc:
        # 整份读崩：把已经读到的留住，另给一条提示
        records.append((reader.line_num, []))
        records.append((-1, ["__csv_error__", str(exc)]))
    return records


def _fill_csv(rep: Report, records: list[tuple[int, list[str]]]) -> None:
    stage = "kv"
    detail_header_seen = False
    detail_cols: dict[str, int] | None = None
    blank_seen = 0
    csv_error: str = ""

    for line_no, fields in records:
        if line_no == -1:
            csv_error = fields[1] if len(fields) > 1 else ""
            break
        cells = [c.strip() for c in fields]
        if not any(cells):
            # 空行：CSV 形态里它是汇总区与明细表之间的分隔
            if stage == "kv" and blank_seen == 0 and not (rep.title or rep.hits is not None):
                rep.issues.append(Issue(
                    level=LEVEL_INFO, code="leading_blank",
                    message="报告开头有 1 行空白，已跳过。", line_no=line_no))
            blank_seen += 1
            continue
        blank_seen = 0

        # 明细表头
        if _is_detail_header(cells):
            detail_header_seen = True
            stage = "detail"
            detail_cols = {name: i for i, name in enumerate(cells)
                           if name in DETAIL_COLUMNS}
            missing = [c for c in DETAIL_COLUMNS if c not in detail_cols]
            if missing:
                rep.issues.append(Issue(
                    level=LEVEL_WARNING, code="detail_header_missing_column",
                    message=f"明细表的表头少了「{'、'.join(missing)}」这一列，"
                            "这些行我按「改前/改后/次数」的固定顺序尝试读取。",
                    line_no=line_no, detail=f"header={cells}"))
            continue

        if stage == "detail":
            _csv_detail_row(rep, cells, line_no, detail_cols)
        else:
            _csv_kv_row(rep, cells, line_no)

    if csv_error:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="csv_broken",
            message="这份报告的格式在中间断掉了，断掉之前的内容我都读出来了，"
                    "后面的部分可能不完整。建议重新导出一份。",
            detail=csv_error))

    if not detail_header_seen:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="no_detail_header",
            message="这份报告里没有找到「改前 / 改后 / 替换次数」这张明细表，"
                    "只读到了上面的汇总信息。" if rep.hits is not None or rep.title
                    else "这份报告里既没有汇总信息也没有明细表，可能不是替换统计报告。"))
    elif not rep.rows:
        rep.notes.append("明细表是空的：这本书没有产生任何替换（或者还没跑过校正）。")


def _is_detail_header(cells: list[str]) -> bool:
    present = {c for c in cells if c in DETAIL_COLUMNS}
    return len(present) >= 2


def _csv_kv_row(rep: Report, cells: list[str], line_no: int) -> None:
    """键值区的一行：``项目,值``。"""
    if len(cells) < 2:
        # 只有一列：认得出字段名就当「值为空」
        key = cells[0] if cells else ""
        if key in (KEY_TITLE, KEY_AUTHOR, KEY_GENERATED_AT, KEY_HITS, KEY_LIBRARIES):
            rep.issues.append(Issue(
                level=LEVEL_WARNING, code="kv_missing_value",
                message=f"第 {line_no} 行只有「{key}」没有对应的值，这一项我按空白处理。",
                line_no=line_no, detail=f"cells={cells}"))
            _assign_kv(rep, key, "", line_no, missing=True)
            return
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="kv_unknown",
            message=f"第 {line_no} 行只有一列，看不出是什么，已跳过。",
            line_no=line_no, detail=f"cells={cells}"))
        return

    key, value = cells[0], cells[1]
    # 值里可能自己带逗号（词库那一行就有），把后面的接回去
    if len(cells) > 2:
        value = ",".join(cells[1:])
    if key == "项目" and value == "值":
        return                                    # 表头
    _assign_kv(rep, key, value, line_no)


def _assign_kv(rep: Report, key: str, value: str, line_no: int, *, missing: bool = False) -> None:
    if key == KEY_TITLE:
        rep.title = value
    elif key == KEY_AUTHOR:
        rep.author = value
    elif key == KEY_GENERATED_AT:
        rep.generated_at = value
    elif key == KEY_HITS:
        rep.hits = _parse_count(rep, value, line_no, KEY_HITS, missing=missing)
    elif key == KEY_LIBRARIES:
        rep.libraries_text = value
        entries, raw = summarize_libraries(value)
        rep.libraries = entries
        rep.libraries_text = raw
    else:
        rep.extra_fields[key] = value
        rep.issues.append(Issue(
            level=LEVEL_INFO, code="kv_extra",
            message=f"第 {line_no} 行有个不认识的字段「{key}」，原样保留，不影响其它内容。",
            line_no=line_no, detail=f"{key}={value}"))


def _csv_detail_row(rep: Report, cells: list[str], line_no: int,
                    cols: dict[str, int] | None) -> None:
    """明细表的一行。缺列 / 次数不是数字都按「逐行一条提示」处理。"""
    idx_b = cols.get("改前") if cols else 0
    idx_a = cols.get("改后") if cols else 1
    idx_c = cols.get("替换次数") if cols else 2

    def pick(i: int) -> str | None:
        return cells[i] if i is not None and i < len(cells) else None

    before, after, count_raw = pick(idx_b), pick(idx_a), pick(idx_c)
    need = max(i for i in (idx_b, idx_a, idx_c) if i is not None)

    if len(cells) <= need or before is None or after is None or count_raw is None:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="detail_short_row",
            message=(f"第 {line_no} 行的列数不够（只有 {len(cells)} 列，"
                     "需要改前、改后、替换次数三列），这一行已跳过。"),
            line_no=line_no, detail=f"cells={cells}"))
        rep.issues[-1].message += _hint_for_short(cells)
        return

    count = _parse_count(rep, count_raw, line_no, "替换次数")
    if count is None:
        return
    if count < 0:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="detail_negative_count",
            message=f"第 {line_no} 行的替换次数是负数（{count_raw}），这一行已跳过。",
            line_no=line_no, detail=f"cells={cells}"))
        return
    if count > _MAX_REASONABLE_COUNT:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="detail_count_too_big",
            message=f"第 {line_no} 行的替换次数（{count_raw}）大得不像替换次数，"
                    "可能是列错位了，这一行已跳过。",
            line_no=line_no, detail=f"cells={cells}"))
        return

    if before == "" and after == "":
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="detail_blank_words",
            message=f"第 {line_no} 行的「改前」和「改后」都是空的，看不出改了什么，这一行已跳过。",
            line_no=line_no, detail=f"cells={cells}"))
        return

    rep.rows.append(Row(before=before, after=after, count=count, line_no=line_no))


def _hint_for_short(cells: list[str]) -> str:
    if not cells:
        return "这一行是空的。"
    return ""


# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------

def parse_text_text(text: str) -> Report:
    """解析 ``<书名>替换统计.txt`` 的文本内容。"""
    lines = text.splitlines()
    rep = make_report(fmt=FMT_TEXT, source="", total_lines=len(lines))
    if not text.strip():
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="empty_file",
            message="这份报告是空的，里面没有任何内容。可以在导出后重新生成一份。"))
        return rep

    detail_start = None
    for i, line in enumerate(lines):
        if line.strip() == _TEXT_DETAIL_MARK:
            detail_start = i
            break

    header_lines = lines if detail_start is None else lines[:detail_start]
    _fill_text_header(rep, header_lines)

    if detail_start is None:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="no_detail_section",
            message="这份报告里没有找到「详细词条」这一段，只读到了上面的汇总信息。"
                    if (rep.hits is not None or rep.title)
                    else "这份报告里既没有汇总信息也没有明细，可能不是替换统计报告。"))
    else:
        _fill_text_details(rep, lines, detail_start + 1)
        if not rep.rows:
            rep.notes.append("明细是空的：这本书没有产生任何替换（或者还没跑过校正）。")
    return rep


def _fill_text_header(rep: Report, lines: list[str]) -> None:
    """前几行「字段：值」。

    第一行是 ``替换统计 · 书名``（不是「字段：值」），单独认。
    """
    for i, line in enumerate(lines, start=1):
        s = line.strip()
        if not s:
            continue
        if s.startswith("替换统计 ·"):
            rep.title = s.split("·", 1)[1].strip()
            continue
        if s.startswith("说明："):
            rep.notes.append("报告自带的说明：" + s[3:].strip())
            continue
        if "：" not in s:
            # 不是字段行（例如「本次替换命中即上表所列词条的出现次数之和。」）
            continue
        key, value = s.split("：", 1)
        key, value = key.strip(), value.strip()
        if key in (KEY_TITLE, KEY_AUTHOR, KEY_GENERATED_AT, KEY_HITS, KEY_LIBRARIES):
            _assign_kv(rep, key, value, i)
        else:
            rep.notes.append(f"报告里还有一行说明：{s}")


def _fill_text_details(rep: Report, lines: list[str], start: int) -> None:
    """「详细词条」段：按小节切，逐条读。

    小节的三项自报数（总替换次数 / 明细条数 / 次数下限）分散在注释行与每条
    明细的序号里：注释行只有「总替换次数」，「序号：【i/n】」的 ``n`` 在**明细行**
    上，所以条数分母要从明细行取（实测 V1 报告就是这么写的）。
    """
    current: Section | None = None
    section_seen = False

    for offset, line in enumerate(lines[start:], start=start + 1):
        s = line.strip()
        if not s:
            continue
        if s.startswith("//"):
            m = _SECTION_LABEL.search(s)
            if m:
                label = m.group(1).strip()
                label = re.sub(r"\s*\.?patch$", "", label)
                _close_section(rep, current)
                current = Section(label=label)
                section_seen = True
                continue
            if current is not None:
                t = _SECTION_TOTAL.search(s)
                if t and current.stated_total is None:
                    current.stated_total = int(t.group(1))
                n = _SECTION_ENTRIES.search(s)
                if n and current.stated_entries is None:
                    current.stated_entries = int(n.group(1))
                th = _SECTION_THRESHOLD.search(s)
                if th and current.threshold is None:
                    current.threshold = int(th.group(1))
            continue

        if not s.startswith("["):
            # 明细段里出现别的行：记一条警告，但继续读。
            # 用警告而不是提示——明细段里认不出的行意味着可能有数据没读进来，
            # 用户需要知道「哪一行、我没有装作读过」。
            if section_seen:
                rep.issues.append(Issue(
                    level=LEVEL_WARNING, code="text_unknown_line",
                    message=f"第 {offset} 行在明细里不像词条，已跳过。",
                    line_no=offset, detail=s[:120]))
            continue

        if current is None:                     # 没有小节标题也照读
            current = Section(label="")
            section_seen = True
        # 序号里的分母只在第一条上出现即可确定本小节条数
        if current.stated_entries is None:
            n = _SECTION_ENTRIES.search(s)
            if n:
                current.stated_entries = int(n.group(1))
        item = _parse_text_item(rep, s, offset)
        if item is not None:
            before, after, count = item
            rep.rows.append(Row(before=before, after=after, count=count, line_no=offset))
            current.rows_found += 1
            current.total_found += count

    _close_section(rep, current)
    if not section_seen:
        rep.issues.append(Issue(
            level=LEVEL_INFO, code="text_no_section_label",
            message="明细里没有分节标记，我按单一明细读出来了。"))


def _close_section(rep: Report, section: Section | None) -> None:
    if section is not None:
        rep.sections.append(section)


def _parse_text_item(rep: Report, line: str, line_no: int) -> tuple[str, str, int] | None:
    """读一条 ``['before' => "X", 'after' => "Y"], // 替换次数: 【N】``。

    顺序是先试单行形态，再试多行形态。都对不上就记一条提示。
    """
    m = _TEXT_ITEM.search(line)
    if m:
        before = _unescape(m.group(1))
        after = _unescape(m.group(2))
        count = int(m.group(3))
        if count < 0 or count > _MAX_REASONABLE_COUNT:
            rep.issues.append(Issue(
                level=LEVEL_WARNING, code="text_bad_count",
                message=f"第 {line_no} 行的替换次数（{count}）不像正常数字，这一行已跳过。",
                line_no=line_no, detail=line[:120]))
            return None
        if before == "" and after == "":
            rep.issues.append(Issue(
                level=LEVEL_WARNING, code="text_blank_words",
                message=f"第 {line_no} 行的「改前」和「改后」都是空的，这一行已跳过。",
                line_no=line_no, detail=line[:120]))
            return None
        return before, after, count

    # 缺次数的行（上游 multi_line 分支没有 // 注释时）
    m2 = _TEXT_ITEM_MULTI.search(line)
    if m2 and m2.group(1) and m2.group(2):
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="text_missing_count",
            message=f"第 {line_no} 行的词条没有写替换次数，这一行已跳过（不影响其它行）。",
            line_no=line_no, detail=line[:120]))
        return None

    rep.issues.append(Issue(
        level=LEVEL_WARNING, code="text_unparsable",
        message=f"第 {line_no} 行认不出是一条词条，已跳过。",
        line_no=line_no, detail=line[:120]))
    return None


def _unescape(s: str) -> str:
    for src, dst in _TEXT_ESCAPE:
        s = s.replace(src, dst)
    return s


# ---------------------------------------------------------------------------
# 公共小工具
# ---------------------------------------------------------------------------

def _parse_count(rep: Report, raw: str, line_no: int, field: str,
                 *, missing: bool = False) -> int | None:
    """把「多少次」读成整数；读不动就记一条提示并返回 None。"""
    s = (raw or "").strip().replace(",", "").replace("，", "")
    s = s.replace(" ", "")
    if not s:
        if not missing:
            rep.issues.append(Issue(
                level=LEVEL_WARNING, code="count_blank",
                message=f"第 {line_no} 行的「{field}」是空的，我看不出写了多少，这一项按未知处理。",
                line_no=line_no, detail=f"{field}={raw!r}"))
        else:
            rep.issues.append(Issue(
                level=LEVEL_WARNING, code="count_blank",
                message=f"第 {line_no} 行的「{field}」没有值，这一项按未知处理。",
                line_no=line_no, detail=f"{field}=<missing>"))
        return None
    try:
        return int(s)
    except ValueError:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="count_not_a_number",
            message=f"第 {line_no} 行的「{field}」写的不是数字（读到「{raw}」），这一项按未知处理。",
            line_no=line_no, detail=f"{field}={raw!r}"))
        return None


def _read_note(label: str, fallback: bool, codec: str) -> str:
    if fallback:
        return f"按{label}读取（没能完全确定格式）"
    return f"按{label}读取"


def _finalize(rep: Report) -> None:
    """读完之后统一判 ok / 补口径说明 / 做两处数字对账。"""
    rep.ok = bool(rep.title or rep.hits is not None or rep.rows)

    if not rep.ok:
        rep.issues.append(Issue(
            level=LEVEL_WARNING, code="nothing_recognized",
            message="这份文件里没有认得出替换统计的内容，可能拿错了文件。"))

    # 两处口径对账：报告写的「命中数」 vs 明细合计
    if rep.hits is not None and rep.rows:
        total = rep.detail_total
        if rep.hits != total:
            rep.issues.append(Issue(
                level=LEVEL_WARNING, code="hits_mismatch",
                message=(f"报告的「命中数」写的是 {rep.hits}，"
                         f"但明细里各词条次数加起来是 {total}，两者差了 {abs(rep.hits - total)}。"
                         "我把两个数都保留了，没有替你选一个。"),
                detail=f"hits={rep.hits} detail_total={total}"))

    # 每段自报的总量 / 条数 vs 该段实际读到的（逐段的数，不跨段摊派）
    for sec in rep.sections:
        label = sec.label or "未命名"
        if sec.stated_total is not None and sec.total_found != sec.stated_total:
            rep.issues.append(Issue(
                level=LEVEL_WARNING, code="section_total_mismatch",
                message=(f"「{label}」这段开头写「总替换次数 {sec.stated_total}」，"
                         f"但我从这段明细里读到的次数合计是 {sec.total_found}，"
                         f"差了 {abs(sec.stated_total - sec.total_found)} 次。"
                         "可能是某几行没能读出来，两个数都保留。"),
                detail=f"stated={sec.stated_total} read={sec.total_found}"))
        if sec.stated_entries is not None and sec.rows_found != sec.stated_entries:
            rep.issues.append(Issue(
                level=LEVEL_WARNING, code="section_entries_mismatch",
                message=(f"「{label}」这段写着共 {sec.stated_entries} 条词条，"
                         f"我实际读到 {sec.rows_found} 条，差了 "
                         f"{abs(sec.stated_entries - sec.rows_found)} 条。"),
                detail=f"stated={sec.stated_entries} read={sec.rows_found}"))

    if len(rep.sections) > 1:
        rep.notes.append(
            f"这份报告分了 {len(rep.sections)} 段明细"
            f"（{'、'.join(s.label or '未命名' for s in rep.sections)}），"
            "明细已全部合并给出；各段之间不会有重复词条。")

    # 口径说明：报告不支持按词库拆命中
    if rep.libraries:
        rep.notes.append(
            "报告只写了「命中数合计 + 涉及词库清单」，没有每个词库各命中多少次；"
            "所以按词库的命中拆分给不出来（不是 0，是没有这个数）。")

    # 校正过的书 vs 没跑过校正
    if rep.hits == 0 and not rep.rows:
        rep.notes.append("这本书这次导出时没有跑过校正（报告里也没有明细），命中数为 0。")
