import regex
import emmet
import logging

from qtpy.QtWidgets import QApplication, QPlainTextEdit, QShortcut, QWidget
from qtpy.QtGui import (
    QTextCharFormat,
    QTextBlockFormat,
    QTextCursor,
    QColor,
    QFontMetrics,
    QKeySequence,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QTextBlock,
    QPalette,
)
from qtpy.QtCore import Qt, Signal, QTimer, QRectF, QRect

from typing import TYPE_CHECKING, Tuple, Optional

if TYPE_CHECKING:
    from core.context_menu import ContextMenu

from config import SMOOTH_SCROLLING
from widgets.custom.custom_highlighter import CustomHighlighter
from widgets.custom.floating_tag_editor import FloatingTagEditor
from core.constants import PROP_LINE_NUM, PROP_MATCHED
import utils.util as util


class CustomPlainTextEdit(QPlainTextEdit):

    undoPerformed = Signal(bool)  # 这个值表示是否还有可撤销的操作
    redoPerformed = Signal(bool)  # 这个值表示是否还有可重做的操作
    replaceByListIndex = Signal(int)
    rawTextLoaded = Signal(str)  # 发送重载文本前的行号位置
    syncingDiff = Signal(str, str)  # (old_text, new_text)，用于将一些差异同步改到 booksBak

    # 定义一个阈值，光标移动超过多少行才算一次“有意义的”键盘跳转
    _KEYBOARD_JUMP_THRESHOLD_LINES = 3

    # 值越大在滚动时越容易触发重新定位
    _COMFORT_ZONE_MARGIN_FACTOR = 0.08

    _LINE_PREFIX_PATTERN = regex.compile(r"^\[(行号|匹配)\s*[:：]\s*(\d+)\](.*)$")
    _MATCH_PROGRESS_PATTERN = regex.compile(r"^(【匹配项：.*?】)\[进度：(.*?)\](.*)$")

    _RM_OLD_TAG_PATTERN = regex.compile(r"<［(o):.*?］>")
    _STRIP_DIFF_TAG_PATTERN = regex.compile(r"<?［?[onda]:(.*?)］>|<［[onda]?:?|］>")
    _TAG_PATTERN = regex.compile(r"<［([onda]):(.*?)］>")
    _OLD_NEW_TAG_PATTERN = regex.compile(r"<［([o]):(.*?)］><［([n]):(.*?)］>")

    def __init__(self, parent=None):
        super().__init__(parent)

        self.custom_menu: "ContextMenu" = None

        self.highlighter = CustomHighlighter(self.document())

        # 拖拽之后会导致光标莫名其妙消失，这里禁用，将事件转移到 MainWindow 处理
        self.setAcceptDrops(False)

        # 后退栈，存储过去的位置
        self.m_cursor_history_back = []
        # 前进栈，存储由后退操作产生的位置
        self.m_cursor_history_forward = []

        # 标志位，防止导航操作本身被记录
        self.m_is_navigating = False

        # 记录上一次光标的位置，用于判断键盘跳转
        self.m_last_cursor_pos = self.textCursor().position()
        self.current_line_number = None

        # 连接信号到槽函数
        self.cursorPositionChanged.connect(self._on_cursor_position_changed)
        self.cursorPositionChanged.connect(self.viewport().update)
        # 防止在调整光标时触发无限递归的标志位
        self._adjusting_cursor = False

        # 绑定快捷键
        QShortcut(QKeySequence(Qt.CTRL | Qt.ALT | Qt.Key_Left), self, self.navigate_back)
        QShortcut(QKeySequence(Qt.CTRL | Qt.ALT | Qt.Key_Right), self, self.navigate_forward)
        QShortcut(QKeySequence(Qt.CTRL | Qt.SHIFT | Qt.Key_D), self, self.duplicate_current_lines)

        self.replace_shortcuts_enabled = False

        # --- 滚动优化配置 ---
        self._smooth_scrolling = SMOOTH_SCROLLING

        # 速度单位，“行/帧”，而不是像素
        self._scroll_velocity = 0.0
        self._scroll_remainder = 0.0

        self._friction = 0.85  # 摩擦力系数
        self._min_velocity = 0.05  # 最小速度阈值

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(4)  # 根据显示器帧率调整
        self._scroll_timer.timeout.connect(self._update_scroll)

        # --- 特定字体颜色 ---
        self._new_chars_color = "#86EEA5", "#000000"
        self._new_lines_color = "#DBEAFE", "#000000"
        self._cur_line_color = "#454B5F"

        # --- 行号相关配置 ---
        self.line_number_area = LineNumberArea(self)
        self._show_line_num = True
        self._new_line_num_text = "新行号"
        self._max_line_num_val = 10000
        self._normal_line_number_color = "#888888"
        self._matched_line_number_color = "#E53935"
        self._new_line_number_color = "#43A047"
        self._progress_line_number_color = "#616161"

        self._cached_colors_dirty = True
        self._qc_normal_num = QColor()
        self._qc_matched_num = QColor()
        self._qc_new_num = QColor()
        self._qc_progress_num = QColor()

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.updateLineNumberAreaWidth(0)

        self.setMouseTracking(True)
        self.m_last_hover_pos = -1  # 记录上一次悬停的字符位置，优化性能
        self.m_last_screen_pos = None  # 物理坐标 (QPoint)

        # 初始化悬停定时器
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)  # 只触发一次
        self.hover_timer.timeout.connect(self._on_hover_timer_timeout)

        # 存储待处理的悬停数据
        self._pending_tag_data = None

        self.tag_editor = FloatingTagEditor(self.viewport())
        self.tag_editor.editFinished.connect(self._apply_tag_edit)
        self.tag_editor.editCancelled.connect(self._cancel_tag_edit)
        self.tag_editor.removeContent.connect(self._apply_tag_edit)

        self.hide_old_tag_content = False

    def set_custom_menu(self, menu):
        self.custom_menu = menu

    def get_highlighter(self) -> CustomHighlighter:
        return self.highlighter

    def update_colors(self, function_colors: dict):
        """统一更新所有功能性颜色"""

        def get_color(key, default_bg, default_fg="#000000"):
            bg, fg = function_colors.get(key, (default_bg, default_fg))
            return bg, fg

        self._new_chars_color = get_color("new_chars_color", "#86EEA5")
        self._new_lines_color = get_color("new_lines_color", "#DBEAFE")
        self._cur_line_color = get_color("cur_line_color", "#454B5F")[0]
        self._normal_line_number_color = get_color("normal_line_number_color", "#888888")[1]
        self._matched_line_number_color = get_color("matched_line_number_color", "#E53935")[1]
        self._new_line_number_color = get_color("new_line_number_color", "#43A047")[1]
        self._progress_line_number_color = get_color("progress_line_number_color", "#616161")[1]

        self._cached_colors_dirty = True
        self.viewport().update()  # 触发重绘

    def set_current_line_number(self, line_number: str):
        self.current_line_number = line_number

    def get_current_line_number(self):
        return self.current_line_number

    def _set_block_custom_data(self, cursor: QTextCursor, line_num: str, matched: bool):
        fmt = cursor.blockFormat()

        # 如果是空，直接清除属性
        if not line_num:
            fmt.clearProperty(PROP_LINE_NUM)
            fmt.clearProperty(PROP_MATCHED)
        else:
            fmt.setProperty(PROP_LINE_NUM, str(line_num))
            fmt.setProperty(PROP_MATCHED, bool(matched))

        cursor.setBlockFormat(fmt)

    def _get_block_custom_data(self, block: QTextBlock) -> Tuple[Optional[str], bool]:
        if not block.isValid():
            return None, False

        fmt = block.blockFormat()
        line_num = fmt.property(PROP_LINE_NUM)
        if line_num is not None:
            matched = bool(fmt.property(PROP_MATCHED))
            return line_num, matched

        return None, False

    def toggle_line_num(self):
        """
        设置是否显示行号区域
        """
        self._show_line_num = not self._show_line_num
        # 调用 updateLineNumberAreaWidth 来根据新的状态更新边距，从而显示或隐藏行号区域
        self.updateLineNumberAreaWidth(0)

    def lineNumberAreaWidth(self):
        # 如果开关为关闭状态，则直接返回 0，隐藏行号区域
        if not self._show_line_num:
            return 0

        digits = 1
        max_num = max(10000, self._max_line_num_val)
        while max_num >= 10:
            max_num /= 10
            digits += 1

        font = self.font()
        font.setPointSize(11)
        font_metrics = QFontMetrics(font)
        space = 15 + font_metrics.width("9") * digits

        return space

    def lineNumberAreaSizeHint(self):
        return self.lineNumberAreaWidth()

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        if self._cached_colors_dirty:
            self._qc_normal_num = QColor(self._normal_line_number_color)
            self._qc_matched_num = QColor(self._matched_line_number_color)
            self._qc_new_num = QColor(self._new_line_number_color)
            self._qc_progress_num = QColor(self._progress_line_number_color)
            self._cached_colors_dirty = False

        painter = QPainter(self.line_number_area)
        bg_color = self.viewport().palette().color(QPalette.Base)
        painter.fillRect(event.rect(), bg_color)

        normal_font = self.font()
        normal_font.setPointSize(11)

        progress_font = self.font()
        progress_font.setPointSize(9)

        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_text, matched = self._get_block_custom_data(block)

                if line_text == self._new_line_num_text:
                    painter.setFont(normal_font)
                    painter.setPen(self._qc_new_num)
                elif line_text and line_text.endswith("%"):
                    painter.setFont(progress_font)
                    painter.setPen(self._qc_progress_num)
                elif matched:
                    painter.setFont(normal_font)
                    painter.setPen(self._qc_matched_num)
                else:
                    painter.setFont(normal_font)
                    painter.setPen(self._qc_normal_num)

                painter.drawText(
                    0,
                    int(top),
                    self.line_number_area.width() - 5,
                    int(self.fontMetrics().height()),
                    Qt.AlignRight | Qt.AlignVCenter,
                    line_text,
                )
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()

    def _parse_line_prefix(cls, line: str) -> Tuple[str, str, bool]:
        """
        解析单行文本，分离前缀和纯文本
        返回: (纯文本, 行号字符串, 是否匹配)
        如果未匹配到标签，行号返回 ""
        """
        line_number_match = cls._LINE_PREFIX_PATTERN.search(line)
        if line_number_match:
            tag_type = line_number_match.group(1)
            line_num = line_number_match.group(2)
            clean_text = line_number_match.group(3)
            return clean_text, line_num, (tag_type == "匹配")

        progress_match = cls._MATCH_PROGRESS_PATTERN.search(line)
        if progress_match:
            tag_type = "行号"
            clean_text_1 = progress_match.group(1)
            line_num = progress_match.group(2)  # 这里的 line_num 换成 progress_str……
            clean_text_2 = progress_match.group(3)  # 这里只把中间的进度信息移除掉……
            return clean_text_1 + clean_text_2, line_num, tag_type

        return line, "", False

    def _build_line_prefix(self, block: QTextBlock) -> str:
        """
        根据 block 重构前缀标签
        """
        line_num, matched = self._get_block_custom_data(block)
        if line_num and line_num != self._new_line_num_text:
            if line_num.endswith("%"):
                return f"[进度：{line_num}]"

            tag = "匹配" if matched else "行号"
            return f"[{tag}：{line_num}]"

        return ""

    def load_raw_text(self, raw_text):
        """
        从搜索结果文本的行首标记 [行号：xxx] 或 [匹配：xxx] 提取出对应的行号信息
        设置到行号区域后，移除这些行首标记
        """
        clean_lines = []
        metadata = []
        max_line_num_val = 0

        for line in raw_text.splitlines():
            clean_text, line_num, matched = self._parse_line_prefix(line)
            clean_lines.append(clean_text)
            metadata.append((line_num, matched))

            if line_num and line_num.isdigit():
                max_line_num_val = max(max_line_num_val, int(line_num))

        # 尾随空行
        clean_lines.append("")
        metadata.append(("", False))

        # 1. 临时卸载高亮器
        self.highlighter.setDocument(None)  # 卸载，setPlainText 时不触发高亮

        try:
            # 2. 批量设文本
            old_line_number = self.current_line_number
            self.setPlainText("\n".join(clean_lines))

            # 3. 回填行号元数据
            block = self.document().firstBlock()
            temp_cursor = QTextCursor(self.document())
            temp_cursor.beginEditBlock()
            try:
                for line_num, matched in metadata:
                    if not block.isValid():
                        break
                    temp_cursor.setPosition(block.position())
                    self._set_block_custom_data(temp_cursor, line_num, matched)
                    block = block.next()
            finally:
                temp_cursor.endEditBlock()
        finally:
            # 4. 重新挂载高亮器 — 此时 userData 已全部就绪，高亮自动运行一次
            self.highlighter.setDocument(self.document())

        self._max_line_num_val = max_line_num_val
        self.document().clearUndoRedoStacks()
        self.updateLineNumberAreaWidth(0)

        self.rawTextLoaded.emit(old_line_number)

    def get_raw_text(self) -> str:
        """
        从编辑器的当前内容和 userData 重构原始文本（带 [标签]）
        """
        lines = []
        block = self.document().firstBlock()
        while block.isValid():
            prefix = self._build_line_prefix(block)
            block_text = block.text()

            if "进度：" in prefix:
                closing_bracket_index = block_text.find("】")
                if closing_bracket_index != -1:
                    # 将进度 prefix 插入到 "【匹配项：xxx】" 的后面
                    insert_position = closing_bracket_index + 1
                    new_line = block_text[:insert_position] + prefix + block_text[insert_position:]
                    lines.append(new_line)
                else:
                    # 如果是通过 replace_in_selection 或者 replace_all 来替换，涉及多行新增或删除时，
                    # 因为是直接插入大段新文本，和手动一个个替换不一样，会导致前缀（行号、进度等）位置错乱，
                    # 和实际行对不上，这时需要完全舍弃前缀，保存时才不会丢失内容
                    lines.append(block_text)
            else:
                lines.append(prefix + block_text)
            block = block.next()

        return "\n".join(lines)

    def contextMenuEvent(self, event):
        """
        如果设置了自定义菜单，则显示它；
        否则，调用父类的实现，这会正确地显示标准的默认菜单（复制、粘贴等）
        """
        if self.custom_menu:
            self.custom_menu.show_custom_context_menu(event)
        else:
            super().contextMenuEvent(event)

    def expand_selected_line_text(self):
        """
        将选中的跨行文本扩展到完整行，并返回新的光标和选中的文本

        Returns:
            tuple: 包含新的 QTextCursor 对象和选中的文本字符串
        """
        cursor = self.textCursor()
        start_pos = cursor.selectionStart()
        end_pos = cursor.selectionEnd()

        # 获取起始行和结束行的行号
        start_block = self.document().findBlock(start_pos)
        end_block = self.document().findBlock(end_pos)

        # 创建新的光标来设置全选范围
        new_cursor = QTextCursor(self.document())
        new_cursor.setPosition(start_block.position())
        new_cursor.setPosition(end_block.position() + end_block.length() - 1, QTextCursor.MoveMode.KeepAnchor)

        self.setTextCursor(new_cursor)

        return new_cursor, self.get_normalized_selected_text(new_cursor)

    def merge_selected_lines(self):
        """
        将选中的多行文本合并为一行，并保留第一行的原始前缀（行号和缩进）
        """
        cursor = self.textCursor()
        selected_text = self.get_normalized_selected_text(cursor)
        # 如果选择的文本行数大于 1，则走多行合并逻辑
        if len(selected_text.splitlines()) > 1:
            cursor, selected_text = self.expand_selected_line_text()
        else:
            # 当无选中文本或仅选中单行时，全选当前行和下一行
            # 当无选中文本时，全选当前行和下一行
            # 注意这里为了不受自动换行影响，应该用 block
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
            selected_text = self.get_normalized_selected_text(cursor)

        try:
            new_text = util.process_merge_lines(selected_text)
        except ValueError as e:
            logging.error(f"合并多行文本失败: {e}")
            return

        # 如果没有得到有效结果则中断
        if not new_text:
            return

        self.insert_and_highlight_chars(cursor, new_text)

    def undo(self):
        """重写系统 undo，确保无论是快捷键还是菜单触发都能被捕获"""
        has_undo_steps = self.document().isUndoAvailable()
        super().undo()
        self.undoPerformed.emit(has_undo_steps)

    def redo(self):
        """重写系统 redo"""
        has_redo_steps = self.document().isRedoAvailable()
        super().redo()
        self.redoPerformed.emit(has_redo_steps)

    def copy(self):
        """重写复制行为，去除特定的差异标记标签，只保留内容"""
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return

        selected_text = self.get_normalized_selected_text(cursor)
        modified_text = regex.sub(self._RM_OLD_TAG_PATTERN, r"", selected_text)
        modified_text = regex.sub(self._STRIP_DIFF_TAG_PATTERN, r"\1", modified_text)

        # 将处理后的文本写入系统剪贴板
        clipboard = QApplication.clipboard()
        clipboard.setText(modified_text)

    def copy_raw(self):
        super().copy()
        return

    def wheelEvent(self, event):
        # 检查是否按下了 Alt 键，下面的大部分逻辑都是试图实现“按下 Alt 键的同时允许滚动”
        has_alt = bool(event.modifiers() & Qt.AltModifier)

        # 1. 获取垂直方向的真实意图滚动值
        delta_y = event.angleDelta().y()
        # 如果按了 Alt，有些系统会把滚轮转化成横向信号 x()，我们把它抢回来变成 y()
        if has_alt and delta_y == 0:
            delta_y = event.angleDelta().x()

        # 2. 如果没有滚动值（比如只是轻微误触），交给父类
        if delta_y == 0:
            super().wheelEvent(event)
            return

        # ==========================================
        # 分支 A：关闭了平滑滚动
        # ==========================================
        if not self._smooth_scrolling:
            if has_alt:
                # 【按了 Alt】：必须手动接管，否则底层会拒绝垂直滚动
                vbar = self.verticalScrollBar()
                # 读取系统设置的每次滚动行数（默认通常是 3）
                sys_lines = QApplication.wheelScrollLines()
                steps = -(delta_y / 120.0) * vbar.singleStep() * sys_lines
                vbar.setValue(int(vbar.value() + steps))
                event.accept()
            else:
                # 【没按 Alt】：完美交还给底层 C++，保留触控板高精度等所有原生特性
                super().wheelEvent(event)
            return

        # ==========================================
        # 分支 B：开启了平滑滚动
        # ==========================================
        # 此时拿到的 delta_y 已经是修复了 Alt 键转横向 bug 之后的值
        num_degrees = delta_y / 8.0
        num_steps = num_degrees / 15.0

        # 累加速度
        self._scroll_velocity -= num_steps * 0.5
        # 限制最大速度
        self._scroll_velocity = max(-2.0, min(2.0, self._scroll_velocity))

        if not self._scroll_timer.isActive():
            self._scroll_timer.start()

        event.accept()

    def _update_scroll(self):
        scrollbar = self.verticalScrollBar()

        # 将速度加到余数中
        self._scroll_remainder += self._scroll_velocity

        # 计算可以滚动的“整数行数”
        # int() 会直接切断小数，这会导致正负数方向处理不一致
        # 手动处理：只有积累超过 1.0 或 小于 -1.0 时才滚动
        steps_to_scroll = 0
        if self._scroll_remainder >= 1.0:
            steps_to_scroll = int(self._scroll_remainder)
            self._scroll_remainder -= steps_to_scroll
        elif self._scroll_remainder <= -1.0:
            steps_to_scroll = int(self._scroll_remainder)
            self._scroll_remainder -= steps_to_scroll

        # 如果有行数需要滚动，则应用
        if steps_to_scroll != 0:
            current_val = scrollbar.value()
            scrollbar.setValue(current_val + steps_to_scroll)

        # 摩擦力减速
        self._scroll_velocity *= self._friction

        # 停止判断
        if abs(self._scroll_velocity) < self._min_velocity:
            self._scroll_velocity = 0
            self._scroll_remainder = 0
            self._scroll_timer.stop()

    def keyPressEvent(self, event: QKeyEvent):
        """
        重写此方法以处理自定义的按键事件
        """
        # 优先处理替换快捷键（如果已启用）
        if self.replace_shortcuts_enabled:
            key_map = {
                Qt.Key_1: 0,
                Qt.Key_2: 1,
                Qt.Key_3: 2,
                Qt.Key_4: 3,
                Qt.Key_5: 4,
            }
            if event.key() in key_map:  # 根据索引值替换
                self.replaceByListIndex.emit(key_map[event.key()])
                return

            if event.key() == Qt.Key_6:  # 数字键 6 用于撤销
                self.undo()
                return

        # 检查是否是回车键
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._insert_custom_newline()
            return

        # 拦截标准撤销快捷键
        if event.matches(QKeySequence.Undo):
            self.undo()
            return

        # 拦截标准重做快捷键 (Ctrl+Y 或 Ctrl+Shift+Z)
        if event.matches(QKeySequence.Redo):
            self.redo()
            return

        # 拦截 Ctrl+C，确保调用自定义的 copy 方法
        if event.matches(QKeySequence.Copy):
            self.copy()
            return

        # 拦截 Ctrl+Shift+C，调用原始的复制方法（保留所有标签）
        if event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier) and event.key() == Qt.Key_C:
            self.copy_raw()
            return

        if event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            # 尝试执行 Emmet 展开
            expanded = self._try_emmet_expand()
            if expanded:
                return

        super().keyPressEvent(event)

    def _insert_custom_newline(self):
        """
        处理回车键逻辑：插入一个带前缀的自定义新行
        整个操作是原子的（可一次性撤销）
        """
        cursor = self.textCursor()

        # 使用 beginEditBlock/endEditBlock 保证操作的原子性
        cursor.beginEditBlock()
        try:
            current_text = cursor.block().text()
            space_str = ""
            match = regex.search(r"([ \u3000]*)", current_text)
            if match:
                space_str = match.group(1)  # 例如 "  "

            cursor_at_block_end = cursor.atBlockEnd()
            text_ends_with_p = current_text.endswith("</p>")

            if text_ends_with_p:  # html 文件
                if not cursor_at_block_end:
                    # 情况 1：在段落中间回车，例如 <p>aaa|bbb</p>
                    # 先闭合当前行，再换行并开始新段落
                    cursor.insertText("</p>")
                    cursor.insertText(f"\n{space_str}<p>")
                else:
                    # 情况 2：在段落末尾回车，例如 <p>aaa</p>|
                    # 一次性插入新行和完整的 <p></p> 标签
                    cursor.insertText(f"\n{space_str}<p></p>")
                    # 然后将光标向左移动，定位到新行的标签中间 <p>|</p>
                    cursor.movePosition(cursor.MoveOperation.Left, cursor.MoveMode.MoveAnchor, 4)
            else:
                # 普通行，或非 html 文件，只继承缩进
                cursor.insertText(f"\n{space_str}")

            # 换行后光标正处于新行上，清除新行的行号格式，使其变成“新行”
            fmt = cursor.blockFormat()
            fmt.setProperty(PROP_LINE_NUM, self._new_line_num_text)
            fmt.setProperty(PROP_MATCHED, False)
            cursor.setBlockFormat(fmt)

        finally:
            # 确保即使出错也能结束编辑块，避免损坏撤销栈
            cursor.endEditBlock()
            self.setTextCursor(cursor)

    def _try_emmet_expand(self):
        """
        尝试获取光标前的缩写并使用 Emmet 展开它
        """
        text_edit = self
        cursor = text_edit.textCursor()

        if cursor.hasSelection():
            return False

        abbreviation = self._get_abbreviation_before_cursor(cursor)

        if not abbreviation:
            return False

        try:
            config = {"options": {"output.indent": " " * 2}}
            expanded_html = emmet.expand(abbreviation, config=config)
            # 如果展开结果和原文一样，说明不是有效的缩写
            if expanded_html == abbreviation:
                return False

            # 先选中并替换原文
            cursor.movePosition(QTextCursor.Left, QTextCursor.MoveMode.KeepAnchor, len(abbreviation))
            text_edit.insert_and_highlight_chars(cursor, expanded_html)

            # 获取编辑器当前的光标（最新的光标，忽略 insert_text_and_set_bg_color 中的光标移动和选区）
            # 使用“绝对定位”，它现在可靠地位于插入文本的末尾
            current_cursor = text_edit.textCursor()
            insertion_end_pos = current_cursor.position()
            insertion_start_pos = insertion_end_pos - len(expanded_html)

            # 1. 优先处理：将光标移动到 src="" 或 href="" 的引号内部
            src_pos_relative = expanded_html.find('src=""')
            href_pos_relative = expanded_html.find('href=""')

            target_pos_absolute = -1

            # 确定哪个属性先出现，并计算其绝对目标位置
            if src_pos_relative != -1 and (href_pos_relative == -1 or src_pos_relative < href_pos_relative):
                # src 在前，或只有 src
                target_pos_absolute = insertion_start_pos + src_pos_relative + len('src="')
            elif href_pos_relative != -1:
                # href 在前，或只有 href
                target_pos_absolute = insertion_start_pos + href_pos_relative + len('href="')

            if target_pos_absolute != -1:
                # 如果找到了目标属性，直接跳转到计算好的绝对位置
                current_cursor.setPosition(target_pos_absolute)
                text_edit.setTextCursor(current_cursor)

            # 2. 次要处理：对于 div{text} 这种情况，光标已在末尾，无需移动
            elif "{" in abbreviation:
                pass

            # 3. 常规处理：将光标移动到标签对的中间，例如 <div></div> -> <div>|</div>
            elif expanded_html.endswith(">"):
                tag_parts = expanded_html.rsplit("</", 1)
                if len(tag_parts) == 2:
                    # 计算闭合标签的长度，例如 "</div>" 的长度
                    end_tag_len = len(tag_parts[1]) + 2
                    # 目标位置 = 插入终点 - 闭合标签长度
                    target_pos_absolute = insertion_end_pos - end_tag_len
                    current_cursor.setPosition(target_pos_absolute)
                    text_edit.setTextCursor(current_cursor)

            text_edit.setFocus()

            return True
        except Exception as e:
            return False

    def _get_abbreviation_before_cursor(self, cursor):
        pos = cursor.position()
        text = self.toPlainText()
        start = pos - 1

        valid_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.#-[]{}*+>"

        while start >= 0:
            char = text[start]
            if char in valid_chars:
                start -= 1
            else:
                break

        return text[start + 1 : pos]

    def mouseReleaseEvent(self, event: QMouseEvent):
        """处理鼠标侧键的前进/后退"""
        if event.button() == Qt.XButton1:  # Back button
            self.navigate_back()
        elif event.button() == Qt.XButton2:  # Forward button
            self.navigate_forward()

        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        """
        重写绘制事件：先绘制当前行背景，再绘制文字
        这样文字的字符格式背景会覆盖在行背景之上
        而不会像 extraSelections 方式覆盖掉文字本身的背景颜色
        """
        # 先让父类绘制所有内容（包括文字和文字背景）
        super().paintEvent(event)

        # 然后在当前行上叠加一层半透明高亮
        painter = QPainter(self.viewport())

        # 获取当前光标所在块的几何信息
        block = self.textCursor().block()
        block_rect = self.blockBoundingGeometry(block).translated(self.contentOffset())

        # 扩展到整个视口宽度
        highlight_rect = QRectF(0, block_rect.top(), self.viewport().width(), block_rect.height())

        # 使用半透明颜色叠加
        highlight_color = QColor(self._cur_line_color)
        # 透明度 0-255，越小越透明。这里设置成极透明，因此配置中的颜色要很极端才能看出高亮
        highlight_color.setAlpha(25)

        painter.fillRect(highlight_rect, highlight_color)
        painter.end()

    def smart_scroll(self):
        # 智能滚动逻辑
        viewport_height = self.viewport().height()
        # 获取当前光标（即选区末尾）相对于视口的矩形
        current_cursor_rect_in_viewport = self.cursorRect()

        # 定义舒适区的上下边界（在视口坐标系中）
        comfort_top = viewport_height * self._COMFORT_ZONE_MARGIN_FACTOR
        comfort_bottom = viewport_height * (1 - self._COMFORT_ZONE_MARGIN_FACTOR)

        # 获取选区第一行和最后一行的顶部和底部在视口中的位置
        # 为了简化，这里主要关注光标（选区末尾）所在行的位置
        # 如果匹配项本身很高，可能需要更复杂的逻辑来判断整个匹配项的可见性
        selection_line_top_in_viewport = current_cursor_rect_in_viewport.top()
        selection_line_bottom_in_viewport = current_cursor_rect_in_viewport.bottom()

        # 判断光标（选区末尾）是否在舒适区之外
        # is_too_high: 光标行的顶部在舒适区之上 (或者完全在视口之上)
        is_too_high = selection_line_top_in_viewport < comfort_top
        # is_too_low: 光标行的底部在舒适区之下 (或者完全在视口之下)
        is_too_low = selection_line_bottom_in_viewport > comfort_bottom
        # is_fully_off_screen_top: 光标行的底部在视口顶部之上 (完全不可见)
        is_fully_off_screen_top = selection_line_bottom_in_viewport < 0
        # is_fully_off_screen_bottom: 光标行的顶部在视口底部之下 (完全不可见)
        is_fully_off_screen_bottom = selection_line_top_in_viewport > viewport_height

        if is_fully_off_screen_top or is_fully_off_screen_bottom or is_too_high or is_too_low:
            # 如果选区末尾（光标）完全移出屏幕，或超出了舒适区，则居中显示
            self.centerCursor()
        else:
            # 如果选区末尾（光标）在舒适区内，则仅确保其可见（最小滚动）
            self.ensureCursorVisible()

    def _on_cursor_position_changed(self):
        """
        光标位置改变时触发
        1. 更新当前行号
        2. 记录光标历史，用于前进/后退
        3. 实现光标在特定标签边缘的“吸附”效果
        """
        cursor = self.textCursor()

        # 1. 更新当前行号
        self._update_current_line_number(cursor.block())

        # 2. 记录光标历史
        self._record_cursor_history(cursor)

        # 3. 处理标签吸附逻辑
        self._handle_tag_snapping(cursor)

    def _handle_tag_snapping(self, cursor: QTextCursor):
        """
        处理光标吸附效果：防止光标落在标签结构符 <［o: ］> 中间。
        此方法在光标位置改变时调用，确保结构安全性。
        """
        if self._adjusting_cursor or cursor.hasSelection():
            return

        block = cursor.block()
        text = block.text()
        pos_in_block = cursor.positionInBlock()

        for match in self._TAG_PATTERN.finditer(text):
            start = util.py_to_qt_index(match.start(), text)
            end = util.py_to_qt_index(match.end(), text)

            if start < pos_in_block < end:
                content_start = util.py_to_qt_index(match.start(2), text)
                content_end = util.py_to_qt_index(match.end(2), text)

                new_pos_in_block = pos_in_block
                if pos_in_block < content_start:
                    new_pos_in_block = content_start
                elif pos_in_block > content_end:
                    new_pos_in_block = content_end

                if new_pos_in_block != pos_in_block:
                    self._adjusting_cursor = True
                    new_cursor = self.textCursor()
                    new_cursor.setPosition(block.position() + new_pos_in_block)
                    self.setTextCursor(new_cursor)
                    self._adjusting_cursor = False
                break

    def get_line_num_from_block(self, block: QTextBlock) -> Optional[str]:
        """从给定的 QTextBlock 中安全地提取行号"""
        if not block.isValid():
            return None

        line_num, _ = self._get_block_custom_data(block)

        # 存在、非默认值、且必须是数字
        if line_num and line_num != self._new_line_num_text and line_num.isdigit():
            return line_num

        return None

    def _update_current_line_number(self, start_block: QTextBlock):
        """根据当前光标所在块更新 self.current_line_number 属性"""
        line_num = self.get_line_num_from_block(start_block)
        if line_num:
            self.current_line_number = line_num
            return

        # 如果当前行没有行号，则向后和向前查找
        found_line_num = None
        search_limit = 30  # 避免扫描整个文档

        # 1. 向前查找 (look forward)
        temp_block = start_block.next()
        count = 0
        while temp_block.isValid() and count < search_limit:
            line_num = self.get_line_num_from_block(temp_block)
            if line_num:
                found_line_num = line_num
                break
            temp_block = temp_block.next()
            count += 1

        # 2. 如果向前找不到，则向后查找 (look backward)
        if not found_line_num:
            temp_block = start_block.previous()
            count = 0
            while temp_block.isValid() and count < search_limit:
                line_num = self.get_line_num_from_block(temp_block)
                if line_num:
                    found_line_num = line_num
                    break
                temp_block = temp_block.previous()
                count += 1

        if found_line_num != None:
            self.current_line_number = found_line_num

    def _record_cursor_history(self, cursor: QTextCursor):
        """记录光标历史，用于前进/后退"""
        # 如果是代码正在导航，则忽略
        if self.m_is_navigating:
            return

        document = self.document()
        old_cursor = QTextCursor(document)

        # 检查 self.m_last_cursor_pos 是否有效，如果无效则重置为 0
        if self.m_last_cursor_pos > document.characterCount() or self.m_last_cursor_pos < 0:
            self.m_last_cursor_pos = 0

        old_cursor.setPosition(self.m_last_cursor_pos)

        # 检查行号变化是否超过阈值
        if abs(cursor.blockNumber() - old_cursor.blockNumber()) >= self._KEYBOARD_JUMP_THRESHOLD_LINES:
            self._record_position(self.m_last_cursor_pos)

        # 更新最后的位置
        self.m_last_cursor_pos = cursor.position()

    def _record_position(self, position: int):
        """
        记录一个新的光标位置到历史中
        """
        # 如果正在导航，则不记录
        if self.m_is_navigating:
            return

        # 如果新位置和栈顶位置相同，则不记录
        if self.m_cursor_history_back and self.m_cursor_history_back[-1] == position:
            return

        self.m_cursor_history_back.append(position)

        # 发生新的跳转时，清空前进历史
        if self.m_cursor_history_forward:
            self.m_cursor_history_forward.clear()

        # 限制历史记录的大小，防止内存无限增长
        if len(self.m_cursor_history_back) > 40:
            self.m_cursor_history_back.pop(0)

    def mouseMoveEvent(self, event: QMouseEvent):
        """处理鼠标移动，实现悬停显示标签编辑器"""
        # 1. 物理位置校验：如果鼠标在屏幕上的坐标根本没动（例如只是在滚动滚轮），直接拦截
        if self.m_last_screen_pos == event.pos():
            return
        self.m_last_screen_pos = event.pos()

        # 如果弹窗正在显示，且鼠标就在弹窗矩形范围内，直接返回
        if self.tag_editor.isVisible():
            if self.tag_editor.geometry().contains(event.pos()):
                return

        super().mouseMoveEvent(event)

        # 2. 获取文档位置
        cursor = self.cursorForPosition(event.pos())
        current_pos = cursor.position()

        # 文档位置没变也不重跑逻辑
        if current_pos == self.m_last_hover_pos:
            return
        self.m_last_hover_pos = current_pos

        # 触发检测逻辑
        self._detect_tag_at_cursor(cursor)

    def _detect_tag_at_cursor(self, cursor: QTextCursor):
        """检测当前位置是否有标签，并管理计时器"""
        # 基础过滤条件
        if QApplication.mouseButtons() != Qt.NoButton or self.textCursor().hasSelection():
            self.hover_timer.stop()
            return

        block = cursor.block()
        text = block.text()
        pos_in_block = cursor.positionInBlock()

        found_tag_data = None

        # 预解析 n 标签对应的 o 内容
        n_to_o_content_map = {}
        for m in self._OLD_NEW_TAG_PATTERN.finditer(text):
            n_tag_start = m.start(3) - 2
            n_to_o_content_map[n_tag_start] = m.group(2)

        # 遍历寻找标签
        for match in self._TAG_PATTERN.finditer(text):
            start = util.py_to_qt_index(match.start(), text)
            end = util.py_to_qt_index(match.end(), text)

            if start <= pos_in_block <= end:
                # --- 视觉位置精确校验 (适配自动换行与行尾空白) ---
                # 获取鼠标指向的这个具体字符位置的视觉矩形（一根竖线）
                char_rect = self.cursorRect(cursor)

                # 计算鼠标当前 X 坐标与该字符视觉 X 坐标的绝对差值
                # 20 像素大约是 1.5 个汉字的宽度。如果差值超过这个数，说明鼠标在行尾空白区
                if abs(self.m_last_screen_pos.x() - char_rect.x()) > 20:
                    continue

                tag_type = match.group(1)
                # 过滤不需要显示的类型
                if tag_type == "o":
                    break

                content_text = match.group(2)
                content_start = util.py_to_qt_index(match.start(2), text)
                content_end = util.py_to_qt_index(match.end(2), text)

                popup_text = content_text
                if tag_type == "n" and match.start() in n_to_o_content_map:
                    popup_text = n_to_o_content_map[match.start()]

                # 封装本次捕获到的标签信息
                found_tag_data = {
                    "block": block,
                    "tag_start": start,
                    "tag_end": end,
                    "content_start": content_start,
                    "content_end": content_end,
                    "tag_type": tag_type,
                    "popup_text": popup_text,
                }
                break

        if found_tag_data:
            # 如果当前已经在显示同一个标签的编辑器，就不重新计时
            new_info = (block.blockNumber(), found_tag_data["tag_start"], found_tag_data["tag_end"])
            if self.tag_editor.isVisible() and self._current_edit_info and self._current_edit_info[:3] == new_info:
                self.hover_timer.stop()
                return

            # 发现新标签，存储数据并启动/重启计时器
            self._pending_tag_data = found_tag_data
            if not self.hover_timer.isActive():
                self.hover_timer.start(100)  # 设置延迟，单位为毫秒
        else:
            # 没碰到标签，停止计时，并按需隐藏
            self.hover_timer.stop()
            self._pending_tag_data = None
            # 如果弹窗内的文本框已经有焦点了（用户在输入或准备输入），绝对不能隐藏
            if self.tag_editor.isVisible() and not self.tag_editor.text_edit.hasFocus():
                self.tag_editor.hide()

    def _on_hover_timer_timeout(self):
        """计时器到时，执行显示逻辑"""
        if not self._pending_tag_data:
            return

        d = self._pending_tag_data
        # 只有在计时器结束时才执行原来 _handle_tag_hover 里的 UI 操作
        # 例如同步光标位置（可选）
        target_pos = d["block"].position() + d["content_start"]
        if self.textCursor().position() != target_pos:
            new_cursor = self.textCursor()
            new_cursor.setPosition(target_pos)
            self._adjusting_cursor = True
            self.setTextCursor(new_cursor)
            self._adjusting_cursor = False

        # 显示编辑器
        self._show_tag_editor(
            d["block"],
            d["tag_start"],
            d["tag_end"],
            d["content_start"],
            d["content_end"],
            d["tag_type"],
            d["popup_text"],
        )
        self._pending_tag_data = None

    def _show_tag_editor(self, block, tag_start, tag_end, content_start, content_end, tag_type, content_text):
        """在光标位置显示悬浮编辑框"""
        if tag_type in "o":  # 灰色旧内容不显示
            return

        # 将所有的坐标信息都记录下来
        new_edit_info = (block.blockNumber(), tag_start, tag_end, content_start, content_end, tag_type)

        if self.tag_editor.isVisible() and self._current_edit_info == new_edit_info:
            return

        self._current_edit_info = new_edit_info

        # 1. 获取光标矩形区域
        cursor = self.textCursor()
        cursor.setPosition(block.position() + content_start)
        rect = self.cursorRect(cursor)

        # 2. 智能计算多行弹窗尺寸
        text_len = len(content_text)

        # 基础最小宽度，保证按钮能放得下
        base_width = 200
        # 如果字很多，让框变宽一点 (最大不超过 400)
        target_width = min(400, max(base_width, self.fontMetrics().width(content_text) + 40))

        # 根据字符长度粗略估算需要的高度（假设每行大概 15~20 个汉字）
        estimated_lines = text_len // 15 + 1
        # 单行约 20px 高，加上 padding 和底部按钮区(约 40px)
        # 最小高度 80 (单行)，最大高度 200 (长文本靠滚动条)
        target_height = min(200, max(100, estimated_lines * 20 + 60))

        self.tag_editor.resize(target_width, target_height)

        # 3. 计算最佳位置，防止边缘截断
        viewport_rect = self.viewport().rect()

        # 设定向上偏移量（像素），覆盖一点当前行的文字
        # 避免出现连续多行的差异时反复触发弹窗互相干扰
        overlap_y = 5

        pos_x = rect.left()
        # 将弹窗底部基准线往上提
        pos_y = rect.bottom() - overlap_y

        # 处理右侧边缘截断
        if pos_x + target_width > viewport_rect.right():
            pos_x = viewport_rect.right() - target_width
            pos_x = max(0, pos_x)

        # 处理底部边缘截断（如果下方放不下，则翻转到上方）
        if pos_y + target_height > viewport_rect.bottom():
            # 弹窗翻转到上方显示
            pos_y = rect.top() - target_height + overlap_y
            pos_y = max(0, pos_y)

        # 反转按钮文字
        if tag_type == "d":
            self.tag_editor.btn_confirm.setText("恢复")
        else:
            self.tag_editor.btn_confirm.setText("采用")

        # 4. 显示与激活
        self.tag_editor.setText(content_text)
        self.tag_editor.move(pos_x, pos_y)
        self.tag_editor.show()
        self.tag_editor.setFocus()
        self.tag_editor.selectAll()

    def _apply_tag_edit(self, new_text, remove=False):
        """将编辑框中的新内容应用回主文本"""
        if not self._current_edit_info:
            return

        # 解包所有的坐标信息
        block_num, tag_start, tag_end, content_start, content_end, tag_type = self._current_edit_info
        block = self.document().findBlockByNumber(block_num)

        if not block.isValid():
            return

        self._current_edit_info = None

        cursor = QTextCursor(self.document())  # 创建一个指向目标位置的新光标

        if tag_type == "d":
            # 反转操作方向
            new_text = f"<［a:{new_text}］>"
        elif tag_type == "n":
            # 为 n 时将原来的 o 和 n 标签全部删除，然后插入新标签结构
            new_text = f"<［n:{new_text}］>"

        # 移除所有内容
        if remove:
            new_text = ""

        # 判断用户编辑后的内容是否为空
        if new_text and tag_type != "d" and tag_type != "n":
            # 1. 有内容，且不是删除或还原动作：只选中内部的内容部分，保留外围标签
            cursor.setPosition(block.position() + content_start)
            cursor.setPosition(block.position() + content_end, QTextCursor.KeepAnchor)
        else:
            # 2. 无内容，或是删除/还原动作：选中整个标签范围（连同括号结构一起删除）
            selection_start = block.position() + tag_start
            selection_end = block.position() + tag_end

            # 如果 tag_type 是 n，则反向寻找最近的 o 标签，连同 o 标签一起删除
            if tag_type == "n":
                last_o_tag_match = util.find_last_match_by_regex(
                    self._RM_OLD_TAG_PATTERN, block.text(), tag_start, 5000
                )
                if last_o_tag_match:
                    # 检查找到的 o 标签与当前的 n 标签之间是否有其他内容
                    gap_text = block.text()[last_o_tag_match.end():tag_start]
                    # 如果中间没有其他文本（紧挨着），或者是纯空格，才视为同一对并连带删除
                    if gap_text == "" or gap_text.isspace():
                        selection_start = block.position() + last_o_tag_match.start()

            # 判断是否整行都是 <［a:］> 标签的内容，如果是则删除整行
            if not new_text:
                # 计算选中范围在当前段落（行）中的相对起止位置
                rel_start = selection_start - block.position()
                rel_end = selection_end - block.position()
                block_text = block.text()

                # 获取要删除的标签前面和后面的文本
                prefix = block_text[:rel_start]
                suffix = block_text[rel_end:]

                # 判断前面和后面是否都只有（或没有）连续的全/半角空格
                if regex.fullmatch(r'[ 　]*', prefix) and regex.fullmatch(r'[ 　]*', suffix):
                    # 如果条件成立，说明这一行只有空格和这个标签，将选中范围扩大到整行
                    if block.next().isValid():
                        # 不是最后一行，选中当前行首到下一行行首（包含当前行的换行符）
                        selection_start = block.position()
                        selection_end = block.next().position()
                    else:
                        # 是最后一行，选中当前整行
                        selection_start = block.position()
                        selection_end = block.position() + block.length()
                        # 连带删掉上一行的换行符避免留白：
                        if block.previous().isValid():
                            selection_start = block.previous().position() + block.previous().length() - 1

            cursor.setPosition(selection_start)
            cursor.setPosition(selection_end, QTextCursor.KeepAnchor)

        self._adjusting_cursor = True
        cursor.insertText(new_text)  # 无内容时 new_text 是 ""，等于直接删除了整个标签
        self._adjusting_cursor = False

        # 此时 cursor 已经位于新插入文本的末尾
        # 调用 setTextCursor 将这个位置同步给主编辑器
        self.setTextCursor(cursor)

        # 将焦点还回主编辑器
        self.setFocus()

    def _cancel_tag_edit(self):
        """取消编辑，焦点返回主文本"""
        self.setFocus()
        self._current_edit_info = None

    def navigate_back(self):
        """
        导航到上一个光标位置
        """
        if not self.m_cursor_history_back:
            return

        self.m_is_navigating = True

        # 记录导航前的光标位置
        original_pos = self.textCursor().position()

        # 将当前位置存入前进栈
        self.m_cursor_history_forward.append(original_pos)

        # 从后退栈弹出一个位置
        nav_pos = self.m_cursor_history_back.pop()

        # 检查位置是否有效，无效则不跳转
        if nav_pos >= self.document().characterCount():
            self.m_is_navigating = False
            return

        # 选中从原始位置到导航位置的文本
        selection_cursor = self.textCursor()
        selection_cursor.setPosition(original_pos, QTextCursor.MoveAnchor)
        selection_cursor.setPosition(nav_pos, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(selection_cursor)
        self.smart_scroll()

        # 导航结束后，将标志位设回 False，并更新 last_pos
        self.m_is_navigating = False
        self.m_last_cursor_pos = nav_pos
        self.setFocus()

    def navigate_forward(self):
        """
        导航到下一个光标位置
        """
        if not self.m_cursor_history_forward:
            return

        self.m_is_navigating = True

        # 记录导航前的光标位置
        original_pos = self.textCursor().position()

        # 将当前位置压回后退栈
        self.m_cursor_history_back.append(original_pos)

        # 从前进栈弹出一个位置
        nav_pos = self.m_cursor_history_forward.pop()

        # 检查位置是否有效，无效则不跳转
        if nav_pos >= self.document().characterCount():
            self.m_is_navigating = False
            return

        # 选中从原始位置到导航位置的文本
        selection_cursor = self.textCursor()
        selection_cursor.setPosition(original_pos, QTextCursor.MoveAnchor)
        selection_cursor.setPosition(nav_pos, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(selection_cursor)
        self.smart_scroll()

        # 导航结束后，将标志位设回 False，并更新 last_pos
        self.m_is_navigating = False
        self.m_last_cursor_pos = nav_pos
        self.setFocus()

    def duplicate_current_lines(self):
        """
        复制当前行或选中的多行，并在其后粘贴
        """
        cursor = self.textCursor()
        cursor.beginEditBlock()  # 开始一个可撤销的原子操作块

        try:
            # 1. 保存原始选区位置
            original_selection_start = cursor.selectionStart()
            original_selection_end = cursor.selectionEnd()
            has_selection = cursor.hasSelection()

            # 2. 确定要复制的文本块范围
            start_block = self.document().findBlock(original_selection_start)
            end_block = self.document().findBlock(original_selection_end)

            # 如果选区在块的开头结束，并且不是起始块，则不包括该块
            if has_selection and end_block.position() == original_selection_end and start_block != end_block:
                end_block = end_block.previous()

            # 如果没有选区，则复制当前行
            if not has_selection:
                end_block = start_block

            # 3. 计算选区相对于起始块的偏移量
            # 这对于后续在新位置恢复选区至关重要
            relative_selection_start = original_selection_start - start_block.position()
            relative_selection_end = original_selection_end - start_block.position()

            # 4. 收集要复制的行的文本
            text_to_duplicate = []
            block = start_block
            while True:
                text_to_duplicate.append(block.text())
                if block == end_block:
                    break
                block = block.next()

            full_text = "\n".join(text_to_duplicate)

            # 5. 在最后一个选定块的末尾插入复制的文本
            insert_cursor = QTextCursor(end_block)
            insert_cursor.movePosition(QTextCursor.EndOfLine)
            insert_cursor.insertText("\n" + full_text)

            # 6. 计算并应用新的选区
            # 新内容的起始位置在原结束块的下一块
            new_content_start_block = end_block.next()
            new_content_start_pos = new_content_start_block.position()

            # 根据新内容的起始位置和之前保存的相对偏移量，计算出新选区的绝对位置
            new_selection_start = new_content_start_pos + relative_selection_start
            new_selection_end = new_content_start_pos + relative_selection_end

            # 创建一个新光标并设置新选区
            new_cursor = QTextCursor(self.document())
            new_cursor.setPosition(new_selection_start)
            new_cursor.setPosition(new_selection_end, QTextCursor.KeepAnchor)
            self.setTextCursor(new_cursor)

        finally:
            cursor.endEditBlock()  # 结束操作块

    def insert_and_highlight_chars(
        self, cursor: QTextCursor, new_text: str, select_new_text: bool = True
    ) -> QTextCursor:
        """
        插入文本。如果文本发生变化，则设置绿色背景高亮（仅字符）
        """
        cur_text = cursor.selectedText()

        # 准备字符格式
        char_format = QTextCharFormat()
        if cur_text != new_text:  # 只有内容不一致时才上色
            bg_color, fg_color = self._new_chars_color
            char_format.setBackground(QColor(bg_color))
            char_format.setForeground(QColor(fg_color))

        # 调用通用方法：只传字符格式，不传块格式
        return self._insert_with_formatting(
            cursor=cursor,
            new_text=new_text,
            select_new_text=select_new_text,
            char_format=char_format,
            block_format=None,
        )

    def insert_and_highlight_lines(
        self, cursor: QTextCursor, new_text: str, select_new_text: bool = True
    ) -> QTextCursor:
        """
        插入文本。强制设置所涉及的整行背景色和字符背景色
        """
        # 1. 准备字符格式 (文字本体)
        char_format = QTextCharFormat()
        bg_color, fg_color = self._new_lines_color
        char_format.setBackground(QColor(bg_color))
        char_format.setForeground(QColor(fg_color))

        # 2. 准备块格式 (整行背景)
        block_format = QTextBlockFormat()
        block_format.setBackground(QColor(bg_color))

        # 调用通用方法：同时传入字符格式和块格式
        return self._insert_with_formatting(
            cursor=cursor,
            new_text=new_text,
            select_new_text=select_new_text,
            char_format=char_format,
            block_format=block_format,
        )

    def _insert_with_formatting(
        self,
        cursor: QTextCursor,
        new_text: str,
        select_new_text: bool,
        char_format: QTextCharFormat = None,
        block_format: QTextBlockFormat = None,
    ) -> QTextCursor:
        """
        [内部通用方法] 在原子操作中插入文本，并可选地应用字符格式和块格式
        会自动解析 [行号：xx] 和 [匹配：xx] 前缀
        """
        cursor.beginEditBlock()
        try:
            start_pos = cursor.selectionStart()

            # 1. 记忆区：收集被替换区域原有的行号信息，用于新文本无标签时“继承”行号
            existing_user_data = []
            if cursor.hasSelection():
                sel_start = cursor.selectionStart()
                sel_end = cursor.selectionEnd()
                curr_block = self.document().findBlock(sel_start)
                end_block = self.document().findBlock(sel_end)

                while curr_block.isValid():
                    line_num, matched = self._get_block_custom_data(curr_block)
                    if line_num:
                        existing_user_data.append((line_num, matched))
                    else:
                        existing_user_data.append(("", False))

                    if curr_block == end_block:
                        break
                    curr_block = curr_block.next()

            clean_lines = []
            metadata = []

            # 2. 解析 new_text，并应用“继承”逻辑
            for i, line in enumerate(new_text.splitlines()):
                clean_text, line_num, matched = self._parse_line_prefix(line)

                # 若当前行解析不出行号，且对应的位置有旧行号，则继承之
                if not line_num and i < len(existing_user_data):
                    old_line_num, old_matched = existing_user_data[i]
                    line_num, matched = old_line_num, old_matched

                clean_lines.append(clean_text)
                metadata.append((line_num, matched))

                if line_num and line_num.isdigit():
                    self._max_line_num_val = max(self._max_line_num_val, int(line_num))

            clean_text = "\n".join(clean_lines)

            # Python 的 splitlines() 会吞掉末尾换行符，如果原文本有换行，这里补回来
            if new_text.endswith(("\n", "\r")):
                clean_text += "\n"

            # 3. 插入纯文本 (应用字符格式)
            if char_format:
                cursor.insertText(clean_text, char_format)
            else:
                cursor.insertText(clean_text)

            end_pos = cursor.position()

            # 4. 强制重新应用块格式和元数据
            block = self.document().findBlock(start_pos)
            temp_cursor = QTextCursor(self.document())
            for line_num, matched in metadata:
                if not block.isValid():
                    break

                temp_cursor.setPosition(block.position())
                if line_num:
                    self._set_block_custom_data(temp_cursor, line_num, matched)
                else:
                    self._set_block_custom_data(temp_cursor, "", False)

                block = block.next()

            # 5. 应用整行块格式（如果提供）
            if block_format:
                temp_cursor = QTextCursor(self.document())
                temp_cursor.setPosition(start_pos)
                temp_cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)
                temp_cursor.mergeBlockFormat(block_format)

            # 6. 恢复选择
            if select_new_text:
                cursor.setPosition(start_pos, QTextCursor.MoveAnchor)
                cursor.setPosition(end_pos, QTextCursor.MoveMode.KeepAnchor)

        except Exception as e:
            logging.error(f"文本插入操作失败: {e}")
        finally:
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            self.setFocus()

        self.smart_scroll()
        self.updateLineNumberAreaWidth(0)

        return cursor

    def get_normalized_selected_text(self, cursor: QTextCursor) -> str:
        """统一处理选区文本的换行符，选中区域会采用特殊换行符，这里要再转一次……"""
        return cursor.selectedText().replace("\u2029", "\n")

    def get_normalized_selected_raw_text(self, cursor: QTextCursor) -> str:
        """
        从编辑器的当前选区内容和 userData 重构原始文本（带 [标签]）
        这对于复制/粘贴等操作非常有用，可以保留行号和匹配信息
        """
        if not cursor.hasSelection():
            return ""

        start_pos = cursor.selectionStart()
        end_pos = cursor.selectionEnd()

        start_block = self.document().findBlock(start_pos)
        end_block = self.document().findBlock(end_pos)

        raw_lines = []
        current_block = start_block

        # 循环遍历所有被选区触及的文本块
        while current_block.isValid() and current_block.position() <= end_pos:
            prefix = self._build_line_prefix(current_block)
            block_start_pos = current_block.position()
            block_text = current_block.text()

            # 使用绝对数学计算切片索引
            # 本行起点的相对偏移（如果是第一行，起点为选区起点，否则为 0）
            local_start = max(0, start_pos - block_start_pos)
            # 本行终点的相对偏移（如果是最后一行，终点为选区终点，否则为文本末尾）
            local_end = min(len(block_text), end_pos - block_start_pos)

            # 提取文本并加上前缀
            text_part = block_text[local_start:local_end]

            # 默认将前缀加在最前面
            final_text = prefix + text_part

            # 特殊处理进度标签：如果 "】" 在选区内，则将前缀插入到它后面
            if "进度：" in prefix:
                closing_bracket_index_in_block = block_text.find("】")
                if closing_bracket_index_in_block != -1:
                    insert_pos_in_block = closing_bracket_index_in_block + 1
                    if local_start < insert_pos_in_block <= local_end:
                        insert_pos_in_text_part = insert_pos_in_block - local_start
                        part1 = text_part[:insert_pos_in_text_part]
                        part2 = text_part[insert_pos_in_text_part:]
                        final_text = part1 + prefix + part2

            raw_lines.append(final_text)

            if current_block == end_block:
                break
            current_block = current_block.next()

        return "\n".join(raw_lines)

    def clear_cursor_history(self):
        """清空所有跳转位置的记录"""
        self.m_cursor_history_back.clear()
        self.m_cursor_history_forward.clear()
        self.m_last_cursor_pos = 0

    def reset_editor_color(self):
        # 恢复编辑器文字的默认颜色，确保清除 insert_text_and_set_bg_color 里面加的颜色
        self.setPlainText("0")  # 重置高亮前清除原文本，避免过长

        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)

        default_fg_color = self.palette().color(self.foregroundRole())
        default_bg_color = self.palette().color(self.backgroundRole())
        fmt = QTextCharFormat()
        fmt.setForeground(default_fg_color)
        fmt.setBackground(default_bg_color)

        cursor.mergeCharFormat(fmt)
        cursor.clearSelection()
        self.setTextCursor(cursor)


class LineNumberArea(QWidget):
    def __init__(self, editor: CustomPlainTextEdit):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return self.editor.lineNumberAreaSizeHint()

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)
