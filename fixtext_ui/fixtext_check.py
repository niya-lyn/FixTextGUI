"""检查问题的真实数据层（无 Qt 依赖，可单独测试）
=================================================

把「引号检查」阶段产出的真实报告读成界面能直接渲染的条目：

    运行目录/04_quote/<书名>.report.json    全量事件（line / char / msg）
    运行目录/04_quote/quote_summary.json    汇总（error_count / checked_file / chars）

刻意**不读** ``quote_summary.json`` 的 ``first_errors``：那个字段只保留前 20 条，
用它渲染会让长报告静默丢数据。条目一律来自报告 JSON 的 ``events``，并用
``error_count`` 交叉核对——两者不一致时如实报告，不假装没问题。

复核标记（已修复 / 已跳过）落在运行目录内，重启后仍在。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: 每条错误在界面上取多长的上下文（字符数）
CTX_BEFORE = 16
CTX_AFTER = 16

QUOTE_STAGE_DIR = "04_quote"
MARKS_FILE = "check_marks.json"

#: 报告里的报错文案 → 人话分类 + 可执行建议 + 自动改法。
#: 报错文案来自引号检查器，界面只展示这里映射后的说法。
#: ``action`` 只给**能被证据支持**的改法：缺引号就在缺口处补一个引号；
#: 交叉错乱 / 嵌套 / 空引号一律留给人工——单看一个字符位置改不准。
#: 顺序有意义：「缺左」先于「交叉」判定，避免复合文案被抢走。
_RULES: tuple[tuple[tuple[str, ...], str, str, dict | None], ...] = (
    (
        ("缺左双引号", "缺左引号"),
        "缺左引号",
        "这句话前面少了一个左引号，补上「“」即可。",
        dict(mode="prepend", char="“"),
    ),
    (
        ("缺左单引号",),
        "缺左引号",
        "这句话前面少了一个左单引号，补上「‘」即可。",
        dict(mode="prepend", char="‘"),
    ),
    (
        ("缺右双引号", "缺右引号"),
        "缺右引号",
        "这段话结尾少了一个右引号，补上「”」即可。",
        dict(mode="append", char="”"),
    ),
    (
        ("缺右单引号",),
        "缺右引号",
        "这段话结尾少了一个右单引号，补上「’」即可。",
        dict(mode="append", char="’"),
    ),
    (
        ("嵌套了独立双引号", "应规范使用单引号"),
        "双套双引号",
        "外层双引号里又套了一层双引号，把里面那层改成单引号。",
        None,
    ),
    (
        ("交叉错乱",),
        "引号交叉错乱",
        "内外层引号的开合顺序对不上，需要按整段话重新配对。",
        None,
    ),
    (
        ("空引号",),
        "空引号",
        "这里是一对没有内容的引号，删掉这一对即可。",
        None,
    ),
    (
        ("多层嵌套",),
        "多层嵌套未闭合",
        "多层引号挤在同一行里，需要人工判断该在哪一层断开。",
        None,
    ),
)

#: 分类排序权重（界面上先看能自动处理的）
_ORDER = {name: i for i, name in enumerate(
    ("缺左引号", "缺右引号", "空引号", "双套双引号", "引号交叉错乱",
     "多层嵌套未闭合", "其他引号问题"))}

#: HTML 标签（电子书的章节正文是带标记的），只用于取上下文时去掉
_TAG_RE = __import__("re").compile(r"<[^>]{1,200}>")


def classify(msg: str) -> tuple[str, str, dict | None]:
    """报错文案 → (分类, 建议, 自动改法)。认不出的一律归人工。"""
    text = str(msg or "")
    for keys, kind, advice, action in _RULES:
        if any(k in text for k in keys):
            return kind, advice, action
    return "其他引号问题", "这处需要人工看一眼再改。", None


def apply_action(item: dict) -> str:
    """按自动改法算出修复后的片段；无自动改法时原样返回。"""
    action = item.get("action") or {}
    hl = str(item.get("hl") or "")
    if action.get("mode") == "prepend":
        return action.get("char", "") + hl
    if action.get("mode") == "append":
        return hl + action.get("char", "")
    return hl


def plain_line(raw: str) -> str:
    """去掉电子书排版标记与行尾符，只留可读正文。"""
    return _TAG_RE.sub("", raw).replace("\r", "").replace("\n", "").strip(" \t\u3000")


def _pick_quote_files(run_dir: Path) -> tuple[Path | None, Path | None]:
    """在运行目录里定位引号报告：先认汇总自述，再按目录枚举。"""
    stage = Path(run_dir) / QUOTE_STAGE_DIR
    report: Path | None = None
    summary: Path | None = None
    if stage.is_dir():
        summary_p = stage / "quote_summary.json"
        if summary_p.exists():
            summary = summary_p
            try:
                said = json.loads(summary_p.read_text(encoding="utf-8")).get("report_json")
                if said and Path(said).exists():
                    report = Path(said)
            except Exception:
                report = None
        if report is None:
            found = sorted(stage.glob("*.report.json"))
            if found:
                report = found[0]
    return report, summary


def _read_lines(path: Path, wanted: set[int]) -> dict[int, str]:
    """只读需要的行（整书十万级行，不做一次性全量载入）。"""
    out: dict[int, str] = {}
    if not wanted:
        return out
    top = max(wanted)
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        for i, raw in enumerate(fh, start=1):
            if i in wanted:
                out[i] = plain_line(raw)
            if i >= top:
                break
    return out


def _slice_context(line_text: str, char: int) -> tuple[str, str, str]:
    """在报错位置附近切出「前文 / 问题片段 / 后文」。

    问题片段取离报错点最近的引号字符本身——引号问题看的就是那个引号。
    """
    text = line_text or ""
    if not text:
        return "", "", ""
    pos = max(0, min(int(char or 0), len(text) - 1))
    quote_pos = pos
    # 在 ±12 字符窗口里找最近的引号，找不到就用报错点本身
    lo, hi = max(0, pos - 12), min(len(text), pos + 13)
    candidates = [i for i in range(lo, hi) if text[i] in "“”‘’「」『』"]
    if candidates:
        quote_pos = min(candidates, key=lambda i: abs(i - pos))
    span = 1
    hl = text[quote_pos:quote_pos + span]
    pre = text[max(0, quote_pos - CTX_BEFORE):quote_pos]
    post = text[quote_pos + span:quote_pos + span + CTX_AFTER]
    return pre, hl, post


def load_report(run_dir: str | Path) -> dict[str, Any]:
    """把一个运行目录读成检查页要的数据。

    返回::

        {
          "ok": bool,              # 报告读到了没有
          "reason": str,           # ok=False 时的人话原因
          "book": str,             # 书名（报告文件名去掉后缀）
          "run_dir": str,
          "checked_file": str,
          "chars": int,
          "declared": int,         # 汇总里声明的错误数（error_count）
          "found": int,            # 报告里实际读到的条数
          "consistent": bool,      # 两者是否一致
          "auto_fixable": int,     # 有自动改法的条数
          "manual": int,           # 需人工判断的条数
          "pages": int,
          "items": [ {line, char, msg, type, advice, fix, pre, hl, post}, ... ],
        }
    """
    run_dir = Path(run_dir)
    report_path, summary_path = _pick_quote_files(run_dir)
    if report_path is None:
        return _empty(f"这次运行没有留下引号检查报告（{QUOTE_STAGE_DIR} 目录为空）。",
                      run_dir=run_dir)

    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 坏文件按人话原因返回，不抛栈
        return _empty(f"引号检查报告读不出来：{exc.__class__.__name__}。",
                      run_dir=run_dir)

    events = payload.get("events") or []
    declared = payload.get("errCount")
    checked_file = ""
    chars = 0
    if summary_path is not None:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(summary.get("error_count"), int):
                declared = summary["error_count"]
            checked_file = str(summary.get("checked_file") or "")
            chars = int(summary.get("chars") or 0)
        except Exception:
            pass

    items: list[dict[str, Any]] = []
    wanted = {int(e.get("line") or 0) for e in events if e.get("line")}
    text_lines: dict[int, str] = {}
    if not checked_file:
        # 汇总缺失时退回报告所在目录的正文（与报告同名的 .txt）
        sibling = report_path.with_suffix("").with_suffix(".txt")
        if sibling.exists():
            checked_file = str(sibling)
    if checked_file and Path(checked_file).exists():
        text_lines = _read_lines(Path(checked_file), wanted)

    for e in events:
        line_no = int(e.get("line") or 0)
        char = int(e.get("char") or 0)
        msg = str(e.get("msg") or "")
        kind, advice, action = classify(msg)
        pre, hl, post = _slice_context(text_lines.get(line_no, ""), char)
        items.append(dict(
            line=line_no, char=char, msg=msg,
            type=kind, advice=advice, action=action,
            pre=pre, hl=hl, post=post, state=None,
        ))

    items.sort(key=lambda it: (_ORDER.get(it["type"], 99), it["line"]))
    found = len(items)
    consistent = (declared is None) or (int(declared) == found)
    return {
        "ok": True,
        "reason": "",
        "book": _book_name(report_path),
        "run_dir": str(run_dir),
        "checked_file": checked_file,
        "chars": chars,
        "declared": int(declared) if isinstance(declared, int) else found,
        "found": found,
        "consistent": bool(consistent),
        "auto_fixable": sum(1 for it in items if it["action"]),
        "manual": sum(1 for it in items if not it["action"]),
        "pages": 0,
        "items": items,
    }


def _empty(reason: str, run_dir: Path | None = None) -> dict[str, Any]:
    return {
        "ok": False, "reason": reason, "book": "",
        "run_dir": str(run_dir) if run_dir else "",
        "checked_file": "", "chars": 0, "declared": 0, "found": 0,
        "consistent": True, "auto_fixable": 0, "manual": 0,
        "pages": 0, "items": [],
    }


def _book_name(report_path: Path) -> str:
    stem = report_path.name
    if stem.endswith(".report.json"):
        stem = stem[: -len(".report.json")]
    return stem


# ---------------------------------------------------------------------------
# 复核标记（已修复 / 已跳过）——按行号 + 报错文案定位，落盘在运行目录内
# ---------------------------------------------------------------------------

def load_marks(run_dir: str | Path) -> dict[str, str]:
    """读回上次的复核标记，键是 ``行号|报错文案``。"""
    path = Path(run_dir) / MARKS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    marks = raw.get("marks") if isinstance(raw, dict) else None
    return dict(marks) if isinstance(marks, dict) else {}


def save_marks(run_dir: str | Path, marks: dict[str, str]) -> None:
    """保存复核标记；失败不阻断界面（只是下次要重新标）。"""
    path = Path(run_dir) / MARKS_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"marks": dict(marks)}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    except Exception:
        pass


def mark_key(item: dict) -> str:
    return f"{item.get('line')}|{item.get('msg')}"


def apply_marks(data: dict[str, Any], marks: dict[str, str]) -> dict[str, Any]:
    """把落盘的标记贴回条目上（界面重开时看到上次的进度）。"""
    for it in data.get("items") or []:
        state = marks.get(mark_key(it))
        if state in ("fixed", "skip"):
            it["state"] = state
    return data
