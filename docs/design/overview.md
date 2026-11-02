# FixText V1 · UI 交付目录

> 本目录收纳 FixText V1（Windows 桌面电子书排版校正工具）的设计原型与 Qt 实现骨架。
> 按用户要求，已把 **Qt 骨架** 与 **原型** 统一收拢到 `UI/` 下，根目录不再散落产出文件。

> **读之前请留意**：本页原为 UI 交付目录的说明，正文按当时云盘交付目录的完整形态写成，因此会提到 `src/`、`tests/`、`screenshots/`、`_scratch/`、`_build_prototypes.py` 等路径。这些内容**没有进本仓库**——`src/` 下的 PySide 骨架已被产品代码 `fixtext_ui/` 取代，`tests/` 下的冒烟脚本与仓库正式测试重名。仓库里实际收录的是本页、`prototypes/`（其中 `FixTextGUI_六入口合并_原型.html` 与 `FixTextGUI_合并版_原型.html` 是本页树里未列出的两个合并版本）与 `fixtext.qss`。为什么这样取舍，见 [`prototype-note.md`](prototype-note.md)。

## 目录结构

```
UI/
├── src/                         # Qt 骨架（可运行源码，互相 import）
│   ├── main_window.py           #   主窗口：左轨导航 + QStackedWidget 切页 + QSS 装载
│   ├── fixtext_widgets.py       #   共享部件库（Card / Pill / Switch / RadioCard / ProgressDialog / ConfirmDialog / Modal …）
│   ├── fixtext_tokens.py        #   设计令牌（单一来源，对应薄地基 :root）
│   ├── build_qss.py             #   令牌 → fixtext.qss 生成器（改令牌后重跑）
│   ├── fixtext.qss              #   生成产物（勿手改）
│   ├── check_module.py          #   检查问题页
│   ├── import_module.py         #   导入书籍页
│   ├── oneclick_module.py       #   一键校正页
│   ├── vocab_module.py          #   词库管理页（新增/检索/查重/合并/删除/本书专有词 + 撤销栈 + 自动快照）
│   ├── export_module.py         #   导出结果页
│   └── history_module.py        #   历史记录页
├── prototypes/                  # 设计原型 + 决策文档 + 生成脚本
│   ├── FixTextGUI_设计系统_薄地基.html
│   ├── FixTextGUI_导入书籍_原型.html
│   ├── FixTextGUI_检查问题_原型.html
│   ├── FixTextGUI_一键校正_原型.html
│   ├── FixTextGUI_导出结果_原型.html
│   ├── FixTextGUI_历史记录_原型.html
│   ├── FixTextGUI_词库管理_原型.html
│   ├── FixTextGUI_六入口合并_原型.html
│   ├── FixTextGUI_设计决策_导航与令牌统一.md
│   ├── _build_prototypes.py     #   原型生成脚本
│   └── _merge_six_prototypes.py #   六入口合并脚本
├── screenshots/                 # Qt 复查 / 骨架截图（真实字体）
├── tests/                       # 冒烟 / 截图验证脚本（已修 sys.path）
│   ├── _smoke_main.py           #   主窗口：6 模块齐全 + 全局设计依据联动 + 顶栏弹窗 + 重生成 QSS + 跨模块跳转
│   ├── _smoke_export.py
│   ├── _smoke_history.py
│   ├── _smoke_vocab.py
│   ├── _smoke_check.py           #   检查问题：save_and_next + 批量操作 入撤销栈 + 整体回退
│   ├── _shot_main.py            #   顶栏 设置 / 帮助 弹窗截图
│   ├── _shot_export.py
│   ├── _shot_history.py
│   └── _shot_vocab.py
├── _scratch/                    # 诊断用临时图与一次性脚本（非交付物，保留可回退）
└── overview.md                  # 本文件
```

## 运行方式

```bash
# 依赖
pip install PySide6

# 启动主窗口（样式表 fixtext.qss 由 build_qss.py 生成，需与 main_window.py 同目录）
python UI/src/main_window.py

# 改令牌后重生成样式表
python UI/src/build_qss.py        # → 写 UI/src/fixtext.qss

# 跑冒烟（offscreen，可直接断言）
cd UI/tests && QT_QPA_PLATFORM=offscreen python _smoke_main.py
cd UI/tests && QT_QPA_PLATFORM=offscreen python _smoke_export.py
cd UI/tests && QT_QPA_PLATFORM=offscreen python _smoke_history.py
cd UI/tests && QT_QPA_PLATFORM=offscreen python _smoke_vocab.py
cd UI/tests && QT_QPA_PLATFORM=offscreen python _smoke_check.py

# 抓真实字体截图（不要加 offscreen；脚本按 sizeHint 全高 render，绕开屏幕钳制）
cd UI/tests && QT_SCALE_FACTOR=1 python _shot_vocab.py
```

