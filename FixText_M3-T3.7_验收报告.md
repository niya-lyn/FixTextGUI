# FixText M3-T3.7 验收报告 · 词库生效与查重执行收口修复

> 起点：`FixText_M3-T3.6_验收断言修正_v2.zip`（file_token `WpGJbAed1ovtGyxhwS2c6stfnMf`，
> 解包于干净目录 `/tmp/m37/pkg`，git 基线 `6dd6ed4`，`git status` 干净）。
> 本卡修复独立质检 B 册判定的两项不满足收口条件缺陷：P0 自定义词不生效、P1 查重弹窗假按钮。

## 1. 修了什么

### 1.1 P0：自定义词 → 替换引擎的桥（排期 §2.4.2③）

**缺陷**：`stages/replace.py` 只读随包 `data/rules/*.json`；用户在「我的词库」里新增/合并/删除的词存在
`workspace/vocab/custom_vocab.json`，两棵树之间没有任何桥——界面六处承诺「自动生效」都是空的。

**修复（4 个提交中的 `86f3c37`）**：

- 新增 `pipeline/fixtext_pipeline/vocab_bridge.py`（335 行）：运行前把「随包词库 + 我的词库自定义词」
  合成为**派生规则** `before.json`/`after.json`，落在用户区 `workspace/vocab/derived_rules/`；
  `data/rules/*.json` 只读不改。合成语义：自定义词整体前置、长词优先（引擎按数组顺序先命中者胜，
  已实测确认）；同原词去重、原词等于替换值、空值一律跳过且**每条带原因**；compose_key 幂等缓存，
  输入没变不重写盘。
- `stages/replace.py`：`run()` 先生成派生规则，`RuleSet.from_files` 读派生文件；日志明示
  「通用 N 条 + 自定义生效 M 条」；报告新增 `derived_rules` 块（含 compose_key、两侧 sha、跳过原因）。
- `fingerprint()` 改为按**实际生效的那份规则**取 sha——自定义词一改派生文件就变，指纹必变，
  断点恢复不会拿旧正文当新结果。
- `config.py` 加 `custom_vocab_path` / `derived_rules_dir`（默认指向产品用户区，`to_dict`/`from_state` 同步）；
  `fixtext_worker.CorrectionJob` 打通这两个参数。
- 自定义词库文件坏了**不阻断校正**：降级为空词库并把原因写进运行摘要。

### 1.2 P1：查重弹窗收口（排期 §2.4.1/§2.4.3）

**缺陷**：`vocab_module.open_dup` 的「暂时不处理」「我知道了」两个按钮不做任何动作；
超过 20 组只列前 20 组。

**修复（`2c32c53`）**：弹窗定位改为**只读全量清单**——标题明说「只读，不会改动词库」，正文写明
处理动作走工具条的「合并」「删除选中」（各自先预览、二次确认、可撤销）；两组以上装进滚动区
**全量渲染**（不再截断 20 组）；底部只留「关闭」。模块暴露 `_dup_view`（total/shown/readonly）
供验收与自检读取。

## 2. 验收实测（全部为真实运行数字，命令见 §5）

### 2.1 P0 正向：真实 788 章语料 + 「萧衍 → 萧彦」

`tools/accept_t37.py` S1：复制真实《炮火弧线》EPUB（788 章），仅在第一章正文插入一句含 3 处
「萧衍」的文字（其余字节不动），「我的词库」加一条「萧衍 → 萧彦」，跑完整六阶段
（与界面同一条 `CorrectionJob` 链路）后导出纯文本：

| 项 | 实测值 |
| --- | --- |
| 章节数 | 788 |
| 校正耗时 | 14.07 s |
| 命中数 | 5102（历史基线 5100 + 自定义词 2 条合并命中） |
| 替换前正文 萧衍/萧彦 | 3 / 0 |
| 替换后正文 萧衍/萧彦 | **0 / 3** |
| 导出 TXT 萧衍/萧彦 | **0 / 3** |
| 导出 TXT sha256 | `7d9cca1b4759f4e35860b5e6b02330963c576d91526637fa9e8f08b5894b5efe`（10,308,565 字节） |
| 派生规则 | 通用 304,255 + 自定义生效 1 = 304,256 条 |

### 2.2 P0 反向对照（断言不是恒真的证明）

S2：**同一份语料、同一个 Go 引擎**，喂给移除桥接的代码（起点包基线副本 `/tmp/m37_baseline`，
其 `CorrectionJob` 不接受 `custom_vocab_path`、`vocab_bridge.py` 不存在）：

- 导出 TXT：萧衍 **3** / 萧彦 **0**——去掉桥接，自定义词一个都不生效。
- 与 §2.1 对照成立：同一断言在无桥接代码上不通过。

### 2.3 P0 只读与指纹

- S3：跑完全部用例后，`data/rules/before.json` sha256 `e961f82e…`、`after.json` `7dd53ae6…`
  与开工前一致——**随包词库原件一个字节没动**。
- S4：自定义词替换值「萧彦」改「萧彦二」，`ReplaceStage.fingerprint()` 前后不同
  （`fp_before != fp_after_change`，实测 PASS）。
- 附加自证（`tests/test_t37_vocab_bridge.py`）：自定义词为空时派生文件与出厂词库**逐字节一致**
  （sha 相等），即内置 304,255 条的既有行为不变；历史基线命中数 5100 在无自定义词场景复现。

### 2.4 P1 查重清单实测

S5（真实界面构建 + 弹窗读取，截图 `evidence/t37_dup_dialog.png`）：造 25 组同词异值冲突——

