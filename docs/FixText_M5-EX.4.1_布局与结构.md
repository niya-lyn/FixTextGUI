# FixText M5-EX.4.1 · UI 对齐布局与结构（SYNC-1～3）

## 目标

落地待办 P1「布局与结构」三项；功能逻辑不动。

| ID | 做法 |
|---|---|
| SYNC-1 | 导出：`开始导出` 置顶 → 结果槽 → 目标/元数据/目录 → 状态 |
| SYNC-2 | 导入：安全说明移到书架后（参考区置底） |
| SYNC-3 | 导入：去掉独立 `EmptyState`；无书时书架卡弱提示 |

## 改动

- `fixtext_ui/export_module.py`
- `fixtext_ui/import_module.py`
- `tests/test_m5_ex4_1_layout.py`

## 自测

```bash
python -m pytest tests/test_m5_ex4_1_layout.py -q
```
