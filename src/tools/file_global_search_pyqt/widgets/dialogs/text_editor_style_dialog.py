import regex
from typing import Dict, List, Optional

from qtpy.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QFrame,
    QColorDialog,
    QFontDialog,
)
from qtpy.QtGui import QColor, QFont


class TextEditorStyleDialog(QDialog):
    """样式设置对话框，用于编辑 QSS 中的 font-family（主字体）、字号、颜色、背景色。"""

    def __init__(self, parent=None, initial_props: Optional[Dict[str, str]] = None):
        """
        :param parent: 父窗口
        :param initial_props: 初始样式属性字典，例如：
            {
                'font-family': '"Consolas-Slim", "FZYouSongJ GBK", "MiSans L3", "黑体"',
                'font-size': '12pt',
                'color': '#bfc7d5',
                'background-color': '#202331'
            }
            如果未提供，则使用默认值。
        """
        super().__init__(parent)

        self.setWindowTitle("样式设置")
        self.setMinimumWidth(400)

        # 默认属性
        default_props = {
            "font-family": '"Consolas-Slim", "FZYouSongJ GBK", "MiSans L3", "黑体"',
            "font-size": "12pt",
            "color": "#bfc7d5",
            "background-color": "#202331",
        }
        self.initial_props = initial_props if initial_props is not None else default_props
        self.current_props = self.initial_props.copy()

        # 存储最终结果，供外部读取
        self.result_props = None

        self._setup_ui()
        self._update_ui_from_props()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 间距
        layout.addSpacing(10)

        # 说明文字
        layout.addWidget(QLabel("修改文本编辑器的主字体、字号、颜色和背景色。"))

        layout.addSpacing(10)

        # 分隔线
        line = QFrame()
        line.setProperty("class", "separator_line")
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        layout.addSpacing(10)

        # ---- 主字体选择 ----
        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("主字体："))
        self.family_label = QLabel()
        self.family_label.setWordWrap(True)
        self.family_label.setMinimumWidth(200)
        font_layout.addWidget(self.family_label)
        choose_font_btn = QPushButton("选择字体")
        choose_font_btn.clicked.connect(self._choose_font)
        font_layout.addWidget(choose_font_btn)
        layout.addLayout(font_layout)

        layout.addSpacing(10)

        # ---- 字号 ----
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("字号："))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 72)
        self.size_spin.setSuffix(" pt")
        self.size_spin.valueChanged.connect(self._on_prop_changed)
        size_layout.addWidget(self.size_spin)
        size_layout.addStretch()
        layout.addLayout(size_layout)

        # ---- 插入提示文本 ----
        layout.addSpacing(5)
        hint_label = QLabel(
            "提示：不支持调整行高。如需调整，可以自己用工具或者让 AI 写脚本改一个 ttf 或 otf 字体文件，"
            "生成新的字体并安装后再来选择。"
        )
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: #888888; font-style: italic;")
        layout.addWidget(hint_label)

        layout.addSpacing(10)

        # ---- 文字颜色 ----
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("文字颜色："))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(40, 30)
        self.color_btn.clicked.connect(lambda: self._choose_color("color"))
        color_layout.addWidget(self.color_btn)
        color_layout.addStretch()
        layout.addLayout(color_layout)

        layout.addSpacing(10)

        # ---- 背景颜色 ----
        bg_layout = QHBoxLayout()
        bg_layout.addWidget(QLabel("背景颜色："))
        self.bg_btn = QPushButton()
        self.bg_btn.setFixedSize(40, 30)
        self.bg_btn.clicked.connect(lambda: self._choose_color("background-color"))
        bg_layout.addWidget(self.bg_btn)
        bg_layout.addStretch()
        layout.addLayout(bg_layout)

        layout.addSpacing(10)

        # ---- 按钮 ----
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.setDefault(True)

        ok_btn.clicked.connect(self._on_ok)
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    # ---------- 界面与数据同步 ----------
    def _update_ui_from_props(self):
        """将 current_props 显示到控件上"""
        # 字体族
        families = self._parse_families(self.current_props.get("font-family", ""))
        self.family_label.setText(families[0] if families else "")

        # 字号
        size_str = self.current_props.get("font-size", "12pt")
        match = regex.search(r"([\d.]+)", size_str)
        if match:
            self.size_spin.setValue(int(float(match.group(1))))
        else:
            self.size_spin.setValue(12)

        # 颜色
        color = self.current_props.get("color", "#000000")
        self._set_color_button(self.color_btn, color)
        bg = self.current_props.get("background-color", "#ffffff")
        self._set_color_button(self.bg_btn, bg)

    @staticmethod
    def _parse_families(family_str: str) -> List[str]:
        """解析 'font-family' 字符串为列表（去除引号）"""
        if not family_str:
            return []

        families = []
        for part in family_str.split(","):
            part = part.strip().strip("\"'")
            if part:
                families.append(part)

        return families

    @staticmethod
    def _build_family_str(families: List[str]) -> str:
        """将列表转换为带引号的 'font-family' 字符串"""
        return ", ".join(f'"{f}"' for f in families)

    def _set_color_button(self, btn: QPushButton, color_str: str):
        """设置按钮的背景色和边框，保留按钮文字"""
        try:
            if color_str.startswith("#"):
                color = QColor(color_str)
            else:
                color = QColor(color_str)
            if color.isValid():
                # 添加灰色边框和微小圆角，使按钮更明显
                btn.setStyleSheet(
                    f"background-color: {color.name()}; "
                    "border: 1px solid #888888; "
                    "border-radius: 2px;"
                )
            else:
                btn.setStyleSheet(
                    "background-color: gray; "
                    "border: 1px solid #888888; "
                    "border-radius: 2px;"
                )
        except Exception:
            btn.setStyleSheet(
                "background-color: gray; "
                "border: 1px solid #888888; "
                "border-radius: 2px;"
            )

    # ---------- 事件响应 ----------
    def _on_prop_changed(self):
        """字号变化时立即更新 current_props"""
        size_val = self.size_spin.value()
        self.current_props["font-size"] = f"{size_val}pt"

    def _choose_font(self):
        """弹出系统字体对话框，实现第一次插入（4→5），后续替换第一个"""
        family_str = self.current_props.get("font-family", "")
        families = self._parse_families(family_str)
        if not families:
            families = ["Arial", "sans-serif"]

        # 当前主字体及字号
        current_family = families[0]
        size_str = self.current_props.get("font-size", "12pt")
        match = regex.search(r"([\d.]+)", size_str)
        current_size = int(float(match.group(1))) if match else 12

        initial_font = QFont(current_family, current_size)
        dialog = QFontDialog(initial_font, self)
        dialog.setWindowTitle("选择主字体")
        if dialog.exec_() == QFontDialog.Accepted:
            selected = dialog.selectedFont()
            new_family = selected.family()

            # 关键逻辑：当前数量为 4 时插入，否则替换第一个
            if len(families) == 4:
                families.insert(0, new_family)  # 变成 5 个
            else:
                families[0] = new_family  # 只替换第一个

            self.current_props["font-family"] = self._build_family_str(families)
            self.family_label.setText(new_family)  # 更新显示

            # 同步字号（如果用户在字体对话框中修改了大小）
            new_size = selected.pointSize()
            if new_size > 0:
                self.current_props["font-size"] = f"{new_size}pt"
                self.size_spin.setValue(new_size)

    def _choose_color(self, prop_key: str):
        """弹出系统颜色对话框，更新指定颜色属性"""
        current = self.current_props.get(prop_key, "#000000")
        if current.startswith("#"):
            initial = QColor(current)
        else:
            initial = QColor(current)
        if not initial.isValid():
            initial = QColor(0, 0, 0)

        color = QColorDialog.getColor(initial, self, "选择颜色")
        if color.isValid():
            hex_str = color.name()
            self.current_props[prop_key] = hex_str
            if prop_key == "color":
                self._set_color_button(self.color_btn, hex_str)
            else:
                self._set_color_button(self.bg_btn, hex_str)

    def _on_ok(self):
        """确定：保存当前属性到 result_props 并关闭"""
        self.result_props = self.current_props.copy()
        self.accept()

    # ---------- 外部接口 ----------
    def get_selected_props(self) -> Optional[Dict[str, str]]:
        """返回用户确认后的样式属性字典，若取消则返回 None"""
        return self.result_props
