"""统一异常处理层（M2-T2.4 核心）——全应用唯一的错误出口。

对外 API（后续 T2.1–T2.3 / M3 各卡统一 import 这一层）：

=====================  =====================================================
``UserFacingError``    UI/业务层已判定错误时抛出的带码异常；
``resolve()``          异常或码 → ``Resolved``（人话 what + guidance + 参考码）；
``report()``           归类 + 写诊断日志 + 弹错误卡（有 Qt 环境时）→ 返回 Resolved；
``guard()``            装饰器：包住 Qt 槽函数 / 长任务入口，异常自动走 report；
``install_app_hooks()`` 应用级兜底：sys.excepthook / threading.excepthook，
                        未枚举异常 → 通用兜底文案 + 技术细节进日志，不崩溃；
``set_dialog_host()``  注册错误卡挂靠的父窗口（主窗口初始化时调用）。
=====================  =====================================================

行为契约：
- report/guard **永不抛异常**：展示或日志失败时静默降级（只保证不再炸）；
- 界面上出现的字符串全部来自 messages.py 映射表（+ 调用方显式提供的
  ``safe_hint``，约定其必须是已面向用户的文案，不得是异常原文）；
- 任何异常的 traceback / 类名 / errno 只写入诊断日志，绝不返回给界面。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .classify import classify, format_technical
from .diaglog import write_record
from .error_codes import ErrorCode
from .messages import get_message


@dataclass
class UserFacingError(Exception):
    """带用户错误码的异常——上游已判定类别时使用。

    code 须是 ErrorCode 枚举值字符串（如 ``"U-I02"``）。
    safe_hint 可选：已确认面向用户的补充短语（如文件名），会显示在卡片上。
    """

    code: str
    safe_hint: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(f"[{self.code}]" + (f" {self.safe_hint}" if self.safe_hint else ""))


@dataclass
class Resolved:
    """一次错误归类的完整结果（界面侧只用 code/title/what/guidance/safe_hint）。"""

    code: str
    title: str
    what: str
    guidance: str
    category: str
    safe_hint: str | None = None
    log_path: str | None = None       # 本次写入的诊断日志文件（证据用）
    exc_type: str | None = None       # 只进日志/排障用，界面不展示


_DIALOG_HOST = None          # 错误卡挂靠的 QWidget（弱引用语义：使用时校验存活）
_DIALOG_SHOWER: Callable[..., Any] | None = None   # 可替换的展示函数（测试注入）
_on_report_callbacks: list[Callable[[Resolved], None]] = []


# ---------------------------------------------------------------------------
# resolve / report
# ---------------------------------------------------------------------------

def resolve(exc_or_code: "BaseException | str | UserFacingError",
            context: str | None = None) -> Resolved:
    """异常（或错误码）→ 人话结果。纯函数：不弹窗、不写日志、永不抛。"""
    try:
        if isinstance(exc_or_code, str):
            code = exc_or_code
            hint = None
            exc_type = None
        else:
            code = classify(exc_or_code, context)
            hint = getattr(exc_or_code, "safe_hint", None)
            exc_type = f"{type(exc_or_code).__module__}.{type(exc_or_code).__qualname__}"
        msg = get_message(code)
        return Resolved(
            code=code, title=msg["title"], what=msg["what"],
            guidance=msg["guidance"], category=msg["category"],
            safe_hint=hint, exc_type=exc_type,
        )
    except Exception:
        msg = get_message(ErrorCode.RUNTIME_UNEXPECTED.value)
        return Resolved(code=ErrorCode.RUNTIME_UNEXPECTED.value, title=msg["title"],
                        what=msg["what"], guidance=msg["guidance"],
                        category=msg["category"])


def report(exc_or_code: "BaseException | str | UserFacingError",
           context: str | None = None,
           parent: Any = None,
           safe_hint: str | None = None) -> Resolved:
    """统一错误出口：归类 → 诊断日志 → 界面错误卡。返回 Resolved。

    parent：可选的挂靠窗口；None 时用 set_dialog_host 注册的主窗口。
    safe_hint：调用方显式提供的面向用户短语（如书名），仅当传入 str/码时生效
    （传异常对象时以异常自身的 safe_hint 为准）。
    """
    resolved = resolve(exc_or_code, context)
    if safe_hint and not isinstance(exc_or_code, BaseException):
        resolved.safe_hint = safe_hint

    # 技术细节 → 日志（唯一去处）
    if isinstance(exc_or_code, BaseException):
        technical = format_technical(exc_or_code, context)
    else:
        technical = {"exc_type": None, "message": None, "errno": None,
                     "engine_code": None, "context": context, "traceback": ""}
    try:
        path = write_record(resolved.code, resolved.title, technical)
        resolved.log_path = path
    except Exception:
        pass

    # 界面 → 人话错误卡
    try:
        _show_dialog(resolved, parent)
    except Exception:
        pass

    for cb in list(_on_report_callbacks):
        try:
            cb(resolved)
        except Exception:
            pass
    return resolved


def on_report(cb: Callable[[Resolved], None]) -> None:
    """注册 report 回调（测试取证 / 未来的遥测用）。"""
    _on_report_callbacks.append(cb)


# ---------------------------------------------------------------------------
# 展示层（默认 Qt；无 Qt 环境自动跳过）
# ---------------------------------------------------------------------------

def set_dialog_host(host: Any) -> None:
    """主窗口初始化时调用：错误卡默认挂靠它。"""
    global _DIALOG_HOST
    _DIALOG_HOST = host


def set_dialog_shower(shower: Callable[[Resolved, Any], Any] | None) -> None:
    """替换/恢复展示函数（测试里注入无头收集器；None 恢复默认）。"""
    global _DIALOG_SHOWER
    _DIALOG_SHOWER = shower


def _show_dialog(resolved: Resolved, parent: Any = None) -> None:
    if _DIALOG_SHOWER is not None:
        _DIALOG_SHOWER(resolved, parent)
        return
    # Qt 控件只能在主线程创建：worker 线程的异常经投递队列转到主线程弹卡
    if threading.current_thread() is not threading.main_thread():
        from .qt_bridge import show_error_card_threadsafe  # 延迟导入

        show_error_card_threadsafe(resolved, parent)
        return
    from .qt_bridge import show_error_card  # 延迟导入，无 Qt 环境不炸

    show_error_card(resolved, parent)


def _host_alive(parent: Any) -> Any:
    """挑一个存活的挂靠窗口（parent 优先，其次全局 host）。"""
    target = parent if parent is not None else _DIALOG_HOST
    if target is None:
        return None
    try:  # Qt C++ 对象可能已销毁
        _ = target.isVisible
        return target
    except RuntimeError:
        return None


# ---------------------------------------------------------------------------
# guard 装饰器
# ---------------------------------------------------------------------------

def guard(fn: Callable) -> Callable:
    """装饰器：函数/槽内异常统一走 report，返回 None（不崩溃、不外泄）。

    用法（Qt 槽 / 按钮回调 / 长任务入口）::

        @error_center.guard
        def do_import(self):
            ...
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (SystemExit, KeyboardInterrupt, GeneratorExit):
            raise
        except Exception as exc:  # noqa: BLE001 —— 这一层就是全量兜底
            # 第一个位置参数若是 QWidget，当作挂靠父窗口
            parent = None
            for candidate in args:
                if _is_widget(candidate):
                    parent = candidate
                    break
            report(exc, context=getattr(fn, "_error_context", None), parent=parent)
            return None

    return wrapper


