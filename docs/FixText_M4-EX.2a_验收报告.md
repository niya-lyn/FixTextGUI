# FixText M4-EX.2a 验收报告 · UI 对齐一：设置页与布局令牌（结构层）

- 任务：M4-EX.2a（task 7701578370257014042）
- 基线：**M4-T4.4 包**（git `3554341`）——云盘 code 目录当时无 M4-T4.2 产物（该任务进行中），按任务卡「双线并行、都从 T4.4 产物起步」的约定回退
- 设计基准：合并版原型 v3 `FixText_V1_合并版_原型.html`（file_token `TE48bcYVlowWcHxIz11cF8wmnMg`）+ 更新记录（`EiDebGBaooOqdjx63ylcLJNmnCc`）
- 本卡 HEAD：`d12e19a`（最后改代码提交 `4ef6804`，2026-10-28 17:09:18 +08:00）；git 提交共 9 条，全部带 `M4-EX.2a` 前缀
- 验收时间：2026-10-28

## 1. 结论

**PASS。** 三项交付全部完成并通过事实性验收：设置页升为平级路由页（四卡、设置项真实生效）、v3 质感层与令牌集中管理落地、布局对齐（左轨六入口 / 顶栏三按钮真实化 / 词库页头浅色变体）。全量测试 214 passed（基线 204 + 新增 10），无回归。

## 2. 交付内容（9 条提交）

| 提交 | 内容 |
|---|---|
| `ec0430f` | 阴影令牌对齐 v3 六档（新增 xs / primary，sm/md/lg/focus 取值更新）；`reference/design_root_snapshot.css` 同步改为 v3 `:root` 节选（头注释写明来源与 MD5） |
| `ea04122` | 设置持久化键 `engine` / `vocabDir` / `logDir` / `diagEnabled` / `showBasis` 与读写辅助；`engine` 契约同 M4-T4.2（`go`\|`python` 默认 `go`，非契约取值不写入并回落 go） |
| `1c0671c` | 新建 `fixtext_ui/settings_module.py`（442 行）：设置页路由模块，四卡——词库与数据（存储位置 + 选择目录 + 恢复默认）、诊断与日志（日志目录 + 打开目录 + 出错自动留痕开关）、通用（只读保护常开 + 显示设计依据开关）、替换引擎（Go 默认 / Python 二选一） |
| `8b1084f` | 主窗口接线：⚙ 由模态弹窗改为跳设置页；切页卡片级联淡入（QGraphicsOpacityEffect + QPropertyAnimation，逐张延迟 55ms / 420ms OutCubic）；大屏收束 max-width 1280（viewport 宽 >1280 时内容区居中）；词库存储位置热重载；启动恢复「显示设计依据」；`main_app.py` 按设置初始化日志目录与留痕开关 |
| `6af61db` | 词库页头浅色控件变体：安全徽标（success 色）+ 历史 / 撤销浅色图标按钮（neutral 底、hover 转 primary）+ 页头分隔线 |
| `0c38419` | QSS 质感层：顶栏竖直渐变（三段 stop）+ 底部高光边、顶栏图标按钮 34×34 半透明底、表格斑马纹 + 行悬停、按钮统一焦点环（同宽描边）、`PathRow` 路径框（浅底虚线 + 等宽字体）；`build_qss.py` 色值 / 字号全部经令牌或集中常量；重新生成 `fixtext.qss` |
| `b018c41` | `tests/test_settings_module.py`（10 项）+ `conftest.py` 会话级隔离设置文件（`FIXTEXT_SETTINGS_FILE` 指向临时目录） |
| `4ef6804` | 页头图标按钮字号改用令牌 `ICON_GLYPH_SIZE`（消除最后一处散落硬编码字号） |
| `d12e19a` | 验收证据 + 取证脚本（`tools/accept_ex2a.py` 新建、`tools/verify_m2t21.py` 适配 ⚙ 路由跳转） |

## 3. 验收结果（事实性）

### 3.1 设置项真实生效（evidence/ex2a/accept_ex2a.json，`tools/accept_ex2a.py` RESULT: **PASS**）

原始输出：

```
rail: True | topbar: True | 新增行硬编码: 0 | 既有遗留: 29 | 词库落新位置: True
| 日志落新目录: True | 留痕关闭生效: True | 开关可写可读: True
RESULT: PASS
```

- **词库存储位置**：设置新目录后 `VocabStore(custom_path=...)` 生效，`add_entry(word="萧衍", value="萧彦", typ="人名")` 落在 `custom_vocab.json`（新目录），还原点子树同目录；等价重启（按设置重建 store）词条仍在。
- **日志目录**：设置新目录后 `_apply_log_backend()` 重新初始化错误中心，`write_record` 落 `…/log_home/fixtext-20261028.log`。
- **留痕开关**：界面真实路径关开关后 `write_record` 返回 None（不再写记录）；重开后恢复。
- **开关重启保留**：`engine=go / vocabDir / logDir / diagEnabled / showBasis` 重新读取（等价新进程）与写入值一致。
- **engine 契约**：`ENGINE_CHOICES=("go","python")`、默认 `go`、非契约取值不写入并回落 go（单测覆盖）。

### 3.2 六入口与顶栏手测（同脚本，离屏真实点击 QTest.mouseClick）

