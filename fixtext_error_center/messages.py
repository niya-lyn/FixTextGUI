"""错误码 → 人话文案 + 下一步指引 的唯一映射表（M2-T2.4）。

要求（对应排期 2.3「人话错误提示」底线与 4.4 T2.4）：
- 每类错误两段式：what（发生了什么，说人话）+ guidance（用户下一步能做什么）；
- 禁止出现堆栈、异常类名、命令行输出、内部路径、技术名词
  （Python / PHP / Go / JSON / traceback / 进程 / 退出码 等）；
- 无「发生错误」这类无指引空文案——guidance 一律给出可执行动作。

文案的受众是「普通人」：句子短、动词开头、告诉用户原始文件是安全的
（FixText 全程只读保护是既有底线，出错文案里也如实声明）。
"""

from __future__ import annotations

from .error_codes import ErrorCode, CATEGORY_OF

# code -> (title, what, guidance)
# title  : 卡片标题（6~12 字，动作导向）
# what   : 发生了什么（≤ 2 句）
# guidance: 下一步指引（用户能做的事，多条用「；」连接）
MESSAGES: dict[str, dict[str, str]] = {
    ErrorCode.IMPORT_FILE_UNREADABLE.value: {
        "title": "没能读取这本书",
        "what": "找不到或读不了你选择的文件——它可能已被移动、删除，或正被其他程序占用。",
        "guidance": "回到原来的位置确认文件还在；如果文件在 U 盘或网盘里，先等它连接、同步完成，再重新导入一次。",
    },
    ErrorCode.IMPORT_FILE_CORRUPT.value: {
        "title": "这本书的文件损坏了",
        "what": "文件内容不完整，打不开——常见于没下载完、复制中断或存储出错。",
        "guidance": "换一个文件试试；如果它来自网络，建议重新下载一次再导入。",
    },
    ErrorCode.IMPORT_ENCODING_UNKNOWN.value: {
        "title": "没法识别这本书的文字",
        "what": "书里的文字用了少见的编码方式，暂时认不出来。",
        "guidance": "换一个文件试试；如果确认文件是好的，可以用记事本打开后「另存为」，编码选 UTF-8，再导入。",
    },
    ErrorCode.IMPORT_EPUB_STRUCTURE.value: {
        "title": "这本书的格式读不了",
        "what": "这本 EPUB 的内部组织和常见格式不一样，暂时解析不了。",
        "guidance": "先用 Calibre 打开这本书做一次「转换」（输入和输出都选 EPUB 即可修复结构），再导入；或直接转成 TXT 导入。",
    },
    ErrorCode.IMPORT_INTERNAL_DATA.value: {
        "title": "工作数据出了点问题",
        "what": "FixTextGUI 自己的中间数据对不上了。你的原始文件不受任何影响。",
        "guidance": "重新导入这本书再试一次；如果反复出现，打开「设置」里的诊断日志目录，把最新的日志发给支持人员。",
    },
    ErrorCode.PROC_ENGINE_MISSING.value: {
        "title": "校正引擎没有就位",
        "what": "负责校正的组件没有随软件一起运行——最常见的原因是杀毒软件把它拦截或隔离了。",
        "guidance": "在杀毒软件的隔离区找到 FixTextGUI 并选择放行/信任，然后重新解压一份完整软件，再打开试一次。",
    },
    ErrorCode.PROC_ENGINE_FAILED.value: {
        "title": "校正中途停了",
        "what": "处理这本书时校正组件意外停止，本次没有生成结果。你的原始文件不受影响。",
        "guidance": "重试一次；若仍失败，换一本书处理以确认是否这本书太大或内容特殊；持续出现请把诊断日志发给支持人员。",
    },
    ErrorCode.PROC_ENGINE_TIMEOUT.value: {
        "title": "处理时间超出了上限",
        "what": "这本书处理时间过长，已经自动停止，没有留下半成品。",
        "guidance": "重试一次；特别大的书会需要更久，可以先拆分后分批处理；反复出现请反馈给支持人员。",
    },
    ErrorCode.PROC_DISK_FULL.value: {
        "title": "磁盘空间不足",
        "what": "电脑磁盘写不进处理结果，本次没有完成。已写入的部分会在重试时自动覆盖。",
        "guidance": "清理磁盘空间后重试（建议至少留出这本书大小两倍的余量）；可以先清理回收站和「下载」文件夹。",
    },
    ErrorCode.PROC_NO_PERMISSION.value: {
        "title": "没有足够的权限",
        "what": "系统不允许 FixTextGUI 读取或使用这个位置，常见于系统目录或其他账户的文件。",
        "guidance": "把文件复制到「文档」或「下载」文件夹再试；如果软件放在系统盘的受限目录，请把整个软件文件夹移动到桌面后重新打开。",
    },
    ErrorCode.EXPORT_DIR_UNWRITABLE.value: {
        "title": "导出目录写不进去",
        "what": "选定的导出位置现在不可用——目录可能被删、被设为只读或没有写入权限。",
        "guidance": "点「浏览…」换一个导出目录（建议「文档」或桌面）再试；如果是 U 盘或移动硬盘，先解除写保护。",
    },
    ErrorCode.EXPORT_WRITE_FAILED.value: {
        "title": "导出没有保存成功",
        "what": "导出时写入文件失败，结果没有保存成功。",
        "guidance": "检查磁盘剩余空间和导出目录后重试；换一个目录导出也可以。",
    },
    ErrorCode.RUNTIME_UNEXPECTED.value: {
        "title": "出了点意外",
        "what": "遇到了一个没有预料到的问题，这次操作没有完成。你的原始文件不受影响。",
        "guidance": "重试一次；如果再次出现，打开「设置」里的诊断日志目录，把最新的日志文件发给支持人员，我们会尽快修复。",
    },
}


# 界面文案中禁止出现的技术词（lint 与单测共用这份清单）。
# 判定口径：用户可见字符串（标题/what/guidance/卡片脚注）里不允许出现下列子串。
FORBIDDEN_TERMS = (
    "traceback", "Traceback",
    "exception", "Exception",
    "python", "Python", "PHP", "php",
    "stderr", "stdout", "exit code", "退出码",
    "命令行", "堆栈", "进程",
    "ValueError", "OSError", "EngineError", "Error:",
)


def get_message(code: str) -> dict[str, str]:
    """取某错误码的完整文案；未知码回落到通用兜底（永不抛异常、永不返回空）。"""
    msg = MESSAGES.get(code)
    if msg is None:
        msg = MESSAGES[ErrorCode.RUNTIME_UNEXPECTED.value]
    out = dict(msg)
    out["category"] = CATEGORY_OF.get(code, "运行")
    return out


def all_codes() -> list[str]:
    """全部错误码（映射表逐类核对 / 完备性单测用）。"""
    return list(MESSAGES.keys())
