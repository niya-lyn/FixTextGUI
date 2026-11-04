# V1.1-D2 超限分批与不合格清单 · 实现与验收说明

基线：`FixTextGUI_MRG4_合并主干_v1.zip`（云盘 `projects/fix_text/code`，file_token
`Ql48bFU2eoGLDbxrbCjckJqlnOe`，md5 `231f07ebfd8db43fc65b7d8a0ddddeec`），dev HEAD `bb76955`。

本卡在 dev 上出**一个**提交（父 `bb76955`，哈希见交付评论——报告随包分发，写死会自指），不 rebase、不 merge。作者
`Doubao Agent Engineer A <doubao-engineer-a@local>`，提交信息带 `V1.1-D2`。

范围：排期文档 §9.4 交付物 2 个——① 超限分批策略；② 不合格行清单。
**不做**预览分组（D3）、**不做**冲突处置（D4）、**不做**写入（D5）。

## 0. 结论先说

两条验收判据都过了，且都是**结构性**可证，不是"跑一遍看着没问题"：

| 判据 | 怎么证的 | 证据 |
|---|---|---|
| 不合格行不阻塞合法行入库 | `ImportPrep.plan` 只装 `rejects.good`；混合表里 20 935 条合法行一条不少全进批，1 069 条不合格行一条都没进批，条数守恒 | §3.2 / §4.1；`evidence/d2/measure_run.log` |
| 清单每条能定位到原始行号 | 清单每条 `原文.split("\n")[行号-1]` **逐字**等于清单里的「该行原文」；22 224 行大表 0 条不匹配，1 102 行真实样本逐条核对 | §3.2 / §4.2 |

数字：**新增 D2 单测 59 项 + D1 既有 75 项 = 134 passed / 0 failed**（§5 原始输出）。
干净目录解压、中性 CWD 下 `opens_on_first_run() = True`（§6）。
三处故意破坏分别被 5 / 8 / 4 项测试抓住（§7），证明测试不是空转。

实现期发现并修掉一个真缺陷：`ProgressReport` / `BatchFailure` / `BatchRunResult`
三个类型在 `run_batches` 的返回值与进度回调里都要用，却没从包顶导出——界面层必须
知道内部文件名才能拿到，等于把实现细节漏给调用方。已补齐并加一条用例钉住（§2.4）。

## 1. 两个交付物长什么样

### 1.1 超限分批策略（`fixtext_vocab_import/batching.py`，414 行）

| 构件 | 职责 | 关键约定 |
|---|---|---|
| `BatchPolicy` | 阈值 + 每批条数 | 默认都是 1000；两者均须 ≥ 1 |
| `plan_batches` | 把合法行切成批 | 按传入顺序连续切，切点只落在两条之间，不重排不跳行 |
| `BatchPlan` | 批的集合 + 自检 | `covers_all_rows()` 校验不重不漏 |
| `Batch` | 单批条目 + 行号区间 | `first_line` / `last_line` 指向原文行号 |
| `ProgressReport` | 一批完成后的快照 | `percent` / `rate` / `eta_seconds` 全部来自实测 |
| `run_batches` | 逐批执行 + 进度回调 | 失败保留已完成部分；`KeyboardInterrupt` 原样上抛 |
| `ImportPrep` | 两个交付物的联合入口 | `plan` 只装合法行（判据一的结构基础） |

**阈值为什么是 1000。** 先量了真实吞吐（§4.3：7.09–7.24 µs/行），再按"1000 行 ≈ 7 ms，
短于用户能察觉的一次停顿"定值，不是凭直觉写数字。批大小与阈值同值，所以"超过阈值"
必然等于"真的切成多批"——避免出现"超限了却只有一批"这种没法对用户解释的状态。
边界用例 `test_a_thousand_rows_exactly_stays_one_batch` 钉住"1000 条整不切"。

**进度文案给的是人话**，原始输出（§4.3）：

```
第 1 / 21 批 · 第 2–1061 行 · 已完成 1000 / 20935 条（5%），正在处理剩下的。
第 21 / 21 批 · 第 21233–22225 行 · 已完成 20935 / 20935 条（100%），全部处理完了。
```

进度卡在哪批 ⇔ 卡在哪一段原文——这就是"失败时用户能回到那一段"的落地方式。

### 1.2 不合格行清单（`fixtext_vocab_import/rejects.py`，443 行）

6 类原因分两组（`REJECT_REASONS` 顺序即清单分组顺序）：

