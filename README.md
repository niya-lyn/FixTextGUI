# FixText 引号检查 · Python 重实现（M1-T1.4）

以 FixText（PHP）`src/app/Service/Quotation/QuotationChecker.php` 检测逻辑为准的独立 Python 模块，
提供中文单双引号检查（配对、嵌套、跨行闭合等检测与报告），供编排器调用。

## 模块结构

```
fixtext_quotation/            # 可导入的 Python 包
├── checker.py                # 核心检测逻辑（对齐 PHP QuotationChecker 检测部分）
├── report.py                 # 报告渲染（人类可读 / JSON）
└── cli.py + __main__.py      # 命令行入口
tests/test_quotation_checker.py   # 38 个单元测试（断言值取自 PHP 原版实际输出）
equivalence/
├── php_harness.php           # PHP 原版参照装备（驱动未修改的 QuotationChecker.php）
├── run_equivalence.py        # 一键等价比对（PHP vs Python）
└── results/                  # 比对结果：php/py 事件流 + comparison_report.md
```

## 用法

```python
from fixtext_quotation import check_file, check_text

errors = check_file("book.txt")      # 或 check_text("“未闭合\n……")
for e in errors:
    print(e.line, e.char, e.msg)    # 行号(1 起)、行内字符下标、报错文案
```

```bash
python -m fixtext_quotation check a.txt b.txt [--json] [--out 报告目录]
```

## 与 PHP 原版的对齐口径

- 对齐原命令 `check-quotation-marks` 统计模式（'c'：只统计错误数）的单遍全文件扫描语义：
  错误总数 == 单遍扫描中 dumpErr 调用次数；每处报错跳过当前行、行状态复位、继续下一行。
- 检测规则逐条对齐，包括：引号配对四类错误、同向嵌套拦截（双套双/单套单）、
  行尾跨行探测（SEARCH_FOR_RD_LINES=100、空行跳过、段首左引号前置字符合法集、
  隔行风格校验）、英文弯撇号过滤（两侧均为字母/数字/空格）、
  以及原版在文件末尾处经 `min(prevNextLineKey, lineCount-1)` 回卷重复探测最后一行的行为。
- 报错文案与 PHP 原版逐字一致。
- 未实现部分：原工具的交互式人工修复链（QuotationFixer::autoFix* 依赖人工确认选项，
  不属于“检查与报告”范围）与 `fixSingles`（把双引号外单引号规范为双引号，属修复功能）。

## 等价性结论

对 T0.4 回归基线集 15 份语料（23.3MB，含 7680 处错误的《紅樓夢》），PHP 原版
（未修改检测逻辑，经 `equivalence/php_harness.php` 驱动）与 Python 实现的事件流
（行号 + 行内字符下标 + 报错文案）**逐条完全一致：15/15 通过**。
另在 26 个针对性构造用例上同样逐条一致（单元测试断言即取自该批 PHP 实际输出）。
详见 `equivalence/results/comparison_report.md`。

复跑等价比对（需本机有 FixText 源码与 PHP ≥ 8）：

```bash
python3 equivalence/run_equivalence.py \
  --fixtext-src /path/to/FixText/src \
  --corpus /path/to/corpus \
  --php php
```

## 依赖

Python ≥ 3.10，无第三方依赖（测试用 pytest）。
