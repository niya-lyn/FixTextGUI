"""
FixText V1 · Qt 令牌单一来源（Single Source of Truth）
========================================================

本模块是 FixText V1 在 Qt / PySide6 侧的**唯一令牌来源**。

- 所有数值逐字对应 `FixText_V1_设计系统_薄地基.html` 的 `:root` 块。
- `build_qss.py` 读取本模块生成 `fixtext.qss`；原型 HTML 里的 `:root` 复制块
  仅作离线预览用途，不再作为 Qt 交付的令牌来源（见决策文档「Qt 交付阶段待办」）。

设计约定（与薄地基一致）：
- 颜色：primary 50–900 主色阶；neutral 0–900 中性阶；success/warning/error/info
  语义色均含 文本色 / 背景色 / 边框色 三件套；focus 为焦点环色。
- 字号：xs12 / sm13 / base14 / md16 / lg18 / xl20 / 2xl24 / 3xl30 / 4xl36。
- 圆角：sm4 / md8 / lg12 / xl16 / full999。
- 间距：以 4px 为基，1=4 2=8 3=12 4=16 5=20 6=24 8=32 10=40 12=48 16=64。
- 阴影：sm/md/lg 三档 + focus 环。
"""

# ---------------------------------------------------------------------------
# 颜色令牌（hex 字符串；Qt 端以 #RRGGBB 直接使用）
# ---------------------------------------------------------------------------

COLORS = {
    # 主色阶
    "primary.50":  "#EEF0FB",
    "primary.100": "#DDE1F6",
    "primary.200": "#C0C6EE",
    "primary.300": "#9AA3E2",
    "primary.400": "#6F79D1",
    "primary.500": "#4F59C0",
    "primary.600": "#3F48A2",
    "primary.700": "#333B83",
    "primary.800": "#2B3169",
    "primary.900": "#232852",
    # 中性阶
    "neutral.0":   "#FFFFFF",
    "neutral.50":  "#F7F8FA",
    "neutral.100": "#EEF1F5",
    "neutral.200": "#DDE2EA",
    "neutral.300": "#C2CAD6",
    "neutral.400": "#9AA4B4",
    "neutral.500": "#6B7585",
    "neutral.600": "#4A5363",
    "neutral.700": "#333B48",
    "neutral.800": "#222831",
    "neutral.900": "#15191F",
    # 语义色（文本 / 背景 / 边框 三件套）+ 焦点
    "success":       "#15803D",
    "success.bg":    "#E7F4EC",
    "success.border": "#B6E0C5",
    "warning":       "#B45309",
    "warning.bg":    "#FBF1DF",
    "warning.border": "#F0D6A8",
    "error":       "#C0392B",
    "error.bg":    "#FBEAE8",
    "error.border": "#F1C4BD",
    "info":       "#3F48A2",
    "info.bg":    "#ECEEF9",
    "info.border": "#C8CDEC",
    "focus":      "#4F59C0",
}

# ---------------------------------------------------------------------------
# 字体令牌
# ---------------------------------------------------------------------------

FONT_SANS = '"Segoe UI","Microsoft YaHei UI","PingFang SC","Microsoft YaHei",system-ui,sans-serif'
FONT_MONO = '"Cascadia Code","JetBrains Mono",Consolas,monospace'

FONT_SIZE = {
    "xs": "12px", "sm": "13px", "base": "14px", "md": "16px", "lg": "18px",
    "xl": "20px", "2xl": "24px", "3xl": "30px", "4xl": "36px",
}

FONT_WEIGHT = {
    "regular": "400", "medium": "500", "semibold": "600", "bold": "700",
}

LINE_HEIGHT = {
    "tight": "1.25", "normal": "1.5", "relaxed": "1.7",
}

# ---------------------------------------------------------------------------
# 间距 / 圆角 / 阴影 令牌
# ---------------------------------------------------------------------------

SPACE = {
    "1": "4px", "2": "8px", "3": "12px", "4": "16px", "5": "20px",
    "6": "24px", "8": "32px", "10": "40px", "12": "48px", "16": "64px",
}

RADIUS = {
    "sm": "4px", "md": "8px", "lg": "12px", "xl": "16px", "full": "999px",
}

SHADOW = {
    "sm":   "0 1px 2px rgba(21,25,31,.06), 0 1px 3px rgba(21,25,31,.08)",
    "md":   "0 4px 10px rgba(21,25,31,.08), 0 2px 4px rgba(21,25,31,.06)",
    "lg":   "0 12px 28px rgba(21,25,31,.12), 0 4px 8px rgba(21,25,31,.06)",
    "focus": "0 0 0 3px rgba(79,89,192,.28)",
}

# ---------------------------------------------------------------------------
# 派生便捷访问（供 build_qss / 业务代码调用）
# ---------------------------------------------------------------------------

def c(key: str) -> str:
    """取颜色令牌，如 c('primary.500') / c('success.bg')。"""
    return COLORS[key]


def sp(key: str) -> str:
    """取间距令牌，如 sp('4') -> '16px'。"""
    return SPACE[key]


def r(key: str) -> str:
    return RADIUS[key]


def fs(key: str) -> str:
    return FONT_SIZE[key]


# 模块清单（左轨 6 入口 + 首页概览），顺序即轨中顺序
MODULES = [
    ("home",    "🏠", "首页概览"),
    ("import",  "📥", "导入书籍"),
    ("oneclick","⚡", "一键校正"),
    ("check",   "🔍", "检查问题"),
    ("vocab",   "📚", "词库管理"),
    ("export",  "📤", "导出结果"),
    ("history", "🕓", "历史记录"),
]

# 每个模块的占位说明（指向对应的 HTML 原型，内容后续逐步移植）
MODULE_PROTO = {
    "import":  "FixText_V1_导入书籍_原型.html",
    "oneclick":"FixText_V1_一键校正_原型.html",
    "check":   "FixText_V1_检查问题_原型.html",
    "vocab":   "FixText_V1_词库管理_原型.html",
    "export":  "FixText_V1_导出结果_原型.html",
    "history": "FixText_V1_历史记录_原型.html",
}

if __name__ == "__main__":
    print("primary.500 =", c("primary.500"))
    print("modules =", [m[2] for m in MODULES])
