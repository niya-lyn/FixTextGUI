# -*- mode: python ; coding: utf-8 -*-
"""FixText V1 · PyInstaller 打包配置（M4-T4.1b）

目标形态：**绿色版 onedir**（不是 onefile）——解压即用、可整体搬走、
启动快；onefile 每次启动都要解压到临时目录，不适合 10MB 词库 + 4MB 引擎。

产物布局（默认 contents_directory，程序内部文件都收在 `_internal/`）：

    <包根>/FixTextGUI(.exe)            主程序
    <包根>/_internal/               程序内部文件（Qt 插件、Python 运行时）
    <包根>/data/rules/              词库规则（构建脚本拷贝，出厂只读）
    <包根>/pipeline/vendor/.../bin/  Go 替换引擎（构建脚本拷贝，只带目标平台那一个）
    <包根>/reference/               设计依据目录（构建脚本拷贝）
    <包根>/workspace/               用户区：**运行时生成，绝不进包**
    （不附带示例书；用户导入自己的书）

**打包清单里显式排除 `workspace/`**：它装的是「当前打开哪本书 / 看过向导没有」
这类运行时状态。把它打进包会让新用户首次启动直接跳过新手向导（实测：
`settings.ini` 带 `wizardSeen=1` 时 `opens_on_first_run()` 返回 False）。
出厂默认词库只从 `data/rules/` 来，`workspace/` 一个字节都不带。

构建：`pyinstaller --noconfirm --clean fixtext.spec`
"""

import os
import sys
from pathlib import Path

#: spec 所在目录即包根（构建脚本从包根调用）
ROOT = Path(SPECPATH).resolve()          # noqa: F821  (PyInstaller 注入)

# ---------------------------------------------------------------- 目标平台
IS_WIN = sys.platform.startswith("win")

#: Go 替换引擎二进制：**只带目标平台那一个**，另一个白占 2.6MB。
#: 文件名与 fixtext_pipeline/engine_selector.py 保持一致（那边是唯一选择入口）。
ENGINE_BIN = (
    "replace_by_go-windows-amd64.exe" if IS_WIN else "replace_by_go-linux-amd64"
)
ENGINE_REL = Path("pipeline") / "vendor" / "fixtext" / "engine" / "go_src" / "bin"


# ------------------------------------------------------------ 隐藏导入扫描
def _hidden_imports() -> list[str]:
    """扫出所有会被动态导入、静态分析看不到的模块。

    两类必然漏掉：
    1. `fixtext_ui/` 没有 `__init__.py`，是 `sys.path` 平级目录——里面每个文件
       都是顶层模块，靠 `import_module` / `main_window` 这类平级 import 拉起；
    2. `pipeline/vendor/` 下的引擎包由 `vendor_bootstrap` 用
       `importlib.import_module()` 按字符串加载，静态分析完全看不见。
    漏掉的后果不是崩溃而是「功能静默缺失」：词库找不到、引擎起不来。
    """
    names: list[str] = []

    # 1. fixtext_ui 平级模块（含 build_qss：打包后重新生成样式表要用）
    ui_dir = ROOT / "fixtext_ui"
    for f in sorted(ui_dir.glob("*.py")):
        if f.stem not in ("__init__", "__main__"):
            names.append(f.stem)

    # 2. 普通包：递归收所有子模块
    def walk_pkg(pkg_dir: Path, prefix: str) -> None:
        for f in sorted(pkg_dir.glob("*.py")):
            if f.stem.startswith("__"):
                continue
            names.append(f"{prefix}.{f.stem}")
        for sub in sorted(p for p in pkg_dir.iterdir() if p.is_dir()):
            if sub.name.startswith(("__", ".")) or sub.name == "__pycache__":
                continue
            if (sub / "__init__.py").is_file():
                names.append(f"{prefix}.{sub.name}")
                walk_pkg(sub, f"{prefix}.{sub.name}")

    for pkg in ("fixtext_import", "fixtext_error_center"):
        if (ROOT / pkg / "__init__.py").is_file():
            names.append(pkg)
            walk_pkg(ROOT / pkg, pkg)

    names.append("fixtext_pipeline")
    walk_pkg(ROOT / "pipeline" / "fixtext_pipeline", "fixtext_pipeline")

    # 3. vendor 引擎包：顶层包名 + 递归子模块
    vdir = ROOT / "pipeline" / "vendor"
    for pkg_dir in sorted(p for p in vdir.iterdir() if p.is_dir()):
        if not (pkg_dir / "__init__.py").is_file():
            continue
        names.append(pkg_dir.name)
        walk_pkg(pkg_dir, pkg_dir.name)

    # 4. 第三方 C 扩展：包名与导入名不一致（pyahocorasick -> ahocorasick）
    for mod in ("ahocorasick", "lxml.etree", "lxml._elementpath"):
        names.append(mod)

    # 5. 打包冒烟模块：只在试打包时收进包（正式绿色包不含，见构建脚本）
    if os.environ.get("FIXTEXT_SMOKE") == "1":
        names.append("fxbundle_smoke")

    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ------------------------------------------------------------------ 数据文件
datas: list[tuple[str, str]] = []

# 样式表：main_window 按 __file__ 同目录找它（冻结后被平铺进 _internal）
_qss = ROOT / "fixtext_ui" / "fixtext.qss"
if _qss.is_file():
    datas.append((str(_qss), "."))

# 设计依据目录（reference/）：主窗口按**包根**定位并「打开目录」给用户看，
# 所以它也必须落在包根（由构建脚本拷），不能进 _internal。

# 注意：datas 里的东西会被放进 `_internal/`（程序内部目录），**用户看不到**。
# 所以用户需要看见 / 需要自己打开的目录（data/rules、pipeline 引擎、
# reference）不写在这里，而由构建脚本拷到包根——绿色包解压后目录结构一眼能懂。
# 产品不附带「示例书」。

#: 明确不进包的东西（写出来是为了让审查者一眼看到边界，而不是靠默认行为）
EXCLUDED_FROM_PACKAGE = [
    "workspace",   # 用户区：运行时生成。进包会让新用户跳过新手向导
    "runs",        # 校正工作目录：运行时产物
    "logs",        # 诊断日志：运行时产物
    ".git",        # 版本库
    "tests",       # 测试代码与测试用样本书
    "tools",       # 验收脚本
    "evidence",    # 验收证据
    "screenshots", # 截图
]


# -------------------------------------------------------------------- 构建
a = Analysis(                          # noqa: F821
    [str(ROOT / "main_app.py")],
    pathex=[
        str(ROOT),
        str(ROOT / "fixtext_ui"),      # 平级模块目录
        str(ROOT / "pipeline"),        # fixtext_pipeline
        str(ROOT / "pipeline" / "vendor"),  # 引擎包
    ],
    binaries=[],
    datas=datas,
    hiddenimports=_hidden_imports(),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 明确排除：把整个用户区/版本库从分析入口就挡掉，避免误收
    excludes=["tkinter", "unittest", "pydoc", "doctest",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtQuick",
              "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)                      # noqa: F821

exe = EXE(                             # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FixTextGUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                         # UPX 会显著提高杀软误报率，不开
    console=False,                     # 窗口程序，不要黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(                        # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    # 默认 _internal：程序内部文件收进子目录，包根只留主程序 + 可见的数据目录
    name="FixTextGUI",
)
