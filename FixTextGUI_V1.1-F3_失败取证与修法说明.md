# V1.1-F3 失败取证与修法说明

基线：`FixTextGUI_V1.1-F2_代码包`（云盘 `projects/fix_text/code`，file_token `R1ibb7kbWoh6c6xxDLncFHH3n0P`，
md5 `8b78bc16ee780dd0db7adeedd5406703`），dev HEAD `456a34e`。
本卡在 dev 上出**一个**提交，不 rebase、不 merge（C1 平行线由小组长合并）。

范围：5 条词库口径既有失败 + 1 处小组长已核准的产品侧小修复。**没有第三个改动**。

## 0. 结论先说

**5 条失败全是测试缺陷，不是产品缺陷。** 每条都能追到一个有意的产品变更提交，测试没跟上：

| # | 用例 | 原始报错 | 追到的变更 | 性质 |
|---|---|---|---|---|
| 1 | `test_t31_vocab_store.py::test_search_scoped_to_tier` | `KeyError: 'b2'` | M5-QC.2 `18a1a7c` 删 `b2`（标点迁排版） | 测试缺陷 |
| 2 | `test_t31_vocab_ui.py::test_module_shows_real_builtin_count` | `assert 302957 == 304255` | 同上 + M5-EX.1 `21cb712` 改读按袋目录 | 测试缺陷 |
| 3 | `test_t31_vocab_ui.py::test_search_hit_count_matches_data_layer` | `assert 18 == 9` | 测试把界面置成**界面上不存在**的状态组合 | 测试缺陷 |
| 4 | `test_t32_vocab_safety.py::test_custom_and_builtin_are_physically_separate` | `IsADirectoryError: .../data/rules/bags` | `21cb712` 新增 `bags/` 子目录，指纹写法没跟上 | 测试缺陷 |
| 5 | `test_t37_vocab_bridge.py::test_custom_word_takes_effect_in_real_correction` | `KeyError: 'applied_words'` | `21cb712` 逐条明细移到 `round_meta.json` | 测试缺陷 |

**业务代码只动了 1 处**：`fixtext_ui/fixtext_worker.py` 的 `finally` 归还引擎客户端的
`subprocess` 代理（小组长核准项）。其余 4 个改动文件全是 `tests/`。

**门禁结果：五批 492 条 0 failed，`tools/run_regression.sh` 退出码 0。**（原始输出见 §3）

## 1. 取证方法

先把「失败」还原成**原始报错原文**，再判断是测试过期还是产品坏了。三条判据：

1. **能不能追到一个有意的产品变更提交**（`git log -S` / `git show`）——能追到，且变更理由成立 → 测试过期；
2. **产品行为本身合理吗**（数字对不对得上、界面上用户能不能真的走到那个状态）；
3. **修完的断言能不能抓住真实回归**（§4 反向验证，防止改成恒真的空断言）。

取证在**基线副本**（`work/base/FixTextGUI`，与修复包同源同 md5）上跑，所以原始的
5 条失败是当场复现出来的，不是抄的：

```
FFFFF                                                                    [100%]
==================== FAILURES ====================
tests/test_t31_vocab_store.py:79: in test_search_scoped_to_tier
    assert counts["b1"] + counts["b2"] + counts["b3"] == 304255
E   KeyError: 'b2'
tests/test_t31_vocab_ui.py:75: in test_module_shows_real_builtin_count
    assert mod.store.builtin_total == 304255
E   assert 302957 == 304255
tests/test_t31_vocab_ui.py:100: in test_search_hit_count_matches_data_layer
    assert mod._hit_total == expect
E   assert 18 == 9
tests/test_t32_vocab_safety.py:367: in test_custom_and_builtin_are_physically_separate
    builtin_before = {n: _sha(builtin_dir / n) for n in sorted(
E   IsADirectoryError: [Errno 21] Is a directory: '.../data/rules/bags'
tests/test_t37_vocab_bridge.py:194: in test_custom_word_takes_effect_in_real_correction
    assert rep["derived_rules"]["applied_words"] == [
E   KeyError: 'applied_words'
========================= 5 failed in 11.84s ==========================
```

（完整原始输出存档：`evidence/f3_regression/base5_repro.log`）

## 2. 逐条取证与修法

### 2.1 `test_search_scoped_to_tier`（KeyError: 'b2'）

**断言原文**（基线）：`assert counts["b1"] + counts["b2"] + counts["b3"] == 304255`，
以及 `assert counts["b1"] == 299114 and counts["b2"] == 893 and counts["b3"] == 4248`。

