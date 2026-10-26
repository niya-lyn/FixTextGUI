# fixtext_layout — FixText 排版功能引擎（Python 复刻）

FixText（PHP）排版功能的独立 Python 模块，供 T1.1 一键校正编排器调用。
规则权威来源为 FixText PHP 源码，已在 81 条差分用例 + 20 份语料上与 PHP
逐字节对照一致（详见 `docs/等价性对比报告.md`）。

## 快速上手

```python
from fixtext_layout import format_text
from fixtext_layout.options import LayoutOptions

options = LayoutOptions(
    change_text_format=True,       # 空白清理/缩进/章节分隔（PHP: changeTextFormat）
    normalize_punctuations=True,   # 标点规范化（113 映射 + 44 pattern）
    format_headings=True,          # ◎ 标题分级（PHP: formatHeadings）
    paranoid_text_spacing=True,    # 中英文间空格（Util::pangu）
)
result = format_text('正文内容……', options)
```

或使用引擎对象：

```python
from fixtext_layout.engine import LayoutEngine
from fixtext_layout.options import LayoutOptions

engine = LayoutEngine(LayoutOptions(change_text_format=True))
result = engine.format('第一章 起点\n正文\n')
```

选项字段与 PHP `App\Service\Formatting\Option` 一一对应（snake_case 命名），
默认值一致；字段清单见 `fixtext_layout/options.py` 的 docstring。

## 模块结构

- `fixtext_layout/options.py` — 排版选项（对应 PHP Option）
- `fixtext_layout/rules_data.py` — 从 PHP 源码导出的规则数据（映射表与 pattern）
- `fixtext_layout/php_compat.py` — PHP/PCRE 兼容层（trim/strtr/html_entity_decode/
  strip_tags/preg_replace 语义、多行锚点翻译）
- `fixtext_layout/engine.py` — 排版引擎（对应 PHP FileProcessor 排版 actions）
- `fixtext_layout/width.py` — 【扩展】东亚文字宽度库（非 PHP 复刻）
- `fixtext_layout/kinsoku.py` — 【扩展】标点禁排与挤压（非 PHP 复刻）

### 扩展功能（默认不参与 format 流水线）

```python
from fixtext_layout.width import text_width
from fixtext_layout.kinsoku import wrap_text

text_width('中文abc')            # 7 —— 显示宽度（全角 2、半角 1、组合附标 0）
wrap_text('一二三四五六七八九十。', 10)  # 按禁排规则断行并挤压行尾标点
```

## 测试

```bash
cd fixtext_layout
python3 -m unittest discover -s tests   # 97 个测试（含 41 条 PHP 黄金用例）
```

`tests/golden.json` 的 expected 全部来自 FixText PHP 源码真实运行输出，
测试离线可跑、不依赖 PHP 环境。

## 对照工具（开发用）

```bash
python3 tools/diff_check.py          # 81 条差分用例（需 PHP）
python3 tools/corpus_compare.py      # 15 份语料 changeTextFormat 对照（需 PHP）
python3 tools/corpus_compare_full.py  # 5 份大语料全流水线对照（需 PHP）
```

## 依赖

仅 Python 3 标准库（`re` / `unicodedata` / `json` / `dataclasses`），零第三方依赖。
