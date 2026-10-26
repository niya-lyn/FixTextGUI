from qtpy.QtCore import Qt, QSortFilterProxyModel
from qtpy.QtGui import QStandardItemModel, QStandardItem
from qtpy.QtWidgets import QCompleter

try:
    from pypinyin import lazy_pinyin, Style

    HAS_PYPINYIN = True
except ImportError:
    HAS_PYPINYIN = False


def get_pinyin(text: str) -> str:
    """获取拼音全拼"""
    if not HAS_PYPINYIN:
        return ""
    return "".join(lazy_pinyin(text))


def get_pinyin_initials(text: str) -> str:
    """获取拼音首字母"""
    if not HAS_PYPINYIN:
        return ""
    return "".join(lazy_pinyin(text, style=Style.FIRST_LETTER))


class PinyinFilterModel(QSortFilterProxyModel):
    """支持拼音过滤的代理模型"""

    PinyinRole = Qt.UserRole + 1
    InitialsRole = Qt.UserRole + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_pattern = ""

    def setFilterPattern(self, pattern: str):
        self._filter_pattern = pattern.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent) -> bool:
        if not self._filter_pattern:
            return True

        index = self.sourceModel().index(source_row, 0, source_parent)

        # 1. 检查显示文本（中文原文）
        display_text = (index.data(Qt.DisplayRole) or "").lower()
        if self._filter_pattern in display_text:
            return True

        # 2. 检查拼音全拼（如 "beijing" 匹配 "北京"）
        pinyin = (index.data(self.PinyinRole) or "").lower()
        if self._filter_pattern in pinyin:
            return True

        # 3. 检查拼音首字母（如 "bj" 匹配 "北京"）
        initials = (index.data(self.InitialsRole) or "").lower()
        if self._filter_pattern in initials:
            return True

        return False


class PinyinCompleter(QCompleter):
    """支持中文拼音匹配的自动完成器

    支持三种匹配方式：
    - 中文原文匹配
    - 拼音全拼匹配（如输入 "beijing" 匹配 "北京"）
    - 拼音首字母匹配（如输入 "bj" 匹配 "北京"）
    """

    def __init__(self, items: list = None, parent=None):
        super().__init__(parent)

        # 创建源模型和过滤代理模型
        self._source_model = QStandardItemModel(self)
        self._filter_model = PinyinFilterModel(self)
        self._filter_model.setSourceModel(self._source_model)

        # 设置使用代理模型
        super().setModel(self._filter_model)
        self.setCaseSensitivity(Qt.CaseInsensitive)
        self.setCompletionMode(QCompleter.PopupCompletion)

        if items:
            self.setItems(items)

    def setItems(self, items: list):
        """设置自动完成的项目列表"""
        self._source_model.clear()

        for text in items:
            item = QStandardItem(text)
            # 存储拼音数据到自定义角色
            item.setData(get_pinyin(text), PinyinFilterModel.PinyinRole)
            item.setData(get_pinyin_initials(text), PinyinFilterModel.InitialsRole)
            self._source_model.appendRow(item)

    def splitPath(self, path: str) -> list:
        """重写：当用户输入时更新过滤器"""
        self._filter_model.setFilterPattern(path)
        return []

    def pathFromIndex(self, index) -> str:
        """重写：返回选中项的显示文本"""
        return index.data(Qt.DisplayRole) or ""
