# FixText M3-T3.5 四卡集成联调 · 验收报告

- 卡片：M3-T3.5 四卡集成联调（M3 收口前置卡）
- 合并基底：线 A（T3.1 → T3.2 → T3.3），HEAD `b7012fe`
- 并入侧：线 B（T2.10 → T3.4），HEAD `fd37bce`，分叉点 `ea04d1a`
- 合并提交：`9060b0d`（2026-10-28 06:06:36）`M3-T3.5: 线A/线B 合并（git merge，非覆盖）`
- 基线成品 sha：`717fdfcee76fe3ee74d9a8bff20afbc84e7150bcbf5ee1a5b033a01739641dc2`（《炮火弧线》788 章 / 5100 处替换 / 108 处引号问题 / 专有词条 5792→去重 5749）
- 语料：《炮火弧线》EPUB，788 章，正文约 499.6 万字
- 全部数字均自采实跑，来源为 `evidence/` 下各 json 与本次命令输出，未沿用任何一条线的旧证据

---

## 1. 合并方式

**真 git merge，不是 `cp -r` 覆盖。**

```bash
git remote add lineb ../B
git fetch lineb
git merge --no-commit --no-ff lineb/master
```

- **冲突总数：1 处，add/add**，就是 `fixtext_ui/fixtext_snapshot.py`。
- 其余 188 个同名文件三方合并没有产生冲突；差异按卡片指定的"取 A / 取 B"逐项裁决。
- 合并后 `git log` 三条 `M3-T3.5` 提交依次为：合并 → 全量验收证据刷新 → 续跑指针缺陷修复。

### 1.1 同名冲突怎么解的

两条线的 `fixtext_ui/fixtext_snapshot.py` 是**两个完全不同的东西**，同名纯属巧合：

| | 线 A 的 `fixtext_snapshot.py` | 线 B 的 `fixtext_snapshot.py` |
|---|---|---|
| 职责 | 词库文件还原点仓库（词库撤销 / 时点恢复） | 运行产物阶段点恢复执行层（恢复到某阶段 / 从该点续跑） |
| 主要接口 | `SnapshotStore`、`MAX_POINTS`、`pack_builtin` / `unpack_builtin` | `list_points`、`restore_point`、`resume_from_point`、`current_state`、`build_export_source` |
| 体量 | 426 行 | 805 行 |
| 消费方 | `fixtext_vocab.py`（`from fixtext_snapshot import SnapshotStore`） | `history_module.py`（`import fixtext_run_snapshot as snapshot`） |

**解法：线 B 的改名，线 A 的保持原名。**

1. `git show lineb/master:fixtext_ui/fixtext_snapshot.py > fixtext_ui/fixtext_run_snapshot.py`
2. `git checkout --ours fixtext_ui/fixtext_snapshot.py`（保住线 A 的 `SnapshotStore`）
3. 同步 4 处导入改名：`history_module.py` / `tests/test_t34_snapshot.py` / `tools/accept_t34.py` / `tests/_smoke_history.py`
4. 两个文件头互相注明"另一个同名概念见 xxx"，防止后续维护者再搞混

改名后 4 处导入实测：

```
fixtext_vocab.py:37:            from fixtext_snapshot import SnapshotStore          ← 线 A，原名
history_module.py:38:           import fixtext_run_snapshot as snapshot             ← 线 B，改名
tests/_smoke_history.py:22:     import fixtext_run_snapshot as snap
tests/test_t34_snapshot.py:25:  import fixtext_run_snapshot as snap
tools/accept_t34.py:51:         import fixtext_run_snapshot as snap
```

### 1.2 两个模块共存导入实测（小组长指定排查项）

证据：`evidence/t35_coexist_import.json`，脚本 `tools/check_t35_coexist.py`，结论 `ALL PASS`。

