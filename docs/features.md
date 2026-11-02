> 本文件由产品文档导出并脱敏，内容与公开发布版一致。

# FixText 已实现功能文档

## 一、项目概览

FixText 是一套运行于 Windows 的中文电子书校对与排版工具，面向「把 EPUB / TXT 电子书整理成规范文本」的完整工作流。整体由四部分构成：

- **PHP 命令行应用**（`src/main.php` 入口，基于 inhere/console 框架）：承载全部核心业务，17 个命令位于 `src/app/Command/`，服务层位于 `src/app/Service/` 与 `src/app/Util/`；
- **PyQt5 图形界面工具**（`src/tools/`，基于 qtpy）：统一控制台、引号检查、文件全局搜索、词条操作 4 个 GUI，全部通过子进程调用 PHP 命令或脚本；
- **Go 替换引擎**（`src/tools/replace_by_go.go`，编译产物 `replace_by_go.exe`）：用 strings.NewReplacer 做多趟批量替换，是词库校正的主力执行器；
- **词库体系**（`src/maps/`）与**配置体系**（`src/config/`）：驱动校正行为的全部数据。

运行前提：项目自带 PHP 运行时（根目录 `php/` 文件夹），所有 bat 都以 `php\php.exe src\main.php <命令>` 方式启动，无需单独安装 PHP；Go 引擎与 msys `diff.exe` 已编译为可执行文件随包分发。

**工作目录约定**（均为根目录下实际存在的文件夹）：

- `books/`：待处理书籍的工作目录，所有命令的输入与主要输出位置；
- `booksBak/`：校正前的备份目录，同时充当 diff 对比的基准（与 books 的差异即「本轮替换报告」）；
- `booksFix/`：全量修改后的书籍备份，用于生成书籍专有词库的对比基准；
- `logs/`：EPUB 合并日志与各阅读软件导出的批注文件存放处；`logs/report/` 存放各类报告产物；
- `src/maps/`：词库数据（含临时校对表与书籍专有词库）。

## 二、使用入口总览（根目录 21 个 bat）

根目录实际共有 **21 个** .bat 入口：17 个「双击运行」编号入口 + 4 个未编号入口（统一控制台、文件全局搜索、词条相关操作、CSV 相关操作）。文档按压缩包实际内容列出全部 21 个，逐个说明其内部调用的命令、做什么、输入与输出。

### 2.1 编号入口（17 个，均调用 PHP 命令）

| # | 入口文件 | 实际调用 | 功能一句话 |
|-|-|-|-|
| 0 | 0.文本排版.bat | `formatting` | 文本预处理与排版（编码、标点、分行、分级标题等） |
| 1 | 1.书籍校正.bat | `fix-text` | 完整校正流程（备份 + 预处理 + 词库校正） |
| 2 | 2.书籍校正（不进行原文件预处理）.bat | `fix-text no-preprocess-fix` | 跳过预处理，直接用词库校正（含生僻字注音等特殊模式） |
| 3 | 3.EPUB 解压.bat | `extract-epubs` | 把 books 下的 EPUB 解压为同名文件夹 |
| 4 | 4.EPUB 压缩还原.bat | `make-epubs` | 把解压的文件夹重新压缩为 EPUB |
| 5 | 5.EPUB 文本合并，原样转成 TXT.bat | `merge-epub-text` | EPUB 全部章节文本按顺序合并为一个 TXT |
| 6 | 6.EPUB 文本拆分还原（从 TXT 中拆分）.bat | `split-epub-text` | 从合并 TXT 拆回 EPUB 各章节文件 |
| 7 | 7.书籍清理（全部删除，包括备份、批注）.bat | `clear-books` | 清空 books / booksBak / booksFix / logs 全部数据 |
| 8-1 | 8.检查中文单双引号问题（1-图形界面方式，推荐）.bat | 引号检查 GUI | 引号检查图形界面（见第四章） |
| 8-2 | 8.检查中文单双引号问题（2-命令行方式）.bat | `check-quotation-marks` | 命令行交互式引号检查与修复 |
| 9 | 9.从批注中生成校对表.bat | `generate-words` | 解析阅读软件批注，生成临时校对表 |
| 10 | 10.通过批注校对表进行替换.bat | `fix-text temp-fix` | 用临时校对表对书籍执行替换并校验命中 |
| 11 | 11.自动生成【书籍专有词库】的书籍词条.bat | `generate-book-maps` | 从 booksFix 与 books 的差异提取本书专有词条 |
| 12 | 12.手动检索.bat | `manual-search` | 按正则规则表逐条人工确认替换（单文件） |
| 13 | 13.生成替换报告.bat | `generate-report` | 对比 booksBak 与 books 生成替换报告（写临时校对表） |
| 14 | 14.将替换报告应用至 booksBak.bat | `temp-fix-books-bak temp-fix` | 把替换报告同步应用至 booksBak，保持对比基准一致 |
| 15 | 15.查找文本中的重复段落.bat | `find-dupl-text` | 检测并报告书籍中的重复段落 |

