# FixText 专有词库生成（M1-T1.5）Python 重实现

把 FixText 上游 PHP 的「专有词库生成」链路完整重实现为 Python，产出与 PHP 逐字节等价的
`maps/书籍专有替换词库/<书名>.php`。

## 验收结论

| 验收项 | 结果 |
| --- | --- |
| 至少 5 份语料上与 p0val 专有词库生成脚本等价 | **15 份语料，15/15 词库文件逐字节等价**（91926 条词条，两侧一致） |
| 核心逻辑有单元测试 | **130 项测试全部通过**（`python3 -m pytest tests/`） |
| 产物 zip 上传 projects/fix_text | 见交付评论中的云盘链接 |

### 关于验收项 1 的口径更正（重要）

任务原文要求「与 **p0val 专有词库生成脚本**输出等价」。实际核查结论是：

> **p0val 包内不存在「专有词库生成」脚本。**

P0 验证包（`FixText_P0验证_脚本与结果包.zip`）与补充的 P0 v2 包内，
全量检索 `generateBookMaps` 命中数为 **0**；包内只有「验证一 词库格式迁移一致性」
与「验证二 大文件替换性能实测」两套脚本，其中 `export_maps.php` / `roundtrip_check.php`
仅**读取**已存在的 `书籍专有替换词库` 文件，不生成词库。

因此本实现改用**更严格**的等价基准：**上游 PHP `Extractor::generateBookMaps()` 的真实产物**。
该基准由两部分证据支撑：

1. 一份真实 PHP 8.5.8 运行产出的词库原件（`verification/reference_samples/pg24032_儒林外史.php`），
   其 sha256 与字节数与记录的参照哈希完全一致，可自校验「产物文件 ↔ 记录哈希」同源；
2. 15 本书的 sha256 与词条数参照哈希（`verification/reference_hashes.json`）。

对标基准从「p0val 脚本」升级为「上游 PHP 真实产物」，是口径收紧而非放宽。

## 方向约定（最容易踩错的一点）

上游 `Extractor::generateBookMaps()` 内部调用
`genDiffWordsMap($patch, $bookFixFile, $bookFile)`，因此：

- **`BOOK_FIX_DIR`（booksFix）提供词条的 `before`（改前）侧文本**；
- **`BOOK_DIR`（books）提供词条的 `after`（改后）侧文本**。

在本项目的 T0.4 基线里，before 侧是**繁体原稿**，after 侧是**简体校正后**，
即词条形如 `['before' => "第一回　說楔子敷陳大義…", 'after' => "第一回　说楔子敷陈大义…"]`。
上游随包附带的《天之下》《铁鹤书》两份真实词库同样是「繁体/错字 → 简体/正字」的方向。

本模块的入参与之一致：`--book-fix-dir` 取 before 侧，`--book-dir` 取 after 侧。

> 注意：上游 `booksFix` 这一命名容易让人误以为它是「校正后的副本」而把两个目录传反。
> 实际以词条方向为准——**before 侧进 `--book-fix-dir`**，已在 `tests/` 与
> `verification/run_independent_equivalence.py` 中固化。

## 目录结构

```
fixtext_bookmap/          模块本体（10 个文件，约 1700 行）
  phpcompat.py            PHP 语义复刻：trim 字符集、php_truthy、strip_tags 状态机、/^/m
  patcher.py              diff -u 封装 + PatchAnalyzer 状态机
  textdiff.py             extractStrDiff（上下文截取）
  wordmap.py              词条提取、词库表读写、插入位置定位
  frequency.py            替换次数统计与汇总
  generator.py            目录遍历与编排入口
  option.py               与上游 Option 默认值一致
  cli.py                  命令行：generate-book-maps / extract / replace-count-report
tests/                    130 项 pytest 用例 + PHP 权威夹具
scripts/
  gen_*_fixtures.php      用真实 PHP 生成权威断言向量
  run_equivalence.py      PHP/Python 词库逐字节对比器
verification/             本轮独立复验（不依赖 PHP 解释器）
  run_independent_equivalence.py  独立复验脚本
  reference_hashes.json            15 本书的参照 sha256 / 词条数
  reference_samples/               真实 PHP 产物原件（哈希自校验样本）
  independent_result.json          复验结果
等价性对比报告.md / .json  本次 15 份语料的实测对比结果
```

