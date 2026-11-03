# V1.1-F2 失败取证与修法说明

**卡号**：V1.1-F2（A 组第二卡，依赖 F1 已收口）
**基线包**：`FixTextGUI_V1.1-MRG.1_合并F1与E1进dev_v1.zip`（md5 `f7ea957b86ec86a57ba521703b387ec3`，下载后回读一致）
**dev 基线 HEAD**：`fc28253`（F1 `6738c9b` + E1 `5c1f413` 已合并）
**本卡提交**：`f48b2d2`（单个 dev 提交，未自行 rebase / merge）
**作者**：Doubao Agent Engineer A `<doubao-engineer-a@local>`
**未动分支**：`master` 仍 `245b7cd`、`svg-icons` 仍 `93b2002`（已核）

---

## 0. 结论先说

**这三条失败全部是测试缺陷，不是产品缺陷。** 业务逻辑一行未改，改动只落在两个测试文件（`tests/test_ex4d_topbar_popup_anchor.py` 9 行、`tests/test_m5_ex4_1_layout.py` 22 行，共 27 增 4 删）。

| # | 用例 | 判定 | 修法方向 |
|---|---|---|---|
| 1 | `test_ex4d_topbar_popup_anchor.py::test_more_menu_items_still_work` | 测试缺陷：引用了产品已删除的菜单项 | 改测试 |
| 2 | `test_m5_ex4_1_layout.py::test_export_actions_before_target` | 测试缺陷：引用了产品已改名的属性 | 改测试 |
| 3 | `test_m5_ex4_1_layout.py::test_import_no_empty_state_safety_after_shelf` | 测试缺陷：误用 Qt 显隐语义 | 改测试 |

三条的共同机制是同一类问题：**测试没有跟着产品侧「有意变更」同步更新**，而产品变更本身都是已发布、已验收的既有提交（`655f47b`、`720d915`），不属于本卡范围。

**全量回归口径（`tools/run_regression.sh` 五批）**：`484 passed / 8 failed` → **`487 passed / 5 failed`**，新增失败 **0**，剩余 5 条与 F3 词库口径清单**逐条一致**。

---

## 1. 取证方法

每条按四步做：① 复现并抓断言原文与实际值；② 反查该符号在 git 里的变更史，定位是哪次产品提交让它变化；③ 判断是「产品被改坏了」还是「测试没跟上」；④ 决定改测试还是改实现，并说明理由。

反查用的是 `git log -S "<符号>" -- <路径>`，而不是凭记忆猜。

---

## 2. 逐条取证与修法

### 2.1 `test_more_menu_items_still_work`

**断言原文（改前）**

```python
assert texts == [
    "新手向导（重新观看）", "重新生成样式表",
    "打开设计依据目录", "关于 FixTextGUI",
], f"☰ 菜单项变了：{texts}"
assert len(captured[0]) == 2, f"☰ 菜单分隔线数量变了：{captured}"
```

**实际值（改前实测）**

```
E       AssertionError: ☰ 菜单项变了：['新手向导（重新观看）', '重新生成样式表', '关于 FixTextGUI']
E         At index 2 diff: '关于 FixTextGUI' != '打开设计依据目录'
E         Right contains one more item: '关于 FixTextGUI'
```

实际菜单是 **3 项 + 2 条分隔线**，测试期望 **4 项 + 2 条分隔线**，差的正是 `"打开设计依据目录"`。

**根因：产品有意删除，测试未同步。**

`git log -S "打开设计依据目录"` 给出两次提交：

```
655f47b M5-EX.2: 移除「显示设计依据」入口（BUG-2）
2ca743f M2-T2.6: 移植顶栏设置/帮助/菜单，词库与历史页接入主窗口
```

`655f47b` 的提交信息写明「各页开关、设置项与菜单项一并去掉；Card basis 标签保留但始终隐藏」，其 `main_window.py` diff：

```diff
     def _act_more(self):
-        """菜单：新手向导 / 重新生成样式表 / 打开设计依据目录 / 关于。"""
+        """菜单：新手向导 / 重新生成样式表 / 关于。"""
         ...
-        a_open = menu.addAction("打开设计依据目录")
-        a_open.triggered.connect(self._open_reference)
```

