"""异常 → 用户错误码 的归类器（M2-T2.4）。

输入是任意异常对象，输出稳定的用户码（error_codes.ErrorCode）。
归类依据按优先级：

1. ``UserFacingError`` —— 上游已判定，直接透传其 code；
2. 带技术错误码的引擎异常（T0.3 ``EngineError``，有 ``.code`` 属性且形如 ``E\d{4}``）
   —— 查 ENGINE_CODE_MAP 翻译；
3. OS 层异常（OSError 家族）—— 按 errno 与 context（import/processing/export）分流；
4. M1 引擎模块的语义异常 —— 按「模块名 + 类名」匹配（epubtext / bookmap / zipfile 等），
   不 import 这些包也能工作（按名字匹配），import 了则精确 isinstance；
5. 编码类异常（UnicodeDecodeError / LookupError）；
6. 其余一切 → ``U-R00`` 通用兜底。

写法约束：本模块永不抛异常（任何内部意外都回落兜底码）。
"""

from __future__ import annotations

import errno
import io
import traceback

from .error_codes import ErrorCode, engine_code_to_user


# ---------------------------------------------------------------------------
# M1 引擎异常的类型签名（模块前缀 + 类名）。
# 真实定义见：
#   epubtext/src/epubtext/errors.py  —— EpubStructureError / BundleFormatError / RestoreError
#   bookmap/build/fixtext_bookmap/patcher.py —— PatchError
#   标准库 zipfile.BadZipFile
# 这里只记名字，避免对本模块产生硬依赖。
# ---------------------------------------------------------------------------

_ENGINE_CLASS_RULES: tuple[tuple[str, str, str], ...] = (
    # (模块前缀, 类名, 用户码)
    ("epubtext", "EpubTextError", ErrorCode.IMPORT_INTERNAL_DATA.value),
    ("epubtext", "EpubStructureError", ErrorCode.IMPORT_EPUB_STRUCTURE.value),  # 后面再按消息细分
    ("epubtext", "BundleFormatError", ErrorCode.IMPORT_INTERNAL_DATA.value),
    ("epubtext", "RestoreError", ErrorCode.IMPORT_INTERNAL_DATA.value),
    ("fixtext_bookmap", "PatchError", ErrorCode.IMPORT_INTERNAL_DATA.value),
    ("zipfile", "BadZipFile", ErrorCode.IMPORT_FILE_CORRUPT.value),
    ("lxml.etree", "XMLSyntaxError", ErrorCode.IMPORT_EPUB_STRUCTURE.value),
    ("fixtext_import", "EncodingUndetectable", ErrorCode.IMPORT_ENCODING_UNKNOWN.value),
)

# EpubStructureError 内部再细分：消息里带 ZIP 损坏字样 → 文件损坏码
_ZIP_CORRUPT_NEEDLES = ("ZIP 结构损坏", "不是合法的 ZIP", "Bad magic", "Cannot find central directory")

# errno → 用户码（读取侧）
_ERRNO_READ_MAP = {
    errno.ENOENT: ErrorCode.IMPORT_FILE_UNREADABLE.value,
    errno.EISDIR: ErrorCode.IMPORT_FILE_UNREADABLE.value,
    errno.ENOTDIR: ErrorCode.IMPORT_FILE_UNREADABLE.value,
    errno.ENOSPC: ErrorCode.PROC_DISK_FULL.value,
}
# errno → 权限类（读写都可能是）
_PERM_ERRNOS = {errno.EACCES, errno.EPERM, errno.EROFS}


def _looks_like_engine_code(value) -> bool:
    if not isinstance(value, str):
        return False
    return len(value) == 5 and value[0] == "E" and value[1:].isdigit()


def _match_engine_class(exc: BaseException) -> str | None:
    """按 MRO 上的「模块前缀 + 类名」匹配 M1 引擎异常。"""
    try:
        for klass in type(exc).__mro__:
            module = getattr(klass, "__module__", "") or ""
            name = getattr(klass, "__name__", "")
            for prefix, cls_name, code in _ENGINE_CLASS_RULES:
                if name == cls_name and module.startswith(prefix):
                    return code
    except Exception:
        return None
    return None


