# FixText T0.2 · 词库 JSON 迁移交付包（v1）

把 FixText 的 PHP 数组词库迁移为正式 JSON 词库，并交付**可一键重跑**的迁移流程。
本包由 P0 前置验证脚本演进而来，补齐了 P0 未做的三件事：**PHP 闭包显式检测与报警**、
**strictMap 瑕疵的数据清洗**、**一键重跑入口 + 产物装配 + 自验报告**。

任务卡：M0 · T0.2 词库 JSON 迁移落地（只做词库迁移；不含引擎集成 T0.3、不含基线集 T0.4）

---

## 一、目录结构

```
FixText_T0.2_词库迁移_v1/
├── README.md                     ← 本文件（交付说明）
├── 迁移报告.md                    ← ★ 本次运行的迁移报告（口径对照 / 清洗明细 / 闭包报警）
├── toolchain/                    ← ★ 迁移工具链（9 步脚本 + 一键入口）
│   ├── run_migration.sh          ←   一键重跑入口
│   ├── README.md                 ←   工具链详细说明（脚本职责 / 闭包机制 / 清洗规则 / 已知边界）
│   ├── config/paths.env          ←   路径配置（默认值指向包内 src/ 与 build/）
│   ├── lib/closure_guard.php     ←   闭包检测与报警库（运行时 + 源码两层）
│   └── scripts/01..09_*          ←   9 个步骤脚本
├── build/                        ← 本次运行产物（由 run_migration.sh 生成，可整体重建）
│   ├── 迁移报告.md
│   ├── dictionary/                ←   ★ 正式 JSON 词库产物
│   │   ├── index.json             ←     迁移总清单
│   │   ├── cleaned/*.json         ←     清洗后的词库原始变量（PHP 权威）
│   │   ├── flat/flat_*.json       ←     清洗后按 Map.php 语义展开的词条（PHP 权威）
│   │   ├── rules/before.json      ←     替换规则对（引擎接入用，本任务不含引擎集成）
│   │   ├── rules/after.json
│   │   ├── rules/rules_full.json  ←     含 mark / replaceHolder 的完整规则
│   │   ├── rules/rules_meta.json  ←     规则统计 + 清洗前后差异
│   │   └── manual/                ←     手动检索正则规则 + 闭包清单
│   ├── exported/  flattened/      ←   P0 口径基线中间产物（未清洗，用于与 P0 报告对齐）
│   ├── manual/                    ←   步骤 7 原始输出
│   ├── reports/                   ←   各步骤机器可读结果
│   └── logs/                      ←   migration.log（全流程日志）、closure_alarm.log（★ 闭包报警留痕）
└── src/                           ← FixText 源码（词库来源，与 FixText.zip 内 src/ 一致）
```

## 二、一键重跑

环境要求：**PHP 8.x**（本次实测 8.5.8，与 P0 口径一致）、**Python 3.8+**（仅标准库）、**Bash 4+**。

```bash
cd toolchain

# 零参数：使用包内 src/ 与 build/，原地重建全部产物
./run_migration.sh

# 指定源码与输出目录
./run_migration.sh --src /path/to/FixText/src --out /path/to/out

# 指定 PHP 可执行文件 + 先清空输出目录（从零复现）
./run_migration.sh --php /usr/bin/php8.3 --clean
```

退出码 `0` = 9 步全部完成；非 `0` = 某步失败，原因见 `build/logs/migration.log`。
步骤 5（闭包静态扫描）命中闭包时返回 `3`，属**预期告警**，入口脚本已单独处理。

实测：包内零参数重跑 **29 秒**完成，与首次运行**数据完全一致**（仅 3 个文件因内嵌源码绝对路径不同，
其余产物逐字节一致）。

## 三、自验数据（口径对照）

| 口径项 | P0 前置验证报告 | 本次实测 | 结论 |
| --- | --- | --- | --- |
| 词库文件数 | 13 | 13 | 一致 |
| 变量回读一致 | 39 / 39 | 39 / 39 | 一致 |
| 编解码往返 | 42 / 43 | 42 / 43 | 一致（唯一差异 `../config/general.php::__return__`，来源是 3 处闭包被 json_encode 静默降级，本次已显式标注） |
| 词条型变量展开逐条全量一致 | 34 / 34 | 34 / 34 | 一致 |
| 展开后规则总数（基线，未清洗） | 222,899 → 304,256 | 222,899 → 304,256 | 一致 |
| 规则总数（清洗后，正式产物口径） | 口径未覆盖 | **304,255** | 差异 -1，来源见下 |

**规则数差异如实说明（不做强行凑一致）**：strictMap 瑕疵共 1 处
（`1.自定义词库.php::strictMap` 第 14 条，`mark` 被写成 `before` 数组的键而非值）。
清洗后伪规则 `before="{处理“悬殊”的问题}" / after="差距太大"` 消失、词条级 mark 恢复，
规则总数由 304,256 降为 **304,255**，差值 -1 已逐条记录在 `迁移报告.md` §4 与
`build/reports/cleaning_report.json`，无其它未解释差异。

**清洗后二次自验**：Python 镜像实现 vs PHP 权威展开 **34 / 34** 逐条全量一致。

## 四、闭包检测与报警（真实触发 + 留痕）

`json_encode()` 遇到 `Closure` 会**静默降级**为 `{}`（不报错、不抛异常），闭包在 JSON 迁移中无声丢失。
排期 3.5 门禁 (c) 禁止这种静默降级，故工具链内置两层检测 + 报警：

| 层 | 实现 | 本次命中 |
| --- | --- | --- |
| 运行时层 | `lib/closure_guard.php` 递归扫描已加载变量 | general.php `noteBrandProcessors` 3 处 |
| 源码层 | `token_get_all` 扫描 `src/maps` + `src/config` | 手动检索规则表 3 处 + general.php 3 处 = **6 处** |

- 报警留痕：`build/logs/closure_alarm.log`，本次 **3 个报警域 / 12 条命中**
  （`runtime-export` 3、`static-scan` 6、`manual-regex-rules` 3）；
- 处置：命中闭包的变量/规则**拒绝 JSON 化**，显式标注 `replace_kind=php_closure` 并附源码行号，
  写入 `dictionary/manual/manual_rules_closure_manifest.json`，交由引擎侧重写；
- 正式词库产物中**不含**任何 `{}` 形式的静默降级残留（已逐文件扫描确认）。

## 五、边界

- 本任务**只做词库迁移**：JSON 词库产物 + 可一键重跑的迁移流程 + 数据清洗 + 闭包报警。
- **不含引擎集成（T0.3）**：规则集已按 Go 生产顺序产出，未接入引擎、未做替换行为验证。
- **不含基线集（T0.4）**：未构造回归基线语料。
- **6 处闭包的运行时行为重写与单独测试**属 T0.3（排期 3.5 门禁 a），本包只做检测与交接留痕。
