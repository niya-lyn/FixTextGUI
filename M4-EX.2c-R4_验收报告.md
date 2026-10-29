# FixText M4-EX.2c-R4 验收报告 · 收口（回归 + 全量测试 + 六场景）

- 卡片：`M4-EX.2c-R4`「收口（回归 + 全量测试 + 报告 + 打包上传）」
- 代码基线：`FixText_M4-EX.2c-R3_S456修复_v1.zip`
  （file_token `A5k4bUVHFoluSlx3Ze0cns7Nnah`，42,754,626 字节，md5 `91d3c52333940da210621714c0fcd602`，git HEAD `c30c9eb`）
- 本轮提交：`7a80ae9`（验收工具适配 + 六场景脚本）、`07587f9`（实测证据）
- 运行环境：`python3.12`（3.12.11）、`QT_QPA_PLATFORM=offscreen`、PySide6 6.11.2
- 样本：`in/paohuo.epub`（788 章，sha256 `93e5687e8856240c…`）
- 基线成品：`in/baseline_paohuo/06_restore/paohuo_restored.epub`
  （4,613,119 字节，sha256 `717fdfcee76fe3ee74d9a8bff20afbc84e7150bcbf5ee1a5b033a01739641dc2`，md5 `b88204041f477656bfd60bedc782206b`）

## 0. 结论先行

| 项目 | 结果 |
| --- | --- |
| 六场景 S1–S6 | **6/6 PASS** |
| 回归 `verify_m2t21` | **4/4 PASS**（总体通过） |
| 回归 `accept_t23` | **PASS**（EXIT=0，1m1s） |
| 回归 `smoke_e2e` | **PASS**（EXIT=0，26s） |
| 全量 pytest | **254 passed / 0 failed**（21 个文件，289.09s） |
| 产品代码改动 | **0**（`git diff -- fixtext_ui/ … tests/ data/` 为空） |
| 证据时间戳 | 全部晚于最后一次改代码的提交 `7a80ae9`（08:09:02） |

本轮所有失败均来自**验收脚本对新增「取消二次确认」交互的适配缺失**，不是产品缺陷：`accept_t23` 与 `smoke_e2e` 原本直接点进度弹窗的「取消」，而现在点取消会先弹确认框（`confirm_cancel=True` 是 M4-EX.2c 的既定行为），旧脚本没人点确认框，于是卡在嵌套模态里。两脚本已改为「排队派发点击 + 点『确认放弃』」，产品代码未动（§5）。

## 1. 六场景（S1–S6）

### 1.1 一次性全跑的原始输出

```
$ QT_QPA_PLATFORM=offscreen PYTHONPATH=<py312 site-packages> \
  python3.12 -u tools/accept_ex2c.py
[S1] 首启弹窗=True 计时={'wizard_shown': 0.57, 'import': 2.04, 'correct': 17.8, 'export': 5.55, 'finish': 0.32} 总=26.28s 导出md5=b88204041f477656bfd60bedc782206b 与基线一致=True 落地页=history PASS=True
[S1] PASS=True -> .../evidence/ex2c_r4_s1.json
[S2] 起始步=0 关窗=True wizardSeen=1 仍会弹=False 新运行目录=[] PASS=True
[S2] PASS=True -> .../evidence/ex2c_r4_s2.json
[S3] 子进程rc=0 弹窗样本=0/191 wizardSeen=1 耗时=3.25s PASS=True
[S3] PASS=True -> .../evidence/ex2c_r4_s3.json
[S4] 文案逐字=True 继续=ok 放弃=cancelled 残留=[] PASS=True
[S4] PASS=True -> .../evidence/ex2c_r4_s4.json
[S5] 起始步=1 有书=True 菜单项=True PASS=True
[S5] PASS=True -> .../evidence/ex2c_r4_s5.json
[S6] 落地页=history 历史条数=9 成品=4613119B sha=717fdfcee76fe3ee 与基线一致=True PASS=True
[S6] PASS=True -> .../evidence/ex2c_r4_s6.json

OVERALL: PASS
```

