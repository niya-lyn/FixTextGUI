import re
import sys
import ctypes
import os
import configparser

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

from qtpy import uic, QtCore
from qtpy.QtCore import QRegularExpression, Qt, QCoreApplication
from qtpy.QtWidgets import QApplication, QWidget
from qtpy.QtGui import QIcon, QSyntaxHighlighter, QTextCharFormat, QColor, QGuiApplication

HIGHLIGHT_RULES = [
    (r"\".*?\"", {"color": "#C3E88D"}),
    (r"'.*?'[ ]+=>", {"color": "#75AAFF"}),
    (r"// .*", {"color": "#798A9F"}),
    (r"// 当前所处的 Map：.*|// ====+", {"color": "cyan"}),
    (r"【第 .*? 行】", {"color": "#C27DB4"}),
    (r"【第 .*? 行.+】", {"color": "#07cb21"}),
]

MAP_FILES = [
    "1.自定义词库.php",
    "2.繁转简词库.php",
    "3.txtFormat 词库.php",
    "4.的地得词库.php",
    "7.生僻字词库.php",
]

MAPS = [
    "normalMap",
    "extraMap",
    "strictMap",
    "accurateDddMap",
    "oldStyleMap",
    "shengpiziMap",
    "t2sRadicalMap",
]


class CustomHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        self.regex_options = (
            QRegularExpression.UseUnicodePropertiesOption
            | QRegularExpression.DotMatchesEverythingOption
            | QRegularExpression.CaseInsensitiveOption
        )

    def add_highlight_rule(self, patterns, **style):
        fmt = QTextCharFormat()
        for key, value in style.items():
            if key == "color":
                fmt.setForeground(QColor(value))
            elif key == "font-weight":
                fmt.setFontWeight(value)
            elif key == "font-size":
                fmt.setFontPointSize(value)
            elif key == "background":
                fmt.setBackground(QColor(value))
            elif key == "italic" and value:
                fmt.setFontItalic(True)
        for pattern in patterns:
            regex = QRegularExpression(pattern, self.regex_options)
            self.rules.append((regex, fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)

    def setup_highlighter(self):
        rules = HIGHLIGHT_RULES
        for pattern, style in rules:
            self.add_highlight_rule([pattern], **style)

    def clear_rules(self):
        self.rules = []


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        current_dir = os.path.dirname(os.path.abspath(__file__))

        if sys.platform == "win32":
            myappid = "fix_text.words_operations"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

        # 设置 icon
        os.chdir(current_dir)
        self.setWindowIcon(QIcon("icon.png"))

        config = configparser.ConfigParser()
        config.read("../env/config.ini", encoding="utf-8")
        self.php_program = config.get("words_operations", "php_program")

        # 设置 php 脚本所在目录
        self.scripts_dir = os.path.abspath(os.path.join(current_dir, "../../scripts"))

        # 加载 .ui 文件
        script_dir = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(script_dir, "ui.ui")
        if not os.path.exists(ui_path):
            # 备选：从当前工作目录查找
            ui_path = os.path.join(os.getcwd(), "ui.ui")
            if not os.path.exists(ui_path):
                raise FileNotFoundError(f"找不到 ui.ui，尝试过: {script_dir} 和 {os.getcwd()}")

        uic.loadUi(ui_path, self)

        # 连接按钮信号和槽
        self.duplicate_check_button.clicked.connect(self.duplicate_check)
        self.search_button.clicked.connect(self.search)
        self.delete_button.clicked.connect(self.delete)
        self.integrate_button.clicked.connect(self.integrate)
        self.flatten_button.clicked.connect(self.flatten)
        self.write_button.clicked.connect(self.write)
        self.clear_line_num_button.clicked.connect(self.clear_line_num)

        self.process = QtCore.QProcess(self)
        self.process.finished.connect(self.process_finished)

        # 初始化词库选择框
        self.lexicon_combobox = self.findChild(QtCore.QObject, "lexicon_combobox")
        lexicon_files = MAP_FILES
        self.lexicon_combobox.addItems(lexicon_files)

        # 初始化 Map 选择框
        self.map_combobox = self.findChild(QtCore.QObject, "map_combobox")
        map_options = MAPS
        self.map_combobox.addItems(map_options)

        self.highlighter = CustomHighlighter(self.result_text.document())
        self._setup_result_text_context_menu()

    def _setup_result_text_context_menu(self):
        self.result_text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.result_text.customContextMenuRequested.connect(self.on_result_text_context_menu)

    def on_result_text_context_menu(self, event):
        menu = self.result_text.createStandardContextMenu()
        # 兼容深色背景的样式
        menu.setStyleSheet("""
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
        """)
        menu.exec_(self.result_text.viewport().mapToGlobal(event))

    def run_php_script(self, script_name, *args):
        """
        运行指定的 php 脚本，并传递必要的参数。

        :param script_name: 要运行的 php 脚本的文件名
        :param args: 从此参数传进来的是从 argv[2] 开始算，argv[1] 固定为文本输入框内容，会写入临时文件
        """
        self.result_text.setPlainText(f"正在执行脚本：【{script_name}】")

        input_text = self.input_text.toPlainText()

        # 固定的临时文件路径
        tmp_file_path = os.path.abspath(os.path.join(self.scripts_dir, "tmp_argv.txt"))

        # 写入输入文本到临时文件
        with open(tmp_file_path, "w", encoding="utf-8", newline="\n") as temp_file:
            temp_file.write(input_text)

        script_path = os.path.join(self.scripts_dir, script_name)
        # 构建参数列表，先添加脚本路径，再添加临时文件路径，最后添加额外参数
        arguments = [script_path, tmp_file_path] + list(args)

        try:
            self.process.start(self.php_program, arguments)
            self.process.waitForFinished(-1)
        finally:
            # 删除临时文件
            if os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

        # 读取 tmp_output.txt 文件内容
        tmp_output_file_path = os.path.abspath(os.path.join(self.scripts_dir, "tmp_output.txt"))
        try:
            with open(tmp_output_file_path, "r", encoding="utf-8") as file:
                output = file.read()
            # 删除 tmp_output.txt 文件
            os.remove(tmp_output_file_path)

            self.highlighter.clear_rules()
            self.highlighter.setup_highlighter()
            self.result_text.setPlainText(output)
        except FileNotFoundError:
            self.result_text.setPlainText("未找到 tmp_output.txt 文件")
        except Exception as e:
            self.result_text.setPlainText(f"读取 tmp_output.txt 文件时出错：{e}")

    def duplicate_check(self):
        selected_map = self.map_combobox.currentText()
        self.run_php_script("词条查重.php", selected_map)

    def search(self):
        selected_lexicon = self.lexicon_combobox.currentText()
        self.run_php_script("词条检索.php", selected_lexicon)

    def delete(self):
        selected_lexicon = self.lexicon_combobox.currentText()
        self.run_php_script("词条删除.php", selected_lexicon)

    def integrate(self):
        selected_map = self.map_combobox.currentText()
        self.run_php_script("词条合并.php", selected_map)

    def flatten(self):
        self.run_php_script("词条展开.php")

    def write(self):
        self.run_php_script("词条写入.php")

    def clear_line_num(self):
        pattern = r"\s+// 【第.*?行.*?】|\s+// 原已有词条"

        text = self.input_text.toPlainText()
        new_text = re.sub(pattern, "", text)
        self.input_text.setPlainText(new_text)

        text = self.result_text.toPlainText()
        new_text = re.sub(pattern, "", text)
        self.result_text.setPlainText(new_text)

    def process_finished(self, exitCode, exitStatus):
        if exitCode != 0:
            error = self.process.readAllStandardError().data().decode("utf-8")
            self.result_text.setPlainText(f"执行脚本时出错：{error}")


def main():
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
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
