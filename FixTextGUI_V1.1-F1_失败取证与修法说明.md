# FixTextGUI V1.1-F1 · A 组入口卡 · 失败取证与修法说明

> 卡目标：清零 **m5_ex1 分袋 smoke 5 条** + **t31_vocab_merge_click 1 条** 共 6 条既有失败，
> 修法可被同类测试复用，**不改业务逻辑**，且**不新增失败**。
> 基线：`projects/fix_text/code` 里的 DOC1 包（file_token `Y3u4bW4bMoLsxhxI62BcEkx6nzd`，dev HEAD `7be8d88`）。
> 分支：本卡只提交在 **dev**（单提交），master / svg-icons 未动。

---

## 一、结论速览

| 项 | 结果 |
|---|---|
| 本卡 6 条目标失败 | **全部清零**（批量跑场景下成立，非单跑） |
| 全量回归（492 条，5 批） | **484 passed / 8 failed**（基线 478 passed / 14 failed） |
| 新增失败 | **0**（前后失败集合做差集，新增侧为空） |
| 剩余 8 条 | 与基线**逐条一致**，全部属于 F2（顶栏 3 条）/ F3（词库口径 5 条）范围，本卡**未动** |
| 业务逻辑改动 | **0 处**。改动只落在 `tests/`（2 个文件）+ 新增回归脚本与证据 |
| git | dev 分支**单提交**，作者 `Doubao Agent Engineer A <doubao-engineer-a@local>` |

一句话定性：**这 6 条里没有一条是产品缺陷**，5 条是**进程级全局状态泄漏**造成的测试污染，
1 条是**上游删控件后测试没跟上**的过期引用。两者都该改测试，不该改实现。

---

## 二、基线与分批口径（先对齐，再谈修法）

### 2.1 环境（与卡面约定一致）

```bash
PY=/usr/local/bin/python3.12
export PYTHONPATH=/home/gem/.aily/.cli/py312/lib/python3.12/site-packages:$PWD:$PWD/fixtext_ui
export QT_QPA_PLATFORM=offscreen
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
# 跑测试前预置（否则首启向导模态会把验收脚本卡死）
printf '[General]\nwizardSeen=1\n' > workspace/settings.ini
```

pytest 实测版本 **8.3.5**（系统自带的 9.1.1 必须靠上面的 `PYTHONPATH` 顶掉）。

### 2.2 分批

1 核沙箱里 44 个测试文件合成一条 pytest 会撞 600s 上限，因此按**文件名字母序的连续段**切 5 批
（脚本已入库：`tools/run_regression.sh`）：

| 批 | 文件段 | 用例数 | 基线结果 | 修复后结果 | 耗时 |
|---|---|---|---|---|---|
| b1 | atomic_write_win … ex4d_topbar_popup_anchor | 101 | 100p / 1f | 100p / 1f | 214.33s |
| b2 | ex6_quotation_fixer … import | 89 | 89p / 0f | 89p / 0f | 11.29s |
| b3 | layout_cancel … settings_module | 110 | 103p / **7f** | **108p / 2f** | 12.70s |
| b4 | t12_vocab_states_ui … t31_vocab_store | 68 | 66p / **2f** | **67p / 1f** | 46.32s |
| b5 | t31_vocab_ui … word_states | 124 | 120p / 4f | 120p / 4f | 90.40s |
| **合计** | | **492** | **478p / 14f** | **484p / 8f** | 6m24.9s |

基线 478/14 与小组长在 dev `6c339f2` 上的独立实测**完全一致**，说明分批口径可对账。
原始日志：`evidence/f1_regression/baseline_batch{1..5}.log`（基线）、`fix_batch{1..5}.log`（修复后）。

### 2.3 复现命令

```bash
bash tools/run_regression.sh <日志目录>     # 5 批全量，逐批留档
```

---

## 三、逐条取证与修法

### 组 1：m5_ex1 分袋 smoke 5 条 —— 同一个根因（进程级全局状态泄漏）

**涉及用例（均在 `tests/test_m5_ex1_runtime.py`）**