## 模块状态

| 模块 | 状态 |
|---|---|
| 导入书籍 / 检查问题 / 一键校正 / 导出结果 | ✅ 真实 Qt 页 |
| 词库管理 | ✅ 真实 Qt 页（已对齐更新后的原型：新增词条全流程 + 查重 + 合并 + 本书专有词 + 撤销栈 + 自动快照） |
| 历史记录 | ✅ 真实 Qt 页（已对齐更新后的原型：恢复 / 单条删除可撤销 + Toast「撤销」+ `Ctrl+Z`；清理全部清空撤销栈、不可撤销）。**恢复撤销已真实化**：恢复前捕获工作区前态（`_active_idx`），撤销时整体回退并刷新「当前工作区」指示 |

## 顶栏动作（⚙ / ? / ☰）

骨架阶段这三颗按钮曾是空桩，现已接入真实行为（`main_window.py`）：

| 按钮 | 行为 |
|---|---|
| ⚙ 设置 | 全局「为所有模块显示设计依据」开关 —— 一键联动 6 个模块的 `basis_cb`（不必逐页点）；附应用与目录信息 |
| ? 帮助 | 六个模块清单（图标 + 一句话职责）+「显示设计依据」说明 + 原型目录路径 |
| ☰ 菜单 | 重新生成样式表（跑 `build_qss.py`）/ 打开原型目录（Windows 资源管理器）/ 关于 |

- 弹窗统一用共享 `Modal`（已从 vocab 提升到 `fixtext_widgets.py`，与 `ConfirmDialog` 一致），只消费令牌。
- `ModulePlaceholder` 占位页类与未命中的 `else` 分支已删除；导航键未接线时改为 `raise RuntimeError`，避免静默降级。

## 词库管理 · 五条安全底线落地

| 底线 | 实现 |
|---|---|
| ① 可撤销 | `_undo_stack` + toast「撤销」按钮 + `Ctrl+Z`（`QShortcut`）；所有写动作先 `_push_undo` |
| ② 自动快照 | 每次变更前 `_snap()`，快照面板可「恢复到此」（`restore_snap`，上限 12 条） |
| ③ 文件不暴露 | 只显示友好名（我的词库 / 常规校正词库…），结果以结构化表格呈现，不露 PHP |
| ④ 先预览再确认 | 新增（预览并查重 → 确认写入）、删除（批量预览 → 确认）、合并、本书专有词均二次确认 |
| ⑤ 恢复默认 | 只重置 3 个内置词库，**保留自定义**（`restore_default`） |

> 条款号（§）一律收进「显示设计依据」开关，正文不露 §；同时清理了历史记录页遗留的条款号正文泄漏。

## 验证记录（本轮）

- `py_compile ../src/*.py` 全绿。
- `_smoke_main.py` 覆盖：6 模块无占位 / 模块齐全 / 全局设计依据联动 / 设置·帮助·关于·信息弹窗构建 / 重新生成样式表 → `MAIN_SMOKE_OK`。
- `_smoke_vocab.py` 覆盖：初始 14 条 / 4 basis、过滤、选择态、新增（二次确认 + 撤销栈）、删除 + 撤销、查重、合并、快照 + 恢复、恢复默认、本书专有词、设计依据开关 → `VOCAB_SMOKE_OK`。
- `_smoke_history.py` 覆盖：初始 3 行 / 状态列（2 正常 + 1 同步失败）/ 依据开关 / 重新导出 toast / **删除 + 撤销** / **恢复 + 撤销** / 清理全部清空撤销栈 / 空栈提示 / `ConfirmDialog` 构造 → `SMOKE_OK`。
- `_smoke_export.py` 回归通过（`ConfirmDialog` 抽入共享库后无重复定义）。
- 真实字体截图 8 张（默认 / 依据 / 快照面板 / 新增 / 查重 / 合并 / 本书专有词 / 删除预览），存于 `screenshots/Qt复查_词库_*.png`。
- 历史截图 4 张（集成 / 默认 / 依据 / **撤销 Toast**），存于 `screenshots/Qt复查_历史_*.png`。
- 顶栏弹窗截图 2 张（设置 / 帮助），存于 `screenshots/Qt复查_顶栏_*.png`。

## 本轮修复

