"""
FixText V1 · 校正后台执行器（M2-T2.3 可视化进度与取消）
=========================================================

把 M1 编排器（fixtext_pipeline）的六个阶段接到 Qt 界面：

* **不重做 M1 引擎**——本文件只做「进度反馈 + 取消 + 回滚」的对接层，
  阶段实现全部复用 ``fixtext_pipeline.stages`` 里的原类。
* **进度**：阶段开始/结束时发信号；预计剩余时间由「已完成阶段的实际耗时」
  对「参考权重」做比例缩放外推（参考值来自真实大语料的实测耗时）。
* **取消**：点「取消」立刻置位取消标记；替换阶段杀掉 Go 引擎子进程（约 1 秒内）；
  排版在**章节边界**响应（``cancel_check``）；其它纯 Python 阶段在阶段边界生效。
  取消后整个工作目录被删除，界面回到可重新开始的干净状态。
* **人话步骤**：六阶段的界面文案在本文件 ``HUMAN_STAGES`` 一处定义，
  内部阶段名（merge/layout/…）不进入任何用户可见文案。

阶段日志照常落在工作目录（供排查），但界面从不展示命令行输出。
"""

from __future__ import annotations

import shutil
import subprocess as _subprocess_mod
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

#: 人话错误体系（T2.4）。合并后各页错误出口统一走这里：
#: 已判定的人话错误仍用页内提示条 / 结果卡（用户不点弹窗也能继续），
#: 只有「没预期到的异常」才经 error_center 归类→写日志→弹人话错误卡。
try:
    import fixtext_error_center as error_center
except Exception:                                    # pragma: no cover
    error_center = None


# ---------------------------------------------------------------------------
# 人话步骤（六阶段 → 用户能懂的文案）。内部阶段名只存在于本文件的 key 里。
# ---------------------------------------------------------------------------

#: 阶段键 → 进度条文案（M5-EX.1 可按开关动态增减）
_STAGE_COPY: dict[str, dict[str, str]] = {
    "merge": dict(name="读取章节", desc="从 EPUB 提取正文并建立章节清单"),
    "layout": dict(name="整理排版", desc="标点规范化，逐章保护标签结构"),
    "replace_preprocess": dict(name="预处理替换", desc="主替换前用预处理词库单独跑一轮"),
    "replace_strict": dict(name="严格替换", desc="用严格词库单独跑一轮"),
    "replace": dict(name="词库批量替换", desc="按勾选词库批量替换错词"),
    "replace_zhuyin": dict(name="生僻字注音", desc="为生僻字补充拼音注音"),
    "quote": dict(name="检查引号配对", desc="逐章检查引号配对与形态"),
    "bookmap": dict(name="提取本书专有词", desc="识别本书的人名/地名等专名"),
    "restore": dict(name="写回校正结果", desc="写回章节并校验与原书一致"),
}

#: 默认六阶段（无可选轮）；动态列表由 ``build_human_stages`` 生成
HUMAN_STAGES: list[dict[str, str]] = [
    dict(key=k, **_STAGE_COPY[k])
    for k in ("merge", "layout", "replace", "quote", "bookmap", "restore")
]


def build_human_stages(
    *,
    skip_layout: bool = False,
    skip_merge: bool = False,
    enable_preprocess: bool = False,
    enable_strict: bool = False,
    zhuyin_mode: str = "off",
) -> list[dict[str, str]]:
    """按 M5-EX.1 开关拼进度步（与 pipeline ``build_stage_keys`` 顺序一致）。

    ``skip_merge``：EPUB 已有工作区 ``book.txt``+账本时跳过合并，直接从工作副本进排版。
    不在此 import pipeline：``CorrectionJob`` 构造时可能尚未 bootstrap。
    """
    keys: list[str] = []
    if not skip_merge:
        keys.append("merge")
    if not skip_layout:
        keys.append("layout")
    if enable_preprocess:
        keys.append("replace_preprocess")
    if enable_strict:
        keys.append("replace_strict")
    keys.append("replace")
    if str(zhuyin_mode) not in ("", "off", "None"):
        keys.append("replace_zhuyin")
    keys.extend(["quote", "bookmap", "restore"])
    out: list[dict[str, str]] = []
    for k in keys:
        copy = _STAGE_COPY.get(k) or dict(name=k, desc="")
        out.append(dict(key=k, name=copy["name"], desc=copy["desc"]))
    return out