| 检查 | 做法 | 实测结果 |
|---|---|---|
| A1 两个模块同时 import | 直接 `import fixtext_snapshot` / `import fixtext_run_snapshot` | A=`fixtext_snapshot.py`，B=`fixtext_run_snapshot.py`；同一文件=False，同名=False |
| A2 未互相遮蔽 | 查 `sys.modules` 两条是否都在 + 接口是否串味 | 两条都在=True；A 沾到 B 接口=False；B 沾到 A 接口=False |
| A3 同时导入后功能可调用 | A 建还原点 + 载荷打包解包；B 对空运行目录列时点 | A 建点√ 且载荷往返√；B 列出 5 个时点全部置灰且都给原因√；B 空指针返回 None√ |
| A4 冷启动真实构建 MainWindow | **独立子进程**从零 import 并 `MainWindow()` | A、B 同时进 `sys.modules`；`vocab_module.store.snap` 的模块 = `fixtext_snapshot`；`history_module.snapshot` 的模块 = `fixtext_run_snapshot`；窗口标题 `FixText V1`，六入口在册 |
| A5 导入链没被注释掉 | 扫 `main_window.py` 有无被注释的导入 + 查两条链的叶子导入 | 被注释的相关导入=0；`history_module`/`vocab_module` 均在；`fixtext_vocab` 确有 `from fixtext_snapshot import`；`history_module` 确有 `import fixtext_run_snapshot` |

**实测原始输出**（在最终包解压目录上直接跑，非沙箱工作区）：

```console
$ python -c "import fixtext_ui.fixtext_snapshot as A; import fixtext_ui.fixtext_run_snapshot as B; ..."
ok
A: /tmp/v35/fixtext_ui/fixtext_snapshot.py | SnapshotStore= True
B: /tmp/v35/fixtext_ui/fixtext_run_snapshot.py | list_points= True | restore_point= True
同一文件? False | A 有 B 接口? False | B 有 A 接口? False
sys.modules 两条: True True
```

冷启动 `MainWindow` 后的真实引用归属（A4 子进程内取）：

```
vocab_snap_module:      fixtext_snapshot        ← 线 A 的 SnapshotStore
history_snapshot_module: fixtext_run_snapshot   ← 线 B 的阶段点恢复层
window_title:            FixText V1
```

**关键说明**：`main_window.py` 本身**不直接**导入这两个快照模块，它是经两条传递依赖同时拉起两边——`main_window → vocab_module → fixtext_vocab → fixtext_snapshot`（线 A），`main_window → history_module → fixtext_run_snapshot`（线 B）。A4 用冷启动子进程真实构建窗口来验证这条链，比静态 grep 更有说服力：窗口起来了、两模块都进 `sys.modules`、各自引用指向正确的那个文件。

---

## 2. 合并裁决摘要（哪些取 A、哪些取 B）

### 2.1 取线 B

| 文件 | 取值 | 理由 |
|---|---|---|
| `fixtext_ui/fixtext_run_snapshot.py` | 线 B 原件改名 | 阶段点恢复执行层，线 A 完全没有 |
| `fixtext_ui/history_module.py` | 线 B 全量（902 行） | 含 `_open_snapshot_dialog` / `_apply_restore` / `_do_export_workspace` / `_do_continue`；线 A 560 行版只有旧的"降级为重新导出"，无真恢复 |
| `fixtext_ui/main_window.py` | **两边并集** | 取线 B 的 `_refresh_export_ctx` 多注入 `rules_before`/`rules_after`/`engine_path`；同时保住线 A 的 `check_module.set_vocab_store(...)` 与 `bookWordsReady.connect(...)` / `_on_book_words_ready` |
| `fixtext_ui/fixtext_export.py` | 线 B 的 `ensure_vendor` 位置 | 纯文本导出走 `clean_text → epubtext.bundle.Ledger/split_bundle`，同样需要引擎包，提前挂载正确 |
| `tests/test_t210_history.py` / `tests/_smoke_history.py` | 线 B 口径 + 补回 T3.3 断言 | 断言 `_open_snapshot_dialog` / `_apply_restore` 存在、`「恢复」` 是真恢复 |
| `tests/test_t34_snapshot.py` / `tools/accept_t34.py` | 线 B 独有，改名后带入 | 阶段点恢复的 9 项用例 + 九场景验收脚本 |

