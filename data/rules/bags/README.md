# 内置词库分袋（bags）· M5-EX.1

卡片：**M5-EX.1 运行模式优化**（非 M4）。  
工程目录：`FixText_M5-EX.1_运行模式优化_源码`。  
由 `tools/split_rule_bags.py` 从 T0.2 flat + 全量 `before/after.json` 生成。  
约束：不改全量规则 SHA；归属闭合 304,255；详见上级 `FixText_M5-EX.1_运行模式优化.md`。

## 约定

| 袋 id | 组合勾选 | 说明 |
|---|---|---|
| `normal` | **锁定必选** | PHP `normalMap` |
| `preprocess` | 可选，默认关 | PHP 预处理；勿与「跳过排版」混淆 |
| `strict` | **不进组合**，严格开关 | PHP `strictMap` |
| `zhuyin` | **不进组合**，注音开关 | `shengpiziMap` + `cjkExtMap` |
| 其余 | 可选 | 见 `manifest.json` |

- `builtin_bags.bin`：与全量 `before.json` **同序**，每条 1 字节袋码（见 manifest `code_map`）。
- 全量 `data/rules/before.json` / `after.json` **未改**，旧链路仍可用。