### 2.2 未编号入口（4 个）

| 入口文件 | 实际调用 | 功能一句话 |
|-|-|-|
| 统一控制台（推荐试用）.bat | 统一控制台 GUI | 图形化任务面板，汇总全部常用任务（见第四章） |
| 文件全局搜索.bat | 文件全局搜索 GUI | 跨文件正则搜索 / 替换 / 比对编辑器（见第四章） |
| 词条相关操作.bat | 词条操作 GUI | 词库词条的可视化查重 / 检索 / 删除 / 合并等（见第四章） |
| CSV 相关操作.bat | `csv-operation` | 词库与 CSV 互转 |

另有 3 个命令没有对应 bat 入口，仅能通过统一控制台或直接敲命令调用：`rename-files-for-compare`（比较时重命名）、`de-drm`（移除伪 DRM 加密）、以及 `fix-text` 的两个参数模式（`no-preprocess-fix` / `temp-fix`，由 1、2、10 号入口分别覆盖）。

## 三、命令层：17 个 PHP 命令详解

命令注册在 `src/bootstrap.php`（扫描 `App\Command` 目录自动注册），命令名由各类的 `$name` 属性声明。以下逐个说明「做什么 / 输入 / 输出 / 源文件」。

### 3.1 fix-text — 书籍校正主流程

- **做什么**：对 books 下的书籍执行「备份 →（可选预处理）→ 词库批量替换 → 校验」的完整校正。带 `no-preprocess-fix` 参数时跳过预处理，改为交互选择特殊模式（严格模式、生僻字注音、多音字拆分等）；带 `temp-fix` 参数时改走「临时校对表替换」子流程。
- **输入**：books 下的 txt / EPUB（EPUB 会先自动做文本合并）；交互选择的词库组合序号（按 `config/map.php` 的分组配置装配）与替换引擎（Go / PHP）。
- **输出**：修改后的 books 文件；校正前备份至 booksBak；全量修改副本至 booksFix；`temp-fix` 模式额外产出未命中校验报告。
- **关键流程**（`src/app/Command/FixText.php` + `src/app/Service/TextFixer.php`）：`prepareBookEnvironment` 备份与合并 → `buildReplaceMap` 组装词库（预处理时用预处理组合，否则用校正组合）→ `flattenMaps` 展开 before 数组与占位词条 → `doReplace` 分派到 `replaceByGo`（生成替换前后 JSON，调 `replace_by_go.exe` 多趟替换）或 `replaceByPHP`。
- **词库维度**（`src/app/Service/Map.php`）：支持 normal / extra / strict / 临时等多组词库组合；`mark` 排除机制可按排除项集合跳过词条；`filterForExtraMap` 按「地 / 得」等关键字过滤出 extra 子表。

### 3.2 formatting — 文本排版

- **做什么**：对 books 文件执行可选的预处理操作序列，操作编号在运行时交互选择（`src/config/formatting.php` 提供 punctuations、大小写、数字等全部数据）。
- **实现的处理项**（`src/app/Service/Formatting/FileProcessor.php` 的 `processFile`，按实际执行顺序）：编码与换行符转换 → 英文大小写转换（含数百个固定大小写词组 `fixedCaseWords`）→ 数字转换（阿拉伯↔中文，带防误伤表 `fixedArabicNumWords`）→ 去中文间空格 → 按标点分行 / 还原（分行时插入 `punctuationPartBreak` 标记）→ 特殊字符转义还原 → 标点规范化（全半角、省略号、破折号，约 40 组正则 `punctuationPatterns`）→ 多行引号处理（补行首引号 / 移除）→ HTML 转 TXT → TXT 排版（去空行、加缩进、章节分隔、剥离标签）→ 分级标题（◎ 标记转「第X部 / 卷 / 章」，最多三级）→ 书籍信息提取 → 附加校对声明（`username` 来自 config）→ 中英文之间加空格（pangu 风格）。
- **输入**：books 文件 + 交互选择的操作编号；**输出**：处理后的 books 文件。特殊行为：执行「引号转换」类操作时会同步处理 booksBak 且不做备份（保证对比基准同步移动）。

### 3.3 EPUB 处理四命令

- **extract-epubs**（`src/app/Command/ExtractEpubs.php`）：解压 books 下的 EPUB 为同名文件夹（html / opf / ncx / css 等原样保留）。输入 EPUB，输出文件夹。
- **make-epubs**（`src/app/Command/MakeEpubs.php`）：把解压后的文件夹重新压缩为 EPUB（配合 `src/app/Util/FileZipper.php`）。输入文件夹，输出 EPUB。
- **merge-epub-text**（`src/app/Command/MergeEpubText.php`）：按 chapter 顺序抽取 EPUB 各章节文本，合并生成同名 TXT（合并日志在 `logs/merge`），供阅读软件打开做批注。输入 EPUB，输出合并 TXT。
- **split-epub-text**（`src/app/Command/SplitEpubText.php`）：按合并时的章节边界标记，把修改后的合并 TXT 拆回 EPUB 内各章节文件。输入合并 TXT，输出还原后的章节文件。