| # | 测试名 |
|---|---|
| 1 | `test_smoke_default_no_extra_rounds` |
| 2 | `test_smoke_preprocess_only` |
| 3 | `test_smoke_strict_only` |
| 4 | `test_smoke_zhuyin_after_main_and_after_raw` |
| 5 | `test_smoke_skip_layout` |

#### 3.1 断言原文（5 条各自的断言，均未被执行到）

```python
# test_smoke_default_no_extra_rounds
assert "layout" in keys
assert "replace_preprocess" not in keys
assert "replace_strict" not in keys
assert "replace_zhuyin" not in keys
text = cfg.replace_after().read_text(encoding="utf-8")
assert len(re.findall(r"[一-鿿]\[[A-Za-z]", text)) == 0
bags_used = (reports["replace"].get("derived_rules") or {}).get("bag_ids") or []
assert "normal" in bags_used
assert "cjk_recover" in bags_used
assert "strict" not in bags_used
assert "zhuyin" not in bags_used

# test_smoke_preprocess_only
assert "replace_preprocess" in keys
assert (reports["replace_preprocess"].get("derived_rules") or {}).get("bag_ids") == ["preprocess"]

# test_smoke_strict_only
assert "replace_strict" in keys
assert (reports["replace_strict"].get("derived_rules") or {}).get("bag_ids") == ["strict"]

# test_smoke_zhuyin_after_main_and_after_raw
assert keys.index("replace") < keys.index("replace_zhuyin")
assert zhu.get("count") == 1
assert (zhu.get("derived_rules") or {}).get("bag_ids") == ["zhuyin"]
raw = cfg.replace_after_raw(); assert raw.is_file()
assert raw_text != after_text or "[" not in after_text

# test_smoke_skip_layout
assert "layout" not in keys
assert keys[0] == "merge" and keys[1] == "replace"
```

#### 3.2 实际值

5 条**全部不是在断言处失败**，而是在跑 replace 阶段时直接抛异常：

```
fixtext_ui/fixtext_worker.py:219: fixtext_worker.CorrectionCancelled: 已终止替换引擎
```

即：断言一条都没跑到，替换引擎被「已取消」掉了。批量日志 `baseline_batch3.log` 里 5 条的失败堆栈完全一致。

**关键对照（本次亲测，留证 `evidence/f1_regression/before_fix_pair_repro.log`）**

```bash
# 只跑两个文件，取消测试在前 → 5 条 smoke 全挂
pytest tests/test_layout_cancel.py tests/test_m5_ex1_runtime.py
#   → 5 failed, 8 passed

# 只跑 smoke → 全过
pytest tests/test_m5_ex1_runtime.py
#   → 11 passed
```

与小组长「单跑过、批量跑挂」的判断吻合。

#### 3.3 根因

引擎客户端把 `subprocess` 当**模块级属性**用：

- `pipeline/vendor/fixtext/engine/client.py:24` → `import subprocess`
- `pipeline/vendor/fixtext/engine/client.py:128` → `proc = subprocess.run(cmd, ...)`

而 worker 每跑一次校正，就把这个属性**换成可取消代理**：

- `fixtext_ui/fixtext_worker.py:471-473`
  ```python
  # 把引擎客户端的 subprocess 换成可取消代理（只影响本进程内的调用）
  import fixtext.engine.client as _engine_client
  _engine_client.subprocess = _SubprocessProxy(self)
  ```
- `fixtext_ui/fixtext_worker.py:216-219`（代理内部）
  ```python
  if self._job.cancel_requested:
      proc.kill()
      proc.wait()
      raise CorrectionCancelled("已终止替换引擎")
  ```

代理里绑的是**那一次 job** 的 `cancel_requested`。`tests/test_layout_cancel.py:99` 的
`test_correction_job_layout_cancel_cleans_workdir` 真的跑了一次 `CorrectionJob` 并 `job.request_cancel()`，
于是这个代理的 `cancel_requested` **永久为 True**；而 `CorrectionJob.run()` 的 `finally`
只摘了 Python 引擎的取消钩子（`py_engine.set_cancel_check(None)`，第 521-522 行），
**没有把 `fixtext.engine.client.subprocess` 摘回标准库模块**。

