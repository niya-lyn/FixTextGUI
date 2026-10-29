# FixText M4-T4.1a 合并双线主干 · 验收报告

- **合并提交**：`b7e5297`（第一父 `07587f9`＝UI 线 M4-EX.2c-R4；第二父 `f70e8c9`＝引擎线 M4-T4.2）
- **证据提交**：`6d4bd85`（合并后专项核验证据与全量验收原始产物）
- **分叉点（merge-base）**：`3554341`（M4-T4.4，两线共同起点）
- **全量测试**：281 passed / 0 failed / 0 error / 0 skipped（22 个测试文件，277.18s）
- **冒烟**：`SMOKE: PASS`
- **结论**：两线干净合并成功，唯 1 处语义冲突已按「能力并集」解法消解并实测验证；合并后全量测试与冒烟全绿。

---

## 1. 起点核验（先验身份，再动手）

任务要求以 **R4 卡交付评论指定的 zip** 为 UI 线基线，而非云盘上最新 mtime 的包（目录里有两个 EX.2c 候选包）。两包下载后逐一比对交付评论里写明的 md5：

| 线条 | 文件 | 字节数 | md5（实算） | 与交付评论 | 线头提交 |
|---|---|---|---|---|---|
| UI 线 | `FixText_M4-EX.2c-R4_收口_v1.zip` | 44,119,863 | `bf0773a3a21e990063ac38691b30f98c` | 一致 | `07587f9` |
| 引擎线 | `FixText_M4-T4.2_替换引擎双轨_v1.zip` | 37,208,334 | `3b679500231a3887bcb2fd2dd9acfa48` | 一致 | `f70e8c9` |

两包各自解压到独立 `/tmp` 干净目录（`/tmp/t41a/ui/pkg`、`/tmp/t41a/eng/pkg`），未做任何跨包复制。

**R4 基线两项特征在合并主干上逐一复核：**

| 特征 | 落点 | 合并主干上的实际形态 | 核验方式与结果 |
|---|---|---|---|
| ① `wizardSeen` 持久化 | `fixtext_ui/main_window.py::_open_wizard` | `QSettings("FixText","V1").setValue("wizardSeen","1")`（经 `fixtext_settings.AppSettings` 落用户区 `settings.ini`） | **实测跨进程**：进程 1 写 → 进程 2 新解释器读到 `1`；`settings.ini` 落地 `[General] wizardSeen=1`。PASS（`evidence/t41a_wizard_seen.json`） |
| ② 已有当前书时向导从第 2 步开始 | `fixtext_ui/first_run_wizard.py` | `has_current_book` 形参 → `self.step = 1 if self.has_current_book else 0`；`main_window` 传 `has_current_book=bool(getattr(self,"_current_text_path",""))` | 源码就位 + `tests/test_first_run_wizard.py` 22 项在合并主干全过 |

> 说明：R4 包的历史里没有单独的 `wizardSeen` sync 提交，而是靠 `AppSettings`（IniFormat 固定路径）写值——我最初怀疑「`setValue` 后不 `sync` 会丢」，因此专门做了跨进程实测，**实测证伪该怀疑**（写入即落盘，无需显式 `sync`）。此结论以实测为准，不按记忆臆断。

---

## 2. 合并方式与结果

### 2.1 真 git merge，不是目录复制

把引擎线包作为 remote 加入 UI 线仓库后 fetch，使 `merge-base` 由真实历史算出（`3554341`），再 `git merge`：

- 两线各自独有提交数：UI 线 30 个、引擎线 3 个（合计 33 个提交被并入）
- 合并提交 `b7e5297` 是**真双亲**：`git log -1 --format="%h  parents=%p"` → `b7e5297  parents=07587f9 f70e8c9`
- 合并相对 UI 父改动 13 个文件、相对引擎父改动 105 个文件——两侧内容都在，不是「取一边覆盖另一边」

### 2.2 冲突清单：只 1 处，但藏着真语义风险

