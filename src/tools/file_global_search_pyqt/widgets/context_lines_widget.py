from typing import Optional
from functools import partial
from contextlib import contextmanager

from qtpy.QtWidgets import (
    QMenu,
    QFrame,
    QWidget,
    QSpinBox,
    QPushButton,
    QVBoxLayout,
    QWidgetAction,
)
from qtpy.QtGui import QIcon
from qtpy.QtCore import QSize, Signal

from resources.ui_generated.ui_context_lines_widget import Ui_ContextLinesWidget


class ContextLinesWidget(QWidget):

    prevLinesChanged = Signal(int)
    nextLinesChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.ui = Ui_ContextLinesWidget()
        self.ui.setupUi(self)

        self.set_icons()

        self.ui.prev_lines_options_button.setIconSize(QSize(15, 15))
        self.ui.next_lines_options_button.setIconSize(QSize(15, 15))

        self._setup_options_menus()
        self._setup_link_logic()

    def set_icons(self, theme: str = "light"):
        self.link_icon = QIcon(f":/{theme}/icons/link.png")
        self.unlink_icon = QIcon(f":/{theme}/icons/unlink.png")

        self._update_link_button_style(self.ui.link_values_button.isChecked())

        self.ui.prev_lines_options_button.setIcon(QIcon(f":/{theme}/icons/options.png"))
        self.ui.next_lines_options_button.setIcon(QIcon(f":/{theme}/icons/options.png"))

    def _setup_options_menus(self):
        # 为“上文行数”创建并设置菜单
        prev_menu = self._create_context_menu(self.ui.prev_lines_spin_box)
        self.ui.prev_lines_options_button.setMenu(prev_menu)

        # 为“下文行数”创建并设置菜单
        next_menu = self._create_context_menu(self.ui.next_lines_spin_box)
        self.ui.next_lines_options_button.setMenu(next_menu)

    def _create_context_menu(self, spin_box: QSpinBox) -> QMenu:
        menu = QMenu(self)

        # 1. 创建一个主容器 QWidget 和一个垂直布局
        container_widget = QWidget(menu)
        container_widget.setObjectName("context_lines_container")
        layout = QVBoxLayout(container_widget)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(3)

        # --- 2. 创建所有按钮并添加到布局中 ---

        # 直接设置值的按钮
        set_values = [0, 1, 3, 5]
        for value in set_values:
            button = QPushButton(f"{value} 行", container_widget)
            button.setFlat(True)
            button.clicked.connect(partial(spin_box.setValue, value))
            layout.addWidget(button)

        # 添加分隔线
        separator1 = QFrame(container_widget)
        separator1.setProperty("class", "separator_line")
        separator1.setFrameShape(QFrame.HLine)
        separator1.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator1)

        # 增量调整值的按钮
        add_values = [3, 5, 10]
        for value in add_values:
            button = QPushButton(f"+{value} 行", container_widget)
            button.setFlat(True)
            button.clicked.connect(lambda _, v=value: spin_box.setValue(spin_box.value() + v))
            layout.addWidget(button)

        # 添加分隔线
        separator2 = QFrame(container_widget)
        separator2.setProperty("class", "separator_line")
        separator2.setFrameShape(QFrame.HLine)
        separator2.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator2)

        # 减量调整值的按钮
        subtract_values = [-3, -5, -10]
        for value in subtract_values:
            button = QPushButton(f"{value} 行", container_widget)
            button.setFlat(True)
            button.clicked.connect(lambda _, v=value: spin_box.setValue(max(0, spin_box.value() + v)))
            layout.addWidget(button)

        # 3. 创建一个 QWidgetAction，它是将 QWidget 放入菜单的桥梁
        widget_action = QWidgetAction(menu)
        widget_action.setDefaultWidget(container_widget)
        menu.addAction(widget_action)

        return menu

    def _setup_link_logic(self):
        """连接两个 SpinBox 的 valueChanged 信号以实现联动"""
        # 设置按钮的图标和大小
        self.ui.link_values_button.setIconSize(QSize(24, 24))

        # 将按钮的 toggled 信号连接到状态更新函数
        self.ui.link_values_button.toggled.connect(self._update_link_button_style)

        # 初始化按钮的初始样式和状态
        self._update_link_button_style(self.ui.link_values_button.isChecked())

        self.ui.prev_lines_spin_box.valueChanged.connect(self._on_linked_value_changed)
        self.ui.next_lines_spin_box.valueChanged.connect(self._on_linked_value_changed)

    def _update_link_button_style(self, checked: bool):
        button = self.ui.link_values_button
        button.setChecked(checked)
        if checked:
            button.setIcon(self.link_icon)
            button.setToolTip("联动修改已开启（点击关闭）")
        else:
            button.setIcon(self.unlink_icon)
            button.setToolTip("联动修改已关闭（点击开启）")

    def _on_linked_value_changed(self, value: int):
        # 1. 检查“联动”按钮的状态
        if not self.ui.link_values_button.isChecked():
            return

        # 2. 识别信号的来源
        sender_spinbox = self.sender()

        # 3. 确定目标和需要发出的信号
        if sender_spinbox is self.ui.prev_lines_spin_box:
            target_spinbox = self.ui.next_lines_spin_box
            signal_to_emit = self.nextLinesChanged
        elif sender_spinbox is self.ui.next_lines_spin_box:
            target_spinbox = self.ui.prev_lines_spin_box
            signal_to_emit = self.prevLinesChanged
        else:
            return

        # 4. 使用信号阻塞来更新 UI，防止无限循环
        with self.block_signals(target_spinbox):
            target_spinbox.setValue(value)

        # 5. 发出信号
        signal_to_emit.emit(value)

    def get_prev_lines(self) -> int:
        """获取“上文行数”的值"""
        return self.ui.prev_lines_spin_box.value()

    def get_next_lines(self) -> int:
        """获取“下文行数”的值"""
        return self.ui.next_lines_spin_box.value()

    def set_prev_lines(self, value: int) -> None:
        """设置“上文行数”的值"""
        with self.block_signals(self.ui.prev_lines_spin_box):
            self.ui.prev_lines_spin_box.setValue(value)

    def set_next_lines(self, value: int) -> None:
        """设置“下文行数”的值"""
        with self.block_signals(self.ui.next_lines_spin_box):
            self.ui.next_lines_spin_box.setValue(value)

    def set_controls_enabled(self, enabled: bool) -> None:
        self.ui.prev_lines_spin_box.setEnabled(enabled)
        self.ui.next_lines_spin_box.setEnabled(enabled)

    def set_context_line_type_hint(self, str: str) -> None:
        self.ui.context_line_type_hint.setText(str)

    @contextmanager
    def block_signals(self, widget: QWidget):
        """一个上下文管理器，用于临时阻塞控件信号"""
        widget.blockSignals(True)
        try:
            yield
        finally:
            widget.blockSignals(False)

    def set_page_size(self, page_size: int):
        self.ui.page_size_spin_box.setValue(page_size)

    def get_page_size(self) -> int:
        return self.ui.page_size_spin_box.value()

    def update_theme_style(self, qss_string: str, theme_name: str):
        self.setStyleSheet(qss_string)
        self.set_icons(theme_name)
