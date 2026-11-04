"""M4-T4.4 写路径静态审计：枚举产品代码里全部「写文件 / 建目录 / 删文件」点，
逐条判定落点是否在白名单内。

白名单（任务卡 §4.6 T4.4）：
    workspace/   产品用户区（词库 / 还原点 / 设置 / 导入副本）
    runs/        一次校正的工作目录
    logs/        日志与诊断记录
    export_dir   用户在导出页显式选择的目录（只在导出动作里出现）
    declared_scratch  显式声明的临时草稿（tempfile / 任务卡允许的中间态），
                      必须 (a) 在系统临时目录里，(b) 用完即删
    n/a          产品运行期不调用的构建期 / 命令行工具与只读误命中

判定方式分两层：
  1) 自动归类：按写入表达式里出现的受控符号（workspace / runs / logs / out_dir /
     tempfile...）给出初判；
  2) 人工复核表 OVERRIDES：凡是自动归类不能确定的那一行，必须有一条复核记录
     （落点 + 依据 + 结论）。没有复核记录的条目一律计入 UNREVIEWED，
     审计结论为 FAIL —— 这样「漏审」会被脚本自己抓出来，而不是被默默放过。

运行：python3.12 tools/audit_t44_write_paths.py
产出：evidence/t44_write_paths.json（清单 + 统计 + 结论）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
EVID = PKG / "evidence"

#: 参与审计的产品代码范围（测试 / 验收脚本不属于产品运行期，单列一节说明）
SCOPES = [
    "main_app.py",
    "fixtext_ui",
    "fixtext_import",
    "fixtext_error_center",
    "pipeline/fixtext_pipeline",
    "pipeline/vendor/fixtext",
    "pipeline/vendor/epubtext",
    "pipeline/vendor/fixtext_bookmap",
    "pipeline/vendor/fixtext_quotation",
]

#: 写动作的识别式（只认真正会落到磁盘的调用）
WRITE_PAT = re.compile(
    r"("
    r"\.write_text\s*\(|\.write_bytes\s*\(|"
    r"\bopen\s*\([^)]*[\"'](w|a|wb|ab|w\+|a\+|xb)[\"']|"
    r"\.mkdir\s*\(|\bos\.makedirs\s*\(|"
    r"\bshutil\.(copy|copyfile|copy2|move|rmtree)\s*\(|"
    r"\.copytree\s*\(|"
    r"\brmtree\s*\(|\bos\.(remove|unlink|rename|replace)\s*\(|"
    r"[^.\w]unlink\s*\(|"
    r"\bzipfile\.ZipFile\s*\([^)]*[\"']w[\"']|"
    r"tempfile\.(mkdtemp|mkstemp|NamedTemporaryFile|TemporaryDirectory)\s*\(|"
    r"\.sync\s*\("
    r")"
)

#: 设置写入（只在接收方是设置对象时才算写点；进度条 setValue 不算）
SETTINGS_PAT = re.compile(r"(QSettings|AppSettings|_settings|settings)\s*[\.\w]*\.setValue\s*\(")

#: 自动归类规则：(标签, 判定依据, 正则)
AUTO_RULES: list[tuple[str, str, str]] = [
    ("declared_scratch",
     "显式临时草稿：系统临时目录 + 用完删除（tempfile 系列）",
     r"tempfile\.(mkdtemp|mkstemp|NamedTemporaryFile|TemporaryDirectory)|"
     r"TemporaryDirectory\("),
    ("declared_scratch",
     "原子写的过渡文件：与目标同目录的隐藏前缀临时文件，写完 os.replace 覆盖并清理",
     r"mkstemp\(dir=|prefix=[\"']\.(snap|vocab|dfr)-"),
    ("logs",
     "日志 / 诊断记录：路径来自 log_dir()（默认 <包根>/logs，可用 FIXTEXT_LOG_DIR 改指）",
     r"log_dir|_log_dir|rotated|diaglog"),
    ("workspace",
     "用户区文件：路径含 workspace/（导入副本、自定义词库、派生规则、还原点、设置）",
     r"workspace|settings_path|CUSTOM_DIR|snap_dir|custom\.path"),
    ("runs",
     "一次校正的工作目录：路径来自 runs_root / workdir / stage_dir / WorkPaths",
     r"runs_root|workdir|stage_dir|WorkPaths|cfg\.(paths|workdir)|self\.workdir|"
     r"logs\(\)|report\(\)|run_dir"),
    ("export_dir",
     "导出目录：用户在导出页显式选择的 out_dir（默认包根「导出/」；"
     "历史页重新导出落「导出/历史记录/书名_时间戳/」）",
     r"out_dir|stats_text_path|stats_csv_path|output_dir"),
]

#: 人工复核表：「相对路径:行号」→ (标签, 落点, 依据)
OVERRIDES: dict[str, tuple[str, str, str]] = {
    "fixtext_ui/build_qss.py:402": (
        "n/a",
        "构建期工具：输出 <包根>/fixtext_ui/fixtext.qss",
        "只在开发时手工跑（改令牌后重新生成样式表），产品运行期不调用；不涉及用户数据"),
    "fixtext_import/textfile.py:85": (
        "workspace",
        "调用方给的 dst 的父目录（导入副本目标）",
        "copy_verbatim 建目标目录；产品内唯一调用点是 importer（用户区书籍目录）"),
    "fixtext_import/textfile.py:97": (
        "workspace",
        "调用方给的 dst（导入副本）",
        "原子写的 os.replace 落正式副本"),
    "pipeline/vendor/fixtext/engine/client.py:278": (
        "declared_scratch|export_dir|runs",
        "同 277 行的输出目标（原子写 os.replace）",
        "同上"),
    # ---- M4-T4.4 修复过的四处越界（重点抽查对象） ----
    "pipeline/vendor/fixtext/common/paths.py:44": (
        "workspace",
        "<包根>app_data_dir() = app_root()（交付包根），仅确保存在",
        "M4-T4.4 修复：原实现写 ~/.local/share/FixText（越界）；现在 app_root() 由 "
        "app_data_dir() 返回，调用点只有 workspace/ 与 logs/"),
    "pipeline/vendor/fixtext/common/paths.py:52": (
        "logs",
        "<包根>/logs（或 FIXTEXT_LOG_DIR 覆盖值）",
        "M4-T4.4 修复：log_dir() 默认 <包根>/logs，允许环境变量改指；不再散落到系统目录"),
    "fixtext_error_center/diaglog.py:52": (
        "logs",
        "<包根>/logs（init() 未显式指定时的回落值）",
        "M4-T4.4 修复：原回落 tempfile.gettempdir()/fixtext-diag（越界且不清理）；现回落 PKG_ROOT/logs"),
    "fixtext_error_center/diaglog.py:91": (
        "logs",
        "<包根>/logs/fixtext_diag.jsonl",
        "init() 传入的 _log_dir = log_dir()（<包根>/logs）；未初始化时按行 52 回落"),
    "fixtext_error_center/diaglog.py:103": (
        "logs",
        "<包根>/logs/fixtext_diag.jsonl.1",
        "日志轮转：与日志同目录，不产生额外落点"),
    "fixtext_error_center/diaglog.py:104": (
        "logs",
        "<包根>/logs/fixtext_diag.jsonl.1",
        "日志轮转：同目录内 os.replace"),
    "fixtext_ui/fixtext_settings.py:37": (
        "workspace",
        "<包根>/workspace/settings.ini（或 FIXTEXT_SETTINGS_FILE 覆盖值）",
        "M4-T4.4 修复：原先 QSettings('FixText','V1') 走 OS 配置目录（越界）；现显式 IniFormat 落用户区"),
    "fixtext_ui/fixtext_settings.py:46": (
        "n/a",
        "构造函数（不写盘）",
        "只是 QSettings 子类构造；实际写盘发生在 main_window 的 setValue + sync"),
    "fixtext_ui/main_window.py:562": (
        "n/a",
        "只读（value('wizardSeen')）",
        "读设置，不写盘；接收方是 AppSettings（→ 用户区 settings.ini）"),
    "fixtext_ui/main_window.py:571": (
        "workspace",
        "<包根>/workspace/settings.ini（wizardSeen=1）",
        "写入点经 fixtext_settings.AppSettings（main_window 第 53 行 import 别名）"),
    # ---- 词库 / 还原点 / 历史（用户区） ----
    "fixtext_ui/fixtext_vocab.py:126": (
        "workspace",
        "<包根>/workspace/vocab/*.json（自定义词库 / 派生规则）",
        "原子写：path 全部来自 CUSTOM_DIR（<包根>/workspace/vocab，M4-T4.4 已统一）"),
    "fixtext_ui/fixtext_vocab.py:134": (
        "workspace",
        "<包根>/workspace/vocab/*.json",
        "同一原子写的 os.replace 步骤"),
    "fixtext_ui/fixtext_vocab.py:143": (
        "workspace",
        "<包根>/workspace/vocab/.vocab-*.tmp",
        "失败清理过渡文件，同目录"),
    "fixtext_ui/fixtext_vocab.py:295": (
        "workspace",
        "<包根>/workspace/vocab/（work_dir）",
        "work_dir 默认 = base_dir（用户区）；测试可显式指到临时子树"),
    "fixtext_ui/fixtext_vocab.py:308": (
        "workspace",
        "<包根>/workspace/vocab/",
        "同上"),
    "fixtext_ui/fixtext_snapshot.py:68": (
        "workspace",
        "<包根>/workspace/vocab/snapshots/",
        "还原点索引目录，来自 VocabStore 的 snap_dir（用户区）"),
    "fixtext_ui/fixtext_snapshot.py:76": (
        "workspace",
        "<包根>/workspace/vocab/snapshots/index.json",
        "原子写 os.replace（同目录）"),
    "fixtext_ui/fixtext_snapshot.py:115": (
        "workspace",
        "<包根>/workspace/vocab/snapshots/",
        "还原点目录创建"),
    "fixtext_ui/fixtext_snapshot.py:249": (
        "workspace",
        "<包根>/workspace/vocab/snapshots/<id>",
        "删单个还原点（用户点删除且二次确认后）；入口见 vocab_module"),
    "fixtext_ui/fixtext_snapshot.py:411": (
        "workspace",
        "<包根>/workspace/vocab/snapshots/<id>",
        "裁剪旧还原点时删各自的索引条目，同一用户区目录"),
    "fixtext_ui/fixtext_snapshot.py:423": (
        "workspace",
        "<包根>/workspace/vocab/snapshots/<blob>",
        "裁剪旧还原点时删各自的数据块，同一用户区目录"),
    "fixtext_ui/fixtext_run_snapshot.py:128": (
        "workspace",
        "<包根>/workspace/snapshots/",
        "运行还原点根目录：root 由调用方给用户区路径"),
    "fixtext_ui/fixtext_run_snapshot.py:130": (
        "workspace",
        "<包根>/workspace/snapshots/<id>.json",
        "还原点摘要的原子写（同目录）"),
    "fixtext_ui/fixtext_run_snapshot.py:344": (
        "workspace",
        "<包根>/workspace/snapshots/",
        "确保还原点根存在"),
    "fixtext_ui/fixtext_run_snapshot.py:348": (
        "workspace",
        "<包根>/workspace/snapshots/<id>.json",
        "删除单个还原点（用户操作 + 二次确认）"),
    "fixtext_ui/fixtext_run_snapshot.py:426": (
        "workspace",
        "<包根>/workspace/snapshots/<id>/<name>",
        "把运行目录的一份拷进还原点（dest 在用户区）"),
    "fixtext_ui/fixtext_run_snapshot.py:461": (
        "workspace",
        "<包根>/workspace/snapshots/<id>/",
        "单条还原点目录"),
    "fixtext_ui/fixtext_run_snapshot.py:489": (
        "workspace",
        "<包根>/workspace/snapshots/<id>",
        "删还原点目录（二次确认后）"),
    "fixtext_ui/fixtext_run_snapshot.py:780": (
        "workspace",
        "<包根>/workspace/snapshots/<id>/work",
        "还原点自带工作树，父目录在用户区；删除后按目的重建"),
    "fixtext_ui/fixtext_run_snapshot.py:781": (
        "workspace",
        "<包根>/workspace/snapshots/<id>/work",
        "同上：从还原点内容重建"),
    "fixtext_ui/fixtext_history.py:122": (
        "workspace",
        "<包根>/workspace/history/",
        "历史摘要目录：dest.parent 来自用户区 history/"),
    "fixtext_ui/fixtext_history.py:123": (
        "workspace",
        "<包根>/workspace/history/<run>.json",
        "历史摘要写入（不是运行目录本身）"),
    "fixtext_ui/fixtext_history.py:137": (
        "runs",
        "<包根>/runs/<run>",
        "历史页把运行目录归位到 runs/；dest 由 runs_root 派生"),
    "fixtext_ui/fixtext_history.py:140": (
        "runs",
        "<包根>/runs/<run>",
        "同上：从旧位置搬回 runs/"),
    "fixtext_ui/fixtext_history.py:144": (
        "runs",
        "<包根>/runs/<run>（搬空后的旧目录）",
        "删除对象是已搬空的旧目录，仍在 runs 根下"),
    "fixtext_ui/fixtext_history.py:154": (
        "workspace",
        "<包根>/workspace/history/",
        "摘要文件落点目录"),
    "fixtext_ui/fixtext_history.py:155": (
        "workspace",
        "<包根>/workspace/history/<run>.json",
        "摘要文件搬入用户区"),
    "fixtext_ui/fixtext_history.py:166": (
        "runs",
        "<包根>/runs/<run>",
        "清理历史时逐个删 run_dir（全部在 runs/ 下）；入口有二次确认（见 t44_destructive_ops）"),
    # ---- 导入 / 工作区 ----
    "fixtext_import/importer.py:160": (
        "workspace",
        "<包根>/workspace/<book_id>/original/",
        "导入时把原书副本放用户区；workspace_root 由 ImportModule 传入（<包根>/workspace）"),
    "fixtext_import/importer.py:186": (
        "workspace",
        "<包根>/workspace/<book_id>/book.txt",
        "归一化正文写进书籍目录（用户区）"),
    "fixtext_import/importer.py:261": (
        "workspace",
        "<包根>/workspace/<book_id>/import.json",
        "导入记录写进书籍目录（用户区）"),
    "fixtext_import/textfile.py:76": (
        "workspace",
        "调用方给的 path 的父目录（导入 / 用户区路径）",
        "通用原子写工具：自己不含硬编码落点，落点由调用方 path 决定；"
        "产品内调用点只有 importer（用户区）与导出统计（导出目录）"),
    "fixtext_import/textfile.py:78": (
        "workspace|export_dir",
        "调用方 path 同目录的 .tmp",
        "同上（原子写的过渡文件）"),
    "fixtext_import/textfile.py:79": (
        "workspace|export_dir",
        "调用方 path",
        "os.replace 落正式文件"),
    "fixtext_import/textfile.py:89": (
        "workspace",
        "调用方 dst（导入副本目标，用户区）",
        "copy_verbatim：逐字节复制原书到工作区，读源写目标；源文件只读"),
    "fixtext_import/epub_import.py:231": (
        "workspace",
        "<包根>/workspace/<book_id>/",
        "EPUB 转 TXT 时写进书籍目录（用户区）"),
    "fixtext_import/epub_import.py:232": (
        "workspace",
        "<包根>/workspace/<book_id>/book.txt",
        "同上"),
    "fixtext_ui/import_module.py:94": (
        "declared_scratch",
        "系统临时目录里的预览副本（mkdtemp）",
        "EPUB 章节预览临时副本，行 135 统一 rmtree 清理"),
    "fixtext_ui/import_module.py:135": (
        "declared_scratch",
        "系统临时目录里的预览副本",
        "清理上一行建出的临时副本"),
    "fixtext_ui/import_module.py:565": (
        "workspace",
        "<包根>/workspace/（ImportModule 的 workspace_root）",
        "主窗口 mount_import 传 <包根>/workspace；default_workspace() 在 M4-T4.4 也统一到包根 workspace"),
    "fixtext_ui/import_module.py:970": (
        "declared_scratch",
        "预览用临时副本文件",
        "删处同 94/135（_preview_copy）"),
    # ---- 一键校正 / 运行目录 ----
    "fixtext_ui/oneclick_module.py:581": (
        "runs",
        "<包根>/runs/（runs_root）",
        "主窗口把 runs_root 传成 <包根>/runs（见 build_run_context）"),
    "fixtext_ui/oneclick_module.py:875": (
        "runs",
        "<包根>/runs/run-*（取消 / 失败后清脏目录）",
        "wd 来自 summary['workdir']，全部在 runs_root 下；不碰原书"),
    "fixtext_ui/fixtext_worker.py:80": (
        "declared_scratch",
        "系统临时目录 fixtext-hits-*",
        "命中数统计的临时工作区，with 语句结束自动删"),
    "fixtext_ui/fixtext_worker.py:311": (
        "runs",
        "<包根>/runs/<run>/",
        "worker 建工作目录（workdir 由 oneclick 传入 runs/run-*）"),
    "fixtext_ui/fixtext_worker.py:312": (
        "runs",
        "<包根>/runs/<run>/logs/",
        "同上"),
    "fixtext_ui/fixtext_worker.py:313": (
        "runs",
        "<包根>/runs/<run>/report/",
        "同上"),
    "fixtext_ui/fixtext_worker.py:315": (
        "runs",
        "<包根>/runs/<run>/<stage>/",
        "同上"),
    "fixtext_ui/fixtext_worker.py:359": (
        "runs",
        "<包根>/runs/<run>/",
        "取消后删本次工作目录（不碰原书）"),
    "fixtext_ui/fixtext_worker.py:366": (
        "runs",
        "<包根>/runs/<run>/",
        "失败后删本次工作目录"),
    "fixtext_ui/fixtext_check.py:311": (
        "runs",
        "<包根>/runs/<run>/",
        "复核标记目录：run_dir 由检查页从运行摘要取"),
    "fixtext_ui/fixtext_check.py:312": (
        "runs",
        "<包根>/runs/<run>/marks.json",
        "同上"),
    "fixtext_ui/plain_book.py:76": (
        "runs",
        "<包根>/runs/<run>/",
        "out_epub 由 oneclick 传 workdir（runs/run-*）；不写用户文件夹"),
    "fixtext_ui/plain_book.py:77": (
        "runs",
        "<包根>/runs/<run>/*.epub",
        "同上"),
    # ---- 导出（用户显式目录） ----
    "fixtext_ui/fixtext_export.py:500": (
        "export_dir",
        "用户选定的导出目录 / 默认包根「导出/」（历史导出在「导出/历史记录/」）",
        "重打包 EPUB 的原子落盘（tmp → 目标）；目录来自 out_dir"),
    "fixtext_ui/fixtext_export.py:569": (
        "export_dir",
        "用户选定的导出目录",
        "导出前确保目录存在"),
    "fixtext_ui/fixtext_export.py:583": (
        "declared_scratch",
        "系统临时目录 fixtext-stats-*",
        "命中统计的临时工作目录，with 结束自动删"),
    "fixtext_ui/fixtext_export.py:643": (
        "export_dir",
        "<导出目录>/<书名>替换统计.txt",
        "统计文本随导出落到用户选定的目录"),
    "fixtext_ui/fixtext_export.py:645": (
        "export_dir",
        "<导出目录>/<书名>替换统计.csv",
        "统计 CSV 同上"),
    "fixtext_ui/fixtext_export.py:682": (
        "export_dir",
        "用户选定的导出目录",
        "写前可写性检查"),
    "fixtext_ui/fixtext_export.py:691": (
        "export_dir",
        "<导出目录>/.fixtext-write-probe",
        "可写性探针文件（写完立即删，行 696）"),
    "fixtext_ui/fixtext_export.py:696": (
        "export_dir",
        "<导出目录>/.fixtext-write-probe",
        "探针用完即删"),
    "fixtext_ui/fixtext_export.py:737": (
        "export_dir",
        "<导出目录>/<书名>.txt",
        "纯文本导出主文件"),
    # ---- 编排器 / epubtext / bookmap / quotation（全部经 runs 路径） ----
    "main_app.py:40": (
        "workspace|runs|logs",
        "<包根>/{workspace,runs,logs}",
        "启动时确保三个受控目录存在（显式白名单，不含其它目录）"),
    "pipeline/fixtext_pipeline/config.py:249": (
        "runs",
        "<包根>/runs/<run>/…",
        "配置快照写进运行目录（path 由 cfg 给）"),
    "pipeline/fixtext_pipeline/config.py:250": (
        "runs",
        "<包根>/runs/<run>/…",
        "同上"),
    "pipeline/fixtext_pipeline/logsetup.py:48": (
        "runs",
        "<包根>/runs/<run>/logs/",
        "阶段日志：WorkPaths.logs = workdir/logs"),
    "pipeline/fixtext_pipeline/logsetup.py:49": (
        "runs",
        "<包根>/runs/<run>/logs/run.log",
        "同上"),
    "pipeline/fixtext_pipeline/report.py:107": (
        "runs",
        "<包根>/runs/<run>/report/",
        "运行报告目录"),
    "pipeline/fixtext_pipeline/report.py:110": (
        "runs",
        "<包根>/runs/<run>/report/run_report.json",
        "同上"),
    "pipeline/fixtext_pipeline/report.py:111": (
        "runs",
        "<包根>/runs/<run>/report/run_report.md",
        "同上"),
    "pipeline/fixtext_pipeline/runner.py:28": (
        "runs",
        "<包根>/runs/<run>/",
        "编排器建工作目录（cfg.workdir 由界面传入 runs/run-*）"),
    "pipeline/fixtext_pipeline/runner.py:29": (
        "runs",
        "<包根>/runs/<run>/logs/",
        "同上"),
    "pipeline/fixtext_pipeline/runner.py:30": (
        "runs",
        "<包根>/runs/<run>/report/",
        "同上"),
    "pipeline/fixtext_pipeline/runner.py:32": (
        "runs",
        "<包根>/runs/<run>/<stage>/",
        "阶段子目录"),
    "pipeline/fixtext_pipeline/runner.py:69": (
        "runs",
        "<包根>/runs/<run>/logs/",
        "run_log 在 WorkPaths.logs 下"),
    "pipeline/fixtext_pipeline/stages/base.py:53": (
        "runs",
        "<包根>/runs/<run>/<stage>/",
        "Stage 基类建阶段目录，路径来自 cfg.stage_dir"),
    "pipeline/fixtext_pipeline/stages/layout.py:135": (
        "runs",
        "<包根>/runs/<run>/02_layout/",
        "排版产物写在阶段目录"),
    "pipeline/fixtext_pipeline/stages/layout.py:138": (
        "runs",
        "<包根>/runs/<run>/02_layout/ledger",
        "同上"),
    "pipeline/fixtext_pipeline/stages/quote.py:42": (
        "runs",
        "<包根>/runs/<run>/04_quote/<stem>.report.txt",
        "引号检查报告（cfg.quote_report_txt）"),
    "pipeline/fixtext_pipeline/stages/quote.py:43": (
        "runs",
        "<包根>/runs/<run>/04_quote/<stem>.report.json",
        "同上"),
    "pipeline/fixtext_pipeline/stages/replace.py:176": (
        "runs",
        "<包根>/runs/<run>/03_replace/…before.txt",
        "给 bookmap 的 before 侧副本，仍在阶段目录"),
    "pipeline/fixtext_pipeline/state.py:124": (
        "runs",
        "<包根>/runs/<run>/state.json",
        "断点状态文件"),
    "pipeline/fixtext_pipeline/state.py:126": (
        "runs",
        "<包根>/runs/<run>/.state-*.tmp → state.json",
        "原子写过渡文件（同目录）"),
    "pipeline/fixtext_pipeline/vocab_bridge.py:81": (
        "workspace",
        "<包根>/workspace/vocab/derived_rules/",
        "派生规则目录：_ui_workspace() = <包根>/workspace（M4-T4.4 已统一到一处）"),
    "pipeline/fixtext_pipeline/vocab_bridge.py:82": (
        "workspace",
        "<包根>/workspace/vocab/derived_rules/.dfr-*.tmp",
        "原子写过渡文件（同目录）"),
    "pipeline/fixtext_pipeline/vocab_bridge.py:88": (
        "workspace",
        "<包根>/workspace/vocab/derived_rules/derived_meta.json",
        "os.replace 落正式文件"),
    "pipeline/fixtext_pipeline/vocab_bridge.py:91": (
        "workspace",
        "<包根>/workspace/vocab/derived_rules/.dfr-*.tmp",
        "失败清理过渡文件"),
    "pipeline/fixtext_pipeline/vocab_bridge.py:236": (
        "workspace",
        "<包根>/workspace/vocab/derived_rules/",
        "out.mkdir：派生规则输出目录"),
    "pipeline/vendor/fixtext/engine/client.py:112": (
        "declared_scratch",
        "系统临时目录 fixtext-engine-*",
        "引擎输入/输出的中转站；行 177 finally 里 rmtree。这是「绝不原地改用户文件」的实现基础"),
    "pipeline/vendor/fixtext/engine/client.py:177": (
        "declared_scratch",
        "系统临时目录 fixtext-engine-*",
        "用完即删"),
    "pipeline/vendor/fixtext/engine/client.py:253": (
        "declared_scratch|export_dir|runs",
        "由调用方给：临时目录（FILE 中转）/ runs 阶段目录 / 导出目录",
        "client 自身不硬编码落点；IN_PLACE 分支已在 M4-T4.4 默认禁用（需 FIXTEXT_ALLOW_IN_PLACE=1）"),
    "pipeline/vendor/fixtext/engine/client.py:254": (
        "declared_scratch|export_dir|runs",
        "同上",
        "同上"),
    "pipeline/vendor/fixtext/engine/client.py:277": (
        "declared_scratch|export_dir|runs",
        "同上（原子写 .tmp → os.replace）",
        "同上"),
    "pipeline/vendor/fixtext/engine/client.py:306": (
        "declared_scratch|export_dir|runs",
        "同上",
        "同上"),
    "pipeline/vendor/epubtext/archive.py:177": (
        "declared_scratch|export_dir|runs",
        "destination：调用方给（runs/ 或导出目录）",
        "epubtext 只负责打包，目标路径全部由上层传入，本身无硬编码落点"),
    "pipeline/vendor/epubtext/archive.py:183": (
        "declared_scratch|export_dir|runs",
        "同上",
        "同上"),
    "pipeline/vendor/epubtext/bundle.py:200": (
        "runs",
        "<run>/…/bundle 文件（path 由 stage 给）",
        "bundle 落点由阶段目录决定"),
    "pipeline/vendor/epubtext/bundle.py:201": (
        "runs",
        "<run>/…/bundle 文件",
        "同上"),
    "pipeline/vendor/epubtext/cli.py:67": (
        "n/a",
        "命令行工具的 --out 目录（开发者手动用）",
        "CLI 入口，产品运行期不调用"),
    "pipeline/vendor/epubtext/merge.py:141": (
        "runs",
        "<run>/01_merge/",
        "merge 阶段产物"),
    "pipeline/vendor/epubtext/merge.py:142": (
        "runs",
        "<run>/01_merge/…txt",
        "同上"),
    "pipeline/vendor/epubtext/merge.py:212": (
        "runs",
        "<run>/01_merge/",
        "同上"),
    "pipeline/vendor/epubtext/merge.py:213": (
        "runs",
        "<run>/01_merge/…txt",
        "同上"),
    "pipeline/vendor/epubtext/merge.py:239": (
        "runs",
        "<run>/01_merge/",
        "同上"),
    "pipeline/vendor/epubtext/restore.py:187": (
        "runs",
        "<run>/06_restore/",
        "还原阶段产物目录"),
    "pipeline/vendor/fixtext/engine/builder.py:162": (
        "n/a",
        "开发期构建工具：输出 go_src/bin/",
        "只在手工重编引擎时用，产品运行期不调用"),
    "pipeline/vendor/fixtext_bookmap/frequency.py:122": (
        "runs",
        "<run>/05_bookmap/",
        "dir_name 由 wordmap 传入 workdir 子目录"),
    "pipeline/vendor/fixtext_bookmap/frequency.py:123": (
        "runs",
        "<run>/05_bookmap/*.tmp",
        "同上"),
    "pipeline/vendor/fixtext_bookmap/frequency.py:165": (
        "runs",
        "<run>/05_bookmap/report/",
        "同上"),
    "pipeline/vendor/fixtext_bookmap/patcher.py:56": (
        "runs",
        "<run>/05_bookmap/patch_*",
        "删自己刚写的临时补丁（patch_dir 在阶段目录）"),
    "pipeline/vendor/fixtext_bookmap/patcher.py:64": (
        "runs",
        "<run>/05_bookmap/patch_*",
        "临时补丁文件"),
    "pipeline/vendor/fixtext_bookmap/wordmap.py:209": (
        "runs",
        "<run>/05_bookmap/",
        "patch_dir 由 stage 传入的运行目录"),
    "pipeline/vendor/fixtext_bookmap/wordmap.py:355": (
        "runs",
        "<run>/05_bookmap/…book_map",
        "同上"),
    "pipeline/vendor/fixtext_bookmap/wordmap.py:388": (
        "runs",
        "<run>/05_bookmap/…book_map",
        "同上"),
    "pipeline/vendor/fixtext_quotation/checker.py:123": (
        "n/a",
        "只读（open(...,'r')）",
        "正则误命中，人工判为只读"),
    "pipeline/vendor/fixtext_quotation/cli.py:30": (
        "n/a",
        "命令行工具的 --out 目录（开发者手动用）",
        "CLI 入口，产品运行期不调用"),
    "pipeline/vendor/fixtext_quotation/cli.py:46": (
        "n/a",
        "同上",
        "同上"),
    "pipeline/vendor/fixtext_quotation/cli.py:50": (
        "n/a",
        "同上",
        "同上"),
}


def iter_scope_files() -> list[Path]:
    out: list[Path] = []
    for s in SCOPES:
        p = PKG / s
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            out += [q for q in sorted(p.rglob("*.py")) if "__pycache__" not in q.parts]
    return out


def scan() -> list[dict]:
    rows: list[dict] = []
    for f in iter_scope_files():
        rel = str(f.relative_to(PKG))
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not (WRITE_PAT.search(stripped) or SETTINGS_PAT.search(stripped)):
                continue
            key = f"{rel}:{i}"
            row: dict = {"loc": key, "code": stripped[:160], "tag": None,
                         "landing": None, "basis": None, "source": None}
            if key in OVERRIDES:
                tag, landing, basis = OVERRIDES[key]
                row.update(tag=tag, landing=landing, basis=basis, source="manual")
            else:
                for tag, basis, pat in AUTO_RULES:
                    if re.search(pat, stripped):
                        row.update(tag=tag, landing="（自动归类，见依据）",
                                   basis=f"自动归类：{basis}", source="auto")
                        break
            if row["tag"] is None:
                row.update(tag="UNREVIEWED", landing="未知",
                           basis="自动归类失败且无人工复核记录")
            rows.append(row)
    return rows


def main() -> int:
    EVID.mkdir(parents=True, exist_ok=True)
    rows = scan()
    counts: dict[str, int] = {}
    for r in rows:
        for t in str(r["tag"]).split("|"):
            counts[t] = counts.get(t, 0) + 1
    unreviewed = [r for r in rows if r["tag"] == "UNREVIEWED"]
    allowed = {"workspace", "runs", "logs", "export_dir", "declared_scratch", "n/a"}
    bad = [r for r in rows if not set(str(r["tag"]).split("|")) <= allowed]
    payload = {
        "generated_by": "tools/audit_t44_write_paths.py",
        "scope": SCOPES,
        "total_sites": len(rows),
        "counts_by_tag": counts,
        "unreviewed": unreviewed,
        "illegal_tags": bad,
        "sites": rows,
        "passed": not unreviewed and not bad,
    }
    (EVID / "t44_write_paths.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写路径站点 {len(rows)} 处")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:18s} {v}")
    print(f"未复核 {len(unreviewed)} 处，非法标签 {len(bad)} 处")
    for r in unreviewed + bad:
        print(f"  !! {r['loc']}  {r['code'][:100]}")
    print("AUDIT:", "PASS" if payload["passed"] else "FAIL")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
