# FixText M1-T1.0 · 回归基线重冻结（304,255 口径）

> M1 引擎闭环首张卡。按排期文档附录 C 第五条裁定，V1 唯一生产基准为 T0.2 清洗后的 **304,255** 条词库；T0.4 交付时的 304,256 条口径仅作历史对照。

## 本卡做了什么

用 T0.4 回归基线集自带的 `run_baseline.py`，把规则集换成 T0.2 迁移产物（304,255 条），重跑 15 个语料并重新冻结基线，再与旧冻结结果逐字节对比。

| 验收项 | 结果 |
|---|---|
| 15/15 语料以 304,255 口径重跑 | **PASS**，`--build` 与 `--check` 均 exit 0 |
| 重冻结基线落盘 | **PASS**，`expected/go` 15 + `expected/php` 15 + `manifest/baseline_manifest.json` |
| 与旧基线逐字节差异 | **0 条** |
| strictMap 伪规则是否真实命中 | **否**，完整串与 `{处理` 前缀在 15 语料中命中 0 次 |
| 总替换次数 | 1,666,476（与旧基线相同） |
| 命中规则并集 | 10,898 条（与旧基线相同，差集两侧均空） |

## 目录结构

```
FixText_M1T1.0_回归基线重冻结_304255_v1/
├── README.md                     本文件
├── run.sh                        一键复现入口（比对 / 重冻结 / 与旧基线对比）
├── baseline/                     基线集本体（304,255 口径）
│   ├── corpus/                   15 个语料 + corpus_manifest.json（23,328,299 B，与 T0.4 同源）
│   ├── expected/                 重冻结输出（go/ 与 php/ 各 15 个，逐字节相同）
│   ├── manifest/                 baseline_manifest.json（新冻结清单）
│   ├── rules/                    ★ 304,255 条规则（T0.2 清洗后，本卡唯一变更）
│   ├── scripts/                  引擎复刻与一键脚本（沿用 T0.4 原件）
│   └── docs/                     语料说明 / 基线方法论（含 §七 口径变更记录）/ 自验记录（历史留痕）
├── rules_source/                 规则集来源证据
│   ├── T0.2_迁移报告.md
│   ├── T0.2_cleaning_report.json 清洗原始记录（含 bogus_rule_removed）
│   └── rules_meta_304255.json
├── reports/                      ★ 本轮全部验证留痕
│   ├── 重冻结对比报告.md         结论 + 逐文件对比表 + 归因 + 边界
│   ├── rule_diff.json            规则集逐条差异（仅 1 条）
│   ├── pseudo_rule_hit_check.json 伪规则在 15 语料的命中检索
│   ├── ab_result.json            仅换规则集的 A/B 对拍
│   ├── build_304255.json         --build 原始结果
│   ├── check_304255.json         --check 原始结果
│   └── union.json                命中规则并集（新旧口径各 10,898 条，采用 count_hits 语义导出）
└── T01_patch/                    并入 T0.1 CI 的补丁（沿用 T0.4 原件，未改）
```

## 一键复现

```bash
chmod +x run.sh

./run.sh                                  # 验收比对：重跑 15 语料比对冻结输出（约 60s，PASS=exit 0）
./run.sh --build                          # 重新冻结 expected/ 与 manifest/
./run.sh --verify-vs-old <旧基线目录>      # 与旧 304,256 冻结输出逐字节对比
```

依赖：PHP ≥ 8（CLI）、Python ≥ 3.8；Go 工具链可选（缺失时用随包预编译 linux/amd64 二进制，`run.sh` 会自动补执行位）。

## 与 T0.4 原包的差异

| 文件 | 变化 |
|---|---|
| `baseline/rules/before.json` `after.json` `rules_meta.json` | 换成 T0.2 产物（304,256 → 304,255，shas 见对比报告） |
| `baseline/expected/go/*` `expected/php/*` | 重冻结（内容与旧版逐字节相同） |
| `baseline/manifest/baseline_manifest.json` | 重生成（规则 shas 与 meta 更新，计数不变） |
| `baseline/docs/02_基线方法论.md` | 口径改为 304,255，新增 §七 口径变更记录 |
| `baseline/docs/03_自验记录.md` | 加口径提示，原 T0.4b 留痕保留不改写 |
| `baseline/docs/01_语料构成说明.md`、`README.md` | 规则条数改为 304,255 |
| `baseline/corpus/` `baseline/scripts/` `T01_patch/` | **未改**，与 T0.4 原件一致 |

## 详细结论

见 `reports/重冻结对比报告.md`。
