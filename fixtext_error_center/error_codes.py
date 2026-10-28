"""FixText V1 · 面向用户的错误码枚举（M2-T2.4）。

分段（与排期 4.4 T2.4 的错误类别一一对应）：
    U-Ixx  导入类：文件读取失败 / 文件损坏 / 编码无法识别 / EPUB 结构异常 / 内部数据不一致
    U-Pxx  处理类：引擎缺失 / 引擎失败 / 超时 / 磁盘空间不足 / 权限不足
    U-Exx  导出类：目标路径不可写 / 写盘失败
    U-Rxx  运行类：意外错误兜底

编码规则：
- 字符串码是稳定契约，只增不改名；
- 与 T0.3 引擎层错误码（E1xxx/E2xxx，机器口径）分属两层：
  引擎码面向程序分流，本表码面向用户呈现；classify.py 负责 E 码 → U 码翻译。
- 「U」= User-facing。
"""

from __future__ import annotations

import enum


class ErrorCode(str, enum.Enum):
    # ---- 导入类 ----
    IMPORT_FILE_UNREADABLE = "U-I01"   # 文件不存在 / 无法读取
    IMPORT_FILE_CORRUPT = "U-I02"      # 文件损坏（无法解包 / ZIP 损坏）
    IMPORT_ENCODING_UNKNOWN = "U-I03"  # 编码无法识别
    IMPORT_EPUB_STRUCTURE = "U-I04"    # EPUB 结构异常
    IMPORT_INTERNAL_DATA = "U-I05"     # 内部工作数据不一致

    # ---- 处理类 ----
    PROC_ENGINE_MISSING = "U-P01"      # 引擎缺失 / 无法执行
    PROC_ENGINE_FAILED = "U-P02"       # 引擎运行失败（含被外部终止）
    PROC_ENGINE_TIMEOUT = "U-P03"      # 处理超时
    PROC_DISK_FULL = "U-P04"           # 磁盘空间不足
    PROC_NO_PERMISSION = "U-P05"       # 权限不足（读/执行）

    # ---- 导出类 ----
    EXPORT_DIR_UNWRITABLE = "U-E01"    # 目标路径不可写
    EXPORT_WRITE_FAILED = "U-E02"      # 写盘失败

    # ---- 运行类 ----
    RUNTIME_UNEXPECTED = "U-R00"       # 未枚举异常的通用兜底


# 分类（用于映射表分组展示与「同类聚合」统计）
CATEGORY_OF = {
    "U-I01": "导入", "U-I02": "导入", "U-I03": "导入",
    "U-I04": "导入", "U-I05": "导入",
    "U-P01": "处理", "U-P02": "处理", "U-P03": "处理",
    "U-P04": "处理", "U-P05": "处理",
    "U-E01": "导出", "U-E02": "导出",
    "U-R00": "运行",
}

# 技术层（T0.3 EngineError）错误码 → 用户码 的翻译表。
# 引擎码定义见 fixtext/engine/errors.py 的 EngineErrorCode。
ENGINE_CODE_MAP = {
    "E1001": "U-P01",            # ENGINE_MISSING
    "E1002": "U-P01",            # ENGINE_NOT_EXECUTABLE
    "E1003": "U-P03",            # ENGINE_TIMEOUT
    "E1004": "U-P02",            # ENGINE_FAILED（非 0 退出 / 被杀）
    "E1005": "U-P02",            # ENGINE_OUTPUT_UNEXPECTED
    "E1006": "U-P01",            # PY_ENGINE_UNAVAILABLE（pyahocorasick 缺失，M4-T4.2）
    "E1900": "U-P02",            # ENGINE_UNKNOWN（引擎范围内兜底）
    "E2101": "U-I01",            # INPUT_MISSING
    "E2102": "U-I01",            # INPUT_UNREADABLE
    "E2201": "U-I05",            # RULES_MISSING（软件自带数据问题）
    "E2202": "U-I05",            # RULES_INVALID_JSON
    "E2203": "U-I05",            # RULES_LENGTH_MISMATCH
    "E2204": "U-I05",            # RULES_EMPTY
    "E2301": "U-I05",            # ARGUMENT_INVALID
    "E2401": "U-E02",            # OUTPUT_WRITE_FAILED
}


def engine_code_to_user(code: str) -> str | None:
    """T0.3 引擎码 → 用户码；未命中返回 None。"""
    return ENGINE_CODE_MAP.get(code)
