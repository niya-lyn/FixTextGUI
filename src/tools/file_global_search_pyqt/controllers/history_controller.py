from qtpy.QtCore import QObject, Signal, QPoint, QSize

from config import HISTORY_ITEM_LIMIT
from widgets.custom.pinnable_list_item import PinnableListItem
from widgets.custom.draggable_history_list_widget import DraggableHistoryListWidget

from typing import List, TYPE_CHECKING, Callable, Tuple

if TYPE_CHECKING:
    from services.history_service import HistoryService
    from widgets.search_widget import SearchWidget
    from widgets.replace_widget import ReplaceWidget
    from widgets.text_editor_widget import TextEditorWidget
    from core.search_options import SearchOptions
    from main_window import MainWindow


class HistoryController(QObject):
    searchItemSelected = Signal(str)
    replaceItemSelected = Signal(str)

    def __init__(
        self,
        main_window: "MainWindow",
        history_service: "HistoryService",
        search_widget: "SearchWidget",
        replace_widget: "ReplaceWidget",
        text_editor_widget: "TextEditorWidget",
        search_options: "SearchOptions",
        get_function_color_callback: Callable[[str], Tuple[str, str]],
    ):
        super().__init__()
        self.main_window = main_window
        self.history_service = history_service
        self.search_widget = search_widget
        self.replace_widget = replace_widget
        self.text_editor_widget = text_editor_widget
        self.search_options = search_options
        self.current_theme = self.history_service.get_theme()
        self.get_function_color_callback = get_function_color_callback

        self.search_list = self.replace_widget.get_search_history_list()
        self.replace_list = self.replace_widget.get_replace_history_list()

        self._pinned_search_history_texts: List[str] = []
        self._pinned_replace_history_texts: List[str] = []

        self._setup_connections()

        self._load_history_data()

    def _setup_connections(self):
        # 监听列表 UI 的操作
        self.search_list.itemsPinStateChanged.connect(self._on_items_pin_state_changed)
        self.replace_list.itemsPinStateChanged.connect(self._on_items_pin_state_changed)
        self.search_list.itemsDeleted.connect(self._on_items_deleted)
        self.replace_list.itemsDeleted.connect(self._on_items_deleted)

    # ---------------- 暴露给 View 的槽函数，傻逼信号转发，待整理 ----------------
    def on_search_list_clicked(self, item: PinnableListItem):
        """当搜索列表某一项被点击时，提取出文本，直接发送信号"""
        search_text = self.search_list.remove_desc_prefix(item.text())
        self.searchItemSelected.emit(search_text)

    def on_replace_list_clicked(self, item: PinnableListItem):
        """当替换列表某一项被点击时，提取出文本，直接发送信号"""
        new_replace_text = self.replace_list.remove_desc_prefix(item.text())
        self.replaceItemSelected.emit(new_replace_text)

    def handle_theme_changed(self, theme: str):
        """当主题切换时，主动重载历史数据，因为历史记录需要保存当前主题"""
        self.current_theme = theme
        self.reload_history_data()

    # ---------------- 对外 API ----------------
    def add_new_search_entry(self, text: str):
        self._add_entry(self.search_list, text)

    def add_new_replace_entry(self, text: str):
        self._add_entry(self.replace_list, text)

    def _add_entry(self, list_widget: DraggableHistoryListWidget, text: str, is_pinned: bool = False):
        """
        私有辅助方法，处理添加、去重、置顶和数量限制的核心逻辑
        """
        # 1. 如果文本为空，则直接返回
        if not text:
            return

        # 2. 确定使用哪个置顶列表
        pinned_texts = (
            self._pinned_search_history_texts
            if list_widget == self.search_list
            else self._pinned_replace_history_texts
        )

        # 3. 如果文本在持久化的置顶列表中，则强制其为置顶状态
        if text in pinned_texts:
            is_pinned = True

        # 4. 查找已存在的条目并移除，以便稍后重新添加到正确的位置
        # - 如果已存在且已置顶，则直接返回，保持位置不变
        # - 如果已存在但未置顶，则移除，后续会重新添加到非置顶区的顶部
        old_desc_prefix = ""
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            item_text = item.text()
            if item and item_text == text:
                old_desc_prefix = list_widget.get_desc_prefix(item_text)
                if item.is_pinned() and is_pinned:
                    return  # 已置顶，位置不变，直接返回
                else:
                    list_widget.takeItem(i)  # 未置顶，移除旧条目
                    break  # 找到并处理后即可退出

        # 5. 创建新的 PinnableListItem
        list_type = PinnableListItem.LIST_TYPE_SEARCH
        if list_widget == self.replace_list:
            list_type = PinnableListItem.LIST_TYPE_REPLACE
        new_list_item = PinnableListItem(old_desc_prefix + text, is_pinned, list_type)
        new_list_item.set_pinned_color(self.get_function_color_callback("pinned_list_item_color"))

        # 6. 将新项插入到正确的位置
        # 置顶项总是在最上方，非置顶项在其后，且最新的非置顶项在最前面
        if is_pinned:
            # 找到第一个非置顶项的位置，然后插入在其前面
            insert_row = 0
            for i in range(list_widget.count()):
                item = list_widget.item(i)
                if not item.is_pinned():
                    break
                insert_row += 1
            list_widget.insertItem(insert_row, new_list_item)
        else:
            # 找到第一个非置顶项的位置（即所有置顶项之后），然后插入
            insert_row = len(pinned_texts)
            list_widget.insertItem(insert_row, new_list_item)

        new_list_item.set_pinned(is_pinned)

        # 7. 维持数量上限（只对非置顶项进行限制）
        while list_widget.count() > len(pinned_texts) + HISTORY_ITEM_LIMIT:
            # 从列表末尾移除，因为那里是最旧的非置顶项
            list_widget.takeItem(list_widget.count() - 1)

    def _on_items_pin_state_changed(self, items: List[PinnableListItem], need_resort: bool):
        """
        统一处理置顶状态变更

        Args:
            items: 发生变更的项目列表
            need_resort: 是否需要重新在 UI 上排序（右键菜单=True, 拖拽=False）
        """
        if not items:
            return

        first_item = items[0]
        list_type = first_item.get_list_type()

        if list_type == PinnableListItem.LIST_TYPE_SEARCH:
            target_list_widget = self.search_list
            pinned_texts_list = self._pinned_search_history_texts
        elif list_type == PinnableListItem.LIST_TYPE_REPLACE:
            target_list_widget = self.replace_list
            pinned_texts_list = self._pinned_replace_history_texts
        else:
            return

        # 1. 更新内存数据 (Backend Data)
        for item in items:
            item_text = item.text()
            is_pinned = item.is_pinned()

            # 根据当前 item 的状态更新列表
            if is_pinned:
                if item_text not in pinned_texts_list:
                    pinned_texts_list.append(item_text)
            else:
                if item_text in pinned_texts_list:
                    pinned_texts_list.remove(item_text)

        # 2. 如果不需要重排，直接结束（拖拽逻辑）
        if not need_resort:
            return

        # 3. 如果需要重排（右键菜单逻辑）
        # 需要将这些项先从 UI 移除，然后重新添加，
        # _add_entry 会根据它们在 pinned_texts_list 中的存在情况自动决定位置
        texts_to_readd = []

        # 收集文本并移除旧项
        # 注意：不要在遍历 items 时直接从 list_widget takeItem，因为行号会变
        # 安全的做法是先收集对象，再查找移除
        for item in items:
            texts_to_readd.append(item.text())
            row = target_list_widget.row(item)
            if row >= 0:
                target_list_widget.takeItem(row)

        # 按照 items 原有的顺序添加，重新添加
        for text in texts_to_readd:
            self._add_entry(target_list_widget, text)

    def _on_items_deleted(self, deleted_text: List[str], list_type: str):
        if list_type == PinnableListItem.LIST_TYPE_SEARCH:
            target_pinned_texts = self._pinned_search_history_texts
        elif list_type == PinnableListItem.LIST_TYPE_REPLACE:
            target_pinned_texts = self._pinned_replace_history_texts
        else:
            return

        for text in deleted_text:
            if text in target_pinned_texts:
                target_pinned_texts.remove(text)

    def _load_history_data(self):
        """从 HISTORY_LOG_FILE 加载 JSON 数据并填充列表"""
        history_data = self.history_service.load_raw_data()
        if not history_data:
            return

        # 首先加载置顶项
        self._pinned_search_history_texts = history_data.get("pinned_search", [])
        self._pinned_replace_history_texts = history_data.get("pinned_replace", [])

        search_history = history_data.get("search", [])
        replace_history = history_data.get("replace", [])

        # 添加置顶的搜索历史，置顶项插入无需逆序……
        for text in self._pinned_search_history_texts:
            self._add_entry(self.search_list, text, is_pinned=True)

        # 添加未置顶的搜索历史，并确保不与置顶项重复
        for text in reversed(search_history):
            if text not in self._pinned_search_history_texts:
                self._add_entry(self.search_list, text, is_pinned=False)

        # 添加置顶的替换历史，置顶项插入无需逆序……
        for text in self._pinned_replace_history_texts:
            self._add_entry(self.replace_list, text, is_pinned=True)

        # 添加未置顶的替换历史，并确保不与置顶项重复
        for text in reversed(replace_history):
            if text not in self._pinned_replace_history_texts:
                self._add_entry(self.replace_list, text, is_pinned=False)

        # 恢复面板状态
        pos_dict = history_data.get("last_history_panel_pos")
        size_dict = history_data.get("last_history_panel_size")

        pos = QPoint(pos_dict["x"], pos_dict["y"]) if pos_dict else None
        size = QSize(size_dict["width"], size_dict["height"]) if size_dict else None

        self.replace_widget.set_history_panel_state(pos, size)
        self.search_options.set_add_to_history_list(history_data.get("add_to_history_list", True))
        self.search_options.set_show_chapter_title(history_data.get("show_chapter_title", False))

    def save_history_data(self):
        """程序退出时，将当前列表和状态收集保存"""
        history_data = {
            "search": [],
            "replace": [],
            "pinned_search": [],
            "pinned_replace": [],
            "demo_search": [
                "乱序行",
                "字数过少",
                "特殊章节",
                "字数最多",
                "【# 迭->叠】(?<![不连更])迭(?![代声遭出落起变哥戈]|连声|亚[哥戈])",
                "【# 处理“位”】(?<=[一二三四五六七八九十零〇百千万亿两廿卅卌壹贰叁肆伍陆柒捌玖拾佰仟萬億这那几])位",
            ],
            "demo_replace": [
                "【# 连接两行】\\1\\2\\5",
                "【# 结尾改成句号】\\1。\\n\\3\\4\\5",
                "【# 结尾改成省略号】\\1……\\n\\3\\4\\5",
                "【# 结尾加上句号】\\1\\2。\\n\\3\\4\\5",
                "【# 在括号前加句号】\\1。\\2",
                "【# 在引号前面补冒号】\\1：“\\2",
                "【# 在引号前面补逗号】\\1，“\\2",
            ],
            "add_to_history_list": True,
            "show_chapter_title": False,
            "theme": self.current_theme,
        }

        # 遍历搜集
        for i in range(self.search_list.count()):
            search_list_item = self.search_list.item(i)
            if not search_list_item.is_pinned():
                history_data["search"].append(search_list_item.text())
            elif search_list_item.is_pinned():
                history_data["pinned_search"].append(search_list_item.text())

        for i in range(self.replace_list.count()):
            replace_list_item = self.replace_list.item(i)
            if not replace_list_item.is_pinned():
                history_data["replace"].append(replace_list_item.text())
            elif replace_list_item.is_pinned():
                history_data["pinned_replace"].append(replace_list_item.text())

        # 保存面板状态
        pos, size = self.replace_widget.get_history_panel_state()
        history_data["last_history_panel_pos"] = {"x": pos.x(), "y": pos.y()} if pos else None
        history_data["last_history_panel_size"] = {"width": size.width(), "height": size.height()} if size else None

        # 顺便存一下主窗口状态，待整理
        main_window_pos = self.main_window.pos()
        main_window_size = self.main_window.size()
        history_data["last_main_window_pos"] = {"x": main_window_pos.x(), "y": main_window_pos.y()}
        history_data["last_main_window_size"] = {
            "width": main_window_size.width(),
            "height": main_window_size.height(),
        }

        history_data["add_to_history_list"] = self.search_options.add_to_history_list
        history_data["show_chapter_title"] = self.search_options.show_chapter_title

        history_data["theme"] = self.current_theme

        self.history_service.save_raw_data(history_data)

    def reload_history_data(self):
        self.save_history_data()
        self.search_list.clear()
        self.replace_list.clear()
        self._load_history_data()