| code | 清单里的分类名 | 阻塞整表？ |
|---|---|---|
| `NO_WORD_COLUMN` | 还没有指定「错词」列 | 是 |
| `NO_VALUE_COLUMN` | 还没有指定「正确写法」列 | 是 |
| `WORD_EMPTY` | 「错词」这一格是空的 | 否 |
| `VALUE_EMPTY` | 「正确写法」这一格是空的 | 否 |
| `BOTH_EMPTY` | 「错词」和「正确写法」都是空的 | 否 |
| `SHORT_ROW` | 这一行少了几格 | 否 |

前两类是"列没指好"，那时合法行本来就是 0，界面该先让用户改列映射，而不是显示
"0 条可导入"。这就是 `is_blocking()` 存在的理由。

清单每条带**行号 + 该行原文 + 原因 + 怎么改**四样（`RejectedRow`）。导出表 7 列
（`EXPORT_COLUMNS`）：`原文行号, 原因分类, 怎么改, 错词, 正确写法, 分类, 该行原文`。
导出用 `utf-8-sig`，表格软件双击就认中文——带签名的写法是实质要求，不然用户打开是乱码，
那就不叫"可导出"。

### 1.3 行号口径：与 D1 逐字一致

这是本卡最容易做错的地方，三条一起成立：

1. **物理行号从 1 起算**，跟用户在文件里数的行号一致；
2. **原版导出首行的说明文字：置空不删行**，所以第一条词条是第 2 行、不是第 1 行；
3. **空行跳过但不前移他行行号**。

证据（§4.1，真实原版 PHP 导出样本 1 102 条）：

```
行数 = 1102  批数 = 2  每批 = [1000, 102]
首批行号跨度 = (2, 1001)     ← 从 2 起，说明 banner 占着第 1 行
首行说明文字被处理 = True  跳过空行 = 1
```

这跟 D1 已确认的口径同源：`RejectList.header_note()` 会把这件事直接写在清单表头
/ 界面提示里，让用户看到的就是同一套说法。

### 1.4 D1 侧的必要改动（`parse.py`，+25/−7）

`ParsedSheet` 增两个字段，只为让 D2 能**如实**交代，不是新功能：

- `banner_removed`：首行是否是旧版导出的说明文字（决定要不要在表头解释行号）；
- `blank_skipped`（`_count_blank_lines`）：跳过了多少空行——告诉用户，不静默丢弃。

## 2. 判据一 · 不合格行不阻塞合法行（怎么证）

### 2.1 结构上不阻塞，不是"跑起来没事"

`ImportPrep.plan` 是由 `plan_batches(rejects.good)` 生成的——不合格行**根本没进批**。
所以"烂行处理失败拖住整批"这条路在数据结构上就不存在。`prepare_import` 一条语句：

```python
def prepare_from_rejects(rejects, policy=None) -> ImportPrep:
    return ImportPrep(rejects=rejects, plan=plan_batches(rejects.good, policy))
```

### 2.2 混合表实测（§4.2）

22 224 个物理行、CRLF 换行、混合合格 / 不合格 / 空行：

```
合格 = 20935 (期望 20935)  不合格 = 1069 (期望 1069)  跳过空行 = 220 (期望 220)
守恒 = True   合格+不合格+空行 = 22224 = 22224
批内只有合法行 = True
```

合格行**一条不少全部进批**，不合格行**一条都没进批**，两边加上空行恰好等于总行数。

### 2.3 反向对照（防恒真断言）

`test_negative_control_deleting_legal_rows_empties_the_plan`：把合法行从输入里拿掉，
断言计划确实变空。若断言恒真，这一条就过不了——它过，说明前面的断言有内容。

### 2.4 实现期修掉的缺陷

`ProgressReport`（进度回调的类型）、`BatchFailure`、`BatchRunResult` 三个类型原先只在
`batching` 子模块里，包顶没有。实测脚本 `from fixtext_vocab_import import ProgressReport`
直接 `ImportError` 才发现。已补齐到 `__init__.py` 的导入与 `__all__`，并新增用例
`test_every_d2_public_name_is_reachable_from_the_package_top` 覆盖 18 个公开名。
这是本卡唯一一处"被发现后修的"，如实记在这里。

## 3. 判据二 · 清单能定位到原始行号（怎么证）

### 3.1 最硬的验法：回原文按行号取那一行，逐字比对

