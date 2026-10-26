# FixText T0.4b · 回归基线集 v1

FixText（PHP/Go 简繁校正工具）的回归基线集：固定 15 个中文语料 + 上游全量规则集，冻结 PHP / Go 两个后端的校正输出与替换计数，提供一键重跑比对脚本，并已并入 T0.1 工程骨架的 CI 结构（作为 baseline 阶段）。

## 目录结构

```
FixText_T0.4_回归基线集_v1/
├── README.md                     本文件
├── baseline/                     基线集本体
│   ├── corpus/                    15 个语料文件 + corpus_manifest.json（23.3 MB 总量）
│   ├── expected/                  冻结的引擎输出（go/ 与 php/ 各 15 个，逐字节一致）
│   ├── manifest/baseline_manifest.json   冻结清单（每文件 sha256、输出哈希、替换计数）
│   ├── rules/                     全量规则集 before/after JSON + rules_meta.json（P0 同源）
│   ├── scripts/                   一键脚本与引擎复刻
│   │   ├── build_corpus.py        语料构建（从云盘原件确定性生成，含章节切片逻辑）
│   │   ├── run_baseline.py        ★ 一键重跑比对 / 冻结
│   │   ├── php_strtr.php          PHP 后端复刻（replaceByPHP 语义：reverse+combine+strtr×2）
│   │   ├── verify_upstream_equivalence.php   上游一致性深度验证（A 规则 / B PHP后端 / C 直连配置）
│   │   └── go/                    Go 源码（replace_by_go 逐字复制上游 + count_hits 计数器）
│   │       └── *.bin              预编译 linux/amd64 二进制（无 Go 工具链时的后备）
│   └── docs/                     三份说明文档（见下）
└── T01_patch/                     并入 T0.1 CI 的补丁（patch.diff + 修改后文件）
    ├── patch.diff                 对 T0.1 骨架三处改动的 unified diff
    ├── scripts/ci.py              增加 baseline 阶段（支持 SKIP）
    ├── scripts/ci_baseline.py     baseline 阶段入口（缺工具链时退出码 77 → CI 显示 [SKIP]）
    └── .github/workflows/ci.yml   矩阵任务 + 独立 baseline 任务（ubuntu-latest）
```

## 文档

- `baseline/docs/01_语料构成说明.md` — 12 本公版书 + 3 部真实小说的选取理由、文件名、大小、云盘出处路径与替换密度统计
- `baseline/docs/02_基线方法论.md` — 冻结对象、规则集来源与口径、三条生产执行路径等价性论证、计数方法、CI 集成方式
- `baseline/docs/03_自验记录.md` — 逐项验收留痕：冻结/比对/确定性/上游一致性/CI 的真实命令输出

## 快速开始

```bash
# 一键重跑比对（约 1 分钟，15/15 通过则退出码 0）
python3 baseline/scripts/run_baseline.py

# 重新冻结基线（语料或规则更新后；会重写 expected/ 与 manifest/）
python3 baseline/scripts/run_baseline.py --build

# 上游一致性深度验证（可选，需上游 FixText 源码解压目录）
php baseline/scripts/verify_upstream_equivalence.php /path/to/FixText/src ./baseline
```

依赖：PHP ≥ 8（CLI）、Python ≥ 3.8；Go 工具链可选（无则自动使用随包预编译 linux/amd64 二进制，其他平台请用 `go build` 自行编译 `baseline/scripts/go/{replace_by_go,count_hits}`）。

## 并入 T0.1 CI

将 `T01_patch/patch.diff` 应用到 T0.1 骨架仓库（或将 `T01_patch/scripts/`、`T01_patch/.github/workflows/ci.yml` 覆盖对应文件），把本包 `baseline/` 目录放到仓库根：

```bash
git apply patch.diff
python3 scripts/ci.py          # baseline 阶段自动纳入
python3 scripts/ci_baseline.py # 单独跑 baseline 阶段
```

GitHub Actions 中 ubuntu-latest 会真实执行基线比对，Windows 矩阵项自动 SKIP。

## 基线口径（一览）

- 语料 15 个 / 23,328,299 字节；规则 304,256 条（19 个 `*Map` 变量全量口径，与 P0 报告同源）
- 生产语义复刻：`doReplace` count=2 两轮替换（`singleReplace=false`）
- 冻结输出：Go 与 PHP 后端全部 15 文件逐字节一致；总替换 1,666,476 次
