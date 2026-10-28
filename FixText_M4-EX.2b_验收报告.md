# M4-EX.2b 验收报告 · UI 对齐二：空状态与交互细节

- 基线：M4-EX.2a（git `f2c656b`），本卡在其上 4 条 `M4-EX.2b` 提交
- 设计基准：合并版原型 v3（file_token `TE48bcYVlowWcHxIz11cF8wmnMg`）
  + 更新记录（file_token `EiDebGBaooOqdjx63ylcLJNmnCc` §4 空状态整改 / §5 原型 bug 修复版）
- 范围纪律：纯 UI 对齐。功能缺陷（假数据、控件未接线）不进本卡，归 M4-EX.4；
  向导归 M4-EX.2c；设置页/令牌/布局已由 2a 完成。

## 一、实现内容

### 1. 统一空状态（v3 §4 口径）
- 新增共享控件 `fixtext_widgets.EmptyState`：对齐原型 `.empty-state` 结构
  （es-ico 54px 圆角底 + sh-sm 阴影 / es-t fs-md 加粗 / es-d fs-xs 灰字最宽 440px
  / es-acts 双按钮居中，主按钮 BtnPrimary + 次按钮 BtnGhost）；**无收起按钮**。
- 五页接入，全部由**真实无数据状态**触发（非写死假状态）：
  - 导入页：工作区扫描 `n_books == 0` → 空状态替换工作区卡；主按钮「📥 选择文件导入」
    接真实 `_choose_file`（原型此位为演示用「导入示例书」，真实应用无演示书，改接真实入口）
  - 一键校正页：`run_context is None` → 整页内容收起；主按钮「📥 去导入第一本书」
  - 检查页：`report is None`（未跑过校正）→ 内容区收起
  - 导出页：`source` 无就绪书源 → 内容区收起
  - 历史页：磁盘扫描 `tasks` 为空 → 任务表 + 快照面板收起
- **词库页不做空状态**（§4：内置词库随时可用），回归测试断言 `empty_state` 不存在。
- 主窗口统一接线 `_wire_empty_state`：主按钮 → 跳导入页；次按钮「🧭 打开新手向导」→ 弹向导。

### 2. 交互细节（按原型行为对齐，含 §5 修复版）
- 卡片折叠：走 `Card` 标题行 `mousePressEvent → toggle()`（等效原型 toggleCard 修复版
  `el.closest(".card")||el`），折叠态/箭头方向/正文显隐三者同步。
- 排版下拉回写：选新值 → 写回 `fmt_state[n]["val"]` + 持久化 + toast
  「排版配置已保存，下次沿用」（对齐原型 setFmtVal 修复版，不复刻旧 bug）。
- toast 反馈：各页 status 标签toast；历史页删除/续跑 toast 带撤销按钮（6000ms）。
- 批注切换 + 条款标签：全局「显示设计依据」开关，开 → 条款标签（§ 条款 / 底线 / T3 系）可见，关 → 隐藏。
- 操作历史（undoHistory）：历史页 `_undo_stack` + Ctrl+Z + toast 撤销按钮；
  删除任务真实移入回收目录，点撤销真实恢复。词库页「操作历史」面板在位（2a 前已有）。

### 3. 文案口径
- 五处空状态文案逐字取自原型 v3；导入页描述中「示例书按钮」按真实应用改为
  「选择文件按钮」（无演示书）。原型虚构演示书名（《星河彼端》《旧巷杂记》《灯下漫笔》）
  在五页空状态下零出现，回归测试逐页断言。

## 二、验收结果（事实性）

### 1. 空状态五处真实触发 + 截图（清空 workspace 后启动触发）
截图：`screenshots/ex2b/01_import.png` ~ `05_history.png`（MainWindow 1280×860 离屏渲染）。
验收脚本 `tools/accept_ex2b.py` 原始输出（21 项全 PASS）：

