"""FixText V1 · 导入链路的人话文案（T2.2）

界面里**不出现**技术词：字符集、编码、BOM、CRLF、spine、OPF、container.xml
这些词一律不出现在界面，本模块把技术事实翻译成一句普通人能看懂的话。

约定：
- 每个函数返回**一句**中文，主语是"这本书"，动词是"我帮你做了什么"。
- 不说"已转换为 UTF-8"，说"已按你计算机上常见的中文编码读出来，并改成通用格式保存"。
- 不解释原理，只说明**结果**和**我做了什么**（用户不需要知道为什么）。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 编码相关
# ---------------------------------------------------------------------------

#: 「这本书是用什么写的」→ 人话
_ENCODING_HUMAN = {
    "utf-8": "通用格式",
    "gbk": "老式中文格式",
    "gb18030": "国标中文格式",
    "big5": "繁体中文格式",
    "utf-16": "带标记的通用格式",
    "utf-32": "带标记的通用格式",
}


def encoding_label(codec: str) -> str:
    """对外展示的编码说法（人话，不含字符集名）。"""
    base = codec.replace("-sig", "")
    return _ENCODING_HUMAN.get(base, "通用格式")


def encoding_note(codec: str, certain: bool) -> str:
    """导入后展示的编码处理说明。"""
    if codec in {"utf-8", "utf-8-sig"}:
        return "这本书的字符格式是通用的，我直接读好了，没有改动任何字符。"
    human = encoding_label(codec)
    if not certain:
        return (
            f"这本书看起来是用{human}写的，我按最常见的那套规则读出来了。"
            "如果正文里有几个字显示不正常，导入后可以直接改。"
        )
    return (
        f"这本书是用{human}写的，我自动按对应规则读出来了，"
        "并改成了通用格式保存，这样后面的所有处理都不会再出现乱码。"
    )


def newline_note(changed: bool) -> str:
    if changed:
        return "书里的换行方式我统一过了，正文看起来和原来一样。"
    return "换行方式本来就是统一的，没有做改动。"


def uncertain_warning() -> str:
    return (
        "这本书的字符格式我没能完全确定，正文可能会有个别字显示不正常。"
        "导入后可以正常继续，遇到错字直接改即可。"
    )


# ---------------------------------------------------------------------------
# 导入方式（EPUB）
# ---------------------------------------------------------------------------

def epub_choice_title() -> str:
    return "这本书是电子书（EPUB）格式，你想怎么处理？"


def epub_choice_direct() -> tuple[str, str]:
    """返回 (标题, 一句说明)。"""
    return (
        "直接处理",
        "保持原书原样：章节、封面、插图都会保留，处理完还能导出成同样的电子书。",
    )


def epub_choice_to_txt() -> tuple[str, str]:
    return (
        "先转成 TXT",
        "把所有章节合并成一个纯文本文件，处理完导出 TXT，适合投稿或粘贴到别处。",
    )


def epub_merged_note(chapters: int) -> str:
    return f"已把这本书的 {chapters} 个章节按书的顺序合并成一份正文。"


def epub_chapters_title() -> str:
    return "章节顺序预览"


def epub_chapters_hint() -> str:
    return "下面是这本书的章节顺序，按书里原有的排列列出。如果发现顺序不对，可以点右下角告诉我。"


def epub_order_ok() -> str:
    return "章节顺序与书里的目录一致。"


def epub_order_suspect() -> str:
    return "有几章的标题和目录对不上，顺序可能有问题，建议看一眼。"


def epub_no_toc() -> str:
    return "这本书没有目录信息，章节按书的排列顺序列出，标题为空的位置会显示为「未命名章节」。"


def epub_unnamed_chapter() -> str:
    return "未命名章节"


def epub_cover_page() -> str:
    """书里第一页常常是封面（只有图、没有正文），单独给它一个名字。"""
    return "封面"


def epub_blank_page() -> str:
    """其它没有任何文字的一页（分隔页 / 空白插页）。"""
    return "空白页"


# ---------------------------------------------------------------------------
# 工作区与安全
# ---------------------------------------------------------------------------

def copied_note() -> str:
    return "书已经复制到 FixTextGUI 的工作区，你原来的文件和其它位置的文件都不会被改动。"


def unchanged_note() -> str:
    return "已核对：你原来的文件和导入前完全一样（逐字节对比一致）。"


def duplicate_note() -> str:
    return "这本书之前导入过，这次直接用了工作区里已有的副本，没有产生重复文件。"


def keep_working_copy_note() -> str:
    return (
        "工作区里已有这本书的正文（可能含校正/检查页修改），"
        "本次导入未覆盖，校正结果还在。"
    )


def big_file_note(size_mb: float) -> str:
    return f"这本书比较大（约 {size_mb:.0f} MB），导入会多花一点时间，请稍等。"


# ---------------------------------------------------------------------------
# 不支持 / 出错
# ---------------------------------------------------------------------------

def unsupported_type() -> str:
    return "目前只能导入 TXT 和 EPUB 两种文件。你可以把 Word 或 PDF 里的文字复制成 TXT 再导入。"


def empty_file() -> str:
    return "这个文件是空的，里面没有任何文字，暂时没法导入。"


def epub_broken(reason: str) -> str:
    return f"这个电子书文件打不开，可能下载时损坏了。可以重新下载一份再试。（{reason}）"


def not_a_book() -> str:
    return "这个文件不是一本完整的书，读不出章节内容，暂时没法导入。"


def too_many_files(n: int) -> str:
    return f"一次最多导入一本书，你选了 {n} 个文件。请先选一个。"
