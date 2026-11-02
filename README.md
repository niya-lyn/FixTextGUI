# FixTextGUI

简体中文小说的桌面校对工具：**导入 → 一键校正 → 逐处检查 → 导出**。把网上常见的 TXT / EPUB 书稿里那些不干净的排版、错别字替换、乱标点整理成一本可以正常阅读的书。

界面基于 PySide6，校正是本地批处理流水线，不联网、不上传书籍内容。

> 当前是 **v1 基线**。Windows 绿色版可双击即用；源码模式支持 Windows 与 Linux。macOS 能打开界面，但**没有可用的替换引擎**，一键校正不可用（见「已知限制」）。

---

## 功能特性

| 能力 | 说明 |
|---|---|
| **TXT / EPUB 导入** | 常见中文编码自动识别（UTF-8 / UTF-8-BOM / GBK / GB18030 / Big5），含 4 字节字符、CRLF/LF 混用等情况。**原文件只读**，只在包内生成副本 |
| **一键校正** | 排版 + 词库替换 + 标点统一，一条链跑完。仓库自带的 301 章公版 fixture 实测 **2.6 秒**量级 |
| **分袋词库** | 出厂 304,255 条规则按用途分 15 袋（常规校正锁定、预处理 / 严格 / 注音等开关可选），勾选即生效，全量 `before/after` 口径不变 |
| **专有词库** | 从本书正文自动比对生成人名地名等专有词条（301 章 fixture 实测 2,243 条），下次校正随出厂规则一起生效 |
| **引号检查** | 逐处列出存疑引号，可单点修、可撤回，改错不丢原文 |
| **词库管理** | 查词、查重、增删改、合并；自定义词条与出厂词库分开存放，出厂库只读、可一键恢复 |
| **历史与续跑** | 每次校正留一条记录，可恢复、可重新导出；中断后能续跑，结果按 sha256 对齐 |
| **导出** | TXT 进 TXT 出、EPUB 进 EPUB 出（EPUB 按原书结构重打包，spine 顺序与逐章正文可比对） |
| **绿色分发** | PyInstaller onedir 打包，解压即用、可整体搬走；自带 `--self-check` 自检入口 |

---

## 安装与运行（源码模式）

### 环境要求

- **Python 3.11 或更新**。硬约束：`pipeline/vendor/fixtext/engine/protocol.py` 使用了 `enum.StrEnum`，3.11 才引入；在 3.10 上导入引擎包会直接 `ImportError`。
- Windows x64 / Linux x64 之一（替换引擎只有这两个平台的二进制）。
- 磁盘：仓库含 304,255 条词库与 Go 引擎，工作树约 38 MB。

### 三步起跑

```bash
# 1. 装依赖
python -m pip install -r requirements.txt

# 2. 启动界面
python main_app.py
```

依赖只有三个（`requirements.txt`）：

| 包 | 用途 |
|---|---|
| `PySide6>=6.5` | 全部窗口、控件、拖放与后台线程 |
| `lxml>=4.9` | EPUB 解包 / 排版 / 还原的 XML 处理 |
| `pyahocorasick>=2.1` | Python 替换引擎（Go 引擎不可用时的降级路径） |

首次启动会自动创建 `workspace/`（当前书与词库副本）、`runs/`（每次校正的工作目录）、`logs/`（诊断日志）。这三个目录都在 `.gitignore` 里，不入库。

### 只想跑命令行链路

`pipeline/` 是一个独立可用的批处理编排器，不需要打开界面：

```bash
cd pipeline

# 环境体检：检查 EPUB、词库、替换引擎、引擎模块是否齐备
python -m fixtext_pipeline doctor \
    --epub /path/to/your_book.epub \
    --wordbank-dir ../data/rules

# 跑全链路（合并 → 排版 → 替换 → 引号 → 专有词库 → 还原）
python -m fixtext_pipeline run \
    --epub /path/to/your_book.epub \
    --workdir /tmp/ft_run \
    --wordbank-dir ../data/rules

# 打印上一次的运行报告
python -m fixtext_pipeline report --workdir /tmp/ft_run
```

`doctor` 的实测输出（本仓库基线，Python 3.12.11）：