`git merge` 后唯一冲突是 **`fixtext_ui/oneclick_module.py`（UU）**。两线都改了 `do_correction` 的方法头：

- **UI 线（EX.2c）**：给 `do_correction` 加 `confirm_cancel` 形参 —— 点「取消」先二次确认（原型 `#corrConfirm`）
- **引擎线（T4.2）**：给 `do_correction` 加引擎预检 + 降级确认；并新增 `_start_correction`

**风险点（这是本卡唯一需要"想清楚"的地方）**：引擎线原版 `_start_correction` **没有** `confirm_cancel` 形参。若按「取引擎线版本」草率解冲突，编译/测试都可能照样过，但 EX.2c 的「取消二次确认」会在**降级重跑**那条路上**静默退化**为直接取消——用户点取消不问就停，而主路径仍正常，很难被发现。

**解法（能力并集，不做取舍）：**

1. import 区保留 UI 线 `EmptyState`，并入引擎线 `ConfirmDialog`（降级确认弹窗需要它）
2. `do_correction(self, *, confirm_cancel: bool = True)` —— 保留 UI 线形参，两段 docstring（EX.2c 取消二次确认 + T4.2 引擎预检）都在
3. **新增贯通**：`do_correction` → `_start_correction(..., confirm_cancel=confirm_cancel)`
4. `_start_correction(self, ctx, *, engine_override=None, confirm_cancel: bool = True)` 加形参，并传给 `ProgressDialog(confirm_cancel=bool(confirm_cancel))`
5. 降级重跑那条递归调用同样带 `confirm_cancel=confirm_cancel`

### 2.3 自动合并的 3 个文件：逐个核验双方改动均在（不靠假设）

| 文件 | 引擎线留下 | UI 线留下 |
|---|---|---|
| `fixtext_ui/main_window.py` | `build_run_context` 不再要求 Go 二进制存在（只挡词库缺失） | 按书隔离 `runs_root=PKG/runs/<书id>` |
| `fixtext_ui/fixtext_worker.py` | `CorrectionJob(engine=...)`、`self.engine_used`、py 引擎协作式取消钩子（UI 线未改此文件） | — |
| `fixtext_error_center/error_codes.py` | 新增 `E1006`（Python 引擎依赖缺失） | — |

---

## 3. 对接点 `engine`：契约键双读互通（实测）

两线约定对接点=设置页配置键 `engine`。实现分居两侧：UI 侧 `fixtext_settings.KEY_ENGINE`，pipeline 侧 `fixtext_pipeline.engine_choice.ENGINE_KEY`。实测同一 `settings.ini` 双向读写：

```
ui_wrote_python:
  ui_read        = python
  pipeline_read  = python
  ini            = [General] engine=python
pipeline_read_after = go      (pipeline 侧回写后)
ui_read_after      = go
constants: KEY_ENGINE(ui)=engine  ENGINE_KEY(pipeline)=engine  choices=[go,python]  default=go
verdict: PASS
```

原始输出见 `evidence/t41a/t41a_engine_key.stdout.log`，结构化结果 `evidence/t41a_engine_key.json`。

---

## 4. 我新增的 `confirm_cancel` 贯通：5 场景实测

这是本次合并中**唯一由我编写的产品逻辑**，因此单独做专项核验——走**真实的** `do_correction` / `_start_correction` / 降级尾部代码，只把三样换桩（`ProgressDialog` 记录后立即关窗避免 `exec()` 阻塞、`CorrectionWorker` 不发车不跑真管线、结果渲染），采集到的 `confirm_cancel` 值来自真实传参。

