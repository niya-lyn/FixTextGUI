# FixTextGUI 一键校正编排器（M1-T1.1）

把 M1 各引擎串成**一条命令行全链路**，对一本书一键完成：

```
EPUB 合并(T1.3) → 排版(T1.2) → 词库替换(T0.3 Go 引擎 + T0.2 词库)
                → 引号检查(T1.4) → 专有词库生成(T1.5) → EPUB 还原(T1.3)
```

编排器**不含任何引擎实现**，全部复用 M1 各卡的模块；替换阶段严格走 T0.3 的
Python 子进程协议，编排器不自己实现字符串替换逻辑。

---

## 一、环境要求

| 项 | 要求 | 说明 |
| --- | --- | --- |
| Python | **≥ 3.11** | T0.3 的 `fixtext.engine` 用了 `enum.StrEnum`（3.11 才引入） |
| lxml | 任意版本 | 排版阶段的 XML 结构守卫、EPUB 校验都要用 |
| Go 引擎 | linux-amd64 / windows-amd64 二选一 | 已在 `vendor/fixtext/engine/go_src/bin/` 内 |

引擎模块已内嵌在 `vendor/`，**不需要 pip 安装各引擎包**：

```
vendor/
  epubtext/            T1.3 EPUB 合并 / 还原 / 校验
  fixtext_layout/      T1.2 排版引擎
  fixtext_quotation/   T1.4 引号检查
  fixtext_bookmap/     T1.5 专有词库生成
  fixtext/engine/      T0.3 Go 引擎子进程协议
```

---

## 二、快速开始

```bash
cd product

# 0) 先体检（检查 EPUB / 词库 / Go 引擎 / 引擎模块是否齐备）
python3 -m fixtext_pipeline doctor \
    --epub ../in/paohuo.epub \
    --wordbank-dir ../pkg/T0.2_wordbank/FixText_T0.2_词库迁移_v1/build/dictionary/rules

# 1) 一键跑全链路
python3 -m fixtext_pipeline run \
    --epub ../in/paohuo.epub \
    --workdir ../runs/paohuo \
    --wordbank-dir ../pkg/T0.2_wordbank/FixText_T0.2_词库迁移_v1/build/dictionary/rules

# 2) 打印上次的运行报告
python3 -m fixtext_pipeline report --workdir ../runs/paohuo
```

`run` 是默认子命令，所以下面这条等价：

```bash
python3 -m fixtext_pipeline --epub book.epub --workdir ./run --wordbank-dir ./rules
```

**退出码**：`0` 全链路成功；`1` 某阶段失败；`2` 参数或环境不满足。

---

## 三、命令参数

### `run`

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--epub` | 必填 | 输入 EPUB 路径 |
| `--workdir` | 必填 | 工作目录：状态、产物、日志、报告都落这里 |
| `--wordbank-dir` | — | 词库规则目录（含 `before.json` / `after.json`） |
| `--rules-before` / `--rules-after` | — | 成对给出，替代 `--wordbank-dir` |
| `--engine` | 自动发现 `vendor/` | Go 引擎二进制路径 |
| `--layout-profile` | `html-safe` | 排版档案，另可选 `none`（只做 trim 不改排版） |
| `--layout-option K=V` | — | 覆盖单个排版选项，可重复 |
| `--replace-count` | `2` | 替换趟数，与上游 `TextFixer` 的 `$replaceCount = 2` 一致 |
| `--engine-timeout` | `1800` | Go 引擎子进程超时秒数 |
| `--stages` | 全链路 | 只跑指定阶段，逗号分隔 |
| `--no-resume` | 关 | 不跳过已完成阶段 |
| `--force` | 关 | 强制重跑（忽略已有状态） |
| `--keep-going` | 关 | 某阶段失败后继续跑后面的阶段 |
| `--bookmap-add-current-time` | 关 | 专有词库写入时间点注释（默认关，保证产物可复现） |
| `--json` | 关 | 额外把运行报告 JSON 打到 stdout |

### `doctor`

`--epub` / `--wordbank-dir` / `--rules-before` / `--rules-after` / `--engine` 均为可选，
缺哪项就跳过哪项检查并如实报出。

### `report`

`--workdir` 必填，输出上一次运行的 `run_report.md`。

---

## 四、工作目录结构

```
<workdir>/
  state.json                  阶段状态（断点恢复的唯一依据）
  logs/
    run.log                   总运行日志
    01_merge.log ... 06_restore.log   各阶段日志
  01_merge/                   合并 TXT + bundle 账本
  02_layout/                  排版后 TXT + 账本副本 + layout_report.json
  03_replace/
    before/<book>.txt         替换前（专有词库生成用）
    after/<book>.txt          替换后（还原用）
    replace_report.json       引擎回执 + 边界完整性复检
  04_quote/                   引号检查报告（txt + json）
  05_bookmap/maps/书籍专有替换词库/<book>.php    专有词库表
  06_restore/                 还原后的 EPUB + validate_report.json
  report/                     run_report.json / run_report.md