同时删掉了 `_open_reference()` 方法本体。产品当前 `_act_more` 实测只 `addAction` 三项。

另一个易混点已排除：`关于 FixText V1 → 关于 FixTextGUI` 这次改名（`6dbff24`，M6-T6.2）**测试已同步过了**，不是本次失败的原因。

**修法与理由：改测试。**

`"打开设计依据目录"` 背后是整个「显示设计依据」功能入口，产品在 `655f47b` 里主动摘除（BUG-2 的既定决定），`_open_reference` 方法已不存在。若为了让这条旧测试通过而把菜单项加回去，等于**在 F2 卡里回滚一次已验收的产品决策**，属于越界改业务逻辑，也正是本卡纪律禁止的。所以只能让测试追上产品现状。

**断言强度没有放松**：仍然逐项列出全部菜单文案（三项少一项 / 多一项 / 换一项都会照旧失败），分隔线仍固定断言 2 条。

### 2.2 `test_export_actions_before_target`

**断言原文（改前）**

```python
mod = ExportModule()
cl = mod._content_w.layout()
i_actions = _index_of(cl, mod._lay_actions)   # ← 崩在这里
i_result = _index_of(cl, mod._w_result)
i_target = _index_of(cl, mod._w_target)
assert i_actions < i_result < i_target
```

**实际值（改前实测）**

```
E       AttributeError: 'ExportModule' object has no attribute '_lay_actions'. Did you mean: '_w_actions'?
```

**根因：属性被产品改名，测试未同步。**

`git log -S "_lay_actions"` 给出三次提交，其中决定性的是 `720d915`（M5-EX.7）：

```diff
         self._w_book = self._book_bar()
-        self._lay_actions = self._actions()
+        self._w_actions = self._actions()
         ...
         cl.addWidget(self._w_book)
-        cl.addLayout(self._lay_actions)
+        cl.addWidget(self._w_actions)
```

原因在 `_actions()` 的返回类型也变了：`44cb0f1`（M5-EX.4.1）先把主操作置顶引入 `_lay_actions`（返回 `QHBoxLayout`，用 `addLayout` 挂），`720d915` 随后把它改成一个带 `#Hero` 渐变底色的 `QFrame`（返回 `QFrame`，改用 `addWidget` 挂）。属性名与布局挂法都是产品**有意重构**。

产品当前实测：

```
self._w_actions = self._actions()      # fixtext_ui/export_module.py:141
self._w_result  = self._result_card()
self._w_target  = self._target_card()
cl.addWidget(self._w_actions)          # 149 → 150 → 151
cl.addWidget(self._w_result)
cl.addWidget(self._w_target)
```

所以 **`actions < result < target` 这个被测语义完好无损**，坏的只是过时的属性名。

**修法与理由：改测试。**

断言要验的是「三段顺序」，顺序没变；导出的主操作被包成 QFrame 是 UI 对齐时的既定重构。测试要点已不存在（`_lay_actions`），只能跟着改名；把 `_lay_actions` 加回产品会给代码留一个与 QFrame 语义不符的别名，属于为迁就测试而污染业务代码。

`_index_of` 已经同时支持 `item.widget()` 与 `item.layout()`，所以 `addWidget` / `addLayout` 两种挂法都吃得下，**断言函数本身无需改动**。

### 2.3 `test_import_no_empty_state_safety_after_shelf`

**断言原文（改前）**

```python
mod = ImportModule(tmp_path / "ws")
assert not hasattr(mod, "empty_state")
assert hasattr(mod, "safety_card")
assert mod.workspace_card.isVisible()          # ← 崩在这里
root = mod.layout()
assert _index_of(root, mod.workspace_card) < _index_of(root, mod.safety_card)
```

**实际值（改前实测）**

```
E       assert False
E        +  where False = <built-in method isVisible of Card object ...>
E        +  where ... = fixtext_widgets.Card(0x2e614000, name="Card") at 0x2e614000
```

**根因：误用 Qt 显隐语义（并带出一个被这条失败长期掩盖的清理缺失）。**

