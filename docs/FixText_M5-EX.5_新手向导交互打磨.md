# FixText M5-EX.5 · 新手向导交互打磨

## 范围

1. 去掉短操作时整页忙碌重绘带来的「提示块/进度条一闪而过」
2. 「返回上一步」文案简化为「上一步」
3. 点「上一步」后，当前页主按钮为「下一步」，直接回到离开前的那一步（不重跑业务；原主操作保留为次按钮）
4. ☰「新手向导（重新观看）」一律从第 1 步开始（撤销「有当前书则跳第 2 步」）

## 改动

- `fixtext_ui/first_run_wizard.py`
- `fixtext_ui/main_window.py`
- `tests/test_first_run_wizard.py`
- `tools/accept_ex2c.py`（S5 口径）
