# FixText M4-EX.3a 验收报告 —— 导入页书架与当前书机制

- 日期：2026-10-28
- 基线：M4-EX.2b 包（git `6a83f22`，224 项测试）
- 本卡交付：git 2 条提交（`b417f85` 功能 + `c52da1c` 验收脚本），HEAD `c52da1c`
- 设计基准：合并版原型 v3 §6「多书工作区与书架打磨」

## 1. 交付内容（对应任务卡三项）

### 1.1 导入页书架

- 新增 `fixtext_ui/fixtext_shelf.py`（数据层，纯 Python 无 Qt 依赖）与
  `fixtext_ui/fixtext_shelf_ui.py`（渲染层：`ShelfRow` / `ShelfPanel` / `BookChip`）。
- 数据源为工作区现有书目枚举（目录下有 `import.json` 才算一本书，与
  `workspace_usage` 同判据），**未新增任何导入副本机制**——书架只是已有副本的视图。
- 每行展示：书名（`《书名》后缀`）、格式（EPUB/TXT）、大小、导入时间、当前标记；
  行内「设为当前」为主操作按钮（QPushButton），「当前」为标识（QLabel），两者分离。
- 状态位只保留「已导出」一处标识（去掉已导入/已校正等冗余状态），
  **且只由真实导出记录 `exports.json` 驱动**——本卡没有写入方（导出完成写入属 3b），
  所以正常路径下该标识不显示，没有放假状态。验收 S2d 与单测
  `test_exported_flag_reads_real_record_only` 均验证：真写一条导出记录后标识才出现。
- 状态位固定 60px、动作位固定 96px、徽标与按钮同高 24px——切换当前书时
  相邻文字零位移（验收 S3b）。
- 无书时沿用 2b 空状态契约（`workspace_card` 收起、`empty_state` 显示），
  回归测试 `test_ex2b_empty_states.py` 未改动、全绿。

### 1.2 「当前书」显式化

- `MainWindow._import_record` 由「最近导入的那本」（隐式）改为**用户选中驱动**：
  选中落用户区 `settings.ini` 的 `currentBook` 键（存书 id），重启后按
  「设置里记的那本 → 否则最近导入那本 → 否则无」恢复。
- **导入新书自动设为当前**（`_on_book_ready` 写 `set_current_book_id` + 刷新书架），
  单书动线不退化：导入完一键校正页直接拿到运行上下文（验收 S7b）。
- 书架「设为当前」即切换（整行可点 + 按钮可点，两路都走同一信号）。

### 1.3 顶栏当前书显示

- 顶栏常驻 `BookChip` 胶囊：34px 高、320px 宽上限、渐变底、可点击可聚焦
  （键盘 Return/Enter/Space 同样触发）。
- 超长书名省略号显示，tooltip 给完整书名（验收 S4c）。
- 点击**复用既有 `go("import")` 路由**跳到导入页书架，未新造导航机制（验收 S5a：
  从一键校正页点击顶栏后 `current_key` 从 `oneclick` 变 `import`，B 行高亮）。
- 无书时显示中性占位「未选择书」，点击同样跳书架（验收 S8a/S8b）。
- 其它页面顶栏只展示不提供切换（用户约束）。

## 2. 中间态如实说明（重要）

**本卡结束时，切换当前书对其他页的可见影响仅顶栏书名变化**：
`_on_current_book_changed` 只更新窗口侧记录与顶栏胶囊，**不**重新推送给
导出页/历史页/检查页——各页数据仍按原逻辑。按书联动属 M4-EX.3b 范围，
本报告不冒充联动完成。代码中该方法 docstring 已写明该边界。

## 3. 验收证据（tools/accept_ex3a.py，全部真实界面路径）

两本书用**真实导入链路**（`fixtext_import.importer`）导入（TXT + 两章 EPUB），
「重启」用**独立子进程**重建主窗口，「点击顶栏」用 `QTest.mouseClick` 真点控件。

**23 项全 PASS**（原始输出见 `evidence/ex3a/accept_ex3a.log`，截图
`evidence/ex3a/01_shelf_two_books.png`）：

| 组 | 项 | 结论 |
|---|---|---|
| S1 真实导入 | S1a/S1b | 工作区 2 本，书名来自真实导入记录 |
| S2 书架 | S2a–S2e | 两行、字段齐全、当前标记唯一、「已导出」不显示、空状态收起 |
| S3 设 B 为当前 | S3a–S3d | 标记换行、文字零位移、落设置文件、标识/按钮分离 |
| S4 顶栏 | S4a–S4c | 书名变 B、常驻显示、tooltip 全文 |
| S5 点击跳转 | S5a–S5c | oneclick→import 走既有路由、B 行高亮、截图落盘 52KB |
| S6 重启 | S6a/S6b | 独立子进程后顶栏与当前书记录仍为 B |
| S7 单书回归 | S7a/S7b | 一本书自动设当前、一键校正页拿到运行上下文 |
| S8 无书占位 | S8a/S8b | 「未选择书」+ 导入页空状态、点击同样跳书架 |

## 4. 测试与回归

- 新增 `tests/test_ex3a_shelf.py` **14 项**（数据层 4 + 书架界面 3 + 顶栏胶囊 2 + 主窗口集成 5）。
- **全量 238 passed**（EX.2b 基线 224 + 本卡 14），305.75s，exit 0。
- `tools/verify_m2t21.py` 通过：零露出扫描 2989 条命中 0、令牌 73 vs 73 差异 0、
  六入口/快捷键/截图全过。
- 硬编码扫描（accept_ex2a §4 口径）：git 新增 777 行中 hex 仅 2 处且都在令牌源
  `fixtext_tokens.py`（颜色的家），UI 代码硬编码 hex/字号 0。
- 证据时间戳全部晚于最后代码提交（`c52da1c` 2026-10-28 20:46:10）：
  `evidence/ex3a/` 21:05、`verify_report.json` 21:04、`screenshots/` 21:04。

## 5. 实现要点与坑（供后续卡片复用）

- `QSettings("FixText","V1")` 在 main_window 里已被 M4-T4.4 换成
  `fixtext_settings.AppSettings` 别名——首启向导标记 `wizardSeen` 存在**用户区
  settings.ini**（`FIXTEXT_SETTINGS_FILE` 可覆盖），不是原生 `~/.config`。
  验收脚本预置该标记必须在设置 env 之后用 `AppSettings` 写，用原生 QSettings
  写了也白写（本轮实际踩过）。
- `ShelfPanel.refresh()` 全量重建行（每行是 `ShelfRow` 组合控件，徽标/按钮互斥），
  固定槽位保证重建前后文字不位移。
- 胶囊用自定义 `ElidedLabel`（`sizeHint` 钳到 248px + `resizeEvent` 里
  `fm.elidedText`），QLabel 自带省略不可靠。
- 书 id = 工作区里该书目录名（导入器生成 `<书名>_<hash8>`），当前书持久化存 id，
  目录改名/重导后按「最近导入」回落。

## 6. 交付物

- `FixText_M4-EX.3a_书架与当前书_v1.zip`（含 .git，HEAD `c52da1c`）
- 本报告 `FixText_M4-EX.3a_验收报告.md`
- 均上传云盘 `projects/fix_text/code`

## 7. 未做与边界

- 各模块按书联动（切书后导出/历史/检查页跟着换书）——M4-EX.3b。
- 书的删除/重命名/批量操作——未做（任务卡边界）。
- 词库/历史数据结构——未动。
- 新手向导——未动（2c 后续基于书架版导入页实现）。