- 界面渲染分组数 **25/25**（`_dup_view = {total:25, shown:25, readonly:true}`）；
- 按钮只剩 `×` 与「关闭」，「我知道了」「暂时不处理」已不存在；
- 点完弹窗前后 `custom_vocab.json` sha256 不变（文件未被动）。

### 2.5 执行位

S6：用 `zip` 命令行打包快照、解压到干净 `/tmp/t37_clean`——引擎文件 mode `755`、`os.access(X_OK)=True`，
`-h` 实跑返回用法说明（退出码 1，符合预期，证明可执行）。

## 3. 回归（在最终代码上全部重跑）

| 项 | 结果 | 说明 |
| --- | --- | --- |
| `pytest tests` | **204 passed**（265.30s） | 基线 194 + 本卡新增 10（`test_t37_vocab_bridge.py`：合成语义 4 项、幂等/坏词库 2 项、正向 1、反向对照 1、指纹 1、查重只读全量 1、空词库字节一致 1） |
| `verify_m2t21` | 通过 | 令牌 71/71；截图 7 张重生成 |
| `accept_t23` | PASS | A/B/B2/C 全场景，确定性 `all_equal=true`，露出 0/1407 |
| `accept_t27` | PASS | 8 项检查全通过，hits=5100、词条行 4817 |
| `accept_t28` | PASS | 向导文案命中 0 |
| `accept_t210` | PASS | 108 处问题，重新导出 sha 与基线一致，露出 0/452 |
| `accept_t31` / `accept_t32` | PASS | 含 `t31_tests.txt` / `t32_tests.txt` 重跑（exit 0） |
| `accept_t33` | **ALL PASS · 18/18** | `_t33_prepare_run.py` 重跑后执行 |
| `accept_t34` | PASS | 九场景 |
| `accept_t35` | ALL PASS | 含 S4 零露出 0/676 |
| `check_t35_coexist` | ALL PASS | 冷启动子进程自检 |
| `smoke_e2e` | PASS | 端到端：导入→取消→复跑，露出 0/745 |
| `accept_t37`（本卡） | 6/6 PASS | S1–S6，总耗时 43.06s |

**证据时间戳口径**（T3.6 教训）：最后一次**代码**提交 `cbeda90`（2026-10-28 12:07:01）之后，
`evidence/`、`screenshots/`、`verify_report.json` 全部重新生成——`find evidence screenshots -type f ! -newermt <代码提交时间>`
结果为空（`evidence/pytest_full.txt` 为收尾落盘，内容即本次 204 passed 输出）。证据以
`54fb22b M3-T3.7: 全量验收证据重生成` 提交入库。

**执行顺序注意**（复跑者须知）：`accept_t210` 会清空 `pkg/runs/`，因此 `accept_t33` 必须在
`_t33_prepare_run.py` 之后、`accept_t210` 之后执行；`accept_t23` 连跑两轮前要清 `t23_runs`。

## 4. 交付内容

- `pipeline/fixtext_pipeline/vocab_bridge.py`（新增，335 行）
- `pipeline/fixtext_pipeline/stages/replace.py`（派生规则接入 + 指纹）
- `pipeline/fixtext_pipeline/config.py`（两个新字段）
- `fixtext_ui/fixtext_worker.py`（`CorrectionJob` 透传）
- `fixtext_ui/vocab_module.py`（查重弹窗只读全量 + `_dup_view`/`_dup_modal`）
- `tests/test_t37_vocab_bridge.py`（新增，10 项）
- `tools/accept_t37.py`（新增，S1–S6 验收脚本）

Git 提交（均含 M3-T3.7）：

```
86f3c37 M3-T3.7 (P0): 自定义词进替换引擎——新增 vocab_bridge 派生规则桥……
2c32c53 M3-T3.7 (P1): 查重弹窗改只读全量清单……并补 10 项 T3.7 用例
cbeda90 M3-T3.7: 验收脚本 accept_t37（S1-S6 六项实测……全 PASS
54fb22b M3-T3.7: 全量验收证据重生成（13 脚本 + 204 项测试……
```

## 5. 复现命令

```bash
# 环境（沙箱重建后）
python3.12 -m pip install --target /home/gem/.aily/.cli/qtenv/lib/python3.12/site-packages PySide6

# 全量测试（204 项）
cd <包根>
PYTHONPATH=/home/gem/.aily/.cli/qtenv/lib/python3.12/site-packages \
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python3.12 -m pytest tests -q

# 本卡验收（S1–S6；S2 需要无桥接基线副本，环境变量 FIXTEXT_T37_BASELINE 指向它）
PYTHONPATH=/home/gem/.aily/.cli/qtenv/lib/python3.12/site-packages \
QT_QPA_PLATFORM=offscreen python3.12 tools/accept_t37.py

# 既有验收（前置：语料与基线放 <pkg同级>/in/，基线成品 06_restore/paohuo_restored.epub）
python3.12 tools/verify_m2t21.py
python3.12 tools/accept_t23.py
python3.12 tools/accept_t27.py && python3.12 tools/accept_t28.py && python3.12 tools/accept_t210.py
python3.12 tools/accept_t31.py && python3.12 tools/accept_t32.py
python3.12 tools/_t33_prepare_run.py && python3.12 tools/accept_t33.py
python3.12 tools/accept_t34.py && python3.12 tools/accept_t35.py && python3.12 tools/check_t35_coexist.py
python3.12 tools/smoke_e2e.py 2> evidence/smoke_stderr.log
```

## 6. 未验证范围

- 导出 EPUB「可直接导入主流阅读器」的最终确认仍属 M4/M5 真机范围（沿 M2-T2.7 口径，沙箱内以结构校验代替）。
- S2 反向对照依赖基线副本目录（`/tmp/m37_baseline`，由起点 zip 解出）；脱离该目录时 S2 报 skipped，不影响其余五项。
