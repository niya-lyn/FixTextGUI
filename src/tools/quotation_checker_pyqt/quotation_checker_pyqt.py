import configparser
import os
import sys
import regex as re
import ctypes

TARGET_API = os.environ.get("QT_API", "pyqt5").lower()

if TARGET_API == "pyqt5":
    import PyQt5

    dirname = os.path.dirname(PyQt5.__file__)
    plugin_path = os.path.join(dirname, "Qt5", "plugins")
elif TARGET_API == "pyside6":
    import PySide6

    dirname = os.path.dirname(PySide6.__file__)
    plugin_path = os.path.join(dirname, "Qt", "plugins")

os.environ["QT_PLUGIN_PATH"] = plugin_path

from qtpy.QtWidgets import QMessageBox, QApplication, QMainWindow, QShortcut, QPlainTextEdit, QTextEdit
from qtpy.QtCore import QProcess, QByteArray, QTimer, QEvent, Qt, QCoreApplication
from qtpy.QtGui import (
    QIcon,
    QColor,
    QTextCursor,
    QKeySequence,
    QTextDocument,
    QTextCharFormat,
    QSyntaxHighlighter,
    QGuiApplication,
)

import ui


# ==================== 配置常量 ====================
class AppConfig:
    """应用配置常量"""

    SHORTCUTS = {
        "REVERT_QUOTATIONS": "Alt+1",
        "CHANGE_QUOTATION_TYPE": "Alt+2",
        "MERGE_SELECTED_LINES": "Alt+3",
        "TRANS_SINGLE_QUOTATIONS": "Alt+4",
        "INSERT_LEFT_DOUBLE_QUOTE": "F1",
        "INSERT_RIGHT_DOUBLE_QUOTE": "F2",
        "INSERT_LEFT_SINGLE_QUOTE": "F3",
        "INSERT_RIGHT_SINGLE_QUOTE": "F4",
    }

    QUOTE_CONTENT_COLOR = "#C3E88D"
    QUOTE_SYMBOL_COLOR = "cyan"
    QUOTE_SYMBOL_FONT_SIZE = 15
    ERROR_LINE_BG_COLOR = "#555"

    MENU_STYLESHEET = """
        QMenu::item {
            background-color: transparent;
        }
        QMenu::item:selected {
            background-color: #3399ff;
            color: white;
        }
        QMenu::item:disabled {
            color: #888888;
        }
    """


# ==================== 正则表达式管理 ====================
class RegexPatterns:
    """集中管理所有正则表达式"""

    def __init__(self):
        self.filename = re.compile(r"文件名：《(.*)》")
        self.filepath = re.compile(r"文件路径：(.*)")
        self.err_paragraph = re.compile(r"【报错段落】(.*)")
        self.progress_line_num = re.compile(r"当前进度：.*? （(.*?) 行 / .* 行）")
        self.progress = re.compile(r"当前进度：(.*? （.*? 行 / .* 行）)")
        self.err_content = re.compile(r"原文内容如下：\n(.*)======= ↑", re.DOTALL)
        self.err_count = re.compile(r"当前文件含有【(.*?)】处引号错误段落")
        self.remove_filename = re.compile(r"文件名：《.*======= ↑", re.DOTALL)
        self.line_head = re.compile(r"([ \u3000]*)")
        self.double_quote = re.compile(r"[“”]")
        self.single_quote = re.compile(r"[‘’]")


