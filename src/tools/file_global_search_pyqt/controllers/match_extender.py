from qtpy.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QDialogButtonBox,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
    QShortcut,
)
from qtpy.QtGui import QTextCursor, QTextBlock, QColor, QKeySequence
from qtpy.QtCore import Qt, QTimer, Signal, QObject

import regex

from typing import TYPE_CHECKING, Optional, List, Dict, Tuple, Union

if TYPE_CHECKING:
    from models.search_model import SearchModel
    from widgets.file_widget import FileWidget
    from widgets.text_editor_widget import TextEditorWidget
    from widgets.bottom_button_widget import BottomButtonWidget


from core.constants import PROP_LINE_NUM, PROP_MATCHED, PatchSearchAction


class MatchExtender(QObject):
    """
    处理匹配项扩展逻辑的类
    """

    matchExtended = Signal(str, str)  # old_text, new_text

    MATCH_HEADER_TAG = "【匹配项："
    OMIT_UPPER_TAG = "※※※（上文省略）※※※"
    OMIT_LOWER_TAG = "※※※（下文省略）※※※"
    CHAPTER_TAG = "【章节行】"

    def __init__(
        self,
        search_model: "SearchModel",
        file_widget: "FileWidget",
        text_editor_widget: "TextEditorWidget",
        bottom_button_widget: "BottomButtonWidget",
    ):
        super().__init__()

        self.search_model = search_model

        self.file_widget = file_widget
        self.text_editor_widget = text_editor_widget
        self.bottom_button_widget = bottom_button_widget

        self.text_edit = self.text_editor_widget.get_text_edit()

        # --- 配置项 ---
        # 定义相邻判断的阈值（行数，硬限制）
        # 用于：
        # 1. 决定是否将相邻的匹配项视为"连通"并强制合并
        # 2. 当扩展遇到未选中的"障碍物"时，作为安全回退距离
        self.neighbor_limit = 2

    def extend_current_matches(self) -> None:
        """扩展当前选中区域内的所有匹配项，合并重叠项"""
        self.is_patch_search = self.search_model.is_patch_search()
        if self.is_patch_search != PatchSearchAction.NOT_PATCH_SEARCH:
            # 在比对视图下，只支持“预览模式”
            self._handle_preview_extend()
            return

        # 识别选中区域内的所有匹配项
        cursor = self.text_edit.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.LineUnderCursor)

        match_blocks = self._find_all_match_blocks_in_selection(cursor)

        if match_blocks == "isChapterSearch":
            # 对章节行的搜索，只支持“预览模式”
            self._handle_preview_extend()
            return

        if not match_blocks:
            QMessageBox.warning(
                self.file_widget, "错误", "未找到匹配项边界。请先点击或选取有“行号”的内容，再进行扩展。"
            )
            return

        # 读取源文件
        file_lines = self._read_source_file()
        if file_lines is None:
            return

        # 获取扩展参数
        extend_prev_lines, extend_next_lines, ok = self._show_extend_lines_dialog()
        if not ok:
            return

        match_blocks = self._expand_to_overlapping_neighbors(match_blocks, extend_prev_lines, extend_next_lines)

        # 合并有重叠的匹配项
        merged_blocks = self._merge_overlapping_matches(match_blocks, extend_prev_lines, extend_next_lines, file_lines)

        # 执行扩展操作
        self._apply_extensions(merged_blocks, file_lines)

    def _handle_preview_extend(self) -> None:
        """
        预览模式：
        不更改文本框中的内容
        处理上下文扩展、预览与直接保存逻辑
        """
        # 1. 获取当前光标所在的 Block 和行号属性
        cursor = self.text_edit.textCursor()
        current_block = cursor.block()
        block_format = current_block.blockFormat()

        if not block_format.hasProperty(PROP_LINE_NUM):
            QMessageBox.warning(self.file_widget, "错误", "未获取到行号信息。请先点击有“行号”的行，再进行扩展。")
            return

        line_num = block_format.property(PROP_LINE_NUM)
        if not line_num.isdigit():
            return

        line_num = int(block_format.property(PROP_LINE_NUM)) - 1

        # 2. 弹出选择行数的无警告对话框
        extend_prev_lines, extend_next_lines, ok = self._show_preview_extend_dialog()
        if not ok:
            return

        # 3. 读取源文件
        file_lines = self._read_source_file()
        if not file_lines:
            return

        total_lines = len(file_lines)

        # 4. 计算需要提取的上下文行范围
        start_idx = max(0, line_num - extend_prev_lines)
        # 包含目标行本身，因此要 + 1
        end_idx = min(total_lines, line_num + extend_next_lines + 1)

        # 提取上下文文本 (假设 file_lines 中的元素自带尾部换行符 \n)
        context_text = "".join(file_lines[start_idx:end_idx])
        highlight_line_index = line_num - start_idx

        # 5. 弹出预览与编辑对话框
        new_text, is_saved = self._show_preview_edit_dialog(context_text, highlight_line_index, start_idx + 1)

        # 6. 如果点击了保存，且内容有修改，则覆盖写入源文件
        if is_saved and new_text != context_text:
            # 兼容处理：防止 QPlainTextEdit 丢失末尾的换行符导致和下文粘连
            if context_text.endswith("\n") and not new_text.endswith("\n"):
                new_text += "\n"

            new_file_content = "".join(file_lines[:start_idx]) + new_text + "".join(file_lines[end_idx:])

            try:
                file_path = self.file_widget.get_file_path()
                if self.is_patch_search == PatchSearchAction.BAK_VS_BOOKS:
                    file_path = self.file_widget.get_backup_file_path()
                with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new_file_content)
                QMessageBox.information(
                    self.file_widget, "保存成功", "修改已保存到源文件。\n建议重新生成比对结果以查看最新状态。"
                )
            except Exception as e:
                QMessageBox.critical(self.file_widget, "保存失败", f"写入源文件时发生错误：\n{str(e)}")

    def _show_preview_extend_dialog(self) -> Tuple[int, int, bool]:
        """显示 Patch 模式下专用的扩展行数对话框"""
        dialog = QDialog(self.file_widget)
        dialog.setWindowTitle("预览上下文")

        layout = QVBoxLayout(dialog)

        h_layout = QHBoxLayout()
        spin_prev = QSpinBox()
        spin_prev.setMinimum(0)
        spin_prev.setMaximum(9999)
        spin_prev.setValue(30)
        spin_prev.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        spin_next = QSpinBox()
        spin_next.setMinimum(0)
        spin_next.setMaximum(9999)
        spin_next.setValue(30)
        spin_next.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h_layout.addWidget(QLabel("上文行数:"))
        h_layout.addWidget(spin_prev)
        h_layout.addSpacing(20)
        h_layout.addWidget(QLabel("下文行数:"))
        h_layout.addWidget(spin_next)
        layout.addLayout(h_layout)

        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.adjustSize()

        if dialog.exec_() == QDialog.Accepted:
            return spin_prev.value(), spin_next.value(), True
        else:
            return 0, 0, False

    def _show_preview_edit_dialog(
        self, initial_text: str, highlight_line_idx: int, start_line_num: int
    ) -> Tuple[str, bool]:
        """显示带有编辑器的预览对话框，并返回 (最终文本, 是否点击了保存)"""
        dialog = QDialog(self.file_widget)
        dialog.setWindowTitle("预览与编辑上下文")
        dialog.resize(700, 500)  # 给一个比较大的窗口方便阅读和编辑

        layout = QVBoxLayout(dialog)

        editor = QPlainTextEdit()
        editor.setFont(self.text_edit.font())

        # 添加行号前缀
        lines = initial_text.splitlines()
        prefixed_lines = [f"[行号：{start_line_num + i}] {line}" for i, line in enumerate(lines)]
        editor.setPlainText("\n".join(prefixed_lines))

        # 高亮指定行并居中
        block = editor.document().findBlockByNumber(highlight_line_idx)
        if block.isValid():
            cursor = QTextCursor(block)
            editor.setTextCursor(cursor)
            QTimer.singleShot(0, editor.centerCursor)

            selection = QTextEdit.ExtraSelection()
            selection.format.setForeground(QColor("#f0574c"))  # 设置前景色为红色
            cursor.select(QTextCursor.BlockUnderCursor)
            selection.cursor = cursor
            editor.setExtraSelections([selection])

        layout.addWidget(editor)

        hint_label = QLabel(
            "可以在上方直接编辑内容，点击“保存”后，修改将被直接写入源文件。\n"
            "请勿修改 [行号：xxx] 前缀。文本框的内容不会实时刷新，可以重新点击“比对”生成视图。"
        )
        hint_label.setStyleSheet("color: #888888;")
        layout.addWidget(hint_label)

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.button(QDialogButtonBox.Save).setText("保存")
        button_box.button(QDialogButtonBox.Cancel).setText("取消")
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        # 绑定 Ctrl+S 快捷键到“保存”
        shortcut = QShortcut(QKeySequence("Ctrl+S"), dialog)
        shortcut.activated.connect(dialog.accept)

        if dialog.exec_() == QDialog.Accepted:
            edited_text = editor.toPlainText()
            # 使用 regex.sub 和 MULTILINE 标志一次性移除所有行号前缀
            final_text = regex.sub(r"^\[行号：\d+\] ?", "", edited_text, flags=regex.MULTILINE)

            # 原始代码中的兼容处理
            if initial_text.endswith("\n") and not final_text.endswith("\n"):
                final_text += "\n"

            return final_text, True
        else:
            return "", False

    def _show_extend_lines_dialog(self) -> Tuple[int, int, bool]:
        """显示扩展行数对话框"""
        dialog = QDialog(self.file_widget)
        dialog.setWindowTitle("扩展上下文")

        layout = QVBoxLayout(dialog)

        # 输入区域
        h_layout = QHBoxLayout()
        spin_prev = QSpinBox()
        spin_prev.setMinimum(0)
        spin_prev.setMaximum(9999)
        spin_prev.setValue(3)  # 默认值
        spin_prev.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        spin_next = QSpinBox()
        spin_next.setMinimum(0)
        spin_next.setMaximum(9999)
        spin_next.setValue(3)  # 默认值
        spin_next.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        h_layout.addWidget(QLabel("扩展上文行数:"))
        h_layout.addWidget(spin_prev)
        h_layout.addSpacing(20)
        h_layout.addWidget(QLabel("扩展下文行数:"))
        h_layout.addWidget(spin_next)
        layout.addLayout(h_layout)

        # 【坑 1】：
        # 不要考虑在扩展后直接 clearUndoRedoStacks。如果在扩展之后做了一些修改，
        # 然后又撤销到扩展时的状态，这时会误判为整个文档都没有修改，
        # 无法将扩展之前做的其他修改（实际可能有）应用到文件。
        #
        # 【坑 2】：
        # 在“扩展->修改->保存”这个流程中，保存之后需要更新 initial_search_result。
        # 而 on_editor_undo 正确回滚的前提是 initial_search_result 没有变动过（走入 else pass 那个分支），
        # 否则在下一步的“当前深度 < 记录深度”那个实际的回滚动作中，是无法通过 replace 还原回去的。
        # 也不能考虑直接将保存后的 initial_search_result 回滚到保存前的状态，
        # 因为保存的时候必须要用最新的 initial_search_result 来比对并进行替换……
        # 所以，只能先接受保存之后不能撤销到扩展操作之前的现状。
        # 或者，可以在“有扩展”并“保存”时，记录一下前面的 initial_search_result，
        # 然后在撤销和重做时，都触发 save 动作，同步回滚或重做 initial_search_result，但是很麻烦……
        warning_label = QLabel(
            "警告：未完全处理【扩展】操作的撤销逻辑。\n\n"
            "【扩展当前项之后】，如果有做修改并【保存】，\n"
            "切勿撤销到【扩展当前项之前】，否则会出问题。\n【未保存】时则可随意撤销。"
        )
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet("color: red;")
        layout.addWidget(warning_label)

        # 按钮
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout.addWidget(button_box)

        dialog.adjustSize()

        if dialog.exec_() == QDialog.Accepted:
            return spin_prev.value(), spin_next.value(), True
        else:
            return 0, 0, False

    def _find_all_match_blocks_in_selection(self, cursor: QTextCursor) -> Union[List[Dict], str]:
        """找到选中区域内的所有匹配项"""
        doc = self.text_edit.document()
        selection_start = cursor.selectionStart()
        selection_end = cursor.selectionEnd()

        match_blocks = []
        current_block = doc.findBlock(selection_start)

        # 回溯到最近的匹配项标题或上文省略标记
        while current_block.isValid():
            text = current_block.text()
            if self.CHAPTER_TAG in text:  # 章节行只支持预览
                return "isChapterSearch"

            if self.MATCH_HEADER_TAG in text:
                break
            current_block = current_block.previous()

        # 向前搜索所有匹配项
        while current_block.isValid() and current_block.position() < selection_end:
            if self.MATCH_HEADER_TAG in current_block.text():
                match_info = self._parse_single_match_block(current_block)
                if match_info:
                    # 检查该匹配项是否与选中区域有交集，如果光标开始时位于：
                    # 【匹配项：xxx】 这一行之内
                    # 回溯标记行时会找到前一个匹配项，实际上这前一个匹配项是不用扩展的
                    if match_info["end_block"].position() >= selection_start:
                        match_blocks.append(match_info)
                    current_block = match_info["end_block"].next()
                    continue
            current_block = current_block.next()

        return match_blocks

    def _parse_single_match_block(self, header_block: QTextBlock) -> Optional[Dict]:
        """从标题行（匹配项行）开始解析"""
        if self.MATCH_HEADER_TAG not in header_block.text():
            return None

        # 找到下文省略标记
        end_marker_block = header_block.next()
        while end_marker_block.isValid():
            if self.OMIT_LOWER_TAG in end_marker_block.text():
                break
            # 如果在找到结束符前遇到了下一个标题，说明当前块结构损坏
            if self.MATCH_HEADER_TAG in end_marker_block.text():
                return None
            end_marker_block = end_marker_block.next()

        if not end_marker_block.isValid():
            return None

        # 提取行号信息
        line_info = self._extract_line_info(header_block, end_marker_block)
        if not line_info["first_line_num"]:
            return None

        # 创建一个临时光标来选中 header_block 的内容，是为了同步获取 [进度：] 的信息
        # 这里临时去除了多余的换行符 \n，待整理
        header_cursor = QTextCursor(header_block)
        header_cursor.select(QTextCursor.BlockUnderCursor)
        header_text = self.text_edit.get_normalized_selected_raw_text(header_cursor).replace("\n", "")

        return {
            "start_block": header_block,  # 起始点是标题行
            "end_block": end_marker_block,
            "line_info": line_info,
            "header_text": header_text,  # 保存标题文本
        }

    def _extract_line_info(self, start_block: QTextBlock, end_block: QTextBlock) -> Dict:
        """提取匹配项中的行号信息"""
        line_info = {}
        first_line_num = None
        last_line_num = None

        current_block = start_block.next()
        while current_block.isValid() and current_block.position() < end_block.position():
            fmt = current_block.blockFormat()
            if fmt.hasProperty(PROP_LINE_NUM):
                line_type = int(fmt.property(PROP_MATCHED))
                num_str = fmt.property(PROP_LINE_NUM)
                line_num = None
                if num_str.isdigit():
                    line_num = int(num_str)
                if first_line_num is None:
                    first_line_num = line_num
                last_line_num = line_num
                line_info[line_num] = line_type

            current_block = current_block.next()

        return {
            "first_line_num": first_line_num,
            "last_line_num": last_line_num,
            "line_types": line_info,
        }

    def _read_source_file(self) -> Optional[List[str]]:
        """读取源文件内容"""
        current_file = self.file_widget.get_file_path()
        if self.is_patch_search == PatchSearchAction.BAK_VS_BOOKS:
            current_file = self.file_widget.get_backup_file_path()
        try:
            with open(current_file, "r", encoding="utf-8") as f:
                return f.readlines()
        except Exception as e:
            QMessageBox.warning(self.file_widget, "文件读取错误", f"无法读取文件：{current_file}\n{e}")
            return None

    def _expand_to_overlapping_neighbors(
        self, match_blocks: List[Dict], extend_prev: int, extend_next: int
    ) -> List[Dict]:
        """
        向前后扩展
        合并条件（满足其一即可）：
        1. 在原始选中项的扩展范围内 （保证用户输入的扩展行数能生效）
        2. 与当前边缘项的距离在 neighbor_limit 内（处理级联吸附，但受输入扩展量限制）
        """
        if not match_blocks:
            return []

        # --- 1. 锁定原始射程边界 ---
        # 无论列表后来怎么变，这个"原始基准"是不变的
        # 向上扩展的极限线：原始第一项的头部 - 用户输入的上文行数
        original_first = match_blocks[0]
        original_top_limit = original_first["line_info"]["first_line_num"] - extend_prev

        # 向下扩展的极限线：原始最后一项的尾部 + 用户输入的下文行数
        original_last = match_blocks[-1]
        original_bottom_limit = original_last["line_info"]["last_line_num"] + extend_next

        # --- 2. 向前吸附 (Previous) ---
        changed = True
        while changed:
            changed = False
            # 当前列表的最前端（可能是刚吸附进来的，也可能是原始的）
            current_first = match_blocks[0]
            curr_start = current_first["line_info"]["first_line_num"]

            prev_match = self._find_previous_match(current_first["start_block"])
            if prev_match:
                prev_end = prev_match["line_info"]["last_line_num"]

                # 判定条件 A：前一项是否在"原始射程"内？
                # (前一项的尾部 >= 原始极限线)
                in_original_range = prev_end >= original_top_limit

                # 判定条件 B：前一项是否与当前项"紧密相邻"？
                if extend_prev < self.neighbor_limit:
                    # 如果用户设定的扩展行数（extend_prev）小于吸附阈值（neighbor_limit），
                    # 说明用户希望精确控制，此时强制关闭吸附功能，避免过度扩展
                    is_close_neighbor = False
                else:
                    is_close_neighbor = (curr_start - self.neighbor_limit) <= prev_end

                # 只要满足任意一个条件，就吸附
                if in_original_range or is_close_neighbor:
                    match_blocks.insert(0, prev_match)
                    changed = True

        # --- 3. 向后吸附 (Next) ---
        changed = True
        while changed:
            changed = False
            # 当前列表的最后端
            current_last = match_blocks[-1]
            curr_end = current_last["line_info"]["last_line_num"]

            next_match = self._find_next_match(current_last["end_block"])
            if next_match:
                next_start = next_match["line_info"]["first_line_num"]

                # 判定条件 A：后一项是否在"原始射程"内？
                # (后一项的头部 <= 原始极限线)
                in_original_range = next_start <= original_bottom_limit

                # 判定条件 B：后一项是否与当前项"紧密相邻"？
                if extend_next < self.neighbor_limit:
                    # 同上，如果用户设定的扩展行数小于吸附阈值，则关闭吸附
                    is_close_neighbor = False
                else:
                    is_close_neighbor = (curr_end + self.neighbor_limit) >= next_start

                # 只要满足任意一个条件，就吸附
                if in_original_range or is_close_neighbor:
                    match_blocks.append(next_match)
                    changed = True

        return match_blocks

    def _merge_overlapping_matches(
        self, match_blocks: List[Dict], extend_prev: int, extend_next: int, file_lines: List[str]
    ) -> List[Dict]:
        """
        合并扩展后有重叠的匹配项，并处理与非选中项（障碍物）的碰撞回退
        """
        if not match_blocks:
            return []

        # 记录当前所有被选中/被吸附的"友军"位置
        current_block_positions = {m["start_block"].position() for m in match_blocks}

        extended_ranges = []
        for match_info in match_blocks:
            line_info = match_info["line_info"]
            first_line = line_info["first_line_num"]
            last_line = line_info["last_line_num"]

            # --- 计算上文扩展 (处理障碍物) ---
            current_extend_prev = extend_prev
            prev_match = self._find_previous_match(match_info["start_block"])

            cross_info_altered = False
            if current_extend_prev and self.search_model.has_pagination() and prev_match is None:
                cross_info_altered = True
                QMessageBox.information(
                    self.file_widget,
                    "跨页提醒",
                    "匹配项位于当前页边缘\n扩展后可能会覆盖前一页的匹配项，"
                    "导致前一页的原匹配项失效\n只有对当前扩展项的修改会保存到文件",
                )

            # 如果存在上一个匹配项，且它不是"友军"（即它是障碍物）
            if prev_match and prev_match["start_block"].position() not in current_block_positions:
                prev_last_line = prev_match["line_info"]["last_line_num"]
                distance = first_line - prev_last_line

                # 计算最大安全距离。任何情况下，扩展绝不能覆盖障碍物（即不能 >= distance）
                max_safe_extend = max(0, distance - 1)

                # 逻辑：如果输入扩展量足以覆盖障碍物 (distance <= extend_prev)
                # 但障碍物距离较远 (distance > neighbor_limit)
                # 则这不应被视为合并，而应视为碰撞，强制回退扩展量
                if self.neighbor_limit < distance <= extend_prev:
                    current_extend_prev = self.neighbor_limit

                # 无论是哪种碰撞情况，最终扩展量绝不能越界
                current_extend_prev = min(current_extend_prev, max_safe_extend)

            # --- 计算下文扩展 (处理障碍物) ---
            current_extend_next = extend_next
            next_match = self._find_next_match(match_info["end_block"])

            if (
                not cross_info_altered
                and current_extend_next
                and self.search_model.has_pagination()
                and next_match is None
            ):
                QMessageBox.information(
                    self.file_widget,
                    "跨页提醒",
                    "匹配项位于当前页边缘\n扩展后可能会覆盖后一页的匹配项，"
                    "导致后一页的原匹配项失效\n只有对当前扩展项的修改会保存到文件",
                )

            # 如果存在下一个匹配项，且它不是"友军"
            if next_match and next_match["start_block"].position() not in current_block_positions:
                next_first_line = next_match["line_info"]["first_line_num"]
                distance = next_first_line - last_line

                # 计算最大安全距离
                max_safe_extend = max(0, distance - 1)

                # 同样的碰撞回退逻辑
                if self.neighbor_limit < distance <= extend_next:
                    current_extend_next = self.neighbor_limit

                # 无论是哪种碰撞情况，最终扩展量绝不能越界
                current_extend_next = min(current_extend_next, max_safe_extend)

            # 计算最终的起止行
            new_start = max(1, first_line - current_extend_prev)
            new_end = min(len(file_lines), last_line + current_extend_next)

            extended_ranges.append(
                {
                    "match_info": match_info,
                    "new_start": new_start,
                    "new_end": new_end,
                    "line_types": line_info["line_types"].copy(),  # 复制避免引用问题
                }
            )

        # 合并重叠的范围
        merged = []
        current_merge = extended_ranges[0]

        for i in range(1, len(extended_ranges)):
            next_range = extended_ranges[i]

            # 检查是否重叠（当前结束 >= 下一个开始）
            if current_merge["new_end"] >= next_range["new_start"]:
                # 合并：扩展范围，合并 line_types。注意这里取两者的最大值，也就是保证会至少满足用户输入的扩展行数
                current_merge["new_end"] = max(current_merge["new_end"], next_range["new_end"])
                current_merge["line_types"].update(next_range["line_types"])
                # 更新 end_block 为最后一个匹配项的 end_block
                current_merge["match_info"]["end_block"] = next_range["match_info"]["end_block"]
            else:
                # 不重叠，保存当前合并结果，开始新的合并
                merged.append(current_merge)
                current_merge = next_range

        # 添加最后一个
        merged.append(current_merge)

        return merged

    def _find_previous_match(self, start_block: QTextBlock) -> Optional[Dict]:
        """查找指定块之前的匹配项"""
        current_block = start_block.previous()

        # 向前查找上一个“【匹配项：”标题行
        while current_block.isValid():
            if self.MATCH_HEADER_TAG in current_block.text():
                return self._parse_single_match_block(current_block)
            current_block = current_block.previous()

        return None

    def _find_next_match(self, end_block: QTextBlock) -> Optional[Dict]:
        """查找指定块之后的匹配项"""
        current_block = end_block.next()

        # 向后查找下一个“【匹配项：”标题行
        while current_block.isValid():
            if self.MATCH_HEADER_TAG in current_block.text():
                return self._parse_single_match_block(current_block)

            current_block = current_block.next()

        return None

    def _apply_extensions(self, merged_blocks: List[Dict], file_lines: List[str]) -> None:
        """应用扩展操作：统一验证、整体拼接、单次替换"""
        if not merged_blocks:
            return

        doc = self.text_edit.document()
        initial_search_result = self.search_model.get_initial_search_result()

        # --- 阶段 1：验证与准备数据 ---
        all_new_texts = []

        # 获取总选区的起始和结束位置
        first_block = merged_blocks[0]["match_info"]["start_block"]
        last_block = merged_blocks[-1]["match_info"]["end_block"]

        # 定义总的替换光标范围
        overall_cursor = QTextCursor(doc)
        overall_cursor.setPosition(first_block.position())
        overall_cursor.setPosition(last_block.position() + last_block.length() - 1, QTextCursor.MoveMode.KeepAnchor)

        # 1.1 遍历验证
        for merged_info in merged_blocks:
            match_info = merged_info["match_info"]

            # 创建临时光标提取当前这个子块的原始文本，用于验证
            temp_cursor = QTextCursor(doc)
            temp_cursor.setPosition(match_info["start_block"].position())
            temp_cursor.setPosition(
                match_info["end_block"].position() + match_info["end_block"].length() - 1,
                QTextCursor.MoveMode.KeepAnchor,
            )

            # 检查 old_text 是否在 initial_search_result 中，如果不在，说明用户手动改过且未保存
            # 更新 initial_search_result 时会因为找不到 old_text，
            # 无法将【initial_search_result】中的“原匹配项的文本”正确更新为“扩展后的文本”，导致其结果始终未变
            # 这时如果去保存，则会直接将【实际文件】中的“原匹配项的文本”变成“扩展后的文本”，会多出重复的扩展行
            sub_old_text = self.text_edit.get_normalized_selected_raw_text(temp_cursor)

            if sub_old_text not in initial_search_result:
                QMessageBox.warning(
                    self.file_widget,
                    "警告",
                    f"在此项中有手动编辑的【未保存修改】：\n{match_info['header_text']}\n\n请先保存（Ctrl+S）后再执行扩展。",
                )
                return

            # 1.2 生成该子块扩展后的新文本
            sub_new_text = self._build_extended_text(
                merged_info["new_start"],
                merged_info["new_end"],
                file_lines,
                merged_info["line_types"],
                match_info["header_text"],
            )
            all_new_texts.append(sub_new_text)

        # --- 阶段 2：整体拼接与执行 ---
        # 获取整个选区当前的完整文本（包括匹配项之间的空行或标题）
        # 这是为了确保 emit 发射的 old_text 和编辑器中被替换掉的部分完全一致
        full_old_text = self.text_edit.get_normalized_selected_raw_text(overall_cursor)

        # 拼接新的完整文本，匹配项之间空一行
        full_new_text = "\n\n".join(all_new_texts)

        # 保存原始位置
        original_scroll_value = self.text_edit.verticalScrollBar().value()

        text_cursor = self.text_edit.textCursor()
        text_cursor.beginEditBlock()
        success = False
        try:
            # 执行单次替换
            self.text_edit.insert_and_highlight_lines(overall_cursor, full_new_text, False)
            success = True
        except Exception as e:
            QMessageBox.critical(self.file_widget, "错误", f"应用扩展时发生异常：\n{str(e)}")
            success = False
        finally:
            text_cursor.endEditBlock()

        if success:
            # 单次发射信号，告知模型：这一整段文字从 A 变为了 B
            # 这样在保存时，模型能通过 full_old_text 定位到文件位置并替换为 full_new_text
            # 不会反复清空 redo_stack 导致撤销重做失效
            self.matchExtended.emit(full_old_text, full_new_text)

        # 恢复视口位置
        self.text_edit.verticalScrollBar().setValue(original_scroll_value)

    def _build_extended_text(
        self, start_line: int, end_line: int, file_lines: List[str], line_types: Dict[int, str], header_text: str
    ) -> str:
        """构建扩展后的文本，包含保留的标题行"""
        lines = []

        # 1. 放入保留的标题行
        lines.append(f"{header_text}\n")

        # 2. 上文省略标记
        lines.append("※※※（上文省略）※※※\n")

        # 3. 内容行
        for i in range(start_line, end_line + 1):
            line_content = file_lines[i - 1]
            line_type = line_types.get(i, 0)
            line_type_str = "行号" if line_type == 0 else "匹配"
            prefix = f"[{line_type_str}：{i}]"
            lines.append(f"{prefix}{line_content}")

        # 4. 下文省略标记
        if end_line < len(file_lines):
            lines.append(self.OMIT_LOWER_TAG)

        return "".join(lines)