| 场景 | 路径 | 断言 | 结果 |
|---|---|---|---|
| V1 | 默认调用 `do_correction()` | 弹窗收到 `confirm_cancel=True` | PASS |
| V2 | `do_correction(confirm_cancel=False)`（验收脚本口径） | 收到 `False`（反向对照，证明不是恒真） | PASS |
| V3 | `engine_path` 指向不存在文件 → 预检失败 → 确认降级 → 改走 python | 弹窗仍收到 `True`；降级原因=`引擎文件不存在（可能被删除或杀毒软件隔离）` | PASS |
| V4 | 运行中引擎失败 → 真实尾部 `_outcome=="fallback"` 分支**递归重跑** | **2 次弹窗（首跑 + 重跑）都收到 `True`** | PASS |
| V5 | 源码静态断言（防回改） | 5 项断言（含 `first_run_wizard` 仍传 `confirm_cancel=True`） | PASS |

V5 五项断言明细：

```json
{
  "_start_correction_has_confirm_cancel": true,
  "do_correction_threads_it": true,
  "fallback_rerun_threads_it": true,
  "progress_dialog_receives_it": true,
  "wizard_still_passes_true": true
}
```

原始输出（`evidence/t41a/t41a_confirm_probe.stdout.log`）：

```
CONFIRM_CANCEL_PROBE: PASS
```

`evidence/t41a_confirm_cancel.json` 里 V4 的 `n_dialogs=2` 是关键——它证明降级重跑那条腿**真的被执行到**，而不是只测了首次弹窗。

---

## 5. 合并后全量回归（原始输出）

### 5.1 全量 pytest：281 passed / 0 failed / 0 skipped