```
[PASS] S0 空状态 · import 页真实触发（还没有导入的书）
[PASS] S0 空状态 · import 页截图 01_import.png
[PASS] S0 空状态 · oneclick 页真实触发（还没有可校正的书）
[PASS] S0 空状态 · oneclick 页截图 02_oneclick.png
[PASS] S0 空状态 · check 页真实触发（还没有可检查的书）
[PASS] S0 空状态 · check 页截图 03_check.png
[PASS] S0 空状态 · export 页真实触发（还没有可导出的书）
[PASS] S0 空状态 · export 页截图 04_export.png
[PASS] S0 空状态 · history 页真实触发（还没有校正历史）
[PASS] S0 空状态 · history 页截图 05_history.png
[PASS] S0 空状态 · 词库页不做空状态（§4）
[PASS] S0 空状态 · 空状态无收起按钮（双按钮形态，仅 2 个按钮）
```

### 2. 交互细节逐项手测记录

```
[PASS] S1 交互 · 卡片折叠：点标题行切换展开/收起 —— False->True，箭头 ▼
[PASS] S1 交互 · 有书后空状态让位常规布局（一键校正页）
[PASS] S1 交互 · 排版下拉回写（n=3：不转换 → 转中文，写回 fmt_state）
[PASS] S1 交互 · toast 反馈（排版改动提示：「排版配置已保存，下次沿用」）
[PASS] S1 交互 · 批注切换开：条款标签可见（4 条） —— 样例：§ 底线③ 文件不暴露 · 友好名 / §2.4.1 五操作 · 新增为 V1 补入 / § 底线③ 结构化表格 · 不露内部文件格式
[PASS] S1 交互 · 批注切换关：条款标签隐藏
[PASS] S1 交互 · 操作历史：真实扫描出 2 条任务（fixture 为真实结构运行目录）
[PASS] S1 交互 · 删除任务 → toast 带撤销按钮（真实移入回收目录） —— 剩余 1 条
[PASS] S1 交互 · 点 toast 撤销按钮 → 任务恢复（undoHistory） —— 恢复后 2 条，撤销栈余 0
```

说明：操作历史的删除/撤销用 `tests/_fixture_run.py` 造的真实结构运行目录
（引号报告来自《炮火弧线》真实运行结果）驱动；删除走 `histdata.delete_run`
真实移入回收目录，撤销真实恢复。

### 3. 全量测试
223 passed（基线 214 + 本卡新增 9），分三批执行
（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，python3.12，offscreen）：

```
批次 A（7 文件）: 110 passed in 256.91s
批次 B（test_ex2b_empty_states + 5 文件）: 56 passed in 17.03s
批次 C（7 文件）: 57 passed in 157.72s
```

- 新增 `tests/test_ex2b_empty_states.py` 9 项：控件形态（双按钮/无收起/信号）、
  五页真实触发、词库页无空状态、卡片折叠、排版下拉回写。
- 既有用例更新 1 处：`test_t210_history.py::test_empty_history_gives_human_hint`
  原断言表内提示「还没有校正记录」，本卡按 §4 新口径改为断言统一空状态
  （标题 + 引导文案 + 任务表/快照面板收起 + 空状态可见）。

### 4. 证据时间戳
全部验收证据（`evidence/ex2b/accept.{json,log}`、`screenshots/ex2b/*.png`）
生成于最后一次改代码提交 `a29b8c4` 之后（验收脚本在提交后重跑，EXIT=0）。

## 三、边界与遗留
- 本卡不碰：词库选择控件/一键校正选项等接线（M4-EX.4）、向导重做（M4-EX.2c）、
  六阶段链路业务逻辑。扫描中未发现需登记清单的新业务问题。
- 已知限制：离屏截图不含鼠标光标与悬停态；向导弹窗本卡只引用入口不展开
  （验收脚本显式关闭首启自动弹窗以免无头阻塞）。
