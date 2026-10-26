from qtpy.QtWidgets import QComboBox, QListView, QApplication
from qtpy.QtGui import QFontMetrics, QWheelEvent, QKeyEvent
from qtpy.QtCore import Qt, QSize
from typing import Iterable


class CustomComboBox(QComboBox):

    MAX_WIDTH = 500  # 这个先写死，待优化
    WIDTH_PADDING = 15

    def __init__(self, parent=None):
        super().__init__(parent)

        # 用于记录 UI 文件或外部代码设置的最小宽度
        self._user_min_width = 0
        # 用于标记是否是内部正在调整大小，防止死循环或误记录
        self._is_internal_resize = False
        # 缓存当前最长文本的像素宽度，避免重复计算
        self._cached_max_text_width = 0

        self._configure_view()

        self._check_and_update_width(self.placeholderText())

    def _configure_view(self):
        # --- 1. 获取系统默认字体 ---
        font = QApplication.font()

        # --- 2. 动态计算行高 ---
        font_metrics = QFontMetrics(font)
        row_height = font_metrics.height() + 12

        # --- 3. 创建新的视图并应用设置 ---
        list_view = QListView()
        list_view.setFont(font)
        list_view.setAlternatingRowColors(True)
        list_view.setStyleSheet(f"QListView::item {{ height: {row_height}px; }}")

        self.setView(list_view)

    def setMinimumWidth(self, width):
        # 如果不是内部自动调整触发的调用，说明是 UI 文件或外部代码在设置，记录下来
        if not self._is_internal_resize:
            self._user_min_width = width
        super().setMinimumWidth(width)

    def setMinimumSize(self, *args):
        if not self._is_internal_resize:
            if len(args) == 1 and isinstance(args[0], QSize):
                self._user_min_width = args[0].width()
            elif len(args) >= 1:
                self._user_min_width = args[0]
        super().setMinimumSize(*args)

    def setPlaceholderText(self, placeholderText: str):
        super().setPlaceholderText(placeholderText)
        self._check_and_update_width(placeholderText)

    def addItem(self, *args):
        super().addItem(*args)
        text = self.itemText(self.count() - 1)
        self._check_and_update_width(text)

    def addItems(self, texts: Iterable[str]):
        # 将 texts 转为列表，以处理可能的生成器并获取其长度
        texts_list = list(texts)
        super().addItems(texts_list)
        if not texts_list:
            return

        # 批量添加时，只需找到新列表中的最长者进行一次比较
        fm = self.fontMetrics()
        max_new_width = max(fm.horizontalAdvance(text) for text in texts_list)
        self._check_and_update_width(max_new_width, is_width=True)

    def insertItem(self, index: int, *args):
        super().insertItem(index, *args)
        text = self.itemText(index)
        self._check_and_update_width(text)

    def insertItems(self, index: int, texts: Iterable[str]):
        texts_list = list(texts)
        super().insertItems(index, texts_list)
        if not texts_list:
            return

        fm = self.fontMetrics()
        max_new_width = max(fm.horizontalAdvance(text) for text in texts_list)
        self._check_and_update_width(max_new_width, is_width=True)

    def clear(self):
        super().clear()
        self._cached_max_text_width = 0
        # 强制重置为占位符宽度或默认最小宽度
        self._check_and_update_width(self.placeholderText())

    def _check_and_update_width(self, text_or_width, is_width=False):
        """
        检查新内容的宽度，如果它比缓存的最长宽度还长，则更新缓存并应用新宽度
        """
        # 如果文本为空，且不是直接传入宽度，则无需操作
        # 但如果清空了所有项目，仍需触发一次宽度应用，以恢复到初始或占位符宽度
        if not text_or_width and not is_width:
            if self.count() == 0:
                self._apply_new_width()
            return

        fm = self.fontMetrics()
        new_width = text_or_width if is_width else fm.horizontalAdvance(text_or_width)

        if new_width > self._cached_max_text_width:
            self._cached_max_text_width = new_width
            self._apply_new_width()

    def _apply_new_width(self):
        """
        根据缓存的最长文本宽度，计算并应用最终宽度到控件和视图。
        """
        # 加上图标的宽度（如果有）和固定的内边距
        padding = self.WIDTH_PADDING
        if self.iconSize().width() > 0:
            padding += self.iconSize().width()

        calculated_width = self._cached_max_text_width + padding

        effective_width = max(calculated_width, self._user_min_width)

        # 应用最大宽度限制
        final_width = min(effective_width, self.MAX_WIDTH)

        # 将计算出的宽度应用到 ComboBox 和其下拉视图
        self._is_internal_resize = True
        self.setMinimumWidth(final_width)
        self.view().setMinimumWidth(final_width)
        self._is_internal_resize = False

    def wheelEvent(self, event: QWheelEvent):
        """
        重写滚轮事件，实现通过滚轮循环选择项目
        """
        delta = event.angleDelta().y()
        if delta > 0:
            self.select_prev_item()
        else:
            self.select_next_item()

        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        """
        重写按键事件，用上下键循环选择项目，并覆盖默认行为
        """
        if event.key() == Qt.Key_Up:
            self.select_prev_item()
            return

        if event.key() == Qt.Key_Down:
            self.select_next_item()
            return

        super().keyPressEvent(event)

    def select_prev_item(self):
        current_index = self.currentIndex()
        count = self.count()
        if count == 0:
            return
        new_index = current_index - 1 if current_index > 0 else count - 1
        self.setCurrentIndex(new_index)

    def select_next_item(self):
        current_index = self.currentIndex()
        count = self.count()
        if count == 0:
            return
        new_index = current_index + 1 if current_index < count - 1 else 0
        self.setCurrentIndex(new_index)
