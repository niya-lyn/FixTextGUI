from qtpy.QtCore import QObject, Signal
from qtpy.QtWidgets import QApplication, QDialog

from typing import Callable, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from main_window import MainWindow
    from services.style_service import StyleService

from widgets.dialogs.text_editor_style_dialog import TextEditorStyleDialog


class StyleController(QObject):
    themeChanged = Signal(str)

    def __init__(
        self,
        main_window: "MainWindow",
        style_service: "StyleService",
        initial_theme: str,
        check_save_callback: Callable[[], bool],
    ):
        super().__init__()

        self.style_service = style_service
        self.current_theme = initial_theme
        self._check_save_callback = check_save_callback

        self.bottom_button_widget = main_window.bottom_button_widget
        self.context_lines_widget = main_window.context_lines_widget
        self.file_widget = main_window.file_widget
        self.replace_widget = main_window.replace_widget
        self.search_widget = main_window.search_widget
        self.text_editor_widget = main_window.text_editor_widget

        # 缓存数据供其他模块读取
        self.markdown_style = ""
        self.editor_highlight_rules = ""
        self.regex_highlight_rules = ""
        self.function_colors = {}

        self.apply_theme(self.current_theme)

    def get_function_color(self, color_key: str) -> Tuple[str, str]:
        return self.function_colors.get(color_key, ("yellow", "black"))

    def get_highlight_rules(self, file_name: str) -> str:
        if file_name == "editor_highlight_rules.json":
            return self.editor_highlight_rules
        elif file_name == "regex_highlight_rules.json":
            return self.regex_highlight_rules
        elif file_name == "markdown.qss":
            return self.markdown_style

        return ""

    def get_current_theme(self) -> str:
        return self.current_theme

    def toggle_theme(self):
        if self._check_save_callback():
            return

        new_theme = "dark" if self.current_theme == "light" else "light"
        self.apply_theme(new_theme)

    def reload_theme(self):
        self.apply_theme(self.current_theme)

    def apply_theme(self, theme_name: str):
        self.current_theme = theme_name

        # 1. 应用 QApplication 全局样式
        common_qss = self.style_service.get_qss(theme_name, "common.qss")
        main_qss = self.style_service.get_qss(theme_name, "main.qss")
        app = QApplication.instance()
        if app:
            app.setStyleSheet(common_qss + main_qss)

        # 2. 缓存给核心业务用的数据
        self.markdown_style = self.style_service.get_qss(theme_name, "markdown.qss")
        self.editor_highlight_rules = self.style_service.get_highlight_rules(theme_name, "editor_highlight_rules.json")
        self.regex_highlight_rules = self.style_service.get_highlight_rules(theme_name, "regex_highlight_rules.json")
        self.function_colors = self.style_service.get_function_colors(theme_name)

        # 3. 设置 Widget 样式
        self._update_widget_theme(self.bottom_button_widget, theme_name, "bottom_button_widget.qss", common_qss)
        self._update_widget_theme(self.context_lines_widget, theme_name, "context_lines_widget.qss", common_qss)
        self._update_widget_theme(self.file_widget, theme_name, "file_widget.qss", common_qss)
        self._update_widget_theme(self.replace_widget, theme_name, "replace_widget.qss", common_qss)
        self._update_widget_theme(self.search_widget, theme_name, "search_widget.qss", common_qss)

        # 文本编辑器比较特殊，它需要具体的颜色字典去设置高亮
        text_qss = self.style_service.get_qss(theme_name, "text_editor_widget.qss")
        self.text_editor_widget.update_theme_style(common_qss + text_qss, theme_name, self.function_colors)

        # 4. 广播主题更改（供外部业务模块使用，如保存历史记录）
        self.themeChanged.emit(self.current_theme)

    def _update_widget_theme(self, widget, theme_name: str, qss_filename: str, common_qss: str):
        widget_qss = self.style_service.get_qss(theme_name, qss_filename)
        # 调用 Widget 统一暴露的接口
        widget.update_theme_style(common_qss + widget_qss, theme_name)

    def update_text_editor_style(self):
        # 1. 获取 QSS 文件路径
        text_editor_qss_path = self.style_service.get_qss_path(self.current_theme, "text_editor_widget.qss")

        # 2. 读取当前 QSS 内容并解析 CustomPlainTextEdit 的属性
        qss_content = self.style_service.get_qss(self.current_theme, "text_editor_widget.qss")
        current_props = self.style_service.parse_qss_selector_props(qss_content, "CustomPlainTextEdit")

        # 如果解析为空，则使用默认属性
        if not current_props:
            current_props = {
                "font-family": '"Consolas-Slim", "FZYouSongJ GBK", "MiSans L3", "黑体"',
                "font-size": "12pt",
                "color": "#bfc7d5",
                "background-color": "#202331",
            }

        # 3. 弹出样式设置对话框
        dialog = TextEditorStyleDialog(self.text_editor_widget, initial_props=current_props)
        if dialog.exec_() == QDialog.Accepted:
            new_props = dialog.get_selected_props()
            if new_props:
                success = self.style_service.update_qss_file(text_editor_qss_path, "CustomPlainTextEdit", new_props)
                if success:
                    self.reload_theme()
                else:
                    pass