def _is_widget(obj: Any) -> bool:
    try:
        from PySide6.QtWidgets import QWidget  # 延迟导入

        return isinstance(obj, QWidget)
    except Exception:
        return False


def guard_with_context(context: str, fn: Callable) -> Callable:
    """guard 的带上下文版本（context 影响 OSError 权限类落点）。"""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (SystemExit, KeyboardInterrupt, GeneratorExit):
            raise
        except Exception as exc:  # noqa: BLE001
            parent = None
            for candidate in args:
                if _is_widget(candidate):
                    parent = candidate
                    break
            report(exc, context=context, parent=parent)
            return None

    return wrapper


# ---------------------------------------------------------------------------
# 应用级兜底钩子
# ---------------------------------------------------------------------------

def install_app_hooks() -> None:
    """安装应用级异常兜底（在 QApplication 创建后、主窗口 show 前调用）。

    覆盖：
    1. ``sys.excepthook`` —— PySide6 6.5+ 的槽函数异常会走到这里
       （实测：安装后不再向 stderr 打印 traceback，且不崩溃）；
    2. ``threading.excepthook`` —— worker 线程未捕获异常。

    未枚举异常 → U-R00 通用兜底文案 + traceback 进日志。
    """
    def _hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, (SystemExit, KeyboardInterrupt)):
            import sys

            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        try:
            report(exc_value if exc_value is not None else exc_type(),
                   context=None)
        except Exception:
            pass

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type in (SystemExit, KeyboardInterrupt, GeneratorExit):
            return
        try:
            exc = args.exc_value if args.exc_value is not None else args.exc_type()
            report(exc, context=f"thread:{args.thread.name if args.thread else '?'}")
        except Exception:
            pass

    # 有 Qt 环境时启动跨线程卡片投递轮询（无 Qt 静默跳过）
    try:
        from .qt_bridge import ensure_bridge

        ensure_bridge()
    except Exception:
        pass

    sys_hook_installed()
    import sys

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


def sys_hook_installed() -> None:
    """占位标记（预留：未来检查钩子是否被第三方覆盖后重装）。"""


def uninstall_app_hooks() -> None:
    """测试用：恢复默认钩子。"""
    import sys

    sys.excepthook = sys.__excepthook__
    threading.excepthook = threading.__excepthook__
