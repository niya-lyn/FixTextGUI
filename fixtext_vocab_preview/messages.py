"""V1.1-D3 · 预览页的人话文案（与 D1 同一套零技术词口径）。

文案单独放一个模块，是为了让 lint（机械扫描源码字面量）能直接对着它跑：
失败路径的句子在正常流程里跑不到，只有扫源码才能保证它一开始就是人话。
"""

from __future__ import annotations


#: 三组的人话名字。界面、汇总句、交付记录都用这一份，不各写一遍。
GROUP_NEW = "新增"
GROUP_CONFLICT = "冲突"
GROUP_REJECT = "格式不合格"

GROUP_NAMES: tuple[str, ...] = (GROUP_NEW, GROUP_CONFLICT, GROUP_REJECT)

#: 三组的兜底解释（组里没有条目时也说清这组是什么，不是一片空白）
GROUP_NOTES: dict[str, str] = {
    GROUP_NEW: "这些词条库里还没有，确认后会新增进去。",
    GROUP_CONFLICT: "这些词条库里已经有一样的词或一样的写法，需要你先决定怎么处理。",
    GROUP_REJECT: "这些行本身不成立（例如格子是空的），改原文后才能导入。",
}


def summary(new: int, conflict: int, reject: int) -> str:
    """一句总账（页面顶部与交付记录共用）。"""
    return (f"这份表里有 {new + conflict + reject} 条候选："
            f"{GROUP_NEW} {new} 条、{GROUP_CONFLICT} {conflict} 条、"
            f"{GROUP_REJECT} {reject} 条。")


def group_title(name: str, count: int) -> str:
    return f"{name} {count} 条"


def batch_note(batch_count: int, batch_size: int) -> str:
    """分批口径的声明（只读预览里也要让用户知道「真导入会怎么切」）。"""
    if batch_count <= 1:
        return "按现在的条数，真导入时一次处理完，不会分批。"
    return (f"按现在的条数，真导入时会按每批 {batch_size} 条分成 "
            f"{batch_count} 批处理，每批结束都会更新进度。")


def cancelled(count: int) -> str:
    return f"已取消 {count} 条，它们不会再出现在任何一组里。"


def all_cancelled() -> str:
    return "三组里的条目都取消了，现在没有要导入的内容。"


def nothing_ready() -> str:
    return ("这份表里没有可以导入的条目。"
            "先看看「格式不合格」那一组里写的怎么改，或者检查列是不是对应好了。")


def mapping_blocked(items: list[str]) -> str:
    head = "列还没对应好，先别急着看分组。"
    return head + ("" if not items else " " + " ".join(items))


def preview_only() -> str:
    """本页定位的一句话（避免用户以为这里会写库）。"""
    return ("这一页只看不动手：不会改动词库。确认无误后，真正的导入在下一步做，"
            "那一步会先给二次确认，做完还能撤销。")


def cancelled_hint() -> str:
    return "点条目右边的「取消」可以把它整条排除；取消过的条目不会再出现在任何一组里。"


def empty_after_cancel_hint() -> str:
    return "想找回来，点上面的「全部恢复」即可——它只恢复本次预览里的取消，不动词库。"


def cannot_cancel_last() -> str:
    return "这条已经取消了。"


def restored(count: int) -> str:
    return f"已恢复 {count} 条到分组里。"


def restore_none() -> str:
    return "现在没有已取消的条目，不需要恢复。"


def rehearsal_title() -> str:
    return "预演核对（不写你的词库）"


def rehearsal_note() -> str:
    return ("下面这组数字来自一次**预演写**：把确认后的条目写进词库文件的临时副本，"
            "再比对前后差集。它证明预览报的数字与真导入会写进去的条数一致，"
            "而你的词库文件一个字节都不会动。")


def rehearsal_done(new: int, added: int, removed_leak: int, identical: bool) -> str:
    state = "一致" if identical else "不一致"
    return (f"预览说新增 {new} 条，预演写实测新增 {added} 条：{state}。"
            f"多出来 {removed_leak} 条。")


def conflict_kinds(kinds: dict[str, int]) -> str:
    """冲突形态的分布（三种形态的名字来自查重引擎的常量）。"""
    if not kinds:
        return "没有冲突。"
    parts = "、".join(f"{k} {v} 条" for k, v in kinds.items())
    return f"冲突按形态看：{parts}。"