于是同一进程里后续任何一次 Go 引擎调用，都会走这个「已取消」的代理 → 抛「已终止替换引擎」。
`test_m5_ex1_runtime.py` 的 5 条 smoke 恰好都在 replace 阶段调 Go 引擎，因此**全部**被这条残留状态打死。

**定性：测试隔离缺陷（全局状态泄漏），不是产品缺陷。**
证据：同一条用例单跑 11 passed；把 `tests/test_layout_cancel.py` 排在前面就 5 failed。
失败与否取决于**别的用例跑没跑过**，与被测代码本身无关。

#### 3.4 修法

在 `tests/conftest.py` 增加一条**用例级 autouse fixture**，把这类进程级全局量在用例之间复位：

```python
_PROCESS_GLOBAL_HOOKS = (
    ("fixtext.engine.client", "subprocess", "出厂值 = 标准库 subprocess 模块"),
    ("fixtext.engine.py_engine", "_cancel_check", "出厂值 = None"),
)

def _reset_process_globals() -> list[str]:
    """把引擎相关的进程级全局量复位到出厂值，返回真正复位过的项。"""
    import subprocess as _stdlib_subprocess
    restored = []
    client = sys.modules.get("fixtext.engine.client")
    if client is not None and getattr(client, "subprocess", None) is not _stdlib_subprocess:
        client.subprocess = _stdlib_subprocess
        restored.append("fixtext.engine.client.subprocess")
    py_engine = sys.modules.get("fixtext.engine.py_engine")
    if py_engine is not None:
        setter = getattr(py_engine, "set_cancel_check", None)
        if callable(setter) and getattr(py_engine, "_cancel_check", None) is not None:
            setter(None)
            restored.append("fixtext.engine.py_engine._cancel_check")
    return restored

@pytest.fixture(autouse=True)
def _isolate_process_globals():
    """每条用例前后各复位一次进程级全局量。"""
    _reset_process_globals()
    yield
    _reset_process_globals()
```

设计要点（这就是「可被同类测试复用」的落点）：

1. **放在 `conftest.py` 的 autouse fixture 里**，任何用例都自动受保护，不需要谁记得写清场代码；
2. **用例前后各复位一次**：用例前复位保证「上一条崩了也不影响这条」，用例后复位保证「这条不污染下一条」；
3. **查 `sys.modules` 而不是直接 import**：引擎模块是靠 `fixtext_pipeline.vendor_bootstrap` 把
   `pipeline/vendor` 塞进 `sys.path` 才导得进来的，在 conftest 里提前 import 会改变全局导入顺序，
   反而可能影响别的用例；
4. **复位目标是「出厂值」而不是「我以为的值」**：client 的出厂值就是标准库 `subprocess` 模块本身，
   py_engine 的出厂值就是 `None`——不需要知道谁装过什么，只要回到出厂状态；
5. **扩展只需往 `_PROCESS_GLOBAL_HOOKS` 加一行**：以后再出现别的进程级全局量泄漏，
   同一条 fixture 直接接管。

#### 3.5 该改测试还是该改实现？——**改测试**（本卡已按此执行）

| | |
|---|---|
| **结论** | 改测试（conftest 复位 fixture），**不动 `fixtext_worker.py`** |
| **理由 1：卡面纪律** | 本卡明确「修法只动测试或最小适配，不得以此为由改业务逻辑」。worker 里那行代理替换是**产品功能**（取消引擎子进程靠它），不是 bug。 |
| **理由 2：这不是产品缺陷** | 产品路径每次 `CorrectionJob.run()` 都会装一个**新的、属于本次 job** 的代理，第二次校正不受影响；被取消的那次 job 的残留只在「同一进程内、job 结束之后又去调引擎」时才致命。产品界面上不存在这种调用序列（引擎只经 `CorrectionJob` 触发）。 |
| **理由 3：修复位置要对** | 泄漏发生在**测试进程**里，正确的隔离边界是「一条用例 = 一份干净的进程级状态」，这是测试基建职责，不是产品职责。 |
| **理由 4：证据支持** | 修复后全量 484/8，5 条 smoke 在**批量**场景下通过；只改测试即可达成目标，无须动业务。 |