`isVisible()` 的语义是「**实际**可见」，要求**整条父链都已 show 且自身未被隐藏**。本用例只 `ImportModule(tmp_path / "ws")` 构造模块、全程没调 `show()`，窗体和所有子控件都不在屏幕上，`isVisible()` 必然 `False`——**断言失败与产品行为无关**。

产品侧其实是**主动把它设为显示**的，实测 `fixtext_ui/import_module.py:596`：

```python
def _refresh_workspace(self) -> None:
    books = self.shelf.books()
    ...
    # 书架卡始终可见：无书时弱提示，有书时列清单（不再整页 EmptyState）
    self.workspace_card.setVisible(True)
```

`_refresh_workspace` 在 `__init__` 末尾就被调用，且该行**没有前置的 `setVisible(False)`**，构造完即处于「要显示」状态。三条实测印证：

| 状态 | `isVisible()` | `isHidden()` | `isVisibleTo(mod)` |
|---|---|---|---|
| 构造后未 show | `False` | `False` | `True` |
| `mod.show()` 后 | `True` | `False` | `True` |

`isHidden() == False` 说明它自己没被隐藏，`isVisibleTo(mod) == True` 说明「相对本模块它是要显示的」——差的只是祖先窗口没 show。

**修法与理由：改测试（改用 `isVisibleTo(mod)`）。**

同包已有多处用这个口径，且都不需要 show 窗口：

- `tests/test_ex2b_empty_states.py:51` → `assert mod.workspace_card.isVisibleTo(mod), "无书时书架卡仍显示"`
- `tests/test_ex3a_shelf.py:296`、`:352` → `win.import_module.workspace_card.isVisibleTo(win.import_module)`
- `tools/accept_ex3a.py:192` → 同款

也就是说，这条用例**偏离了包内既有的正确惯例**。`isVisibleTo(mod)` 问的是「相对 mod，它是不是要显示」，恰好等价于本条 SYNC-3「无书用书架弱提示、不再整页空态」要验的东西，且不受祖先窗口 show 状态干扰。

若改用 `mod.show()` 再 `isVisible()`，在离屏后端更脆（依赖窗口系统行为），不如跟既有惯例走。**断言强度不变**：产品只要真把书架卡隐藏（`setVisible(False)`）或整页空态回归，两种写法都会失败——已做反向验证（见 §4）。

### 2.4 修好之后新暴露的退出阶段段错误（必须记录）

这是本卡最需要留意的一点：**改 2.3 不只让一条断言变绿，它第一次让该用例走到了函数末尾**，于是把一个长期被失败掩盖的清理缺失翻了出来。

**现象**：单跑通过（`1 passed`），但进程退出码 **139**（或 134）。

```
...                                                                      [100%]
1 passed in 0.90s
Fatal Python error: Segmentation fault
Current thread 0x00007fb3ff511740 (most recent call first):
  <no Python frame>
```

换 `-X faulthandler` 看是 `<no Python frame>`——崩在解释器退出、Python 栈已清空之后。换成更小的组合会看到 `pure virtual method called` / `malloc_consolidate(): unaligned fastbin chunk detected`，都是 Qt/shiboken 在析构期出事的典型表现。

**为什么基线不崩**：基线时这条用例一进函数第 3 行就 `AttributeError`，`mod` 从未跑到 `mod.shutdown()`，失败状态掩盖了后续清理问题。**这不是我改出来的新缺陷，而是原用例本就缺的一步收尾**。

**定位过程（都是实跑，不是推断）**

| 实验 | 结果 |
|---|---|
| 单独跑 `test_export_actions_before_target` | 改后 EXIT=139；基线 EXIT=1 |
| `test_m5_ex3_import + test_m5_ex4_1_layout` | 改后 6 passed 但 EXIT=139；基线 2 failed 但 EXIT=1 |
| 顺序反转（ex4_1 在前） | 仍 EXIT=134，**与顺序无关** |
| 只保留 export 用例、去掉 import 用例 | 仍 EXIT=139 → **触发源是 export 用例** |
| 只把 import 断言回退成基线失败态、保留 export 修法 | 仍 EXIT=139 → **与 2.3 的改法无关** |
| 去掉 `mod.shutdown()` 试跑 | 仍崩（`malloc_consolidate`）→ **不是 ImportModule.shutdown 的问题** |
| 纯脚本里构造 `ExportModule` 后 `close()+deleteLater()+processEvents()+del+gc` | EXIT=0 |
| 最小 pytest 模块：跑到底（1 passed） | EXIT=139 |
| 最小 pytest 模块：入口就 AttributeError（1 failed） | EXIT=1 |

