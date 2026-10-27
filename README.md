# FixText M2-T2.1 · 主窗口与六入口路由

在已验收的 Qt 骨架上完成统一主界面框架：左侧六入口常驻导航轨 + 顶栏 + 内容区，
六个入口全部可点、状态清晰，界面无内部目录概念露出。

## 一、这一版做了什么

| # | 改动 | 说明 |
|---|---|---|
| 1 | 左轨从 7 项收敛为 6 项 | 骨架把「首页概览」当成第 7 个导航项，与任务卡「六入口」不符。首页降级为内容区页，左轨只留导入书籍 / 一键校正 / 检查问题 / 词库管理 / 导出结果 / 历史记录。 |
| 2 | 占位页改成用户话术 | 原占位页直接打印 HTML 原型文件名（内部资料名露出）。改为三句话说明「它没坏、点得动」+ 做好后能做什么 + 「去用检查问题」直达按钮。 |
| 3 | 顶栏三个按钮接上真实功能 | 骨架里 ☰ / ? / ⚙ 三个 `_top_action` 是 `pass` 空实现（点了没反应）。现在分别是「想去哪」菜单、三步使用说明、设置说明。 |
| 4 | 顶栏加「当前位置」 | 切换入口时顶栏同步显示 `图标 + 入口名`，用户随时知道自己在哪。 |
| 5 | 品牌名改为可聚焦按钮 | 原来是 `QLabel + mousePressEvent`，键盘 Tab 到不了。改成 `QPushButton`，可 Tab 聚焦、Enter 触发回首页。 |
| 6 | 加入键盘快捷方式 | `Ctrl+1~6` 直达六个入口，`Ctrl+H` 回首页。 |
| 7 | 窗口尺寸按内容反推 | 默认 1280×820、最小 1220×700，实测 1220/1280/1400 三档宽度下六个页面均无横向滚动条（不裁切、不挤压）。 |
| 8 | 检查问题页副标题去术语 | 原文带「（§2.2 入口③ 验收②）」这类排期文档内部编号，改成用户能读懂的描述。 |

## 二、目录结构

```
FixText_M2-T2.1_qt_ui/
├── fixtext_ui/                 可直接运行的 Qt 界面包
│   ├── main_window.py          主窗口：左轨 + 顶栏 + QStackedWidget 路由
│   ├── fixtext_tokens.py       令牌单一来源（71 项）+ 六入口定义（ENTRIES）
│   ├── build_qss.py            令牌 -> fixtext.qss 生成器
│   ├── fixtext.qss             由上面生成，勿手改
│   ├── fixtext_widgets.py      通用控件（Card / Pill / Switch / FieldRow）
│   └── check_module.py         检查问题模块（已验收移植版，本卡未改业务逻辑）
├── screenshots/                七个页面离屏截图（验收④证据）
│   ├── 01_home_overview.png    首页概览（无轨选中）
│   ├── 02_entry1_import.png    导入书籍（建设中）
│   ├── 03_entry2_oneclick.png  一键校正（建设中）
│   ├── 04_entry3_check.png     检查问题（可用，真实模块）
│   ├── 05_entry4_vocab.png     词库管理（建设中）
│   ├── 06_entry5_export.png    导出结果（建设中）
│   └── 07_entry6_history.png   历史记录（建设中）
├── tools/
│   └── verify_m2t21.py         四项验收自检脚本（见下）
├── reference/
│   └── design_root_snapshot.css  设计地基 :root 原样快照（MD5 6faf81eeb24e592a906cb22caf3977e4）
├── verify_report.json          最近一次自检的机器可读结果
└── README.md
```

## 三、怎么跑

```bash
pip install PySide6==6.11.2
cd FixText_M2-T2.1_qt_ui
python fixtext_ui/main_window.py
```

自检（离屏，无需显示器）：

```bash
cd FixText_M2-T2.1_qt_ui
QT_QPA_PLATFORM=offscreen python tools/verify_m2t21.py
# 退出码 0 = 四项全通过；同时刷新 screenshots/ 与 verify_report.json
```

## 四、四项验收怎么对应

| 验收标准 | 脚本里的检查 | 判定条件 |
|---|---|---|
| ① 六入口可达且状态清晰 | `1_entries_reachable` / `1b` / `1c` / `1d` / `1e` | 对左轨控件发**真实鼠标点击**（不是直接调 `go()`），逐个断言：stack 当前页是它、选中态有且仅有它、顶栏位置跟随、"建设中"标签与入口状态一致、页面可见且有尺寸；再验 Ctrl+1~6 / Ctrl+H、占位页直达按钮、顶栏三个按钮各自弹出真窗口 |
| ② 内部目录概念零露出 | `2_zero_internal_leak` | 扫控件树里所有可见字符串（text / tooltip / accessibleName / accessibleDescription / placeholder / windowTitle）+ 源码中文文案字面量，共 543 条，对 25 条禁用模式（books / booksBak / booksFix / spine / OPF / NCX / manifest / rules.json / 内部路径 / 内部标识符等）零命中 |
| ③ 令牌值与设计地基一致 | `3_tokens_aligned` | `fixtext_tokens.py` 展开 71 项，与设计地基 `:root` 逐项比对：颜色 34、字号 9、字重 4、行高 3、间距 10、圆角 5、阴影 4 + 2 字体族，差异 0 / 缺失 0 / 多余 0 |
| ④ 主窗口可构造 + 六页截图 | `4_construct_and_screenshots` | 走真实构造路径建窗口，七个页面各截一张 PNG，全部落盘且非空 |

补充：`1b_route_keeps_state` 验证「切换不丢状态、不重建窗口」——在检查问题里修一处引号，
切到词库管理再切回，断言取到的是**同一个控件实例**、修复状态仍在、全程窗口数始终为 1。

## 五、已知遗留（分级见任务评论）

- 五个占位入口尚未接后端引擎（M3/M4 卡范围）。
- 检查问题页内容较高（1319px），窗口变高前需在内容区竖向滚动，属预期行为。
- 顶栏 ☰ 菜单目前只有两项（回首页 / 关于），等模块补齐后再扩。
