from enum import Enum, auto

from qtpy.QtGui import QTextFormat

# blockFormat 的自定义属性，行号、是否为匹配行
PROP_LINE_NUM = QTextFormat.UserProperty + 1
PROP_MATCHED = QTextFormat.UserProperty + 2


class PatchSearchAction(Enum):
    NOT_PATCH_SEARCH = auto()
    BOOKS_VS_BAK = auto()
    BAK_VS_BOOKS = auto()


class SaveAction(Enum):
    NO_CHANGES = auto()  # 无修改，不需要弹出保存选择
    DO_SAVE = auto()  # 用户点击保存，且已完成 save_change
    DISCARD_SAVE = auto()  # 用户点击不保存（放弃修改）
    CANCELLED = auto()  # 用户取消了操作（关闭对话框或点击取消）