### 3.4 check-quotation-marks — 引号检查与修复

- **做什么**：对全部书籍做中文单双引号的栈式配对检查，交互式逐处确认修复；支持 `from-gui` 参数进入 GUI 协作模式（由引号检查 GUI 以子进程驱动）。
- **检查项**（`src/app/Service/Quotation/QuotationChecker.php`）：缺左 / 右引号、引号交叉错乱、空引号、双引号内嵌套独立双引号、跨行未闭合（单层引号可跨行，向下最多探测 100 行并校验风格一致性）；英文撇号（前后为字母）会被过滤不报错。
- **自动修复链**（`src/app/Service/Quotation/QuotationFixer.php`）：7 种规则自动修复——双套双改单、写反引号反转、连续同向引号归一、句尾孤立右引号移除、补左引号、按文件类型补右引号；另有「最外层单引号批量改双引号」的批量操作。
- **交互**：每处报错打印上下文（GUI 模式输出更多行），操作码 `1` 退出 / `x` 强制跳过 / `f` 强制修复 / `c` 仅统计错误数。
- **输入**：books 文件；**输出**：控制台错误清单 + 修复后的文件。

### 3.5 generate-words — 从批注生成校对表

- **做什么**：把阅读软件导出的批注笔记转换成「临时校对表」词条，写入 `src/maps/5.临时校对表.php`。
- **输入**：`logs/` 下的批注文件。支持 9 种批注格式的正则匹配（`src/app/Service/Note/NoteParser.php` 的 `noteMatchPatterns`），内置 3 个品牌处理器：静读天下（moonreader）、Calibre、微信读书（weread）。
- **转换体系**（`src/app/Service/Note/NoteConverter.php` + `NoteConstants.php`）：批注内支持一套操作符语法——`#` 分隔多条、`@` 定向匹配、`+` 追加、`-` 删除叠字、`。。` 定位标记（支持按位置插入 / 删除 / 替换 / 换行）、`##` / `@@` / `!!` 等特殊标记、阿拉伯与中文数字互转（含「二→两」特殊规则）。
- **分类落库**（`src/app/Service/Note/NoteClassifier.php` + `ResultGenerator.php`）：6 类分类（同值 / 缺规则 / 固定规则生成 / 排版标记 / 普通映射 / 额外信息），写入 `$tempMap`（`$genByNotes = true` 标记来源为批注），额外信息以 JSON 注释块保存。
- **输出**：`src/maps/5.临时校对表.php` 词条；随后由 `ReplacementChecker`（`src/app/Service/Note/ReplacementChecker.php`）在替换阶段校验命中率，未命中清单写入 `logs/report/临时校对表未命中结果.txt`。

### 3.6 generate-report — 生成替换报告

- **做什么**：以 booksBak 为基准，对比 books 的当前差异，把「本轮实际发生的替换」反推为替换对，写入临时校对表（`src/app/Service/Diff/Extractor.php` 的 `genReplaceCountReport`，配合 `src/app/Util/PatchAnalyzer.php` 与 msys `diff.exe`，配置在 `src/config/diff.php`）。
- **输入**：booksBak（校正前备份）+ books（校正后）；**输出**：临时校对表词条 + `logs/report/` 下的统计报告。
- **前置**：必须先跑过至少一轮校正（否则 booksBak 与 books 无差异）。

### 3.7 generate-book-maps — 生成书籍专有词库

- **做什么**：对比 booksFix 与 books，把「本书特有且已确认的修改」沉淀为专有词条，写入 `src/maps/书籍专有替换词库/{书名}.php` 的 `bookNotes` 数组（文件名须与书名一致，见该目录 `README.md`）。
- **输入**：booksFix + books；**输出**：书籍专有词库文件。已随包附带两份示例词库供参照。

### 3.8 temp-fix-books-bak — 同步替换报告至 booksBak

- **做什么**：带 `temp-fix` 参数把临时校对表中的替换同样应用到 booksBak，使备份基准与 books 保持一致（避免下一轮 generate-report 重复报告旧差异）。输入 booksBak，输出同步后的 booksBak。

### 3.9 manual-search — 手动检索替换

- **做什么**：对单文件（books 下有且仅有一个 txt 时运行）按 `src/maps/手动检索规则表.php` 的正则规则逐条人工判断并替换，主要处理自动替换易漏改的混淆字。
- **实现**（`src/app/Service/ManualSearch/ManualSearcher.php`）：加载规则 → 按颜色分组 / 替换次数 / 文件顺序 3 种方式排序展示 → 选择序号（支持 `1`、`1 2 3`、`1-3`、`1-3,10-20`、`+` 看详情）→ 执行替换。
- **防重复**（`src/app/Service/ManualSearch/BookMapManager.php`）：已执行过的规则记入 `manualSearchedMarks`，存到书籍专有词库文件，下次自动排除。
- **输入**：单个 txt + 规则表；**输出**：修改后的文件 + 已执行规则记录。

