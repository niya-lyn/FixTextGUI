"""编排器配置与工作目录布局。

一次运行对应一个 ``--workdir``，目录结构固定：

    <workdir>/
        state.json                 阶段状态（断点恢复依据）
        logs/
            run.log                总运行日志
            01_merge.log ...       各阶段日志
        01_merge/                  合并 TXT + bundle 账本
        02_layout/                排版后 TXT + 账本副本
        03_replace/before|after/   替换前 / 替换后文本（专有词库生成用）
        04_quote/                  引号检查报告（txt + json）
        05_bookmap/maps/书籍专有替换词库/   专有词库表
        06_restore/                还原后的 EPUB + 校验报告
        report/                    run_report.json / run_report.md
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

#: 阶段名 -> 目录序号与中文标题
STAGE_META: dict[str, tuple[str, str]] = {
    "merge": ("01_merge", "EPUB 合并（T1.3）"),
    "layout": ("02_layout", "排版（T1.2）"),
    "replace": ("03_replace", "词库替换（T0.3 Go 引擎 + T0.2 词库）"),
    "quote": ("04_quote", "引号检查（T1.4）"),
    "bookmap": ("05_bookmap", "专有词库生成（T1.5）"),
    "restore": ("06_restore", "EPUB 还原与校验（T1.3）"),
}

#: 排版档案：把「哪些排版开关打开」固化成可复用的命名档案
LAYOUT_PROFILES: dict[str, dict[str, Any]] = {
    # HTML 安全档：只做不破坏标签结构的排版（标点规范、引号形态），
    # 关掉会重排空行/缩进的 change_text_format —— 它会给每行加全角缩进，
    # 会把 XHTML 的 <?xml ...?> 首行顶出文件头，导致章节不再是合法 XML。
    "html-safe": {
        "is_txt_file": False,
        "change_text_format": False,
        "add_indentation": False,
        "normalize_punctuations": True,
        "quotation_type": 0,
        "consecutive_quotations_type": 0,
        "rm_spaces_between_chn_chars": False,
        "paranoid_text_spacing": False,
        "format_headings": False,
        "extract_text_from_html": False,
        "add_html_tag": 0,
        "new_line_type": "\n",
        "to_encoding": "UTF-8",
    },
    # 关闭排版（只做 trim + 换行归一），用于做「只替换不改排版」的对照组
    "none": {
        "is_txt_file": False,
        "change_text_format": False,
        "add_indentation": False,
        "normalize_punctuations": False,
        "quotation_type": 0,
        "consecutive_quotations_type": 0,
        "rm_spaces_between_chn_chars": False,
        "paranoid_text_spacing": False,
        "format_headings": False,
        "extract_text_from_html": False,
        "add_html_tag": 0,
        "new_line_type": "\n",
        "to_encoding": "UTF-8",
    },
}


@dataclass
class WorkPaths:
    """工作目录内的全部路径。"""

    workdir: Path

    @property
    def logs(self) -> Path:
        return self.workdir / "logs"

    @property
    def report(self) -> Path:
        return self.workdir / "report"

    @property
    def state_file(self) -> Path:
        return self.workdir / "state.json"

    def stage_dir(self, stage: str) -> Path:
        return self.workdir / STAGE_META[stage][0]

    def stage_log(self, stage: str) -> Path:
        return self.logs / f"{STAGE_META[stage][0]}.log"

    @property
    def run_log(self) -> Path:
        return self.logs / "run.log"


@dataclass
class PipelineConfig:
    """一次全链路运行的全部输入与开关。"""

    epub: Path
    workdir: Path
    rules_before: Path
    rules_after: Path
    engine_path: Path
    #: 替换趟数，与上游 TextFixer 的 $replaceCount = 2 一致
    replace_count: int = 2
    #: 替换引擎（M4-T4.2）：go = Go 子进程（默认），python = 进程内 pyahocorasick 贪心
    engine: str = "go"
    #: Go 引擎子进程超时（秒）
    engine_timeout_s: float = 1800.0
    #: 排版档案名，见 LAYOUT_PROFILES
    layout_profile: str = "html-safe"
    #: 排版选项覆盖（会覆盖档案里的同名项）
    layout_overrides: dict[str, Any] = field(default_factory=dict)
    #: 专有词库是否写入「时间点注释」（上游默认开；关掉可让产物可复现）
    bookmap_add_current_time: bool = False
    #: 要执行的阶段（默认全链路）
    stages: tuple[str, ...] = ("merge", "layout", "replace", "quote", "bookmap", "restore")
    #: 是否允许跳过已完成的阶段（断点恢复）
    resume: bool = True
    #: 强制重跑（忽略已有状态）
    force: bool = False
    #: 失败时是否继续跑后面的阶段
    keep_going: bool = False
    #: 「我的词库」自定义词文件（M3-T3.7）；None = 用产品用户区里的默认位置
    custom_vocab_path: Path | None = None
    #: 派生规则落点（M3-T3.7）；None = 用产品用户区里的默认位置
    derived_rules_dir: Path | None = None
    #: 协作式取消（界面注入）：返回 True 表示用户已点取消。
    #: 排版等长循环在章节边界调用；默认 None = 命令行编排器不检查。
    cancel_check: Callable[[], bool] | None = None

    def __post_init__(self) -> None:
        self.epub = Path(self.epub).expanduser().resolve()
        self.workdir = Path(self.workdir).expanduser().resolve()
        self.rules_before = Path(self.rules_before).expanduser().resolve()
        self.rules_after = Path(self.rules_after).expanduser().resolve()
        self.engine_path = Path(self.engine_path).expanduser().resolve()
        # 用户区路径：显式给了就按给的（便携 / 测试），否则按产品默认位置
        from . import vocab_bridge as _vb
        self.custom_vocab_path = (Path(self.custom_vocab_path).expanduser().resolve()
                                  if self.custom_vocab_path else _vb.default_custom_path())
        self.derived_rules_dir = (Path(self.derived_rules_dir).expanduser().resolve()
                                  if self.derived_rules_dir else _vb.default_derived_dir())
        if self.layout_profile not in LAYOUT_PROFILES:
            raise ValueError(
                f"未知排版档案 {self.layout_profile!r}，可选：{sorted(LAYOUT_PROFILES)}"
            )
        if self.replace_count <= 0:
            raise ValueError("replace_count 必须是正整数")
        from .engine_choice import normalize_choice
        self.engine = normalize_choice(self.engine)

    # ---- 派生路径 ----

    @property
    def paths(self) -> WorkPaths:
        return WorkPaths(self.workdir)

    @property
    def book_stem(self) -> str:
        """书名（不含扩展名），用于各阶段产物的命名。"""
        return self.epub.stem

    @property
    def layout_options(self) -> dict[str, Any]:
        opts = dict(LAYOUT_PROFILES[self.layout_profile])
        opts.update(self.layout_overrides)
        return opts

    def stage_dir(self, stage: str) -> Path:
        return self.paths.stage_dir(stage)

    def merged_text(self) -> Path:
        return self.stage_dir("merge") / f"{self.book_stem}.txt"

    def merged_ledger(self) -> Path:
        return self.stage_dir("merge") / f"{self.book_stem}.bundle.json"

    def layout_text(self) -> Path:
        return self.stage_dir("layout") / f"{self.book_stem}.txt"

    def replace_before(self) -> Path:
        return self.stage_dir("replace") / "before" / f"{self.book_stem}.txt"

    def replace_after(self) -> Path:
        return self.stage_dir("replace") / "after" / f"{self.book_stem}.txt"

    def quote_report_txt(self) -> Path:
        return self.stage_dir("quote") / f"{self.book_stem}.report.txt"

    def quote_report_json(self) -> Path:
        return self.stage_dir("quote") / f"{self.book_stem}.report.json"

    def bookmap_dir(self) -> Path:
        return self.stage_dir("bookmap") / "maps" / "书籍专有替换词库"

    def bookmap_file(self) -> Path:
        return self.bookmap_dir() / f"{self.book_stem}.php"

    def restored_epub(self) -> Path:
        return self.stage_dir("restore") / f"{self.book_stem}_restored.epub"

    def restore_report(self) -> Path:
        return self.stage_dir("restore") / "validate_report.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "epub": str(self.epub),
            "workdir": str(self.workdir),
            "rules_before": str(self.rules_before),
            "rules_after": str(self.rules_after),
            "engine_path": str(self.engine_path),
            "replace_count": self.replace_count,
            "engine": self.engine,
            "custom_vocab_path": str(self.custom_vocab_path),
            "derived_rules_dir": str(self.derived_rules_dir),
            "engine_timeout_s": self.engine_timeout_s,
            "layout_profile": self.layout_profile,
            "layout_overrides": self.layout_overrides,
            "bookmap_add_current_time": self.bookmap_add_current_time,
            "stages": list(self.stages),
            "resume": self.resume,
            "force": self.force,
        }

    @staticmethod
    def from_state(raw: dict[str, Any]) -> "PipelineConfig":
        """从 state.json 还原配置（用于续跑时保持参数一致）。"""
        return PipelineConfig(
            epub=Path(raw["epub"]),
            workdir=Path(raw["workdir"]),
            rules_before=Path(raw["rules_before"]),
            rules_after=Path(raw["rules_after"]),
            engine_path=Path(raw["engine_path"]),
            replace_count=int(raw.get("replace_count", 2)),
            engine=str(raw.get("engine", "go")),
            custom_vocab_path=Path(raw["custom_vocab_path"]) if raw.get("custom_vocab_path") else None,
            derived_rules_dir=Path(raw["derived_rules_dir"]) if raw.get("derived_rules_dir") else None,
            engine_timeout_s=float(raw.get("engine_timeout_s", 1800.0)),
            layout_profile=str(raw.get("layout_profile", "html-safe")),
            layout_overrides=dict(raw.get("layout_overrides", {})),
            bookmap_add_current_time=bool(raw.get("bookmap_add_current_time", False)),
            stages=tuple(raw.get("stages", ("merge", "layout", "replace", "quote", "bookmap", "restore"))),
        )


def dump_json(path: Path, payload: Any) -> Path:
    """落盘 JSON（UTF-8、不转义中文、缩进 2）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