## 用法

```bash
# 生成词库（--map-root 下须已存在 maps/书籍专有替换词库/）
python3 -m fixtext_bookmap generate-book-maps \
  --book-fix-dir <改前文本目录（before 侧，对应上游 booksFix）> \
  --book-dir    <改后文本目录（after 侧，对应上游 books）> \
  --map-root    <FixText 根目录>

# 单元测试
python3 -m pytest tests/ -q

# 等价性比对（需 PHP 环境：上游源码 + vendor/）
python3 scripts/run_equivalence.py \
  --php-maps <PHP 产出目录> --py-maps <Python 产出目录> \
  --report 报告.md --json 结果.json \
  --exclude 天之下.php --exclude 铁鹤书.php --corpora-count 15

# 本轮独立复验（不需要 PHP 解释器，用冻结的 PHP 产物作基准）
python3 verification/run_independent_equivalence.py \
  --baseline <FixText_T0.4_回归基线集_v1>/baseline \
  --out verification/independent_result.json
```

## 测试的可信度说明

测试断言刻意**不来自本 Python 实现**，避免「自己验证自己」：

- `tests/fixtures/strip_tags_php.json` —— 49 条向量，期望值由真实 PHP 8.5.8 的 `strip_tags()` 跑出，
  含注释嵌套、引号保护、`<? ?>` 处理指令等对抗性用例；
- `tests/fixtures/patch_analyzer_php.json` —— 真实 `diff -u` 文本 + 上游 `PatchAnalyzer` 的解析结果；
- `tests/fixtures/core_php.json` —— `extractStrDiff` / `trimUnicodeChars` / `getFilename` /
  `getWordsPrintStr` / `changeEncodingAndNewLineType` 的上游输出；
- `tests/fixtures/map_php.json` —— `/^/m` 边界、`findClosingBracket`、插入位置、词库合并的上游输出。

开发中这些权威向量直接暴露了实现缺陷，例如 `/^/m` 原先错误地在**末尾换行之后**也插入缩进，
以及空串未返回前缀；均已按 PHP 实测行为修正，并补了边界回归用例。

## 与上游的唯一有意差异

`generator.iter_files()` 对文件做了排序，上游是文件系统遍历顺序。

- 原因：让多次运行结果可复现、可比对。
- 影响范围：只影响「多本书的处理先后顺序」，不影响任何单本书的词库内容——
  15 份语料的比对已证明最终词库文件逐字节一致。

其余行为（含 PHP 的 `"0"` 为假值、跨行差异用字面 `\n` 拼接、单独 `-`/`+` 行借用上下文、
`strip_tags` 的多状态机、时间点注释格式）均按上游原样复刻。

## 已知边界

- 语料编码按 UTF-8 处理；上游另支持 GBK 等编码的旧书，Python 侧未做编码嗅探。
- 依赖 GNU `diffutils` 的 `diff` 命令（与上游同样依赖），需在 PATH 中。
- 上游 `GenerateBookMaps` 命令是交互式提问（是否记录时间点），本模块改为 CLI 参数
  `--add-current-time` / `--timestamp`，非交互。
- `strip_tags` 复刻的是 PHP 的字节级扫描状态机，对病态嵌套（如未闭合 `<!`）与 PHP 保持一致，
  但不保证与浏览器 HTML 解析器的语义相同。

## 环境要求

- Python 3.10+
- GNU diffutils（`diff` 命令必须在 PATH 中，与上游同样依赖）
- 重跑 PHP 夹具生成时需要 PHP 8.0+ 与 FixText 源码的 `vendor/`
