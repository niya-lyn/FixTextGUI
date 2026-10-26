from qtpy.QtCore import QRegularExpression
from qtpy.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QPen, QFont

import json
import logging

from core.constants import PROP_MATCHED


class CustomHighlighter(QSyntaxHighlighter):

    def __init__(self, document):
        super().__init__(document)

        self.rules = []

        # 【坑】这个 QSyntaxHighlighter 是基于行（块）进行高亮
        # 当内容跨行或包含涉及跨行的断言时，无法实现高亮……
        # 据说只能引入复杂的状态机写法才能实现
        #
        # 另一种可能的方式是在加载完搜索结果的文本后，利用 setExtraSelections 进行高亮，可以实现跨行高亮
        # 但是在匹配结果数很多的时候，因为要反复 finditer 和创建 QTextCursor，会导致性能急剧下降
        self.default_regex_options = (
            QRegularExpression.UseUnicodePropertiesOption
            | QRegularExpression.DotMatchesEverythingOption
            | QRegularExpression.MultilineOption
            | QRegularExpression.CaseInsensitiveOption
        )

        self.has_context_lines = False  # 有上下文时才高亮匹配行的字符

        self.matched_line_format = None  # 特殊处理，对匹配行进行高亮

        self.matched_line_highlight_mark = "高亮匹配行字符"

    def add_highlight_rule(self, patterns, options=None, rehighlight=True, **style):
        fmt = self.getFormatFromStyle(style)
        regex_options = options if options is not None else self.default_regex_options
        for pattern in patterns:
            regex = QRegularExpression(pattern, regex_options)
            if not regex.isValid():
                logging.error(f"不支持的正则: '{pattern}'，Error: {regex.errorString()}，无法高亮")
                continue
            self.rules.append((regex, fmt))

        if rehighlight:
            self.rehighlight()

    def getFormatFromStyle(self, style) -> QTextCharFormat:
        fmt = QTextCharFormat()
        for key, value in style.items():
            if key == "color":
                fmt.setForeground(QColor(value))
            elif key == "background":
                fmt.setBackground(QColor(value))
            elif key == "font-weight":
                fmt.setFontWeight(value)
            elif key == "font-size":
                fmt.setFontPointSize(value)
            elif key == "italic" and value:
                fmt.setFontItalic(True)
            elif key == "strikeout" and value:
                fmt.setFontStrikeOut(True)
            elif key == "overline" and value:
                fmt.setFontOverline(True)
            elif key == "underline":
                fmt.setFontUnderline(True)
                if isinstance(value, dict):
                    if "color" in value:
                        fmt.setUnderlineColor(QColor(value["color"]))
                    if "style" in value:
                        underline_style = getattr(QTextCharFormat, value["style"], QTextCharFormat.SingleUnderline)
                        fmt.setUnderlineStyle(underline_style)
                elif value is not True:
                    fmt.setUnderlineColor(QColor(value))
            elif key == "outline":
                if isinstance(value, dict):
                    pen_color = QColor(value.get("color", "black"))
                    pen_width = value.get("width", 1)
                    pen = QPen(pen_color, pen_width)
                    fmt.setTextOutline(pen)
                else:
                    pen = QPen(QColor(value))
                    fmt.setTextOutline(pen)
            elif key == "letter-spacing":
                # 设置为绝对字间距模式，并应用对应的值 (负数就是向左折叠)
                if hasattr(fmt, "setFontLetterSpacingType"):
                    fmt.setFontLetterSpacingType(QFont.AbsoluteSpacing)
                fmt.setFontLetterSpacing(float(value))

        return fmt

    def remove_highlight_rule(self, pattern_to_remove: str, rehighlight=True):
        """
        根据正则表达式字符串移除一个高亮规则
        """
        if not pattern_to_remove:
            return

        self.rules = [(regex, fmt) for regex, fmt in self.rules if regex.pattern() != pattern_to_remove]

        if rehighlight:
            self.rehighlight()

    def highlightBlock(self, text):
        block = self.currentBlock()

        fmt = block.blockFormat()
        is_matched_line = bool(fmt.property(PROP_MATCHED)) if fmt.hasProperty(PROP_MATCHED) else False

        if is_matched_line and self.matched_line_format and self.has_context_lines:
            self.setFormat(0, len(text), self.matched_line_format)

        for pattern, rule_fmt in self.rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), rule_fmt)

    def setup_highlighter(self, custom_highlight_rules):
        rules = json.loads(custom_highlight_rules).get("rules", [])

        for rule in rules:
            pattern_str = rule.get("pattern")
            style_dict = rule.get("style", {})
            mark = rule.get("mark", "")

            if mark == self.matched_line_highlight_mark:
                if self.has_context_lines:
                    self.matched_line_format = self.getFormatFromStyle(style_dict)

                continue

            if pattern_str:
                self.add_highlight_rule([pattern_str], rehighlight=False, **style_dict)

        self.rehighlight()

    def clear_rules(self):
        self.rules = []
        self.rehighlight()

    def set_has_context_lines(self, has_context_lines: bool):
        self.has_context_lines = has_context_lines


class RegexSyntaxHighlighter(CustomHighlighter):  # 继承自 CustomHighlighter

    def __init__(self, document):
        super().__init__(document)
        self.regex_syntax_options = (  # 正则语法高亮通常区分大小写
            QRegularExpression.UseUnicodePropertiesOption | QRegularExpression.DotMatchesEverythingOption
        )

    def setup_regex_syntax_rules(self, regex_highlight_rules: str = ""):
        """
        设置专门用于高亮正则表达式语法的规则
        """
        rules = json.loads(regex_highlight_rules).get("rules", [])

        for rule in rules:
            pattern_str = rule.get("pattern")
            style_dict = rule.get("style", {})
            if pattern_str:
                self.add_highlight_rule(
                    [pattern_str], options=self.regex_syntax_options, rehighlight=False, **style_dict
                )
