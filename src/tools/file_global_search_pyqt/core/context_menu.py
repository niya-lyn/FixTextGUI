import regex
from functools import partial
import html
import logging

from qtpy.QtGui import QTextCursor, QKeySequence
from qtpy.QtWidgets import (
    QShortcut,
    QMessageBox,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QDialog,
    QDialogButtonBox,
)

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from controllers.match_extender import MatchExtender
    from widgets.file_widget import FileWidget
    from widgets.text_editor_widget import TextEditorWidget

import utils.util as util
from utils.text_case_converter import TextCaseConverter
from utils.chapter_num_checker import ChapterNumChecker
from config import SHORTCUTS
from core.env_config import env_config
from utils.patch_formatter import PatchFormatter
from widgets.dialogs.renumber_options_dialog import RenumberOptionsDialog


class ContextMenu:

    def __init__(
        self, text_editor_widget: "TextEditorWidget", file_widget: "FileWidget", match_extender: "MatchExtender"
    ):
        self.text_editor_widget = text_editor_widget
        self.file_widget = file_widget
        self.match_extender = match_extender

        self.text_edit = self.text_editor_widget.get_text_edit()

        self._fixed_rules_history: List[str] = []

        shortcut_mappings = {
            "ADD_QUOTE_1": partial(self.add_quote_in_selection, left_quote="【", right_quote="】"),
            "ADD_QUOTE_2": partial(self.add_quote_in_selection, left_quote="〖", right_quote="〗"),
            "ADD_QUOTE_3": partial(self.add_quote_in_selection, left_quote="〔", right_quote="〕"),
            "ADD_QUOTE_4": partial(self.add_quote_in_expansion, left_quote="【", right_quote="】"),
            "ADD_QUOTE_5": partial(self.add_quote_in_expansion, left_quote="〖", right_quote="〗"),
            "ADD_QUOTE_6": partial(self.add_quote_in_expansion, left_quote="〔", right_quote="〕"),
            "EDIT_QUOTE_1": partial(self.edit_quote, type=1),
            "EDIT_QUOTE_2": partial(self.edit_quote, type=2),
            "EDIT_QUOTE_3": partial(self.edit_quote, type=3),
            "CHANGE_CASE_1": partial(self.change_case_in_text, mode=1),
            "CHANGE_CASE_2": partial(self.change_case_in_text, mode=2),
            "CHANGE_CASE_3": partial(self.change_case_in_text, mode=3),
            "CHANGE_CASE_4": partial(self.change_case_in_text, mode=4),
            "CHANGE_CASE_5": partial(self.change_case_in_text, mode=5),
            "ARABIC_TO_CHN_NUM": self.process_arabic_to_chn_num,
            "CHN_TO_ARABIC_NUM": self.process_chn_to_arabic_num,
            "TRANS_QUOTATIONS_1": self.trans_quotations_1,
            "MERGE_SELECTED_LINES": self.merge_selected_lines,
            "CONVERT_BY_FIXED_RULES": self.convert_by_fixed_rules,
            "STRIP_HTML_TAGS": self.strip_html_tags,
            "EXTEND_CURRENT_MATCHES": self.extend_current_matches,
            "REVERT_DIFF": self.revert_diff,
            "REVERT_DIFF_2": self.revert_diff,
            "SYNC_DIFF": self.sync_diff,
        }

        for shortcut_key, handler in shortcut_mappings.items():
            QShortcut(QKeySequence(SHORTCUTS[shortcut_key]), self.text_edit).activated.connect(handler)

    def show_custom_context_menu(self, event):
        # 1. 定义整个菜单的结构
        menu_structure = [
            None,
            (
                "添加标记（选中的内容，【】）",
                "ADD_QUOTE_1",
                partial(self.add_quote_in_selection, left_quote="【", right_quote="】"),
            ),
            (
                "添加标记（选中的内容，〖〗）",
                "ADD_QUOTE_2",
                partial(self.add_quote_in_selection, left_quote="〖", right_quote="〗"),
            ),
            (
                "添加标记（选中的内容，〔〕）",
                "ADD_QUOTE_3",
                partial(self.add_quote_in_selection, left_quote="〔", right_quote="〕"),
            ),
            None,
            (
                "添加标记（扩展选中行，【】）",
                "ADD_QUOTE_4",
                partial(self.add_quote_in_expansion, left_quote="【", right_quote="】"),
            ),
            (
                "添加标记（扩展选中行，〖〗）",
                "ADD_QUOTE_5",
                partial(self.add_quote_in_expansion, left_quote="〖", right_quote="〗"),
            ),
            (
                "添加标记（扩展选中行，〔〕）",
                "ADD_QUOTE_6",
                partial(self.add_quote_in_expansion, left_quote="〔", right_quote="〕"),
            ),
            None,
            ("整理跨行引号（仅保留首尾引号）", "EDIT_QUOTE_1", partial(self.edit_quote, type=1)),
            ("整理跨行引号（中间行都只加前引号）", "EDIT_QUOTE_2", partial(self.edit_quote, type=2)),
            ("整理跨行引号（每一行都加前后引号）", "EDIT_QUOTE_3", partial(self.edit_quote, type=3)),
            None,
            # 子菜单定义: ("菜单标题", [菜单项列表])
            (
                "转换英文大小写",
                [
                    ("首字母大写（整句）", "CHANGE_CASE_1", partial(self.change_case_in_text, mode=1)),
                    ("首字母大写（单词）", "CHANGE_CASE_5", partial(self.change_case_in_text, mode=5)),
                    ("全转为小写", "CHANGE_CASE_2", partial(self.change_case_in_text, mode=2)),
                    ("全转为大写", "CHANGE_CASE_3", partial(self.change_case_in_text, mode=3)),
                    ("只转换固定词组", "CHANGE_CASE_4", partial(self.change_case_in_text, mode=4)),
                ],
            ),
            (
                "转换数字",
                [
                    ("阿拉伯数字转中文", "ARABIC_TO_CHN_NUM", self.process_arabic_to_chn_num),
                    ("中文转阿拉伯数字", "CHN_TO_ARABIC_NUM", self.process_chn_to_arabic_num),
                ],
            ),
            ("单引号转〔〕", "TRANS_QUOTATIONS_1", self.trans_quotations_1),
            ("固定批注规则转换", "CONVERT_BY_FIXED_RULES", self.convert_by_fixed_rules),
            None,
            ("移除 HTML 和差异项标签", "STRIP_HTML_TAGS", self.strip_html_tags),
            ("还原选区中的差异项变更", "REVERT_DIFF", self.revert_diff),
            ("将差异项同步到 booksBak", "SYNC_DIFF", self.sync_diff),
            None,
            ("合并选中的行", "MERGE_SELECTED_LINES", self.merge_selected_lines),
            ("扩展/预览匹配项的上下文", "EXTEND_CURRENT_MATCHES", self.extend_current_matches),
            None,
            (
                "重排章节号",
                [
                    # 子菜单项可以不带快捷键: (标题, 处理器)
                    ("阿拉伯数字，常规写法，如：1-999", partial(self.renumber_chapters, type=0)),
                    ("阿拉伯数字，高位补 0，如：001-999", partial(self.renumber_chapters, type=1)),
                    None,
                    ("中文数字，常规写法，如：一至九十", partial(self.renumber_chapters, type=2)),
                    ("中文数字，逐位转换，如：一九〇〇", partial(self.renumber_chapters, type=3)),
                    ("中文数字，逐位转换，三位以下原样", partial(self.renumber_chapters, type=4)),
                    ("中文数字，逐位转换，高位补〇", partial(self.renumber_chapters, type=5)),
                    ("中文数字，转为大写，如：壹贰叁肆", partial(self.renumber_chapters, type=6)),
                ],
            ),
        ]

        # 2. 创建并构建菜单
        menu = QMenu(self.text_edit)

        # === 手动构建基础功能区（撤销/重做/剪切/复制/粘贴/全选） ===

        # --- 撤销 ---
        undo_action = menu.addAction("撤销")
        undo_action.setShortcut(QKeySequence.Undo)
        undo_action.triggered.connect(self.text_edit.undo)
        # 根据编辑器状态设置是否可用（变灰）
        undo_action.setEnabled(self.text_edit.document().isUndoAvailable())

        # --- 重做 ---
        redo_action = menu.addAction("重做")
        redo_action.setShortcut(QKeySequence.Redo)
        redo_action.triggered.connect(self.text_edit.redo)
        redo_action.setEnabled(self.text_edit.document().isRedoAvailable())

        menu.addSeparator()

        # --- 剪切 ---
        cut_action = menu.addAction("剪切")
        cut_action.setShortcut(QKeySequence.Cut)
        cut_action.triggered.connect(self.text_edit.cut)
        cut_action.setEnabled(self.text_edit.textCursor().hasSelection())

        # --- 复制 ---
        copy_action = menu.addAction("复制")
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.triggered.connect(self.text_edit.copy)
        copy_action.setEnabled(self.text_edit.textCursor().hasSelection())

        copy_raw_action = menu.addAction("复制（保留差异项标签）")
        copy_raw_action.setShortcut("Ctrl+Shift+C")
        copy_raw_action.triggered.connect(self.text_edit.copy_raw)
        copy_raw_action.setEnabled(self.text_edit.textCursor().hasSelection())

        # --- 粘贴 ---
        paste_action = menu.addAction("粘贴")
        paste_action.setShortcut(QKeySequence.Paste)
        paste_action.triggered.connect(self.text_edit.paste)
        # 检查剪贴板是否有文本
        paste_action.setEnabled(self.text_edit.canPaste())

        # --- 删除 (可选) ---
        # QPlainTextEdit 没有直接的 delete 槽，通常用 cut 代替或忽略
        if self.text_edit.textCursor().hasSelection():
            del_action = menu.addAction("删除")
            del_action.setShortcut(QKeySequence.Delete)
            del_action.triggered.connect(self.text_edit.cut)

        # --- 全选 ---
        select_all_action = menu.addAction("全选")
        select_all_action.setShortcut(QKeySequence.SelectAll)
        select_all_action.triggered.connect(self.text_edit.selectAll)
        select_all_action.setEnabled(bool(self.text_edit.toPlainText()))

        self._create_menu_from_structure(menu, menu_structure)

        # 3. 显示菜单
        menu.exec_(self.text_edit.viewport().mapToGlobal(event.pos()))

    def _create_menu_from_structure(self, parent_menu, menu_structure):
        """
        一个通用的辅助函数，根据定义好的数据结构递归创建菜单
        """
        for item in menu_structure:
            if item is None:  # None 为分隔符
                parent_menu.addSeparator()
                continue

            # 子菜单的定义：(子菜单标题, [子菜单项...])
            if (
                isinstance(item, (list, tuple))
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], list)
            ):
                submenu_title, submenu_items = item
                submenu = parent_menu.addMenu(submenu_title)
                # 递归调用来创建子菜单
                self._create_menu_from_structure(submenu, submenu_items)
                continue

            # 普通菜单项的定义
            # 兼容 (title, handler) 和 (title, shortcut_key, handler) 两种格式
            shortcut_key = None
            if len(item) == 3:
                title, shortcut_key, handler = item
            elif len(item) == 2:
                title, handler = item
            else:
                continue  # 跳过格式不正确的数据

            action = parent_menu.addAction(title)
            if shortcut_key and shortcut_key in SHORTCUTS:
                action.setShortcut(QKeySequence(SHORTCUTS[shortcut_key]))

            # 使用 partial 确保 handler 是一个无参数的可调用对象
            if isinstance(handler, partial):
                action.triggered.connect(handler)
            else:
                # 对于普通方法和 lambda，直接连接
                action.triggered.connect(handler)

    def edit_quote(self, type: int):
        """
        type 为 1 时，仅保留首尾引号
        type 为 2 时，中间行都只加前引号
        type 为 3 时，每一行都加前后引号
        """
        cursor, selected_text = self._expand_selected_line_text()
        if not selected_text:
            QMessageBox.warning(self.file_widget, "无选中内容", "请先选中要处理的内容")
            return

        lines = selected_text.splitlines()
        if not lines:
            QMessageBox.warning(self.file_widget, "无有效行", "选中文本不包含有效行")
            return

        # --- 1. 引号检测 ---
        quote_pairs = {
            "“": "”",
            "‘": "’",
            "[": "]",
            "【": "】",
            "〖": "〗",
            "「": "」",
            "『": "』",
            "〔": "〕",
            "［": "］",
            "（": "）",
            "(": ")",
        }
        escaped_quote_keys = regex.escape("".join(quote_pairs.keys()))
        reverse_quote_pairs = {v: k for k, v in quote_pairs.items() if k != v}

        open_quote = "“"
        close_quote = "”"

        # 用更复杂的正则表达式来处理前缀、空格和 HTML 标签
        # 匹配: [前缀]? [空格]* [前导标签]* (后面内容)
        # 注意：这个HTML标签匹配很简单，不能处理复杂嵌套或注释等
        # (?:<[^>]+>\s*)* 匹配零或多个 HTML 标签（如 <p>, <span class="a">）及其后的可选空白
        line_parser_for_quote_detection = regex.compile(
            r"^(\[(?:行号|匹配)：\d+\])?"  # Group 1: Optional prefix
            r"([ 　]*)"  # Group 2: Leading space
            r"((?:<[^>]+>\s*)*)"  # Group 3: Leading HTML tags
            rf"(.*?(?:：|——)(?=[{escaped_quote_keys}]))?"  # Group 4: 可能出现的带冒号的部分
            r"(.*)"  # Group 5: Rest of the line
        )

        # 从第一个有内容的行检测引号（跳过前缀、空格、前导标签）
        for line in lines:
            match = line_parser_for_quote_detection.match(line)
            if match:
                rest_of_line = match.group(5)  # 获取标签后的内容

                # 去除 rest_of_line 开头的空白
                content_to_check = rest_of_line.lstrip(" 　\t\n\r\f")  # 处理各种空白

                if content_to_check:  # 确保去除空白后还有内容
                    first_char = content_to_check[0]  # 现在检查的是第一个非空白字符
                    # --- 引号判断逻辑 ---
                    if first_char in quote_pairs:
                        open_quote = first_char
                        close_quote = quote_pairs[first_char]
                        break  # 找到后立即停止
                    elif first_char in reverse_quote_pairs:
                        close_quote = first_char
                        open_quote = reverse_quote_pairs[first_char]
                        break
                    elif first_char == '"' or first_char == "'":
                        open_quote = close_quote = first_char
                        break
                    # 如果第一个非空字符不是已知引号，则停止检测，使用默认值
                    else:
                        break

            # 如果行不匹配正则但 strip 后有内容，也应该停止检测，用默认值
            elif line.strip():
                break

        # --- 2. 处理每一行---
        processed_lines_data = []

        # 正则表达式分解行结构: [前缀]? [空格]* [前导标签]* [核心内容] [结尾标签]*
        # 这个正则需要更精确地捕获各部分
        line_structure_pattern = regex.compile(
            r"^(\[(?:行号|匹配)：\d+\])?"  # Group 1: Optional prefix
            r"([ 　]*)"  # Group 2: Leading space
            r"((?:<[^>]+>\s*)*)"  # Group 3: Leading HTML tags (non-greedy if needed, but * should be ok here)
            rf"(.*?(?:：|——)(?=[{escaped_quote_keys}]))?"  # Group 4: 可能出现的带冒号的部分
            r"(.*?)"  # Group 5: The content part (non-greedy)
            r"((?:\s*</[^>]+>)*)$"  # Group 6: Trailing HTML tags (greedy, anchored to end)
        )

        for line in lines:
            match = line_structure_pattern.match(line)
            if match:
                line_prefix = match.group(1) or ""
                leading_space = match.group(2) or ""
                leading_tags = match.group(3) or ""
                colon = match.group(4) or ""
                inner_content_with_quotes = match.group(5) or ""
                trailing_tags = match.group(6) or ""

                # 清理 inner_content_with_quotes: 移除检测到的首尾引号
                core_text = inner_content_with_quotes
                # 先移除尾部关引号
                if len(core_text) >= len(close_quote) and core_text.endswith(close_quote):
                    core_text = core_text[: -len(close_quote)]
                # 再移除头部开引号
                if len(core_text) >= len(open_quote) and core_text.startswith(open_quote):
                    core_text = core_text[len(open_quote) :]

                # 只有当核心文本不为空时，才保留该行数据
                # 这里假设只要原始行匹配结构就处理，即使 core_text 为空
                # 如果需要过滤 core_text 为空的行，则加上 if core_text:
                processed_lines_data.append(
                    {
                        "prefix": line_prefix,
                        "lead": leading_space,
                        "ltags": leading_tags,  # 前导标签
                        "colon": colon,  # 可能出现的带冒号的部分
                        "core": core_text,  # 核心文本 (无引号)
                        "ttags": trailing_tags,  # 结尾标签
                    }
                )
            elif line.strip():  # 如果行不匹配结构但有内容
                # 方案 A: 作为普通文本处理 (无标签)
                # processed_lines_data.append({'prefix':'', 'lead':'', 'ltags':'', 'core': line, 'ttags':''})
                # 方案 B: 忽略这些行 (如果它们不应该被处理)
                pass  # 当前选择忽略格式不符的非空行

        if not processed_lines_data:
            QMessageBox.warning(self.file_widget, "无有效内容", "选中内容清理或解析后无有效结构化文本")
            return

        # --- 3. 应用格式化---
        new_lines = []
        num_lines = len(processed_lines_data)
        close_p_tag = "</p>"  # 定义目标标签，便于维护

        for i, line_data in enumerate(processed_lines_data):
            prefix = line_data["prefix"]
            lead = line_data["lead"]
            ltags = line_data["ltags"]
            colon = line_data["colon"]
            core = line_data["core"]
            ttags = line_data["ttags"]
            formatted_line = ""

            # `original_core`用于检测原始文本中是否已存在后引号
            def format_with_close_quote(current_core, original_core, current_ttags):
                # 新增判断：如果核心文本中已经包含了当前对应的后引号，直接返回，不再补全
                if close_quote in original_core:
                    return f"{current_core}{current_ttags}"

                if close_p_tag in current_ttags:
                    last_p_index = current_ttags.rfind(close_p_tag)
                    # 分割：</p>之前的部分 和 </p>及之后的部分
                    tags_before_last_p = current_ttags[:last_p_index]
                    last_p_part = current_ttags[last_p_index:]
                    return f"{current_core}{tags_before_last_p}{close_quote}{last_p_part}"
                else:
                    # 如果没有 </p>，则加在核心内容和所有结尾标签之间
                    return f"{current_core}{close_quote}{current_ttags}"

            # -- 根据 type 构建行 --
            if type == 1:
                if num_lines == 1:
                    # 单行：需要开引号和特殊处理的关引号
                    start_part = f"{prefix}{lead}{ltags}{colon}{open_quote}"
                    formatted_line = format_with_close_quote(start_part + core, core, ttags)
                elif i == 0:  # 第一行
                    # 只有开引号，保留所有标签
                    formatted_line = f"{prefix}{lead}{ltags}{colon}{open_quote}{core}{ttags}"
                elif i == num_lines - 1:  # 最后一行
                    # 只有特殊处理的关引号，保留所有标签
                    start_part = f"{prefix}{lead}{ltags}"
                    formatted_line = format_with_close_quote(start_part + core, core, ttags)
                else:  # 中间行
                    # 无引号，保留所有标签
                    formatted_line = f"{prefix}{lead}{ltags}{colon}{core}{ttags}"

            elif type == 2:
                # 每行都有开引号
                start_part = f"{prefix}{lead}{ltags}{colon}{open_quote}{core}"
                if i == num_lines - 1:  # 最后一行，需要特殊处理关引号
                    formatted_line = format_with_close_quote(start_part, core, ttags)
                else:  # 非最后一行，只有开引号
                    formatted_line = f"{start_part}{ttags}"

            elif type == 3:
                # 每行都有开引号和特殊处理的关引号
                start_part = f"{prefix}{lead}{ltags}{colon}{open_quote}{core}"
                formatted_line = format_with_close_quote(start_part, core, ttags)

            else:
                QMessageBox.warning(self.file_widget, "未知类型", f"不支持的操作类型: {type}")
                return

            new_lines.append(formatted_line)

        self.text_edit.insert_and_highlight_chars(cursor, "\n".join(new_lines))

    def add_quote_in_selection(self, left_quote: str, right_quote: str):
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            new_text = f"{left_quote}{self.text_edit.get_normalized_selected_text(cursor)}{right_quote}"
            self.text_edit.insert_and_highlight_chars(cursor, new_text)

    def add_quote_in_expansion(self, left_quote: str, right_quote: str):
        cursor, selected_text = self._expand_selected_line_text()
        if selected_text:
            pattern = regex.compile(r"((?:\[(?:行号|匹配)：.*?\])?\s+(?:<p.*?>)?)(.*)", regex.DOTALL)
            new_text = pattern.sub(rf"\1{left_quote}\2{right_quote}", selected_text)
            new_text = new_text.replace(f"</p>{right_quote}", f"{right_quote}</p>")
            self.text_edit.insert_and_highlight_chars(cursor, new_text)

    def _expand_selected_line_text(self):
        """
        将选中的跨行文本扩展到完整行，并返回新的光标和选中的文本

        Returns:
            tuple: 包含新的 QTextCursor 对象和选中的文本字符串
        """
        return self.text_edit.expand_selected_line_text()

    def change_case_in_text(self, mode: int):
        cursor = self.text_edit.textCursor()
        selected_text = self.text_edit.get_normalized_selected_text(cursor)
        if not selected_text:
            QMessageBox.warning(self.file_widget, "无选中内容", "请先选中要处理的内容")
            return

        try:
            fixed_case_words = []
            if mode == 4:  # 读取 PHP 配置文件中的固定词组
                formatting_config_file = env_config.formatting_config_file
                fixed_case_words = util.parse_php_config(formatting_config_file)["fixedCaseWords"]

            is_html_file = self.file_widget.is_html_file
            new_text = TextCaseConverter.change_case_in_text(selected_text, mode, fixed_case_words, is_html_file)

            self.text_edit.insert_and_highlight_chars(cursor, new_text)

        except regex.error as e:
            QMessageBox.warning(self.file_widget, "正则错误", f"无效的正则表达式: {str(e)}")
        except Exception as e:
            QMessageBox.warning(self.file_widget, "未知错误", f"未知错误，无法操作: {str(e)}")

    def process_arabic_to_chn_num(self):
        cursor = self.text_edit.textCursor()
        selected_text = self.text_edit.get_normalized_selected_text(cursor)
        if not selected_text:
            QMessageBox.warning(self.file_widget, "无选中内容", "请先选中要处理的内容")
            return

        try:
            # 阿拉伯数字转中文
            new_text = regex.sub(
                r"(?<!行号：)(?<!匹配：)(?<!【匹配项：)(?<![\d/\.])(\d+)(?![\]%\.\d])",
                lambda m: util.arabic_to_chn_num(int(m.group())),
                selected_text,
            )

            # 特殊处理“二”字
            new_text = regex.sub(
                r"(?<![第十点])((?<![千万])二[千万](?![百千万])|二三?(?:分[米钟]|小时|公里|[年岁滴枚堆条个块根秒支枝柄把只张厘米吨斤克毫份桶口天次门杯下圈朵股波拨群名位碗盘盆框颗粒副幅瓶罐套])|[午晚晨]二点)",
                lambda m: m.group().replace("二", "两"),
                new_text,
            )

            self.text_edit.insert_and_highlight_chars(cursor, new_text)

        except regex.error as e:
            QMessageBox.warning(self.file_widget, "正则错误", f"无效的正则表达式: {str(e)}")

    def process_chn_to_arabic_num(self):
        cursor = self.text_edit.textCursor()
        selected_text = self.text_edit.get_normalized_selected_text(cursor)
        if not selected_text:
            QMessageBox.warning(self.file_widget, "无选中内容", "请先选中要处理的内容")
            return

        def chn_repl(m) -> str:
            original_match = m.group(0)
            arabic_num = util.chn_to_arabic_num(original_match)
            if arabic_num is None:
                return original_match
            else:
                return str(arabic_num)

        try:
            new_text = regex.sub(
                r"[一二三四五六七八九十零〇百千万亿两廿卅卌壹贰叁肆伍陆柒捌玖拾]+",
                chn_repl,
                selected_text,
            )

            self.text_edit.insert_and_highlight_chars(cursor, new_text)

        except regex.error as e:
            QMessageBox.warning(self.file_widget, "正则错误", f"无效的正则表达式: {str(e)}")

    def trans_quotations_1(self):
        """
        将单引号‘’替换为〔〕
        """
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            new_text = self.text_edit.get_normalized_selected_text(cursor).replace("‘", "〔").replace("’", "〕")
            self.text_edit.insert_and_highlight_chars(cursor, new_text)

    def convert_by_fixed_rules(self) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            return

        # 历史记录数据
        history_items = self._fixed_rules_history if self._fixed_rules_history else []
        initial_text = history_items[0] if history_items else ""

        # --- 1. 创建自定义 Dialog ---
        dialog = QDialog(self.file_widget)
        dialog.setWindowTitle("批注规则转换")
        dialog.setMinimumWidth(350)
        layout = QVBoxLayout(dialog)
        label = QLabel("请输入转换内容：", dialog)
        layout.addWidget(label)

        # --- 2. 输入框 (QLineEdit) ---
        line_edit = QLineEdit(dialog)
        line_edit.setText(initial_text)
        line_edit.setPlaceholderText("在此输入或从下方选择")
        layout.addWidget(line_edit)

        # --- 3. 历史记录列表 (QListWidget) ---
        list_widget = QListWidget(dialog)
        list_widget.addItems(history_items)
        list_widget.setAlternatingRowColors(True)

        def on_item_clicked(item):
            line_edit.setText(item.text())  # 先把文字填入输入框
            dialog.accept()  # 然后直接触发“确定”，关闭窗口

        # 单击即触发
        list_widget.itemClicked.connect(on_item_clicked)

        # --- 4. 关键：计算列表高度 (最多显示 5 项) ---
        if history_items:
            row_height = list_widget.sizeHintForRow(0)
            if row_height < 0:
                row_height = 25  # 默认兜底高度

            # 计算要显示的行数，强制设置列表高度
            display_count = min(len(history_items), 5)

            list_height = (row_height * display_count) + (list_widget.frameWidth() * 2) + 2
            list_widget.setFixedHeight(list_height)
        else:
            # 如果没有历史记录
            list_widget.hide()

        layout.addWidget(list_widget)

        # --- 5. 底部按钮 ---
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        # 默认焦点在输入框，方便直接打字
        line_edit.setFocus()
        line_edit.selectAll()

        # --- 6. 执行与处理结果 ---
        if dialog.exec_() == QDialog.Accepted:
            after_text = line_edit.text()
            if not after_text:
                return

            # 更新历史记录
            if after_text in self._fixed_rules_history:
                self._fixed_rules_history.remove(after_text)
            self._fixed_rules_history.insert(0, after_text)

            before_text = self.text_edit.get_normalized_selected_text(cursor)
            converter_script = env_config.fixed_rules_converter_script
            try:
                result = util.run_php_script(converter_script, before_text, after_text)
                if result:
                    self.text_edit.insert_and_highlight_chars(cursor, result)
            except Exception as e:
                logging.error(f"转换脚本执行失败：{e}")

        self.text_edit.setFocus()

    def strip_html_tags(self) -> None:
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            QMessageBox.warning(self.file_widget, "无选中内容", "请先选中要处理的内容")
            return

        selected_text = self.text_edit.get_normalized_selected_text(cursor)

        # 步骤 1: 使用正则表达式移除所有 HTML 标签
        text_no_tags = PatchFormatter.strip_all_tags(selected_text)
        text_no_tags = regex.compile(r"<[^>]+>").sub("", text_no_tags)

        # 步骤 2: 解码剩余的 HTML 实体 (例如 &lt; -> <, &nbsp; -> ' ')
        new_text = html.unescape(text_no_tags)

        self.text_edit.insert_and_highlight_chars(cursor, new_text)

        self.text_edit.setFocus()

    def merge_selected_lines(self):
        """
        将选中的多行文本合并为一行，并保留第一行的原始前缀（行号和缩进）
        """
        self.text_edit.merge_selected_lines()

    def extend_current_matches(self) -> None:
        """扩展当前选中区域内的所有匹配项，合并重叠项"""
        self.match_extender.extend_current_matches()

    def revert_diff(self) -> None:
        """
        恢复（反转）选定区域或光标所在位置的差异标记
        - 添加（a）和删除（d）标记会相互转换
        - 替换旧值（o）和新值（n）标记的内容会相互交换
        """
        cursor = self.text_edit.textCursor()
        full_text = self.text_edit.toPlainText()

        # 1. 转换光标坐标为 Python 视角的安全索引
        start_pos = util.qt_to_py_index(cursor.selectionStart(), full_text)
        end_pos = util.qt_to_py_index(cursor.selectionEnd(), full_text)

        # 2. 调用 PatchFormatter 计算并扩展操作范围
        expanded_start, expanded_end = PatchFormatter.get_actionable_range(full_text, start_pos, end_pos)
        if expanded_start == -1:
            QMessageBox.warning(self.text_edit, "操作无效", "未在选区内找到任何差异标记")
            return

        # 3. 提取原文本并反向处理
        original_text = full_text[expanded_start:expanded_end]
        modified_text = PatchFormatter.revert_string(original_text)

        # 4. 将修改后的文本应用回编辑器
        if modified_text != original_text:
            cursor.beginEditBlock()
            replace_cursor = self.text_edit.textCursor()

            # 翻译回 Qt 的 UTF-16 坐标
            qt_expanded_start = util.py_to_qt_index(expanded_start, full_text)
            qt_expanded_end = util.py_to_qt_index(expanded_end, full_text)

            replace_cursor.setPosition(qt_expanded_start)
            replace_cursor.setPosition(qt_expanded_end, QTextCursor.KeepAnchor)

            self.text_edit.insert_and_highlight_chars(replace_cursor, modified_text, False)

            self.text_edit.setTextCursor(replace_cursor)
            cursor.endEditBlock()
        else:
            QMessageBox.information(self.text_edit, "无变化", "未在选区内找到可还原的差异项")

    def sync_diff(self) -> None:
        LINE_PREFIX_PATTERN = regex.compile(r"^(【匹配项：.*?】)", regex.M)
        NEXT_MATCH_END = "※※※（下文省略）※※※"

        cursor = self.text_edit.textCursor()
        doc = self.text_edit.document()

        # --- 1. 确定操作范围的起始位置（向上找） ---
        selection_start_pos = cursor.selectionStart()
        start_block = doc.findBlock(selection_start_pos)

        # 从选区开始处不断向上，直到匹配到前缀
        while start_block.isValid() and not LINE_PREFIX_PATTERN.match(start_block.text()):
            start_block = start_block.previous()

        if not start_block.isValid():
            return

        operation_start_pos = start_block.position()

        # --- 2. 确定操作范围的结束位置（向下找） ---
        selection_end_pos = cursor.selectionEnd()
        end_block = doc.findBlock(selection_end_pos)

        # 选区微调：如果用户用鼠标划选时，多划到了下一行的行首，
        # 把结束块退回到上一行的行尾，避免把不相干的下一段卷进来
        if (
            cursor.hasSelection()
            and selection_end_pos == end_block.position()
            and doc.findBlock(selection_start_pos) != end_block
        ):
            end_block = end_block.previous()

        # 从 end_block 自身开始向下找 END 标记
        operation_end_block = end_block
        while operation_end_block.isValid():
            if NEXT_MATCH_END in operation_end_block.text():
                break
            operation_end_block = operation_end_block.next()

        if not operation_end_block.isValid():
            # 万一文档末尾缺失了 END 标记，就以选区本来所在的块作为结尾兜底
            operation_end_block = end_block

        # 结束位置先包含当前 END 块及其末尾的回车符
        operation_end_pos = operation_end_block.position() + operation_end_block.length()

        # 检查紧接着的下一行是不是间隔空行，如果是，把它也“吞”进来一并删掉
        next_empty_block = operation_end_block.next()
        while next_empty_block.isValid() and next_empty_block.text().strip() == "":
            operation_end_pos = next_empty_block.position() + next_empty_block.length()
            next_empty_block = next_empty_block.next()

        max_pos = doc.characterCount() - 1
        if operation_end_pos > max_pos:
            operation_end_pos = max_pos

        # --- 3. 执行操作 ---
        new_cursor = QTextCursor(doc)
        new_cursor.setPosition(operation_start_pos)
        new_cursor.setPosition(operation_end_pos, QTextCursor.KeepAnchor)
        self.text_edit.setTextCursor(new_cursor)

        full_text = self.text_edit.toPlainText()
        py_start = util.qt_to_py_index(operation_start_pos, full_text)
        py_end = util.qt_to_py_index(operation_end_pos, full_text)

        expanded_start, _ = PatchFormatter.get_actionable_range(full_text, py_start, py_end)
        if expanded_start == -1:
            # 取消原本高亮的选区，避免影响观感
            new_cursor.clearSelection()
            self.text_edit.setTextCursor(new_cursor)
            QMessageBox.warning(self.text_edit, "操作无效", "未在选区内找到任何差异标记")
            return

        # 提取操作块纯文本
        selected_text = full_text[py_start:py_end]

        # 调用 PatchFormatter 翻转所有涉及的差异标签
        # 也就是获取到 booksBak 内的原内容
        old_text = PatchFormatter.revert_string(selected_text)

        # 发送信号，让 save_controller 去实际同步到文件
        self.text_edit.syncingDiff.emit(old_text, selected_text)

        # 从编辑器中删除旧的已处理的内容
        new_cursor.removeSelectedText()

        self.text_edit.smart_scroll()

    def renumber_chapters(self, type=0) -> None:
        """
        将包含 [行号/匹配：...] 标记的行后的第一个章节号进行重排
        重排从第一个匹配到的章节号开始，后续章节号依次递增
        支持 "xx-yy" 格式的章节范围，并将其规范化为单个数字
        """
        cursor, selected_text = self._expand_selected_line_text()
        if not selected_text or "【章节行】" not in selected_text:
            QMessageBox.warning(self.file_widget, "提示", "请选中包含【章节行】的内容")
            return

        # 1. 扫描检测
        has_sub = ChapterNumChecker.has_sub_chapter_suffix(selected_text)
        has_range = ChapterNumChecker.has_range_pattern(selected_text)
        has_vol_change = ChapterNumChecker.has_volume_change(selected_text)

        # 2. 交互逻辑
        group_sub, reset_vol, keep_range = False, False, False
        if has_sub or has_vol_change or has_range:
            dlg = RenumberOptionsDialog(self.file_widget, has_sub, has_vol_change, has_range)
            if dlg.exec_() == QDialog.Accepted:
                group_sub = dlg.results["group_sub"]
                reset_vol = dlg.results["reset_vol"]
                keep_range = dlg.results["keep_range"]
            else:
                return

        # 3. 执行
        success, result = ChapterNumChecker.renumber_chapter_text(
            selected_text,
            renumber_type=type,
            group_sub_chapters=group_sub,
            reset_on_volume=reset_vol,
            preserve_range=keep_range,
        )

        if success:
            self.text_edit.insert_and_highlight_chars(cursor, result, False)
        else:
            QMessageBox.warning(self.file_widget, "错误", result)
