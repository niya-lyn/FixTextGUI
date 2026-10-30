# FixText M5-EX.6 · 设置页「初始化」

## 范围

在设置页增加「初始化」按钮：二次确认后强制清理全部运行产物，界面回到刚装好时的空状态。

## 清理

- `workspace/`（书、词库工作副本、settings.ini）
- `runs/`、`logs/`、包根 `导出/`
- 设置文件（含引擎 / 向导已看过等键）→ 默认值

不动：出厂词库 `data/rules`、引擎与源码。

## 改动

- `fixtext_ui/fixtext_factory_reset.py`（新建）
- `fixtext_ui/settings_module.py`
- `fixtext_ui/main_window.py`
- `tests/test_settings_module.py`

## 补丁：初始化后向导导出仍用旧书名

根因：导出页 `title_edit` 在无书 / 换书时未重绑，初始化清盘后内存里仍留着
「我的玩家二周目」，向导导入「炮火弧线」再导出时文件名仍用旧名。

- `fixtext_ui/export_module.py`：按正文路径绑定元信息；无书清空；换书重填
- `tests/test_export_meta_rebind.py`