> ⚠️ **单列说明（发现但本卡未改，需小组长决策）**
> `fixtext_worker.CorrectionJob.run()` 确实**从不摘掉** `fixtext.engine.client.subprocess` 代理
> （`finally` 只摘了 `py_engine.set_cancel_check`）。今天不影响产品，是因为引擎只有 `CorrectionJob`
> 一条入口；一旦将来出现「不经过 job 直接调引擎」的产品路径（例如引擎预检、词库批量预览），
> 被取消过的进程里那次调用会直接报「已终止替换引擎」。
> 修法很小（`finally` 里把 `subprocess` 还原回标准库模块），但它**属于产品代码改动**，
> 按卡面纪律本卡**不自行决定**，在此单列，等小组长与 F2/F3 合流时统一处置。

---

### 组 2：t31_vocab_merge_click 1 条 —— 测试引用了上游已删的控件

**测试名**：`tests/test_t31_vocab_merge_click.py::test_merge_full_user_click_path`

#### 4.1 断言原文（用例主体仍然有效）

```python
boxes = _row_checkboxes(mod)
assert len(boxes) == 3, f"自定义分级应显示 3 行可勾选，实际 {len(boxes)}"
...
_click(qapp, mod._merge_btn)
assert len(dlgs) == 1, f"点合并后应有 1 个弹窗，实际 {len(dlgs)}"
assert first.windowTitle() == "合并词条（先预览清单）", first.windowTitle()
...
assert second.windowTitle() == "写入词库（二次确认）", second.windowTitle()
...
assert len(mod.store.custom) == 1, f"合并后应保留 1 条，实际 {len(mod.store.custom)}"
kept = mod.store.custom.entries()[0]["word"]
assert kept == "甲词", f"应保留第一条为主词，实际保留「{kept}」"
assert sha_after != sha_before, "确认写入后文件内容必须变化"
assert mod.undo_btn.isVisible(), "合并后提示条上应出现可点的撤销按钮"
...
assert len(mod.store.custom) == 3, f"撤销后应回到 3 条，实际 {len(mod.store.custom)}"
assert _sha(path) == sha_before, "撤销后文件必须与合并前逐字节一致"
```

#### 4.2 实际值

失败发生在**第一条断言之前**——辅助函数取属性就炸了：

```
tests/test_t31_vocab_merge_click.py:68: AttributeError
E  AttributeError: 'VocabModule' object has no attribute 'basis_cb'
```

留证：`evidence/f1_regression/before_fix_merge_click.log`。

#### 4.3 根因

`_row_checkboxes()` 的排除名单写死了两个控件：

```python
return [c for c in mod.findChildren(QCheckBox)
        if c is not mod._chk_all and c is not mod.basis_cb      # ← basis_cb 已不存在
        and not c.isHidden()]
```

- 用例写于 `c883954`（M3-T3.1，2026-10-28），当时界面上确实有「显示设计依据」勾选框；
- 上游提交 **`655f47b`「M5-EX.2: 移除「显示设计依据」入口（BUG-2）」**（2026-10-29）
  把该控件从 `fixtext_ui/vocab_module.py` 删掉了（`git log -S "basis_cb"` 只剩这两条）；
  测试没跟着改 → 每次跑都 `AttributeError`。

**与产品行为无关**：合并链路本身完好，界面元素都还在——
`open_merge`（vocab_module.py:1558）、弹窗「合并词条（先预览清单）」（1565）、
「预览写入」（1576）、`do_merge`（1580）、弹窗「写入词库（二次确认）」（1587）、
「确认写入」（1593）、`_do_merge_commit`（1599）、表头全选 `self._chk_all`（771）、
行内勾选框（813）、提示条撤销 `self.undo_btn`（2065）。

#### 4.4 修法

把排除名单改成「**取得到才排除**」，并补一句来源说明：

