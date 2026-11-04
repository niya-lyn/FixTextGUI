"""V1.1-D2 · 超限分批策略：阈值、分批边界、进度反馈。

本模块只做**切分与进度记账**，不写库（D5 负责）、不做查重（D3 负责）。
它给下游一个统一形状：无论多少条，都拿到一份 `BatchPlan`，
按批迭代即可——调用方不需要为「小表单批」写分支。

三条设计约束（每条都有单测守着）：

1. **阈值是「是否给进度」的分界线，不是「能不能处理」的分界线。**
   一千条以内一次走完，不弹进度条（小表弹进度条只是在闪一下，反而像卡了）；
   超过阈值就切成每批若干条，每批结束回一次进度。所以小表也返回 1 个批，
   `BatchPlan` 的形状不变。
2. **分批边界按「行的原始顺序」连续切，不重排、不合并、不跨批共享状态。**
   每批自带原始行号区间，于是「进度卡在哪一批」等价于「卡在哪一段原文」——
   这是本卡验收判据「清单可定位到原始行号」在分批侧的对应物。
3. **进度数字来自实测，不估算。** 已完成条数、按批计数累加；剩余时间用
   本批实测速率外推（`done` 与 `elapsed` 都来自调用方的时钟），
   没有实测样本时给不出估计就如实说「还要一会儿」，不编数字。

阈值与批大小的取值依据是**实测**不是估计（验收报告 3.2 有原始输出）：
单行「占位符还原 + 列映射」实测约 3.5µs，本卡的行级判定同量级，取 7µs 作保守值。
1000 行一次走完 ≈ 7ms，用户察觉不到，所以一千行以内不分批；
超过就按每批 1000 行切（≈7ms/批），每批回一次进度。

阈值与批大小取同一个值（1000），于是三个说法完全等价：
**超过阈值 ⇔ 要分批 ⇔ 切成 2 批以上 ⇔ 需要给进度**。
不让它们可以互相矛盾——「超限了但只有一批」那种状态没法对用户解释。
阈值只决定「要不要给进度」，不决定「能不能处理」。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from . import messages as msg

#: 条数**超过**这个值才改为分批并给进度（等于这个值仍然一次走完）
DEFAULT_BATCH_THRESHOLD = 1000

#: 每批处理多少条。取 1000：一批约 7ms，远短于用户能察觉的一次停顿；
#: 批再小只是多刷几次进度，不会更快。与阈值同值（阈值也可能被调用方单独调大）。
DEFAULT_BATCH_SIZE = 1000


# ---------------------------------------------------------------------------
# 策略
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BatchPolicy:
    """一次导入的分批规则。"""

    threshold: int = DEFAULT_BATCH_THRESHOLD
    batch_size: int = DEFAULT_BATCH_SIZE

    def __post_init__(self) -> None:
        if int(self.threshold) < 1:
            raise ValueError("阈值得是 1 条以上")
        if int(self.batch_size) < 1:
            raise ValueError("每批的条数得是 1 条以上")

    def is_over_limit(self, count: int) -> bool:
        """超过阈值吗——超了才需要进度反馈。"""
        return int(count) > self.threshold

    def describe(self) -> str:
        """给界面看的一句话（用户不懂「阈值」，只懂「超过多少条」）。"""
        return (
            f"一次导入超过 {self.threshold} 条时，会分成每批 {self.batch_size} 条来处理，"
            "每批结束都会更新进度。"
        )


# ---------------------------------------------------------------------------
# 批次与计划
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Batch:
    """一批待处理的词条（只读快照 + 它的原始行号区间）。"""

    index: int                  # 第几批，从 1 开始
    total: int                  # 一共几批
    rows: tuple                 # 本批的词条（MappedRow，保持原始顺序）
    first_line: int             # 本批第一条的原始行号
    last_line: int              # 本批最后一条的原始行号

    @property
    def count(self) -> int:
        return len(self.rows)

    def span_text(self) -> str:
        if self.count == 1:
            return f"第 {self.first_line} 行"
        return f"第 {self.first_line}–{self.last_line} 行"

    def title(self) -> str:
        return f"第 {self.index} / {self.total} 批 · {self.span_text()} · {self.count} 条"


@dataclass(frozen=True)
class BatchPlan:
    """一份「怎么切」的完整答案，小表也是它（只是只有 1 批）。"""

    rows: tuple                       # 全部待处理词条
    batches: tuple                    # Batch 序列，按行号升序
    policy: BatchPolicy
    #: 是否**真的切成多批**（= 需要给进度）。刻意不与「阈值判定」分开写：
    #: 「超限了却只有一批」这种状态没法给用户解释，两个说法必须同源。
    over_limit: bool = False

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    @property
    def batch_count(self) -> int:
        return len(self.batches)

    def __len__(self) -> int:
        return len(self.batches)

    def __iter__(self) -> Iterable[Batch]:
        return iter(self.batches)

    def covers_all_rows(self) -> bool:
        """各批拼起来是否**不重不漏**地覆盖全部行（自检用，也可给界面核对）。"""
        seen = [row for batch in self.batches for row in batch.rows]
        if len(seen) != len(self.rows):
            return False
        return all(a is b for a, b in zip(seen, self.rows))

    def describe(self) -> str:
        if self.total_rows == 0:
            return "没有要处理的词条。"
        if self.batch_count <= 1:
            return f"共 {self.total_rows} 条，一次处理完。"
        return (
            f"共 {self.total_rows} 条，按每批 {self.policy.batch_size} 条分成 "
            f"{self.batch_count} 批处理。"
        )


def plan_batches(rows: Sequence, policy: BatchPolicy | None = None) -> BatchPlan:
    """把待处理词条切成批次。

    **边界规则**：按传入顺序连续切（传入顺序就是原始行号升序），
    每批至多 `policy.batch_size` 条，最后一批可以不满。
    不重排、不跳行、不跨批拆分单条——切点永远落在两条词条之间。

    :param rows: 已校验通过的词条（`MappedRow` 或任何带 `line_no` 的对象）
    :param policy: 分批规则；不给就用默认值
    """
    pol = policy or BatchPolicy()
    items = tuple(rows)
    total_rows = len(items)

    if total_rows == 0:                    # 一条都没有：没有批，不是「一个空批」
        return BatchPlan(rows=items, batches=(), policy=pol, over_limit=False)

    # 小表：一批走完，形状不变（调用方不必为「没超过阈值」写分支）
    size = pol.batch_size if pol.is_over_limit(total_rows) else total_rows

    chunks = [items[i:i + size] for i in range(0, total_rows, size)]
    total = len(chunks)

    batches = []
    for idx, chunk in enumerate(chunks, start=1):
        first = int(getattr(chunk[0], "line_no", 0)) if chunk else 0
        last = int(getattr(chunk[-1], "line_no", 0)) if chunk else 0
        batches.append(Batch(index=idx, total=total, rows=tuple(chunk),
                             first_line=first, last_line=last))

    return BatchPlan(rows=items, batches=tuple(batches), policy=pol,
                     over_limit=len(batches) > 1)


# ---------------------------------------------------------------------------
# 进度反馈
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProgressReport:
    """一批处理完之后的一份进度快照（界面直接拿来刷进度条与文案）。"""

    done: int               # 累计已处理条数
    total: int              # 总条数
    batch_index: int        # 刚完成的是第几批
    batch_count: int        # 一共几批
    first_line: int         # 这批的原始行号区间
    last_line: int
    elapsed: float          # 从开始到此刻的实测秒数

    @property
    def percent(self) -> float:
        if self.total <= 0:
            return 100.0
        return min(100.0, self.done * 100.0 / self.total)

    @property
    def remaining(self) -> int:
        return max(0, self.total - self.done)

    @property
    def finished(self) -> bool:
        return self.remaining == 0

    def rate(self) -> float | None:
        """实测速率（条/秒）；一条都还没处理完时不给（不能除以 0）。"""
        if self.done <= 0 or self.elapsed <= 0:
            return None
        return self.done / self.elapsed

    def eta_seconds(self) -> float | None:
        """剩余时间：用**本次实测**速率外推；没有实测样本就不给估计。"""
        rate = self.rate()
        if rate is None or self.finished:
            return None
        return self.remaining / rate if rate > 0 else None

    def text(self) -> str:
        """一句人话，界面直接显示。"""
        span = (f"第 {self.first_line} 行" if self.first_line == self.last_line
                else f"第 {self.first_line}–{self.last_line} 行")
        head = (f"第 {self.batch_index} / {self.batch_count} 批 · {span} · "
                f"已完成 {self.done} / {self.total} 条（{self.percent:.0f}%）")
        if self.finished:
            return head + "，全部处理完了。"
        eta = self.eta_seconds()
        if eta is None or eta < 1:
            return head + "，正在处理剩下的。"
        if eta < 60:
            return head + f"，大约还要 {eta:.0f} 秒。"
        return head + f"，大约还要 {eta / 60:.0f} 分钟。"


@dataclass
class BatchFailure:
    """某一批处理失败（带批次与行号区间，用户能回到原文那一段）。"""

    batch_index: int
    batch_count: int
    first_line: int
    last_line: int
    rows: int
    reason: str                 # 人话
    exc: BaseException | None = None   # 只进日志，不进界面

    def text(self) -> str:
        span = (f"第 {self.first_line} 行" if self.first_line == self.last_line
                else f"第 {self.first_line}–{self.last_line} 行")
        return (f"第 {self.batch_index} / {self.batch_count} 批（{span}，{self.rows} 条）"
                f"没能处理完：{self.reason}")

    def log_line(self) -> str:
        return msg.log_unexpected(self.exc) if self.exc is not None else self.reason


@dataclass
class BatchRunResult:
    """一次分批运行的结果（成功与失败都保留已完成部分，不整批丢）。"""

    plan: BatchPlan
    results: list = field(default_factory=list)   # 每批处理函数的返回值，按批序
    completed_batches: int = 0
    rows_done: int = 0
    failure: BatchFailure | None = None
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.failure is None and self.completed_batches == self.plan.batch_count

    def summary(self) -> str:
        if self.ok:
            return f"共 {self.rows_done} 条分 {self.completed_batches} 批处理完了。"
        if self.failure is not None:
            return (f"已处理 {self.rows_done} 条（{self.completed_batches} 批），"
                    f"然后卡住了：{self.failure.text()}")
        return f"已处理 {self.rows_done} 条（{self.completed_batches} 批），还没走完。"


#: 每批的处理函数：拿到 Batch，返回该批的处理结果（本卡不关心内容）
Handler = Callable[[Batch], Any]
#: 进度回调：每批结束调用一次
ProgressSink = Callable[[ProgressReport], None]


def run_batches(
    plan: BatchPlan,
    handler: Handler,
    *,
    on_progress: ProgressSink | None = None,
    clock: Callable[[], float] = time.monotonic,
    stop_on_failure: bool = True,
) -> BatchRunResult:
    """按批调用 `handler`，每批结束回一次进度。

    **失败不丢已完成部分**：某一批抛错时，前面批次的结果与条数都在，
    失败那一批的原始行号区间也记下来（用户能回到那一段原文）。
    错误本身翻成人话进 `failure.reason`，技术细节只留在 `failure.exc`。

    :param stop_on_failure: 默认停下——某批处理不了，后面接着做通常只会更糟
    """
    start = clock()
    results: list = []
    rows_done = 0
    failure: BatchFailure | None = None

    for batch in plan.batches:
        try:
            results.append(handler(batch))
        except Exception as exc:            # noqa: BLE001 - 统一翻人话，不让异常原样上界面
            # 失败同样要记账（哪怕继续跑后面的批，也要留下是哪一批、哪一段）
            failure = failure or BatchFailure(
                batch_index=batch.index, batch_count=batch.total,
                first_line=batch.first_line, last_line=batch.last_line,
                rows=batch.count, reason=msg.human_error(exc), exc=exc,
            )
            if stop_on_failure:
                return BatchRunResult(plan=plan, results=results,
                                      completed_batches=len(results),
                                      rows_done=rows_done, failure=failure,
                                      elapsed=clock() - start)
            continue
        except BaseException:               # 键盘中断之类：不当作业务失败，原样抛
            raise

        rows_done += batch.count
        if on_progress is not None:
            on_progress(ProgressReport(
                done=rows_done, total=plan.total_rows,
                batch_index=batch.index, batch_count=batch.total,
                first_line=batch.first_line, last_line=batch.last_line,
                elapsed=clock() - start,
            ))

    return BatchRunResult(plan=plan, results=results,
                          completed_batches=len(results), rows_done=rows_done,
                          failure=failure, elapsed=clock() - start)


# ---------------------------------------------------------------------------
# 两个交付物的联合入口
# ---------------------------------------------------------------------------

@dataclass
class ImportPrep:
    """一次导入备好的东西：**只含合法行**的分批计划 + 不合格行清单。

    两个交付物在这里合起来用，语义就一句话：
    **不合格的行进清单，合格的行进批，两件事不互相卡住。**

    * `plan` 只装 `rejects.good` 里的行——不合格的行根本没进批，
      所以它们在处理中途出问题不可能拖住合法行；
    * `rejects` 保留全部不合格行（含行号与原文），可导出；
    * `blocking` 只在「列都没指好」时成立，那时合法行本来就是 0，
      界面应当先让用户改列映射，而不是显示「0 条可导入」了事。
    """

    rejects: object                     # RejectList
    plan: BatchPlan

    @property
    def good(self) -> list:
        return self.rejects.good

    @property
    def total_rows(self) -> int:
        return self.rejects.total_rows

    @property
    def blocking(self) -> bool:
        return self.rejects.is_blocking()

    @property
    def needs_progress(self) -> bool:
        """要不要给进度——只跟合法行的条数有关（不合格行不进批）。"""
        return self.plan.over_limit

    def summary(self) -> str:
        return self.rejects.summary_text() + " " + self.plan.describe()


def prepare_import(sheet, policy: BatchPolicy | None = None,
                   *, source_name: str = "") -> ImportPrep:
    """解析好的表 → (只含合法行的分批计划, 不合格行清单)。"""
    from .rejects import partition_sheet      # 就地导入：避免两模块顶层的循环引用
    return prepare_from_rejects(partition_sheet(sheet, source_name=source_name),
                                policy=policy)


def prepare_from_rejects(rejects, policy: BatchPolicy | None = None) -> ImportPrep:
    """已有清单时只做切批（`rejects.good` 进批，不合格行不进）。"""
    return ImportPrep(rejects=rejects, plan=plan_batches(rejects.good, policy))


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_BATCH_THRESHOLD",
    "Batch",
    "BatchFailure",
    "BatchPlan",
    "BatchPolicy",
    "BatchRunResult",
    "ImportPrep",
    "ProgressReport",
    "plan_batches",
    "prepare_from_rejects",
    "prepare_import",
    "run_batches",
]
