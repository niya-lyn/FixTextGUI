# FixText M4-EX.3b 验收报告 —— 多本书·二：各模块按书联动

- 任务：M4-EX.3b（多本书第二张：把「当前书」接到所有模块）
- 基线：M4-EX.3a（c52da1c）
- 本卡提交：cf1a997 → d31d681 → 270af78 → b828b75 → 3e59237（代码）→ ac4f421（证据）
- 结论：**任务卡三项功能全部落地，全部验收通过**（accept_ex3b 34/34、全量 pytest 245 passed、verify_m2t21 通过、accept_ex3a 回归 23/23、smoke_e2e PASS）。

## 一、做了什么（对照任务卡三项）

### 1. 运行上下文按书
- `main_window.build_run_context`：运行根目录改为 `PKG_ROOT/runs/<书id>/`（原来全书共用 `PKG_ROOT/runs/`）。oneclick 工作目录、历史扫描、快照 `_snapshots/current.json`、`_trash` 全部随 runs_root 走——一处注入，全书隔离。
- 书架切换当前书后，一键校正页立即通过 `set_run_context` 拿到新书的运行根（不等下次操作）。

### 2. 结果页按书联动
- 新增 `MainWindow._reload_book_pages()`：统一「启动恢复 / 书架切换 / 导入完成」三条路径的四页重挂载（一键校正上下文 → 历史页 → 检查页 → 导出页上下文）。3a 时刻意的"不推给各页"中间态在本卡收敛。
- `_load_history` / `_sync_check` / `_sync_export` / `_refresh_export_ctx` 全部改走 `_book_runs_root()`；无记录的书走 2b 落地的空状态（验收 S3b 证实：检查页空、历史页空、导出页挂该书原文 corrected=False）。
- **接通「已导出」写点**（`fixtext_history.py` 预留字段首次有写入方）：
  - `fixtext_shelf.write_export_record(book_dir, fmt, path, sha256, hits)` 写书目录 `exports.json`；
  - 导出页 `export_module._record_export`（新增信号 `exportRecorded`）与历史页 `history_module._record_export_outcome` 两路写点，共用同一数据源；
  - `histdata.write_run_meta` 补写运行摘要的 `exported_at` / `exported_sha256`；
  - 写点不抛错：记录失败只不亮标识，不影响导出结果本身；
  - 书架「已导出」标识由书目录真实记录驱动（3a 只读方读 `exported_at` 键，键名兼容）。

### 3. 切换联动刷新
- `currentBookChanged` → `_on_current_book_changed` → `_reload_book_pages()`：切换即时刷新四页；`bookReady`（导入新书）与 `_restore_current_book`（启动恢复）同样收敛到该入口。
- B 书页面不得出现 A 书数据：验收 S4/S5/S6/S8 逐页断言 + 连续切换 6 次 + 独立子进程重启三重证实。

### 顺手修的真实缺陷
- `fixtext_export.export_book` 的 **txt 分支漏算成品 sha256**（只在 epub 分支算），导致导出记录与运行摘要的 `exported_sha256` 恒为空（b828b75）。
- `tools/smoke_e2e.py` 取消残留检查改为 **run 级比较**：3b 起 runs 根下按书分目录，书目录容器保留是正确行为，要清理的是半成品 `run-*`（3e59237）。

## 二、边界遵守

- 未动词库划分：通用词库仍全局共享、本书专有词仍按书（本卡零改动）。
- 未做书删除/重命名/批量操作；未动向导（2c 在本卡之后）。
- 设置仍全局。

## 三、验收原始输出

### 1. accept_ex3b（34/34 全 PASS，真实路径：真导入两本 / 真点按钮跑六阶段 / 真点导出 / 独立子进程重启）

