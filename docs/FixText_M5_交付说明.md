# FixText M5 · 交付说明（整理时点）

- **基线**：M4 收口 `f2565e1`（包在 `../M4_产品化收口/FixText_M4收尾_*.zip`）
- **工程目录**：`../FixText_M5-EX.1_运行模式优化_源码`（活跃 git；本目录只放卡说明）
- **当前 HEAD**：`3cacd5e`

## 已完成卡片

| 卡 | 说明文件 | 代表提交 |
|---|---|---|
| M5-EX.1 | `FixText_M5-EX.1_运行模式优化.md` | `e085265` |
| M5-EX.2 | `FixText_M5-EX.2_修复bug.md` | `fc53355`…`b3ed11b` |
| M5-EX.3 | `FixText_M5-EX.3_导入页简化.md` | `9008b53` |
| M5-EX.4.1 | `FixText_M5-EX.4.1_布局与结构.md` | `f692781` |
| M5-EX.4.2 | `FixText_M5-EX.4.2_样式抛光.md` | `3c16c0c` + `3cacd5e` |

## 合并口径

延续 M4：单卡 cherry-pick / 普通提交叠 master；双线才 merge。M5 未新开旁路树。

## 未打 zip

本阶段以工作树 + 短卡为准；需要整包时再从工作树打 `FixText_M5-EX.*_源码.zip`（不回写 M4 收尾包）。
