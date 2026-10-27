# FixText M2-T2.3 可视化进度与取消

> 交付包 · 2026-10-27 · 依赖：M2 Qt 骨架（prototypes/ + src/）+ M1-T1.1 编排器产品

## 一、实现内容（UI 层 + 编排器对接层，未改 M1 引擎）

### 1. `src/fixtext_worker.py`（新增，核心对接层）

- `HUMAN_STAGES`：六阶段 → 人话步骤映射（merge→「读取章节」、layout→「整理排版」、
  replace→「替换词语」、quote→「检查标点引号」、bookmap→「提取本书专有词」、
  restore→「生成校正后的 EPUB」）；内部阶段名不进界面。
- `CorrectionJob`：直接驱动 M1 的六个 Stage 类（非整链 run_pipeline），阶段间插取消检查点；
  通过 monkey-patch `fixtext.engine.client.subprocess` 注入 `_SubprocessProxy`，
  把 Go 引擎子进程句柄登记到 `_active_proc` —— 点「取消」立即 `kill()`，不等引擎跑完。
  每阶段完成检查取消标记，取消后 `_cleanup()` 整目录删除工作区（chmod 兜底），
  抛 `CorrectionCancelled`。
- `snapshot()`：percent / eta_s / elapsed_s / current_index / cancelling，供界面 200ms 轮询。
- ETA 外推：已完成阶段的实际耗时 vs 基准权重（REFERENCE_SEC，来自大语料实测）按比例缩放；
  末阶段完成前进度条封顶 96%，避免「假完成」。
- `CorrectionWorker(QObject)`：后台 `threading.Thread` 跑 job，`set_stage_callbacks` 把阶段回调
  转成 Qt 信号（stage_started / stage_finished / succeeded / failed / cancelled，跨线程自动排队）。
  失败消息经 `_human_error()` 归成人话（E 码 / 堆栈 / 路径不进界面）。
- 原始 EPUB 全程只读（引擎只碰工作区副本）→ 天然「校正前快照」，取消即干净。

### 2. `src/fixtext_widgets.py`（修改：ProgressDialog 升级双模式）

- 新增 `mode="live"`：`start_live(state_provider)` 启动 200ms 轮询定时器，
  驱动进度条值 + 「已用 X · 预计剩余 Y」文案；`live_stage_started/finished` 更新步骤文案与指示点；
  `live_begin_cancelling()`（「正在取消本次校正…」+ 禁用取消按钮）→ `live_close_cancelled()`。
- 旧 `timer` 模式保留（导入/导出页继续用，不回归）。

### 3. `src/oneclick_module.py`（修改：一键校正页接真链路）

- `set_run_context()` 注入 EPUB / 词库 / 引擎 / pipeline 路径 + 书名；书条显示
  「《书名》.epub · X MB」与「校正过程只读原文件，可随时恢复到校正前」。
- `do_correction()`：创建独立工作目录 `runs/run-<ms>` → CorrectionJob + CorrectionWorker →
  live 进度弹窗（取消按钮接 `worker.request_cancel`）→ `exec()` 阻塞等结果。
- 结果区全部换成真实数据（章节数 / 规则条数 / 引号待修 / 字符数 / 成品指纹）。
- 取消后 toast：「已取消，工作区已清理，未留下半成品（原书完好）」，界面回可重跑状态。

## 二、验收自检（大语料实测：炮火弧线 EPUB 4.6MB · 788 章 · 304,255 规则 × 2 趟）

| 验收条 | 结论 | 实测数字 |
| --- | --- | --- |
| ① >3s 操作有进度反馈 | PASS | 完整运行 19.54s。layout 9.24s 期间 92 次进度更新、步骤文案「整理排版…」、进度 4.7%→51.3%、ETA「已用 X 秒 · 预计剩余 Y 秒」持续滚动；replace 3.15s 期间 32 次更新、「替换词语…」、59.9%→78.2%；restore 2.83s 也有 33 次更新（未到 3s 线但有反馈） |
| ② 取消即时生效且无脏状态 | PASS | 替换阶段（Go 子进程运行中）取消：点击→子进程被杀 1.00s，弹窗关闭 1.00s；排版阶段（纯 Python 阶段）取消：1.00s 置位标记 + 杀进程句柄，弹窗在本阶段结束点关闭（9.58s，layout 不可中断属设计内）。取消后工作区整目录删除、runs 目录零残留、原书 sha256 不变。**sha256 对照：取消复跑 B2 与首次完整运行 A 完全一致（`717fdfcee76fe3ee74d9…9641dc2`），C2 亦一致，且与 M1 编排器直跑基线一致（all_equal=true）** |
| ③ 人话步骤、零内部露出 | PASS | 全部 6 步文案为人话（「整理排版…」「替换词语…」…）；露出扫描 1,561 条界面文本（模块控件树 + 弹窗全量文本 + 步骤/ETA 采样原文），内部阶段名 / 命令行词 / 内部路径命中 0 |

复跑耗时：B2 18.07s、C2 18.29s，与首次同量级；全程无命令行输出进界面。

## 三、遗留问题分级

- **P0**：无。
- **P1**：纯 Python 阶段（layout，本语料约 9.2s）内取消需等本阶段结束才生效（阶段间检查点 +
  子进程即时杀，进程内 Python 循环不可安全中断）。界面以「正在取消本次校正…」明示等待。
  若要求秒级，需 M1 阶段内部加协作式取消点（改引擎，超本卡范围）。
- **P2**：① ETA 初始估计依赖 REFERENCE_SEC 基准权重（按本语料标定），语料体量差异大时
  前几秒估计偏差较大，随阶段完成自动收敛；② 基准权重当前硬编码于 fixtext_worker.py，
  后续可落配置文件；③ 验收脚本阶段信号钩子改为「轮询采样 + job 自报 stage_elapsed」双通道
  取证（信号钩子时序在离屏环境不可靠，不影响产品代码）。

## 四、目录

- `src/`：完整源码（新增 fixtext_worker.py；fixtext_widgets.py / oneclick_module.py 修改；
  其余为骨架原文件，未动词库管理占位页）。
- `tests/accept_t23.py`：验收脚本（真实点击路径：QTest.mouseClick 主按钮 / 取消按钮；
  5 场景 A/B/B2/C/C2 + 露出扫描 + sha256 确定性判定）。
- `evidence/t23_evidence.json`：全量实测证据（各场景耗时 / 取消延迟 / sha / 轮询采样原文）。
- `evidence/证据摘要.md`：人类可读摘要。

## 五、复跑方式

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=<PySide6 site-packages> \
  python3.12 tests/accept_t23.py   # 需 in/ 下的语料、词库、T1.1 产品（见脚本头部路径）
```
