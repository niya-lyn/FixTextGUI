"""V1.1-D1 · 列映射：把任意列顺序的表，映射到「错词 / 正确写法 / 分类」。

设计要点（决定这一层能不能"错配时纠正"）：

1. **映射是可改的数据，不是硬编码的猜测。** 表头识别只负责给出一个
   *建议*（`ColumnMapping.suggested()`），用户可以逐列改成别的用途。
2. **映射与原始表是分离的。** 同一份 `ParsedSheet` 可以反复套用不同映射，
   不需要重新解析——改映射必须便宜，否则"错配时纠正"会变成重新导入。
3. **映射要能表达「这列不用」。** 表里常有多出来的列（拼音、备注、
   书籍名），把它们标成 `IGNORE` 而不是硬塞进某个角色。
4. **必须能说清错在哪。** 同一个用途被指给两列、关键列没被指到、
   选中的列在这一行是空的——这些都要能在**逐条**层面报出来（附原始行号），
   而不是整批失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Sequence

from . import messages as msg

#: 一列可以被指派的用途。用常量避免拼写漂移（曾因 role 名字手误排查很久）。
ROLE_WORD = "word"                 # 错词（要被替换的写法）
ROLE_VALUE = "value"               # 正确写法（替换成什么）
ROLE_TYPE = "type"                 # 分类（错词校正 / 角色名 / 专有名词 / 其他）
ROLE_PINYIN = "pinyin"             # 拼音（生僻字用）
ROLE_IGNORE = "ignore"             # 这列不用

ROLES: tuple[str, ...] = (ROLE_WORD, ROLE_VALUE, ROLE_TYPE, ROLE_PINYIN, ROLE_IGNORE)

#: 用途 → 人话（预览页直接用这些字，不把代号给用户看）
ROLE_NAMES: dict[str, str] = {
    ROLE_WORD: "错词",
    ROLE_VALUE: "正确写法",
    ROLE_TYPE: "分类",
    ROLE_PINYIN: "拼音",
    ROLE_IGNORE: "不使用这列",
}

#: 缺省分类（与词库写入层的默认值一致，避免 D5 再猜一次）
DEFAULT_TYPE = "错词校正"

#: 表头里可能出现的字样 → 用途。只用于**建议**，不用于强制。
#: 刻意让「错词」的匹配词更具体，避免和「正确写法」互抢。
_HEADER_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (ROLE_WORD, ("错词", "原文", "替换前", "改前", "before", "旧词", "错误写法",
                 "待改", "要改", "查找", "原词")),
    (ROLE_VALUE, ("正确写法", "改后", "替换后", "替换为", "after", "新词",
                  "建议", "正确", "改为", "修正为", "目标词")),
    (ROLE_TYPE, ("分类", "类型", "类别", "type", "词条类型")),
    (ROLE_PINYIN, ("拼音", "注音", "pinyin")),
    (ROLE_IGNORE, ("备注", "说明", "书籍", "书名", "来源", "序号", "id", "note")),
)


@dataclass
class ColumnMapping:
    """一份"哪一列当什么用"的指派。列下标从 0 开始。"""

    roles: list[str] = field(default_factory=list)

    # ----- 构造 -----

    @classmethod
    def all_ignored(cls, column_count: int) -> "ColumnMapping":
        return cls(roles=[ROLE_IGNORE] * max(0, column_count))

    @classmethod
    def suggested(cls, headers: Sequence[str] | None, column_count: int) -> "ColumnMapping":
        """按表头字样给出**建议指派**；没有表头时按「第 1 列错词、第 2 列正确写法」。"""
        if column_count <= 0:
            return cls(roles=[])

        roles = [ROLE_IGNORE] * column_count
        if headers:
            taken: dict[str, int] = {}
            for idx, raw in enumerate(headers[:column_count]):
                role = _match_header(raw)
                if role is None:
                    continue
                # 同一用途只指派给第一列命中者（后面的当「不使用」，让用户自己改）
                if role in taken:
                    continue
                taken[role] = idx
                roles[idx] = role

            # 表头命中不足两条关键列时，退回位置建议
            if ROLE_WORD not in taken or ROLE_VALUE not in taken:
                fallback = cls._positional(column_count)
                for idx, role in enumerate(fallback.roles):
                    if role in taken or roles[idx] == ROLE_IGNORE:
                        roles[idx] = role if roles[idx] == ROLE_IGNORE else roles[idx]
                # 位置建议与表头建议可能冲突：以表头已明确指派的为准
                for role, idx in taken.items():
                    roles[idx] = role
        else:
            roles = cls._positional(column_count).roles
        return cls(roles=roles)

    @classmethod
    def _positional(cls, column_count: int) -> "ColumnMapping":
        """无表头时的位置约定：1 列=错词；2 列起=错词+正确写法；3 列起=再加分类。"""
        roles = [ROLE_IGNORE] * column_count
        if column_count >= 1:
            roles[0] = ROLE_WORD
        if column_count >= 2:
            roles[1] = ROLE_VALUE
        if column_count >= 3:
            roles[2] = ROLE_TYPE
        return cls(roles=roles)

    # ----- 查询 -----

    def __len__(self) -> int:
        return len(self.roles)

    def column_for(self, role: str) -> int | None:
        try:
            return self.roles.index(role)
        except ValueError:
            return None

    @property
    def word_column(self) -> int | None:
        return self.column_for(ROLE_WORD)

    @property
    def value_column(self) -> int | None:
        return self.column_for(ROLE_VALUE)

    @property
    def type_column(self) -> int | None:
        return self.column_for(ROLE_TYPE)

    @property
    def pinyin_column(self) -> int | None:
        return self.column_for(ROLE_PINYIN)

    # ----- 修改 -----

    def with_role(self, column: int, role: str) -> "ColumnMapping":
        """把第 `column` 列改指派为 `role`；若该用途已被别列占用，先解占。

        这是"错配时可纠正"的核心动作：**改一次即可，不需要重解析**。
        """
        if role not in ROLES:
            raise ValueError(f"未知的列用途：{role}")
        if not (0 <= column < len(self.roles)):
            raise ValueError(f"列号超出范围：{column}")
        roles = list(self.roles)
        if role != ROLE_IGNORE:
            for idx, current in enumerate(roles):
                if current == role and idx != column:
                    roles[idx] = ROLE_IGNORE
        roles[column] = role
        return ColumnMapping(roles=roles)

    def with_roles(self, roles: Sequence[str]) -> "ColumnMapping":
        if len(roles) != len(self.roles):
            raise ValueError("新的列指派数量与列的个数不一致")
        for role in roles:
            if role not in ROLES:
                raise ValueError(f"未知的列用途：{role}")
        return ColumnMapping(roles=list(roles))

    def swap(self, a: int, b: int) -> "ColumnMapping":
        """交换两列的用途（最常见的错配就是两列反了）。"""
        if not (0 <= a < len(self.roles) and 0 <= b < len(self.roles)):
            raise ValueError("列号超出范围")
        roles = list(self.roles)
        roles[a], roles[b] = roles[b], roles[a]
        return ColumnMapping(roles=roles)

    def copy(self) -> "ColumnMapping":
        return replace(self, roles=list(self.roles))

    # ----- 自检 -----

    def problems(self) -> list[str]:
        """映射本身的毛病（与具体某一行无关），返回人话。"""
        out: list[str] = []
        if self.word_column is None:
            out.append("还没有指定哪一列是「错词」")
        if self.value_column is None:
            out.append("还没有指定哪一列是「正确写法」")
        if not out:
            return out
        return out

    def is_ready(self) -> bool:
        return not self.problems()

    def describe(self) -> list[str]:
        """逐列的人话说明，预览页直接展示。"""
        return [f"第 {i + 1} 列：{ROLE_NAMES.get(r, r)}" for i, r in enumerate(self.roles)]


def _match_header(raw: str) -> str | None:
    """按表头字样猜用途；只做**建议**，猜不到就返回 None（交给位置约定）。"""
    text = (raw or "").strip().strip("：: 　").lower()
    if not text:
        return None
    for role, hints in _HEADER_HINTS:
        for hint in hints:
            if hint in text:
                return role
    return None


# ---------------------------------------------------------------------------
# 把映射套到数据行上
# ---------------------------------------------------------------------------

@dataclass
class MappedRow:
    """一条映射后的候选词条，带**原始行号**（D2 的不合格清单要能定位回去）。"""

    line_no: int                       # 原始文件/粘贴文本里的行号，从 1 开始
    word: str
    value: str
    typ: str = DEFAULT_TYPE
    pinyin: str = ""
    problem: str = ""                  # 非空 = 这一行不合格，内容是人话原因

    @property
    def ok(self) -> bool:
        return not self.problem


@dataclass
class MappingResult:
    rows: list[MappedRow] = field(default_factory=list)
    skipped_blank: int = 0             # 跳过的空行数（会告诉用户，不静默丢弃）
    restored_marks: int = 0            # 共还原了多少个占位标记

    def good(self) -> list[MappedRow]:
        return [r for r in self.rows if r.ok]

    def bad(self) -> list[MappedRow]:
        return [r for r in self.rows if not r.ok]


def apply_mapping(
    rows: Sequence[tuple[int, list[str]]],
    mapping: ColumnMapping,
    *,
    restore: bool = True,
) -> MappingResult:
    """按映射把 (行号, 已切好的字段列表) 变成候选词条。

    :param restore: 是否把原版占位标记还原成原字符。**必须在切列之后**
                    才调用本函数（切列由解析层负责），原因见 `escape.py` 头。
    """
    from .escape import restore_escaped_once

    result = MappingResult()
    wcol = mapping.word_column
    vcol = mapping.value_column
    tcol = mapping.type_column
    pcol = mapping.pinyin_column

    def _pick(fields: list[str], idx: int | None) -> str:
        if idx is None or idx >= len(fields):
            return ""
        return fields[idx]

    for line_no, fields in rows:
        if not fields or all((f or "").strip(" \t") == "" for f in fields):
            result.skipped_blank += 1
            continue

        raw_word = _pick(fields, wcol)
        raw_value = _pick(fields, vcol)
        raw_type = _pick(fields, tcol)
        raw_pinyin = _pick(fields, pcol)

        if restore:
            w_report = restore_escaped_once(raw_word)
            v_report = restore_escaped_once(raw_value)
            t_report = restore_escaped_once(raw_type)
            p_report = restore_escaped_once(raw_pinyin)
            raw_word, raw_value = w_report.text, v_report.text
            raw_type, raw_pinyin = t_report.text, p_report.text
            result.restored_marks += (
                w_report.replaced + v_report.replaced
                + t_report.replaced + p_report.replaced
            )

        # 只去两端的普通空格与制表符，**不要去换行**：
        # 出厂词库里确有以换行结尾的词条（如「懒的开口啊\n」），
        # 那一枚换行是词条内容的一部分（替换时要连行尾一起吃掉），
        # 用 `.strip()` 会把它吃掉，等于悄悄改坏原词条。
        word = raw_word.strip(" \t")
        value = raw_value.strip(" \t")
        typ = raw_type.strip(" \t") or DEFAULT_TYPE
        pinyin = raw_pinyin.strip(" \t")

        problem = ""
        if wcol is None:
            problem = msg.ROW_NO_WORD_COLUMN
        elif vcol is None:
            problem = msg.ROW_NO_VALUE_COLUMN
        elif not word:
            problem = msg.ROW_WORD_EMPTY
        elif not value:
            problem = msg.ROW_VALUE_EMPTY

        result.rows.append(MappedRow(
            line_no=line_no, word=word, value=value, typ=typ,
            pinyin=pinyin, problem=problem,
        ))
    return result