### 2.2 保留线 A（逐项实测，确认没被线 B 覆盖）

| 文件 | 卡片基准 | 合并后实测 | 关键特征实测 |
|---|---|---|---|
| `fixtext_ui/fixtext_vocab.py` | 1141 行 | **1141 行** ✓ | 线 B 根本没有此文件 |
| `fixtext_ui/vocab_module.py` | 1516 行 | **1516 行** ✓ | 非线 B 的 1088 行演示版 |
| `fixtext_ui/check_module.py` | 1031 行 | **1031 行** ✓ | 「加入词库」出现 **9 处** ✓（非线 B 的 886 行无按钮版） |
| `fixtext_ui/oneclick_module.py` | 905 行 | **905 行** ✓ | `BOOK_WORDS` 命中 **0** ✓；星陨大陆 / 墨羽 / 九转玄功 全 `fixtext_ui` 命中 **0 / 0 / 0** ✓ |
| `fixtext_ui/first_run_wizard.py` | 中性示例名 | **384 行** ✓ | 星河彼端 **0**、旧巷杂记 **0** ✓ |
| `pipeline/fixtext_pipeline/stages/bookmap.py` | 216 行含硬门禁 | **216 行** ✓ | 第 34 行 `ENTRY_PREVIEW_MAX = 0` ✓；非线 B 的 94 行截断 20 条版 |
| `fixtext_ui/fixtext_worker.py` | 524 行透传 | **524 行** ✓ | `book_words_declared_total` 命中 1 处 ✓（非线 B 的 481 行） |
| T3.1–T3.3 测试与验收脚本 | 全部在 | 全部在 ✓ | `test_t31_*` 43 项、`test_t32_vocab_safety.py` 23 项、`test_t33_book_words_ui.py` 8 项；`accept_t31/t32/t33` + `build_vocab_index.py` + `_t33_prepare_run.py` 齐全 |

**8 类全部达标，无一处被线 B 覆盖。**

### 2.3 未照搬

线 B 的 `evidence/` 与 `screenshots/` 未使用任何一张。合并版 `evidence/` 与 `screenshots/` 全部用合并后的代码重跑生成（见第 5 节时间自检）。

---

## 3. 测试

**194 项全绿，290.94s。**

```
194 passed in 290.94s (0:04:50)
```

### 3.1 项数核对（不重不漏）

| 来源 | 项数 | 说明 |
|---|---|---|
| 线 A 侧（T3.1 + T3.2 + T3.3 + M1/M2 存量） | 184 | 卡片基准 |
| 线 B 侧新增 `test_t34_snapshot.py` | 9 | 线 B 独有，改名后带入 |
| M3-T3.5 新增回归 | 1 | `test_resume_adopts_workspace_and_stays_exportable`（第 4 节缺陷的锁） |
| **合计** | **194** | `pytest --co` 实测 194 |

卡片预期约 193 = 184 + 9；实测 194 比预期多 1，多出的正是本次为线 B 缺陷补的回归用例，**不是重复计数**。按文件分布实测（`--co` 计数）：

```
28 test_error_center.py        24 test_no_jargon.py         23 test_t32_vocab_safety.py
20 test_encoding.py            16 test_t31_vocab_ui.py      16 test_t31_vocab_store.py
12 test_first_run_wizard.py    10 test_t34_snapshot.py      10 test_t31_book_words.py
10 test_import.py               8 test_t33_book_words_ui.py  6 test_export_resolve.py
 5 test_t210_history.py         4 test_t210_check_inject.py  1 test_t31_vocab_merge_click.py
 1 test_t210_reexport_sha.py
```

对照线 B 原包同名文件计数：`test_t34_snapshot.py` 线 B 为 **9** 项，合并后 **10** 项，差额 1 = 新增回归；其余文件项数与线 B 完全一致，无重复收集。

---