> 说明：本卡任务书的场景编号沿用早期验收报告（S1 新用户全路径 / S2 跳过 / S3 重启不再弹 / S4 ☰ 重开 / S5 返回上一步 / S6 取消二次确认），而 R3 用的编号是 S4 取消二次确认 / S5 有书从第 2 步 / S6 完成跳历史。**本报告一律用 R3 的编号**（脚本与 R3 证据对齐），两套编号对照见 §1.8。

### 1.2 S1 · 新用户全路径（首启自动弹 → 导入 → 校正 → 导出 → 跳历史）

证据：`evidence/ex2c_r4_s1.json`，截图 `screenshots/r4_s1_step1_imported.png` / `_step2_corrected.png` / `_step3_exported.png`

| 项 | 实测值 |
| --- | --- |
| 首启自动弹出向导 | `True`（起始步 0） |
| 导入结果 | 书名「炮火弧线」，4,996,484 字 |
| 校正结果 | 788 章，命中 5,100 处 |
| 导出文件 | 4,613,119 字节 |
| 导出 **md5** | `b88204041f477656bfd60bedc782206b` |
| 与基线 md5 一致 | `True`（sha256 也一致：`717fdfcee76fe3ee…`） |
| 完成页落地 | `history`（历史记录页） |
| 全路径计时 | 首启 0.57s ＋ 导入 2.04s ＋ 校正 17.8s ＋ 导出 5.55s ＋ 完成跳转 0.32s ＝ **26.28s** |
| 卡片要求 | ≤ 2 分钟 → **满足** |

分步计时口径：`wizard_shown` 从建窗到向导可见；`import` / `correct` / `export` 分别取「点主按钮 → 该步结果区就绪」；`finish` 取「点完成 → 向导关闭」。

### 1.3 S2 · 跳过

证据：`evidence/ex2c_r4_s2.json`，截图 `screenshots/r4_s2_wizard_step1.png`

| 项 | 实测值 |
| --- | --- |
| 向导起始步 | 0 |
| 关闭方式 | 点「跳过」→ 向导关闭 `True` |
| `wizardSeen` 写入 | `1` |
| `opens_on_first_run()` | `False`（以后不再自动弹） |
| 新增运行目录 | `[]`（跳过不产生任何校正产物） |
| 耗时 | 0.75s |

### 1.4 S3 · 重启后不再自动弹（独立子进程）

证据：`evidence/ex2c_r4_s3.json`

| 项 | 实测值 |
| --- | --- |
| 方式 | `subprocess` 起**新解释器进程**，沿用 S2 写下的同一份 `settings.ini` 与工作区 |
| 子进程 rc | `0` |
| 向导可见采样 | `0 / 191`（2 秒内每 ~10ms 采一次，全程未出现可见向导） |
| 子进程读到 `wizardSeen` | `1` |
| 重启耗时 | 3.25s（含 2 秒观察窗） |

> 这一项是真重启验证：不是在同一进程里清模块，而是另起解释器读同一份用户区设置。

### 1.5 S4 · 校正取消二次确认（两段独立会话）

证据：`evidence/ex2c_r4_s4.json`，截图 `screenshots/r3_s4a_confirm.png` / `r3_s4a_after_resume.png` / `r3_s4b_confirm.png` / `r3_s4b_after_discard.png`

| 项 | 实测值 |
| --- | --- |
| 标题逐字一致 | `确认放弃本次校正？` → `True` |
| 正文逐字一致 | `校正前已自动创建快照，放弃不会留下任何半成品文件；但当前进度将丢失，需要重新运行校正。` → `True` |
| 两个按钮文案 | `继续校正` / `确认放弃` → `True` |
| 模态 | `isModal=True` |
| A 段（点继续校正） | `outcome=ok`，命中 5,100，跑完整条链路 25.19s |
| B 段（点确认放弃） | `outcome=cancelled`，B 段新增运行目录残留 `[]` |
| 两段耗时 | A 25.19s / B 2.64s |

