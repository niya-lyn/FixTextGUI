from qtpy.QtWidgets import (
    QListWidget,
    QMenu,
    QInputDialog,
    QAbstractItemView,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QPlainTextEdit,
    QDialogButtonBox,
)
from qtpy.QtCore import Qt, QPoint, Signal

from typing import List, Optional

from widgets.custom.pinnable_list_item import PinnableListItem


class HistoryTextEditDialog(QDialog):

    def __init__(self, text: str, title: str = "编辑内容", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(500, 400)

        layout = QVBoxLayout(self)

        # 文本编辑区域
        self.text_edit = QPlainTextEdit()
        self.text_edit.setPlainText(text)
        layout.addWidget(self.text_edit)

        # 按钮区域 (确定/取消)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_text(self) -> str:
        return self.text_edit.toPlainText()


class DraggableHistoryListWidget(QListWidget):

    itemsPinStateChanged = Signal(list, bool)
    itemsDeleted = Signal(list, str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

        self.setAlternatingRowColors(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        # 需要显式禁用滚动条才会出现省略效果
        # self.setTextElideMode(Qt.ElideRight)
        # self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def item(self, row: int) -> Optional[PinnableListItem]:
        return super().item(row)

    def itemAt(self, pos: QPoint) -> Optional[PinnableListItem]:
        return super().itemAt(pos)

    def selectedItems(self) -> List[PinnableListItem]:
        return super().selectedItems()

    def takeItem(self, row: int) -> Optional[PinnableListItem]:
        return super().takeItem(row)

    def currentItem(self) -> Optional[PinnableListItem]:
        return super().currentItem()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Delete or e.key() == Qt.Key_Backspace:
            self.delete_selected_items()
        else:
            super().keyPressEvent(e)

    def dropEvent(self, event):
        """
        重写拖拽释放事件，允许自由拖拽，并根据落点自动更新置顶状态
        不需要 Manager 重排序 (need_resort=False)
        """
        # 1. 获取当前被拖拽的所有项目（在移动发生前）
        dragged_items = self.selectedItems()
        if not dragged_items:
            return

        # 2. 判断落点位置的目标状态
        # 获取鼠标释放位置下的项目（即将插入到该项目之前）
        target_item: PinnableListItem = self.itemAt(event.pos())

        should_be_pinned = False

        if target_item:
            # 如果落在一个已存在的项目上（或其缝隙），则继承该项目的状态
            # 例如：落在置顶项之前，则自己也变为置顶；落在非置顶项之前，则变为非置顶
            should_be_pinned = target_item.is_pinned()
        else:
            # 如果落在空白处（列表底部），则默认为非置顶
            should_be_pinned = False

        # 3. 执行父类的默认拖拽移动操作（此时行序会发生改变）
        super().dropEvent(event)

        # 4. 更新被拖拽项的状态以匹配落点区域
        items_changed = []
        for item in dragged_items:
            # 只有当状态确实需要改变时才处理
            if item.is_pinned() != should_be_pinned:
                item.set_pinned(should_be_pinned)
                items_changed.append(item)

        # 5. 发送信号通知管理器更新后台数据，但不触发布局重排
        if items_changed:
            self.itemsPinStateChanged.emit(items_changed, False)

    def show_context_menu(self, position: QPoint):
        selected_items = self.selectedItems()
        if not selected_items:
            return

        context_menu = QMenu(self)

        # 获取鼠标点击处的项目，以此决定本次操作是“全部置顶”还是“全部取消”
        clicked_item: PinnableListItem = self.itemAt(position)

        # 如果点击了某个项目，根据该项目的状态决定动作
        target_state_is_pinned = True
        if clicked_item:
            target_state_is_pinned = not clicked_item.is_pinned()

        # 动态生成菜单文本，显示受影响的项目数量
        count_suffix = f"（共 {len(selected_items)} 项）" if len(selected_items) > 1 else ""
        action_text = ("置顶" if target_state_is_pinned else "取消置顶") + count_suffix

        pin_action = context_menu.addAction(action_text)
        pin_action.triggered.connect(lambda: self.batch_toggle_pin(selected_items, target_state_is_pinned))

        context_menu.addSeparator()

        # 仅单选时显示的选项
        if len(selected_items) == 1 and clicked_item:
            edit_content_action = context_menu.addAction("编辑内容")
            edit_content_action.triggered.connect(lambda: self.edit_content(clicked_item))
            context_menu.addSeparator()

            if clicked_item.text().startswith("【# "):
                edit_desc_action = context_menu.addAction("编辑说明")
                edit_desc_action.triggered.connect(lambda: self.edit_desc(clicked_item))
                remove_desc_action = context_menu.addAction("移除说明")
                remove_desc_action.triggered.connect(lambda: self.remove_desc(clicked_item))
            else:
                set_desc_action = context_menu.addAction("添加说明")
                set_desc_action.triggered.connect(lambda: self.add_desc(clicked_item))
            context_menu.addSeparator()

        delete_action = context_menu.addAction("删除" + count_suffix)
        delete_action.triggered.connect(self.delete_selected_items)

        context_menu.exec_(self.mapToGlobal(position))

    def batch_toggle_pin(self, items: List[PinnableListItem], new_state: bool):
        """
        批量切换置顶状态辅助方法
        """
        changed_items = []
        for item in items:
            if item.is_pinned() != new_state:
                item.set_pinned(new_state)
                changed_items.append(item)
            elif item.is_pinned() == new_state:
                changed_items.append(item)

        if changed_items:
            # 发射信号：通知数据变更，且需要 UI 重排（归位到置顶区/非置顶区）
            self.itemsPinStateChanged.emit(changed_items, True)

    def edit_content(self, item: PinnableListItem):
        """
        弹出大文本框编辑内容，保留原有的说明前缀，并进行查重处理
        """
        # 1. 分离说明前缀和实际内容
        prefix = self.get_desc_prefix(item.text())
        current_content = self.remove_desc_prefix(item.text())

        # 2. 弹出自定义对话框
        dialog = HistoryTextEditDialog(current_content, title="编辑内容", parent=self)

        if dialog.exec_() == QDialog.Accepted:
            new_content = dialog.get_text()

            # 3. 校验空值
            if not new_content.strip():
                QMessageBox.warning(self, "内容无效", "内容不能为空")
                return

            # 4. 重新拼接前缀
            new_full_text = f"{prefix}{new_content}"

            # 5. 调用现有的查重更新逻辑
            self._update_item_text_with_conflict_resolution(item, new_full_text)

    def add_desc(self, item: PinnableListItem):
        desc, ok = QInputDialog.getText(self, "添加说明", "请输入说明：")
        if ok and desc:
            if not desc.strip():
                QMessageBox.warning(self, "说明无效", "说明不能为空。")
                return
            new_text = f"【# {desc}】{item.text()}"
            self._update_item_text_with_conflict_resolution(item, new_text)

    def edit_desc(self, item: PinnableListItem):
        """
        编辑说明。如果编辑后导致重名，询问用户是否覆盖
        """
        prefix = self.get_desc_prefix(item.text())
        if not prefix:
            return

        current_desc = prefix[3:-1]  # 从 "【# " 和 "】" 中提取描述

        new_desc, ok = QInputDialog.getText(self, "编辑说明", "请输入新的说明：", text=current_desc)

        if ok and new_desc:
            if not new_desc.strip():
                QMessageBox.warning(self, "说明无效", "说明不能为空。")
                return

            original_text_without_prefix = self.remove_desc_prefix(item.text())
            new_text = f"【# {new_desc}】{original_text_without_prefix}"

            self._update_item_text_with_conflict_resolution(item, new_text)

    def remove_desc(self, item: PinnableListItem):
        """
        移除说明前缀。如果移除后导致重名，询问用户是否覆盖（删除旧的重复项）
        """
        new_text = self.remove_desc_prefix(item.text())
        self._update_item_text_with_conflict_resolution(item, new_text)

    def _update_item_text_with_conflict_resolution(self, item: PinnableListItem, new_text: str) -> bool:
        """
        更新列表项文本，并通过与用户交互来处理潜在的重复项

        Args:
            item: 要更新的列表项
            new_text: 新的文本内容

        Returns:
            bool: 如果列表项成功更新，则返回 True，否则返回 False
        """
        if item.text() == new_text:
            return False

        conflicting_items = []
        for i in range(self.count()):
            existing_item = self.item(i)
            if existing_item is not item and existing_item.text() == new_text:
                conflicting_items.append(existing_item)

        if conflicting_items:
            truncated_text = (new_text[:30] + "...") if len(new_text) > 30 else new_text
            reply = QMessageBox.question(
                self,
                "名称重复",
                f"操作后将与其他项（{truncated_text}）内容重复。\n是否移除已存在的重复项以继续？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if reply == QMessageBox.Yes:
                deleted_texts = []
                list_type = item.get_list_type()

                for conflict_item in conflicting_items:
                    row = self.row(conflict_item)
                    self.takeItem(row)
                    deleted_texts.append(conflict_item.text())

                if deleted_texts:
                    self.itemsDeleted.emit(deleted_texts, list_type)

                item.setText(new_text)
                return True
            else:
                return False
        else:
            item.setText(new_text)
            return True

    @staticmethod
    def remove_desc_prefix(text: str) -> str:
        if text.startswith("【# "):
            end_index = text.find("】")
            if end_index != -1:
                return text[end_index + 1 :]

        return text

    @staticmethod
    def get_desc_prefix(text: str) -> str:
        if text.startswith("【# "):
            end_index = text.find("】")
            if end_index != -1:
                return text[0 : end_index + 1]

        return ""

    def delete_selected_items(self):
        deleted_text = []
        list_type = ""
        for item in self.selectedItems():
            row = self.row(item)
            self.takeItem(row)
            deleted_text.append(item.text())
            list_type = item.get_list_type()

        self.itemsDeleted.emit(deleted_text, list_type)