# ==================== 文件信息管理 ====================
class FileInfoManager:
    """管理文件相关信息和状态"""

    def __init__(self):
        self.filename = ""
        self.filepath = ""
        self.progress = ""
        self.err_paragraph = ""  # 脚本返回的报错段落原文
        self.err_line_num = ""  # 这个是整个文档中的行号

        self.err_content = ""  # 截取后的报错段落，直接设置到编辑器中
        self.err_content_line_num = 0  # 这个是截取的错误部分的行号
        self.original_content = ""
        self.edited_content = ""

    def update_from_output(self, content, patterns: RegexPatterns):
        """从输出内容中更新文件信息"""
        if match := patterns.filename.search(content):
            self.filename = match.group(1)

        if match := patterns.filepath.search(content):
            self.filepath = match.group(1).strip()

        if match := patterns.err_paragraph.search(content):
            self.err_paragraph = match.group(1)
        else:
            self.err_paragraph = ""

        if match := patterns.progress_line_num.search(content):
            self.err_line_num = match.group(1)

        if match := patterns.progress.search(content):
            self.progress = match.group(1)

    def extract_err_content(self, content, patterns: RegexPatterns):
        """提取错误内容段落"""
        if match := patterns.err_content.search(content):
            self.err_content = match.group(1)

            # 计算错误行号
            for match in patterns.err_paragraph.finditer(self.err_content):
                self.err_content_line_num = self.err_content[: match.start()].count("\n") + 1

            self.err_content = self.err_content.replace("【报错段落】", "")
            self.original_content = self.err_content

    def has_error_paragraph(self):
        """检查是否存在报错段落"""
        return bool(self.err_paragraph)

    def get_display_filename(self, max_length=20):
        """获取用于显示的文件名"""
        clean_name = self.filename.replace("【EPUB 合并文件】", "")
        if len(clean_name) > max_length:
            return clean_name[:max_length] + "…"

        return clean_name

    def get_progress_text(self):
        """获取进度显示文本"""
        return f"文件名：{self.get_display_filename()}\n进度：{self.progress}"


# ==================== 文本处理工具 ====================
class TextTransformer:
    """文本转换工具类"""

    @staticmethod
    def revert_quotations(text):
        """前后引号互换"""
        return text.translate(str.maketrans("‘’“”", "’‘”“"))

    @staticmethod
    def change_quotation_type(text):
        """单双引号互转"""
        return text.translate(str.maketrans("‘’“”", "“”‘’"))

    @staticmethod
    def trans_single_quotations(text):
        """单引号转〔〕"""
        return text.translate(str.maketrans("‘’", "〔〕"))

    @staticmethod
    def merge_lines(text):
        """合并多行文本"""
        lines = text.split("\u2029")
        if len(lines) <= 1:
            return text

        first_line = lines[0]
        rest_lines = [line.lstrip() for line in lines[1:]]
        return first_line + "".join(rest_lines)


