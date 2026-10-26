# epubtext —— EPUB 文本合并与还原模块

M1-T1.3 交付物。独立 Python 模块，供编排器以 **函数调用** 或 **CLI 子进程** 两种方式驱动。

- 合并：EPUB → 单个 TXT（`zipfile` + OPF/NCX/spine 解析）
- 还原：TXT → EPUB（按章回填模板包，保留图片/样式/目录）

## 为什么不是"按文件名排序 + `</html>` 切分"

原 PHP 实现（`FixText/src/app/Service/EpubFixer.php`）有两个会**静默产出错书**的做法，本模块针对性改掉：

| 原实现 | 风险 | 本模块 |
| --- | --- | --- |
| 文件按索引与 `$origFilenames[$k]` 对齐 | 章节数与文件数不一致就整体错位，不报错 | 账本按 `path` 精确配对，路径不符直接抛 `BundleFormatError` |
| `explode("</html>\n")` 切分 | 正文里出现该字面串即多切一段 | 行级标记 `<!-- EPUBTEXT-SPLIT:nonce:i ... -->`，标记缺失/重复/错序都是硬错误 |
| 顺序取自目录列表 | `chapter10` 排在 `chapter1` 后 | 顺序**只**取自 `spine`；NCX 仅提供章节标题 |

## 安装与运行

```bash
# 依赖
pip install lxml          # 解析 OPF/NCX/XHTML
pip install pytest ebooklib   # 测试与独立阅读器交叉验证（仅验证用）

# 作为模块
PYTHONPATH=src python3 -m epubtext roundtrip book.epub --output-dir out/

# 分步
PYTHONPATH=src python3 -m epubtext merge   book.epub -o book.txt
PYTHONPATH=src python3 -m epubtext restore book.txt --template book.epub -o book_restored.epub
PYTHONPATH=src python3 -m epubtext check   book_restored.epub
```

所有 CLI 子命令都只输出**一个 JSON 对象**，成功 `ok: true`，异常统一 `{"ok": false, "error": ..., "message": ...}` 且退出码 2，便于编排器判断。

## 编排器接入

```python
from epubtext import merge_epub, restore_epub, check_epub, compare_content, compare_bytes

merged   = merge_epub("book.epub")                    # -> book.txt + book.bundle.json
report   = check_epub("book_restored.epub")           # 结构与正文自检
restored = restore_epub(merged.text_path, merged.ledger_path, "book.epub")
content  = compare_content("book.epub", restored.epub_path)
binary   = compare_bytes("book.epub", restored.epub_path)
assert report.ok and content["content_ok"] and binary["byte_identical"]
```

批量场景（多本书合并成一个 TXT，或整目录合并）：

```python
from epubtext import merge_many, restore_many, merge_directory

merged   = merge_many(["a.epub", "b.epub"], "all.txt")     # 账本里按书分组，章索引全局连续
restored = restore_many(merged.text_path, merged.ledger_path, ["a.epub", "b.epub"], "out/")

results = merge_directory("in/", "out/")                    # 目录内每本各生成一份 TXT
```

## 文件布局

```
src/epubtext/
  archive.py    ZIP 层：条目名归一化、percent-encoding 兼容、mimetype 规范写入
  package.py    OPF/NCX/spine 解析；spine 权威顺序；NCX↔spine 一致性检查
  bundle.py     TXT 包格式 + 账本；切分与字节重建（唯一权威实现）
  merge.py      EPUB → TXT
  restore.py    TXT → EPUB（按模板包逐条替换）
  validate.py   独立自检（不复用合并侧逻辑）+ 内容/字节比对
  cli.py        merge / restore / check / roundtrip
```

## 合并产物格式

```text
<!-- EPUBTEXT-BUNDLE format=epubtext-bundle/1 nonce=<8-32 hex> books=1 chapters=N -->
<!-- EPUBTEXT-BOOK:<nonce>:0 title=.. source=book.epub chapters=N -->
<!-- EPUBTEXT-SPLIT:<nonce>:0 path=OEBPS/c1.xhtml label=.. chars=.. sha=.. -->
<章节原始 XHTML>

<!-- EPUBTEXT-SPLIT:<nonce>:1 path=... -->
...
```