def _classify_epub_structure(exc: BaseException) -> str:
    """EpubStructureError 细分：ZIP 解包损坏 → 文件损坏码；其余 → 结构异常码。"""
    try:
        text = str(exc)
    except Exception:
        text = ""
    for needle in _ZIP_CORRUPT_NEEDLES:
        if needle in text:
            return ErrorCode.IMPORT_FILE_CORRUPT.value
    return ErrorCode.IMPORT_EPUB_STRUCTURE.value


def classify(exc: BaseException, context: str | None = None) -> str:
    """把任意异常归到用户错误码。

    context 可选值：``"import"`` / ``"processing"`` / ``"export"`` / None。
    只影响 OSError 权限类错误的落点（导出目录写不进去 vs 读取无权限）。
    本函数永不抛异常。
    """
    try:
        return _classify(exc, context)
    except Exception:
        return ErrorCode.RUNTIME_UNEXPECTED.value


def _classify(exc: BaseException, context: str | None) -> str:
    # 1) 上游已判定的用户异常
    from .center import UserFacingError  # 延迟导入避免环

    if isinstance(exc, UserFacingError):
        return exc.code

    # 2) T0.3 引擎异常（带 .code）
    code = getattr(exc, "code", None)
    if _looks_like_engine_code(code):
        mapped = engine_code_to_user(code)
        if mapped:
            return mapped

    # 3) OS 层
    if isinstance(exc, OSError):
        eno = getattr(exc, "errno", None)
        if eno == errno.ENOSPC:
            return ErrorCode.PROC_DISK_FULL.value
        if eno in _PERM_ERRNOS:
            if context == "export":
                return ErrorCode.EXPORT_DIR_UNWRITABLE.value
            return ErrorCode.PROC_NO_PERMISSION.value
        if eno in _ERRNO_READ_MAP:
            return _ERRNO_READ_MAP[eno]
        # 其余 OSError：写侧上下文给导出失败，读侧给读取失败
        if context == "export":
            return ErrorCode.EXPORT_WRITE_FAILED.value
        return ErrorCode.IMPORT_FILE_UNREADABLE.value

    # 4) M1 引擎语义异常（名字匹配）
    matched = _match_engine_class(exc)
    if matched is not None:
        if matched == ErrorCode.IMPORT_EPUB_STRUCTURE.value:
            return _classify_epub_structure(exc)
        return matched

    # 5) 编码类
    if isinstance(exc, UnicodeDecodeError):
        return ErrorCode.IMPORT_ENCODING_UNKNOWN.value
    if isinstance(exc, UnicodeError):
        return ErrorCode.IMPORT_ENCODING_UNKNOWN.value
    if isinstance(exc, LookupError):
        # codecs.lookup 找不到编码名（"不存在的编码"）
        return ErrorCode.IMPORT_ENCODING_UNKNOWN.value
    if isinstance(exc, MemoryError):
        return ErrorCode.RUNTIME_UNEXPECTED.value

    # 6) 兜底
    return ErrorCode.RUNTIME_UNEXPECTED.value


def format_technical(exc: BaseException, context: str | None) -> dict:
    """把技术细节整理成可写入诊断日志的字典（只进日志，永不进界面）。

    包含：异常类全名、消息、errno、引擎码、完整 traceback 文本、context。
    """
    tb = ""
    try:
        buf = io.StringIO()
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=buf)
        tb = buf.getvalue()
    except Exception:
        tb = "(traceback 不可用)"
    return {
        "exc_type": f"{type(exc).__module__}.{type(exc).__qualname__}",
        "message": _safe_str(exc),
        "errno": getattr(exc, "errno", None),
        "engine_code": getattr(exc, "code", None) if _looks_like_engine_code(
            getattr(exc, "code", None)) else None,
        "context": context,
        "traceback": tb,
    }


def _safe_str(exc: BaseException) -> str:
    try:
        return str(exc)
    except Exception:
        return "(消息不可用)"