不做"行号在合理范围内"这种松断言，而是：

```python
raw = text.split("\n")
for r in prep.rejects.rejects:
    assert r.raw_line == raw[r.line_no - 1]
```

清单里存的「该行原文」是**未切列、未还原占位标记**的原样，所以用户拿行号回原文能逐字对上。
22 224 行大表实测：**不匹配 = 0**（§4.2）。

### 3.2 真实样本逐条核对

`orig_oldstyle_map.csv`（1 102 条，原版 PHP 直接导出）在
`test_real_file_1102_rows_line_numbers_match_the_file_verbatim` 里逐行核对，且在
`test_batching_a_real_1102_row_file_crosses_the_threshold_with_progress` 里同时验阈值跨界：
1 102 条 → 2 批 `[1000, 102]`，首批行号 `(2, 1001)`。

### 3.3 换行归一不影响行号

`test_crlf_file_keeps_line_numbers_after_newline_normalization`：CRLF 文件在 D1 归一成
LF 之后，行号仍是原文行号。§4.2 的大表本身就用 CRLF 构造，守恒与 0 不匹配两项同时成立。

### 3.4 清单分类计数（§4.2 实测）

```
清单原因分类 = {'「错词」这一格是空的': 524, '「正确写法」这一格是空的': 247, '这一行少了几格': 298}
```

524 + 247 + 298 = 1 069 = 不合格行数。分组计数与总数对得上，不是各算各的。

### 3.5 导出实物

`evidence/d2/导入不合格清单_样例.csv`（1 069 数据行 + 1 表头，158 106 字节，带 BOM）：

```
表头: 原文行号,原因分类,怎么改,错词,正确写法,分类,该行原文
第 42 行: 42,「错词」这一格是空的,补上这一格的内容，或者把这一行删掉再导入。,,值41,错词校正,,值41
第 74 行: 74,这一行少了几格（只切出 1 格，表头有 3 列）,检查这一行是不是漏了分隔，或者补上缺的那一格。,孤零零一格,,错词校正,孤零零一格
```

每行末列是原文重现——用户拿它对照原文件，能一眼认出是哪一行。

## 4. 实测原始输出

### 4.1 真实旧式词库

```
[1] 真实旧式词库（原版 PHP 导出）: orig_oldstyle_map.csv
    字节数 = 25884  md5 = 881c9e2e33e71f0f14533fe238b36386
    行数 = 1102  批数 = 2  每批 = [1000, 102]
    首批行号跨度 = (2, 1001)
    不合格 = 0  守恒 = True
    首行说明文字被处理 = True  跳过空行 = 1
    文案: 共 1102 条，按每批 1000 条分成 2 批处理。
    文案: 全部 1102 行都合格，没有不合格的行。
```

### 4.2 22 224 行大表（CRLF）

```
[2] 大表（CRLF 换行）: 22224 个物理行 + 1 行表头
    耗时 = 0.161 s  → 7.24 µs/行
    批数 = 21  首批/末批条数 = [1000, 935]
    合格 = 20935 (期望 20935)  不合格 = 1069 (期望 1069)  跳过空行 = 220 (期望 220)
    守恒 = True   合格+不合格+空行 = 22224 = ？ 22224
    批内只有合法行 = True
    清单行号回原文逐字比对：不匹配 = 0
    清单原因分类 = {'「错词」这一格是空的': 524, '「正确写法」这一格是空的': 247, '这一行少了几格': 298}
    covers_all_rows() = True  总条数核对 = True  批间无重叠 = True
```

### 4.3 进度与导出

```
[3] run_batches: ok = True  已完成批 = 21 / 21  行数 = 20935
    进度采样（21 次回调）: [(1, '5%'), (2, '10%'), (3, '14%'), '…', (21, '100%')]
    首条: 第 1 / 21 批 · 第 2–1061 行 · 已完成 1000 / 20935 条（5%），正在处理剩下的。
    末条: 第 21 / 21 批 · 第 21233–22225 行 · 已完成 20935 / 20935 条（100%），全部处理完了。

[4] 导出实物: 导入不合格清单_样例.csv
    字节 = 158106  BOM = True  md5 = 09b2872d9a03bab891f6afb229fe790b
    数据行数 = 1069 (应 = 1069)
    export_ready() = True
    export_name() = 导入不合格清单_20261104_1430.csv
```