## 4. 发现并修复的线 B 真实缺陷

### 4.1 现象

端到端走到「从该点续跑 → 再导出」这一步时，续跑本身成功（exit 0、跳过 merge/layout/replace、成品 sha 与基线一致），但紧接着点「导出当前工作区」报：

> 导出失败：这本书还没有可导出的正文，请先导入一本书。

界面侧同源表现：续跑成功后「导出当前工作区」按钮反而变灰。

### 4.2 根因

`fixtext_run_snapshot.py` 的 `_adopt_workspace()` 在续跑成功后把工作目录登记成"当前工作区"，写指针时**漏了 `snapshot_dir` 字段**：

```python
# 修复前
_set_current(runs_root, {k: v for k, v in meta.items()
                         if k not in ("stage_dirs", "continued")})
```

而 `current_state()` 的第一道判据就是它：

```python
raw = _read_json(store_root(runs_root) / CURRENT_FILE)
if not raw or not raw.get("snapshot_dir"):
    return None
```

于是 `current_state()` 返回 None → `history_module._do_export_workspace()` 抛「还没有恢复过时点」→ `_refresh_active()` 里 `ready = bool((cur or {}).get("working_text"))` 也为假，按钮随之置灰。

**为什么 T3.4 自己的验收没抓到**：`accept_t34.py` 的 S4 只断言续跑退出码、跳过阶段和成品 sha，没测"续跑之后还能不能导出"；`test_restore_replace_then_resume_skips_done_stages` 又用了 `adopt=False`，压根不走 `_adopt_workspace`。缺陷因此一直隐着。

### 4.3 最小修复

只补一个字段，不动任何业务逻辑：

```python
# M3-T3.5 修：续跑后这里就是新的「当前工作区」现场，指针必须带上
# snapshot_dir，否则 current_state() 判定「没有时点」直接返回 None，
# 「导出当前工作区」会在续跑成功后反而失效。
snapshot_dir=str(work),
```

### 4.4 新回归用例

`tests/test_t34_snapshot.py::test_resume_adopts_workspace_and_stays_exportable`——真跑一次六阶段校正 → 恢复到「替换完成」→ `adopt=True` 续跑 → 断言：指针非 None、`snapshot_dir` 存在且目录在、`working_text` 存在、`build_export_source()` 能取到源且 `can_restore_epub` 为真。修复前该用例失败，修复后通过。

`tools/accept_t35.py` 的步骤⑧也从"自己拼状态字典"改为走界面真实路径 `history_module._do_export_workspace(ctx)`，这样验的是**用户实际点的那条路**，而不是我另外造的一条。

---

## 5. 证据自检（小组长指定项）

```
合并提交 9060b0d: 2026-10-28 06:06:36 +0800
evidence/ + screenshots/ 文件总数: 39
早于合并提交的文件数: 0
最早一件证据: 2026-10-28 06:13:04  screenshots/01_home_overview.png
最晚一件证据: 2026-10-28 07:00:01  evidence/t32_tests.txt
```

自检时先发现 **7 个文件早于合并提交**，已全部重新生成：

| 文件 | 原时间 | 产出方式 | 现时间 |
|---|---|---|---|
| `evidence/smoke_stderr.log` | 02:34:48 | 重跑 `tools/smoke_e2e.py`（stderr 重定向） | 06:58:52 |
| `evidence/t31_tests.txt` | 02:34:49 | 重跑 `pytest tests/test_t31_*.py`（43 passed / 16.22s） | 06:59:33 |
| `screenshots/08_topbar_help_open.png` | 02:34:55 | 新建 `tools/_shoot_topbar.py` 重拍 | 06:58:25 |
| `screenshots/09_topbar_settings_open.png` | 02:34:55 | 同上 | 06:58:26 |
| `screenshots/10_topbar_menu_open.png` | 02:34:55 | 同上 | 06:58:26 |
| `evidence/t32_tests.txt` | 03:42:15 | 重跑 `pytest tests/test_t32_vocab_safety.py`（23 passed / 22.64s） | 07:00:01 |
| `evidence/t29_scan.json` | 05:26:55 | 重跑 `tools/scan_t29.py`（2153 条文案 / 25 项词表 / 命中 0） | 06:58:33 |

