import textwrap

from qtpy.QtWidgets import (
    QLabel,
    QDialog,
    QWidget,
    QCheckBox,
    QShortcut,
    QSpinBox,
    QTextEdit,
    QTabWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPlainTextEdit,
    QDialogButtonBox,
    QGroupBox,
    QPushButton,
    QLineEdit,
)
from qtpy.QtGui import QKeySequence, QFont
from qtpy.QtCore import Qt, QEvent

from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from core.search_options import SearchOptions

from config import SHORTCUTS, REGEX_TOOLBAR_GROUPS
import utils.util as util
from widgets.custom.custom_highlighter import RegexSyntaxHighlighter
from core.env_config import env_config


class SearchEditDialog(QDialog):

    # 自定义对话框返回码，用于区分不同的关闭操作
    SearchInFile = QDialog.Accepted + 1  # 对应“搜索文件”
    SearchInEditor = QDialog.Accepted + 2  # 对应“搜索文本框”
    SetConditionOnly = QDialog.Accepted + 3  # 对应“仅改变条件”

    def __init__(
        self,
        search_text: str,
        search_options: "SearchOptions",
        search_condition: str,
        replace_text: str,
        markdown_style: str,
        regex_highlight_rules: str,
        parent: None,
    ):
        super().__init__(parent)

        # 将传入的参数保存为实例属性，方便在辅助方法中使用
        self.search_text = search_text
        self.search_options = search_options
        self.search_condition = search_condition
        self.replace_text = replace_text
        self.markdown_style = markdown_style
        self.regex_highlight_rules = regex_highlight_rules

        # 按逻辑顺序调用初始化方法
        self._init_ui()
        self._connect_signals()
        self._set_initial_state()

    def _init_ui(self):
        """初始化窗口和所有 UI 组件"""
        self.setWindowTitle("编辑搜索内容")
        self.setMinimumSize(600, 800)
        layout = QVBoxLayout(self)

        # 创建并添加核心UI组件
        tab_widget = self._create_tabs()
        hint_label, button_box = self._create_buttons_and_hint()

        layout.addWidget(tab_widget)
        layout.addWidget(hint_label)
        layout.addWidget(button_box)

    def _create_tabs(self) -> QTabWidget:
        """创建并填充 Tab 部件"""
        tab_widget = QTabWidget()

        content_tab = self._create_content_tab()
        intro_tab = self._create_intro_tab()

        tab_widget.addTab(content_tab, "内容")
        tab_widget.addTab(intro_tab, "正则简介")

        # 根据条件动态创建“注释”Tab
        if self.search_condition and "comment" in self.search_condition:
            comment_tab = self._create_comment_tab()
            tab_widget.addTab(comment_tab, "注释")

        return tab_widget

    def _create_content_tab(self) -> QWidget:
        """创建“内容”Tab页面，包含搜索文本框、快捷工具栏和搜索选项"""
        content_tab = QWidget()
        layout = QVBoxLayout(content_tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 1. 搜索文本框区
        # 如果用 QTextEdit，复制粘贴时会带入一些外部样式，除非重写 insertFromMimeData 方法
        self.text_edit = QPlainTextEdit()
        font = self.text_edit.font()
        font.setPointSize(10)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        self.text_edit.setFont(font)

        # 应用正则高亮
        self.regex_syntax_highlighter = RegexSyntaxHighlighter(self.text_edit.document())
        self.regex_syntax_highlighter.setup_regex_syntax_rules(self.regex_highlight_rules)
        self.text_edit.setPlainText(self.search_text)

        layout.addWidget(self.text_edit)

        # 2. 替换内容
        replace_layout = QHBoxLayout()
        replace_layout.setContentsMargins(0, 5, 0, 0)

        replace_label = QLabel("替换为：")
        self.replace_line_edit = QLineEdit()
        self.replace_line_edit.setText(self.replace_text)  # 填入传入的 replace_text

        # 统一输入框字体大小
        line_edit_font = self.replace_line_edit.font()
        line_edit_font.setPointSize(10)
        self.replace_line_edit.setFont(line_edit_font)

        replace_layout.addWidget(replace_label)
        replace_layout.addWidget(self.replace_line_edit)

        layout.addLayout(replace_layout)

        self.last_focused_input = self.text_edit  # 默认焦点为搜索文本框
        self.text_edit.installEventFilter(self)
        self.replace_line_edit.installEventFilter(self)

        # 3. 快捷输入分组
        quick_toolbar_group = self._create_quick_toolbar()
        layout.addWidget(quick_toolbar_group)

        # 34. 搜索选项分组
        self.options_group = QGroupBox("搜索选项")
        # 给 GroupBox 增加一些内边距，防止内容太挤
        options_main_layout = QVBoxLayout(self.options_group)
        options_main_layout.setContentsMargins(15, 20, 15, 10)
        options_main_layout.setSpacing(8)

        # 选项内部采用两列布局
        checkboxes_layout = QHBoxLayout()
        search_options = self.search_options

        # 左侧列
        left_options_layout = QVBoxLayout()
        self.use_regex_checkbox = QCheckBox("启用正则表达式", checked=search_options.use_regex)
        self.enable_match_count_checkbox = QCheckBox("启用实时匹配计数", checked=search_options.enable_match_count)
        self.enable_match_count_checkbox.setToolTip(
            "匹配计数会实时计算当前文本框里所有匹配结果的数量，在正则表达式较复杂，\n"
            "或匹配结果过多时，可以关闭匹配计数，避免影响性能。"
        )
        self.add_to_history_list_checkbox = QCheckBox(
            "添加搜索和替换记录", checked=search_options.add_to_history_list
        )
        self.add_to_history_list_checkbox.setToolTip("关闭此项则不记录搜索和替换的内容。")

        left_options_layout.addWidget(self.use_regex_checkbox)
        left_options_layout.addWidget(self.enable_match_count_checkbox)
        left_options_layout.addWidget(self.add_to_history_list_checkbox)

        # 右侧列
        right_options_layout = QVBoxLayout()
        self.use_dotall_checkbox = QCheckBox("启用单行模式（. 匹配换行符）", checked=search_options.use_dotall)
        self.case_sensitive_checkbox = QCheckBox("区分大小写", checked=search_options.case_sensitive)
        self.show_chapter_title_checkbox = QCheckBox("显示章节标题", checked=search_options.show_chapter_title)
        self.show_chapter_title_checkbox.setToolTip(
            "开启后会略微增加搜索耗时。在【检查章节序号】时会默认开启。\n"
            "可避免将每卷被重置的“第一章”误判为乱序。\n"
            "如对搜索结果有干扰（例如查找【数字串】时），建议关闭。"
        )

        right_options_layout.addWidget(self.use_dotall_checkbox)
        right_options_layout.addWidget(self.case_sensitive_checkbox)
        right_options_layout.addWidget(self.show_chapter_title_checkbox)

        checkboxes_layout.addLayout(left_options_layout)
        checkboxes_layout.addLayout(right_options_layout)
        options_main_layout.addLayout(checkboxes_layout)

        # 4. 最大匹配行数限制 (放在选项组的最下方)
        max_lines_layout = QHBoxLayout()
        max_lines_label_start = QLabel("单个【匹配项】最多包含")
        self.max_match_lines_spinbox = QSpinBox()
        self.max_match_lines_spinbox.setRange(1, 9999)
        self.max_match_lines_spinbox.setValue(search_options.max_match_lines)
        self.max_match_lines_spinbox.setFixedWidth(60)  # 限制一下宽度
        self.max_match_lines_spinbox.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        max_lines_label_end = QLabel("个【匹配行】，超出行数后将被强制分割。")

        max_lines_layout.addWidget(max_lines_label_start)
        max_lines_layout.addWidget(self.max_match_lines_spinbox)
        max_lines_layout.addWidget(max_lines_label_end)
        max_lines_layout.addStretch()

        options_main_layout.addLayout(max_lines_layout)

        layout.addWidget(self.options_group)

        # 设置拉伸：文本框(0)占用所有剩余空间，工具栏(1)和选项组(2)按需收缩
        layout.setStretch(0, 1)
        layout.setStretch(1, 0)
        layout.setStretch(2, 0)
        layout.setStretch(3, 0)

        return content_tab

    def _create_quick_toolbar(self) -> QWidget:
        """创建快捷正则按钮栏"""
        container = QGroupBox("快捷输入")
        container.setObjectName("quick_regex_group")
        container.setStyleSheet("""
            QPushButton {
                padding: 2px 5px;
                border-radius: 3px;
                min-width: 45px;
            }
        """)

        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(5, 10, 5, 5)
        main_layout.setSpacing(4)

        for label_text, btns in REGEX_TOOLBAR_GROUPS:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(4)

            label = QLabel(label_text)
            row_layout.addWidget(label)

            for btn_text, val, tip in btns:
                btn = QPushButton(btn_text)
                btn.setToolTip(tip)
                btn.setAutoDefault(False)  # 避免默认选中后，按 Enter 误触发
                btn.setFocusPolicy(Qt.NoFocus)
                btn.clicked.connect(lambda _, v=val: self._insert_regex_text(v))
                row_layout.addWidget(btn)

            row_layout.addStretch()
            main_layout.addLayout(row_layout)

        return container

    def _insert_regex_text(self, prefix: str):
        """智能插入文本：支持包裹选中内容"""
        cursor = self.text_edit.textCursor()

        # 获取选中的文本 (处理换行符兼容性)
        start_pos = cursor.selectionStart()
        selected_text = cursor.selectedText().replace("\u2029", "\n")

        # 定义前缀与后缀的映射关系
        pairs = {"(": ")", "(?:": ")", "(?=": ")", "(?!": ")", "(?<=": ")", "(?<!": ")", "[": "]", "[^": "]"}

        if prefix in pairs:
            suffix = pairs[prefix]
            # 构造完整字符串
            new_text = f"{prefix}{selected_text}{suffix}"

            # 1. 插入文本（这会自动替换掉当前选中的内容）
            cursor.insertText(new_text)

            # 2. 手动计算光标应该在的位置
            # 目标位置 = 插入点的起始位置 + 前缀的长度 + 原选中文字的长度
            target_position = start_pos + len(prefix) + len(selected_text)

            # 3. 强制设置光标位置
            cursor.setPosition(target_position)

            # 4. 把修改后的光标对象应用回文本框
            self.text_edit.setTextCursor(cursor)
        else:
            # 普通插入（如 \d, \w 等）
            cursor.insertText(prefix)

        # 插入后让文本框获得焦点，确保用户可以直接输入
        self.text_edit.setFocus()

    def _insert_regex_text(self, prefix: str):
        """智能插入文本：支持包裹选中内容，并自动判断插入到搜索框还是替换框"""
        # 获取当前应接收输入的控件（搜索框或替换框）
        target = getattr(self, "last_focused_input", self.text_edit)

        # 定义前缀与后缀的映射关系
        pairs = {"(": ")", "(?:": ")", "(?=": ")", "(?!": ")", "(?<=": ")", "(?<!": ")", "[": "]", "[^": "]"}
        suffix = pairs.get(prefix, "")

        # 针对 QPlainTextEdit (搜索内容框)
        if isinstance(target, QPlainTextEdit):
            cursor = target.textCursor()
            start_pos = cursor.selectionStart()
            selected_text = cursor.selectedText().replace("\u2029", "\n")

            if suffix:
                new_text = f"{prefix}{selected_text}{suffix}"
                # 1. 插入文本（这会自动替换掉当前选中的内容）
                cursor.insertText(new_text)
                # 2. 手动计算光标应该在的位置
                # 目标位置 = 插入点的起始位置 + 前缀的长度 + 原选中文字的长度
                target_position = start_pos + len(prefix) + len(selected_text)
                # 3. 强制设置光标位置
                cursor.setPosition(target_position)
                # 4. 把修改后的光标对象应用回文本框
                target.setTextCursor(cursor)
            else:
                cursor.insertText(prefix)

        # 针对 QLineEdit (替换为框)
        elif isinstance(target, QLineEdit):
            # 获取选中状态及文本
            if target.hasSelectedText():
                start_pos = target.selectionStart()
                selected_text = target.selectedText()
            else:
                start_pos = target.cursorPosition()
                selected_text = ""

            if suffix:
                new_text = f"{prefix}{selected_text}{suffix}"
                target.insert(new_text)
                target_position = start_pos + len(prefix) + len(selected_text)
                target.setCursorPosition(target_position)
            else:
                target.insert(prefix)

        # 插入后让对应的文本框重新获得焦点，保证可以继续打字
        target.setFocus()

    def _create_intro_tab(self) -> QWidget:
        """创建“正则简介”Tab页面"""
        intro_tab = QWidget()
        layout = QVBoxLayout(intro_tab)

        font = QFont("Consolas-Slim, FZYouSongJ GBK, 黑体", 11)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)

        self.intro_text_edit = QTextEdit()
        self.intro_text_edit.setReadOnly(True)
        self.intro_text_edit.setFont(font)
        self.intro_text_edit.document().setDefaultStyleSheet("""
        code, pre {
            font-family: "Consolas-Slim", "FZYouSongJ GBK", "黑体";
            background-color: #FFFFD1;
        }
        """)
        self.intro_regex_highlighter = RegexSyntaxHighlighter(self.intro_text_edit.document())
        self.intro_regex_highlighter.setup_regex_syntax_rules(self.regex_highlight_rules)
        self.intro_text_edit.setHtml(self.get_regex_intro())

        layout.addWidget(self.intro_text_edit)
        return intro_tab

    def _create_comment_tab(self) -> QWidget:
        """创建“注释”Tab页面"""
        comment_tab = QWidget()
        layout = QVBoxLayout(comment_tab)

        font = QFont("Consolas-Slim, FZYouSongJ GBK, 黑体", 11)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)

        self.comment_text_edit = QTextEdit()
        self.comment_text_edit.setReadOnly(True)
        self.comment_text_edit.setFont(font)
        self.comment_text_edit.document().setDefaultStyleSheet("""
        code, pre {
            font-family: "Consolas-Slim", "FZYouSongJ GBK", "黑体";
            background-color: #FFFFD1;
        }
        """)
        self.comment_regex_highlighter = RegexSyntaxHighlighter(self.comment_text_edit.document())
        self.comment_regex_highlighter.setup_regex_syntax_rules(self.regex_highlight_rules)
        comment = textwrap.dedent(self.search_condition["comment"])
        self.comment_text_edit.setHtml(util.render_custom_markdown(comment, self.markdown_style))

        layout.addWidget(self.comment_text_edit)
        return comment_tab

    def _create_buttons_and_hint(self):
        """创建底部的提示标签和按钮栏"""
        hint_label = QLabel("提示：可用 Ctrl+Enter 搜索文件，Ctrl+Shift+Enter 搜索文本框。")
        hint_label.setObjectName("search_hint_label")

        self.button_box = QDialogButtonBox(self)

        self.search_in_file_button = self.button_box.addButton("搜索文件", QDialogButtonBox.ActionRole)
        self.search_in_file_button.setToolTip("每次都会直接【在文件中】进行搜索，生成新的搜索结果。")

        self.search_in_editor_button = self.button_box.addButton("搜索文本框", QDialogButtonBox.ActionRole)
        self.search_in_editor_button.setToolTip(
            "【在文本框中】对现有结果进行二次搜索和替换。\n" + "可使用左边的▲▼导航按钮或对应的快捷键进行跳转。"
        )

        self.set_condition_button = self.button_box.addButton("仅改变条件", QDialogButtonBox.ActionRole)
        self.set_condition_button.setToolTip("仅改变搜索条件，不搜索，不跳转。")

        self.cancel_button = self.button_box.addButton("取消", QDialogButtonBox.RejectRole)

        return hint_label, self.button_box

    def _connect_signals(self):
        # 按钮点击事件
        self.search_in_file_button.clicked.connect(lambda: self.done(self.SearchInFile))
        self.search_in_editor_button.clicked.connect(lambda: self.done(self.SearchInEditor))
        self.set_condition_button.clicked.connect(lambda: self.done(self.SetConditionOnly))
        self.cancel_button.clicked.connect(self.reject)

        # 快捷键
        self.shortcut_search_file = QShortcut(QKeySequence(SHORTCUTS["SEARCH_IN_FILE"]), self)
        self.shortcut_search_file.activated.connect(self.search_in_file_button.click)

        self.shortcut_search_editor = QShortcut(QKeySequence(SHORTCUTS["SEARCH_IN_EDITOR"]), self)
        self.shortcut_search_editor.activated.connect(self.search_in_editor_button.click)

    def _set_initial_state(self):
        """设置对话框打开时的初始焦点和文本选择"""
        self.text_edit.setFocus()
        self.text_edit.selectAll()


    def eventFilter(self, obj, event):
        """全局事件过滤器：用于捕获搜索框和替换框的焦点获取事件"""
        if event.type() == QEvent.FocusIn:
            if obj is self.text_edit or obj is self.replace_line_edit:
                self.last_focused_input = obj

        return super().eventFilter(obj, event)

    def get_search_text(self) -> str:
        """获取用户输入的搜索文本"""
        return self.text_edit.toPlainText()

    def get_replace_text(self) -> str:
        """获取用户输入的替换文本"""
        return self.replace_line_edit.text()

    def get_options(self) -> Tuple:
        """获取用户勾选的搜索选项"""
        return (
            self.use_regex_checkbox.isChecked(),
            self.use_dotall_checkbox.isChecked(),
            self.case_sensitive_checkbox.isChecked(),
            self.enable_match_count_checkbox.isChecked(),
            self.add_to_history_list_checkbox.isChecked(),
            self.show_chapter_title_checkbox.isChecked(),
            self.max_match_lines_spinbox.value(),
        )

    def get_regex_intro(self) -> str:
        file = env_config.regex_intro_md
        with open(file, "r", encoding="utf-8") as f:
            text = f.read()

        return util.render_custom_markdown(text, self.markdown_style)