### 3.10 find-dupl-text — 重复段落检测

- **做什么**：检测书籍中的重复段落（`src/app/Service/DuplTextFinder.php`）。先做重复章节名检测（`src/app/Util/ChapterAnalyzer.php`，发现即阻断询问），再按 6 个锚字（的是了一，。）截取句片段（≥20 字），聚合相同片段、去重、标记连续段落（行号差 ≤3 视为相邻），支持 3 种排序重排结果。
- **输入**：books 文件；**输出**：`logs/report/重复段落检测结果.txt`。

### 3.11 csv-operation — 词库与 CSV 互转

- **做什么**：把词库导出为 CSV（`,`、引号、换行等转义为中文占位符），或把 CSV 词条行写回词库（`src/app/Service/Csv.php`）。词库范围由 `config/map.php` 的 `fileMapping`（28 个变量名映射到 8 个词库文件）决定。
- **注意**：`Csv::loadMapFromCsv` 方法在源码中标注「暂时未调用」，属预留能力。

### 3.12 其余三个命令

- **extract / make 已见 3.3**；**clear-books**（`src/app/Command/ClearBooks.php`）：清空 books / booksBak / booksFix / logs（含批注），带确认交互，破坏性操作。
- **rename-files-for-compare**（`src/app/Command/RenameFilesForCompare.php`，自述「比较文件时以基准文件名进行重命名」）：先统一排版格式，再以 books 中「！」或 `!` 开头的文件作为基准文件名（剥离书名号与「校对」「作者」等多余说明），把 booksBak 中对应文件重命名成与 books 一致的命名，方便 Beyond Compare 等工具逐文件比对；重命名前的同名冲突文件会先移入 booksBak。无 bat 入口，经统一控制台调用。
- **de-drm**（`src/app/Command/DeDrm.php`，实现 `src/app/Service/DeDrmWriter.php`）：重打包 EPUB 时排除 `encryption.xml`（伪 DRM 加密），并对含 `:*` 等非法字符的文件名改名并同步替换内部引用。无 bat 入口，经统一控制台调用。

### 3.13 支撑组件（Util 层）

- `src/app/Util/Util.php`：通用工具集（书籍环境准备、文件遍历 Walk、GUI 模式检测 `isFromGUI`、ANSI 颜色控制等）；
- `src/app/Util/ChapterAnalyzer.php`：章节名分析与重复章节检测（供重复段落检测、GUI 章节标题显示调用，另有独立脚本 `src/scripts/chapter_analyzer.php`）；
- `src/app/Util/NumberConverter.php`：阿拉伯数字 ↔ 中文数字转换（含大写数字、位数处理）；
- `src/app/Util/PatchAnalyzer.php`：diff 补丁解析（配合 generate-report）；
- `src/app/Util/FileZipper.php`：ZIP / EPUB 打包解包；
- `src/app/Service/PatternFileLoader.php`：加载手动检索规则表与「地」前缀断言、标点集合；
- `src/app/Service/ZhuyinProcessor.php`：生僻字注音的 4 种模式处理（仅注一次 / 所有位置 / 取第一读音 / 多音字拆分），实现「先跑替换统计生成临时报告 → 提取拼音映射 → 从 booksBak 还原 → 一次性应用」的流程，供 fix-text 特殊模式调用。


## 四、GUI 工具（src/tools，PyQt5）

四个 GUI 均在 `src/tools/` 下，共享 `src/tools/env/config.ini` 配置文件（各 GUI 各占一个配置节），依赖声明于 `src/tools/pyproject.toml`（PyQt5、regex、ansi2html、pypinyin、portalocker、qtpy 等）。GUI 与 PHP 的通信模式统一为「QProcess 子进程 + stdin 指令 + stdout 回传」或「临时文件协议」。

### 4.1 统一控制台

- **源文件**：`src/tools/uni_console_pyqt/uni_console_pyqt.py`（主窗口，753 行）+ `command_tab.py`（326 行，命令页签组件）+ `output_formatter.py`（ANSI 转 HTML 输出渲染）。
- **做什么**：把全部常用任务汇总成一个图形面板，按五组组织：

  1. **建议流程**：查重（`find-dupl-text`）→ 排版（`formatting`）→ 校正（`fix-text`）→ 引号检查 → 全局搜索 → 手动检索 → 书籍清理（一次执行类，带红色警示）；
  2. **EPUB 相关**：EPUB 解压 / 压缩还原 / 文本合并 / 拆分还原 / 移除伪 DRM 加密（唤起外部 GUI）/ 多 EPUB 合并（唤起外部 GUI）；
  3. **批注笔记相关**：生成校对表（`generate-words`，带前置动作：先弹文件选择把批注文件复制到 logs）、临时校对表替换（`fix-text temp-fix`）；
  4. **替换报告**：生成替换报告（`generate-report`）、应用至 booksBak（`temp-fix-books-bak temp-fix`）、生成书籍专有词库（`generate-book-maps`）；
  5. **其他工具**：临时校对表替换、词库 CSV 互转、词条相关操作（调词条 GUI）、比较时重命名、调整章节顺序、多 EPUB 合并。
