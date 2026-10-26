import regex
from qtpy.QtCore import QObject
from core.data_classes import ReplaceResult


class ReplaceService(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)

    def get_single_replace_result(self, match_obj: regex.Match, replace_text: str, callback=None) -> ReplaceResult:
        """
        根据查找结果（正则匹配对象）获取替换结果文本
        适用于“单次替换”，和导航时“预览替换结果”
        """
        try:
            if callback and replace_text != "":
                new_text = callback(match_obj)
            else:
                # 使用 expand 查找可能的分组，格式化替换字符串
                # 这里不应该使用原来的 pattern.sub(replace_text, match.group(0))
                # 否则涉及后行断言时根本无法进行替换
                new_text = match_obj.expand(replace_text)

            return ReplaceResult(new_text=new_text, error_msg="", success=True)
        except Exception as e:
            return ReplaceResult(new_text="", error_msg=str(e), success=False)

    def perform_bulk_replace(
        self, source_text: str, search_term: str, replace_text: str, use_regex: bool, flags: int, callback=None
    ) -> ReplaceResult:
        if search_term == replace_text:
            return ReplaceResult(new_text=source_text, error_msg="", success=True)

        pattern_str = search_term if use_regex else regex.escape(search_term)

        try:
            pattern = regex.compile(pattern_str, flags)
        except Exception as e:
            return ReplaceResult(new_text=source_text, error_msg=f"无效的正则表达式：{str(e)}", success=False)

        try:
            if callback and replace_text != "":
                new_text = pattern.sub(callback, source_text)
            else:
                new_text = pattern.sub(replace_text, source_text)

            # 特殊处理，防止结束标记被错误合并到上一行 (完全保留你的原版逻辑)
            new_text = new_text.replace("※※※（下文省略）※※※", "\n※※※（下文省略）※※※")
            new_text = new_text.replace("\n\n※※※（下文省略）※※※", "\n※※※（下文省略）※※※")

            return ReplaceResult(new_text=new_text, error_msg="", success=True)
        except Exception as e:
            return ReplaceResult(new_text=source_text, error_msg=f"替换时发生错误：{str(e)}", success=False)