class OutputFormatter:
    """支持 256 色、粗体、下划线、背景色的 ANSI 转 HTML 格式化器，可适应浅色主题"""

    ANSI_ESCAPE_RE = re.compile(r"\x1b\[([\d;]*)m")

    # 基本前景色映射（30-37 / 90-97）
    BASE_COLORS_DARK = {
        30: "#000000", 31: "#cd3131", 32: "#0dbc79", 33: "#e5e510",
        34: "#2472c8", 35: "#bc3fbc", 36: "#11a8cd", 37: "#e5e5e5",
        90: "#666666", 91: "#f14c4c", 92: "#23d18b", 93: "#f5f543",
        94: "#3b8eea", 95: "#d670d6", 96: "#29b8db", 97: "#e5e5e5",
    }
    BASE_COLORS_LIGHT = {
        30: "#1a1a1a", 31: "#b82020", 32: "#0d8040", 33: "#9e7c00",   # 黄色调暗为暗金
        34: "#1a5fb4", 35: "#8b3a8b", 36: "#0d7c9a", 37: "#333333",
        90: "#555555", 91: "#cc3333", 92: "#1e9e5e", 93: "#b89500",   # 亮黄色也调暗
        94: "#3366cc", 95: "#aa55aa", 96: "#1e9eaa", 97: "#555555",
    }

    # 基本背景色映射（40-47 / 100-107）
    BASE_BG_COLORS_DARK = {
        40: "#000000", 41: "#cd3131", 42: "#0dbc79", 43: "#e5e510",
        44: "#2472c8", 45: "#bc3fbc", 46: "#11a8cd", 47: "#e5e5e5",
        100: "#666666", 101: "#f14c4c", 102: "#23d18b", 103: "#f5f543",
        104: "#3b8eea", 105: "#d670d6", 106: "#29b8db", 107: "#e5e5e5",
    }
    BASE_BG_COLORS_LIGHT = {
        40: "#f0f0f0", 41: "#fddcdc", 42: "#dcfce8", 43: "#fef9e0",
        44: "#dde8f9", 45: "#f2ddf2", 46: "#dcf4f8", 47: "#eeeeee",
        100: "#cccccc", 101: "#ffaaaa", 102: "#aaffcc", 103: "#ffffaa",
        104: "#aaccff", 105: "#eebbee", 106: "#aaffee", 107: "#dddddd",
    }

    # 256 色标准色表（索引 0-15），根据主题不同
    STANDARD_COLORS_DARK = [
        "#000000", "#cd0000", "#00cd00", "#cdcd00", "#0000ee", "#cd00cd",
        "#00cdcd", "#e5e5e5", "#7f7f7f", "#ff0000", "#00ff00", "#ffff00",
        "#5c5cff", "#ff00ff", "#00ffff", "#ffffff"
    ]
    STANDARD_COLORS_LIGHT = [
        "#1a1a1a", "#b82020", "#0d8040", "#9e7c00", "#1a5fb4", "#8b3a8b",
        "#0d7c9a", "#333333", "#555555", "#cc3333", "#1e9e5e", "#b89500",
        "#3366cc", "#aa55aa", "#1e9eaa", "#dddddd"
    ]

    def __init__(self, theme="dark"):
        self.theme = theme
        if theme == "light":
            self.base_colors = self.BASE_COLORS_LIGHT
            self.base_bg_colors = self.BASE_BG_COLORS_LIGHT
            self.standard_colors = self.STANDARD_COLORS_LIGHT
        else:
            self.base_colors = self.BASE_COLORS_DARK
            self.base_bg_colors = self.BASE_BG_COLORS_DARK
            self.standard_colors = self.STANDARD_COLORS_DARK

        # 跨行持久化状态
        self.fg_color = None
        self.bg_color = None
        self.bold = False
        self.underline = False
        self.italic = False

    @staticmethod
    def _escape_html(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _color_index_to_rgb(self, index):
        """将 xterm 256 色索引转换为 HTML 颜色字符串"""
        if index < 0 or index > 255:
            return "#ffffff"
        if index < 16:
            return self.standard_colors[index]
        # 16-231：216 色立方体 (6×6×6)
        if index <= 231:
            index -= 16
            r = (index // 36) * 51
            g = ((index % 36) // 6) * 51
            b = (index % 6) * 51
            return f"#{r:02x}{g:02x}{b:02x}"
        # 232-255：24 级灰度
        gray = (index - 232) * 10 + 8
        return f"#{gray:02x}{gray:02x}{gray:02x}"

    def format_html(self, text):
        # 统一换行符，按行处理
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        formatted_lines = []
        for i, line in enumerate(lines):
            escaped = self._escape_html(line)
            preserved = escaped.replace(" ", "&nbsp;")
            html_line = self._convert_line(preserved)
            formatted_lines.append(html_line)
            if i < len(lines) - 1:
                formatted_lines.append("<br>")
        return "".join(formatted_lines)

    def _convert_line(self, line):
        """解析行内 ANSI 转义码并返回带 <span> 的 HTML"""
        parts = []
        last_end = 0

        for match in self.ANSI_ESCAPE_RE.finditer(line):
            plain = line[last_end:match.start()]
            if plain:
                parts.append(self._wrap_style(plain))

            codes_str = match.group(1)
            if codes_str:
                codes = [int(c) for c in codes_str.split(";") if c]
            else:
                codes = [0]

            i = 0
            while i < len(codes):
                c = codes[i]
                if c == 0:
                    self.fg_color = None
                    self.bg_color = None
                    self.bold = False
                    self.underline = False
                    self.italic = False
                elif c == 1:
                    self.bold = True
                elif c == 3:
                    self.italic = True
                elif c == 4:
                    self.underline = True
                elif 30 <= c <= 37 or 90 <= c <= 97:
                    if self.bold and 30 <= c <= 37:
                        self.fg_color = self.base_colors.get(c + 60, self.base_colors[c])
                    else:
                        self.fg_color = self.base_colors.get(c)
                elif 40 <= c <= 47 or 100 <= c <= 107:
                    if self.bold and 40 <= c <= 47:
                        self.bg_color = self.base_bg_colors.get(c + 60, self.base_bg_colors[c])
                    else:
                        self.bg_color = self.base_bg_colors.get(c)
                elif c == 38:
                    if i+2 < len(codes) and codes[i+1] == 5:
                        idx = codes[i+2]
                        self.fg_color = self._color_index_to_rgb(idx)
                        i += 2
                elif c == 48:
                    if i+2 < len(codes) and codes[i+1] == 5:
                        idx = codes[i+2]
                        self.bg_color = self._color_index_to_rgb(idx)
                        i += 2
                i += 1

            last_end = match.end()

        remaining = line[last_end:]
        if remaining:
            parts.append(self._wrap_style(remaining))
        return "".join(parts)

    def _wrap_style(self, text):
        """用当前样式包裹文本"""
        styles = []
        if self.fg_color:
            styles.append(f"color:{self.fg_color}")
        if self.bg_color:
            styles.append(f"background-color:{self.bg_color}")
        if self.bold:
            styles.append("font-weight:bold")
        if self.underline:
            styles.append("text-decoration:underline")
        if self.italic:
            styles.append("font-style:italic")

        if styles:
            return f'<span style="{";".join(styles)};">{text}</span>'
        return text

# ==================== 进程管理器 ====================
class ProcessManager:
    """管理与 PHP 进程的交互"""

    def __init__(self, output_callback, finished_callback, error_callback=None):
        self.process = None
        self.output_callback = output_callback
        self.finished_callback = finished_callback
        self.error_callback = error_callback
        self.last_error_msg = ""

    def start(self, php_program, php_script):
        """启动 PHP 进程"""
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self._handle_output)
        self.process.readyReadStandardError.connect(self._handle_error)
        self.process.finished.connect(self.finished_callback)
        self.process.errorOccurred.connect(self._on_error_occurred)

        self.process.setProgram(php_program)
        self.process.setArguments([php_script, "check-quotation-marks", "from-gui"])
        self.process.start()

    def _handle_output(self):
        """处理进程输出"""
        output_bytes = self.process.readAllStandardOutput().data()
        output = output_bytes.decode("UTF-8")
        self.output_callback(output)

    def _handle_error(self):
        """处理 PHP 的报错信息 (Stderr)"""
        err_bytes = self.process.readAllStandardError().data()
        err_text = err_bytes.decode("UTF-8", errors="replace")
        self.last_error_msg += err_text  # 累积报错内容
        if self.error_callback:
            self.error_callback(err_text)

    def _on_error_occurred(self, error):
        """处理进程无法启动等系统错误"""
        error_msgs = {
            QProcess.FailedToStart: "无法启动 PHP 程序，请检查路径是否正确。",
            QProcess.Crashed: "PHP 进程崩溃了。",
            QProcess.Timedout: "操作超时。",
            QProcess.WriteError: "写入数据失败。",
            QProcess.ReadError: "读取数据失败。",
            QProcess.UnknownError: "发生未知错误。",
        }
        msg = error_msgs.get(error, f"未知错误代码: {error}")
        if self.error_callback:
            self.error_callback(f"系统错误: {msg}")

    def send_command(self, command):
        """发送命令到进程"""
        if self.process:
            self.process.write(QByteArray(command.encode("UTF-8")))

    def is_running(self):
        """检查进程是否正在运行"""
        return self.process and self.process.state() == QProcess.ProcessState.Running

    def terminate(self):
        """终止进程"""
        if not self.is_running():
            return

        # 断开信号连接
        try:
            self.process.readyReadStandardOutput.disconnect()
            self.process.finished.disconnect()
        except TypeError:
            pass

        # 优雅终止
        self.process.terminate()
        if not self.process.waitForFinished(1000):
            self.process.kill()
            self.process.waitForFinished()


# ==================== 文本编辑器增强 ====================
class TextEditEnhancer:
    """增强文本编辑器功能"""

    def __init__(self, text_edit: QPlainTextEdit):
        self.text_edit = text_edit
        self.line_head_pattern = re.compile(r"([ \u3000]*)")

    def insert_custom_newline(self):
        """智能插入换行"""
        cursor = self.text_edit.textCursor()
        cursor.beginEditBlock()

        try:
            current_text = cursor.block().text()
            leading_spaces = self._extract_leading_spaces(cursor)

            if leading_spaces:
                if current_text.endswith("</p>"):
                    cursor.insertText("</p>")
                    new_text = f"\n{leading_spaces}<p>"
                else:
                    new_text = f"\n{leading_spaces}"
            else:
                new_text = "\n"

            cursor.insertText(new_text)
        finally:
            cursor.endEditBlock()

    def _extract_leading_spaces(self, cursor):
        """提取行首空格"""
        block = cursor.block()
        if not block.isValid():
            return ""

        text = block.text()
        if match := self.line_head_pattern.search(text):
            return match.group(1)
        return ""

    def highlight_line(self, line_num):
        """高亮并居中显示指定行"""
        if line_num <= 0:
            return

        # 获取目标行的位置
        temp_doc = QTextDocument()
        temp_doc.setPlainText(self.text_edit.toPlainText())
        block = temp_doc.findBlockByLineNumber(line_num - 1)

        if not block.isValid():
            self.text_edit.setExtraSelections([])
            return

        # 创建高亮选区
        cursor = self.text_edit.textCursor()
        cursor.setPosition(block.position())
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)

        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor(AppConfig.ERROR_LINE_BG_COLOR))
        selection.cursor = cursor

        self.text_edit.setExtraSelections([selection])

        # 延迟滚动到目标位置
        position_cursor = self.text_edit.textCursor()
        position_cursor.setPosition(block.position())
        QTimer.singleShot(0, lambda: self._scroll_to_cursor(position_cursor))

    def _scroll_to_cursor(self, cursor):
        """滚动到指定光标位置"""
        self.text_edit.setTextCursor(cursor)
        self.text_edit.centerCursor()
        self.text_edit.setFocus()