**实际值**：`counts` 里已经没有 `b2` 这个键 → `KeyError`。

**根因**：M5-QC.2 `18a1a7c`（"接通分袋勾选并回复词库独立选项缺口"）把标点规范袋
`punctuation` 从界面分级里摘掉了——标点已迁到排版阶段处理，DNA 里不再挂这个分级。
该提交在 `fixtext_ui/fixtext_vocab.py` 三张表里同步删了 `b2`：

- `TIER_NAMES`：`"b2": "标点规范词库"` → `"cjk": "CJK 恢复词库"`；
- `BAG_TO_TIER`：`"punctuation": "b2"` → 该条目整条移除（`punctuation/postfix/temp` 不再下发）；
- `TIER_TO_BYTE` / `BUILTIN_TIER_CODE`：`b2`/`"2"` 两个键一并删掉。

所以「三个分级」这个**前提**已经不成立，不是代码取错了键。

**实测的两边数字**（`data/rules/bags/manifest.json` 逐袋实算，不是记忆值）：

| 口径 | 条数 | 说明 |
|---|---|---|
| 可达袋之和（`BAG_TO_TIER` 12 个取值） | **302,957** | 界面能点到的全部 |
| 磁盘总（15 袋） | **304,255** | 与 F2 时代那个 304,255 一致 |
| 差额：`postfix` 1,296 + `punctuation` 1 + `temp` 1 | **1,298** | 界面上不挂的三袋 |

302,957 + 1,298 = 304,255，账平。原来那条断言里的 304,255 是**磁盘总数**，
而 `builtin_total` 现在是**可达总数**——两个数都对，只是口径不同，测试把两者当成一个。

**修法与理由**：改成不写死数字的等价断言，用 `BAG_TO_TIER` 的**取值集合**（可达分级）
去算，并额外核准差额出处：

1. 可达分级之和 == `builtin_total`（两边各自独立算，不许互抄）；
2. 磁盘总数 == 可达之和 + 隐藏袋之和，且 `hidden == ["postfix", "punctuation", "temp"]`
   ——差额必须有明确出处，否则将来再加隐藏袋会被这条拦住；
3. 每个可达分级的条数 == manifest 里对应袋的条数（这才是「分级过滤真的按袋生效」）；
4. 抽样分级检索命中 ≤ 该分级条数；
5. 全库命中 == 各可达分级命中之和（口径一致性，`> 0` 防空断言）。

不写死数字是刻意的：本卡之前 5 条失败里有 3 条就是「写死数字 + 产品有意改口径」的组合，
写死会在下一轮再犯一次。

### 2.2 `test_module_shows_real_builtin_count`（302957 != 304255）

**断言原文**：`assert mod.store.builtin_total == 304255`，随后 `assert counts["b1"] + counts["b2"] + counts["b3"] == 304255`。

**实际值**：`builtin_total = 302,957`（界面汇总处实读）。

**根因**：同 2.1 的两层叠加——`b2` 被删（`18a1a7c`），且词库展示从 flat 五件套改成
读按袋目录（M5-EX.1 `21cb712`），`builtin_total` 的语义变成「界面上可达条数」。
磁盘 304,255 里 1,298 条属 `punctuation/postfix/temp`，界面上故意不挂。

**修法**：与 2.1 同口径，三条：可达之和 == `builtin_total`；`builtin_total` ==
manifest 可达袋之和；磁盘总数 == `builtin_total` + 隐藏袋之和。断言的是**层级关系**
（界面汇总 = 数据层可达 = manifest 可达），而不是某个常数。

### 2.3 `test_search_hit_count_matches_data_layer`（18 != 9）

**断言原文**：把界面置成 `mod.dict_ = "all"`、`mod.tier = "b1"`，然后
`assert mod._hit_total == search_count("好象", dict_code="b1")`。

**实际值**：`_hit_total = 18`，`search_count(..., "b1") = 9`。

**根因（这条最值得记）**：`dict_="all"` + `tier="b1"` 是**界面上不存在**的状态组合。
真实点击路径只会产生两种：

- 页头的分档按钮（全部/自定义/内置）走 `set_tier()`，它**不动** `dict_`；
- 左侧分级列表走 `select_dict(d)`，它把 `tier` 归到 `custom` / `all`。

而 `_scope()` 先看 `dict_`：`"all"` 不在 `TIER_NAMES` 里，于是返回 `"all"`（全库）。
实测两条路径分开跑：