**说明一处口径**：顶栏三张展开态截图原本由 M2-T2.6 一次性人工补拍、包里没有可复现脚本。本次补了 `tools/_shoot_topbar.py`（QTimer 在 `exec()` 弹窗出现后抓图再关闭，规避无头环境阻塞），按同一口径重新生成，使该项也变成可复现的。若小组长认为这三张属于 M2-T2.6 范畴、不该由本卡承担，可整组剔除，不影响本卡任何验收条款（六入口截图 01–07 由 `verify_m2t21.py` 产出，与这三张无关）。

---

## 6. 两套快照能力并存（核心验收条款）

### 6.1 词库侧（线 A，`fixtext_snapshot.SnapshotStore`）

证据：`evidence/accept_t35.json` → `s1a_vocab_snapshot`

| 项 | 值 |
|---|---|
| 加入前 sha | `28adcba340338e5e47e1…` |
| 加入后 sha | `e85861da65a7e8fa3d75…` |
| 撤销后 sha | `28adcba340338e5e47e1…` |
| 撤销后 == 加入前 | **True** |
| 还原点载荷可取 | True（`point_count=4`） |

端到端里同样验了一次：`sha_before` `74f8cb5f87e82c8107f9…` → 加入后 `ef86c6dca9fd6cab02c6…` → 撤销后回到 `74f8cb5f87e82c8107f9…`，`undo_identical=True`。

### 6.2 运行侧（线 B，`fixtext_run_snapshot`）

证据：`evidence/accept_t35.json` → `s1b_run_snapshot`

| 项 | 值 |
|---|---|
| 可用阶段点 | **5 / 5** |
| 恢复到的点 | `replace`「替换完成」 |
| 工作正文 sha | `1f74a4a181042211c4613c954e4cfc258b2f900b51d1f2ed7a4de8c84dfcfd06` |
| 该阶段产物 sha | `1f74a4a181042211c4613c954e4cfc258b2f900b51d1f2ed7a4de8c84dfcfd06` |
| 一致 | **True** |
| 逐项复制校验 | 7 项（after_text / before_text / layout_text / merge_text / merge_ledger / layout_ledger / ledger）全部 True |
| 恢复后重新导出 sha | `717fdfcee76fe3ee…`（== 基线） |

### 6.3 结论

**两边都能重新导出**：词库侧撤销后可继续读词库、运行侧恢复后可导出成品（sha 与基线一致）。两套能力在同一份代码里同时活着，互不遮蔽（第 1.2 节 A1–A5 全部实测通过）。

---

## 7. 六入口真实可用 + 令牌与零露出

证据：`evidence/accept_t35.json` → `s2_six_entries`、`s4_no_leak`；`verify_report.json`；`evidence/t29_scan.json`

### 7.1 六入口逐入口真实点开（`QTest.mouseClick` 点左轨真控件）

| 入口 | 真点击 | 落地 | 页面对象 | 模块 | 页面文本数 |
|---|---|---|---|---|---|
| 导入书籍 | ✓ | ✓ | ✓ | ✓ | 55 |
| 一键校正 | ✓ | ✓ | ✓ | ✓ | 106 |
| 检查问题 | ✓ | ✓ | ✓ | ✓ | 339 |
| 词库管理 | ✓ | ✓ | ✓ | ✓ | 98 |
| 导出结果 | ✓ | ✓ | ✓ | ✓ | 41 |
| 历史记录 | ✓ | ✓ | ✓ | ✓ | 37 |

**6 / 6 全部可用。**

### 7.2 `verify_m2t21` 通过

- 六入口可达 + 选中态唯一 + 顶栏「当前位置」跟随 + 页面非空：通过
- 设计令牌 71 项 vs 薄地基 HTML `:root` 71 项，**差异 0**
- 零露出：2799 条界面字符串 / 25 项禁用词，**命中 0**
- 离屏截图 7 张（01–07）

