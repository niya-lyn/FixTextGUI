# FixText T0.2 · 词库 JSON 迁移工具链

把 FixText 的 PHP 数组词库迁移为正式 JSON 词库，并提供可一键重跑的迁移流程。
本工具链由 P0 前置验证包（`export_maps.php` / `validate_migration.py` / `flatten_export.php` /
`roundtrip_check.php` / `build_rules.py`）演进而来，在其基础上补齐了三件 P0 未做的事：

1. **PHP 闭包显式检测与报警**（P0 只观察到闭包导致 42/43，未在工具链里检测与留痕）
2. **strictMap 瑕疵的数据清洗**（P0 记录了瑕疵，未清洗）
3. **一键重跑入口 + 产物装配 + 自验报告**

---

## 一、环境要求

| 依赖 | 版本 | 说明 |
| --- | --- | --- |
| PHP | 8.x（本次实测 8.5.8） | 词库是 PHP 数组，**必须由 PHP 加载**才能拿到权威值；PHP 版本不同不影响词库内容，但建议与 P0 一致 |
| Python | 3.8+ | 仅用标准库，无第三方依赖 |
| Bash | 4+ | 入口脚本 |

> P0 报告的口径基线是在 PHP 8.5.8 下取得的，本工具链同样使用 8.5.8 复现，结论可 1:1 对齐。

## 二、一键重跑

```bash
cd toolchain

# 方式一：包内自带源码与默认输出目录
./run_migration.sh

# 方式二：显式指定词库源码目录与输出目录
./run_migration.sh --src /path/to/FixText/src --out /path/to/out

# 方式三：指定 PHP 可执行文件，并先清空输出目录
./run_migration.sh --php /usr/bin/php8.3 --clean
```

参数：

| 参数 | 说明 |
| --- | --- |
| `--src <dir>` | FixText 源码中的 `src` 目录（需含 `maps/` 与 `config/`；步骤 7 还需 `vendor/autoload.php`） |
| `--out <dir>` | 输出目录，默认 `toolchain/../build` |
| `--php <path>` | PHP 可执行文件，默认按「`config/paths.env` → PATH 中的 php → 常见安装路径」顺序探测 |
| `--clean` | 先删除输出目录再跑，保证是从零复现 |

退出码：`0` = 9 步全部完成；非 `0` = 某步失败，原因见 `<out>/logs/migration.log`。
步骤 5（闭包静态扫描）发现闭包时返回 `3`，属于**预期告警**而非失败，入口脚本已单独处理。

## 三、流程步骤

| # | 脚本 | 作用 | 产物 |
| --- | --- | --- | --- |
| 1 | `scripts/01_export_maps.php` | `include` 13 个词库文件，收集 `get_defined_vars()` 逐变量导出；**导出前做运行时闭包扫描**，命中闭包的变量拒绝导出并报警 | `exported/*.json`、`exported/__meta__.json` |
| 2 | `scripts/02_flatten_export.php` | PHP 侧按 `Map.php` 语义（`flattenWord` / `processReplaceHolder`）展开词条型变量 | `flattened/flat_*.json` |
| 3 | `scripts/03_roundtrip_check.php` | 重新 `include` 原文件取原值 → `json_decode` 导出文件 → 严格 `===` 比对 | `reports/roundtrip_result.json` |
| 4 | `scripts/04_validate_migration.py` | Python 镜像实现与 PHP 展开结果**逐条全量**比对；同时做 JSON 回读、条目数、结构校验 | `reports/validation1_result.json` |
| 5 | `scripts/05_detect_closure_static.php` | `token_get_all` 扫描 `src/maps` + `src/config` 的匿名函数 / 箭头函数，报警留痕 | `reports/closure_report.json` |
| 6 | `scripts/06_clean_and_flatten.php` | **strictMap 数据清洗**（把 `before` 里的 `mark` 键提升为词条级 `mark`）+ 清洗后重新展开 | `dictionary/cleaned/*.json`、`dictionary/flat/flat_*.json`、`reports/cleaning_report.json` |
| 7 | `scripts/07_export_manual_rules.php` | 手动检索规则表迁移（扩展单元 B）；`replace` 为闭包的规则**显式标注**、不静默降级 | `manual/manual_regex_rules.json`、`manual/manual_rules_closure_manifest.json` |
| 8 | `scripts/08_build_dict.py` | 装配正式 JSON 词库产物 + 合并规则集（Go 生产顺序）+ 清洗后二次全量比对 | `dictionary/`、`reports/build_report.json` |
| 9 | `scripts/09_make_report.py` | 汇总本次运行产物生成迁移报告（数字不手写） | `迁移报告.md` |

