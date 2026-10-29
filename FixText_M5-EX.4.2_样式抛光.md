# FixText M5-EX.4.2 · UI 样式抛光（P2 · 只改观感）

## 目标

推进待办 P2 中可纯样式落地的 BUG-1a～e（及词库工具条高度）；不改业务逻辑。

## 本轮做了什么

| ID | 做法 |
|---|---|
| BUG-1a | `#BookChip` 玻璃胶囊渐变 / hover 边框 / empty 对比度；`#BcGo` 左边线 + hover 主色 |
| BUG-1b | `#BtnSetCurrent:hover/pressed` 主色实底 + 白字 |
| BUG-1c | 全局 `QComboBox` 聚焦环 / hover / 下拉列表选中态；校正下拉 `FmtCombo` 对象名 |
| BUG-1d / BUG-8 | 词库 `_toolbar` `Maximum` 竖向 + workspace stretch：工具条不拉伸、表格吃剩余 |
| BUG-1e | `#HeadIconBtn` / `#SafeBadge` 统一走 `fixtext.qss`（去掉内联冲突样式） |

主要文件：`fixtext_ui/fixtext.qss`、`vocab_module.py`、`oneclick_module.py`。

## 本轮跳过

| ID | 原因 |
|---|---|
| BUG-6 | 检查页快捷变换/插引号是**产品去留**，非样式；待产品确认后再动 |
| BUG-7（全域） | 「整体对齐设计系统」面过大；本轮仅通过 1a～1e 局部贴原型，**不全量**铺卡片阴影/顶栏渐变/级联动画，余量下期 |
| P2-8 | `resume=False` 属**功能/产品确认**，非样式；维持待产品确认 |

## 自测

本机无 PySide6 → **跳过 GUI 目视**，仅提交样式 / SizePolicy diff。