- **任务类型**：可交互（自动启动命令进程、面板可继续发指令）、一次执行（选中即确认执行，支持前置动作）、仅说明（只展示说明）、唤起外部 GUI（后台启动另一个 GUI 程序）；重复点击会询问是否重新运行。
- **书籍导入导出**：支持拖拽或按钮导入书籍（自动复制进 books；EPUB 导入后自动执行 EPUB 文本合并）；导出结果时检测「EPUB 合并文件」前缀的 txt，先弹拆分确认再导出。
- **配置**：`config.ini` 的 `[uni_console]` 节，引用根目录 bat（引号检查、词条相关操作、文件全局搜索、章节顺序调整、多 EPUB 合并）与 `main.php`。**默认隐藏 4 个任务**（`exclude` 配置）：移除伪 DRM 加密、比较时重命名文件、调整章节顺序、多 EPUB 合并——其中后两项引用的 `章节顺序调整.bat` 与 `多 EPUB 合并.bat` 在压缩包根目录并不存在（见第八章）。

### 4.2 引号检查 GUI

- **源文件**：`src/tools/quotation_checker_pyqt/quotation_checker_pyqt.py`（969 行）。
- **做什么**：`ProcessManager` 以子进程启动 `php main.php check-quotation-marks from-gui`，用正则解析其 stdout（文件名、报错段落、进度、错误总数），把 256 色 ANSI 输出转为 HTML 渲染；右侧文本编辑器展示当前错误段落并高亮引号，可直接编辑并保存回写原文件，保存后自动跳到下一处。
- **快捷修复**：`Alt+1` 前后引号互换、`Alt+2` 单双引号互转、`Alt+3` 合并行、`Alt+4` 单引号转〔〕、`F1~F4` 插入四种引号；另有「错误统计」按钮，仅统计错误总数。
- **输入**：books 文件；**输出**：修复后的文件 + 界面内错误列表。配置读 `config.ini` 的 `[quotation_checker]` 节。

### 4.3 文件全局搜索

- **源文件**：`src/tools/file_global_search_pyqt/main_window.py`（主窗口）+ `controllers/`（8 个控制器：搜索 / 替换 / 保存 / 历史 / 导航 / 文件 / 样式 / 匹配扩展）+ `services/`（对应 7 个服务）+ `tasks/`（后台任务：search_task / save_task / file_count_chars_task / navigation_counter_task）+ `utils/`（chapter_num_checker / text_case_converter / text_counter / patch_formatter 等）。
- **做什么**：针对 books 目录（`config.ini[file_global_search]` 节的 `file_dir`）的跨文件正则搜索与替换编辑器，核心能力：

  - **搜索**：调 PHP 脚本 `src/scripts/regex_searcher.php`（「正则文件 + 目标文件 + 结果 JSON 文件」三参数协议，内部做字节偏移→字符偏移转换）在后台线程执行，可随时终止；支持上文 / 下文行数控制（相邻匹配连成块）、大小写、历史、章节标题显示（调 `src/scripts/chapter_analyzer.php` 取章节结构）、搜索历史记录（持久化到 `history_log_file` JSON，含窗口位置记忆）。
  - **替换**：替换下一处 / 替换选区 / 全部替换，均带撤销；右键菜单还提供英文大小写转换（5 种模式，`TextCaseConverter`，模式 4 用 `formatting.php` 的固定词组）、批注规则单条转换（选中后输入替换文，调 `src/scripts/fixed_rules_converter.php` 复用批注转换规则）、HTML 标签剥离、合并选中行、扩展当前匹配。
  - **保存**：保存任务把当前文件全部有效替换整理成替换前后清单，调用 Go 引擎 `replace_by_go.exe`（`go_replace_cmd` 配置）批量应用写回 books，同时支持把改动同步到 booksBak（编辑器 diff 同步信号）。
  - **比对视图**：用 `diff` 命令（优先系统 diff，否则用配置的 msys `diff_cmd`）生成 books 与 booksBak 的差异视图，差异标记（添加 / 删除 / 替换）可单点恢复反转；首次启动有内置指引文本，另配 `compare_guidance_md` 说明与 BC 工具配合使用。
  - **章节序号检查**：`ChapterNumChecker` 解析章节行（支持中文数字、范围「1-2」、子序号后缀「（上 / 中 / 下）」），检测序号断档 / 乱序并支持重排（特殊章节 `0.0` 不参与）。
  - **文件管理**：文件列表增删刷新、拖拽导入（自动复制到 books）、EPUB 导入自动执行合并（`epub_merger` 指向 `main.php`）、字符统计（`TextCounter`，后台线程）。