# ==================== 上下文菜单 ====================
class ContextMenu:
    """文本编辑器上下文菜单"""

    def __init__(self, text_edit):
        self.text_edit: QPlainTextEdit = text_edit
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """设置快捷键"""
        shortcuts = [
            ("REVERT_QUOTATIONS", self.revert_quotations),
            ("CHANGE_QUOTATION_TYPE", self.change_quotation_type),
            ("MERGE_SELECTED_LINES", self.merge_selected_lines),
            ("TRANS_SINGLE_QUOTATIONS", self.trans_single_quotations),
            ("INSERT_LEFT_DOUBLE_QUOTE", self.insert_left_double_quote),
            ("INSERT_RIGHT_DOUBLE_QUOTE", self.insert_right_double_quote),
            ("INSERT_LEFT_SINGLE_QUOTE", self.insert_left_single_quote),
            ("INSERT_RIGHT_SINGLE_QUOTE", self.insert_right_single_quote),
        ]

        for key, handler in shortcuts:
            QShortcut(QKeySequence(AppConfig.SHORTCUTS[key]), self.text_edit).activated.connect(handler)

    def show(self, event):
        """显示上下文菜单"""
        menu = self.text_edit.createStandardContextMenu()

        # 定义菜单项
        items = [
            None,
            ("前后引号互换", "REVERT_QUOTATIONS", self.revert_quotations),
            ("单双引号互转", "CHANGE_QUOTATION_TYPE", self.change_quotation_type),
            ("合并选中的行", "MERGE_SELECTED_LINES", self.merge_selected_lines),
            ("单引号转〔〕", "TRANS_SINGLE_QUOTATIONS", self.trans_single_quotations),
            None,
            ("插入左双引号【“】", "INSERT_LEFT_DOUBLE_QUOTE", self.insert_left_double_quote),
            ("插入右双引号【”】", "INSERT_RIGHT_DOUBLE_QUOTE", self.insert_right_double_quote),
            ("插入左单引号【‘】", "INSERT_LEFT_SINGLE_QUOTE", self.insert_left_single_quote),
            ("插入右单引号【’】", "INSERT_RIGHT_SINGLE_QUOTE", self.insert_right_single_quote),
        ]

        # 添加菜单项
        for item in items:
            if item is None:
                menu.addSeparator()
            else:
                title, shortcut_key, handler = item
                action = menu.addAction(title)
                action.setShortcut(QKeySequence(AppConfig.SHORTCUTS[shortcut_key]))
                action.triggered.connect(handler)

        menu.setStyleSheet(AppConfig.MENU_STYLESHEET)
        menu.exec_(event.globalPos())

    def revert_quotations(self):
        """前后引号互换"""
        self._apply_transformation(TextTransformer.revert_quotations)

    def change_quotation_type(self):
        """单双引号互转"""
        self._apply_transformation(TextTransformer.change_quotation_type)

    def merge_selected_lines(self):
        """合并选中的行"""
        cursor = self.text_edit.textCursor()

        # 如果没有选中多行，则选中当前行和下一行
        if not (cursor.hasSelection() and "\u2029" in cursor.selectedText()):
            if not cursor.block().next().isValid():
                return

            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            self.text_edit.setTextCursor(cursor)

        self._apply_transformation(TextTransformer.merge_lines)

    def trans_single_quotations(self):
        """单引号转〔〕"""
        self._apply_transformation(TextTransformer.trans_single_quotations)

    def _apply_transformation(self, transformer):
        """应用文本转换"""
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            return

        start_pos = cursor.selectionStart()
        selected_text = cursor.selectedText()
        new_text = transformer(selected_text)

        if new_text is not None and new_text != selected_text:
            cursor.insertText(new_text)

            # 重新选中替换后的文本
            cursor.setPosition(start_pos)
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.KeepAnchor,
                len(new_text),
            )
            self.text_edit.setTextCursor(cursor)

    def insert_left_double_quote(self):
        self.text_edit.textCursor().insertText("“")

    def insert_right_double_quote(self):
        self.text_edit.textCursor().insertText("”")

    def insert_left_single_quote(self):
        self.text_edit.textCursor().insertText("‘")

    def insert_right_single_quote(self):
        self.text_edit.textCursor().insertText("’")


