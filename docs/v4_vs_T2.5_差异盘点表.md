# M2-T2.6 · v4 骨架 vs T2.5 基座 逐项差异盘点表

- 基座：`FixText_M2-T2.5_集成联调_v1.zip`（云盘 file_token `LWZAbu3vSoXcofxBwvrciBmtnXg`，projects/fix_text/code）
- 增强源：用户 UI v4 骨架，云盘 projects/fix_text/UI（folder_token `YNYLfKC77ldRsUd8ceocrbABn4d`，`src/` 下 10 个 py）
- 盘点口径：逐个文件比对 v4 与基座的同名文件，差异逐条列出；判定「移植 / 不移植 / 部分移植」并给理由。
- 盘点时间：2026-10-27（本次卡开工时）

## 0. 文件级总览

| 文件 | v4 行数 | 基座行数 | 差异性质 | 结论 |
| --- | --- | --- | --- | --- |
| `vocab_module.py` | 1087 | 不存在 | v4 独有：完整词库五操作页 | **移植**（移植项 1） |
| `history_module.py` | 426 | 不存在 | v4 独有：完整历史页（含 `_active_idx` 撤销回退） | **移植**（移植项 2） |
| `check_module.py` | 657 | 611 | v4 多第 8 条示例问题、批量操作真实现、`save_and_next` 入栈 | **移植**（移植项 3） |
| `fixtext_widgets.py` | 680 | 618 | v4 多 `ConfirmDialog` / `Modal`；但 v4 的 `ProgressDialog` 是旧版（无 live 模式） | **部分移植**（只补 `ConfirmDialog` + `Modal`，见移植项 5） |
| `main_window.py` | 427 | 858 | 基座是六入口真壳（T2.1~T2.5 累积）；v4 是七项导航骨架 + 顶栏富交互 | **部分移植**（只取顶栏三按钮实现，见移植项 4） |
| `fixtext_tokens.py` | 149 | 221 | v4 用 `MODULES`（7 项含 home）+ `MODULE_PROTO`；基座用 `ENTRIES`（6 项）+ `MODULE_PROTO` 无 | **不移植**（基座导航模型更符合任务卡「六入口」），仅改 `status` 字段 |
| `build_qss.py` | 350 | 404 | v4 删掉了 `#PageTitle` / `#PageSub` / `#TopWhere` / `#RailIco` / `#RailLabel` / `#RailTag` / `#RailTip` / `#OverviewCard` / `#OvfIco` 样式 | **不移植**（基座这些页面部件在用，删了会掉样式）；仅吸收「HERE 常量」小改进 |
| `import_module.py` | 739 | 1050 | v4 是演示壳；基座已接真导入引擎（T2.2） | **不移植**（任务卡明确排除） |
| `oneclick_module.py` | 794 | 907 | v4 是演示壳（QTimer 假进度）；基座已接真链路 + 真取消（T2.3） | **不移植**（任务卡明确排除） |
| `export_module.py` | 642 | 不存在 | v4 独有导出结果页（演示壳） | **不移植**（任务卡移植范围未列；导出页真链路属 M3，本卡不扩范围） |

## 1. 移植项 1：词库管理页真实五操作 UI

**改了哪个文件**：新增 `fixtext_ui/vocab_module.py`（v4 1087 行 → 基座 `VocabModule`）。

**基座对应文件现状**：`main_window.py::BuildingPage`，`ENTRIES` 里 `vocab.status="building"`，页面只显示「这个入口还在建设中」+「现在可以先去这里」CTA。

**差异内容（v4 有、基座无）**：