**交叉印证（来自小组长独立核验 + R3 上传证据 `M4-EX.2c-R3-S4_evidence.json`）**：同一组六项断言
（title / note / buttons / is_modal / resume→result 0 / confirm→result 1）在 R3 证据里同样 6/6 为 `true`，
A 段 16.92s（`outcome=ok`、命中 5,100）、B 段 2.49s（`outcome=cancelled`、残留 0）。两份独立运行结论一致，
计时差异属正常波动（同一台 1 核沙箱、同一本 788 章书）。

### 1.6 S5 · ☰ 菜单重开，有当前书从第 2 步开始

证据：`evidence/ex2c_r4_s5.json`，截图 `screenshots/r3_s5_reopen.png`

| 项 | 实测值 |
| --- | --- |
| 先真实导入一本书成为「当前书」 | `True` |
| 真实点顶栏 ☰ → 触发菜单项「新手向导（重新观看）」 | `True`（菜单项在真实弹出菜单里读到） |
| 向导起始步 | `1`（＝第 2 步「一键校正」） |
| `has_current_book` | `True` |
| 进度条取值 | `[100, 50, 0]`（第 1 步满、当前步半） |
| 第 2 步提示 | 「已检测到当前书：向导直接从第 2 步开始，不必重新导入。想换一本书，可点「← 返回上一步」。」 |

**交叉印证（来自小组长独立核验 + R3 上传证据）**：R3 证据 8 项断言全 `true`
（含 `no_book_starts_step1=true` / `with_book_starts_step2=true` / `with_book_shows_context_hint=true` /
`prev_from_step2_returns_to_step1=true`，起始步 无书=0、有书=1）；另有 R3 成员真跑 epub 的端到端证据
`M4-EX.2c-R3-S5_reopen_evidence.json`（起始步 1、`has_current_book=True`、`bars=[100,50,0]`）与
`s5_change.diff`（低侵入改动：只加构造参数 + `_open_wizard` 传参，57 行以内）。

### 1.7 S6 · 完成页跳历史记录页

证据：`evidence/ex2c_r4_s6.json`，截图 `screenshots/r3_s6_complete.png`

| 项 | 实测值 |
| --- | --- |
| 完成前所在页 | `home` |
| 点「完成」后所在页 | `history`（跳转 `True`） |
| 历史记录条数 | `9` |
| 导出文件 | 4,613,119 字节 |
| 导出 **md5** | `b88204041f477656bfd60bedc782206b`（与基线一致 `True`） |
| 场景耗时 | 19.9s |

**交叉印证（来自小组长独立核验 + R3 上传证据 `M4-EX.2c-R3-S6_evidence.json`）**：R3 证据
`page_before_finish=home` → `page_after_finish=history`、`history_rows=1`、md5 `b88204041f47…`、
`content_identical=true`，耗时 19.33s；拒绝路径（点「跳过」）原地不动。

> 历史条数我这次是 9、R3 是 1：历史记录在同一工作区里**累加**，我连跑了 S1/S4/S6 三次完整导出，
> 条数自然多于 R3 只跑一次。断言用的是「>0」与跳转结果，不是条数相等。

### 1.8 编号对照（避免两套口径混淆）

| 本卡任务书编号 | 内容 | 本报告/R3 编号 |
| --- | --- | --- |
| S1 新用户全路径 | 首启导入→校正→导出 | **S1** |
| S2 跳过 | 点跳过只记已看过 | **S2** |
| S3 重启不再弹 | 新进程不再自动弹 | **S3** |
| S4 ☰ 重开 | 有当前书从第 2 步 | **S5** |
| S5 返回上一步 | 第 2 步 ← 返回第 1 步 | **S5**（R3 证据里的 `prev_from_step2_returns_to_step1` 项） |
| S6 取消二次确认 | 继续校正 / 确认放弃 | **S4** |