# ==================== 语法高亮 ====================
class QuoteHighlighter(QSyntaxHighlighter):
    """引号语法高亮器"""

    def __init__(self, document):
        super().__init__(document)
        self.patterns = RegexPatterns()

        # 引号内容格式
        self.quote_content_format = QTextCharFormat()
        self.quote_content_format.setForeground(QColor(AppConfig.QUOTE_CONTENT_COLOR))

        # 引号符号格式
        self.quote_symbol_format = QTextCharFormat()
        self.quote_symbol_format.setForeground(QColor(AppConfig.QUOTE_SYMBOL_COLOR))
        self.quote_symbol_format.setFontPointSize(AppConfig.QUOTE_SYMBOL_FONT_SIZE)

    def highlightBlock(self, text):
        """高亮文本块"""
        self._highlight_quotes(text, self.patterns.double_quote)
        self._highlight_quotes(text, self.patterns.single_quote)

    def _highlight_quotes(self, text, pattern):
        """高亮指定类型的引号"""
        quote_positions = [match.start() for match in pattern.finditer(text)]

        index = 0
        while index < len(quote_positions):
            start_pos = quote_positions[index]
            self.setFormat(start_pos, 1, self.quote_symbol_format)

            next_index = index + 1
            if next_index < len(quote_positions):
                end_pos = quote_positions[next_index]
                # 高亮引号之间的内容
                self.setFormat(start_pos + 1, end_pos - start_pos - 1, self.quote_content_format)
                # 高亮结束引号
                self.setFormat(end_pos, 1, self.quote_symbol_format)
                index = next_index + 1
            else:
                # 没有配对引号，高亮到行尾
                self.setFormat(start_pos + 1, len(text) - start_pos - 1, self.quote_content_format)
                break

        # 处理行首没有开始引号的情况
        if quote_positions and quote_positions[0] > 0 and text[quote_positions[0]] in ("”", "’"):
            self.setFormat(0, quote_positions[0], self.quote_content_format)
            self.setFormat(quote_positions[0], 1, self.quote_symbol_format)


