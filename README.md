# FixText T1.6 · PHP 闭包重实现（noteBrandProcessors Python 等价模块）

## 是什么

`FixText/src/config/general.php` 中 `noteBrandProcessors` 含 3 处 PHP 闭包，T0.2 词库迁移时因
`json_encode` 对 Closure 静默降级为 `{}` 而无法导出（词库 JSON 已显式标记）。本包用 Python
重实现这 3 处闭包，作为词库处理的**可选增强模块**：

| brand | PHP 源码位置 | Python 函数 | 功能 |
| --- | --- | --- | --- |
| moonreader | general.php L1086 | `process_moonreader` | 把划线文本尾部 ` (批注)` 拆出 |
| calibre | general.php L1095 | `process_calibre` | 删划线文本中的 Markdown 标题行与 BOM |
| weread | general.php L1102 | `process_weread` | "发表想法"交换原文/想法、纯划线去 `◆ `、整体倒序 |

## 目录结构

```
note_brand_processors.py      # 本卡核心交付：3 处闭包的 Python 重实现（含逐行 PHP 对照注释）
py_note_parser.py             # 参照 NoteParser.php 的解析管线（normalize/extract/clean），用于验证与接入
note_brand_processors_manifest.json  # 闭包清单（对齐 T0.2 closure manifest 惯例）
tests/
  test_note_brand_processors.py     # 21 条单元测试（pytest，不依赖 PHP）
  fixtures/                          # 10 份构造语料（三品牌 basic/edge + 对照 + 混合）
compare/
  php_note_harness.php        # PHP 权威对照探针（复用 T0.2 的 PHP 环境，三阶段 JSON 输出）
  run_compare.py              # PHP vs Python 全量对比驱动（fixtures + 15 语料 + 45 混合语料）
  gen_hybrid_corpus.py        # 混合语料生成器（T0.4 语料 × 3 品牌批注块）
  probe_backtrack.php         # PCRE 回溯上限实证探针（9 处相异差异的根因证据）
  report/
    compare_report.json        # 70 项对比明细（61 一致 / 9 相异，见对比结论）
    对比结论.md                # 验收结论与逐条差异说明
```

## 用法

```python
from note_brand_processors import NOTE_BRAND_PROCESSORS

processor = NOTE_BRAND_PROCESSORS.get(brand)   # brand ∈ {moonreader, calibre, weread}
if processor:
    processor(matches)   # 原地修改，等价 PHP function (array &$matches)
```

`matches` 行结构与 PHP `preg_match_all(PREG_SET_ORDER)` 一致：
`match[0]`=整体匹配、`match[1]`=分组1（划线/before）、`match[2]`=分组2（批注/after，缺失用 None，序列化时按 PHP 缺键剥除）。

## PHP ↔ Python 逐条对应

`note_brand_processors.py` 每个函数头部内嵌对应 PHP 闭包原文与逐行语义注释。关键对齐规则：

- **修饰符**：PHP `/ums` → `re.M | re.S`；`u`（非 UCP）下 `\d` 仅 ASCII → 统一写 `[0-9]`（Python `\d` 会多匹配全角数字，必须显式收窄）
- **trim**：`trim($s, ' ()')` ≡ `str.strip(' ()')`（字符集剥两端）
- **str_replace / preg_replace**：`str.replace` / `re.sub`（全局）
- **缺键语义**：PHP 数组缺键 ≡ Python None；`$match[2] = x` 对缺失下标的自动扩展用 `_set` 补 None 实现
- **引用传参**：`array &$matches` ≡ 三个函数全部原地修改；weread 末尾 `$matches = array_reverse($matches)` 用 `matches.reverse()` 实现调用方可见的重绑定
- **`$ret[1] ?? ''`**：weread 内层 `preg_match` 失败时 PHP 空数组取 null 合并空串 ≡ Python `if m else ""`

## 验证结论（详见 compare/report/对比结论.md）

- 10 份构造语料三阶段（原始匹配→闭包处理后→清洗后）逐字段深比对：**10/10 一致**
- 15 份 T0.4 原始语料：双方均"未找到匹配的批注内容"，**15/15 一致**
- 45 份混合语料（真实语料全文 + 3 品牌批注块）：**36/45 一致**；9 处相异全部为
  `calibre__*` ≥1.6MB 大文件，根因是 PHP PCRE `pcre.backtrack_limit=1000000` 回溯耗尽导致
  `preg_match_all` 返回 false（PHP 侧直接无匹配并抛异常，闭包根本未执行），Python `re` 无
  回溯上限可正常完成匹配。属于正则引擎资源限制差异，非闭包逻辑差异；在 PHP 引擎能完成
  匹配的全部案例（含 6 个 calibre 大语料 + 15 moonreader + 15 weread 混合语料）上三阶段
  sha256 完全一致。

## 运行测试

```bash
python3 -m pytest -q tests/test_note_brand_processors.py   # 21 passed，无需 PHP
```

PHP 对照复现（需 FixText 源码与 PHP CLI，T0.2 已确认本仓库沙箱含 php 8.5）：

```bash
python3 compare/gen_hybrid_corpus.py --corpus <T0.4语料目录> --out <混合语料目录>
python3 compare/run_compare.py --src <FixText/src> --fixtures tests/fixtures \
    --corpus <T0.4语料目录> --corpus-hybrid <混合语料目录>
php compare/probe_backtrack.php <任一相异的calibre混合文件> <FixText/src>   # 根因复现
```