## 四、输出目录结构

```
<out>/
├── 迁移报告.md                    # 本次运行的迁移报告（口径对照、清洗明细、闭包报警）
├── dictionary/                    # ★ 正式 JSON 词库产物
│   ├── index.json                 #   迁移总清单
│   ├── cleaned/*.json             #   清洗后的词库原始变量（PHP 权威）
│   ├── flat/flat_*.json           #   清洗后展开的词条（PHP 权威）
│   ├── rules/before.json          #   替换规则对（引擎接入用）
│   ├── rules/after.json
│   ├── rules/rules_full.json      #   含 mark / replaceHolder 的完整规则
│   ├── rules/rules_meta.json      #   规则统计 + 清洗前后差异
│   └── manual/                    #   手动检索正则规则 + 闭包清单
├── exported/  flattened/          # P0 口径基线中间产物（未清洗）
├── manual/                        # 步骤 7 原始输出
├── reports/                       # 各步骤机器可读结果
└── logs/
    ├── migration.log              # 全流程运行日志
    └── closure_alarm.log          # ★ 闭包报警留痕
```

## 五、闭包检测与报警机制

**为什么必须显式检测**：`json_encode()` 遇到 `Closure` 会**静默降级**为 `{}` —— 不报错、不抛异常，
闭包在 JSON 迁移中无声丢失。排期文档 3.5 门禁 (c) 明确禁止这种静默降级。

**两层检测**（`lib/closure_guard.php`）：

| 层 | 实现 | 能发现什么 |
| --- | --- | --- |
| 运行时层 | `closure_scan_runtime()` 递归遍历已加载变量 | 已加载词库中的 `Closure` 实例，给出 JSON 路径（如 `$[noteBrandProcessors][moonreader]`）与源码行号 |
| 源码层 | `closure_scan_static()` 用 `token_get_all` 扫描 `src/maps` + `src/config` | 源码里的匿名函数 `function (...) {}` 与箭头函数 `fn (...) =>`，含行号；能发现因依赖问题无法 `include` 的文件 |

**处置策略**：

- 命中闭包的变量 / 规则：**拒绝 JSON 化**，`replace_kind=php_closure` 显式标注，
  在 `*_closure_manifest.json` 里列出规则序号、源码行号、`search` 模式，交由引擎侧重写；
- 每次命中写一条 `ALARM[PHP-CLOSURE]` 到 `logs/closure_alarm.log`（时间戳、来源、路径、行号、处置动作）。

## 六、strictMap 数据清洗规则

**瑕疵形态**：`mark` 被写成 `before` 数组的一个**键**，而不是词条级的**值**：

```php
['before' => ["悬殊太大", "过于悬殊", "很悬殊", "非常悬殊", "十分悬殊",
              'mark' => "{处理“悬殊”的问题}"], 'after' => "差距太大"],
```

**后果**（`Map.php` 语义）：`flattenWord` 走 `foreach ($word['before'] as $before)`，键被忽略 →
mark 字符串被当成一个 before 取值，生成一条**伪规则**；同时 `createWord` 只在
`isset($word['mark'])` 时写 mark 键 → 词条级 mark 丢失。

**清洗动作**（只改数据，不改 PHP 源码，按排期 3.5 门禁 (b) 不作代码缺陷处理）：
把 `before` 数组里的 `mark` 键提升为词条级 `mark` 字段，并从 `before` 移除该键。

清洗后伪规则消失、词条级 mark 恢复，**规则总数因此减少**（差异已在迁移报告中逐条列明）。

## 七、已知边界

- 步骤 6 的清洗**只针对 `before` 数组中出现字符串键 `mark`** 的词条；`regexMap` 等非词条型变量不受影响。
- 步骤 7 需要 `vendor/autoload.php` 与 `SCRIPT_DIR`（手动检索规则表依赖 `App\Service\PatternFileLoader`）。
- 规则集已按 Go 生产顺序产出，但**本工具链不做引擎接入、不做替换行为验证**（属 T0.3），
  也**不构造回归基线集**（属 T0.4）。