| # | 能力 | v4 实现位置 | 判定 |
| --- | --- | --- | --- |
| 1.1 | 页头：标题 / 副标题 / 「显示设计依据」开关 / 分级切换（全部·自定义·内置）/ 快照开关 | `_header` | 移植 |
| 1.2 | 本书专有词库横幅（发现 3 条专有词 → 查看并加入 / 稍后） | `_banner` / `hide_banner` / `open_book_words` / `add_book_words` | 移植 |
| 1.3 | 左侧词库分级（我的词库 + 3 本内置，友好名 + 条数 + 可编辑/只读） | `_dict_list` / `_dict_item` / `_set_dict_active` | 移植 |
| 1.4 | 工具条五操作：新增 / 检索（双向）/ 查重 / 合并 / 删除选中 + 展开核对 + 选择计数 | `_toolbar` | 移植 |
| 1.5 | 词条表格（勾选 / 原词 / 替换为 / 类型 / 来源 / 命中书籍 / 操作），内置行只读 | `_table_card` / `_entry_header` / `_entry_row` | 移植 |
| 1.6 | 新增词条全流程：表单 → 预览并查重（冲突清单）→ 二次确认写入 | `open_add` / `preview_add` / `confirm_add` | 移植 |
| 1.7 | 编辑词条（内置禁编辑，保存入撤销栈） | `open_edit` / `save_edit` | 移植 |
| 1.8 | 查重：同词不同值 / 同值不同词分组预览 | `open_dup` / `_compute_dups` | 移植 |
| 1.9 | 合并：选 ≥2 条自定义 → 预览清单 → 二次确认写入 | `open_merge` / `do_merge` / `_after_merge` | 移植 |
| 1.10 | 删除：单条 / 批量，影响范围（命中书籍）预览 + 二次确认 | `_on_delete_selected` / `_confirm_delete` / `do_delete` | 移植 |
| 1.11 | 展开核对（只读结构化表格） | `open_expand` | 移植 |
| 1.12 | 撤销栈（底线①）：所有写动作入栈，toast 内「撤销」+ Ctrl+Z | `_push_undo` / `_undo` / `_build_status` / `_toast` | 移植 |
| 1.13 | 自动快照（底线②）：每次变更前快照，可恢复到任一时刻，保留最近 12 个 | `_snap` / `_render_snaps` / `restore_snap` | 移植 |
| 1.14 | 恢复默认词库（底线⑤）：只重置内置，保留自定义 | `restore_default` | 移植 |

**移植方式**：新增文件（v4 原样搬入，仅做三处适配：① 导入来源改基座包内路径；② 演示数据保留、真数据接口留 M3，按任务卡要求；③ 术语/内部词按基座 lint 口径复核）。`fixtext_tokens.ENTRIES` 里 `vocab.status` 由 `building` 改 `ready`；`main_window._build_content` 把 vocab 页从 `BuildingPage` 换成 `VocabModule`。

**不移植的部分**：v4 里没有需要排除的内容；演示数据本身按任务卡「演示数据保留」。

## 2. 移植项 2：历史页「恢复」撤销真实回退

**改了哪个文件**：新增 `fixtext_ui/history_module.py`（v4 426 行 → `HistoryModule`）。

**基座对应文件现状**：`BuildingPage` 占位，`history.status="building"`。

**差异内容**：

| # | 能力 | v4 实现位置 | 判定 |
| --- | --- | --- | --- |
| 2.1 | 任务列表表格（书名 / 时间 / 替换数 / 状态 / 操作），列宽比例 `COL_W=(3,2,1,2,4)` | `_task_card` / `_header_row` / `_task_row` | 移植 |
| 2.2 | 状态列：正常 / 基准同步失败（警示 + 留痕说明） | `_status_cell` | 移植 |
| 2.3 | **「恢复」撤销真实回退**：`_active_idx` 记录当前工作区快照；恢复入栈 `dict(type="restore", prev_active=…)`；撤销把 `_active_idx` 还原为 `prev_active` | `_confirm_restore` / `_undo` / `_refresh_active` | **移植（本项核心）** |
| 2.4 | 列表行「当前工作区」徽标（`idx == _active_idx` 时显示 `Pill("当前工作区","ok")`） | `_task_row` | 移植 |
| 2.5 | 删除单条可撤销，且维护 `_active_idx`（删当前→置 None；删前面的→前移一位） | `_confirm_delete` | 移植 |
| 2.6 | 清理全部历史（破坏性 + 二次确认 + 清空撤销栈） | `_confirm_clear` | 移植 |
| 2.7 | 快照与恢复说明卡 + 「当前工作区」提示文案 | `_snap_card` / `_refresh_active` | 移植 |

**移植方式**：整文件搬入 + 接进 `_build_content`；`ENTRIES["history"].status` 改 `ready`。**注意**：`verify_m2t21.py::1d_placeholder_cta` 原来点的是「历史记录」占位页的 CTA——历史页变真模块后该探针失效，需按 T2.5 同样做法改为点仍为占位的「导出结果」页（断言语义不变：占位页 CTA 必须真能跳转），并在工具里注明集成调整。

## 3. 移植项 3：检查页批量操作 + save_and_next 入撤销栈

**改了哪个文件**：`fixtext_ui/check_module.py`（增量改，不整文件覆盖——基座 check 页已接 T2.1~T2.3 成果）。

**基座对应文件现状**：`batch_op()` 是**假实现**——固定文案「影响 42 处」、确认后只弹「已批量修改 42 处」toast，**不真的改任何数据**；`save_and_next()` 直接标 fixed，**不入撤销栈**；`_push_undo` 只存 `hl`（不存 `pre`/`post`）。

**差异内容**：

