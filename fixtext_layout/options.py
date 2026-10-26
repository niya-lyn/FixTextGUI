"""排版选项。

字段与 FixText 的 ``App\\Service\\Formatting\\Option`` 一一对应（只保留排版相关项），
默认值完全一致，便于与 PHP 侧做同参数对照。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict

__all__ = ['LayoutOptions']


@dataclass
class LayoutOptions:
    """排版引擎选项。"""

    #: 处理空行、缩进等排版（PHP: changeTextFormat）
    change_text_format: bool = False
    #: 是否给正文加两全角空格缩进；False 表示去除所有缩进和空行（PHP: addIndentation）
    add_indentation: bool = True
    #: 0-保持原样 1-套上 <p>/<title> 标签 2-移除 <p> 标签（PHP: addHtmlTag）
    add_html_tag: int = 0
    #: 规范标点符号（全半角、标点形态、中英文标点间距）（PHP: normalizePunctuations）
    normalize_punctuations: bool = False
    #: 0-保持原样 1-使用规范的多行引号形式 2-连续段落中仅保留开头结尾引号
    consecutive_quotations_type: int = 0
    #: 0-保持原样 1-弯引号 “”‘’ 2-直角引号 「」『』（PHP: quotationType）
    quotation_type: int = 0
    #: 移除中文之间的空格（PHP: rmSpacesBetweenChnChars）
    rm_spaces_between_chn_chars: bool = False
    #: 中文字符和英文字母、数字之间添加空格（PHP: paranoidTextSpacing / Util::pangu）
    paranoid_text_spacing: bool = False
    #: 自动给含 ◎ 的标题分级（PHP: formatHeadings）
    format_headings: bool = False
    #: 从 epub 提取文本后按论坛格式排版（PHP: extractTextFromHtml）
    extract_text_from_html: bool = False
    #: 输入是否为 txt（影响 HTML 实体解码与部分分支；PHP: isTxtFile）
    is_txt_file: bool = True
    #: 收尾换行符（PHP: newLineType）
    new_line_type: str = '\n'
    #: 目标编码（PHP: toEncoding），本实现只处理 UTF-8
    to_encoding: str = 'UTF-8'

    def is_default_encoding(self) -> bool:
        """等价于 PHP ``Option::isDefaultEncoding()``。"""
        return self.to_encoding == 'UTF-8' and self.new_line_type == '\n'

    def copy(self, **kwargs: Any) -> 'LayoutOptions':
        """返回一个修改过部分字段的新选项对象。"""
        return replace(self, **kwargs)

    def to_dict(self) -> Dict[str, Any]:
        """导出为普通字典（便于写对照报告）。"""
        return {
            'change_text_format': self.change_text_format,
            'add_indentation': self.add_indentation,
            'add_html_tag': self.add_html_tag,
            'normalize_punctuations': self.normalize_punctuations,
            'consecutive_quotations_type': self.consecutive_quotations_type,
            'quotation_type': self.quotation_type,
            'rm_spaces_between_chn_chars': self.rm_spaces_between_chn_chars,
            'paranoid_text_spacing': self.paranoid_text_spacing,
            'format_headings': self.format_headings,
            'extract_text_from_html': self.extract_text_from_html,
            'is_txt_file': self.is_txt_file,
            'new_line_type': self.new_line_type,
            'to_encoding': self.to_encoding,
        }
