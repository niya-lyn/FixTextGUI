import re

class OutputFormatter:
    """支持 256 色、粗体、下划线、背景色的 ANSI 转 HTML 格式化器"""

    # 标准 ANSI 转义序列正则
    ANSI_ESCAPE_RE = re.compile(r"\x1b\[([\d;]*)m")

    # 基本色映射（前景 30-37 / 90-97 和背景 40-47 / 100-107）
    BASE_COLORS = {
        30: "#000000",
        31: "#cd3131",
        32: "#0dbc79",
        33: "#e5e510",
        34: "#2472c8",
        35: "#bc3fbc",
        36: "#11a8cd",
        37: "#e5e5e5",
        90: "#666666",
        91: "#f14c4c",
        92: "#23d18b",
        93: "#f5f543",
        94: "#3b8eea",
        95: "#d670d6",
        96: "#29b8db",
        97: "#e5e5e5",
    }
    # 背景色的基本色映射（40-47 -> 同前景色值，100-107 -> 同高亮色值）
    BASE_BG_COLORS = {
        40: "#000000",
        41: "#cd3131",
        42: "#0dbc79",
        43: "#e5e510",
        44: "#2472c8",
        45: "#bc3fbc",
        46: "#11a8cd",
        47: "#e5e5e5",
        100: "#666666",
        101: "#f14c4c",
        102: "#23d18b",
        103: "#f5f543",
        104: "#3b8eea",
        105: "#d670d6",
        106: "#29b8db",
        107: "#e5e5e5",
    }

    def __init__(self):
        # 跨行持久化状态
        self.fg_color = None  # 当前前景色（CSS 颜色字符串）
        self.bg_color = None  # 当前背景色
        self.bold = False
        self.underline = False
        self.italic = False

    @staticmethod
    def _escape_html(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    @staticmethod
    def _color_index_to_rgb(index):
        """将 xterm 256 色索引转换为 HTML 颜色字符串"""
        if index < 0 or index > 255:
            return "#ffffff"
        # 0-15：标准终端颜色
        standard = [
            "#000000",
            "#cd0000",
            "#00cd00",
            "#cdcd00",
            "#0000ee",
            "#cd00cd",
            "#00cdcd",
            "#e5e5e5",
            "#7f7f7f",
            "#ff0000",
            "#00ff00",
            "#ffff00",
            "#5c5cff",
            "#ff00ff",
            "#00ffff",
            "#ffffff",
        ]
        if index < 16:
            return standard[index]
        # 16-231：216 色立方体 (6×6×6)
        if index <= 231:
            index -= 16
            r = (index // 36) * 51
            g = ((index % 36) // 6) * 51
            b = (index % 6) * 51
            return f"#{r:02x}{g:02x}{b:02x}"
        # 232-255：24 级灰度
        gray = (index - 232) * 10 + 8
        return f"#{gray:02x}{gray:02x}{gray:02x}"

    def format_html(self, text):
        # 统一换行符，按行处理
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        formatted_lines = []
        for i, line in enumerate(lines):
            # 先转义 HTML
            escaped = self._escape_html(line)
            preserved = escaped.replace(" ", "&nbsp;")
            # 应用 ANSI 样式
            html_line = self._convert_line(preserved)
            formatted_lines.append(html_line)
            if i < len(lines) - 1:
                formatted_lines.append("<br>")
        return "".join(formatted_lines)

    def _convert_line(self, line):
        """解析行内 ANSI 转义码并返回带 <span> 的 HTML"""
        parts = []
        last_end = 0

        for match in self.ANSI_ESCAPE_RE.finditer(line):
            # 转义码之前的纯文本
            plain = line[last_end : match.start()]
            if plain:
                parts.append(self._wrap_style(plain))
            # 解析转义码序列
            codes_str = match.group(1)
            if codes_str:
                codes = [int(c) for c in codes_str.split(";") if c]
            else:
                codes = [0]  # \x1b[m 等价于重置

            i = 0
            while i < len(codes):
                c = codes[i]
                if c == 0:  # 重置
                    self.fg_color = None
                    self.bg_color = None
                    self.bold = False
                    self.underline = False
                    self.italic = False
                elif c == 1:
                    self.bold = True
                elif c == 3:
                    self.italic = True
                elif c == 4:
                    self.underline = True
                elif 30 <= c <= 37 or 90 <= c <= 97:
                    # 基本前景色（如果粗体且为基础色30-37，自动提升为高亮色）
                    if self.bold and 30 <= c <= 37:
                        self.fg_color = self.BASE_COLORS.get(c + 60, self.BASE_COLORS[c])
                    else:
                        self.fg_color = self.BASE_COLORS.get(c)
                elif 40 <= c <= 47 or 100 <= c <= 107:
                    # 基本背景色
                    if self.bold and 40 <= c <= 47:
                        self.bg_color = self.BASE_BG_COLORS.get(c + 60, self.BASE_BG_COLORS[c])
                    else:
                        self.bg_color = self.BASE_BG_COLORS.get(c)
                elif c == 38:  # 扩展前景色
                    if i + 2 < len(codes) and codes[i + 1] == 5:
                        idx = codes[i + 2]
                        self.fg_color = self._color_index_to_rgb(idx)
                        i += 2
                elif c == 48:  # 扩展背景色
                    if i + 2 < len(codes) and codes[i + 1] == 5:
                        idx = codes[i + 2]
                        self.bg_color = self._color_index_to_rgb(idx)
                        i += 2
                # 忽略其他未知代码
                i += 1

            last_end = match.end()

        # 剩余文本
        remaining = line[last_end:]
        if remaining:
            parts.append(self._wrap_style(remaining))
        return "".join(parts)

    def _wrap_style(self, text):
        """用当前样式包裹文本"""
        styles = []
        if self.fg_color:
            styles.append(f"color:{self.fg_color}")
        if self.bg_color:
            styles.append(f"background-color:{self.bg_color}")
        if self.bold:
            styles.append("font-weight:bold")
        if self.underline:
            styles.append("text-decoration:underline")
        if self.italic:
            styles.append("font-style:italic")

        if styles:
            return f'<span style="{";".join(styles)};">{text}</span>'
        return text
