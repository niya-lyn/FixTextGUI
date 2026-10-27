"""fixtext_pipeline —— FixText 一键校正编排器（M1-T1.1）。

把 M1 各引擎串成一条命令线全链路：

    合并(T1.3) → 排版(T1.2) → 词库替换(T0.3 Go 引擎 + T0.2 词库)
                → 引号检查(T1.4) → 专有词库生成(T1.5) → EPUB 还原(T1.3)

设计约束：

* **替换阶段必须走 Go 引擎的 Python 子进程协议**（``fixtext.engine``），
  编排器不自己实现任何字符串替换逻辑；
* 每个阶段独立落盘（产物 + 日志 + 计时），并把状态写进 ``state.json``，
  中断后可用 ``--resume`` 从上次完成的阶段继续；
* 排版阶段在 HTML 模式下逐章执行，并带「XML 结构守卫」——
  排版后若章节不再是合法 XML 或标签/属性结构被破坏，该章自动回退到排版前内容。
"""

from __future__ import annotations

__all__ = ["__version__", "STAGE_ORDER"]

__version__ = "1.0.0"

#: 全链路阶段顺序（依赖顺序即执行顺序）
STAGE_ORDER = ("merge", "layout", "replace", "quote", "bookmap", "restore")