- **输入**：books 文件 + 用户正则 / 替换文本；**输出**：修改后的 books 文件（经 Go 引擎写回）、booksBak 同步、持久化的搜索 / 替换历史。

### 4.4 词条相关操作 GUI

- **源文件**：`src/tools/words_operations_pyqt/words_operations_pyqt.py`（280 行）。
- **做什么**：为 `src/scripts/` 下的词条维护脚本提供图形界面，7 个按钮对应 7 个操作——查重 / 检索 / 删除 / 合并 / 展开 / 写入 / 清除行号，分别调用 `词条查重.php`、`词条检索.php`、`词条删除.php`、`词条合并.php`、`词条展开.php`、`词条写入.php` 等脚本。
- **协议**：输入经 `tmp_argv.txt` 传给脚本，脚本输出写到 `tmp_output.txt` 再由界面读回渲染（带 PHP 语法高亮）；词库文件下拉（`MAP_FILES`：1/2/3/4/7 号词库）与变量名下拉（`MAPS`：normalMap、extraMap 等含 t2sRadicalMap）两级选择。
- **输入**：用户指令 + 词库选择；**输出**：修改后的词库文件或检索结果展示。配置读 `config.ini` 的 `[words_operations]` 节（含 `php_program`）。

## 五、词库与配置体系

### 5.1 配置文件（src/config 与 main.php 常量）

- **main.php**（入口文件，第 6\~53 行）：集中定义全部运行常量——`SCRIPT_DIR`、`BOOK_DIR`（books）、`BOOK_BAK_DIR`（booksBak）、`BOOK_FIX_DIR`（booksFix）、`EPUB_MERGE_LOG_DIR`（logs/merge）、`EPUB_LIST_LOG`、`REPORT_DIR`（logs/report）、`EPUB_EXTRACT_PREFIX`（「EPUB 解压文件夹」）、`EPUB_MERGE_PREFIX`（「EPUB 合并文件」）、`TEMP_MAP_FILE`（`src/maps/5.临时校对表.php`）、`REPLACE_BY_GO` 与 `GO_REPLACE_CMD_FILE`（Go 替换引擎开关与路径）、替换中转文件 `TXT_REPLACE_BEFORE/AFTER.txt`，以及 gojieba 分词相关常量（`TOKENIZE_CONTENT = false`，见第八章）。
- **config/map.php**：词库装配中枢。`useMapsConfig`（第 15 行起）定义 10 组「按流程选择词库组合」的配置（预处理 / 校正 / 严格模式等各用哪组词库）；`fileMapping`（第 144 行起）把 28 个词库变量名映射到 8 个词库文件（`tempMap` 映射到 5.临时校对表.php 等）。
- **config/general.php**：批注快捷转换规则 `fixedNoteRules`——批注内容命中某条规则时（如「的地得」「在再」「像象相向橡」），把划线内容中该规则的全部字词统一为批注字词，生成词条的 after；支持批注里用 `#` 组合多条规则，靠前的规则优先且生效后停止遍历。该规则被 `NoteConverter::applyFixedRules` 与 `generate-words` 流程消费。
- **config/diff.php**：diff 工具路径与对比选项（msys `diff.exe`，随包在 `src/tools/` 下，附 `msys-1.0.dll`）。
- **config/formatting.php**（424 行）：排版数据源——`username`（校对声明署名）、`punctuationMap`（全半角与省略号 / 破折号规范化）、`punctuationPatterns`（约 40 组英文标点转中文、引号转换、重复标点归一正则）、`fixedCaseWords`（数百个固定大小写词组，支持断言）、`fixedArabicNumWords`（如「国窖1573」等防误伤表）。

### 5.2 词库文件（src/maps）

全部为返回 PHP 数组的文件，`Map.php` 按需 include 后展开使用：

