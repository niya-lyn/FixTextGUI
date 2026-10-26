import re
import html
from utils.util import format_count_to_readable_chinese


class TextCounter:
    HTML_CHAPTER_MARK = "◎【chapter_mark】"
    EPUB_MERGE_PREFIX = "【EPUB 合并文件】"

    # For count_text_chars
    RE_LEADING_WHITESPACE = re.compile(r"^[ 　\t]+", flags=re.M)
    RE_TRAILING_WHITESPACE = re.compile(r"[ 　\t]+$", flags=re.M)
    RE_PUNCTUATIONS = re.compile(r"[\s&%#￥\$\*/，。？！…；、～~\-—－：:（）“”‘’\'\"《》【】〖〗「」『』\[\]·]")

    # For extract_text_from_html
    RE_TITLE = re.compile(r"<title>.*?</title>", flags=re.S | re.I)
    RE_STYLE = re.compile(r"<style.*?</style>", flags=re.S | re.I)
    RE_HEAD_DIV = re.compile(
        r'<div class="head1">.*?<div class="head" title="">.*?</div>.*?</div>.*?<p class="head">.*?</p>',
        flags=re.S | re.I,
    )
    RE_REVIEW_COUNT = re.compile(r'<span class="review-count">(.*?)</span>', flags=re.M)
    RE_NOTE_NUM = re.compile(r'note-num="(.*?)".*?>', flags=re.I)
    RE_NOTE_CONTENT_NUM = re.compile(r'note-content-num="(.*?)".*?>(.*)</a>', flags=re.I)
    RE_H_TITLE = re.compile(r'<h([^>]*?)title=[\'"](.*?)[\'"].*>\s*</h', flags=re.I)
    RE_H_TAG = re.compile(r"<h([^>]*?)>(.*?)</h", flags=re.I)
    RE_QUOTE_SPAN = re.compile(r'<span class="quote">(?!〖)(.*?)</span>', flags=re.M | re.I)
    RE_QUOTE_DIV_P = re.compile(r'<div class="quote([^<>]*?)">\s*<p>', flags=re.S | re.I)
    RE_P_DIV = re.compile(r"</p>(\n\s*)+</div>", flags=re.S | re.I)
    RE_QUOTE_DIV = re.compile(r'<div class="quote">(?!<p>〖)(.*?)</div>', flags=re.S | re.I)
    RE_QUOTE_DIV_2 = re.compile(r'<div class="quote-2">(?!<p>【)(.*?)</div>', flags=re.S | re.I)
    RE_HTML_TAGS = re.compile(r"<[^>]+>")

    _REPLACEMENTS = {
        "</h1><p": "</h1>\n<p",
        "</h2><p": "</h2>\n<p",
        "</h3><p": "</h3>\n<p",
        "<h4><p": "</h4>\n<p",
        "</h5><p": "</h5>\n<p",
        "</h6><p": "</h6>\n<p",
        "</p><p": "</p>\n<p",
        "</h1> <p": "</h1>\n<p",
        "</h2> <p": "</h2>\n<p",
        "</h3> <p": "</h3>\n<p",
        "<h4> <p": "</h4>\n<p",
        "</h5> <p": "</h5>\n<p",
        "</h6> <p": "</h6>\n<p",
        "</p> <p": "</p>\n<p",
        '<p class="brline"><img src="../Images/transpacep.png"/>　</p>': "※※※",
        '<p class="brline"><img alt="" src="../Images/transpacep.png"/>　</p>': "※※※",
        '<p class="brline">※ ※ ※</p>': "※※※",
        '<p class="break">……</p>': "※※※",
        "<p><br/></p>": "※※※",
        "<p>&#160;</p>": "",
        '<br class="note-br"/>': "\n",
        "<br/> ": " ",
        "<br/>": " ",
    }
    RE_REPLACEMENTS = re.compile("|".join(map(re.escape, _REPLACEMENTS.keys())))

    @classmethod
    def count_text_chars(cls, file, text, count_punctuations=True, readable_count=True):
        if cls.is_html_file(file):
            text = cls.extract_text_from_html(text)

        text = cls.RE_LEADING_WHITESPACE.sub("", text)
        text = cls.RE_TRAILING_WHITESPACE.sub("", text)
        text = text.replace("\n", "")
        text = text.replace(cls.HTML_CHAPTER_MARK, "")

        if not count_punctuations:
            text = cls.RE_PUNCTUATIONS.sub("", text)

        count = len(text)
        if readable_count:
            count = format_count_to_readable_chinese(count)

        return count

    @classmethod
    def is_html_file(cls, file):
        return file.lower().endswith((".html", ".htm")) or cls.EPUB_MERGE_PREFIX in file

    @classmethod
    def extract_text_from_html(cls, content):
        # 处理多余的样式、标题等
        content = cls.RE_TITLE.sub("", content)
        content = cls.RE_STYLE.sub("", content)
        content = cls.RE_HEAD_DIV.sub("", content)
        content = cls.RE_REVIEW_COUNT.sub("", content)

        # 处理注释，注标序号为页内计数
        content = cls.RE_NOTE_NUM.sub(r'note-num="\1">（注\1）', content)
        content = cls.RE_NOTE_CONTENT_NUM.sub(r'href="#noteref_\1">（注\1：\2）', content)

        # 处理分隔符和其他需要手动调整的符号
        content = cls.RE_REPLACEMENTS.sub(lambda m: cls._REPLACEMENTS[m.group(0)], content)

        # 标题强制加标记，格式化排版时再移除
        content = cls.RE_H_TITLE.sub(r"<h\1>\2</h", content)
        content = cls.RE_H_TAG.sub(r"<h\1>" + cls.HTML_CHAPTER_MARK + r"\2</h", content)

        # 恢复某些引言标记
        content = cls.RE_QUOTE_SPAN.sub(r"〖\1〗", content)
        content = cls.RE_QUOTE_DIV_P.sub(r'<div class="quote\1"><p>', content)
        content = cls.RE_P_DIV.sub(r"</p></div>", content)
        content = cls.RE_QUOTE_DIV.sub(r"〖\1〗", content)
        content = cls.RE_QUOTE_DIV_2.sub(r"【\1】", content)

        # 使用自带函数移除其他所有标签
        content = cls.RE_HTML_TAGS.sub("", content)

        # 处理 html 实体
        content = html.unescape(content)

        return content