- `QShortcut` 从 `QtGui` 导入（原误放 `QtWidgets`）。
- `self._snap_card` 名称冲突：在 `_workspace()` 里把 `_snap_card()` 的返回值赋给同名实例属性。
- 全选复选框 `self._chk_all` 跨重渲染复用导致 C++ 对象被级联删除：改为每次 `_entry_header()` 重建。
- `get_filtered()` 过滤逻辑：`dict_ == "custom"` 被错误排除，改为 `dict_ != "all"` 即按词库过滤；`set_tier()` 非自定义档位时把 `dict_` 复位为 `all`。
- `open_book_words()` 把 `QVBoxLayout` 传给 `add_widget`（需 `QWidget`）→ 包一层容器。
- 左栏词库卡片被右栏高度拉伸居中 → `addWidget(..., AlignTop)` 顶部对齐。
- 正文条款号泄漏（§2.4 / §2.2 / 2.4.2 / 2.4.3）→ 收进依据或删除。

## 顶栏 / 清理轮修复

- `Modal` 从 `vocab_module.py` 提升到 `fixtext_widgets.py`（与 `ConfirmDialog` 一致），vocab 改为导入，消除重复定义。
- 删除死代码 `ModulePlaceholder` 类与未命中的 `else` 分支；导航键未接线时 `raise RuntimeError`，不静默降级。
- 清理 `MODULE_DESC` 上方、`_top_action` 的过时「占位 / 待移植」注释；移除未用的 `r` 导入；`MODULE_PROTO` 由死数据改为帮助弹窗 tooltip 数据源。
- `_regen_qss()` 的子进程统一 `stdin/stdout/stderr=DEVNULL` + `timeout=30`，避免在 GUI 进程中因继承管道而挂起。

## 相对原型的交互缺口补齐（本轮）

用户指出的三处「原型有、骨架缺」已修复并补齐测试：

### 1. 跨模块跳转：占位 Toast → 真实 `MainWindow.go()`
- `main_window.py` 在模块实例化时把 `page.main = self` 暴露给各模块，供其调用 `go()`。
- 结果卡 / 导出完成卡的后续动作改为真实跳转，不再是「原型示意」Toast：
  - 导入完成 → 「⚡ 去一键校正」→ `go("oneclick")`；「🔍 先检查问题」→ `go("check")`。
  - 一键校正完成 → 「📤 去导出」→ `go("export")`。
  - 导出完成 → 「🕓 查看历史记录」→ `go("history")`；「⚡ 再校正一轮」→ `go("oneclick")`。
- 跳转逻辑抽成命名方法（`_go_oneclick` / `_go_check` / `_go_export` / `_go_history`），便于测试；`main` 缺失时回退 Toast，避免 standalone 测试崩溃。

### 2. 历史「恢复」撤销不完整 → 真实回退工作区前态
- 原实现只压 `{type:"restore"}`，撤销仅弹文案、不回退任何状态。
- 现引入 `self._active_idx`（当前已恢复到工作区的快照）：恢复前捕获 `prev_active`，撤销时复位并 `_render_tasks()` + `_refresh_active()`，使「当前工作区」提示与行内「当前工作区」徽标真实来回切换。
- 删除 / 清理同步维护激活态（删除激活项→清空；删除其前项→随列表前移），避免悬空索引。

### 3. 检查页：批量操作 + `save_and_next` 入撤销栈（P1）
- 原 `save_and_next` 直接标记 fixed、不推栈；`batch_op` 仅弹「可撤销」文案、不改数据也不入栈。
- `_push_undo()` 现捕获 `pre/hl/post/state`（含 `qx` 合并行改 `post` 的回退）；`save_and_next` 先 `_push_undo()` 再标记。
- `batch_op` 现**计算真实影响条数**（动态显示，不再硬编码 42）、对受影响处执行「最外层单引号→双引号」变换、压入 `{batch:True, items:[...]}` 批量记录；`undo_last()` 支持批量整体回退。
- 为可演示，新增 1 条单引号样例数据（`L1288 最外层单引号`），问题总数 7 → 8。

### 测试与验证
- 新增 `tests/_smoke_check.py`：覆盖 `save_and_next` 入栈+回退、批量操作入栈（批量记录）+ 整体回退（打桩 `QMessageBox.exec` 绕过阻塞弹窗）→ `CHECK_SMOKE_OK`。
- `_smoke_history.py` 强化「恢复 + 撤销」断言：验证 `_active_idx` 捕获与回退、「当前工作区」提示文本复位。
- `_smoke_main.py` 新增「跨模块跳转调用 `MainWindow.go`」断言：5 个跳转动作均命中正确模块键。
- 全量回归：`py_compile src/*.py` 全绿；`_smoke_check / _smoke_history / _smoke_main / _smoke_export / _smoke_vocab` 全绿。