环境：Python 3.12.11 / Linux-6.6.95。
完整原始输出存档：`evidence/d2/measure_run.log`；脚本 `evidence/d2/measure_d2.py`（可复跑）。

## 5. 测试

```
$ PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.12 -m pytest \
    tests/test_d1_vocab_import.py tests/test_d2_batching_rejects.py -q
........................................................................ [ 53%]
..............................................................           [100%]
134 passed in 3.47s
```

- D1 既有：**75** 项，未删改任何断言，全绿；
- D2 新增：**59** 项，名单见 `evidence/d2/pytest_d2_verbose.log`。

按判据归类（不是泛覆盖）：

| 判据 / 主题 | 代表用例 |
|---|---|
| 判据一 · 不阻塞 | `test_mixed_table_keeps_every_legal_row_in_the_plan`、`..._illegal_row_out_of_the_plan`、`test_counts_are_conserved_...`、`test_negative_control_...` |
| 判据二 · 行号 | `test_every_reject_points_at_the_real_original_line`、`test_real_file_1102_rows_line_numbers_match_the_file_verbatim`、`test_line_number_keeps_d1_banner_convention_banner_is_line_1`、`test_crlf_file_keeps_line_numbers_...`、`test_end_to_end_on_a_large_mixed_table_every_reject_traces_back` |
| 阈值与边界 | `test_a_thousand_rows_exactly_stays_one_batch`、`test_threshold_decides_whether_to_batch_not_whether_it_can_be_done`、`test_over_limit_is_reported_from_the_threshold_exactly`、`test_batching_a_real_1102_row_file_crosses_the_threshold_with_progress` |
| 进度 | `test_progress_reports_reach_100_...`、`test_eta_comes_from_the_measured_rate_not_from_a_guess`、`test_eta_is_absent_when_nothing_has_been_measured_yet` |
| 失败不丢已完成部分 | `test_failing_batch_keeps_the_batches_already_done_...`、`test_stop_on_failure_false_continues_other_batches`、`test_keyboard_interrupt_is_not_swallowed_as_a_batch_failure` |
| 导出 | `test_export_table_has_one_row_per_reject_with_all_columns`、`test_export_bytes_are_stable_and_openable`、`test_export_preserves_marker_text_and_compresses_newlines_into_one_row` |
| 人话（无技术词） | `test_no_technical_terms_in_the_two_new_modules`、`test_all_user_facing_text_of_a_real_partition_is_jargon_free`、`test_policy_describe_avoids_internal_jargon` |
| 包顶导出完整 | `test_every_d2_public_name_is_reachable_from_the_package_top` |

**不做**的事也说清楚：本卡不跑五批全量回归（按纪律由小组长合并时跑）。所以上面 134 项
是 D1+D2 两条线的证据，不等于全仓回归证据。

## 6. 打包门禁

```
=== 干净解压 + 中立 CWD 门禁（2026-11-04T14:35+08:00）===
[git] [本卡唯一 V1.1-D2 提交] V1.1-D2：超限分批策略与不合格行清单…
      bb76955 MRG.4：五批回归与专项合跑证据（492/0 + 158/1skip）
[git status]（空）
[中立 CWD] opens_on_first_run() = True
```

另外在干净解压目录里跑了 D1+D2 全部 134 项：**134 passed in 0.60s**，跑完 `git status`
仍为空（跑测试不污染工作树）。存档 `evidence/d2/pack_gate.log`。

> 注意一个已踩过的坑（记录在此以免复踩）：`opens_on_first_run()` 必须在**包外中立 CWD**
> 跑。站在源码包目录里跑 `python -c` 会把源码包的 `fixtext_paths` 先导进来，误报 False——
> 那是环境串扰，不是打包问题。

## 7. 变异检验（测试真的会失败吗）

三处故意破坏，分别跑一次 D2 全量：

| 变异 | 破坏什么 | 抓住它的用例数 |
|---|---|---|
| M1 | 批计划里把不合格行也塞进去 | **5** |
| M2 | 清单行号偏移 +1（不懂 banner 口径） | **8** |
| M3 | 判定不再认全角空格（看着空却不判空） | **4** |

原始输出（节选）：