```
Python            : 3.12.11
引擎模块          : 全部就绪 ['epubtext', 'fixtext_layout', 'fixtext_quotation', 'fixtext_bookmap', 'fixtext.engine']
替换引擎选择      : go（配置键 engine，缺省 go）
Go 引擎           : .../replace_by_go-linux-amd64（2,646,016 字节，mode 755，可执行=True）
Python 引擎依赖   : pyahocorasick 已安装
lxml              : 6.0.2
体检通过，可以开跑。
```

`run` 的实测数据（用仓库自带的公版 fixture `tests/samples/book_public_domain.epub`，301 章 / 646 KB，由 `tools/build_fixture_epub.py` 从 Project Gutenberg #51828 现场合成）：总耗时 **2.576s**，全部阶段 `done`，还原校验「spine 顺序一致、逐章正文比对 301 章无缺失无空章」，产出 43 处引号错误、2,243 条专有词条（去重 2,127）。各阶段耗时：合并 0.056s、排版 1.227s、替换 0.484s、引号 0.074s、专有词库 0.210s、还原 0.306s。上面这些数字由 `tools/make_fixture_meta.py` 在 fixture 上真实跑一次生成，写进 `tests/samples/fixture_run_meta.json`，测试直接读它做期望值，不抄数字。

---

## 构建 Windows 绿色版

> 仓库里**没有**名为《Windows构建步骤.md》的文档。构建入口就是包内的两个文件：**`构建绿色版.bat`**（一键脚本，7 步）与 **`fixtext.spec`**（PyInstaller 配置）。下面按这两个文件的实际情况写。

### 一键构建（推荐）

在 Windows 上，把源码包解压好，**双击 `构建绿色版.bat`**。脚本会依次做 7 件事，任一步失败就停下来给人话提示：

| 步 | 动作 | 失败时 |
|---|---|---|
| 1/7 | 检查 Python ≥ 3.11（借助 `py` 或 `python`） | 提示去 python.org 安装并勾选 `Add python.exe to PATH`（脚本**不联网下载**） |
| 2/7 | 建独立构建环境 `.build_env/` | 不污染机器上已有 Python |
| 3/7 | 安装打包工具与运行依赖 | 需联网，几分钟 |
| 4/7 | PyInstaller `onedir` 打包 | 走 `fixtext.spec` |
| 5/7 | 拷贝词库、设计依据与**目标平台**的替换引擎 | 只带当前平台那一个二进制 |
| 5.5/7 | 确认包内不含 `workspace/` | 防止新用户首次启动跳过新手向导 |
| 6/7 | 用 `FixTextGUI.exe --self-check` 让程序自己验一遍 | 最常见是引擎被杀软隔离 → 加白名单重试 |
| 7/7 | 压成 `release\FixTextGUI_绿色版_v1_<日期>.zip` | 可手动把 `dist\FixTextGUI` 打包，目录结构须原样保留 |

说明几点打包设计（摘自 `fixtext.spec`，改打包时必须守住）：

- **onedir 而非 onefile**：经不起每次启动解压 10 MB 词库 + 4 MB 引擎。
- **`workspace/` 不进包**：它装的是「当前打开哪本书 / 看过向导没有」。带进去会让 `opens_on_first_run()` 返回 `False`，新用户永远看不到新手向导。`--self-check` 专门断言这一条。
- **引擎只带目标平台那一个**：`windows-amd64.exe` 与 `linux-amd64` 各约 2.6 MB，另一个白占体积。

### 手动打包

```bash
python -m pip install pyinstaller
pyinstaller --noconfirm --clean fixtext.spec
```

产物在 `dist/FixTextGUI/`。打包后还需要把 `data/rules/`、`reference/`、目标平台的引擎二进制拷进包根——`构建绿色版.bat` 的第 5 步做的就是这件事，手动做容易漏，建议直接用脚本。

### 重新编译 Go 替换引擎