#: 参考耗时（秒），来自一本 788 章 / 314 万字符的真实语料实测，
#: 用于第一个阶段完成前的初始估算；之后按实际耗时等比例修正。
REFERENCE_SEC: dict[str, float] = {
    "merge": 0.82,
    "layout": 10.92,
    "replace_preprocess": 1.5,
    "replace_strict": 1.5,
    "replace": 3.05,
    "replace_zhuyin": 2.0,
    "quote": 1.28,
    "bookmap": 0.71,
    "restore": 2.92,
}


def _count_replaced(before: Path | None, after: Path | None) -> int | None:
    """统计本次替换的命中数（按导出口径，与导出统计里的数字一致）。

    命中数是「改前/改后正文实际差异」算出来的，不是引擎自报的次数；
    算不出来（文件缺失/依赖不可用）时返回 None，界面上显示「—」，
    绝不编一个数字充数。
    """
    if not before or not after:
        return None
    try:
        import tempfile

        import fixtext_export as fx

        if not (before.is_file() and after.is_file()):
            return None
        # 统计要用到引擎包里的分词/差异库，先把它们挂上（与导出同一条引导）
        fx.ensure_vendor(None)
        with tempfile.TemporaryDirectory(prefix="fixtext-hits-") as tmp:
            hits, _rows = fx._count_hits(before, after, Path(tmp))
        return int(hits)
    except Exception:
        return None


def _artifact_paths(layout: dict, replace: dict, quote: dict,
                    restore: dict, bookmap: dict | None = None,
                    merge: dict | None = None) -> dict[str, str]:
    """汇总本次运行的**权威产物路径**（各阶段报告里自述的绝对路径）。

    导出侧拿它定位校正后的正文，不必再按文件名推测——导入侧固定写
    ``book.txt``、管线按书名命名，两套名字天生不同，猜名字必错。
    账本优先取排版产物（与 after_text 同 nonce）；跳过排版时退回合并账本。
    """
    laid_out = str(layout.get("text_path") or "")
    merge_text = str((merge or {}).get("text_path") or "")
    ledger = ""
    for base in (laid_out, merge_text):
        if not base:
            continue
        cand = Path(base).with_name(Path(base).stem + ".bundle.json")
        if cand.is_file():
            ledger = str(cand)
            break
    if not ledger:
        lp = str((merge or {}).get("ledger_path") or "")
        if lp and Path(lp).is_file():
            ledger = lp
    return {
        "laid_out_text": laid_out,
        "before_text": str(replace.get("before_path") or ""),
        "after_text": str(replace.get("after_path") or ""),
        "checked_file": str(quote.get("checked_file") or ""),
        "ledger": ledger,
        "restored_epub": str(restore.get("restored_epub") or ""),
        "book_map_file": str((bookmap or {}).get("book_map_file") or ""),
    }


class CorrectionCancelled(RuntimeError):
    """用户取消。"""


# ---------------------------------------------------------------------------
# 可取消的 subprocess 代理：只替换 Go 引擎客户端里的 subprocess.run
# ---------------------------------------------------------------------------

