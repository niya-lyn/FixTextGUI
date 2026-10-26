import regex
from typing import List, Dict, Tuple, Optional, Set, Any
import math
from dataclasses import dataclass

import utils.util as util


@dataclass
class ChapterInfo:
    """存储单行章节信息的简单数据结构"""

    line_index: int
    content: str
    type: str  # 'numbered', 'ungrouped', 'special' (0.0)
    start_num: Optional[int] = None
    end_num: Optional[int] = None
    has_sub_suffix: bool = False  # 是否含有中文括号子序号后缀
    sub_value: Optional[int] = None  # 数字类子后缀解析值（一→1, 2→2）
    sub_fixed: Optional[str] = None  # 固定序列子后缀字符（上/中/下）


class ChapterNumChecker:

    # ==========================
    # 常量定义
    # ==========================

    # 表示特殊章节，不参与序列检测和重排
    # 在【0.文本排版】的“处理自定义【分级标题】”中加上
    SPECIAL_CHAPTER_NUM = "0.0"

    # 用于 check_chapter_num 检查缩进
    _FORMAT_PATTERN = regex.compile(r"^　　|^  ", regex.MULTILINE)

    # 用于 _parse_chapters 识别行首
    _MARKER_LINE_REGEX = regex.compile(r"^\[匹配：(\d+)\]")

    # 用于识别非数字的顶格章节
    _UNGROUPED_CHAPTER_REGEX = regex.compile(
        r"^(\s*(?:<h\d+[^>]*>(?:<span[^>]*>)?|<title[^>]*>)\s*)?(?![<\[]|※※|==)[^\s<]"
    )

    # 用于检测并解析中文括号内的子序号后缀（三个分组：中文数字 | 阿拉伯数字 | 上中下）
    _SUB_SUFFIX_REGEX = regex.compile(r"（(?:([一二三四五六七八九十零〇百千万]+)|(\d+)|([上中下]))）")

    # 固定子后缀的合法完整序列
    _FIXED_SUB_SEQUENCE = ["上", "中", "下"]

    # 用于 renumber_chapter_text 解析行前缀
    _MARKER_PREFIX_REGEX = regex.compile(r"^((?:\[(?:行号|匹配)：\d+\])?(?:【(?:章节|乱序)行.*?】))(.*)")

    # 定义数字部分：支持中文、阿拉伯数字、点
    _NUM_PART = r"(?<!<h|</h)[\d一二三四五六七八九十零〇百千万亿两廿卅卌壹贰叁肆伍陆柒捌玖拾佰仟萬億.]+(?!\">)"
    # 匹配范围: "1-2" "1到2" "1至2"
    _RANGE_PATTERN = regex.compile(rf"({_NUM_PART})\s*[\-—至到]\s*({_NUM_PART})")
    # 匹配单个: "1"
    _SINGLE_NUM_PATTERN = regex.compile(rf"({_NUM_PART})")

    # 统计相关正则
    _RE_MOST_CHARS = regex.compile(r"(?<=┃　　)字数：.*")
    _RE_TOO_FEW = regex.compile(r"长度：(?=█{0,2}┃)")

    # 摘要行替换正则
    _RE_TIME = regex.compile(r"搜索耗时(.*?)秒，")
    _RE_TOTAL_MATCH = regex.compile(r"共有 \d+ 个匹配项，")
    _RE_MATCH_COUNT = regex.compile(r"(\d+) 处匹配")

    # ==========================
    # 对外入口方法
    # ==========================

    @classmethod
    def check_chapter_num(cls, search_result: str, file_path: str) -> str:
        """
        检查章节标题的顺序，并计算每个章节之间的字数
        返回格式化后的搜索结果
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original_content = f.read()
        except Exception as e:
            return f"【错误】无法读取文件 '{file_path}': {e}\n\n{search_result}"

        if not cls._FORMAT_PATTERN.search(original_content):
            return "【请先用排版脚本修改格式：正文的每行需要缩进两个全角空格。之后再来检查章节标题】"

        lines = search_result.splitlines()

        # 1. 提取结构化章节数据
        chapter_data_list = cls._parse_chapters(lines)

        if not chapter_data_list:
            return search_result  # 没有找到任何章节行，直接返回

        # 按在搜索结果中的出现顺序排序（通常对应文件顺序）
        chapter_data_list.sort(key=lambda x: x.line_index)

        # 2. 计算原始字数（整数）
        char_counts = cls._calculate_chapter_char_counts(chapter_data_list, original_content, file_path)

        # 3. 分析乱序情况
        disordered_indices = cls._identify_disordered_indices(chapter_data_list, lines)

        # 3.1 检查子分节后缀的连续性
        sub_disordered = cls._check_sub_suffix_order(chapter_data_list)
        disordered_indices.update(sub_disordered)

        # 4. 格式化输出
        return cls._format_report(lines, chapter_data_list, char_counts, disordered_indices)

    @classmethod
    def renumber_chapter_text(
        cls,
        text_to_process: str,
        renumber_type: int = 0,
        group_sub_chapters: bool = False,  # 同章分节保留模式：若开启，(上)(下)或(一)(二)将共享主章号
        reset_on_volume: bool = False,  # 跨卷序号重置模式：若开启，检测到面包屑中卷名变化则序号从1重新开始
        preserve_range: bool = False,  # 章节范围保留模式：若开启，"1-2"这种合并章会保留跨度
    ) -> Tuple[bool, str]:
        """
        核心逻辑：
        1. 遍历全文，识别出所有合法的章节行，并记录它们在文中的物理位置。
        2. 实时监测“卷”标记，为每个章节绑定所属的卷上下文。
        3. 遍历待处理队列，根据业务规则（重置、分节等）计算出每一行应该对应的新序号。
        4. 按照记录的物理位置，精准替换原文字符串。
        """
        lines = text_to_process.splitlines()
        modified_lines = list(lines)
        renumber_targets = []  # 存放待修改的目标信息对象

        # 【第一遍扫描：收集上下文与目标】
        current_sticky_vol = None  # 记录当前最新的卷名（用于跨卷重置判断）

        for i, line in enumerate(lines):
            # A. 实时更新“卷”上下文：因为卷标题通常在章节行上方出现
            v_tag = cls._extract_volume_tag(line)
            if v_tag:
                current_sticky_vol = v_tag

            # B. 基础检查：是否为搜索结果的标记行（含【章节行】或【乱序行】标记）
            prefix_match = cls._MARKER_PREFIX_REGEX.match(line)
            if not prefix_match:
                continue

            # C. 提取内容部分：去掉前面的 [匹配:n][章节行] 等前缀
            prefix_str = prefix_match.group(1)
            content_raw = prefix_match.group(2)
            content = content_raw.lstrip()
            # 计算数字在整行中的绝对偏移量，用于后续精准替换
            offset = len(prefix_str) + (len(content_raw) - len(content))

            # D. 识别数字：寻找行内最合适的章节号（处理单号或范围号）
            match = cls._find_best_chapter_match(content)
            if not match:
                continue  # 如果行内没数字（如 ungrouped 章节），跳过

            groups = match.groups()
            logical_start = groups[0].strip()

            # E. 特殊章节过滤：如果识别到是 0.0，跳过重排逻辑，保持原样
            if logical_start == cls.SPECIAL_CHAPTER_NUM:
                continue

            # F. 处理范围号逻辑：识别如 "1-2" 中的结束号和分隔符
            logical_end = groups[1].strip() if len(groups) > 1 and groups[1] else None
            sep = ""
            if logical_end:
                f_text = match.group(0)
                # 提取中间的分隔符（如 "-", "至", "到"）
                s_match = regex.search(rf"{regex.escape(logical_start)}(.*?){regex.escape(logical_end)}", f_text)
                sep = s_match.group(1) if s_match else "-"

            # G. 封装信息：进入待处理队列
            renumber_targets.append(
                {
                    "line_index": i,
                    "start_str": logical_start,
                    "end_str": logical_end,
                    "sep": sep,
                    "is_chinese": not logical_start.isdigit(),  # 标记原始是否为中文数字
                    "num_start": offset + match.start(),  # 替换开始位置
                    "num_end": offset + match.end(),  # 替换结束位置
                    "vol_tag": current_sticky_vol,  # 绑定所属卷名
                    # 如果开启了子分节保留，则提取后缀信息（如“（上）”）
                    "suffix_info": cls._extract_sub_suffix_info(content, match) if group_sub_chapters else None,
                }
            )

        # 如果没搜集到任何需要重排的行，直接返回
        if not renumber_targets:
            return (False, "未匹配到任何有效的章节行")

        # 【第二遍处理：执行重排逻辑】
        first = renumber_targets[0]
        try:
            # 解析起始数字：将第一项的数字作为起始基准
            cur_num = util.chn_to_arabic_num(first["start_str"]) if first["is_chinese"] else int(first["start_str"])
        except:
            return (False, "起始号解析失败")

        prev_vol = renumber_targets[0]["vol_tag"]
        prev_suffix = None
        # 计算补零长度：基于总数预估位数
        pad_len = len(str(cur_num + len(renumber_targets)))

        for idx, item in enumerate(renumber_targets):
            # 1. 判断是否需要重置序号（跨卷逻辑）
            # 开启了模式 且 不是第一行 且 卷名发生了变化
            if reset_on_volume and idx > 0 and item["vol_tag"] != prev_vol:
                cur_num = 1
            elif idx > 0:
                # 2. 判断是否保持当前序号（同章分节逻辑）
                # 开启了模式 且 当前行被识别为上一行的连续子分节（如 上->中）
                is_sub = group_sub_chapters and cls._is_consecutive_sub_chapter(prev_suffix, item["suffix_info"])
                if not is_sub:
                    # 如果不是子分节，序号才累加
                    cur_num += 1

            # 3. 计算范围差值 (diff)
            # 无论是否 preserve_range，都需要知道这个范围占了多少个数，以便更新计数器
            current_span_diff = 0
            if item["end_str"]:
                try:
                    v1 = util.chn_to_arabic_num(item["start_str"]) if item["is_chinese"] else int(item["start_str"])
                    v2 = util.chn_to_arabic_num(item["end_str"]) if item["is_chinese"] else int(item["end_str"])
                    current_span_diff = max(0, v2 - v1)
                except:
                    current_span_diff = 0

            # 4. 生成新的序号字符串
            if preserve_range and item["end_str"]:
                # 范围保留模式：计算原有的范围差（如 10-12 差值为 2），应用到新序号上
                try:
                    v1 = util.chn_to_arabic_num(item["start_str"]) if item["is_chinese"] else int(item["start_str"])
                    v2 = util.chn_to_arabic_num(item["end_str"]) if item["is_chinese"] else int(item["end_str"])
                    diff = v2 - v1
                    s1 = cls._generate_new_number_str(cur_num, renumber_type, pad_len)
                    s2 = cls._generate_new_number_str(cur_num + max(0, diff), renumber_type, pad_len)
                    new_str = f"{s1}{item['sep']}{s2}"
                except:
                    new_str = cls._generate_new_number_str(cur_num, renumber_type, pad_len)
            else:
                # 普通单章模式
                new_str = cls._generate_new_number_str(cur_num, renumber_type, pad_len)

            # 5. 执行字符串替换
            ln_idx = item["line_index"]
            # 仅替换数字部分
            modified_lines[ln_idx] = (
                modified_lines[ln_idx][: item["num_start"]] + new_str + modified_lines[ln_idx][item["num_end"] :]
            )
            # 6. 状态修复：重排后，所有的【乱序行】标签统一更正为【章节行】
            modified_lines[ln_idx] = regex.sub("【乱序行.*?】", "【章节行】", modified_lines[ln_idx])

            # 7. 将 cur_num 更新为当前范围的末尾数值
            # 这样在下一轮循环执行 cur_num += 1 时，就会从正确的位置开始
            if preserve_range:  # 只在选择“保留范围”时执行
                # 如果不保留范围（合并重排），则 2-3 变成了 2，下一章应该是 3，则不应加 current_span_diff
                cur_num += current_span_diff

            # 记录当前状态供下一轮循环比较
            prev_vol = item["vol_tag"]
            prev_suffix = item["suffix_info"]

        return (True, "\n".join(modified_lines))

    @classmethod
    def has_sub_chapter_suffix(cls, text_to_process: str) -> bool:
        """
        检测文本块中是否包含可能的子章节后缀（如（上）、（一）等）
        UI 层可在调用 renumber_chapter_text 前调用此方法，
        如果返回 True，则弹出提示询问用户是否要开启【同章分节保留模式】
        """
        lines = text_to_process.splitlines()
        for line in lines:
            prefix_match = cls._MARKER_PREFIX_REGEX.match(line)
            if not prefix_match:
                continue

            content_part = prefix_match.group(2).lstrip()
            num_match = cls._find_best_chapter_match(content_part)

            # 检测是否含有后缀，且后缀不是主章节号本身
            if cls._extract_sub_suffix_info(content_part, num_match):
                return True

        return False

    @classmethod
    def has_range_pattern(cls, text_to_process: str) -> bool:
        """检测文本中是否包含范围章节（如 1-2）"""
        lines = text_to_process.splitlines()
        for line in lines:
            prefix_match = cls._MARKER_PREFIX_REGEX.match(line)
            if not prefix_match:
                continue

            content_part = prefix_match.group(2).lstrip()
            num_match = cls._find_best_chapter_match(content_part)

            # 如果匹配到了数字，且该匹配项包含第二个分组（即 end_num），说明主章节号是范围格式
            if num_match and len(num_match.groups()) >= 2 and num_match.group(2):
                return True

        return False

    @classmethod
    def has_volume_change(cls, text_to_process: str) -> bool:
        """检测文本块中是否包含跨卷的情况（卷名发生了变化）"""
        vol_names = []
        for line in text_to_process.splitlines():
            v = cls._extract_volume_tag(line)
            if v:
                # 只有当卷名真的变了（字符串不同）才加入序列
                if not vol_names or v != vol_names[-1]:
                    vol_names.append(v)

        # 如果去噪后的卷名序列长度 > 1，说明确实跨卷了
        return len(vol_names) > 1

    # ==========================
    # 核心逻辑辅助方法
    # ==========================

    @classmethod
    def _parse_chapters(cls, lines: List[str]) -> List[ChapterInfo]:
        """从搜索结果行中提取结构化的章节数据"""
        chapter_data = []

        for i, line in enumerate(lines):
            if not cls._MARKER_LINE_REGEX.match(line):
                continue

            marker_end = line.find("]") + 1
            content = line[marker_end:].lstrip()

            # 1. 如果是以 ◎ 开头，归入 ungrouped，不检测序号
            if content.startswith("◎"):
                chapter_data.append(ChapterInfo(i, content, "ungrouped"))
                continue

            # 2. 尝试匹配带数字的章节
            numbered_match = cls._find_best_chapter_match(content)
            if numbered_match:
                groups = numbered_match.groups()
                # 2.1 如果是 "0.0"，直接归类为特殊章节，并跳过后续处理
                if groups[0].strip() == cls.SPECIAL_CHAPTER_NUM:
                    chapter_data.append(ChapterInfo(i, content, "special"))  # internal type: special/0.0

                # 2.2 范围匹配或单数字匹配
                else:
                    start_num, end_num = None, None
                    if len(groups) == 2:  # 范围匹配
                        start_num = cls._parse_num_string(groups[0].strip())
                        end_num = cls._parse_num_string(groups[1].strip())
                    else:  # 单数字匹配
                        num = cls._parse_num_string(groups[0].strip())
                        if num is not None:
                            start_num, end_num = num, num

                    if start_num is not None and end_num is not None:
                        # 复用 _extract_sub_suffix_info 来填充 ChapterInfo
                        suffix_info = cls._extract_sub_suffix_info(content, numbered_match)

                        has_sub = suffix_info is not None
                        sub_value = suffix_info["value"] if suffix_info and suffix_info["type"] == "digit" else None
                        sub_fixed = suffix_info["value"] if suffix_info and suffix_info["type"] == "fixed" else None

                        chapter_data.append(
                            ChapterInfo(
                                line_index=i,
                                content=content,
                                type="numbered",
                                start_num=start_num,
                                end_num=end_num,
                                has_sub_suffix=has_sub,
                                sub_value=sub_value,
                                sub_fixed=sub_fixed,
                            )
                        )

            # 3. 匹配无数字的顶格章节
            elif cls._UNGROUPED_CHAPTER_REGEX.search(content):
                chapter_data.append(ChapterInfo(i, content, "ungrouped"))

        return chapter_data

    @classmethod
    def _extract_sub_suffix_info(cls, content: str, main_num_match: regex.Match) -> Optional[Dict[str, Any]]:
        """
        解析内容中的子分节后缀
        如果主章节号恰好就是括号里的内容（如 "（一）"），则不将其视为后缀
        """
        sub_match = cls._SUB_SUFFIX_REGEX.search(content)
        if not sub_match:
            return None

        # 检查主章节号是否落在括号内
        num_start = main_num_match.start()
        num_end = main_num_match.end()
        # 如果主数字的范围被包含在后缀匹配范围内，说明这一整个括号就是章节号本身，而不是后缀
        if num_start >= sub_match.start() and num_end <= sub_match.end():
            return None

        if sub_match.group(1):  # 中文数字
            return {"type": "digit", "value": util.chn_to_arabic_num(sub_match.group(1))}
        elif sub_match.group(2):  # 阿拉伯数字
            return {"type": "digit", "value": int(sub_match.group(2))}
        elif sub_match.group(3):  # 上/中/下
            return {"type": "fixed", "value": sub_match.group(3)}

        return None

    @classmethod
    def _is_consecutive_sub_chapter(cls, prev_info: Optional[Dict], curr_info: Optional[Dict]) -> bool:
        """
        判断当前行的后缀是否是上一行后缀的连续后续
        如果连续，则应该共享同一个主章节号
        """
        if not prev_info or not curr_info:
            return False

        if prev_info["type"] != curr_info["type"]:
            return False

        # 处理固定序列 (上 -> 中 -> 下)
        if prev_info["type"] == "fixed":
            try:
                prev_idx = cls._FIXED_SUB_SEQUENCE.index(prev_info["value"])
                curr_idx = cls._FIXED_SUB_SEQUENCE.index(curr_info["value"])
                # 只有当索引递增时（允许 上->下 跳过 中），才视为同章
                return curr_idx > prev_idx
            except ValueError:
                return False

        # 处理数字序列 (1 -> 2 -> 3)
        if prev_info["type"] == "digit":
            # 只有严格递增才视为连续 (1->2, 2->3)
            # 当前值 == 前值 + 1
            return curr_info["value"] == prev_info["value"] + 1

        return False

    @classmethod
    def _extract_volume_tag(cls, line: str) -> Optional[str]:
        """从标记行或内容中提取纯净的卷标识（去噪处理）"""
        if " » " not in line:
            return None

        # 1. 取得 » 之前的部分
        # 例：'【匹配项：4/1840】【章节名：第一集 传说的年代 » 第一章' -> '...第一集 传说的年代'
        parts = line.split(" » ")
        tag = parts[-2].strip()

        # 2. 去噪：去掉前面的 【章节名：...】
        if "章节名：" in tag:
            tag = tag.split("章节名：")[-1]

        # 3. 清理掉可能残留的左中括号
        return tag.strip("【 ").strip()

    @classmethod
    def _identify_disordered_indices(cls, sorted_chapters: List[ChapterInfo], original_lines: List[str]) -> Set[int]:
        """分析并返回乱序行的行号集合"""
        disordered_indices = set()
        prev_end_num = None

        # 用于记录上一次的分卷名和分卷数字
        prev_volume_name = None
        prev_volume_num = None

        for item in sorted_chapters:
            # 只有带数字的章节才参与顺序检查
            if item.type != "numbered":
                continue

            cur_start_num, idx = item.start_num, item.line_index

            # 提取当前行的分卷名及分卷序号
            cur_volume_name = None
            cur_volume_num = None
            if " » " in item.content:
                # 提取 " » " 前面的部分作为分卷名，例如 "第一卷"
                cur_volume_name = item.content.split(" » ")[0].strip()

                # 尝试从分卷名中提取数字序列
                vol_match = cls._find_best_chapter_match(cur_volume_name)
                if vol_match:
                    # 获取匹配到的数字字符串并解析为数字
                    num_val = cls._parse_num_string(vol_match.groups()[0].strip())
                    # 确保成功解析为整数，排除 nan 等特殊情况
                    if isinstance(num_val, int):
                        cur_volume_num = num_val

            # 判断连续性：当前开始 == 上一个结束 + 1
            is_seq = (prev_end_num is None) or (cur_start_num == prev_end_num + 1)

            # --- 同章号子分节检测 ---
            # 当章节号相同且当前行含中文括号子序号后缀（如（一）（2）（上）），
            # 视为同一章的分节，不算乱序
            is_sub_chapter = False
            if not is_seq and prev_end_num is not None and cur_start_num == prev_end_num and item.has_sub_suffix:
                is_seq = True
                is_sub_chapter = True

            # --- 特殊逻辑：检测“卷 » 章”结构重置序号 ---
            # 如果不连续，且当前是"1"，可能是新卷开始，这时可以认为实际是连续的
            if not is_seq and (cur_start_num == 1 and prev_end_num != 1):
                if cur_volume_name is not None:
                    # 如果成功解析出了当前的卷号和上一个卷号
                    if cur_volume_num is not None and prev_volume_num is not None:
                        # 要求分卷序号必须严格 +1（例如 第一卷 -> 第二卷），否则视为乱序
                        # 如果 prev_volume_num 或 cur_volume_num 被解析为 0，实际应该是 0.0 的特殊卷序号，则不视为乱序
                        if cur_volume_num == prev_volume_num + 1 or prev_volume_num == 0 or cur_volume_num == 0:
                            is_seq = True
                    else:
                        # 如果没解析出数字（比如"序卷"等），退回检查卷名是否不同
                        if cur_volume_name != prev_volume_name:
                            is_seq = True
                else:
                    if cls._check_for_volume_reset(idx, original_lines):
                        is_seq = True

            if not is_seq:
                disordered_indices.add(idx)

            # 子分节不更新 prev_end_num，以保证下一个主章节号的连续性检查正确
            if not is_sub_chapter:
                prev_end_num = item.end_num

            # 更新分卷记录
            if cur_volume_name is not None:
                prev_volume_name = cur_volume_name
                prev_volume_num = cur_volume_num

        return disordered_indices

    @classmethod
    def _check_for_volume_reset(cls, current_line_idx: int, all_lines: List[str]) -> bool:
        """检查上下文是否存在卷标记（»），用于确认序号重置是否合理"""
        # 向上回溯查找最近的【章节...】行
        search_limit = max(0, current_line_idx - 20)
        for k in range(current_line_idx - 1, search_limit - 1, -1):
            line_text = all_lines[k]
            if "【章节" in line_text and "】" in line_text:
                # 找到了最近的一个章节信息行，检查面包屑标记 "»"
                return " » " in line_text

        return False

    @classmethod
    def _check_sub_suffix_order(cls, sorted_chapters: List[ChapterInfo]) -> Set[int]:
        """
        检查同章号子分节后缀的连续性，返回需要标记为乱序的行号集合

        只对「主章节号相同且连续出现 ≥2 次」的组才启动子后缀检查，
        避免主章节号正常递增时（如第33章（上）→第34章（下））被误判
        """
        disordered: Set[int] = set()

        # 提取所有 numbered 类型的章节
        numbered_items = [item for item in sorted_chapters if item.type == "numbered"]

        # 按连续相同 start_num 分组
        i = 0
        while i < len(numbered_items):
            j = i + 1
            while j < len(numbered_items) and numbered_items[j].start_num == numbered_items[i].start_num:
                j += 1

            group = numbered_items[i:j]
            i = j

            # TODO: 这里的判断实际上是必须有“第一章 aa（上）”和“第一章 aa（下）”这种主章节号相同的时候才触发
            # 会导致“第一章 aa”和“第二章 aa（下）”，这种跨章节号而有（下）没有（上）的情况被跳过，待优化
            # 其实应该读取连续的主标题“aa”，根据主标题来分组并判断，而不是根据主章节号“第一章”“第二章”来分组

            # 组内至少 2 行才可能构成子分节关系
            if len(group) < 2:
                continue

            # 提取组内有子后缀的行
            sub_items = [item for item in group if item.has_sub_suffix]
            if not sub_items:
                continue

            cls._check_group_sub_order(sub_items, disordered)

        return disordered

    @classmethod
    def _check_group_sub_order(cls, sub_items: List[ChapterInfo], disordered: Set[int]) -> None:
        """
        检查同一主章节号组内子后缀的连续性

        规则：
        - 数字类（中文/阿拉伯）：必须从 1 开始，中间连续递增
        - 固定序列（上/中/下）：必须从"上"开始，单调递增，以"下"结束
        """
        first = sub_items[0]

        if first.sub_fixed is not None:
            # ---- 固定序列检查 ----
            prev_idx = None
            for item in sub_items:
                if item.sub_fixed is None or item.sub_fixed not in cls._FIXED_SUB_SEQUENCE:
                    disordered.add(item.line_index)
                    continue
                actual_idx = cls._FIXED_SUB_SEQUENCE.index(item.sub_fixed)
                if prev_idx is None:
                    if actual_idx != 0:  # 必须从"上"开始
                        disordered.add(item.line_index)
                else:
                    if actual_idx <= prev_idx:  # 单调递增（允许跳过"中"）
                        disordered.add(item.line_index)
                prev_idx = actual_idx

            # 必须以"下"结束
            if prev_idx is not None and prev_idx != len(cls._FIXED_SUB_SEQUENCE) - 1:
                disordered.add(sub_items[-1].line_index)

        elif first.sub_value is not None:
            # ---- 数字连续性检查 ----
            prev_val = None
            for item in sub_items:
                if item.sub_value is None:
                    disordered.add(item.line_index)  # 组内类型不一致
                    continue
                if prev_val is None:
                    if item.sub_value != 1:  # 必须从 1 开始
                        disordered.add(item.line_index)
                else:
                    if item.sub_value != prev_val + 1:  # 连续递增
                        disordered.add(item.line_index)
                prev_val = item.sub_value

    @staticmethod
    def _calculate_chapter_char_counts(
        sorted_chapter_data: List[ChapterInfo], original_content: str, file_path: str
    ) -> Dict[int, int]:
        """
        通过精确定位文件中每个标题的物理位置，来计算章节间的字数
        """
        from utils.text_counter import TextCounter

        char_counts = {}
        chapter_positions = []
        last_find_pos = -1  # 跟踪上一个找到的位置，以处理重复标题

        # 1. 精确查找并记录每个章节标题在原文中的物理位置
        for item in sorted_chapter_data:
            # 从上一个找到的位置之后开始搜索，确保定位到正确的重复项
            current_pos = original_content.find(item.content, last_find_pos + 1)
            if current_pos != -1:
                chapter_positions.append(
                    {
                        "line_index": item.line_index,
                        "start_pos": current_pos,
                        "content_len": len(item.content),
                    }
                )
                last_find_pos = current_pos
            else:
                # 如果在原文中找不到搜索结果里的标题（不太可能发生），则标记字数为 -1 以示区分
                char_counts[item.line_index] = -1

        # 2. 根据精确的位置列表计算字数
        count_chapters = len(chapter_positions)
        for i, pos_info in enumerate(chapter_positions):
            # 如果前一步已标记为错误，则跳过
            if char_counts.get(pos_info["line_index"]) == -1:
                continue

            # 定义当前章节内容的起始点（标题之后）
            text_start = pos_info["start_pos"] + pos_info["content_len"]

            if i + 1 < count_chapters:
                # 如果不是最后一个章节，则结束点是下一个章节标题的起始点
                text_end = chapter_positions[i + 1]["start_pos"]
                text_slice = original_content[text_start:text_end]
            else:
                # 如果是最后一个章节，代表切片到文件末尾
                text_slice = original_content[text_start:]

            count = TextCounter.count_text_chars(file_path, text_slice, count_punctuations=True, readable_count=False)
            char_counts[pos_info["line_index"]] = count

        return char_counts

    @classmethod
    def _format_report(
        cls,
        original_lines: List[str],
        chapter_info_list: List[ChapterInfo],
        char_counts: Dict[int, int],
        disordered_indices: Set[int],
    ) -> str:
        """生成最终的报告文本"""
        result_lines = []
        max_char_count = max(char_counts.values()) if char_counts else 0

        # 统计数据
        stats = {"disordered": len(disordered_indices), "too_few": 0, "most_char": 0, "special": 0}

        disordered_counter = 1
        chapter_map = {item.line_index: item for item in chapter_info_list}

        for idx, line in enumerate(original_lines):
            if idx not in chapter_map:
                result_lines.append(line)
                continue

            info = chapter_map[idx]
            match = cls._MARKER_LINE_REGEX.match(line)
            if not match:
                result_lines.append(line)
                continue

            prefix = match.group(0)

            # --- 构建第一行：章节标题 ---
            if idx in disordered_indices:
                marker = f"【乱序行：{disordered_counter}/{stats['disordered']}】"
                chapter_line = f"{prefix}{marker}{info.content}"
                disordered_counter += 1
            else:
                marker = "【章节行】"
                new_prefix = prefix.replace("[匹配：", "[行号：")
                chapter_line = f"{new_prefix}{marker}{info.content}"

            result_lines.append(chapter_line)

            # --- 构建第二行：字数统计 ---
            count = char_counts.get(idx, 0)
            stats_line = cls._generate_stats_line(count, max_char_count)

            # 标记特殊状态
            is_most = False
            if cls._RE_MOST_CHARS.search(stats_line):
                stats_line += "（字数最多）　"
                stats["most_char"] += 1
                is_most = True

            if info.type in ("ungrouped", "special") and not is_most:
                stats_line += "（特殊章节）　"
                stats["special"] += 1
            elif cls._RE_TOO_FEW.search(stats_line) and not is_most:
                stats_line += "（字数过少）　"
                stats["too_few"] += 1

            result_lines.append(stats_line)

        # 更新头部摘要信息
        final_text = "\n".join(result_lines)
        return cls._update_summary_header(final_text, stats)

    # ==========================
    # 纯工具/解析方法
    # ==========================

    @classmethod
    def _find_best_chapter_match(cls, content: str) -> Optional[regex.Match]:
        """
        在内容中查找最合适的章节号匹配（单个数字或范围）

        逻辑：
        - 如果在范围之前出现单个数字，则优先选择单个数字
        - 否则，如果范围首先出现，则优先选择范围
        - 这能正确处理 "第1章 标题 2-3"（选择 "1"）和 "第1-2章"（选择 "1-2"）等情况
        """
        range_match = cls._RANGE_PATTERN.search(content)
        single_match = cls._SINGLE_NUM_PATTERN.search(content)

        if not single_match:
            return range_match
        if not range_match:
            return single_match

        # 如果单个数字的起始位置在范围匹配之前，则优先选择单个数字
        if single_match.start() < range_match.start():
            return single_match
        else:
            return range_match

    @staticmethod
    def _parse_num_string(raw_str: str) -> Optional[int]:
        """解析中英文数字字符串"""
        if "." in raw_str:
            return float("nan")  # 返回一个无法比较的特殊值

        if raw_str.isdigit():
            return int(raw_str)

        return util.chn_to_arabic_num(raw_str)

    @staticmethod
    def _generate_visual_bar(count: int, max_count: int, max_bar_len: int = 40) -> str:
        """生成表示长度的视觉条"""
        if count <= 0 or max_count <= 0:
            return ""

        chars_per_block = max_count / max_bar_len
        num_blocks = math.ceil(count / chars_per_block)

        return "█" * min(max_bar_len, max(1, num_blocks))

    @classmethod
    def _generate_stats_line(cls, count: int, max_count: int) -> str:
        """生成字数统计行文本"""
        MAX_BAR_LENGTH = 40
        visual_bar = cls._generate_visual_bar(count, max_count, MAX_BAR_LENGTH)
        padding_needed = MAX_BAR_LENGTH - len(visual_bar)
        padding_spaces = "┃" + "█" * padding_needed  # 占位符

        return f"【字数行】长度：{visual_bar}{padding_spaces}　　字数：{count} 字"

    @classmethod
    def _update_summary_header(cls, text: str, stats: Dict[str, int]) -> str:
        """更新结果文本中的搜索摘要部分"""
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("【搜索耗时"):
                line = cls._RE_TIME.sub("", line)
                line = cls._RE_TOTAL_MATCH.sub("", line)
                replacement = (
                    rf"匹配行：\1 | 乱序行：{stats['disordered']} | "
                    rf"字数过少：{stats['too_few']} | "
                    rf"字数最多：{stats['most_char']} | "
                    rf"特殊章节：{stats['special']}"
                )
                lines[i] = cls._RE_MATCH_COUNT.sub(replacement, line)
                break

        return "\n".join(lines)

    @staticmethod
    def _generate_new_number_str(num: int, renumber_type: int, pad_len: int) -> str:
        """根据重排类型生成新的数字字符串"""
        num_str = str(num)

        renumber_methods = {
            1: lambda: num_str.zfill(pad_len),
            2: lambda: util.arabic_to_chn_num(num),
            3: lambda: util.arabic_to_chn_num_variant(num_str),
            4: lambda: util.arabic_to_chn_num_variant(num_str, has_lower_limit=True),
            5: lambda: util.arabic_to_chn_num_variant(num_str, has_lower_limit=False, pad_len=pad_len),
            6: lambda: util.arabic_to_chn_num(num, to_upper=True),
        }

        # 从映射中获取对应的处理函数，如果找不到则默认返回原数字字符串
        return renumber_methods.get(renumber_type, lambda: num_str)()