```python
def _row_checkboxes(mod):
    """行内勾选框（排除表头那一行的全选）。

    …（原有说明保留）…

    排除名单按「属性存在才算」取：原来还有一个「显示设计依据」的勾选框要排除，
    但它已经在 M5-EX.2（BUG-2）里从界面上删掉了，直接取 ``mod.basis_cb``
    会 AttributeError。改成「取不到就不排除」，界面上以后再增减顶层勾选框，
    这条用例不用跟着改。
    """
    from PySide6.QtWidgets import QCheckBox

    excluded = {id(getattr(mod, name, None)) for name in ("_chk_all", "basis_cb")}
    return [c for c in mod.findChildren(QCheckBox)
            if id(c) not in excluded and not c.isHidden()]
```

要点：**语义完全不变**（仍然排除表头全选、仍然只认「没被显式隐藏」的行内框），
只是不再假设 `basis_cb` 一定存在；将来界面再加/减顶层勾选框，这条用例也不用改。

#### 4.5 该改测试还是该改实现？——**改测试**

| | |
|---|---|
| **结论** | 改测试（辅助函数适配当前界面） |
| **理由 1** | `basis_cb` 被删是**上游有意的产品决策**（BUG-2 修复，移除一个入口）。把控件加回去等于把已修复的 bug 放回去，方向完全错。 |
| **理由 2** | 用例要验的是「合并的真实点击链路通不通」，而 `basis_cb` 只是一个**要排除掉的干扰项**；它没了，排除名单自然少一项，用例意图不受影响。 |
| **理由 3** | 「按属性存在与否构造排除名单」比「写死控件名」更抗上游改动，**同类测试**（凡是按控件名定位 UI 的用例）都可以照这个写法加固。 |
| **理由 4** | 修复后用例**跑完了完整链路**：勾选 3 条 → 合并 → 预览写入 → 确认写入 → 撤销，且 sha256 逐字节校验全部通过——说明产品行为本来就是对的，错的只是测试脚手架。 |

---

## 四、修法可复用性

| 修法 | 复用方式 | 同类测试怎么用 |
|---|---|---|
| conftest `_isolate_process_globals` | **autouse，全局生效** | 任何用例留下的进程级全局量都会被自动复位；新增全局量只要往 `_PROCESS_GLOBAL_HOOKS` 加一行 |
| `_row_checkboxes` 的「取得到才排除」 | 模式可复制 | 凡按控件名定位 UI 的用例，构造排除名单时统一用 `getattr(obj, name, None)`，上游删/加控件都不再炸 |

两条修法都不依赖具体测试名，**对同类测试（全局状态类 / UI 定位类）直接生效**。

---

## 五、回归对照（前后失败集合差集）

**基线失败 14 条**（`evidence/f1_regression/failures_baseline.txt`）→ **修复后失败 8 条**
（`evidence/f1_regression/failures_after_fix.txt`）：

```
=== 基线有 / 修复后无（本卡清零的 6 条） ===
tests/test_m5_ex1_runtime.py::test_smoke_default_no_extra_rounds
tests/test_m5_ex1_runtime.py::test_smoke_preprocess_only
tests/test_m5_ex1_runtime.py::test_smoke_skip_layout
tests/test_m5_ex1_runtime.py::test_smoke_strict_only
tests/test_m5_ex1_runtime.py::test_smoke_zhuyin_after_main_and_after_raw
tests/test_t31_vocab_merge_click.py::test_merge_full_user_click_path

=== 修复后有 / 基线无（新增失败，必须为空） ===
（空）
```

**6 条在批量场景下 passed 的直接证据**（`evidence/f1_regression/fix_batch*.log`）：

| 批 | 结果行 |
|---|---|
| b3 | `2 failed, 108 passed in 12.70s` —— 5 条 m5_ex1 smoke 全在其中 passed |
| b4 | `1 failed, 67 passed in 46.32s` —— merge_click passed |
| 全量 | 484 passed / 8 failed |

另有**两条最小复现对照**留证：

- `before_fix_pair_repro.log`：修复前 `test_layout_cancel.py + test_m5_ex1_runtime.py` → **5 failed, 8 passed**
- `after_fix_pair_repro.log`：修复后同两文件 + `test_t31_vocab_merge_click.py` → **14 passed**

---

## 六、明确未动的 8 条（F2 / F3 范围）