| 文件 | 主要变量 | 内容 |
|-|-|-|
| 1.自定义词库.php | `preprocessMap`、`normalMap`、`extraMap`、`strictMap`、`regexMap`、`extraRegexMap`、`strictRegexMap`、`excludedWords`、`postFixMap`、`puncts`、`dePrefixPattern`、`dieci` 等 | 核心自定义词库（9 万行级），普通词条 + 正则词条 + 排除项集合 + 叠词 / 标点 /「地」后缀断言等辅助数据；文件头含「RegExp Outline」编辑器规则注释 |
| 1.自定义词库【旧式、通假写法】.php | `oldStyleMap`、`regexMap` | 旧书常见通假写法（校正旧书时可选择性修正） |
| 2.繁转简词库.php | 繁转简映射（含 `radicalsSupplementMap` 补充表） | 繁体字 / 词转简体 |
| 3.txtFormat 词库.php | `txtFormatMap` | txtFormat 工具的「常见错别字」词库（8.7 万行级） |
| 4.的地得词库.php | `dddMap`、`accurateDddMap` | 「的地得」误用修正词库（1.4 万行级） |
| 5.临时校对表.php | `tempMap` | **工作产物文件**：批注校对表与替换报告的落点；出厂仅含占位词条与注释掉的示例 |
| 6.用户扩展词库.php | `customPreprocessMap` 等若干 `custom*Map` | 用户对各类词库的扩展挂载点（当前均为空数组，预留） |
| 7.生僻字词库.php | `shengpiziMap` | 生僻字注音（来源 Sigil 注音插件，单音 / 多音 / 词语注音格式） |
| 7.生僻字词库【扩展区】.php | `cjkExtMap`、`cjkRecoverMap` | CJK 扩展 B\~H 区生僻字注音 |
| 手动检索规则表.php | 规则数组 + `dePrefixPattern`、`puncts` | 手动检索的正则规则（支持 color 分组着色；当前规则多为注释掉的历史示例） |
| 书籍专有替换词库/ | `bookNotes`（每书一个文件） | 每本书的专有词条 + `manualSearchedMarks`（已执行手动检索规则记录）；含两份示例与 README（文件名须与书名一致） |

词库条目统一为 `['before' => ..., 'after' => ..., 'mark' => ...]` 结构，`before` 可为数组（一对多），`mark` 用于排除机制；`flattenMaps` 负责展开与 `@` 占位词条组合。

## 六、辅助脚本（src/scripts，12 个）

脚本统一由 `src/scripts/autoload.php` 引导（设定 4096M 内存上限、定位 SCRIPT_DIR、定义 `writeToOutputFile` 输出到 `tmp_output.txt`），主要服务词条维护与 GUI 后端：

- **词条查重.php / 词条检索.php / 词条删除.php / 词条合并.php / 词条写入.php / 词条展开.php**：词库维护六件套——查重（after+mark 跨 5 个词库文件查重并标注重复）、检索（按关键词搜词库并按 Map 分组输出带行号结果）、删除（按行删除词条）、合并（把多个 before 合并为一对多词条、查重并标注「已有重复词条 / 原已有词条」）、写入（把「原已有词条」合并回 1.自定义词库.php 的 `normalMap`）、展开（用 `flattenMaps` 展开词库供人工核对，可选排序）。均由词条操作 GUI 调用，也支持直接命令行运行。
- **regex_searcher.php**：文件全局搜索的后端。三参数文件协议（正则文件 + 目标文件 + 结果 JSON 文件），执行正则搜索并把字节偏移转换为字符偏移后写 JSON 结果。
- **chapter_analyzer.php**：章节结构分析后端，调 `ChapterAnalyzer::analyze` 把章节信息写入临时 JSON 文件（路径打印到 stdout），供全局搜索 GUI 显示章节标题。
- **fixed_rules_converter.php**：单条批注转换后端，调 `NoteConverter::convertByFixedNoteRules` 对 GUI 中选中的文本执行批注规则转换并回传结果。
- **书籍专有词库格式调整.php**：一次性迁移脚本，把书籍专有词库文件的历史词条统一包进 `bookNotes` 数组格式。
- **修改 vendor 内容.php**：维护性脚本，对 vendor（inhere/console 与 Color.php）打中文化补丁；vendor 升级后需重新执行。

## 七、功能依赖关系

- **校正主流程（fix-text）**：依赖 `config/map.php` 的词库组合配置 → `Map.php` 装配展开 → Go 引擎（`REPLACE_BY_GO` 开关 + `replace_by_go.exe`，经 `TXT_REPLACE_BEFORE/AFTER.txt` 中转）或 PHP 引擎执行替换；EPUB 输入依赖 merge-epub-text 的合并能力；备份写 booksBak、全量副本写 booksFix。
- **批注校对闭环**：`generate-words`（依赖 logs 下批注文件 + `config/general.php` 的 fixedNoteRules）→ 写 5.临时校对表.php → `fix-text temp-fix`（依赖临时校对表）执行替换 → `ReplacementChecker` 校验命中（仅当词库标记 `$genByNotes = true` 时启用）→ 未命中报告落 logs/report。
- **替换报告闭环**：先跑一轮校正产生 booksBak 与 books 的差异 → `generate-report`（依赖 msys diff.exe + `PatchAnalyzer`）反推替换对写临时校对表 → 可选 `temp-fix-books-bak temp-fix` 把报告同步到 booksBak，避免下轮重复报告。
- **书籍专有词库闭环**：fix-text 产出 booksFix → `generate-book-maps` 对比 booksFix 与 books 提取专有词条 → 专有词库参与后续轮次的校正与手动检索去重（`manualSearchedMarks`）。
- **引号检查**：命令行版独立运行；GUI 版依赖 PHP 进程（from-gui 模式）+ config.ini 的 `[quotation_checker]` 节。
- **GUI ↔ PHP 通信**：统一控制台与引号检查 GUI 用 QProcess + stdin 指令；文件全局搜索与词条 GUI 用「临时文件协议」（tmp_argv.txt / tmp_output.txt / 三参数 JSON）+ 独立脚本后端；全部路径经由 `src/tools/env/config.ini` 桥接。
- **外部工具依赖**：msys `diff.exe`（随包在 src/tools，比对视图与报告生成使用）、`replace_by_go.exe`（随包，替换引擎）；文档推荐配合 Beyond Compare 使用（比对指引见 `compare_guidance_md`）。

