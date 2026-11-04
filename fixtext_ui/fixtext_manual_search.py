# -*- coding: utf-8 -*-
"""手动检索 · 规则集与命中统计（V1.1-E3）

排期 V1.1 §10.4 的三件交付物都落在这一层：

1. **205 条规则迁移** —— 原版 ``src/maps/手动检索规则表.php`` 的规则集，含 3 条
   回调的等价实现（回调**不许**静默降级成字面量，见 ``CALLBACKS``）；
2. **命中统计与排序** —— 每条规则在这本书里命中几次，三种排序（原文件顺序 /
   替换次数 / 优先级颜色分组）；
3. **规则集单测** —— 见 ``tests/test_e3_manual_rules.py``。

三条纪律（E3 卡片自带，别越过）：

- **只读**：本模块没有任何写回原文的入口。``preview()`` 返回**新字符串**，
  原文本对象与磁盘文件都不动；扫描更不落盘。落盘改书属 E4（逐批确认）。
- **不碰装载层**：``vocab_bridge.compose()`` / ``bags.write_round_rules()``
  一个字都不改，本模块只读规则集 JSON。
- **不越界到 E5**：已执行记忆 / 按书排除是 E5 的事，这里不写任何状态。

为什么要 PyPI ``regex`` 而不是标准库 ``re``
-------------------------------------------

原版是 PHP ``preg_replace``（PCRE）。实测 205 条里 **45 条**用了**变宽**
lookbehind（``(?<![a]|abc|abcd)`` 这类），标准库 ``re`` 直接报
``look-behind requires fixed-width pattern``：``re`` 只通过 160/205。
``regex`` 模块 205/205。所以依赖是**硬依赖**，不是优化项——没有它就等于
45 条规则跑不起来，而"跑不起来"绝不能悄悄变成"0 命中"。

命中口径与 PHP 严格对齐
-------------------------

- 修饰符：原版所有规则都走默认 ``umx``：
  ``u`` = UTF-8（Python 侧 Rust 后端默认即 Unicode）、``m`` = 多行、
  ``x`` = 忽略空白与 ``#`` 注释（对应 ``regex.VERBOSE``）。
  **``x`` 是必须的**：规则表里大量断言跨行缩进书写，去掉 ``x`` 全部失效。
- 计数：PHP ``preg_match_all`` 的返回值 = 不重叠匹配个数，
  等价于 ``len(regex.finditer(...))``。
- 替换：PHP 模板里的 ``$1`` / ``$2`` 在 Python 侧逐条翻译成 ``\\g<1>``；
  规则表里**没有** ``$0`` / ``${...}`` / 反斜杠（导出时已核验），
  所以翻译是完备的、不需要通用模板引擎。
- 回调：PHP ``preg_replace_callback`` 传 ``$matches``，未参与匹配的分组是
  **空字符串**（不是 null）。Python 侧 ``m.group(i)`` 对未匹配分组是
  ``None``，这里统一折成 ``""``，否则 3 条回调会拼出 ``None`` 字样。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

try:                                        # 硬依赖：缺了宁可报错也不要静默降级
    import regex as _re
except ImportError as exc:                  # pragma: no cover - 环境缺件
    raise ImportError(
        "手动检索规则集需要 PyPI `regex` 模块：205 条规则里 45 条用了变宽 "
        "lookbehind，标准库 `re` 编译不了。请 `pip install regex`。"
    ) from exc

#: 原版默认修饰符 ``umx`` 对应到 ``regex`` 的旗标
FLAGS = _re.VERBOSE | _re.MULTILINE | _re.UNICODE

#: 规则集 JSON 期望的 schema 版本
SCHEMA_VERSION = "1.0"

#: 原版是 PCRE，Python 侧是 ``regex`` 模块——两者**方言不完全一致**。
#: 导出时做过全表普查（见 ``tests/test_e3_manual_rules.py`` 的同名用例），
#: 205 条里只有一处真正分叉，就是 PCRE 的 ``\gN`` 反向引用：
#:
#: * PHP/PCRE：``\g1`` = 引用第 1 个捕获组（实测 ``(a)\g1`` 能匹配 ``"aa"``）；
#: * Python ``regex``：``\g1`` 被当成字面量 ``g1``（实测 ``(a)\g1`` 只匹配
#:   ``"ag1"``，**不报错**——静默错语义，比报错更危险）。
#:
#: 所以编译前必须把 ``\g<数字>`` 翻译成 ``\g<数字>`` 的尖括号形式。
#: 其余方言（内联旗标、``\K``、``\R``、``\h``、占有量词、原子组、``(?(`` 条件、
#: 递归、``\p{}``、``\Q..\E``、八进制转义）全表 0 命中，无需翻译。
#:
#: 翻译发生在 ``_compile`` 里，且**只改反向引用这一种记号**；每次翻译都记在
#: ``Rule.dialect`` 字段上，验收时可以逐条列出"这条规则被翻译过"。
_DIALECT_G_REF = _re.compile(r"\\(g)(\d{1,2})")


def normalize_dialect(pattern: str) -> tuple[str, list[str]]:
    """把 PCRE 方言改写成 ``regex`` 的等价写法，返回（新表达式, 改动清单）。"""
    changes: list[str] = []

    def _fix(m: Any) -> str:
        changes.append(f"\\{m.group(1)}{m.group(2)} -> \\g<{m.group(2)}>")
        return "\\g<" + m.group(2) + ">"

    return _DIALECT_G_REF.sub(_fix, pattern), changes

#: 三种排序（与 PHP ``PatternMatcher::sortPatterns`` 的 sort=0/1/2 一一对应）
ORDER_FILE = "file"        # 原文件顺序（PHP sort=0，即默认不排序）
ORDER_COUNT = "count"      # 按替换次数（PHP sort=1，count 升序）
ORDER_COLOR = "color"      # 按优先级颜色分组（PHP sort=2，[color, count] 升序）
ORDERS = (ORDER_FILE, ORDER_COUNT, ORDER_COLOR)

#: 排序名 → 人话（界面只显示这些，不外露内部枚举名）
ORDER_LABELS = {
    ORDER_FILE: "按规则表顺序",
    ORDER_COUNT: "按命中次数（少的在前）",
    ORDER_COLOR: "按优先级分组",
}


# ---------------------------------------------------------------------------
# 3 条回调的等价实现
# ---------------------------------------------------------------------------
#
# 原版 3 条回调都是「对捕获组做二次替换」，PHP 源码见 rules.json 的
# ``cb_source`` 字段（导出器原样抄出）。这里逐条对照实现，**不做任何近似**：
#
#   1. {额->呃}   str_replace("额","呃",$matches[1])
#   2. {恩->嗯}   str_replace("恩","嗯",$matches[1])
#   3. {移除概数之中的顿号}  条件判断后再 str_replace("、","",$matches[2])
#
# 第 3 条还有个「防误伤」前置条件：首尾都落在"十/百/千"的语境里时不动
# （``$matches[1]=="十"`` 且 ``$matches[3]`` 是 十/百/千）。
#
# PHP 的 ``str_replace`` 是**全量替换**，对应 Python ``str.replace`` 同义。


def _group(m: Any, i: int) -> str:
    """取捕获组，未参与匹配的分组折成空串（PHP ``$matches`` 的语义）。"""
    try:
        value = m.group(i)
    except IndexError:
        return ""
    return "" if value is None else value


def _cb_variant(src_char: str, dst_char: str) -> Callable[[Any], str]:
    """``str_replace(src, dst, $matches[1])`` 的等价实现（回调 1、2 共用形状）。"""

    def _apply(m: Any) -> str:
        return _group(m, 1).replace(src_char, dst_char)

    return _apply


def _cb_remove_count_dunhao(m: Any) -> str:
    """{移除概数之中的顿号}：1、2 之间的顿号去掉，但"十…十/百/千"不动。

    对应 PHP 源码（原样逻辑）：

    .. code-block:: php

        if (!(
            $matches[1] == "十" && $matches[3] == "十"
            || $matches[1] == "十" && $matches[3] == "百"
            || $matches[1] == "十" && $matches[3] == "千"
        )) {
            $matches[2] = str_replace("、", "", $matches[2]);
        }
        return $matches[1] . $matches[2] . $matches[3];

    """
    first, middle, last = _group(m, 1), _group(m, 2), _group(m, 3)
    protected = first == "十" and (last == "十" or last == "百" or last == "千")
    if not protected:
        middle = middle.replace("、", "")
    return first + middle + last


#: 回调键 → 等价实现。键写在 rules.json 的 ``callback_id`` 字段里；
#: 加载时逐条核对「有回调的规则都必须在这里找到实现」，否则**直接失败**，
#: 绝不允许静默降级成字面量替换。
CALLBACKS: dict[str, Callable[[Any], str]] = {
    "额->呃": _cb_variant("额", "呃"),
    "恩->嗯": _cb_variant("恩", "嗯"),
    "移除概数之中的顿号": _cb_remove_count_dunhao,
}

#: 3 条回调规则的 mark（与 PHP 规则表一致，供测试与文档引用）
CALLBACK_MARKS = ("{额->呃}", "{恩->嗯}", "{移除概数之中的顿号}")


def _callback_id_from_mark(mark: str) -> str:
    """``{额->呃}`` → ``额->呃``（rules.json 的 callback_id 就是这个形状）。"""
    strip_hint = mark.startswith("{") and mark.endswith("}")
    return mark[1:-1] if strip_hint else mark


# ---------------------------------------------------------------------------
# 规则与规则集
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """一条手动检索规则（原版规则表的一行）。"""

    index: int                      # 在原文件里的序号（0-based，顺序的唯一权威）
    mark: str                       # 原版唯一标识，如 "{盍->阖}"
    search: str                     # PCRE 源文本（已展开 {$puncts} / {$dePrefixPattern}）
    replace: str | None             # 模板（$1 形式）；回调规则为 None
    is_callback: bool
    callback_id: str | None
    color: str                      # 优先级分组色；无则空串
    modifiers: str | None            # 原版逐条修饰符覆盖；规则表里目前全为 None
    note: str | None                # 原版紧邻的说明注释
    cb_source: str | None = None    # 回调源码（原样，供人工核对）

    #: 编译缓存（不参与相等性比较）
    _pattern: Any = field(default=None, repr=False, compare=False)

    #: 这条规则在编译前被改写过哪些方言记号（空 = 原样可用）
    dialect: tuple[str, ...] = ()
    #: 不可编译时的原因（None = 可编译）
    compile_error: str | None = None

    def template(self) -> str | None:
        """替换模板转成 Python 的 ``\\g<N>`` 形式；字面规则原样返回。"""
        if self.replace is None:
            return None
        return _php_template_to_python(self.replace)


def _php_template_to_python(template: str) -> str:
    """PHP ``$1`` / ``$2`` → Python ``\\\\g<1>``。

    规则表里的模板只有 ``$N`` 一种占位（导出时已核验无 ``$0`` / ``${...}`` /
    反斜杠），因此这里不做通用解析，只按 ``$`` 后跟数字整段替换。
    """
    out: list[str] = []
    i, n = 0, len(template)
    while i < n:
        ch = template[i]
        if ch == "$" and i + 1 < n and template[i + 1].isdigit():
            j = i + 1
            while j < n and template[j].isdigit():
                j += 1
            out.append("\\g<" + template[i + 1:j] + ">")
            i = j
            continue
        if ch == "\\":
            # 模板里不该有反斜杠；真出现就转义成字面量，避免被当成分组引用
            out.append("\\\\")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


@dataclass
class ValidationReport:
    """规则集校验结论：逐条可编译 / 不可编译条目与原因。"""

    total: int
    compilable: int
    failures: list[tuple[int, str, str]]      # (index, mark, 原因)
    callback_rules: int
    missing_callbacks: list[str]              # 有回调但实现缺失的 mark
    schema_version: str
    source_sha256: str

    @property
    def ok(self) -> bool:
        """全部可编译 **且** 3 条回调都有实现。"""
        return not self.failures and not self.missing_callbacks

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "compilable": self.compilable,
            "failures": [
                {"index": i, "mark": m, "reason": r} for i, m, r in self.failures
            ],
            "callback_rules": self.callback_rules,
            "missing_callbacks": list(self.missing_callbacks),
            "schema_version": self.schema_version,
            "source_sha256": self.source_sha256,
            "ok": self.ok,
        }


@dataclass
class RuleHit:
    """一条规则在一段文本上的命中结果。"""

    rule: Rule
    count: int

    @property
    def mark(self) -> str:
        return self.rule.mark


@dataclass
class ScanResult:
    """一次扫描的全部结果（含 0 命中的规则，便于对照）。"""

    hits: list[RuleHit]                   # 与规则集同序（原文件顺序）
    total: int                            # 所有规则命中的总和
    elapsed: float                        # 秒
    text_chars: int

    @property
    def nonzero(self) -> list[RuleHit]:
        return [h for h in self.hits if h.count]

    def ordered(self, order: str = ORDER_FILE) -> list[RuleHit]:
        """按指定排序返回；``ORDER_FILE`` 原样返回。"""
        return sort_hits(self.hits, order)


def sort_hits(hits: Sequence[RuleHit], order: str = ORDER_FILE) -> list[RuleHit]:
    """三种排序，语义与 PHP ``PatternMatcher::sortPatterns`` 对齐。

    - ``ORDER_FILE``：原文件顺序（``index`` 升序），**不**按命中数重排；
    - ``ORDER_COUNT``：命中次数升序（PHP ``$a['count'] <=> $b['count']``）；
    - ``ORDER_COLOR``：先按颜色分组、组内再按命中次数升序
      （PHP ``[$a['color'], $a['count']] <=> [...]``；无颜色的规则 color 视为空串，
      空串排在有颜色之前——与 PHP 的字符串比较一致）。

    PHP ``usort`` 不保证稳定；这里在并列时用 ``index`` 兜底，保证结果可复现。
    """
    if order not in ORDERS:
        raise ValueError(f"未知排序：{order!r}（可选 {ORDERS}）")
    items = list(hits)
    if order == ORDER_FILE:
        return sorted(items, key=lambda h: h.rule.index)
    if order == ORDER_COUNT:
        return sorted(items, key=lambda h: (h.count, h.rule.index))
    return sorted(items, key=lambda h: (h.rule.color or "", h.count, h.rule.index))


class RuleSet:
    """手动检索规则集：加载 / 校验 / 编译 / 扫描 / 排序 / 只读预览。"""

    def __init__(self, rules: Sequence[Rule], meta: dict[str, Any]) -> None:
        self._rules = list(rules)
        self._meta = dict(meta)

    # -- 加载 ------------------------------------------------------------
    @classmethod
    def from_json(cls, path: str | Path | None = None) -> "RuleSet":
        p = Path(path) if path else default_rules_path()
        payload = json.loads(p.read_text(encoding="utf-8"))
        ver = payload.get("schema_version")
        if ver != SCHEMA_VERSION:
            raise ValueError(
                f"规则集文件版本不符：期望 {SCHEMA_VERSION}，实际 {ver!r}（{p}）"
            )
        items = payload["items"]
        rules: list[Rule] = []
        for i, it in enumerate(items):
            mark = str(it["mark"])
            is_cb = bool(it["is_callback"])
            cb_id = _callback_id_from_mark(mark) if is_cb else None
            rules.append(Rule(
                index=i,
                mark=mark,
                search=str(it["search"]),
                replace=None if is_cb else (it.get("replace") or ""),
                is_callback=is_cb,
                callback_id=cb_id,
                color=str(it.get("color") or ""),
                modifiers=it.get("modifiers"),
                note=it.get("note"),
                cb_source=it.get("cb_source"),
            ))
        meta = {
            "schema_version": ver,
            "counts": payload.get("counts", {}),
            "source": payload.get("source", {}),
            "path": str(p),
        }
        return cls(rules, meta)

    # -- 基本信息 --------------------------------------------------------
    def __len__(self) -> int:
        return len(self._rules)

    def __iter__(self) -> Iterable[Rule]:
        return iter(self._rules)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)

    def get(self, index: int) -> Rule:
        return self._rules[index]

    def by_mark(self, mark: str) -> Rule:
        for r in self._rules:
            if r.mark == mark:
                return r
        raise KeyError(mark)

    @property
    def meta(self) -> dict[str, Any]:
        return dict(self._meta)

    @property
    def callbacks(self) -> list[Rule]:
        return [r for r in self._rules if r.is_callback]

    # -- 校验 ------------------------------------------------------------
    def validate(self, compile_all: bool = True) -> ValidationReport:
        """逐条编译；不可编译的**显式登记原因**，不吞掉、不降级。"""
        failures: list[tuple[int, str, str]] = []
        if compile_all:
            for rule in self._rules:
                err = _compile_error(rule)
                if err is not None:
                    failures.append((rule.index, rule.mark, err))
                    object.__setattr__(rule, "compile_error", err)

        missing = [
            r.mark for r in self._rules
            if r.is_callback and (r.callback_id or "") not in CALLBACKS
        ]
        src = self._meta.get("source", {})
        return ValidationReport(
            total=len(self._rules),
            compilable=len(self._rules) - len(failures),
            failures=failures,
            callback_rules=len(self.callbacks),
            missing_callbacks=missing,
            schema_version=str(self._meta.get("schema_version", "")),
            source_sha256=str(src.get("rules_sha256", "")),
        )

    # -- 编译 ------------------------------------------------------------
    def compiled(self, rule: Rule) -> Any:
        """取（并缓存）编译后的模式；不可编译则抛 ``RuleCompileError``。"""
        if rule._pattern is not None:
            return rule._pattern
        pat, err = _compile(rule)
        if err is not None:
            object.__setattr__(rule, "compile_error", err)
            raise RuleCompileError(rule, err)
        object.__setattr__(rule, "_pattern", pat)
        return pat

    def warmup(self) -> int:
        """预编译全部规则，返回成功条数（失败条目记在 ``rule.compile_error``）。"""
        ok = 0
        for rule in self._rules:
            try:
                self.compiled(rule)
                ok += 1
            except RuleCompileError:
                continue
        return ok

    # -- 扫描 ------------------------------------------------------------
    def scan(self, text: str) -> ScanResult:
        """统计每条规则在 ``text`` 上的命中数（不含替换；只读）。

        ``text`` 必须是**同一份**文本（一本书）——与原版 ``file_get_contents``
        一次读入全书再逐条 ``preg_match_all`` 的口径一致。
        """
        t0 = time.perf_counter()
        hits: list[RuleHit] = []
        for rule in self._rules:
            pat = self.compiled(rule)          # 不可编译 → 抛，不静默算 0
            hits.append(RuleHit(rule=rule, count=sum(1 for _ in pat.finditer(text))))
        elapsed = time.perf_counter() - t0
        return ScanResult(
            hits=hits,
            total=sum(h.count for h in hits),
            elapsed=elapsed,
            text_chars=len(text),
        )

    # -- 只读预览 --------------------------------------------------------
    def preview(
        self,
        text: str,
        indices: Sequence[int] | None = None,
    ) -> "PreviewResult":
        """**只读预览**：算出「若执行这些规则会变成什么」，返回新字符串。

        语义对齐原版 ``PatternReplacer::executeReplace``：按 **选中规则的顺序**
        逐条 ``preg_replace`` 串行套用（上一条的输出是下一条的输入）。
        选中顺序用 ``indices``（规则集原序号）给出；缺省 = 全部规则按原顺序。

        本方法**不写盘、不改入参**——``text`` 是 ``str``（不可变），返回值是
        **新的** ``str``。落盘属 E4，本卡不做。
        """
        ordered = self._selected(indices)
        t0 = time.perf_counter()
        current = text
        per_rule: list[RuleHit] = []
        for rule in ordered:
            before = current
            current = self._apply(rule, current)
            per_rule.append(RuleHit(rule=rule, count=_diff_count(before, current)))
        t0 = time.perf_counter() - t0
        return PreviewResult(text=current, per_rule=per_rule, elapsed=t0)

    def apply_rule(self, rule: Rule, text: str) -> str:
        """单条规则套用一次（回调走等价实现），返回新字符串。"""
        return self._apply(rule, text)

    def _selected(self, indices: Sequence[int] | None) -> list[Rule]:
        if indices is None:
            return list(self._rules)
        out: list[Rule] = []
        for i in indices:
            if not (0 <= i < len(self._rules)):
                raise IndexError(f"规则序号越界：{i}（共 {len(self._rules)} 条）")
            out.append(self._rules[i])
        return out

    def _apply(self, rule: Rule, text: str) -> str:
        pat = self.compiled(rule)
        if rule.is_callback:
            fn = CALLBACKS.get(rule.callback_id or "")
            if fn is None:                      # 防御：校验阶段已拦
                raise RuleCompileError(
                    rule, f"回调 {rule.callback_id} 没有等价实现（拒绝静默降级）"
                )
            return pat.sub(fn, text)
        return pat.sub(rule.template() or "", text)


@dataclass
class PreviewResult:
    """只读预览结果。``text`` 是**新字符串**，原文本不变。"""

    text: str
    per_rule: list[RuleHit]
    elapsed: float

    @property
    def changed_chars(self) -> int:
        return sum(h.count for h in self.per_rule)


class RuleCompileError(RuntimeError):
    """某条规则编译失败（携带规则与原因，便于逐条登记）。"""

    def __init__(self, rule: Rule, reason: str) -> None:
        self.rule = rule
        self.reason = reason
        super().__init__(f"规则 {rule.index} {rule.mark} 无法编译：{reason}")


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _flags_for(rule: Rule) -> int:
    """原版逐条 ``modifiers`` 覆盖优先（规则表里目前全为 None）。"""
    mods = (rule.modifiers or "").lower()
    flags = 0
    if "x" in mods or not mods:
        flags |= _re.VERBOSE
    if "m" in mods or not mods:
        flags |= _re.MULTILINE
    if "i" in mods:
        flags |= _re.IGNORECASE
    if "s" in mods:
        flags |= _re.DOTALL
    flags |= _re.UNICODE
    return flags


def _compile(rule: Rule) -> tuple[Any, str | None]:
    try:
        source, changes = normalize_dialect(rule.search)
        if changes:
            object.__setattr__(rule, "dialect", tuple(changes))
        return _re.compile(source, _flags_for(rule)), None
    except Exception as exc:                    # noqa: BLE001 - 逐条登记原因
        return None, f"{type(exc).__name__}: {exc}"


def _compile_error(rule: Rule) -> str | None:
    return _compile(rule)[1]


def _diff_count(before: str, after: str) -> int:
    """两次文本的「变了多少处」——按前缀/后缀剥掉相同部分后剩下的块数。

    只用于**预览**的分条计数（真实替换次数由 ``scan()`` 给），
    对整段替换是最小近似，**不**参与任何验收数字。
    """
    if before == after:
        return 0
    # 去掉公共前缀 / 后缀，中间残段按「至少 1 处」计
    lo = 0
    limit = min(len(before), len(after))
    while lo < limit and before[lo] == after[lo]:
        lo += 1
    hi_b, hi_a = len(before), len(after)
    while hi_b > lo and hi_a > lo and before[hi_b - 1] == after[hi_a - 1]:
        hi_b -= 1
        hi_a -= 1
    return 1 if (hi_b > lo or hi_a > lo) else 0


def default_rules_path() -> Path:
    """默认规则集路径：``<包根>/data/manual_search/rules.json``。"""
    try:
        from fixtext_paths import pkg_root          # noqa: PLC0415
        return pkg_root() / "data" / "manual_search" / "rules.json"
    except Exception:                                # pragma: no cover
        return Path(__file__).resolve().parent.parent / "data" / "manual_search" / "rules.json"


def load_rules(path: str | Path | None = None, *, strict: bool = True) -> RuleSet:
    """便捷入口：加载并校验；``strict`` 时校验不过直接抛。"""
    rs = RuleSet.from_json(path)
    report = rs.validate()
    if strict and not report.ok:
        detail = "; ".join(f"#{i} {m}: {r}" for i, m, r in report.failures[:5])
        missing = ",".join(report.missing_callbacks)
        raise ValueError(
            f"规则集校验未通过：不可编译 {len(report.failures)} 条"
            f"{('（' + detail + '）') if detail else ''}"
            f"{('；缺回调实现: ' + missing) if missing else ''}"
        )
    return rs