```

---

## 五、断点恢复

恢复判定写在 `fixtext_pipeline.runner._should_skip`，**三条同时满足**才跳过某阶段：

1. 上次状态为 `done`；
2. 阶段输入指纹一致（指纹变了说明输入变了，必须重跑）；
3. 上次声明的产物**全部仍在**。

任一条不满足 → 重跑该阶段。实测行为：

| 场景 | 结果 |
| --- | --- |
| 同一命令再跑一次 | 6 个阶段全部 SKIP，耗时从 19.5s → 0.8s |
| 删掉 `05_bookmap` 的 `.php` 和 `06_restore` 的 EPUB | 只有 bookmap + restore 重跑，上游全部 SKIP |
| 跑到一半 `kill -9` | `state.json` 留下 `merge=done` / `layout=running`；重跑时 merge 被 SKIP，layout 从头重跑，其后阶段照常跑完 |

阶段状态在**每个阶段开始前**和**结束后**各写一次 `state.json`，所以任何时刻中断都不丢进度。

---

## 六、几个关键设计

### 1. 替换阶段必须走 Go 引擎子进程协议

```python
rules = RuleSet.from_files(before_json, after_json)      # T0.3
request = EngineRequest(count=2, input_mode=FILE, output_mode=FILE, ...)
response = GoEngineClient(engine_path).run(request)      # T0.3
```

引擎失败时把 T0.3 的错误码与处置建议原样抛出，编排器不做任何「自己动手改一改」的兜底。

替换完成后还会做一次 **边界完整性复检**：用账本严格切分替换后的 TXT
（`split_bundle(strict=True)`）。`EPUBTEXT-*` 边界标记一旦被词条打坏，切分就会失败，
阶段直接报错，不会把坏文本传给下游。

### 2. 排版在「逐章」粒度上执行

合并后的 TXT 里夹着 `EPUBTEXT-*` 边界标记行。整份文件做「每行加全角缩进」这类排版会把
标记行顶坏，账本切分随之失效。逐章执行还有第二个好处：**XML 结构守卫**可以逐章判定 ——
排版后若该章不再是合法 XML、或标签/属性结构被改坏，该章**自动回退**到排版前内容，
并计入 `layout_report.json` 的 `reverted` 统计。

默认档案 `html-safe` 只开 `normalize_punctuations` 这类不碰标签结构的开关，
`change_text_format` 保持关闭（上游默认也是关闭的）。

### 3. 还原用原 EPUB 当模板重打包

图片、样式、OPF、NCX 全部原样保留，只替换 spine 指向的那几个 XHTML 条目，
所以**章节顺序天然不会乱**。还原后做三重校验，任一不通过即判阶段失败：

1. `check_epub(deep=True)` —— 包能不能打开、结构完不完整；
2. `compare_content` —— 逐章比对正文，确认没有章节变空/丢失；
3. spine 指纹比对 —— 原包与还原包的 spine 路径序列 sha256 必须完全一致。

`tools/verify_epub.py` 是**独立于编排器**的第三方校验器（只用 zipfile + lxml 拆包核对），
用来交叉验证还原结果。

---

## 七、跑测试

```bash
cd product
python3 -m pytest tests -q
```

> 若环境里装了第三方 pytest 插件且与新版 pytest 不兼容，用
> `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q` 跳过自动加载。

---

## 八、目录结构

```
product/
  fixtext_pipeline/
    __init__.py          包元信息、阶段顺序
    __main__.py          python -m 入口
    cli.py               命令行解析（run / doctor / report）
    config.py            PipelineConfig、工作目录布局、排版档案
    state.py             state.json 读写、指纹、产物存在性判定
    logsetup.py          阶段日志（文件 + 终端 + 捕获 print）
    report.py            run_report.json / run_report.md
    runner.py            主循环：依赖检查 → 指纹 → 跳过判定 → 计时 → 落状态
    vendor_bootstrap.py  vendor 引擎导入引导
    stages/              六个阶段实现
  vendor/                五个引擎包（epubtext / fixtext_layout /
                         fixtext_quotation / fixtext_bookmap / fixtext）
  tools/verify_epub.py   独立 EPUB 校验器
  tests/test_pipeline.py 单元测试（32 个）
```