跑法：`python3.12`（3.12.11）+ `pytest 8.3.5`，`QT_QPA_PLATFORM=offscreen`，`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，**逐文件串行**（1 核沙箱单进程全量会被 OOM 杀，`test_encoding.py` 单文件就要 184s）。

**在合并提交之上重跑**（不是复用合并前的旧证据）：

```text
# 全量 pytest（逐文件串行）
# 解释器: 3.12.11 via /usr/local/bin/python3.12
# pytest: pytest 8.3.5
# 文件数: 22  耗时: 277.18s
# 合计: 281 passed, 0 failed/error, 0 skipped
# rc!=0 的文件: 无
=== test_encoding.py rc=0 183.90s :: 20 passed in 183.74s (0:03:03)
=== test_error_center.py rc=0 0.48s :: 28 passed in 0.32s
=== test_ex2b_empty_states.py rc=0 0.65s :: 10 passed in 0.43s
=== test_ex3a_shelf.py rc=0 1.86s :: 14 passed in 1.56s
=== test_ex3b_linkage.py rc=0 2.18s :: 7 passed in 1.80s
=== test_export_resolve.py rc=0 0.28s :: 6 passed in 0.13s
=== test_first_run_wizard.py rc=0 2.16s :: 22 passed in 1.79s
=== test_import.py rc=0 2.97s :: 10 passed in 2.82s
=== test_no_jargon.py rc=0 0.38s :: 23 passed in 0.23s
=== test_settings_module.py rc=0 0.51s :: 10 passed in 0.35s
=== test_t210_check_inject.py rc=0 0.83s :: 4 passed in 0.62s
=== test_t210_history.py rc=0 0.39s :: 5 passed in 0.25s
=== test_t210_reexport_sha.py rc=0 16.85s :: 1 passed in 16.71s
=== test_t31_book_words.py rc=0 0.61s :: 10 passed in 0.43s
=== test_t31_vocab_merge_click.py rc=0 0.80s :: 1 passed in 0.63s
=== test_t31_vocab_store.py rc=0 1.96s :: 16 passed in 1.82s
=== test_t31_vocab_ui.py rc=0 4.81s :: 16 passed in 4.47s
=== test_t32_vocab_safety.py rc=0 12.74s :: 23 passed in 12.50s
=== test_t33_book_words_ui.py rc=0 2.11s :: 8 passed in 1.83s
=== test_t34_snapshot.py rc=0 35.45s :: 10 passed in 35.28s
=== test_t37_vocab_bridge.py rc=0 4.94s :: 10 passed in 4.74s
=== test_t42_engine.py rc=0 0.34s :: 27 passed in 0.19s
```

**数字自洽校验**：UI 线基线 254 项（R4 报告 224 + 后续 EX.3a/3b/2c 新增）+ 引擎线 `test_t42_engine.py` 27 项 = **281**。逐文件相加：20+28+10+14+7+6+22+10+23+10+4+5+1+10+1+16+16+23+8+10+10+27 = **281**。✅

### 5.2 冒烟 `tools/smoke_e2e.py`：PASS

真实点击驱动（`QTest.mouseClick`），788 章真实语料：

```text
[1] 预览完成：共 788 行，首行 = '封面'，封面标注正确 = True，前3行 = ['封面', '第 2 章\u3000简介', '第 3 章\u3000目录']
[1] 导入完成 1.76s：788 章 / 约 4,996,484 字 → 一键校正上下文已就绪 = True
[2] 取消场景：outcome=cancelled 9.23s，runs 残留 = []，无脏状态 = True
[3] 复跑完成：outcome=ok 14.62s，成品存在 = True，原书未动 = True，阶段耗时 = {'merge': 0.3, 'layout': 8.8, 'replace': 1.8, 'quote': 0.7, 'bookmap': 0.2, 'restore': 2.1}
[4] 错误卡：采集 8 条文本，人话且无内部细节 = True
[4] 诊断日志：code=U-R00，已写入 = True
[5] 零露出：扫描 758 条界面文本，命中 0
SMOKE: PASS
```

`stderr` 只有无害噪声（离屏插件提示）：

```text
QObject::startTimer: current thread's event dispatcher has already been destroyed
This plugin does not support propagateSizeHints()
```

### 5.3 引擎线自带验收 `tools/accept_t42.py`：7/7 ALL PASS（在合并主干上）

```text
=== S1 start ===
[S1] go 引擎全量 788 章跑起 …
[S1] python 引擎全量 788 章跑起 …
[S1] PASS  同输入 after 4f6ea8af90edafd3… == 4f6ea8af90edafd3…；restored 717fdfcee76fe3ee… 一致；replace go 3.568s / py 33.294s
=== S2 start ===
[S2] novel_fanpai_ch001-060.txt: 0.44MB 1.45s sha=bf2ec3c716da… 一致
[S2] novel_guimie_full.txt: 1.60MB 2.12s sha=369e24dc2d3e… 一致
[S2] novel_quehun_ch001-060.txt: 0.50MB 1.39s sha=6caf38174b09… 一致
[S2] pg23863_水滸傳.txt: 1.60MB 3.76s sha=8fa7729e7b08… 一致
[S2] pg23910_封神演義.txt: 1.80MB 3.71s sha=c5b267327ec9… 一致
[S2] pg23950_三國志演義.txt: 1.82MB 4.26s sha=ea5686aa6cf4… 一致
[S2] pg23962_西遊記.txt: 2.22MB 4.66s sha=4e2e582aa11e… 一致
[S2] pg24032_儒林外史.txt: 0.83MB 2.00s sha=d039136d51bf… 一致
[S2] pg24141_警世通言.txt: 1.15MB 2.69s sha=906f4622597f… 一致
[S2] pg24226_史記.txt: 1.93MB 4.62s sha=a60bdcd1b612… 一致
[S2] pg24230_今古奇觀.txt: 2.85MB 5.33s sha=e04dd510ac7b… 一致
[S2] pg24264_紅樓夢.txt: 2.62MB 5.54s sha=ff5cb694e61f… 一致
[S2] pg27166_呐喊.txt: 0.26MB 1.86s sha=9140f761a1ed… 一致
[S2] pg51828_聊齋志異.txt: 1.45MB 3.12s sha=641f2b2c192c… 一致
[S2] pg52200_金瓶梅.txt: 2.27MB 3.95s sha=1dfa6d8ced10… 一致
[S2] PASS  15/15 语料逐字节一致 （23.3MB / 50.5s）
```

```text
=== S3 start ===
[S3] 改名 Go 引擎 → 界面降级确认（探针点「改用 Python 引擎」）…
[S3] PASS  六阶段经 Python 引擎完成，还原 EPUB 与 Go 版逐字节一致；弹窗按钮=['取消', '改用 Python 引擎，继续校正'] 用户点了「改用 Python 引擎，继续校正」
=== S4 start ===
[S4] 改名 Go 引擎 → 用户拒绝降级 → 明确报错不硬跑 …
[S4] PASS  报错文案：「校正未开始：校正引擎不可用（引擎文件不存在（可能被删除或杀毒软件隔离））。可重试，或在设置里改用 Python 备用引擎。」；runs 产生 []
```

```text
=== S5 start ===
[S5] PASS  python→python / go→go，输出 sha 一致 717fdfcee76fe3ee…
=== S6 start ===
[S6] PASS  缺引擎 rc=1（明确报错）；--replace-engine python rc=0 报告 engine=python；doctor 对 python 模式提示不算问题
=== S7 start ===
[S7] Python 引擎 0.31 MB/s（33.294s / 10.5MB）vs Go 2.93 MB/s；排期基准 3.09 MB/s
evidence -> /tmp/t41a/work/evidence/t42_evidence.json
ALL PASS
```

### 5.4 UI 线自带验收 `tools/accept_t23.py`：PASS（在合并主干上）

```text
[A] 完整运行 29.99s outcome=ok poll=300 workdir_left=True
[B] 替换阶段取消 outcome=cancelled close=0.387s signal=Nones workdir_exists=False
[B2] 复跑 58.5s sha=717fdfcee76fe3ee…
[C] 排版阶段取消 outcome=cancelled close=9.228s workdir_exists=False
[D] 露出扫描：2020 条界面文本，命中 0
ACCEPT: PASS
{"A_vs_baseline": true, "B2_vs_A": true, "C2_vs_A": true, "all_equal": true}
```

---

## 6. 交付包内容与执行位

- zip 用 `zip`/`unzip` CLI 打包（**不用 python zipfile**——它丢 Unix 执行位）
- 保留 `.git`（下游可继续基于历史提交）
- 引擎二进制执行位：`git ls-files -s` → `100755 ... pipeline/vendor/fixtext/engine/go_src/bin/replace_by_go-linux-amd64`
- 排除：`runs/`（e2e 运行产物）、`__pycache__/`、`.pytest_cache/`

清洁解压后的自检结果见交付评论。

---

## 7. 已知边界（不掩盖）

- 冒烟与验收在 **Linux 离屏**环境跑；Windows 交互未实测。
- 全量 pytest 因 1 核/4GB 沙箱限制采用**逐文件串行**，与「单进程全量」在测试选择上等价（同一 22 个文件、同一环境变量），但并行/顺序对个别的跨文件状态无覆盖差异——本卡未验证并行执行下的行为。
- `accept_t42` S6 的 CLI 子进程用例依赖 `pyahocorasick` 装在 **用户区**（本次装到 `/home/gem/.aily/.cli/python/lib/python3.12/site-packages`）。这是**环境依赖**而非产品缺陷：干净机器上 `requirements.txt` 已列 `pyahocorasick`，但 CLI 子进程若在无 site-packages 的隔离 PYTHONPATH 下运行，需先 `pip install`。

---

## 8. 复现命令

```bash
# 全量测试（逐文件串行）
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=<pylibs>:<PySide6 site-packages>:<pkg>/fixtext_ui:<pkg>/pipeline:<pkg> \
FIXTEXT_SETTINGS_FILE=/tmp/xx.ini python3.12 run_pytest.py <pkg> out.log

# 冒烟（语料需放 <pkg>/../paohuo.epub）
QT_QPA_PLATFORM=offscreen PYTHONPATH=... python3.12 tools/smoke_e2e.py
```