引擎源码在 `pipeline/vendor/fixtext/engine/go_src/`（`replace_by_go.go` + `go.mod`，**只 import 5 个标准库**：`encoding/json`、`fmt`、`os`、`strconv`、`strings`，无第三方依赖）。可以完全离线构建——需要先装 [Go 1.22+](https://go.dev/dl/)：

```bash
cd pipeline
PYTHONPATH=vendor python -m fixtext.engine.builder --both   # linux + windows
PYTHONPATH=vendor python -m fixtext.engine.builder --windows # 只编 Windows
PYTHONPATH=vendor python -m fixtext.engine.builder --rebuild   # 强制重编当前主机
```

（`--windows` / `--both` / `--rebuild` / `--json` 是全部选项。）`builder.py` 内部固定了 `GOPROXY=off`、`GOTOOLCHAIN=local`、`CGO_ENABLED=0`、`-p 1`，因此不需要联网拉模块、不需要 gcc、也不会把单核机器打满。

实测（Linux x64 / `go version go1.22.8`）：重编产物 2,646,016 字节，与仓库内已提交的 `replace_by_go-linux-amd64` **md5 逐字节一致**（`8bd212a083d99bc9833d849571ba07ce`），即引擎构建是可复现的。

---

## 使用说明

界面左侧六个入口，顶部图标回首页。首次启动会弹「新手向导」，三步**真的**带你导入、校正、导出一本书。

1. **导入书籍**：TXT 或 EPUB 拖进窗口。自动识别编码；原文件不动，软件只用副本。导完自动进下一步。
2. **一键校正**：点主按钮。排版、换词、统一标点一次做完。过程中可取消——换词约 1 秒内停，排版在**当前章**结束处停，取消后中间结果清掉，不留半成品。
3. **检查问题**（可选）：对引号等存疑处逐处确认，改错可撤回。
4. **词库管理**（可选）：查词、查重、删、合并。**自定义词条在下次一键校正时生效**。出厂大词库只读，可一键恢复默认。
   > 查重弹窗**故意只读**（不是漏做）：清单只能看，底部只有「关闭」。要处理重复，用工具条上的「合并」或「删除选中」，各自先预览、二次确认、可撤销。
5. **导出结果**：TXT 进 TXT 出，EPUB 进 EPUB 出。可另选格式与书名。建议第一次导完用常用阅读软件打开确认。
6. **历史记录**：每次校正一条，可恢复或重新导出。

**本仓库不附带示例书以外的真实书籍**，请导入自己的书试用。

导出默认落在包根下的「导出」文件夹。软件自身数据都在程序文件夹内：`workspace/`、`runs/`、`logs/`（设置页可一键打开日志目录）。

---

## 目录结构

```
.
├── main_app.py                 # 界面入口：建 QApplication → 加载 QSS → 初始化错误中心 → 主窗口
├── fixtext_paths.py            # 包根解析唯一入口（适配打包容器的路径漂移）
├── fixtext_self_check.py       # FixTextGUI.exe --self-check 的实现
├── fixtext.spec                # PyInstaller onedir 配置
├── 构建绿色版.bat               # Windows 绿色版一键构建（7 步）
├── requirements.txt            # 运行时依赖（3 个）
├── 运行说明.md                  # 面向使用者的运行说明
├── 使用说明.html / .txt         # 面向使用者的图文说明
│
├── fixtext_ui/                 # 界面层（28 个模块）
│   ├── main_window.py          #   主窗口、左轨导航、顶栏
│   ├── import_module.py        #   导入页（TXT / EPUB、编码识别结果）
│   ├── oneclick_module.py      #   一键校正页（进度、取消、逐阶段文案）
│   ├── check_module.py         #   检查问题页
│   ├── vocab_module.py         #   词库管理页（查词 / 查重 / 合并）
│   ├── export_module.py        #   导出结果页
│   ├── history_module.py       #   历史记录页（恢复 / 重导出）
│   ├── first_run_wizard.py     #   任务式新手向导（真实三步）
│   ├── fixtext_worker.py       #   校正任务线程；阶段 → 人话映射
│   ├── fixtext_tokens.py       #   设计令牌（色彩 / 字号 / 间距 / 圆角）
│   ├── build_qss.py            #   令牌 → fixtext.qss（Qt 无 CSS 变量，需展开）
│   └── fixtext.qss             #   由 build_qss.py 生成，勿手改
│
├── fixtext_import/             # 导入与编码识别（不依赖 Qt）
│   ├── encoding.py             #   BOM → ASCII → 严格解码 → 可读性打分仲裁
│   ├── importer.py             #   TXT / EPUB 统一导入入口
│   ├── epub_import.py          #   EPUB 可逆账本（导入即能还原）
│   └── textfile.py             #   换行 / 编码归一
│
├── fixtext_error_center/       # 人话错误体系
│   ├── error_codes.py          #   14 个用户码（U-I / U-P / U-E / U-R）+ 引擎码翻译表
│   ├── classify.py             #   六层归类
│   ├── journal.py              #   JSONL 诊断日志
│   └── qt_bridge.py            #   跨线程弹卡（worker 线程不得直接建 QWidget）
│
├── pipeline/                   # 命令行编排器（可独立于界面使用）
│   ├── fixtext_pipeline/       #   六阶段编排、配置、CLI
│   ├── vendor/                 #   各引擎（均已内置，无需 pip 安装）
│   │   ├── epubtext/           #     EPUB 合并 / 还原 / 校验
│   │   ├── fixtext_layout/     #     排版
│   │   ├── fixtext_quotation/  #     引号检查
│   │   ├── fixtext_bookmap/    #     专有词库生成
│   │   └── fixtext/engine/     #     Go 引擎子进程协议 + Python 降级引擎
│   └── README.md               #   编排器详细说明
│
├── vendor/epubtext/            # 导入层（fixtext_import）用的 EPUB 引擎路径
│                              #   （与 pipeline/vendor/epubtext 内容相同；两处入口
│                              #     各自按自己的相对位置找包，都需保留）
├── data/rules/                 # 出厂词库（只读）
│   ├── before.json / after.json        # 全量 304,255 条（4.5 MB × 2）
│   ├── bags/                           #   按用途分 15 袋 + 每袋 meta
│   ├── builtin_bags.bin / builtin_tiers.bin   # 与全量同序的袋码 / 分级码
│   └── builtin_marks.json              # 词条说明
│
├── reference/                  # 设计地基快照（:root 令牌原文），供令牌一致性校验
├── tests/                      # pytest 用例集（含编码样本与公版 EPUB fixture）
├── tools/                      # 各卡验收脚本与探针
├── docs/                       # 研发文档（已知缺口、待处理清单）
└── verify_report.json          # 基座自检结果（界面六入口可达性）
```

---

## 开发与测试指引

### 跑测试

```bash
python -m pytest tests -q
```

基线实测：**430 passed**（Python 3.12.11 / PySide6 / lxml 6.0.2）。测试自己在 `tests/conftest.py` 里把包根与 `fixtext_ui/` 插进 `sys.path`，不需要额外配 `PYTHONPATH`。

无显示器环境（CI、容器）要指定离屏后端，否则 Qt 起不来：

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests -q
```

`conftest.py` 已经 `setdefault` 了 `QT_QPA_PLATFORM=offscreen`，并为整轮测试共用一个 `QApplication`——错误中心会在 `report()` 时真弹非模态卡，没有应用实例时创建 QWidget 会让进程**直接 abort**（不是抛异常）。另外它把设置文件指到会话临时目录（`FIXTEXT_SETTINGS_FILE`），避免上次人工验收留下的值串进用例。

### 改代码时要守住的几条

| 约束 | 原因 |
|---|---|
| **不要手改 `fixtext_ui/fixtext.qss`** | 它由 `build_qss.py` 从 `fixtext_tokens.py` 的令牌展开生成。Qt QSS 没有 CSS 变量，必须展开；手改会在下次生成时被覆盖。改令牌后重跑 `python fixtext_ui/build_qss.py`（脚本固定写到自身同目录，与 cwd 无关）。实测重跑后 `fixtext.qss` 与仓库内容零差异（md5 `feded4a2aa279e9f67107b72ba0d93d4`） |
| **令牌值以 `reference/` 的 `:root` 快照为准** | `tools/verify_m2t21.py` 会读快照并与 `fixtext_tokens.py` 比对，令牌漂移会让基座验收失败 |
| **worker 线程不要创建 QWidget / QDialog** | 在 Qt 里会让进程**静默挂死**（无异常、无日志）。要走 `fixtext_error_center.qt_bridge` 投递到主线程 |
| **不要用 `QMessageBox.exec()` 做自动化** | 它阻塞事件循环，无头环境直接卡住。界面内提示走页内内联提示条 |
| **`workspace/` 永不进打包** | 见上文打包设计 |
| **`data/rules/before.json` 与 `after.json` 必须同序同长** | 替换引擎按下标配对；`split_rule_bags.py` 的 `builtin_bags.bin` 也依赖这个顺序 |
| **改词库后要重跑对账** | `data/rules/bags/manifest.json` 记录了全量 sha256 与逐袋条数（各袋合计必须等于 304,255） |

### 加测试的约定

- 涉及 Qt 的用例，`conftest.py` 已提供 `qapp`，直接依赖它取 `QApplication`。
- 涉及真实 EPUB 的用例统一从 `tests/_public_fixture.py` 取样本路径，它是**唯一事实来源**；样本本体 `tests/samples/book_public_domain.epub` 是仓库自带的公版合成书，随仓库分发，因此这些用例默认就会真实执行（`skipif` 只在样本文件被误删时才生效，作用是给出可读的跳过原因，不是常规路径）。
- 期望值（章数 / 命中数 / 引号问题数 / 成品 sha256）一律从 `tests/samples/fixture_run_meta.json` 读，由 `tools/make_fixture_meta.py` 真实跑一次生成；**不要把这些数字抄进断言**，否则产品少跑一章、少报一处，测试也会跟着抄错。
- 验证「原文件不被改动」这类断言的用例，一律**运行时计算 sha256**，不要把哈希写死在代码里。
- 编码识别的判据不是「能不能解码」（GB18030 几乎能解一切字节），而是「严格解码结果的可读性打分」。改这块务必跑 `tests/test_encoding.py` 全量。

### 调试便利

```bash
# 打包版自检：不打开界面，只打印包根 / 词库 / 引擎 / 向导可见性
FixTextGUI.exe --self-check

# 命令行链路体检
cd pipeline && python -m fixtext_pipeline doctor --epub <书> --wordbank-dir ../data/rules
```

诊断为 JSONL，默认落 `logs/`；设置页可改目录或关闭留痕（`fixtext_settings.log_dir()` / `diag_enabled()`）。

---

## 已知限制

这些是**当前版本的诚实边界**，不是待办清单：

1. **macOS 不支持完整校正**。包内无 macOS 替换引擎，一键校正不可用，启动时会明示。
2. **导出 EPUB 未做主流阅读器真机确认**。结构与内容在开发环境做了校验（spine 顺序 + 逐章正文比对），但没在 Kindle / Apple Books / 微信读书上一一验证「导入即读」。
3. **取消不是瞬时中断**。排版要等当前章结束；其它步骤等当前步跑完。取消后不留半成品。
4. **杀毒软件可能误报**。未购买代码签名，首次运行可能出现「Windows 已保护你的电脑」——点「更多信息」→「仍要运行」。已在微软 Defender 与火绒上验证不隔离；360 与其他杀软未测。
5. **不附带示例书**。请导入自己的书。

更细的缺口（含已解决项）见 [`docs/已知缺口.md`](docs/已知缺口.md)。

---

## 关于词库与上游

出厂词库（`data/rules/`）由上游 PHP 项目 **`edennow/fix-text`**（MIT）的 map 词库迁移而来，304,255 条规则按 PHP 变量归属拆袋。上游项目采用 MIT 许可，本仓库的词库数据沿用同一条来源；**若要以本仓库名义对外分发词库，须在上游 MIT 声明之外自行确认你所在场景的合规性**（详见 `LICENSE` 与扫描报告中的「词库与语料」一节）。

`tests/samples/` 下的样本全部来自 Project Gutenberg 公版书（《吶喊》《聊齋志異》等）；其中 `book_public_domain.epub` 由 `tools/build_fixture_epub.py` 现场合成，不含任何版权作品，可直接分发。本仓库**不含任何在售书籍的正文**：体积大的语料与样书一律不进版本库，需要复现大书场景请自备一本 EPUB。

---

## 许可证

本仓库采用 **MIT**（见 `LICENSE`）。选择理由与风险提示写在 `LICENSE` 末尾的「选择说明」一节。
