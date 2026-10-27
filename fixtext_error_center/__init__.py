"""FixText M2-T2.4 · 人话错误体系（独立模块）。

后续各卡统一 ``import fixtext_error_center as error_center`` 使用：
- 出错的地方 ``error_center.report(exc, context=...)``；
- Qt 槽 / 长任务入口套 ``@error_center.guard``；
- 主程序入口 ``error_center.install_app_hooks()`` + ``diaglog.init(...)``。

契约：界面只呈现 messages.py 的人话文案；技术细节只进诊断日志。
"""

from .center import (
    Resolved,
    UserFacingError,
    guard,
    guard_with_context,
    install_app_hooks,
    uninstall_app_hooks,
    on_report,
    report,
    resolve,
    set_dialog_host,
    set_dialog_shower,
)
from .classify import classify, format_technical
from .diaglog import init, last_record, log_dir, log_path, read_records
from .error_codes import CATEGORY_OF, ENGINE_CODE_MAP, ErrorCode
from .messages import FORBIDDEN_TERMS, all_codes, get_message

__version__ = "1.0.0"

__all__ = [
    "ErrorCode", "CATEGORY_OF", "ENGINE_CODE_MAP",
    "Resolved", "UserFacingError",
    "resolve", "report", "classify", "format_technical",
    "guard", "guard_with_context",
    "install_app_hooks", "uninstall_app_hooks",
    "set_dialog_host", "set_dialog_shower", "on_report",
    "init", "log_dir", "log_path", "read_records", "last_record",
    "get_message", "all_codes", "FORBIDDEN_TERMS",
]