| # | 差异 | 基座现状 | v4 做法 | 判定 |
| --- | --- | --- | --- | --- |
| 3.1 | 第 8 条示例问题「最外层单引号」（L1288） | 只有 7 条 | `PROBS` 增 1 条 | 移植 |
| 3.2 | `_push_undo` 存整段上下文 | 只存 `i` / `hl` / `state` | 存 `i`/`pre`/`hl`/`post`/`state` | 移植 |
| 3.3 | `save_and_next` 入撤销栈 | 不入栈，撤销撤不回来 | `self._push_undo()` 后再标 fixed | **移植（本项核心）** |
| 3.4 | `undo_last` 支持批量记录 | 只能撤单条 | `a.get("batch")` 时逐条还原 `pre/hl/post/state`，`cur` 回到首条 | 移植 |
| 3.5 | 批量操作真实现 | 假实现（固定 42 处、不改数据） | `_affected_single()` 真扫 + `_apply_outer_single()` 真替换 + 真实条数二次确认 + 批量入栈 | **移植（本项核心）** |

**移植方式**：按 diff 逐块 `edit`，不做整文件覆盖（避免丢 T2.1/T2.2/T2.3 在 check 页的接线）。

## 4. 移植项 4：顶栏三颗按钮

**改了哪个文件**：`fixtext_ui/main_window.py`（增量改）。

**基座对应文件现状**：三个按钮存在但都是**弱实现**：
- `_act_settings` → 弹 `SettingsDialog`，**只有「诊断日志」一项**，没有「全局设计依据联动」；
- `_act_help` → 纯 `QMessageBox` 三段文字，**不列六个入口职责**；
- `_act_more` → `QMessageBox` + 两个 ActionRole 按钮（回首页 / 关于），**没有「重新生成 QSS」「打开原型目录」**。

**差异内容**：

| # | 差异 | v4 实现 | 判定 |
| --- | --- | --- | --- |
| 4.1 | ⚙ 设置：`Modal` + `Switch`「为所有模块显示设计依据」+ `_apply_basis(on)` 遍历所有模块的 `basis_cb` | `_open_settings` / `_apply_basis` | 移植（保留基座已有的「诊断日志」入口，二者合并） |
| 4.2 | ？帮助：`Modal` 列出六个入口的图标 / 名称 / 短职责 / 原型 tooltip + 设计依据说明 | `_open_help` | 移植 |
| 4.3 | ☰ 菜单：`QMenu`「重新生成样式表」/「打开原型目录」/「关于 FixText V1」 | `_open_menu` | 移植 |
| 4.4 | 重新生成 QSS：subprocess 跑 `build_qss.py`，成功/失败用 `_flash` 反馈 | `_regen_qss` | 移植 |
| 4.5 | 打开原型目录（非 Windows 平台降级为路径提示） | `_open_prototypes` | 移植 |
| 4.6 | 轻量反馈弹窗 | `_flash` | 移植 |

**适配点（基座与 v4 的差异，必须处理）**：
1. v4 的 `_apply_basis` 遍历 `self.modules.values()`；基座模块是 `import_module` / `oneclick_module` / `check_module` / 新增 `vocab_module` / `history_module`，需改成基座的属性名集合，且 `import_module` **没有** `basis_cb` → 必须 `getattr(mod,"basis_cb",None)` 判空跳过（v4 原码已这么写，保留）。
2. v4 「打开原型目录」指向 `../prototypes`（v4 骨架目录结构）；基座交付包里原型 HTML **不随包分发**，路径需改为基座的 `reference/`（或说明「本机没有原型目录」）。这是**必须适配**的点，否则按钮点了会指向不存在的路径。
3. v4 菜单项「关于 FixText V1」文案里的 `UI/src/`、`UI/prototypes/` 属内部路径，基座的 lint 口径要过——改成用户能懂的说法。

**不移植的部分**：v4 `MODULES` 七项导航（含 home），基座保持六入口 + 首页内容区页。

## 5. 移植项 5：Modal 提升为共享 widgets 组件

**改了哪个文件**：`fixtext_ui/fixtext_widgets.py`（增量追加，不覆盖）。

**基座对应文件现状**：**没有 `Modal`，也没有 `ConfirmDialog`**。基座 `fixtext_widgets.py` 只有 `hline` / `no_badge` / `Pill` / `Switch` / `Card` / `FieldRow` / `RadioDot` / `RadioCard` / `ProgressDialog`。

**差异内容**：

| # | 类 | v4 实现 | 判定 |
| --- | --- | --- | --- |
| 5.1 | `ConfirmDialog`：破坏性/需二次确认动作的确认弹窗（`note_kind` warn/info、`confirm_kind` primary/danger） | v4 line 516 起 | 移植 |
| 5.2 | `Modal`：通用模态弹窗（`ModalHead` 图标+标题+关闭 / `body_l` / `foot`，API `add_note` / `add_widget` / `add_spacing` / `add_foot` / `exec`） | v4 line 592 起 | 移植 |