**根因**：`ExportModule()` 是个 `QWidget`，用例跑到底后实例一直活着（测试帧结束只是丢引用、没人把它交给 Qt 销毁），等到解释器退出、`QApplication` 已析构之后 shiboken 才去销毁它——此时底层 Qt 对象已失效，于是段错误。

**修法**：在用例末尾补 `mod.deleteLater()`，把模块交还 Qt 销毁。

```python
    assert i_actions < i_result < i_target, (...)
    # V1.1-F2：用例跑到底之后必须把模块交还 Qt 销毁。
    mod.deleteLater()
```

**为什么这样修是对的**：同包早有同款惯例——`tests/test_export_meta_rebind.py` 的 `export_mod` fixture 就是 `yield mod; mod.deleteLater()`。本用例只是之前从没跑到过这句，现在补齐。属**测试侧资源清理**，不碰业务代码。

**修后实测**：`ex4_1::export` 单独 `EXIT=0`；`ex3_import + ex4_1` `EXIT=0`；整批 3 `110 passed, EXIT=0`。全量五批日志再扫 `Segmentation fault|core dumped|consolidate|pure virtual|Aborted` → **无崩溃痕迹**。

---

## 3. 验收：全量五批回归（这才是判据）

单跑通过不算修好。按本卡要求用包内 `tools/run_regression.sh` 的**五批切分**（按测试文件名字母序连续段，101/89/110/68/124 = 492 条）复跑，改动前后各跑一轮。

### 3.1 改前（基线，dev `fc28253` + 本卡未生效）

```
=== batch 1 ===  1 failed, 100 passed in 209.73s (0:03:29)
=== batch 2 ===  89 passed in 12.80s
=== batch 3 ===  2 failed, 108 passed in 12.50s
=== batch 4 ===  1 failed, 67 passed in 45.90s
=== batch 5 ===  4 failed, 120 passed in 95.60s (0:01:35)
```

→ **484 passed / 8 failed**

### 3.2 改后（dev `f48b2d2`）

```
=== batch 1 ===  101 passed in 206.47s (0:03:26)
=== batch 2 ===  89 passed in 10.17s
=== batch 3 ===  110 passed in 10.29s
=== batch 4 ===  1 failed, 67 passed in 45.12s
=== batch 5 ===  4 failed, 120 passed in 97.08s (0:01:37)
```

→ **487 passed / 5 failed**

### 3.3 失败清单差集（机器算，不手抄）

改后剩余 5 条：

```
FAILED tests/test_t31_vocab_store.py::test_search_scoped_to_tier
FAILED tests/test_t31_vocab_ui.py::test_module_shows_real_builtin_count
FAILED tests/test_t31_vocab_ui.py::test_search_hit_count_matches_data_layer
FAILED tests/test_t32_vocab_safety.py::test_custom_and_builtin_are_physically_separate
FAILED tests/test_t37_vocab_bridge.py::test_custom_word_takes_effect_in_real_correction
```

与 F3 清单（`t31_vocab_store` 一条、`t31_vocab_ui` 两条、`t32_vocab_safety` 一条、`t37_vocab_bridge` 一条）**逐条一致**。

差集运算：

```
新增失败（comm -13 改前 改后）→ 空（无输出）
已清零（comm -23 改前 改后）→
  test_ex4d_topbar_popup_anchor.py::test_more_menu_items_still_work
  test_m5_ex4_1_layout.py::test_export_actions_before_target
  test_m5_ex4_1_layout.py::test_import_no_empty_state_safety_after_shelf
计数：after=5  before=8
```

**新增失败 0**，三条目标用例清零，另 5 条原样不动。