```
非法组合 dict_=all, tier=b1 -> scope = 'all'  hit_total = 18
真实点击 select_dict(b1)    -> scope = 'b1'   hit_total =  9   len(get_filtered()) = 9
全库 search_count(好象) = 18 ；b1 口径 = 9
```

也就是说测试手工造了一个 UI 到不了的状态，然后拿全库的 18 去比单分级的 9。
产品这边是自洽的：点 b1 就只数 b1，点「全部」就数全库。

**修法**：改成按**真实点击路径**置状态——`mod.select_dict("b1")`（等价于用户点左侧
「常规校正词库」），再核对命中数与数据层 b1 同口径；每页条数 `PAGE_SIZE` 从
`vocab_module` 取（它是界面常量，不在数据层，原来写死的 `40` 也是同类隐患）。
这样验的是用户真能走到的行为，而不是测试自造的中间态。

### 2.4 `test_custom_and_builtin_are_physically_separate`（IsADirectoryError）

**断言原文**：`builtin_before = {n: _sha(builtin_dir / n) for n in sorted(p.name for p in builtin_dir.glob("*"))}`。

**实际值**：`IsADirectoryError: [Errno 21] Is a directory: '.../data/rules/bags'` ——
`builtin_dir.glob("*")` 命中了 `bags/` 这个**目录**，`_sha` 直接 `read_bytes()`。

**根因**：`21cb712` 把内置词库改成按袋存放，`data/rules/` 下多了 `bags/`（15 袋 + manifest
+ bin）以及 `rules.json` 等，取指纹的写法还停在「顶层全是文件」的时代。**不是产品坏了**，
是取指纹的代码没跟上目录结构。

**修法**：递归枚举内置词库目录下**所有普通文件**逐个取 sha，并加一条自检
（`assert any(k.startswith("bags/") ...)`）确保指纹真的覆盖到 `bags/` 内部——
不然递归也会被将来的重构悄悄退化成空集。覆盖面比原来更大（原来只扫顶层）。
断言语义一字未变：写自定义词前后，内置目录一个字节都不许变。

### 2.5 `test_custom_word_takes_effect_in_real_correction`（KeyError: 'applied_words'）

**断言原文**：`assert rep["derived_rules"]["applied_words"] == [{"word": "萧衍", "value": "萧彦", "id": 1}]`。

**实际值**：`replace_report.json` 的 `derived_rules` 里没有 `applied_words` 这个键。

**根因**：`21cb712` 把分袋多轮改成「每轮一个派生目录」（`derived_rules_dir/round_<id>/`），
同时把报告里的派生字段**收窄成白名单**（`pipeline/fixtext_pipeline/stages/replace.py:317`）：

```
"derived_rules": {k: derived.get(k) for k in (
    "bag_ids", "base_rules", "custom_input", "custom_applied",
    "total_rules", "custom_error", "include_custom", ...
)}
```

逐条明细移到派生目录自己的 `round_meta.json`（`bags.write_round_rules` 落盘同一份
stats，`before_path` / `after_path` / 各 sha 都在里面）。所以「报告 = 本轮摘要，
`round_meta` = 明细」是**有意做的分层**，被测字段只是换了落点。

**修法**：去派生目录读明细，语义一字不改：

```
meta_main = tmp_path / "derived" / "round_main" / "round_meta.json"
assert meta_main.is_file()                        # 主轮必须留下自己的元数据
derived_meta = json.loads(meta_main.read_text(encoding="utf-8"))
assert derived_meta["custom_applied"] == 1
assert derived_meta["applied_words"] == [{"word": "萧衍", "value": "萧彦", "id": 1}]
```

实测真实内容：`custom_applied = 1`，`applied_words = [{'word': '萧衍', 'value': '萧彦', 'id': 1}]`。
原用例里「报告也要有 `custom_applied == 1`」那条**保留未动**——它确实还在白名单里，
两条一起看正好证明「摘要 + 明细」两层都对得上。

## 2.6 核准的产品侧修复：`CorrectionJob.run()` 归还可取消代理

**缺陷**（小组长登记自 F1 取证）：`fixtext_ui/fixtext_worker.py` 里 `run()` 把引擎客户端的
`subprocess` 换成 `_SubprocessProxy(self)`（为了让取消能**即时杀掉** Go 子进程），
但 `finally` 只摘了 Python 引擎的取消钩子，**没把 `subprocess` 还回去**。
代理里绑的是**这一次 job** 的 `cancel_requested`，被取消过的 job 永远是 `True` ——
于是同进程里后续任何一次**直调引擎**（不走 job 的路径）都会读到那个标记。