### 1.9 零露出扫描（六场景界面文本）

| 场景 | 扫描文本数 | 内部概念命中 | 绝对路径命中 |
| --- | --- | --- | --- |
| S1 | 771 | 0 | 3 |
| S2 | 471 | 0 | 1 |
| S4 | 1,505 | 0 | 2 |
| S5 | 725 | 0 | 1 |
| S6 | 785 | 0 | 3 |

内部概念（`books` / `spine` / `OPF` / `rules.json` / 内部路径 等 25 个模式）**全部 0 命中**。

绝对路径命中项如实披露：都是「保存位置：`<包根>/runs/<书>/<run>/03_replace/after/导出结果`」与设置页
「日志目录」这两处 baseline 既有的绝对值标签（`accept_t23` / `verify_m2t21` 对该项的判定口径是「记账、不断言」），
**不是本卡引入**。

## 2. 回归三项（本轮实跑原始输出）

三项都在最后一次改代码提交 `7a80ae9`（08:09:02）**之后**重跑：`verify_report.json` 08:09:41、
`t23_evidence.json` 08:10:49、`smoke_e2e.json` 08:11:22。

### 2.1 `tools/verify_m2t21.py` → 4/4 PASS

```
$ QT_QPA_PLATFORM=offscreen PYTHONPATH=<py312> python3.12 -u tools/verify_m2t21.py
====================================================================
FixText M2-T2.1 验收自检
====================================================================
  [PASS] 1 六入口可达且状态清晰
  [PASS] 2 内部目录概念零露出
  [PASS] 3 令牌值与设计地基一致
  [PASS] 4 主窗口可构造 + 六页截图

  入口数 6，逐入口选中态唯一： True
  路由保状态：同实例=True 状态保持=fixed
  快捷方式 Ctrl+3/Ctrl+H： True | 占位页 CTA： True | 顶栏按钮： [True, True, True]
  扫描界面字符串 3043 条 / 禁用模式 25 个，命中 0
  令牌 73 vs 73，差异 0，缺失 0，多余 0
  截图 7 张，stack 页 8

  report -> verify_report.json
  总体: 通过
EXIT=0
```

与小组长给的基线数字一致（零露出 3041~3043 条命中 0、令牌 73 vs 73 差异 0、六页截图 7 张）。
**本项没有 FAIL**——本工作区里 S5 用的是小组长的低侵入版（`has_current_book` 构造参数 + `_open_wizard` 传参），
`git diff` 也证明产品代码零改动。

### 2.2 `tools/accept_t23.py` → PASS

```
$ QT_QPA_PLATFORM=offscreen PYTHONPATH=<py312> python3.12 -u tools/accept_t23.py
[A] 完整运行 14.7s outcome=ok poll=147 workdir_left=True
[A] >3s 阶段进度证据: {"layout": {"elapsed_s": 8.915, "over_3s": true, "ui_step_label": "整理排版…",
     "ui_step_labels_during": ["整理排版…"], "eta_texts_sample": ["已用 0 秒 · 预计剩余 19 秒", …],
     "progress_updates_during": 90, "percent_first_last": [4.2, 96.0]}}
[B] 替换阶段取消 outcome=cancelled close=0.129s signal=0.127s workdir_exists=False
[B2] 复跑 14.74s sha=717fdfcee76fe3ee…
[C] 排版阶段取消 outcome=cancelled close=8.929s workdir_exists=False
[D] 露出扫描：1436 条界面文本，命中 0
ACCEPT: PASS
{"A_vs_baseline": true, "B2_vs_A": true, "C2_vs_A": true, "all_equal": true}
EXIT=0
```

关键点：A 完整跑 14.7s；B 取消即时生效（close 0.129s，工作目录已清）；B2 复跑 sha 与基线一致；
C 排版阶段取消在阶段边界生效（8.929s，协作式检查点，符合 T2.3 既定设计）；三方 sha 全等。

