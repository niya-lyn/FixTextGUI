"""
FixText V1 · Qt 令牌单一来源（Single Source of Truth）
========================================================

本模块是 FixText V1 在 Qt / PySide6 侧的**唯一令牌来源**。

- 所有数值逐字对应 `FixText_V1_设计系统_薄地基.html` 的 `:root` 块（71 项）。
- `build_qss.py` 读取本模块生成 `fixtext.qss`；原型 HTML 里的 `:root` 复制块
  仅作离线预览用途，不再作为 Qt 交付的令牌来源。

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
    "success":        "#15803D",
    "success.bg":     "#E7F4EC",
    "success.border": "#B6E0C5",
    "warning":        "#B45309",
    "warning.bg":     "#FBF1DF",
    "warning.border": "#F0D6A8",
    "error":        "#C0392B",
    "error.bg":     "#FBEAE8",
    "error.border": "#F1C4BD",
    "info":         "#3F48A2",
    "info.bg":      "#ECEEF9",
    "info.border":  "#C8CDEC",
    "focus":        "#4F59C0",
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
    # v3 合并版原型 :root 六档（更新记录 §1 质感打磨后的最终值）；
    # 快照 reference/design_root_snapshot.css 已同步改为 v3 :root 节选。
    "xs":     "0 1px 2px rgba(21,25,31,.05)",
    "sm":     "0 1px 2px rgba(21,25,31,.05), 0 1px 3px rgba(21,25,31,.06)",
    "md":     "0 6px 16px rgba(21,25,31,.08), 0 2px 4px rgba(21,25,31,.04)",
    "lg":     "0 24px 48px rgba(21,25,31,.16), 0 8px 16px rgba(21,25,31,.08)",
    "primary": "0 8px 20px rgba(79,89,192,.34)",
    "focus":  "0 0 0 3px rgba(79,89,192,.24)",
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


def px(value: str) -> int:
    """'12px' -> 12"""
    return int(str(value).replace("px", ""))


# ---------------------------------------------------------------------------
# 应用外壳尺寸（窗口级常量，不属于设计地基的色彩/字号令牌）
# ---------------------------------------------------------------------------

APP_NAME = "FixText"
APP_TITLE = "FixText V1"
RAIL_WIDTH = 212
# 默认窗口按「左轨 212 + 检查问题页最小宽 947 + 内容区左右留白 40」反推，
# 最小宽 1220 = 947（检查页两栏最小宽）+ 212（左轨）+ 40（内容留白）+ 竖向滚动条余量，
# 保证从最小尺寸到默认尺寸都不会出现横向滚动条（不裁切、不挤压）。
WINDOW_W, WINDOW_H = 1280, 820
WINDOW_MIN_W, WINDOW_MIN_H = 1220, 700
# v3 质感层：大屏收束——内容区超过这个宽度后居中收束（原型 .main max-width）
CONTENT_MAX_W = 1280
# 设置页路由键（不在左轨六入口里，由顶栏 ⚙ 进入）
SETTINGS_KEY = "settings"

# ---------------------------------------------------------------------------
# v3 质感层派生常量（原型质感规则里的字面值，:root 没有对应变量，集中在此管理）
# ---------------------------------------------------------------------------

#: 顶栏竖直渐变（180deg）：上端 → 主色带 → 下端（原型 #TopBar linear-gradient）
TOPBAR_GRADIENT_TOP = "#1C2230"
TOPBAR_GRADIENT_BOTTOM = "#10141B"
#: 顶栏底部高光描边（原型 border-bottom rgba(255,255,255,.07)）
TOPBAR_EDGE = "rgba(255,255,255,.07)"
#: 顶栏图标按钮底色 / 悬停底色（原型 .icon-btn，白色半透明）
TOPBAR_ICON_BG = "rgba(255,255,255,.14)"
TOPBAR_ICON_BG_HOVER = "rgba(255,255,255,.22)"
#: 图标字形尺寸（原型 .icon-btn font-size:15px；页头浅色图标按钮同款）
ICON_GLYPH_SIZE = "15px"
#: 左轨「建设中」小标签字号（原型 .n-tag font-size:10px）
MICRO_TAG_SIZE = "10px"


# ---------------------------------------------------------------------------
# 六入口定义（左轨常驻顺序 = 本表顺序，共 6 项）
#
# status: "ready" 已可用 / "building" 建设中
# 文案一律用用户话术，不出现内部目录、文件名与格式术语。
# ---------------------------------------------------------------------------

ENTRIES = [
    dict(
        key="import", icon="📥", label="导入书籍", status="ready",
        short="拖放或选择 TXT / EPUB，自动识别编码并转成通用文本",
        what=[
            "把书拖进窗口就能用，不需要事先改格式、改编码。",
            "GBK、GB18030 这类中文编码由软件自己认出来，转好之后用一句话告诉你转成了什么。",
            "导入时会复制一份给软件自己用，你的原文件不会被改动。",
        ],
    ),
    dict(
        key="oneclick", icon="⚡", label="一键校正", status="ready",
        short="排版、词库替换、标点统一一次跑完，随时可停",
        what=[
            "点一下就把排版、词库替换、标点统一跑完，不用挑词库组合。",
            "跑的过程中有进度和剩余时间，跑到一半想停就停，不会留下半截结果。",
            "动手之前会自动留一份原样，跑坏了可以退回去。",
        ],
    ),
    dict(
        key="check", icon="🔍", label="检查问题", status="ready",
        short="引号配对检查，一处一处确认，改错了能撤回",
        what=[
            "检查全文的中文引号配对是否出错，把每一处的位置列出来。",
            "点一条就跳到正文对应位置，你可以逐处确认、修复或跳过。",
            "改错了能撤回；一次批量改很多处之前，会先告诉你影响多少条。",
        ],
    ),
    dict(
        key="vocab", icon="📚", label="词库管理", status="ready",
        short="查词、查重、删除、合并，改动前先给你看清单",
        what=[
            "在这里查一个词会被换成什么，也可以往词库里加你自己的词。",
            "查重会告诉你哪些词条互相打架，删除和合并前都会先列出清单让你确认。",
            "每次改动都留了记录，删错了、合并错了都能退回去。",
        ],
    ),
    dict(
        key="export", icon="📤", label="导出结果", status="ready",
        short="导出干净的 TXT，EPUB 进来的还原回 EPUB",
        what=[
            "导出一份干净文本，可以直接丢进常见阅读器。",
            "如果书是用 EPUB 导进来的，导出时会还原成 EPUB，打开就能看。",
            "每次导出会自动附一份「改了哪些地方」的统计文件，存在导出的同一个地方。",
        ],
    ),
    dict(
        key="history", icon="🕓", label="历史记录", status="ready",
        short="每次校正都留一条记录，能退回到任一次",
        what=[
            "每校正一本书记一条：书名、时间、改了多少处。",
            "可以从任意一条记录退回当时的样子，也可以把那次的结果重新导出。",
            "删记录要你确认两次；「全部清空」是彻底删除，同样先确认。",
        ],
    ),
]

ENTRY_BY_KEY = {e["key"]: e for e in ENTRIES}

# 已可用入口（用于「现在可以先去这里」引导）
READY_KEYS = [e["key"] for e in ENTRIES if e["status"] == "ready"]

# 首页概览页键（内容区页，不是左轨入口）
HOME_KEY = "home"

STATUS_TEXT = {"ready": "可用", "building": "建设中"}

if __name__ == "__main__":
    print("primary.500 =", c("primary.500"))
    print("entries =", [e["label"] for e in ENTRIES])