本卡**没有顺手改**任何一条，修复前后失败集合里它们逐条一致：

| # | 失败用例 | 归属 | 现象（未深查） |
|---|---|---|---|
| 1 | `test_ex4d_topbar_popup_anchor::test_more_menu_items_still_work` | F2 | 顶栏「更多」菜单项 |
| 2 | `test_m5_ex4_1_layout::test_export_actions_before_target` | F2 | `AttributeError: 'ExportModule' object has no attribute '_lay_actions'`（属性名漂移，同 4.3 那类） |
| 3 | `test_m5_ex4_1_layout::test_import_no_empty_state_safety_after_shelf` | F2 | 第 43 行 `assert False` |
| 4 | `test_t31_vocab_store::test_search_scoped_to_tier` | F3 | `KeyError: 'b2'` |
| 5 | `test_t31_vocab_ui::test_module_shows_real_builtin_count` | F3 | 302957 vs 304255（词条口径） |
| 6 | `test_t31_vocab_ui::test_search_hit_count_matches_data_layer` | F3 | 18 vs 9（命中口径） |
| 7 | `test_t32_vocab_safety::test_custom_and_builtin_are_physically_separate` | F3 | `IsADirectoryError: data/rules/bags` |
| 8 | `test_t37_vocab_bridge::test_custom_word_takes_effect_in_real_correction` | F3 | `KeyError: 'applied_words'` |

> A 组「全量 0 failed」由 F1+F2+F3 三卡合流达成；本卡只保证这 6 条清零且不引入新失败。

---

## 七、改动清单（业务逻辑改动 = 0）

```
tests/conftest.py                   | 65 +++++++++++++++++++++++++++++++++++++
tests/test_t31_vocab_merge_click.py | 13 +++++---
```

外加新增（不进产品路径）：

- `tools/run_regression.sh` —— 5 批全量回归脚本（可复现本文档全部数字）
- `evidence/f1_regression/` —— 基线 / 修复后 5 批日志、失败清单、最小复现对照
- `FixTextGUI_V1.1-F1_失败取证与修法说明.md` —— 本文档

**产品代码（`fixtext_ui/`、`pipeline/`、`data/`）一行未改。**

---

## 八、未验证范围与风险

1. **未跑「一条 pytest 一次跑完 492 条」**：1 核沙箱实测会在 600s 上限内超时；
   本卡按 5 批跑（与基线口径一致），分批边界处仍存在「跨批状态不共享」的可能——
   但污染形态是**同进程内**的模块属性，跨批本来就不共享，因此该风险与基线同源、不影响结论。
2. **未在真实显示器环境跑**（全程 `QT_QPA_PLATFORM=offscreen`）；离屏下控件命中与真实环境可能存在差异，
   但本次改的是「测试隔离」与「排除名单构造」，不依赖像素命中。
3. **`fixtext_worker` 残留代理未在产品侧修复**（见 3.5 的单列说明），属已识别、未处置项。
4. **未验证 Windows / macOS**：本卡只在本沙箱（Linux）实测。
5. 合并包 `.git` 保留、master 与 svg-icons 分支未动；本卡与 E1 卡各自基于 dev `7be8d88` 独立开发，
   **未 rebase、未 merge 任何其它分支**。

---

## 九、交付与复现

```bash
# 1) 解包
unzip FixTextGUI_V1.1-F1_清零m5_ex1与merge_click_v1.zip -d pkg && cd pkg

# 2) 预置首启标记（否则首启向导模态卡死）
mkdir -p workspace && printf '[General]\nwizardSeen=1\n' > workspace/settings.ini

# 3) 全量回归（5 批）
bash tools/run_regression.sh /tmp/f1_logs
# 期望：484 passed / 8 failed；剩下的 8 条全是 F2/F3 范围

# 4) 只看本卡 6 条
export PYTHONPATH=/home/gem/.aily/.cli/py312/lib/python3.12/site-packages:$PWD:$PWD/fixtext_ui
export QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python3.12 -m pytest tests/test_m5_ex1_runtime.py tests/test_t31_vocab_merge_click.py -q
# 期望：12 passed
```