class _SubprocessProxy:
    """装在 ``fixtext.engine.client.subprocess`` 上的代理。

    与原 ``subprocess.run(cmd, capture_output=True, timeout=…)`` 语义一致，
    但轮询进程状态：取消标记置位 → 立即 kill 并抛 ``CorrectionCancelled``；
    超时 → kill 并抛真正的 ``subprocess.TimeoutExpired``（保持上游错误归类）。
    其余属性全部透传原模块。
    """

    def __init__(self, job: "CorrectionJob"):
        self._job = job

    def __getattr__(self, name: str):
        return getattr(_subprocess_mod, name)

    def run(self, cmd, capture_output: bool = False, timeout=None, cwd=None, **_kw):
        # Windows：隐藏 Go 引擎 CUI 黑窗（见 fixtext_pipeline.winproc）
        try:
            from fixtext_pipeline.winproc import hidden_kwargs as _hidden
            _win = _hidden()
        except Exception:  # noqa: BLE001 — 缺模块时仍能跑，只是可能闪窗
            _win = {}
        proc = _subprocess_mod.Popen(
            cmd,
            stdout=_subprocess_mod.PIPE,
            stderr=_subprocess_mod.PIPE,
            cwd=cwd,
            **_win,
        )
        self._job._active_proc = proc
        deadline = None if timeout is None else time.monotonic() + timeout
        try:
            while True:
                returncode = proc.poll()
                if returncode is not None:
                    break
                if self._job.cancel_requested:
                    proc.kill()
                    proc.wait()
                    raise CorrectionCancelled("已终止替换引擎")
                if deadline is not None and time.monotonic() > deadline:
                    proc.kill()
                    proc.wait()
                    raise _subprocess_mod.TimeoutExpired(cmd, timeout)
                time.sleep(0.05)
            out, err = proc.communicate()
        finally:
            self._job._active_proc = None
        return _subprocess_mod.CompletedProcess(cmd, returncode, stdout=out, stderr=err)


# ---------------------------------------------------------------------------
# 校正任务（纯 Python，不依赖 Qt；由 CorrectionWorker 放进线程执行）
# ---------------------------------------------------------------------------