---

## 4. 反向验证：改后的断言仍能抓住真实回归

只把断言改到「现在能过」，有变空转的风险，所以逐条做反向注入（把产品按「回归会怎么坏」的方式临时改坏，确认断言仍 FAIL）。全部通过临时脚本执行，**未写回仓库**。

| 负控 | 注入 | 结果 |
|---|---|---|
| 1 | 把 `_w_actions` 从 content 布局移除后重挂到末尾（主操作沉底） | index = `7 / 1 / 2` → `actions < result < target` **不成立，断言会 FAIL** |
| 2 | 把 `workspace_card.setVisible(False)`（真隐藏书架卡） | `isVisibleTo(mod)` = **False，断言会 FAIL** |
| 3 | 把 `safety_card` 插到布局首位（参考区跑到书架之前） | index = `5 / 0` → `shelf < safety` **不成立，断言会 FAIL** |

菜单那条不需要额外注入——它逐项比对 `texts` 列表本身，与分隔线计数同一条断言，少一项/多一项/换一项都会失败（改前就是因为多一项而失败，说明它确实在起作用）。

---

## 5. 业务代码改动情况

**零。** `git show --stat f48b2d2` 的代码侧只有两个测试文件：

```
 tests/test_ex4d_topbar_popup_anchor.py |  9 +++++++--
 tests/test_m5_ex4_1_layout.py          | 22 ++++++++++++++++++++--
 2 files changed, 27 insertions(+), 4 deletions(-)
```

（另有 `evidence/f2_regression*/` 证据留档。）

三条判为测试缺陷、方向都是改测试，因此**没有触发「须先停下等小组长确认」的条件**。

---

## 6. 打包与干净解压自检

- 打包用 `zip` CLI（不用 python zipfile，避免丢执行位），**保留 `.git`**。
- 排除：`workspace/`、`runs/`、`logs/`、`导出/`、`__pycache__/`、`.pytest_cache/`。
- 包内**不得夹带 `settings.ini`** 与 **vocab 运行时产物**。
- 干净解压后 `opens_on_first_run() == True`（实现为 `AppSettings().value("wizardSeen","0") != "1"`，即包里没有带 `wizardSeen=1` 的 `settings.ini`）。

具体结果见文末「交付校验」。

---

## 7. 未处置 / 留给后续卡的事项

1. **F3 的 5 条词库口径失败**按要求原样保留，本卡一条未碰，归 F3 处理。
2. **2.4 暴露的清理缺失只在测试侧补齐**。若将来产品侧 `ExportModule` 也需要在窗口关闭时主动 `deleteLater`（当前未见问题，主窗口关闭由 Qt 统一销毁子控件），那属于产品改动、与显隐语义无关，不建议塞进本卡。
3. 本卡**未**跑 `tools/accept_t*` 系列验收脚本（不在本卡验收判据内，且部分脚本会 `rmtree` 包内 `runs/`、需特定顺序预跑）。回归口径以 `run_regression.sh` 五批为准。

---

## 8. 环境与命令（可复现）

```bash
# 环境
python3.12            # /usr/local/bin/python3.12
pytest 8.3.5          # /home/gem/.aily/.cli/py312/lib/python3.12/site-packages
QT_QPA_PLATFORM=offscreen
PYTHONPATH=<site-packages>:<pkg> :<pkg>/fixtext_ui
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1     # 系统 pytest 9.1.1 的 libtmux 插件会崩会话

# 跑测试前预置（本卡按任务约定预置过；包内不打包）
mkdir -p workspace && printf '[General]\nengine=python\nwizardSeen=1\n' > workspace/settings.ini

# 全量回归（五批）
bash tools/run_regression.sh <日志目录>
```

三条目标用例单跑复现命令：

```bash
python3.12 -m pytest \
  tests/test_ex4d_topbar_popup_anchor.py::test_more_menu_items_still_work \
  "tests/test_m5_ex4_1_layout.py::test_export_actions_before_target" \
  "tests/test_m5_ex4_1_layout.py::test_import_no_empty_state_safety_after_shelf" \
  -p no:cacheprovider -q
```