```
[M1 批计划把不合格行也塞进批]
  exit = 1  | 5 failed, 54 passed in 1.59s
    FAILED ...::test_mixed_table_keeps_every_legal_row_in_the_plan
    FAILED ...::test_mixed_table_keeps_every_illegal_row_out_of_the_plan
    FAILED ...::test_negative_control_deleting_legal_rows_empties_the_plan
    FAILED ...::test_crlf_file_keeps_line_numbers_after_newline_normalization
    FAILED ...::test_end_to_end_on_a_large_mixed_table_every_reject_traces_back

[M2 清单行号偏移 +1（不懂 banner 口径）]
  exit = 1  | 8 failed, 51 passed in 1.72s
    … test_every_reject_points_at_the_real_original_line / test_raw_line_is_kept_verbatim_… 等

[M3 判定里不再补全角空格（空格看着空却不判空）]
  exit = 1  | 4 failed, 55 passed in 1.57s
    FAILED ...::test_full_width_space_only_cell_is_rejected 等
```

每次破坏后源码都逐字还原（脚本打印 `内容一致 = True`），还原后 134 项复跑全绿。
存档 `evidence/d2/mutation_run.log`，脚本 `evidence/d2/mutate_d2.py`。

> M3 引出的一个真实设计判断：D1 的 `apply_mapping` 只去普通空格与制表符。用户从 Word / 网页
> 复制时常见**全角空格**，那一格看着是空的、去普通空格却判它非空，于是变成一条"错词是全角
> 空格"的词条被照常入库。D2 的 `BLANK_CHARS` 把 `\u3000 \u00a0 \u200b \u200c \u200d \ufeff`
> 一并算作空白。这一条不是洁癖，是真实数据里会长出来的脏词条。

另一个已确认的口径（记录免得被"顺手修好"）：**改前改后相同不判不合格**。真实出厂样本里就有
103 条这样的词条，那是 D3 查重 / D4 冲突的事，不是格式层面的"不合法"。用例
`test_same_word_and_value_is_not_treated_as_invalid` 钉住它。

## 8. 改动清单

| 文件 | 性质 | 行数 |
|---|---|---|
| `fixtext_vocab_import/batching.py` | 新增 | 414 |
| `fixtext_vocab_import/rejects.py` | 新增 | 443 |
| `tests/test_d2_batching_rejects.py` | 新增 | 806 |
| `fixtext_vocab_import/__init__.py` | 改（D2 公开名导出） | +56/−5 |
| `fixtext_vocab_import/parse.py` | 改（`banner_removed` / `blank_skipped`） | +23/−2 |
| `evidence/d2/*` | 新增证据 | 6 件 |

代码改动 5 个文件（`git diff --stat bb76955 HEAD`，不含下面追加的证据与本文档）：

```
 fixtext_vocab_import/__init__.py  |  61 ++-      (+56 / −5)
 fixtext_vocab_import/batching.py  | 414 ++++++++++++++++++++   (+414 / −0)
 fixtext_vocab_import/parse.py     |  25 +-       (+23 / −2)
 fixtext_vocab_import/rejects.py   | 443 +++++++++++++++++++++   (+443 / −0)
 tests/test_d2_batching_rejects.py | 806 ++++++++++++++++++++++++++++++++++++++
 5 files changed, 1742 insertions(+), 7 deletions(-)
```

同提交还带 `evidence/d2/`（6 件：2 个可复跑脚本、3 份原始输出、1 份导出实物）与本文档。

## 9. 遗留事项与边界

1. **D3 / D4 / D5 未做**（本卡范围外）：预览分组、冲突处置、写入。当前 `ImportPrep.plan`
   提供"合法的、已分批的"行，写入方直接消费 `plan` 即可，但**是否需要 D4 处理重复**要 D4 定，
   本卡不预设。
2. **五批全量回归未跑**：按纪律由小组长合并时跑。本卡证据 = D1(75) + D2(59) = 134。
3. **界面接线未做**：本卡只出数据层两个交付物与其单测；进度条 / 清单弹窗的界面呈现不在本卡，
   属 D2 之后的界面卡。`ProgressReport` / `RejectList` 的字段与文案已按界面直接可用设计
   （percent / text / summary_text / grouped / table_lines）。
4. **导出编码**：`utf-8-sig`（带 BOM）。若后续要求 GBK 导出（原版词库习惯），需要
   `to_file_bytes(encoding=...)` 扩参——本卡不预设，因为带 BOM 是"双击就认中文"的最低代价。
5. **`SHORT_ROW` 的边界**：行内格数少于表头列数即判短行；格数多于表头列数**不判不合格**
   （多出的格忽略，D1 映射只取指定列）。这是沿用 D1 口径，未在本卡改动。