class CorrectionJob:
    """驱动 fixtext_pipeline 六阶段的一次真实运行。

    参数（RunContext，由界面或测试注入）：
        epub            待校正的 EPUB 路径
        workdir         本次运行的独立工作目录（取消时整个删除）
        rules_before/after  词库规则 JSON
        engine_path     Go 引擎二进制
        pipeline_root   fixtext_pipeline 产品目录（含 fixtext_pipeline/ 与 vendor/）
        engine          本次运行用的替换引擎（``go``|``python``）。
                        None = 读持久化配置（契约键 ``engine``，默认 ``go``）；
                        降级路径确认后由界面显式传 ``python``——只影响本次
                        运行，不写回设置（M4-T4.2 §3.3）。
    """

    def __init__(self, *, epub: Path, workdir: Path, rules_before: Path,
                 rules_after: Path, engine_path: Path, pipeline_root: Path,
                 title: str = "", author: str = "", source_epub: Path | None = None,
                 custom_vocab_path: Path | None = None,
                 derived_rules_dir: Path | None = None,
                 word_states_path: Path | None = None,
                 engine: str | None = None,
                 auto_fix_quotes: bool = False,
                 quotation_rules_path: Path | None = None,
                 skip_layout: bool = False,
                 enable_preprocess: bool = False,
                 enable_strict: bool = False,
                 zhuyin_mode: str = "off",
                 selected_bags: tuple[str, ...] | list[str] | None = None,
                 working_text: Path | None = None,
                 working_ledger: Path | None = None,
                 on_stage_started: Callable[[int], None] | None = None,
                 on_stage_finished: Callable[[int, float], None] | None = None):
        self.epub = Path(epub)
        #: 界面显示的书名 / 作者（历史记录要用；缺省回落到文件名）
        self.title = str(title or "").strip()
        self.author = str(author or "").strip()
        #: M4-EX.6-R3：词替换后自动修引号（默认关）
        self.auto_fix_quotes = bool(auto_fix_quotes)
        self.quotation_rules_path = (
            Path(quotation_rules_path) if quotation_rules_path else None)
        #: 用户导入的原书（纯文本书包装成电子书时，原书另有其物）
        self.source_epub = Path(source_epub) if source_epub else None
        self.workdir = Path(workdir)
        self.rules_before = Path(rules_before)
        self.rules_after = Path(rules_after)
        self.engine_path = Path(engine_path)
        self.pipeline_root = Path(pipeline_root)
        #: 「我的词库」自定义词与派生规则落点（M3-T3.7）。None = 用产品里的默认位置；
        #: 测试 / 便携场景可指到临时子树，绝不碰交付包自带的用户区。
        self.custom_vocab_path = Path(custom_vocab_path) if custom_vocab_path else None
        self.derived_rules_dir = Path(derived_rules_dir) if derived_rules_dir else None
        #: 词条禁用集文件（V1.1-T1.3）。None = 产品里 `workspace/vocab/word_states.json`；
        #: 测试 / 隔离场景可指到临时文件，这样「禁用一条词」能真正作用到本次运行。
        self.word_states_path = Path(word_states_path) if word_states_path else None
        #: 本次运行的替换引擎（M4-T4.2）。None = 启动时读配置键 ``engine``；
        #: 界面降级确认后显式传 ``python``（只本次生效，不写回设置）。
        self.engine = engine
        #: 工作区正文 / 账本（EPUB）：有则跳过 merge，直接从 TXT 工作副本进后续阶段
        self.working_text = Path(working_text) if working_text else None
        self.working_ledger = Path(working_ledger) if working_ledger else None
        self.skip_merge = bool(
            self.working_text and self.working_text.is_file()
            and self.working_ledger and self.working_ledger.is_file()
        )
        #: M5-EX.1 运行模式 / 分袋开关
        self.skip_layout = bool(skip_layout)
        self.enable_preprocess = bool(enable_preprocess)
        self.enable_strict = bool(enable_strict)
        self.zhuyin_mode = str(zhuyin_mode or "off")
        if selected_bags is not None:
            self.selected_bags = tuple(selected_bags)
        else:
            try:
                from fixtext_pipeline.bags import DEFAULT_SELECTED_BAGS
                self.selected_bags = tuple(DEFAULT_SELECTED_BAGS)
            except Exception:  # pragma: no cover
                self.selected_bags = ("b1", "custom", "cjk")
        #: 实际用上的引擎（run() 里回填，供测试 / 证据核对）
        self.engine_used: str | None = None
        self._on_stage_started = on_stage_started
        self._on_stage_finished = on_stage_finished

        self._cancel = threading.Event()
        self._active_proc: _subprocess_mod.Popen | None = None
        self._lock = threading.Lock()

        # 运行状态（界面轮询读取）
        self.current_index = -1          # 当前阶段下标（-1 未开始）
        self.stage_elapsed: dict[str, float] = {}
        self.stage_reports: dict[str, dict[str, Any]] = {}
        self._stage_started_at = 0.0
        self._run_started_at = 0.0
        #: 本次任务的动态进度步（构造时即定，供 ProgressDialog）
        self.human_stages: list[dict[str, str]] = build_human_stages(
            skip_layout=self.skip_layout,
            skip_merge=self.skip_merge,
            enable_preprocess=self.enable_preprocess,
            enable_strict=self.enable_strict,
            zhuyin_mode=self.zhuyin_mode,
        )

    # ---------------- 取消 ----------------

    def set_stage_callbacks(self, on_started, on_finished) -> None:
        """注入阶段回调（界面线程可在启动前或运行中挂接）。"""
        self._on_stage_started = on_started
        self._on_stage_finished = on_finished

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def request_cancel(self) -> None:
        """请求取消：立即置位标记并终止正在跑的引擎子进程。

        可从任意线程调用（界面线程点击「取消」即走这里）。
        """
        self._cancel.set()
        proc = self._active_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    # ---------------- 进度推算 ----------------

    def _now(self) -> float:
        return time.monotonic()

    def elapsed_s(self) -> float:
        if not self._run_started_at:
            return 0.0
        return self._now() - self._run_started_at

    def _current_elapsed_s(self) -> float:
        if self.current_index < 0 or not self._stage_started_at:
            return 0.0
        return self._now() - self._stage_started_at

    def snapshot(self) -> dict[str, Any]:
        """界面轮询用：进度百分比、已用时间、预计剩余秒数。"""
        with self._lock:
            elapsed_copy = dict(self.stage_elapsed)
        done_sec = sum(elapsed_copy.values())
        cur_sec = self._current_elapsed_s()
        total_done = done_sec + cur_sec

        stages = self.human_stages
        done_keys = list(elapsed_copy.keys())
        if done_keys:
            scale = done_sec / max(
                0.001,
                sum(REFERENCE_SEC.get(k, 2.0) for k in done_keys),
            )
        else:
            scale = 1.0
        remaining_keys = [s["key"] for s in stages if s["key"] not in elapsed_copy]
        # 当前阶段已跑的秒数从「剩余」里扣掉
        eta = max(
            0.0,
            sum(REFERENCE_SEC.get(k, 2.0) for k in remaining_keys) * scale - cur_sec,
        )
        est_total = total_done + eta
        percent = 0.0 if est_total <= 0 else total_done / est_total * 100
        if self.current_index >= 0 and self.current_index < len(stages) - 1:
            percent = min(percent, 96.0)   # 最后一步完成前不显示满格
        return {
            "percent": round(min(percent, 100.0), 1),
            "elapsed_s": round(total_done, 1),
            "eta_s": round(eta, 1),
            "current_index": self.current_index,
            "cancelling": self.cancel_requested,
        }

    # ---------------- 主循环 ----------------

    def run(self) -> dict[str, Any]:
        """执行六阶段。返回汇总 dict；取消抛 ``CorrectionCancelled``。

        汇总供结果卡使用——全部来自各阶段真实报告，不含编造数字。
        """
        self._bootstrap_pipeline()
        from fixtext_pipeline.config import PipelineConfig, STAGE_META
        from fixtext_pipeline.logsetup import StageLogger, capture_output
        from fixtext_pipeline.stages import STAGES

        # 本次运行的替换引擎（M4-T4.2）：显式指定优先（降级确认后的
        # ``python`` 只本次生效），否则读持久化配置键 ``engine``（默认 go）。
        from fixtext_pipeline.engine_choice import get_engine_choice
        engine = self.engine if self.engine is not None else get_engine_choice()
        self.engine_used = engine

        stages = self.human_stages
        cfg = PipelineConfig(
            epub=self.epub,
            workdir=self.workdir,
            rules_before=self.rules_before,
            rules_after=self.rules_after,
            engine_path=self.engine_path,
            engine=engine,
            replace_count=2,
            layout_profile="html-safe",
            stages=tuple(s["key"] for s in stages),
            resume=False,   # 界面每次都是全新运行；断点续跑属引擎命令行的能力
            force=False,
            keep_going=False,
            # 自定义词生效（M3-T3.7）：把「我的词库」交给替换阶段合成派生规则
            custom_vocab_path=self.custom_vocab_path,
            derived_rules_dir=self.derived_rules_dir,
            # 词条禁用（V1.1-T1.3）：禁用集进装载层过滤 + 阶段指纹
            word_states_path=self.word_states_path,
            # 排版章循环协作取消（P1-7）
            cancel_check=lambda: self.cancel_requested,
            # M4-EX.6-R3：词替换后可选自动修引号（与检查页共用规则文件）
            auto_fix_quotes=self.auto_fix_quotes,
            quotation_rules_path=self.quotation_rules_path,
            skip_layout=self.skip_layout,
            enable_preprocess=self.enable_preprocess,
            enable_strict=self.enable_strict,
            zhuyin_mode=self.zhuyin_mode,
            selected_bags=self.selected_bags,
        )

        # 准备目录（与编排器 _prepare 相同的布局）
        cfg.workdir.mkdir(parents=True, exist_ok=True)
        cfg.paths.logs.mkdir(parents=True, exist_ok=True)
        cfg.paths.report.mkdir(parents=True, exist_ok=True)
        for s in stages:
            cfg.stage_dir(s["key"]).mkdir(parents=True, exist_ok=True)

        # --- 预备份：校正前工作区副本快照 ------------------------------------------------
        # _sync_book_text_from_run 会把 replace 后的 after_text 写回 shelf book.txt
        # 和账本；后续点「恢复到校正前」必须能还原到这个备份，否则连续两次校正的
        # 第二次会以已经校正过的文本为起点，hits 为 0（BUG-回归保护）。
        if self.working_text and self.working_text.is_file():
            pre_dir = cfg.workdir / "00_pre_correction"
            pre_dir.mkdir(exist_ok=True)
            try:
                shutil.copy2(self.working_text, pre_dir / "book.txt")
            except Exception:
                pass  # best-effort，备份失败不阻塞校正
            if self.working_ledger and self.working_ledger.is_file():
                try:
                    shutil.copy2(self.working_ledger, pre_dir / "ledger.bundle.json")
                except Exception:
                    pass
            import_json = self.working_text.parent / "import.json"
            if import_json.is_file():
                try:
                    shutil.copy2(import_json, pre_dir / "import.json")
                except Exception:
                    pass
        # --------------------------------------------------------------------------------

        # 跳过 merge 时仍要有 01_merge，供排版读入工作区 TXT
        if self.skip_merge:
            cfg.stage_dir("merge").mkdir(parents=True, exist_ok=True)
            self._seed_merge_from_working(cfg)

        # 把引擎客户端的 subprocess 换成可取消代理（只影响本进程内的调用）
        import fixtext.engine.client as _engine_client
        _engine_client.subprocess = _SubprocessProxy(self)

        # Python 引擎在进程内跑（没有子进程可杀）：挂协作式取消钩子，
        # 跑完（含取消 / 失败）立刻注销，不影响后续别的调用方。
        py_cancel_hook_installed = False
        if engine == "python":
            from fixtext.engine import py_engine
            py_engine.set_cancel_check(lambda: self.cancel_requested)
            py_cancel_hook_installed = True

        self._run_started_at = self._now()
        self._run_started_wall = time.time()
        try:
            for i, meta in enumerate(stages):
                if self.cancel_requested:
                    raise CorrectionCancelled("在阶段开始前取消")
                key = meta["key"]
                logger = StageLogger(cfg.paths.stage_log(key), echo=False)
                stage = STAGES[key](cfg, logger)
                self.current_index = i
                self._stage_started_at = self._now()
                if self._on_stage_started:
                    self._on_stage_started(i)
                try:
                    with capture_output(logger):
                        stage_report = stage.run() or {}
                except Exception as exc:
                    # 排版等阶段在章节边界抛 StageCancelled → 统一成界面取消
                    from fixtext_pipeline.stages import StageCancelled
                    if isinstance(exc, StageCancelled):
                        raise CorrectionCancelled(str(exc) or "章节边界取消") from exc
                    raise
                finally:
                    logger.close()
                elapsed = round(self._now() - self._stage_started_at, 3)
                with self._lock:
                    self.stage_elapsed[key] = elapsed
                    self.stage_reports[key] = stage_report
                if self._on_stage_finished:
                    self._on_stage_finished(i, elapsed)
                if self.cancel_requested:
                    # 阶段函数已自然返回，但用户在此期间点了取消：不进入下一阶段
                    raise CorrectionCancelled("阶段边界取消")
        except CorrectionCancelled:
            self._cleanup()
            raise
        finally:
            if py_cancel_hook_installed:
                from fixtext.engine import py_engine
                py_engine.set_cancel_check(None)

        return self._build_summary(cfg)

    def _seed_merge_from_working(self, cfg) -> None:
        """EPUB：用工作区 ``book.txt`` + 账本填充合并产物，跳过重新 merge 原件。"""
        import shutil

        assert self.working_text is not None and self.working_ledger is not None
        dst_txt = cfg.merged_text()
        dst_led = cfg.merged_ledger()
        shutil.copy2(self.working_text, dst_txt)
        shutil.copy2(self.working_ledger, dst_led)
        chapters = None
        try:
            from epubtext.bundle import Ledger
            chapters = sum(len(b.chapters) for b in Ledger.load(dst_led).books)
        except Exception:
            chapters = None
        self.stage_reports["merge"] = {
            "text_path": str(dst_txt),
            "ledger_path": str(dst_led),
            "chapters": chapters,
            "seeded_from_working_copy": True,
        }
        self.stage_elapsed["merge"] = 0.0

    # ---------------- 收尾 ----------------

    def _cleanup(self) -> None:
        """取消后的状态回滚：删除整个工作目录，不留半成品。"""
        if self.workdir.exists():
            shutil.rmtree(self.workdir, ignore_errors=True)
            if self.workdir.exists():   # 只读文件导致删不掉时补执行位再删
                for p in self.workdir.rglob("*"):
                    try:
                        p.chmod(p.stat().st_mode | 0o200)
                    except OSError:
                        pass
                shutil.rmtree(self.workdir, ignore_errors=True)

    def _build_summary(self, cfg) -> dict[str, Any]:
        merge = self.stage_reports.get("merge", {})
        layout = self.stage_reports.get("layout", {})
        replace = self.stage_reports.get("replace", {})
        quote = self.stage_reports.get("quote", {})
        bookmap = self.stage_reports.get("bookmap", {})
        restore = self.stage_reports.get("restore", {})
        counts = bookmap.get("entry_counts") or {}
        summary = {
            "book": cfg.epub.stem,
            "title": self.title or cfg.epub.stem,
            "author": self.author,
            "source_epub": str(self.source_epub or self.epub),
            "started_at": getattr(self, "_run_started_wall", 0.0),
            "finished_at": time.time(),
            "workdir": str(cfg.workdir),
            "chapters": merge.get("chapters"),
            "layout_changed": layout.get("changed"),
            "replace_rules": replace.get("rules"),
            "replace_engine": replace.get("engine") or self.engine_used,
            "replace_chars_in": replace.get("chars_in"),
            "replace_chars_out": replace.get("chars_out"),
            "quote_errors": quote.get("error_count"),
            "quote_errors_before": quote.get(
                "error_count_before", quote.get("error_count")),
            "quote_fixed": quote.get("quote_fixed", 0),
            "auto_fix_quotes": bool(quote.get("auto_fix_quotes", False)),
            "hits": _count_replaced(
                Path(str(replace.get("before_path") or "")) if replace.get("before_path") else None,
                Path(str(replace.get("after_path") or "")) if replace.get("after_path") else None,
            ),
            "bookmap_entries": sum(counts.values()) if counts else None,
            "book_words": self._book_words_preview(bookmap),
            # 引擎原始条数（含重复 vs 去重后的清单条数）：两个数都摆出来，
            # 界面上的「发现 N 条」= len(book_words)，可与这里互相核对。
            "book_words_declared_total": bookmap.get("entries_total"),
            "book_words_unique": bookmap.get("entries_unique"),
            "restored_sha256": restore.get("restored_sha256"),
            "stage_elapsed": dict(self.stage_elapsed),
            "total_elapsed_s": round(self.elapsed_s(), 3),
            # 本次运行的**权威产物路径**：各阶段自己报告的绝对路径。
            # 导出侧据此定位，不再按文件名猜（导入侧固定写 book.txt，
            # 而管线按书名命名，两套名字天生不同 → 猜必错）。
            "artifacts": _artifact_paths(
                layout, replace, quote, restore, bookmap, merge=merge),
        }
        # 运行摘要落盘（工作目录内，供导出/排查；界面不直接展示路径）
        from fixtext_pipeline.config import dump_json
        dump_json(cfg.paths.report / "ui_run_summary.json", summary)
        return summary

    # ---------------- 本书专有词 ----------------

    def _book_words_preview(self, bookmap: dict) -> list[dict]:
        """把 bookmap 阶段抽出的**真实**专有词条整理成界面可用的行。

        没有真实词条时返回空列表——界面据此不显示横幅，绝不退回演示数据。

        M3-T3.3：**不再截断**。以前 bookmap 报告只带前 20 条，界面「整组加入」
        最多写进 20 条，而引擎实际抽出几千条——这是静默丢条。现在报告带全量，
        这里的条数 == 引擎产物去重后的条数，``declared_total`` 另行给出引擎
        原始条数（含重复），两个数都摆出来，不互相顶替。

        每条带：词条（原词）/ 替换值 / 类型 / 出现次数，供预览清单逐条展示。
        """
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        book = str(self.title or self.epub.stem or "")
        preview = bookmap.get("entry_preview") or {}
        for _key, arr in preview.items():
            for w in arr or []:
                before = str(w.get("before") or "").strip()
                after = str(w.get("after") or "").strip()
                if not before:
                    continue
                key = (before, after or before)
                if key in seen:
                    continue
                seen.add(key)
                out.append(dict(
                    word=before,
                    value=after or before,
                    type=str(w.get("type") or "专有名词"),
                    count=int(w.get("count") or 1),
                    note=f"本书专有词 · 《{book}》",
                ))
        return out

    # ---------------- 引擎引导 ----------------

    def _bootstrap_pipeline(self) -> None:
        root = str(self.pipeline_root.resolve())
        if root not in sys.path:
            sys.path.insert(0, root)
        from fixtext_pipeline.vendor_bootstrap import bootstrap
        bootstrap(root, strict=True)