# ==================== 主窗口 ====================
class MainWin(QMainWindow):
    """主窗口类"""

    def __init__(self):
        super().__init__()

        self.php_program = ""
        self.php_script = ""

        # 初始化组件
        self.patterns = RegexPatterns()
        self.file_info = FileInfoManager()
        self.output_formatter = OutputFormatter(theme="light")
        self.process_manager = ProcessManager(
            output_callback=self._on_process_output,
            finished_callback=self._on_process_finished,
            error_callback=self._on_process_stderr,
        )

        # 记录是否收到了退出提示
        self.can_exit_script = False

        self._init_ui()
        self._setup_connections()

    def _init_ui(self):
        """初始化 UI"""
        self.ui = ui.Ui_MainWindow()
        self.ui.setupUi(self)

        # 设置文本编辑器
        self.text_edit = self.ui.plainTextEdit
        self.text_enhancer = TextEditEnhancer(self.text_edit)
        self.context_menu = ContextMenu(self.text_edit)
        self.highlighter = QuoteHighlighter(self.text_edit.document())

        # 设置事件
        self.text_edit.contextMenuEvent = self.context_menu.show
        self.text_edit.installEventFilter(self)

        self.ui.textBrowser.document().setDefaultStyleSheet("p { margin:0; line-height:1.2; }")

        self.show()

    def _setup_connections(self):
        """设置信号连接"""
        # 命令按钮
        command_buttons = [
            (self.ui.send0, "0\n"),
            (self.ui.send2, "2\n"),
            (self.ui.send3, "3\n"),
            (self.ui.sendX, "x\n"),
            (self.ui.sendF, "f\n"),
        ]

        for button, command in command_buttons:
            button.clicked.connect(lambda _, cmd=command: self.process_manager.send_command(cmd))

        # 单独处理发送 1 的按钮
        self.ui.send1.clicked.connect(self._on_send_1_clicked)

        # 功能按钮
        self.ui.saveFile.clicked.connect(self._on_save_file)
        self.ui.getErrCount.clicked.connect(self._on_get_err_count)

        # 快捷键
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._on_save_file)

    def eventFilter(self, source, event):
        """事件过滤器"""
        if event.type() == QEvent.KeyPress and source == self.text_edit:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.text_enhancer.insert_custom_newline()
                return True

        return super().eventFilter(source, event)

    def start_script(self):
        """启动 PHP 脚本"""
        self.process_manager.start(self.php_program, self.php_script)

    def _on_process_output(self, output):
        """处理进程输出"""
        # 检测退出提示
        if "输入 1 退出脚本" in output:
            self.can_exit_script = True
        else:
            self.can_exit_script = False

        self._process_error_location(output)
        self._process_error_count(output)

        # 先移除文件名块，再转换为 HTML
        filtered_output = self.patterns.remove_filename.sub("======= ↑", output)
        formatted_output = self.output_formatter.format_html(filtered_output)
        self.ui.textBrowser.append(formatted_output)

    def _on_send_1_clicked(self):
        """处理发送 1 的指令"""
        if self.can_exit_script:
            # 创建自定义消息框
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("手动修正提示")
            msg_box.setIcon(QMessageBox.Warning)
            msg_box.setText(
                "此错误无法通过快捷键自动修正，需要手动在右边的编辑区中修复。\n修复后，需要按“保存文件”才会跳到下一处报错。"
            )

            # 添加自定义按钮
            _ = msg_box.addButton("我已了解", QMessageBox.ActionRole)
            exit_btn = msg_box.addButton("退出脚本", QMessageBox.DestructiveRole)

            msg_box.exec_()

            if msg_box.clickedButton() == exit_btn:
                self.process_manager.send_command("1\n")
                self.can_exit_script = False  # 发送后重置
            else:
                # 点击“我已了解”，不执行任何操作，关闭弹窗即可
                pass
        else:
            # 如果没有触发退出提示，则按原样发送 1，退出脚本
            self.process_manager.send_command("1\n")

    def _process_error_location(self, content):
        """处理错误定位"""
        self.file_info.extract_err_content(content, self.patterns)
        self.file_info.update_from_output(content, self.patterns)

        if self.file_info.has_error_paragraph():
            # 更新文本编辑器
            self.text_edit.setPlainText(self.file_info.err_content)

            # 更新进度信息
            self.ui.progressInfo.setText(self.file_info.get_progress_text())

            # 高亮错误行
            self.text_enhancer.highlight_line(self.file_info.err_content_line_num)

            # 重新应用语法高亮
            self.highlighter.rehighlight()

    def _on_save_file(self):
        """保存文件"""
        self.file_info.edited_content = self.text_edit.toPlainText()

        if not self.file_info.filename:
            return

        try:
            with open(self.file_info.filepath, "r", encoding="utf-8", newline="\n") as f:
                content = f.read()

            new_content = content.replace(
                self.file_info.original_content.rstrip("\n"), self.file_info.edited_content.rstrip("\n")
            )

            with open(self.file_info.filepath, "w", encoding="utf-8", newline="\n") as f:
                f.write(new_content)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存文件失败: {e}")
            return

        # 自动跳到下一处错误
        self.process_manager.send_command("0\n")
        self.file_info.original_content = self.file_info.edited_content

    def _on_get_err_count(self):
        """获取错误统计"""
        QMessageBox.information(
            self,
            "信息",
            "开始统计当前文件含有的引号错误总数\n如果文件较大，速度会比较慢",
        )
        self.process_manager.send_command("c\n")

    def _process_error_count(self, content):
        """处理错误计数"""
        if match := self.patterns.err_count.search(content):
            QMessageBox.information(
                self,
                "信息",
                f"当前文件含有【{match.group(1)}】处引号错误段落",
            )

    def _on_process_stderr(self, err_msg):
        """当 PHP 向 stderr 打印内容时，显示在文本框里"""
        self.ui.textBrowser.append(f'<pre style="color:red;">{err_msg}</pre>')

    def _on_process_finished(self, exit_code, exit_status):
        """当进程结束时触发"""
        if exit_status == QProcess.CrashExit or exit_code != 0:
            # 弹出报错对话框
            error_detail = self.process_manager.last_error_msg
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Critical)
            msg_box.setWindowTitle("后端脚本执行错误")
            msg_box.setText(f"PHP 脚本异常终止 (退出代码: {exit_code})")
            msg_box.setInformativeText(
                "可能是 PHP 代码语法错误或逻辑崩溃。\n请查看左边窗口最后的红色错误信息，修复后需要重新运行程序。"
            )
            msg_box.setDetailedText(error_detail if error_detail else "请查看左边窗口最后的红色错误信息。")
            msg_box.exec_()
        else:
            # 正常退出
            self.close()

    def closeEvent(self, event):
        """关闭窗口事件"""
        self.process_manager.terminate()
        super().closeEvent(event)