**危害探针（同一份脚本，基线包 vs 修复包，两跑对照）**：

基线（未修）：

```
CANCELLED ok: 在阶段开始前取消
Traceback (most recent call last):
  File ".../pipeline/vendor/fixtext/engine/client.py", line 128, in _run_or_raise
    proc = subprocess.run(
  File ".../fixtext_ui/fixtext_worker.py", line 219, in run
    raise CorrectionCancelled("已终止替换引擎")
fixtext_worker.CorrectionCancelled: 已终止替换引擎
```

修复后：

```
CANCELLED ok: 在阶段开始前取消
resp.ok = True
client.subprocess = <module 'subprocess' from '/opt/python3.12/lib/python3.12/subprocess.py'>
```

即：**没修之前，取消过一次 job 之后同进程直调引擎必然误报「已终止替换引擎」**；
修完直调正常成功，且 `client.subprocess` 已回到标准库模块。
（原始输出：`evidence/f3_regression/harm_probe_baseline.log` / `harm_probe_fixed.log`）

**修法（两处小改，不改任何行为语义）**：

```python
# 装代理时留句柄
import fixtext.engine.client as _engine_client
_proxy = _SubprocessProxy(self)
_engine_client.subprocess = _proxy

# finally 里按「是不是我装的那个」归还
if _engine_client.subprocess is _proxy:
    _engine_client.subprocess = _subprocess_mod     # 模块级 import subprocess as _subprocess_mod
```

为什么用 `is _proxy` 判一下而不是无条件赋回：如果有别的调用方（未来的并发入口、
或者宿主工具）自己换上去一个代理，job 收尾时无条件覆盖就会**越权拆掉别人的钩子**。
「只还自己装的那一个」是这个修法最容易被写错的地方。

**守卫测试**（新增 `tests/test_f3_engine_globals.py`，2 条）：

- `test_cancelled_job_hands_subprocess_back`：取消一次 job → 断言 `subprocess` 已还原 →
  **同进程直调引擎必须成功**且替换真的生效（萧衍消失 / 萧彦出现）；
- `test_completed_job_hands_subprocess_back`：跑完（非取消）的 job 同样必须还原。

RED → GREEN 原始对照（同一份测试文件）：

```
# 基线包（未修）：2 failed
tests/test_f3_engine_globals.py:130: assert _restored()
E   AssertionError: 取消后的 job 必须把 fixtext.engine.client.subprocess 还原回标准库模块...
# 修复包：2 passed
tests/test_f3_engine_globals.py::test_cancelled_job_hands_subprocess_back PASSED
tests/test_f3_engine_globals.py::test_completed_job_hands_subprocess_back PASSED
============================== 2 passed in 3.30s ===============================
```

（原始输出：`evidence/f3_regression/guard_red_baseline.log` / `guard_f3.log`）

**这条守卫测试不在五批 492 条的账里**（`tools/run_regression.sh` 的切分是按文件名字母序
连续段的固定清单，新增文件不进任何一批）。所以本卡的总账是：
**492 条（五批）+ 2 条（守卫）= 494 条，全绿。** 我没有去改 `run_regression.sh` 的清单——
那会让本卡的门禁口径与小组长基线不可比，而可比正是分批的唯一价值。

## 3. 验收：五批全量回归（这才是判据）

用卡片指定的唯一验收脚本 `tools/run_regression.sh`（五批按文件名字母序连续段切分，
101 / 89 / 110 / 68 / 124 = 492 条），一次跑完，原始输出：

```
=== batch 1 ===
101 passed in 207.13s (0:03:27)
=== batch 2 ===
89 passed in 10.50s
=== batch 3 ===
110 passed in 11.82s
=== batch 4 ===
68 passed in 44.28s
=== batch 5 ===
124 passed in 92.34s (0:01:32)
```

脚本退出码 `SCRIPT_EXIT=0`（脚本语义：任一批非 0 即返回非 0）。逐批原始日志：
`evidence/f3_regression/batch{1..5}.log` + `summary.txt` + `official_run_console.log`。

**与 F2 基线的对账**（失败集合是差集算出来的，不是手抄）：

