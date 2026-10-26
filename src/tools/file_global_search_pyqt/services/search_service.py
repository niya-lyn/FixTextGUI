import regex
from qtpy.QtCore import QObject, QThreadPool
from typing import List, Tuple, Optional
from tasks.search_task import SearchTask
from utils.text_counter import TextCounter
from core.constants import PatchSearchAction


class SearchService(QObject):
    _INFO_STRIP_PATTERN = regex.compile(
        r"\[(行号|匹配)：\d+\]\s*|【匹配项：.*】\s*|※※※（.*?省略）※※※\s*|={60,}\s*|【搜索耗时.*?】\s*|【匹配行.*?】\s*|【字数行】.*|\n|<［[adno]:|］>"
    )
    _LINE_NUM_EXTRACT_PATTERN = regex.compile(r"^\[(?:行号|匹配)：(\d+)\]", regex.M)

    def __init__(self, compare_guidance_md: str):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()
        self.compare_guidance_md = compare_guidance_md

    def start_search_task(
        self, file_path, search_term, condition, prev_lines, next_lines, options, patch_action, patch_merge_threshold
    ):
        task = SearchTask(
            file_path, search_term, condition, prev_lines, next_lines, options, patch_action, patch_merge_threshold
        )
        self.thread_pool.start(task)

        return task

    def calculate_char_count_info(
        self, display_text: str, file_path: str, patch_action: PatchSearchAction
    ) -> Tuple[str, bool]:
        clean_text = self._INFO_STRIP_PATTERN.sub("", display_text)

        readable_char_count = TextCounter.count_text_chars(file_path, clean_text)
        info = f"当前：{readable_char_count}"
        highlight = patch_action != PatchSearchAction.NOT_PATCH_SEARCH

        if patch_action == PatchSearchAction.BOOKS_VS_BAK:
            info = f"books 差异：{readable_char_count}"
        elif patch_action == PatchSearchAction.BAK_VS_BOOKS:
            info = f"booksBak 差异：{readable_char_count}"

        return info, highlight

    def save_button_text(self, patch_action: PatchSearchAction) -> Tuple[str, bool]:
        info = f"保存修改到文件（Ctrl+S）"
        highlight = patch_action != PatchSearchAction.NOT_PATCH_SEARCH

        if patch_action == PatchSearchAction.BOOKS_VS_BAK:
            info = f"比对视图：保存 → books"
        elif patch_action == PatchSearchAction.BAK_VS_BOOKS:
            info = f"比对视图：保存 → booksBak"

        return info, highlight

    def revise_condition_before_search(self, search_text: str, is_html_file: bool) -> str:
        """根据是否为 HTML 文件，决定是否跳过标签内的匹配"""
        if not is_html_file:
            return search_text.replace("<[^>]*>(*SKIP)(*F)|", "")
        return search_text

    def get_compare_guidance_md(self) -> str:
        guidance_text = ""
        with open(self.compare_guidance_md, "r", encoding="utf-8") as f:
            guidance_text = f.read()

        return guidance_text

    # --- 分页坐标计算相关 ---
    def find_match_offset(self, text: str, item_num: int, start_hint: int = 0) -> int:
        marker = f"【匹配项：{item_num}/"
        return text.find(marker, start_hint)

    def get_page_line_ranges(self, text: str, total_matches: int, page_size: int) -> List[Tuple[int, int]]:
        page_ranges = []
        start_hint = 0
        for i in range(1, total_matches + 1, page_size):
            start_item_num = i
            end_item_num = min(i + page_size - 1, total_matches)

            # 查找分页起始匹配项的偏移量和行号
            start_offset = self.find_match_offset(text, start_item_num, start_hint)
            if start_offset == -1:
                continue
            start_line = self._find_line_num_after_offset(text, start_offset)
            if start_line is None:
                continue

            # 查找分页结束匹配项的偏移量和行号
            end_offset = self.find_match_offset(text, end_item_num, start_offset)
            if end_offset == -1:
                # 如果找不到结束项（虽然理论上不应该），就用起始项的偏移量
                end_offset = start_offset
            end_line = self._find_line_num_after_offset(text, end_offset)
            if end_line is None:
                end_line = start_line  # 如果找不到结束行号，就用起始行号

            page_ranges.append((start_line, end_line))
            # 更新下一次搜索的起始点
            start_hint = end_offset + 1

        return page_ranges

    def _find_line_num_after_offset(self, text: str, offset: int) -> Optional[int]:
        """在指定偏移量后查找第一个行号"""
        match = self._LINE_NUM_EXTRACT_PATTERN.search(text, pos=offset)
        if match:
            return int(match.group(1))

        return None

    def splice_page_result(
        self, initial_result: str, current_page_text: str, first_item_num: int, last_item_num: int
    ) -> str:
        start_replace_pos = self.find_match_offset(initial_result, first_item_num)
        # 结束位置是 "当前页最后一项的下一项" 的起始位置
        end_replace_pos = self.find_match_offset(initial_result, last_item_num + 1, start_replace_pos)

        if start_replace_pos == -1:
            return ""  # 返回空代表出错

        # 原始头部 + 当前编辑的新内容 + 原始尾部
        prefix = initial_result[:start_replace_pos]
        if end_replace_pos != -1:
            suffix = initial_result[end_replace_pos:]
            # 无论 current_text 结尾有没有换行，统一去掉并补上一个标准换行符
            return prefix + current_page_text.rstrip("\n") + "\n" + suffix
        else:
            # 替换到文件末尾
            return prefix + current_page_text