## 八、未实现 / 半成品与注意点盘点

以下为代码中实际可见的未完成或需注意事项，均注明出处，无推测：

1. **入口数量差异**：说明材料曾称 22 个 bat，压缩包根目录实际为 21 个（17 个编号 + 4 个未编号）。
2. **两个被引用但缺失的 bat**：`config.ini` 的 `[uni_console]` 节引用了根目录的 `章节顺序调整.bat` 与 `多 EPUB 合并.bat`（`chapter_sorter_cmd` / `epub_merger_cmd`），这两个文件在压缩包中不存在；对应的「调整章节顺序」「多 EPUB 合并」两个任务恰好也在 `exclude` 默认排除列表中，界面默认不显示，故不会触发报错——但一旦取消排除即会因文件缺失而无法运行。
3. **统一控制台默认隐藏 4 个任务**：`exclude` 配置默认排除「移除伪 DRM 加密、比较时重命名文件、调整章节顺序、多 EPUB 合并」；前两个命令本体存在可用（`de-drm` / `rename-files-for-compare`），后两个依赖缺失 bat。
4. **gojieba 分词功能预留未启用**：`main.php` 定义了 `TOKENIZE_CONTENT = false` 与 `GOJIEBA_CMD_FILE`（指向 `tools/gojieba.exe`）、`GOJIEBA_DICT`，但全仓库无任何调用代码，且 gojieba.exe / gojieba_dict.txt 均未随包分发——属预留能力。
5. **CSV 读入未接线**：`Csv::loadMapFromCsv` 标注「暂时未调用」，CSV 读回词库方向暂不可用（词库→CSV 导出、CSV→词条行写入可用）。
6. **词条 GUI 变量下拉与脚本词库范围不完全一致**：words_operations 的 `MAPS` 变量下拉含 `t2sRadicalMap`，而词条查重等脚本实际只 include 5 个词库文件，选择该变量做查重时覆盖范围可能小于界面呈现（以各脚本源码 include 列表为准）。
7. **5.临时校对表.php 与 6.用户扩展词库.php 当前为空壳**：前者仅含占位词条与注释示例（属正常——它是 generate-words / generate-report 的工作产物落点），后者各 `custom*Map` 均为空数组（预留扩展位）。
8. **手动检索规则表当前无启用规则**：`maps/手动检索规则表.php` 的规则大多为注释掉的历史示例，开箱状态下 manual-search 无规则可执行，需用户自行取消注释或补充。
9. **vendor 补丁依赖**：`修改 vendor 内容.php` 对框架源码打中文化补丁，vendor 目录升级后需重新执行，否则界面文案回退为英文。
10. **一次性脚本**：`书籍专有词库格式调整.php` 为历史数据迁移脚本，正常使用中无需再跑。

## 附录：源码文件索引

- 命令层：`src/app/Command/`（17 个命令类，文件名与命令一一对应）
- 服务层：`src/app/Service/`（TextFixer、Map、EpubFixer、Csv、DeDrmWriter、DuplTextFinder、ZhuyinProcessor、PatternFileLoader + Diff / Formatting / ManualSearch / Note / Quotation 五个子目录）
- 工具层：`src/app/Util/`（Util、ChapterAnalyzer、NumberConverter、PatchAnalyzer、FileZipper、Config、Console）
- 配置：`src/config/`（map.php、general.php、diff.php、formatting.php）+ `src/main.php` 常量
- 词库：`src/maps/`（10 个词库文件 + 书籍专有替换词库目录）
- 脚本：`src/scripts/`（12 个辅助脚本）
- GUI：`src/tools/`（uni_console_pyqt、quotation_checker_pyqt、file_global_search_pyqt、words_operations_pyqt、env/config.ini、pyproject.toml）
- 引擎与外部工具：`src/tools/replace_by_go.go`（Go 替换引擎源码及 exe）、`src/tools/diff.exe` + `msys-1.0.dll`

本文档基于解压源码逐文件分析整理，所有功能描述均对应实际代码，未运行验证的推断性内容已在第八章单独标注。