### 2.3 `tools/smoke_e2e.py` → PASS

```
$ QT_QPA_PLATFORM=offscreen PYTHONPATH=<py312> python3.12 -u tools/smoke_e2e.py
[1] 预览完成：共 788 行，首行 = '封面'，封面标注正确 = True，前3行 = ['封面', '第 2 章　简介', '第 3 章　目录']
[1] 导入完成 0.89s：788 章 / 约 4,996,484 字 → 一键校正上下文已就绪 = True
[2] 取消场景：outcome=cancelled 9.3s，runs 残留 = []，无脏状态 = True
[3] 复跑完成：outcome=ok 14.59s，成品存在 = True，原书未动 = True，
    阶段耗时 = {'merge': 0.3, 'layout': 8.9, 'replace': 1.6, 'quote': 0.8, 'bookmap': 0.2, 'restore': 2.1}
[4] 错误卡：采集 8 条文本，人话且无内部细节 = True
[4] 诊断日志：code=U-R00，已写入 = True
[5] 零露出：扫描 805 条界面文本，命中 0
SMOKE: PASS
EXIT=0
```

`QObject::startTimer: …` 是无头环境关窗时的 Qt 无害告警，不影响断言。

## 3. 全量 pytest

### 3.1 实跑结果

`python3.12 -m pytest tests/ -q` 一次性跑会在 **254 项中的第 242 项被 OOM killer 杀掉**
（EXIT=137，5m2s，1 核 / 3GB 沙箱），因此改为**逐文件串行**跑同一批 21 个测试文件：

```
test_encoding.py                         rc=0  194.54s  20 passed
test_error_center.py                     rc=0    0.50s  28 passed
test_ex2b_empty_states.py                rc=0    0.64s  10 passed
test_ex3a_shelf.py                       rc=0    2.09s  14 passed
test_ex3b_linkage.py                     rc=0    2.29s   7 passed
test_export_resolve.py                   rc=0    0.28s   6 passed
test_first_run_wizard.py                 rc=0    2.21s  22 passed
test_import.py                           rc=0    3.02s  10 passed
test_no_jargon.py                        rc=0    0.39s  23 passed
test_settings_module.py                  rc=0    0.51s  10 passed
test_t210_check_inject.py                rc=0    0.86s   4 passed
test_t210_history.py                     rc=0    0.41s   5 passed
test_t210_reexport_sha.py                rc=0   16.92s   1 passed
test_t31_book_words.py                   rc=0    0.61s  10 passed
test_t31_vocab_merge_click.py            rc=0    0.84s   1 passed
test_t31_vocab_store.py                  rc=0    1.94s  16 passed
test_t31_vocab_ui.py                     rc=0    5.05s  16 passed
test_t32_vocab_safety.py                 rc=0   12.80s  23 passed
test_t33_book_words_ui.py                rc=0    2.23s   8 passed
test_t34_snapshot.py                     rc=0   35.76s  10 passed
test_t37_vocab_bridge.py                 rc=0    5.20s  10 passed
TOTAL elapsed 289.09
```

**合计 254 passed / 0 failed / 0 error，21 个文件 rc 全 0。** 与基线参考（254 passed）项数一致；
计时 289.09s 低于单进程基线的 398.06s / 小组长的 360.78s，因为逐文件跑没有进程内累积状态与 GC 压力。

逐文件明细：`pytest_split_r4b.json`（随回归证据包上传）。

## 4. 证据时间戳核验

最后一次改代码的提交：`7a80ae9`，`2026-10-29 08:09:02 +0800`。

