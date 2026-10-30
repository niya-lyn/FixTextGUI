# FixText M5-EX.7 · UI 对齐（无功能改动）

## 范围

对照合并版原型 + 更新记录 **§10 样式打磨**，只做观感收口；不改业务逻辑。

| Step | 本轮 |
|---|---|
| 1–2 令牌 / 硬编码色 | ✅ Qt 侧落地 |
| 3 图标 emoji→SVG | ⏭ 跳过 |
| 4 page-head / hero / chk-top | ✅ |
| 5–6 交互三态 + 禁用语言 | ✅ |
| 7 空状态视觉 | ✅ |
| 8 暗色模式 | ⏭ 跳过 |
| 额外 | 顶栏 BookChip 无书态去掉半透明 wash |

## 本轮做了什么

| 项 | 做法 |
|---|---|
| BookChip 无书 | 去掉 `#BookChip[empty]` wash；无书/有书同一玻璃底；仅弱化文字/圆点 |
| Step 1–2 | 新增 `on.fill`；业务内联 `#fff` → `c('neutral.0')` / `c('on.fill')` |
| Step 4 | `#PageHead` 底部分隔；校正/检查/导出主操作横幅同规（padding 26×28、大按钮 16×34） |
| Step 5–6 | 按钮补 pressed；禁用 `opacity:0.5` + `not-allowed` |
| Step 7 | EmptyState：dashed `neutral.200`、图标环 primary-50 6px、标题 semibold、说明 `fs-sm` |

主要文件：`build_qss.py`、`fixtext.qss`、`fixtext_tokens.py`、`fixtext_shelf_ui.py`、`fixtext_widgets.py`、`oneclick_module.py`、`check_module.py`、`export_module.py`、各页 `PageHead`。

## 本轮跳过

| 项 | 原因 |
|---|---|
| Step 3 | SVG 雪碧图基建大，易碰交互面 |
| Step 8 | 暗色模式整包主题反转，不在本轮 |

## 自测

```text
python fixtext_ui/build_qss.py
pytest tests/test_ex3a_shelf.py tests/test_ex2b_empty_states.py -q
```