- `nonce` 每次运行随机；混入标记可防止把两次合并的文本拼错。
- 正文**原样保留 XHTML**（不剥标签），因此还原能恢复图片引用、内链、样式类。
- 侧车账本 `<stem>.bundle.json` 记录每章 `path/label/size/sha256/eol/tail/bom`。
- `eol`、`tail`（尾部换行）、`bom` 三个字段让**字节级**可逆：`sha256` 记录的是**原始字节**（含 BOM、含 CRLF），还原后 `compare_bytes` 可直接判等，而不是近似。

## 校验方式（三层，互相独立）

1. **结构自检** `check_epub`：CRC、`mimetype` 必须是首条目且 `STORED` 且 `extra` 为空（否则部分阅读器拒绝打开）、container/OPF 可解析、spine 文件齐全、manifest href 可解析、逐章 XHTML 可解析。
2. **正文比对** `compare_content`：按 spine 逐章比 `<body>` 文本（空白归一）。只比 `<body>` 是刻意的——正文被清空而 `<title>` 还在时，仍会判为**正文缺失**而不是"文本不同"。
3. **字节比对** `compare_bytes`：逐条目 `sha256`，`byte_identical` 即"与原书完全一致"。

切分侧另有**三重校验**（`split_bundle(strict=True)`）：头部存在且 nonce 与账本一致、标记序号从 0 连续且总数等于声明值、每个标记的 `path` 与账本同位置记录相同。

> `check_epub` 刻意不复用 `merge`/`restore` 的解析结果重新包装，而是重新独立解析；否则"校验通过"只是"同一段代码自证"。

## 测试

```bash
PYTHONPATH=src:. python3 -m pytest tests/ -q
```

- `test_package.py` — 顺序权威性、NCX 映射、path 逃逸/百分号编码、nav 排除
- `test_bundle.py` — 标记往返、CRLF/BOM/尾部换行字节可逆、各类篡改拒绝
- `test_roundtrip.py` — 合成样本往返、spine 打乱仍保持、定向改章、`allow_modified=False`
- `test_validate.py` — mimetype 规范、非 zip、内容缺失识别、大文本
- `test_integration.py` — **两个真实样本**的往返与顺序证明、多书合并、语料大文本

真实样本测试依赖 `in/` 下的云盘材料（`paohuo.epub`/`wanjia.epub`/`corpus/*.txt`），
缺失时 skip 而非伪造。可通过 `EPUBTEXT_SAMPLE_DIR`、`EPUBTEXT_CORPUS_DIR` 指向其他目录。

## 已知限制

- **未跑 epubcheck**：沙箱内无 `java`，官方 java 版 epubcheck 无法运行。结构校验由本模块自实现（覆盖 mimetype 规范、CRC、container/OPF/spine/manifest 完整性），并用第三方阅读库 `ebooklib` 实际打开做交叉验证。
- **无 NCX 的 EPUB**（EPUB3 仅 nav）仍能合并（顺序取自 spine），但章节 `label` 退化为空串（不会凭空编标题）；`looks_like_chapter_title()` 已备好作为后续兜底入口，当前未接入合并流程。
- **加密/DRM 包**不支持（`META-INF/encryption.xml` 未处理），会按普通条目读取而得到密文。
- **还原依赖模板 EPUB**：还原是"回填模板"，不是从纯文本重建包。图片/样式/字体必须由模板提供。
- `linear="no"` 的 spine 条目仍参与合并（否则会丢内容），仅在账本里标注 `linear=False`。
- 单核 4 GB 沙箱实测：788 章 / 10.5 MB TXT 合并 0.28 s、还原 0.58 s；4 本共 276 万字符 → 8.0 MB TXT 合并 0.51 s、还原 0.95 s。更大规模未压测。