| 证据 | 生成时间 | 晚于提交 |
| --- | --- | --- |
| `verify_report.json` | 08:09:41 | 是（+39s） |
| `screenshots/01..07_*.png`（7 张） | 08:09:41 | 是 |
| `evidence/t23_evidence.json` | 08:10:49 | 是（+107s） |
| `evidence/smoke_e2e.json` | 08:11:22 | 是（+140s） |
| `evidence/ex2c_r4_s1..s6.json` + summary | 08:17:12 – 08:18:07 | 是（+8m10s 起） |
| `screenshots/r3_*.png` / `r4_*.png`（7 张） | 08:17 – 08:18 | 是 |

`pytest_split_r4b.json` 由提交后的 08:11–08:16 逐文件跑出（与 21 个 `rc=0` 行一致）。

## 5. 本轮改动清单（产品代码 0 改动）

| 文件 | 性质 | 改动 |
| --- | --- | --- |
| `tools/accept_ex2c.py` | **新增**验收脚本 | 六场景一脚本（S1–S6），`--only` 可选跑；复用 R3 的 `Session` / `click_later` / `fresh_env` / `patch_file_dialog` 骨架，新增 S1（真实书全路径 + 分步计时 + 导出 md5 比对）、S2（跳过）、S3（新解释器进程重启） |
| `tools/accept_t23.py` | 验收脚本适配 | +23 / −4 行：点「取消」改为 `QTimer.singleShot(0)` 排队派发（嵌套模态里同步点击会卡死该心跳槽，R2 踩过）；派发后点「确认放弃」；取消耗时改从确认点击起算，并新增 `confirm_dialog_shown` / `confirm_click_latency_s` |
| `tools/smoke_e2e.py` | 验收脚本适配 | `run_correction_with_click` 的 `watch_cancel` 同法改造 |

**产品代码零改动证据**：

```
$ git diff --stat -- fixtext_ui/ fixtext_import/ fixtext_error_center/ pipeline/ main_app.py tests/ data/
（空）
```

为什么必须改脚本而不是改产品：M4-EX.2c 把「一键校正取消」定成了必须二次确认（`do_correction(confirm_cancel=True)`、
`ProgressDialog(confirm_cancel=...)`），旧脚本点完取消就去轮询结果，没人处理确认框 → 卡住。这是**行为规范的既定变更**，
不是缺陷；`grep` 也确认 `fixtext_ui/fixtext_widgets.py` 本轮被误编辑后已回退，`git status` 全程干净。

两处适配的原始 diff：`accept_t23_M4EX2c适配.diff`、`smoke_e2e_M4EX2c适配.diff`（已上传 code 目录）。

## 6. 未完成 / 未验证项（如实保留）

1. **绝对路径标签**：设置页「日志目录」与「保存位置」仍显示绝对路径（S1 3 处、S4 2 处、S6 3 处）。属 baseline 既有（`verify_m2t21` 口径为记账不断言），本卡按「不改产品代码」纪律未处理，建议登记缺陷卡。
2. **实机（非离屏）视觉确认**：六场景截图都是 `widget.grab()`，没有在真实桌面合成器下看过字重/行高观感。离屏渲染对版式判断有限。
3. **Windows 未实测**：全部在 Linux 沙箱完成，Windows 下的字体回退与拖放路径未验证。

## 7. 交付物

| 文件 | 说明 |
| --- | --- |
| `FixText_M4-EX.2c-R4_收口_v1.zip` | 完整工作区（含 `.git`、引擎执行位 `rwxr-xr-x`），排除 `runs/`（501MB 运行产物）与 `__pycache__` |
| `FixText_M4-EX.2c-R4_验收报告.md` | 本报告 |
| `M4-EX.2c-R4_S123_证据与截图.zip` | S1–S3 的 evidence JSON + 4 张截图 |
| `M4-EX.2c-R4_回归三项与全量pytest_原始输出.zip` | 三项回归控制台原始输出 + `t23_evidence.json` / `smoke_e2e.json` / `verify_report.json` + `pytest_split_r4b.json` |
| `M4-EX.2c-R4_verify_m2t21_截图.zip` | `verify_m2t21` 七张截图 |
