from qtpy.QtWidgets import QListWidgetItem
from qtpy.QtGui import QColor, QBrush

from typing import Tuple


class PinnableListItem(QListWidgetItem):

    LIST_TYPE_SEARCH = "search"
    LIST_TYPE_REPLACE = "replace"

    def __init__(self, text: str, is_pinned: bool = False, list_type: str = LIST_TYPE_SEARCH, parent=None):
        super().__init__(text, parent)

        self._original_font = self.font()

        self.pinned_color = "#FFF8E1", "#B0523D"

        self.set_pinned(is_pinned)
        self.set_list_type(list_type)

    def set_pinned_color(self, color: Tuple[str, str]):
        self.pinned_color = color

    def set_pinned(self, is_pinned: bool):
        self._is_pinned = is_pinned

        if is_pinned:
            font = self.font()
            font.setUnderline(True)
            self.setFont(font)
            bg_color, fg_color = self.pinned_color
            self.setBackground(QColor(bg_color))
            self.setForeground(QColor(fg_color))
        else:
            self.setFont(self._original_font)
            self.setBackground(QBrush())  # 恢复默认背景
            self.setForeground(QBrush())  # 恢复默认前景

    def is_pinned(self) -> bool:
        return self._is_pinned

    def set_list_type(self, list_type: str):
        self._list_type = list_type

    def get_list_type(self) -> str:
        return self._list_type
