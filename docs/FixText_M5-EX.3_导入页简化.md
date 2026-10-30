# FixText M5-EX.3 · 导入页简化（去向导 + 统一可逆）

## 目标

导出页已可选 TXT / 还原 EPUB；导入时再选「直接处理 / 先转 TXT」多余。  
去掉导入向导整块 UI，EPUB 一律可逆合并（保留章节映射账本）。

## 口径

| 项 | 做法 |
|---|---|
| UI | 移除导入向导（步骤点 / 处理方式 / 章节预览 / 上下一步） |
| 交互 | 拖放或选文件 → 直接导入（进度 + 可取消 → 结果摘要） |
| 功能 | EPUB 固定 `merge_reversible`；导出能力不变 |
| 文案 | 不跟原型同步 |

## 改动文件

- `fixtext_import/importer.py` — EPUB 只走可逆；忽略 `epub_mode=text`
- `fixtext_ui/import_module.py` — 去向导；`take_file` 即开跑
- `fixtext_ui/first_run_wizard.py` — 去掉代点步骤机
- 冒烟 / 验收脚本：`smoke_e2e` / `fxbundle_smoke` / `accept_ex2c` / `accept_t210` / `accept_t34` / `accept_t35`
- 测试：`tests/test_import.py` / `test_m5_ex3_import.py` / `test_no_jargon.py`

## 定向自测

```bash
python -m pytest tests/test_import.py tests/test_m5_ex3_import.py -q
```

期望：EPUB 默认有 `ledger_path`；传入 `epub_mode=text` 仍为 `direct` + 账本；TXT 仍通。