### 7.3 合并版零露出复扫

| 扫描 | 文案数 | 禁用词表 | 命中 |
|---|---|---|---|
| `accept_t35` S4 | 676 | 24 项 | **0** |
| `scan_t29`（全站） | 2153 | 25 项 | **0** |
| `accept_t34` S9 | 402 | — | **0** |
| `accept_t210` | 404 | — | **0** |
| `accept_t23` | 1575 | — | **0** |
| `verify_m2t21` | 2799 | 25 项 | **0** |
| `smoke_e2e` | 743 | — | **0** |

**合并后零技术名词露出，全项命中 0。**

---

## 8. 十个验收脚本（合并版全部复跑）

| 脚本 | 结果 | 关键数字 |
|---|---|---|
| `verify_m2t21` | PASS | 令牌 71 vs 71 差异 0；2799 条文案 / 25 词表 / 命中 0；截图 7 张 |
| `accept_t23` | PASS | A 全跑 18.19s（layout 9.36 / replace 3.00 / restore 2.87）；B 取消在 replace；B2 复跑；C 取消在 layout；确定性 `all_equal=True`（A vs 基线 / B2 vs A / C2 vs A 全一致）；1575 条文案命中 0 |
| `accept_t27` | PASS | 788 章；导出 sha `717fdfce…` == 基线；8 项检查全通过 |
| `accept_t28` | PASS | 向导 69 条文案 / 25 词表 / 命中 0 |
| `accept_t210` | PASS | 108 处问题 declared==found==108（自动可修 97 / 人工 11）；3 页；重启后记录仍在；重新导出 sha `717fdfce…` == 基线；404 条文案命中 0 |
| `smoke_e2e` | PASS | 预览 788 行首行「封面」；导入 1.31s；取消 11.23s 无残留；复跑 19.28s；原书未动；错误卡 8 条人话；743 条文案命中 0 |
| `accept_t31` | PASS | 合并操作 6→1；撤销 `undo_identical=True` |
| `accept_t32` | PASS | 31 个用例载荷；重启后撤销一致；时间线 12 条渲染 |
| `accept_t33` | PASS | **18 / 18**；准备运行 19.55s；专有词条 5749 / 声明 5792；788 章；引号 108 处；还原 sha `717fdfce…` |
| `accept_t34` | PASS | 5/5 阶段点；S2 工作正文 sha `bf7e6b21a2c2e01d…` == 阶段产物；S3 导出 sha `717fdfce…`；S4 续跑 9.35s 跳过 merge/layout/replace；S9 402 条文案命中 0 |

外加本卡新增：
| `tools/accept_t35.py` | **ALL PASS** | 见第 6、7、9 节 |
| `tools/check_t35_coexist.py` | **ALL PASS** | 见第 1.2 节 |

---

## 9. 端到端真实路径（八步，全程 sha 对照）

证据：`evidence/accept_t35.json` → `s3_e2e.steps`，截图 `evidence/t35/*.png`

| 步骤 | 耗时 | 产出 / 数字 | sha256 | == 基线 |
|---|---|---|---|---|
| ① 导入《炮火弧线》 | 1.17s | 788 章 | — | — |
| ② 一键校正 | 19.82s | 788 章 / 5100 处替换 | `717fdfcee76fe3ee74d9…` | **True** |
| ③ 检查页 | — | 108 处问题 | — | — |
| ④ 词库页加入专有词 → 撤销 | — | `sha_before` `74f8cb5f…` → 加后 `ef86c6dc…` → 撤销 `74f8cb5f…` | 回到前态 True | — |
| ⑤ 导出 | 0.0s* | 《炮火弧线》.epub | `717fdfcee76fe3ee74d9…` | **True** |
| ⑥ 历史页恢复「替换完成」 | — | 工作正文 == 阶段产物 | `1f74a4a181042211c461…` | — |
| ⑦ 从该点续跑 | 9.8s | exit 0；跳过 merge(0.706s)/layout(9.075s)/replace(3.03s)；实跑 quote 1.128s / bookmap 0.854s / restore 2.965s | `717fdfcee76fe3ee74d9…` | **True** |
| ⑧ 再导出 | — | 走界面真实路径 `_do_export_workspace` | `717fdfcee76fe3ee74d9…` | **True** |