- 左轨六入口逐一点击全部跳转成功，面包屑正确：导入书籍 / 一键校正 / 检查问题 / 词库管理 / 导出结果 / 历史记录。
- 顶栏三按钮真实可点：☰ 更多（弹出 1 层菜单）、? 帮助（弹出 1 层帮助窗）、⚙ 设置（`history` → `settings`，平级路由跳转，非弹窗）。
- 页面切换卡片级联淡入实际生效（同一页不重放）。

### 3.3 QSS 令牌集中管理核查

- **本卡新增代码行中的散落硬编码色值 / 字号：0 条**（git diff 3554341..HEAD 的 + 行，排除令牌源 `fixtext_tokens.py` 与样式生成器 `build_qss.py`，注释不计）。
- 本卡改动的 QSS 新增视觉值全部来自令牌或 `fixtext_tokens.py` 集中常量（顶栏渐变 `TOPBAR_GRADIENT_TOP/BOTTOM`、图标底 `TOPBAR_ICON_BG(_HOVER)`、图标字号 `ICON_GLYPH_SIZE`、小标签字号 `MICRO_TAG_SIZE` 等）。
- `fixtext.qss` 内 29 个十六进制取值均为令牌展开结果（快照可逐一对回 `design_root_snapshot.css`）。
- **既有遗留 29 条**（基线已有、本卡未新增，如实列示留待后续卡）：fixtext_widgets.py 9 / first_run_wizard.py 6 / check_module.py 4 / oneclick_module.py 3 / vocab_module.py 3 / import_module.py 2 / export_module.py 1 / main_window.py 1。明细见 `evidence/ex2a/accept_ex2a.json` 第 4 节。

### 3.4 令牌对照与零露出（tools/verify_m2t21.py：**总体 通过**）

原始输出（节选）：

```
入口数 6，逐入口选中态唯一： True
路由保状态：同实例=True 状态保持=fixed
快捷方式 Ctrl+3/Ctrl+H： True | 占位页 CTA： True | 顶栏按钮： [True, True, True]
扫描界面字符串 2906 条 / 禁用模式 25 个，命中 0
令牌 73 vs 73，差异 0，缺失 0，多余 0
截图 7 张，stack 页 8
总体: 通过
```

- 令牌 73 项（v3 快照）与 `fixtext_tokens.py` 全量一致，差异 / 缺失 / 多余均为 0。
- 界面字符串扫描 2906 条，禁用模式命中 0（零露出）。
- ⚙ 探针已适配路由跳转（原探针期待模态窗，会误报 False）。

### 3.5 全量测试（evidence/ex2a/pytest_full.txt）

```
214 passed in 403.16s (0:06:43)
```

基线 204 + 本卡新增 10（`tests/test_settings_module.py`：engine 契约 / vocabDir / logDir / 开关持久化与重启读回 / 词库位置真实生效（含还原点子树与等价重启）/ 日志目录应用于错误中心 / 留痕关闭停写 / 四卡构建 / 引擎切换选中态 / 设计依据开关双向同步发信号）。

### 3.6 截图对照

- `screenshots/ex2a/10_home.png`（首页概览）、`screenshots/ex2a/11_settings.png`（设置页，QSS 已加载、1440×900）。
- 与原型 v3 同名视图的结构对照：设置页四卡顺序、页头（标题 + 副标题 + 右上开关）、路径虚线框、双引擎单选卡布局一致；首页卡片网格与顶栏渐变一致。

## 4. 差异清单（可接受偏差）

1. **字体渲染差异**：Qt 与浏览器字体渲染（抗锯齿 / 字距 / Segoe UI 回退）存在天然差异，按任务卡边界不做像素级复刻；结构、信息层级、文案对齐已对齐。
2. **级联动画实现差异**：原型 CSS `cardIn` 为 translateY + opacity；Qt 侧用等效 opacity 淡入（QPropertyAnimation），无位移动画——视觉效果接近，实现更稳（离屏环境下无副作用）。
3. **hover 平滑过渡**：CSS `transition` 在 QSS 中不可用，Qt 侧以离散 hover/pressed/focus 状态色阶近似（三档色差按令牌取）。
4. **既有 29 条硬编码字号/色值**：基线遗留（2b 前的历史代码），本卡未扩大，明细在证据 JSON；建议 2b 顺带清零。
5. **设计快照来源切换**：`reference/design_root_snapshot.css` 由薄地基版改为 v3 `:root` 节选（仅阴影区扩六档，其余令牌与薄地基一致），头注释已写明来源与 MD5。

## 5. 业务问题上报清单（只记录，未修）

1. `verify_m2t21.py` 原 ⚙ 探针按「弹出模态窗」断言——本卡已随路由化适配（属工具适配，非业务缺陷，列此备查）。
2. `first_run_wizard.py` 存在 6 处硬编码字号（基线遗留，属 2b 范围）。
3. 基线 29 条散落硬编码清单（见 3.3）建议在 2b 统一收编令牌。

## 6. 交付物

- `FixText_M4-EX.2a_设置页与布局令牌_v1.zip`（含 `.git`，9 条提交，zip CLI 打包保留执行位）
- 本报告 `FixText_M4-EX.2a_验收报告.md`
- 均上传云盘 `projects/fix_text/code`（folder_token `IIvifoTtFlIhXKdQBtrcDQYdnlW`）

## 7. 与 M4-T4.2 的对接契约（重要）

本卡只提供 `engine` 键的控件与读写（`go` 默认 / `python`，键名 `engine`，落用户区 `workspace/settings.ini`）；**引擎实际执行逻辑属 T4.2**。两线合流时以本卡键名与默认值为准。