```
S1a	PASS	真实导入两本书	titles=['北岭旧事', '南川杂记']
S2a	PASS	《北岭旧事》真实六阶段校正完成	outcome=ok 用时1.5s hits=0
S2b	PASS	运行目录落在该书专属目录 runs/<书 id>/ 下	/tmp/pkg/runs/北岭旧事_f81b2df4/run-1793195199607
S2c	PASS	校正后各页立即是甲书数据（无需切换）	
S3a	PASS	书架切换到乙书（真实点击）	stored=南川杂记_dcae2bbd chip='南川杂记'
S3b	PASS	切换后乙书还没记录：检查页空、历史页空、导出页挂乙书原文	check='' hist=[] exp='南川杂记'
S3c	PASS	《南川杂记》真实六阶段校正完成	outcome=ok hits=0
S3d	PASS	乙书运行目录落在 runs/<乙书 id>/ 下（与甲书隔离）	/tmp/pkg/runs/南川杂记_dcae2bbd/run-1793195201158
S4a	PASS	检查页只显示《南川杂记》的问题	book='南川杂记' found=20 期望=20
S4b	PASS	历史页只有《南川杂记》的记录	titles=['南川杂记']
S4c	PASS	导出页挂的是《南川杂记》的最近校正产物	title='南川杂记' corrected=True
S4d	PASS	一键校正上下文指向《南川杂记》的运行目录	runs_root='/tmp/pkg/runs/南川杂记_dcae2bbd'
S4e	PASS	四页截图已落盘（南川杂记）	S4_1_oneclick.png, S4_2_check.png, S4_3_history.png, S4_4_export.png
S4f	PASS	甲书的运行记录没有混进乙书的历史页	runs=['/tmp/pkg/runs/南川杂记_dcae2bbd/run-1793195201158']
S5a	PASS	切回甲书（真实点击）	
S5a	PASS	检查页只显示《北岭旧事》的问题	book='北岭旧事' found=10 期望=10
S5b	PASS	历史页只有《北岭旧事》的记录	titles=['北岭旧事']
S5c	PASS	导出页挂的是《北岭旧事》的最近校正产物	title='北岭旧事' corrected=True
S5d	PASS	一键校正上下文指向《北岭旧事》的运行目录	runs_root='/tmp/pkg/runs/北岭旧事_f81b2df4'
S5e	PASS	四页截图已落盘（北岭旧事）	S5_1_oneclick.png, S5_2_check.png, S5_3_history.png, S5_4_export.png
S5f	PASS	乙书的记录没有混进甲书的历史页	
S6a	PASS	A/B 连续切换 6 次：每次四页数据都正确、无崩溃	南川杂记:ok → 北岭旧事:ok → 南川杂记:ok → 北岭旧事:ok → 南川杂记:ok → 北岭旧事:ok
S7a	PASS	真实点击导出：甲书导出成功	done=True ok=True
S7b	PASS	甲书目录出现真实导出记录（exports.json）	keys=['exported_at', 'exported_sha256', 'fmt', 'hits', 'path']
S7c	PASS	导出记录带成品路径与校验值	path=北岭旧事.txt
S7d	PASS	书架甲书行亮「已导出」、乙书不亮	甲=已导出 乙=空
S7e	PASS	乙书目录没有导出记录（不串书）	
S7f	PASS	甲书那次运行的摘要写上了导出状态	exported_at=2026-10-28 21:46:43
S7g	PASS	书架「已导出」截图落盘	S7_shelf_exported.png
S8a	PASS	重启后当前书仍是乙书	chip='南川杂记'
S8b	PASS	重启后检查页只有乙书的问题	book='南川杂记' found=20
S8c	PASS	重启后历史页只有乙书	titles=['南川杂记']
S8d	PASS	重启后导出页挂乙书	'南川杂记'
S8e	PASS	重启后历史运行目录指向乙书专属目录	runs_root='/tmp/pkg/runs/南川杂记_dcae2bbd'

共 34 项，失败 0 项
```

任务卡验收点对照：
- 两书互不串页 → S4（乙书侧四页只有乙书数据）+ S5（切回甲书同理），逐页截图 S4_1~S4_4 / S5_1~S5_4 共 8 张 + 书架 S7_shelf_exported.png；
- A/B 来回切换 → S6a 连续 6 次来回，四页指纹每次都正确、无崩溃；
- 证据时间戳晚于最后一次改代码提交 → 全部证据文件 mtime 晚于 3e59237（2026-10-28 21:40:45），违规 0。

### 2. 全量 pytest（245 passed = 3a 基线 238 + 本卡新增 7）

```
245 passed in 301.41s (0:05:01)
```

### 3. verify_m2t21（令牌对齐 + 零露出）

```
  扫描界面字符串 2994 条 / 禁用模式 25 个，命中 0
  令牌 73 vs 73，差异 0，缺失 0，多余 0
  截图 7 张，stack 页 8
  总体: 通过
```

### 4. accept_ex3a 回归（3a 的 23 项在 3b 改动后仍全绿，证据已刷新）

```
共 23 项，失败 0 项
```

### 5. smoke_e2e（788 章端到端）

```
[1] 导入完成 0.8s：788 章 / 约 4,996,484 字 → 一键校正上下文已就绪 = True
[2] 取消场景：outcome=cancelled 9.3s，runs 残留 = []，无脏状态 = True
[3] 复跑完成：outcome=ok 14.56s，成品存在 = True，原书未动 = True，阶段耗时 = {'merge': 0.3, 'layout': 8.8, 'replace': 1.7, 'quote': 0.7, 'bookmap': 0.2, 'restore': 2.1}
[4] 错误卡：采集 8 条文本，人话且无内部细节 = True
[4] 诊断日志：code=U-R00，已写入 = True
[5] 零露出：扫描 761 条界面文本，命中 0
SMOKE: PASS
```

## 四、新增测试（tests/test_ex3b_linkage.py，7 项）

- test_run_context_runs_root_is_per_book —— 运行根按书
- test_switch_reloads_all_four_pages —— 切换即时刷新四页（乙空→甲有→乙空三段）
- test_repeated_switch_keeps_data_correct —— 4 次来回切换
- test_write_export_record_roundtrip —— 导出记录读写回路
- test_shelf_row_lights_exported_badge —— 书架「已导出」点亮
- test_export_module_records_book_and_run —— 导出页写点（exports.json + 运行摘要，exportRecorded 信号）
- test_history_reexport_records_book —— 历史页重新导出写点

## 五、已知事项

- 导出页与历史页两路写点以各自入口真实触发（export_now / 重新导出），共用 `write_export_record` + `write_run_meta`，不会双写同一事件。
- smoke_e2e 的取消残留判定从「runs 根级」改为「run 级」：书目录容器（runs/&lt;书id&gt;/）保留是 3b 起的正确行为，半成品 run-* 仍要求清干净（实测残留 = []）。
- 3a 的验收报告与证据随本包一并保留并已刷新（accept_ex3a 23/23 复跑）。