**明确不移植的 widgets 差异**：v4 的 `ProgressDialog` 是**旧版 timer-only**（无 live 模式），基座 T2.3 已升级为 `timer` + `live` 双模式（真实事件驱动、可取消、正在取消态）。**若整文件用 v4 覆盖，会把 T2.3 的实时进度与取消整条链路打回旧版** → widgets 只做**增量追加**，`ProgressDialog` 一个字不动。

**连带**：`Modal` 用到的 objectName（`ModalHead` / `ModalFoot` / `ModalClose`）在两边的 `fixtext.qss` 里都**没有**样式规则（两版 `build_qss.py` 均未生成），属 v4 遗留（靠内联 `setStyleSheet` 撑住外观）。本卡不擅自扩 QSS（会把令牌/样式门禁搅乱），按 v4 原样内联样式移植，并把「这三个 objectName 无 QSS 规则」记入遗留问题 P2。

## 6. 明确不移植清单（逐条理由）

| 项 | 理由 |
| --- | --- |
| v4 `import_module.py`（739 行演示壳） | 任务卡明确排除；基座该页已接 T2.2 真导入引擎（编码识别 / 3 步向导 / 后台线程），v4 是静态演示，覆盖即功能倒退 |
| v4 `oneclick_module.py`（794 行演示壳） | 同上；基座已接 T2.3 真链路（六阶段真进度 + Go 子进程即时 kill + 取消复跑 sha 一致） |
| v4 `export_module.py`（642 行） | 任务卡移植范围未列；导出真链路属 M3，本卡不扩范围（范围纪律） |
| v4 `fixtext_tokens.MODULES`（7 项含首页） | 基座已是六入口（首页为内容区页），v4 反而多一个首页轨项，与任务卡「基座六入口」冲突 |
| v4 `build_qss.py` 的样式删减 | 删掉 `#PageTitle` / `#PageSub` / `#TopWhere` / `#RailIco` / `#RailLabel` / `#RailTag` / `#RailTip` / `#OverviewCard` / `#OvfIco`——这些基座页面部件正在用，照搬会掉样式 |
| v4 `fixtext_tokens.MODULE_PROTO` 之外的描述块 `MODULE_DESC` | 基座 `ENTRIES[].short` / `.what` 已覆盖同等信息，重复引入会造成两套文案源 |

## 7. 移植后需要同步的基座文件（连带改动）

| 文件 | 改动 | 原因 |
| --- | --- | --- |
| `fixtext_ui/fixtext_tokens.py` | `ENTRIES` 中 `vocab` / `history` 的 `status`：`building` → `ready` | 这两页挂的是真模块，左轨不该再显示「建设中」；`verify_m2t21` 的 `rail_tag_matches_status` 用例正是按这个字段判 |
| `fixtext_ui/main_window.py` | `_build_content` 路由：`vocab` → `VocabModule()`、`history` → `HistoryModule()`；新增 `self.vocab_module` / `self.history_module`；`page()` 返回真模块 | 页面实例只建一次、路由保状态的约束不变 |
| `tools/verify_m2t21.py` | `1d_placeholder_cta` 改点仍为占位的「导出结果」页；`1e_topbar_actions` 探针兼容 `QMenu`（☰ 弹的是菜单不是对话框） | 历史页不再是占位页；菜单弹窗不是 QDialog 子类，原探针扫不到 |
| `docs/` | 本盘点表 + 移植自检记录 | 任务卡验收⑤要求随包交付 |

## 8. 验收衔接：移植后必须复跑的链路

| 链 | 脚本 | 关键数字 |
| --- | --- | --- |
| T2.5 验收① | `tools/verify_m2t21.py` | 4 检查（六入口可达 / 零露出 / 令牌对齐 / 截图） |
| T2.5 验收② | `pytest tests/` | ≥82 passed |
| T2.5 验收③ | `tools/accept_t23.py` | A 全跑 / B 取消 / B2 / C 异常 / C2，sha 三方一致 |
| T2.5 验收④ | `tools/smoke_e2e.py` | 导入 → 校正 → 取消 → 复跑 → 异常注入人话卡 |
| v4 冒烟① | `tests/_smoke_vocab.py`（适配基座路径） | 初始 14 条 / 4 basis；新增 / 删除 / 查重 / 合并 / 快照 / 恢复默认 / 专有词 |
| v4 冒烟② | `tests/_smoke_history.py`（适配） | 3 行；删除+撤销；**恢复+撤销真实回退**；清理全部清栈 |
| v4 冒烟③ | `tests/_smoke_check.py`（适配） | `save_and_next` 入栈 + 撤销回退；批量入栈 + 整体回退 |
| 截图 | `verify_m2t21.py` 产出 | 7 张（含新词库页 05、历史页 07）+ 顶栏按钮展开态 |