# ==================== 应用初始化 ====================
def setup_environment():
    """设置应用环境"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(current_dir)

    # Windows 任务栏图标设置
    if sys.platform == "win32":
        myappid = "fix_text.quotation_checker"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    return current_dir


def load_app_config(current_dir):
    """加载应用配置"""
    config = configparser.ConfigParser()
    config.read(os.path.join(current_dir, "../env/config.ini"), encoding="utf-8")

    file_dir = config.get("quotation_checker", "file_dir")
    if not os.path.isabs(file_dir):
        file_dir = os.path.abspath(os.path.join(current_dir, file_dir))

    return {
        "file_dir": file_dir,
        "php_program": config.get("quotation_checker", "php_program"),
        "php_script": config.get("quotation_checker", "php_script"),
    }


def main():
    """主函数"""
    if TARGET_API == "pyside6":
        if hasattr(QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
    else:
        if hasattr(Qt, "AA_EnableHighDpiScaling"):
            QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        if hasattr(Qt, "AA_UseHighDpiPixmaps"):
            QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        if hasattr(QCoreApplication, "setHighDpiScaleFactorRoundingPolicy"):
            QCoreApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 设置环境
    current_dir = setup_environment()

    # 加载配置
    config = load_app_config(current_dir)

    # 创建主窗口
    win = MainWin()
    win.setWindowIcon(QIcon("icon.png"))
    win.php_program = config["php_program"]
    win.php_script = config["php_script"]

    # 切换到工作目录并启动
    os.chdir(config["file_dir"])
    win.show()
    win.start_script()

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