# ---------------------------------------------------------------------------
# Qt 包装：线程 + 信号
# ---------------------------------------------------------------------------

class CorrectionWorker(QObject):
    """在后台线程跑 ``CorrectionJob``，用信号向界面汇报。

    信号：
        stage_started(i)        第 i 个步骤开始
        stage_finished(i, sec)  第 i 个步骤完成，耗时 sec 秒
        succeeded(summary)      全部完成（summary 见 ``CorrectionJob._build_summary``）
        failed(message)         阶段失败（message 已是人话）
        cancelled()             取消完成，工作区已清理干净
        engine_failed(reason)   Go 引擎不可用（M4-T4.2 降级触发）——工作线程
                                已结束、半成品已清理，由界面弹确认：用户同意
                                则改走 Python 引擎重跑本次校正，拒绝则明确报错
    """

    stage_started = Signal(int)
    stage_finished = Signal(int, float)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    engine_failed = Signal(str)

    def __init__(self, job: CorrectionJob, parent=None):
        super().__init__(parent)
        self.job = job
        self.thread: threading.Thread | None = None

    # ---- 界面线程调用 ----

    def start(self):
        self.thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self.thread.start()

    def request_cancel(self):
        self.job.request_cancel()

    def snapshot(self) -> dict[str, Any]:
        return self.job.snapshot()

    @property
    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    # ---- 工作线程执行 ----

    def _run_in_thread(self):
        # 阶段回调 → Qt 信号（跨线程 emit 自动排队到界面线程）
        self.job.set_stage_callbacks(
            lambda i: self.stage_started.emit(i),
            lambda i, sec: self.stage_finished.emit(i, sec),
        )
        try:
            summary = self.job.run()
        except CorrectionCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:  # noqa: BLE001 - 界面兜底：任何阶段异常都归成人话
            # Go 引擎不可用（M4-T4.2 §3.3）：单独分流——半成品清理后发
            # engine_failed，由界面弹「改用 Python 引擎」确认，不当普通失败。
            try:
                from fixtext_pipeline.stages.replace import GoEngineUnavailableError
            except ImportError:                       # pragma: no cover
                GoEngineUnavailableError = ()          # type: ignore[assignment]
            if GoEngineUnavailableError and isinstance(exc, GoEngineUnavailableError):
                self.job._cleanup()
                # 原因已是人话（"Go 引擎不存在：…可在设置里改用 Python…"），
                # 界面的降级确认弹窗直接用，不再叠加"校正未完成"前缀
                self.engine_failed.emit(str(exc))
                return
            # 没预期到的异常：归类 → 写诊断日志 → 人话错误卡（跨线程自动投递）。
            if error_center is not None:
                try:
                    error_center.report(exc, context="correction")
                except Exception:
                    pass
            self.failed.emit(self._human_error(exc))
            return
        self.succeeded.emit(summary)

    @staticmethod
    def _human_error(exc: Exception) -> str:
        """阶段异常 → 用户能看懂的一句话（不露内部阶段名/堆栈/路径）。"""
        text = str(exc).strip() or exc.__class__.__name__
        # 常见引擎错误形态「E1004 …」等码不进界面
        if text.startswith("E") and len(text) > 4 and text[1].isdigit():
            return "校正引擎执行失败，本次未产生任何结果文件，可重试。"
        return f"校正未完成：{text[:120]}"