\* ⑤ 的 `seconds=0.0` 是按钮点击到异步任务启动的耗时（导出在后台线程跑），不是导出本身耗时；导出结果的 sha 由 `outcome.sha256` 读取。

**结论：八步全程 `717fdfce…` 一致，没有一步改变了产物。** 唯一"改变过产物"的位置是第 ④ 步的词库文件（加词改变 sha），撤销后逐字节回到前态，且它不影响成品电子书——成品 sha 前后都是基线值。

`⑦` 说明续跑只补做后面三阶段（quote / bookmap / restore），前面三阶段按断点恢复跳过且耗时如实记录，而不是"假装跳过"。

---

## 10. 本轮唯一偏离"只合并"的地方（如实记录）

除同名模块改名与导入同步外，**改了 1 个字段**（第 4 节的 `snapshot_dir`）并加了 1 项回归用例。这是卡片纪律允许的"发现 A/B 真实缺陷时修最小必要范围并写进报告"。

除此之外没有任何产品行为改动：
- 未新增入口、未改界面文案、未改任何阶段逻辑、未改词库/导出/历史页行为
- 未改动线 A 的 8 类文件任何一行（行数与关键特征逐项实测一致）
- 未改动线 A 的 `fixtext_snapshot.py`（426 行，仅新增了文件头互相注明的 docstring）

---

## 11. 已知限制 / 未验证范围

1. **只在离屏（`QT_QPA_PLATFORM=offscreen`）下验过**，未在真实桌面合成器上验窗口尺寸/滚动条表现。M2-T2.1 的"三档宽度无横向滚动条"结论沿用原口径，本卡未重测。
2. **只在 Linux 验过**。Windows 引擎 `replace_by_go-windows-amd64.exe` 随包但未在 Windows 上实跑。
3. **顶栏三张截图的口径**见第 5 节说明：原为一次性人工补拍，本次补脚本重拍；若判定不属本卡范围可整组剔除。
4. **`accept_t33` 依赖预跑**：需先执行 `tools/_t33_prepare_run.py`（19.55s 真实六阶段运行）产出 `runs/t33_real`，否则脚本报缺文件。这是一次性前置，不是缺陷。
5. **`accept_t23` / `smoke_e2e` 依赖基线目录** `work/in/baseline_paohuo/`，需先跑一次 M1 全链路。同理属环境前置。
6. **单语料**：全部端到端只用了《炮火弧线》一本（788 章）。其他语料（GB18030 / Big5 / 简繁体混排书）的端到端未在本卡复验，M2-T2.2 的编码识别结论未变。
7. **性能未做专项**：19–20s 全链路耗时为实测值，但本卡未建立性能基线合同，不构成性能结论。
8. **`_adopt_workspace` 修复只覆盖"续跑后导出"这一条路径**。续跑后**再次恢复另一个时点**、续跑中途取消等组合路径，本卡未逐一展开验证（不在 T3.5 验收条款内）。

---

## 12. 交付清单

- 代码包：`FixText_M3-T3.5_四卡集成联调_v1.zip`（含 `.git`、引擎执行位 100755、排除 `runs/` 与 `__pycache__`）
- 验收报告：本文档 `FixText_M3-T3.5_验收报告.md`
- 证据：`evidence/`（含 `accept_t35.json`、`t35_coexist_import.json`、10 个验收脚本证据）+ `screenshots/`（10 张）+ `evidence/t35/`（端到端截图）
- 新增工具：`tools/accept_t35.py`、`tools/check_t35_coexist.py`、`tools/_shoot_topbar.py`