| 批 | F2 基线（`evidence/f2_regression`） | 本卡 |
|---|---|---|
| 1 | 101 passed | 101 passed |
| 2 | 89 passed | 89 passed |
| 3 | 110 passed | 110 passed |
| 4 | **1 failed, 67 passed**（`t31_vocab_store::test_search_scoped_to_tier`） | 68 passed |
| 5 | **4 failed, 120 passed**（`t31_vocab_ui` ×2、`t32_vocab_safety`、`t37_vocab_bridge`） | 124 passed |
| 合计 | 487 passed / 5 failed | **492 passed / 0 failed** |

5 条失败的分布正好对上：`t31_vocab_store` 落在第 4 批，另外 4 条落在第 5 批。
**没有新增失败，也没有任何一条被 skip。**

### 3.1 退出码：一次环境性段错误，交代清楚

本卡 batch 1 共跑过 3 次整批：第一次 `101 passed` 但进程退出码 **139**（Segmentation fault，
发生在 pytest 打印完结果之后、解释器退出时）；紧接着**单跑该批最后一个文件**
`tests/test_ex4d_topbar_popup_anchor.py` → `8 passed` / `EXIT=0`；之后两次整批 → `EXIT=0`
（上面 §3 的正式门禁就是其中一次）。

为判断这是不是本卡引入的，我在**基线副本**（未修、同源同 md5）上跑了同一批文件：

```
101 passed in 207.75s (0:03:27)
（进程退出码同样为 139）
```

基线也 139，说明这是**既有的、环境相关的 Qt/shiboken 析构崩溃**，与本卡的两处业务代码
改动无关（本卡改的 `finally` 归还代理不可能影响解释器退出阶段的 Qt 对象析构）。
F2 的报告里也记录过同一现象（"单跑通过（`1 passed`），但进程退出码 **139**（或 134）"）。

处置：**不掩盖、不规避**。正式门禁那一轮五批退出码全为 0（脚本聚合返回 0 即为证，
脚本逻辑是 `[ $code -ne 0 ] && rc=$code`）。这条偶发现象如实登记在 §7，留后续卡处理。

## 4. 反向验证：修订后的断言不是恒真的

只把断言改成「能通过」是危险的——可能改成了空断言。所以三条关键断言各做一次人工注入：

```
########## NEG-1：t32 指纹能否抓到内置文件被写 ##########
断言是否会亮（应为 True）: True
变化文件: ['bags/normal/before.json']
已按字节还原，还原后全量指纹与改前一致 = True

########## NEG-2 / NEG-3 ##########
NEG-2 基准：可达分级之和 = 302957 builtin_total = 302957
NEG-2 人为把 b1 减 1 后断言应为 False = True （左 302956 vs 右 302957 ）
NEG-3 真实 round_meta: custom_applied = 1 applied_words = [{'word': '萧衍', 'value': '萧彦', 'id': 1}]
NEG-3 把期望值改成 0（模拟自定义词没生效）断言应为 False = True
```

- NEG-1：给 `bags/normal/before.json` 尾部加一个空格 → 指纹断言立刻失败，且能**指认到具体文件**；按字节还原后全量指纹与改前一致（不留残留）。
- NEG-2：把某个可达分级条数人为减 1 → 「可达之和 == builtin_total」失败（302956 vs 302957），说明这条不是恒真。
- NEG-3：把期望的 `custom_applied` 改成 0（等价于「自定义词没生效」）→ 断言失败，说明 `round_meta` 里那个字段是真判据。

（原始输出：`evidence/f3_regression/negative_probe.log`）

## 5. 业务代码改动情况

**只改了 1 处**，即小组长核准的 `fixtext_ui/fixtext_worker.py`（见 §2.6），
两处 hunk：装代理时留句柄 + `finally` 归还。**没有第三处业务代码改动**，
没有顺手重构、没有夹带格式化。

其余 5 个文件变化全部在 `tests/`：

| 文件 | 变化 |
|---|---|
| `fixtext_ui/fixtext_worker.py` | +9 / −1（核准项） |
| `tests/test_t31_vocab_store.py` | 修订 `test_search_scoped_to_tier` |
| `tests/test_t31_vocab_ui.py` | 修订 2 条 |
| `tests/test_t32_vocab_safety.py` | 修订 1 条 |
| `tests/test_t37_vocab_bridge.py` | 修订 1 条 |
| `tests/test_f3_engine_globals.py` | 新增（2 条守卫） |

`data/`、`pipeline/`、`fixtext_import/`、`fixtext_error_center/` 一个字节都没动。
