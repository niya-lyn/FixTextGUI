import difflib
import re
import os
import subprocess
from typing import Callable, List, Tuple

from core.env_config import env_config
from core.errors import SearchCancelledError
from core.constants import PatchSearchAction


class PatchFormatter:
    # 各类操作的标签前缀
    TAG_ADD = "a"
    TAG_DELETE = "d"
    TAG_REPLACE_OLD = "o"
    TAG_REPLACE_NEW = "n"
    TAG_START_MARK = "<［"  # 表示搜索结果中含有自定义的差异项展示
    TAG_END_MARK = "］>"

    HUNK_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    def __init__(self, file_path: str, is_patch_search=PatchSearchAction.NOT_PATCH_SEARCH, merge_threshold=2):
        self.file_path = file_path
        self.file_directory = os.path.dirname(file_path)
        self.is_patch_search = is_patch_search
        self.merge_threshold = merge_threshold  # 合并差异的阈值，小于等于此长度的上下文将被视为差异的一部分
        self.filename = os.path.basename(file_path)
        self.patch_dir = env_config.patch_dir
        self.diff_cmd = env_config.diff_cmd

    def generate_patch(self, context_lines=3) -> str:
        """
        使用 diff 命令生成 patch 文件，返回 patch 文件路径
        比较 self.file_path (新文件) 和其在 backup 目录中的备份 (旧文件)
        """
        if not self.file_path or not os.path.exists(self.file_path):
            raise FileNotFoundError(f"新文件（{self.file_path}）不存在，无法打开。")

        # 构造旧文件（备份文件）的路径
        backup_dir = os.path.join(os.path.dirname(self.file_directory), "booksBak")
        old_file_path = os.path.join(backup_dir, self.filename)

        if not os.path.exists(old_file_path):
            raise FileNotFoundError(
                f"备份文件 '{old_file_path}' 不存在\n需要先进行编辑保存操作，才能生成差异比对的结果"
            )

        try:
            with open(old_file_path, "r", encoding="utf-8") as f:
                old_content = f.read()
        except UnicodeDecodeError:
            with open(old_file_path, "r", encoding="gbk") as f:
                old_content = f.read()

        with open(old_file_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(old_content)

        new_file_path = self.file_path

        patch_file_name = self.filename + ".patch"
        patch_file_path = os.path.join(self.patch_dir, patch_file_name)

        # 确保 patch 目录存在
        os.makedirs(self.patch_dir, exist_ok=True)

        # 以 booksBak 为主体时将新旧文件交换
        if self.is_patch_search == PatchSearchAction.BAK_VS_BOOKS:
            old_file_path, new_file_path = new_file_path, old_file_path

        command = [
            self.diff_cmd,
            "-U",
            str(max(context_lines, 0)),
            os.path.normpath(old_file_path),
            os.path.normpath(new_file_path),
        ]

        try:
            # 运行 diff 命令并捕获其标准输出到内存
            creationflags = 0
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                creationflags = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                creationflags=creationflags,
            )

            # diff 命令在文件有差异时返回 1，无差异时返回 0，出错时返回 >1。
            if result.returncode > 1:
                raise IOError(f"生成 patch 文件失败: {result.stderr}")

            patch_content = result.stdout
            modified_content = ""

            # 如果 patch 内容不为空，则移除前两行（避免 Windows 下用户未开启 utf-8 文件名支持）
            if patch_content:
                lines = patch_content.splitlines(True)
                if len(lines) > 2:
                    modified_content = "".join(lines[2:])

            with open(patch_file_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(modified_content)

            return patch_file_path

        except Exception as e:
            raise IOError(f"生成 patch 文件时发生未知错误: {e}")

    def merge_patch_match_contexts(self, patch_content, check_cancel: Callable[[], bool], max_match_lines: int):
        lines = patch_content.splitlines()
        merged_info = []

        current_block = []
        current_new_ln = 0
        last_good_ln = 0  # 记录上一个有效行（上下文或新增行）的行号

        pending_deletes = []
        pending_inserts = []

        def flush_pending():
            """
            精确处理差异块的行号：
            - 删除的行 (-) “借用”前一行的行号，不占用新文件的行号
            - 新增的行 (+) 正常递增行号
            - 替换的行 (-/+) 根据数量匹配处理，如果不等长则启用智能相似度配对
            """
            nonlocal current_new_ln, last_good_ln
            if not pending_deletes and not pending_inserts:
                return

            num_del = len(pending_deletes)
            num_ins = len(pending_inserts)
            paired = {}  # 记录 delete_index -> insert_index

            if num_del > 0 and num_ins > 0:
                # 行数相等，直接一对一映射，不计算相似度
                if num_del == num_ins:
                    paired = {i: i for i in range(num_del)}

                # 如果行数不相等，但差距数量极其庞大（例如删 100 行增 50 行），为防止双层循环卡死，强制降级为按顺序粗略匹配
                elif num_del * num_ins > 400:  # 阈值可调，400 次运算属于极度安全的范围
                    common_len = min(num_del, num_ins)
                    paired = {i: i for i in range(common_len)}

                # 行数不相等且在安全计算范围内，启用智能相似度配对
                else:
                    import difflib
                    matches = []
                    for i, d_line in enumerate(pending_deletes):
                        for j, i_line in enumerate(pending_inserts):
                            if d_line.strip() or i_line.strip():
                                ratio = difflib.SequenceMatcher(None, d_line, i_line, autojunk=False).ratio()
                                if ratio > 0.3:
                                    matches.append((ratio, i, j))
                            elif not d_line and not i_line:
                                matches.append((1.0, i, j))

                    matches.sort(key=lambda x: x[0], reverse=True)

                    used_d, used_i = set(), set()
                    raw_pairs = []
                    for ratio, i, j in matches:
                        if i not in used_d and j not in used_i:
                            raw_pairs.append((i, j))
                            used_d.add(i)
                            used_i.add(j)

                    raw_pairs.sort(key=lambda x: x[0])
                    last_j = -1
                    for i, j in raw_pairs:
                        if j > last_j:
                            paired[i] = j
                            last_j = j

            # --- 双指针按原始顺序输出差异块 ---
            d_idx, i_idx = 0, 0
            while d_idx < num_del or i_idx < num_ins:

                # 1. 纯新增 (a)
                if i_idx < num_ins and i_idx not in paired.values():
                    formatted_text = self._format_tag(pending_inserts[i_idx], self.TAG_ADD)
                    for sub_line in formatted_text.split("\n"):
                        current_block.append((max(current_new_ln, 0), True, sub_line))
                        current_new_ln += 1
                    last_good_ln = current_new_ln - 1
                    i_idx += 1
                    continue

                # 2. 处理删除行 (d) 或者精准替换 (o/n)
                if d_idx < num_del:
                    if d_idx in paired and paired[d_idx] == i_idx:
                        merged_diff = self._generate_inline_diff(pending_deletes[d_idx], pending_inserts[i_idx])
                        diff_lines = merged_diff.split("\n")

                        if pending_deletes[d_idx] != "" and pending_inserts[i_idx] == "":
                            diff_lines.append("")

                        for j, diff_line in enumerate(diff_lines):
                            display_ln = current_new_ln + j
                            current_block.append((max(display_ln, 0), True, diff_line))

                        current_new_ln += 1
                        last_good_ln = current_new_ln - 1
                        d_idx += 1
                        i_idx += 1
                    else:
                        borrowed_ln = last_good_ln
                        formatted_text = self._format_tag(pending_deletes[d_idx], self.TAG_DELETE)
                        for sub_line in formatted_text.split("\n"):
                            current_block.append((max(borrowed_ln, 0), True, sub_line))
                        d_idx += 1
                else:
                    break

            pending_deletes.clear()
            pending_inserts.clear()

        for i, line in enumerate(lines):
            # 根据上游传入回调的执行结果，在这里用异常中断
            # 每 1000 行检查一次取消状态
            if i % 1000 == 0 and check_cancel():
                raise SearchCancelledError()

            if not line:
                continue

            # 直接用行首字符判断是何种类型的行
            char = line[0]

            if char == " ":
                flush_pending()
                current_block.append((max(current_new_ln, 0), False, line[1:]))
                current_new_ln += 1
                last_good_ln = current_new_ln - 1

            elif char == "-":
                if line.startswith("---"):  # 文件名行，在实际 patch 中已移除
                    continue
                # 如果之前有等待处理的 insert，但现在遇到了 delete，说明 insert 是孤立的
                if pending_inserts:
                    flush_pending()
                pending_deletes.append(line[1:])

            elif char == "+":
                if line.startswith("+++"):  # 文件名行，在实际 patch 中已移除
                    continue
                pending_inserts.append(line[1:])

            elif char == "@":
                # 只有当首字符是 @ 时才触发正则校验，且使用预编译正则
                if line.startswith("@@"):
                    flush_pending()
                    if current_block:
                        merged_info.append(current_block)
                        current_block = []

                    # 提取新文件的起始行号
                    m = self.HUNK_PATTERN.match(line)
                    if m:
                        current_new_ln = int(m.group(1))
                        last_good_ln = current_new_ln - 1

        flush_pending()
        if current_block:
            merged_info.append(current_block)

        return self._split_oversized_blocks(merged_info, max_match_lines)

    def _generate_inline_diff(self, old_text, new_text):
        """
        使用 difflib 提取差异，并对结果进行后处理，
        将由短上下文隔开的零碎差异合并，并根据差异类型智能选择标签
        """
        matcher = difflib.SequenceMatcher(None, old_text, new_text, autojunk=False)
        opcodes = matcher.get_opcodes()

        # 步骤1：将操作码分组
        groups = []
        if not opcodes:
            return ""

        # 使用改进的分组逻辑，正确识别作为分隔符的长相等块
        for tag, i1, i2, j1, j2 in opcodes:
            is_long_equal = tag == "equal" and (i2 - i1) > self.merge_threshold
            if is_long_equal:
                groups.append([(tag, i1, i2, j1, j2)])  # 分隔符组
            else:
                # 如果是第一个块，或前一个是分隔符组，则新建一个差异组
                if not groups or (len(groups[-1]) == 1 and groups[-1][0][0] == "equal"):
                    groups.append([])
                groups[-1].append((tag, i1, i2, j1, j2))

        # 步骤2：遍历分组，生成最终的文本
        result_parts = []
        for group in groups:
            if not group:
                continue

            first_opcode = group[0]
            # 检查是否是“长相等”分隔符组
            is_separator_group = first_opcode[0] == "equal" and len(group) == 1

            # 如果是“长相等”组，直接附加文本
            if is_separator_group:
                _, i1, i2, _, _ = first_opcode
                result_parts.append(old_text[i1:i2])
                continue

            # --- “差异”组的处理逻辑 ---

            has_delete = any(op[0] == "delete" for op in group)
            has_insert = any(op[0] == "insert" for op in group)
            has_replace = any(op[0] == "replace" for op in group)

            # 场景一：替换 (包含 replace 操作，或同时有 insert 和 delete)
            if has_replace or (has_delete and has_insert):
                start_i1, end_i2 = group[0][1], group[-1][2]
                start_j1, end_j2 = group[0][3], group[-1][4]
                o_part = old_text[start_i1:end_i2]
                n_part = new_text[start_j1:end_j2]

                if "\n" in o_part or "\n" in n_part:
                    if o_part:
                        result_parts.append(self._format_tag(o_part, self.TAG_DELETE))
                    if n_part:
                        result_parts.append(self._format_tag(n_part, self.TAG_ADD))
                elif o_part or n_part:
                    result_parts.append(
                        f"{self.TAG_START_MARK}{self.TAG_REPLACE_OLD}:{o_part}{self.TAG_END_MARK}"
                        f"{self.TAG_START_MARK}{self.TAG_REPLACE_NEW}:{n_part}{self.TAG_END_MARK}"
                    )

            # 场景二：纯删除或纯插入（或仅包含短 equal）
            # 遍历组内所有操作码，重建文本，而不是只提取差异部分
            else:
                for tag, i1, i2, j1, j2 in group:
                    if tag == "equal":
                        result_parts.append(old_text[i1:i2])
                    elif tag == "delete":
                        result_parts.append(self._format_tag(old_text[i1:i2], self.TAG_DELETE))
                    elif tag == "insert":
                        result_parts.append(self._format_tag(new_text[j1:j2], self.TAG_ADD))

        return "".join(result_parts)

    def _format_tag(self, text, tag_type):
        """
        处理包含换行符的变动块
        将文本按换行拆分，每一行单独包裹标签，确保不破坏外层的按行切分逻辑
        """
        if text is None:
            return ""

        # 无论 line 是否为空，统一包裹标签，以维持正确的行数
        return "\n".join(
            f"{self.TAG_START_MARK}{tag_type}:{line}{self.TAG_END_MARK}" for line in text.split("\n")
        )

    def _split_oversized_blocks(self, merged_info: List[List[Tuple]], max_match_lines: int) -> List[List[Tuple]]:
        # 简化版截断，逻辑保持不变
        MAX_MATCH_LINES = max_match_lines
        result = []
        for block in merged_info:
            chunk, m_count = [], 0
            for item in block:
                chunk.append(item)
                if item[1]:  # item[1] 是 is_match
                    m_count += 1

                if m_count >= MAX_MATCH_LINES:
                    result.append(chunk)
                    chunk, m_count = [], 0

            if chunk:
                result.append(chunk)

        return result

    @classmethod
    def _get_patterns(cls):
        """获取用于匹配标签的正则表达式"""
        start_mark = re.escape(cls.TAG_START_MARK)
        end_mark = re.escape(cls.TAG_END_MARK)

        any_tag_pattern = re.compile(
            f"{start_mark}[{cls.TAG_ADD}{cls.TAG_DELETE}{cls.TAG_REPLACE_OLD}{cls.TAG_REPLACE_NEW}]:.*?{end_mark}"
        )
        on_pair_pattern = re.compile(
            f"({start_mark}{cls.TAG_REPLACE_OLD}:(.*?){end_mark})"
            f"(\\s*)"
            f"({start_mark}{cls.TAG_REPLACE_NEW}:(.*?){end_mark})"
        )

        return any_tag_pattern, on_pair_pattern

    @classmethod
    def get_actionable_range(cls, full_text: str, start_pos: int, end_pos: int) -> Tuple[int, int]:
        """
        根据给定的起始和结束索引，向外扩展以包含完整的、相关的差异标签
        用于处理无选区或选区切断标签的情况
        返回: (expanded_start, expanded_end)。如果未找到任何有效标记，返回 (-1, -1)
        """
        any_tag_pattern, _ = cls._get_patterns()

        # 1. 无选区（光标状态）：查找光标所在位置或之后的第一个标记
        if start_pos == end_pos:
            found_match = None
            for match in any_tag_pattern.finditer(full_text):
                if match.end() > start_pos:
                    found_match = match
                    break

            if not found_match:
                return -1, -1
            start_pos, end_pos = found_match.span()

        # 2. 扩展选区：查找所有与当前范围相交的标记
        all_tags = list(any_tag_pattern.finditer(full_text))
        intersecting_tags = [m for m in all_tags if m.start() < end_pos and m.end() > start_pos]

        if not intersecting_tags:
            return -1, -1

        expanded_start = min(m.start() for m in intersecting_tags)
        expanded_end = max(m.end() for m in intersecting_tags)

        # 3. 特殊处理 o/n 相邻的配对情况
        first_tag_match = intersecting_tags[0]
        if first_tag_match.group(0).startswith(f"{cls.TAG_START_MARK}{cls.TAG_REPLACE_NEW}:"):
            idx = all_tags.index(first_tag_match)
            if idx > 0:
                prev_tag = all_tags[idx - 1]
                if prev_tag.group(0).startswith(f"{cls.TAG_START_MARK}{cls.TAG_REPLACE_OLD}:"):
                    between = full_text[prev_tag.end() : first_tag_match.start()]
                    if not between or between.isspace():
                        expanded_start = prev_tag.start()

        last_tag_match = intersecting_tags[-1]
        if last_tag_match.group(0).startswith(f"{cls.TAG_START_MARK}{cls.TAG_REPLACE_OLD}:"):
            idx = all_tags.index(last_tag_match)
            if idx < len(all_tags) - 1:
                next_tag = all_tags[idx + 1]
                if next_tag.group(0).startswith(f"{cls.TAG_START_MARK}{cls.TAG_REPLACE_NEW}:"):
                    between = full_text[last_tag_match.end() : next_tag.start()]
                    if not between or between.isspace():
                        expanded_end = next_tag.end()

        return expanded_start, expanded_end

    @classmethod
    def revert_string(cls, original_text: str) -> str:
        """
        对传入的文本片段进行差异反转操作
        - 添加(a)变删除(d)，删除(d)变添加(a)
        - 替换(o/n)：将 n 里的内容换成 o 的，并且只保留 n 标签的壳
        """
        any_tag_pattern, on_pair_pattern = cls._get_patterns()
        modified_text = original_text

        pair_matches = list(on_pair_pattern.finditer(original_text))
        single_matches = list(any_tag_pattern.finditer(original_text))

        # 过滤掉已经包含在 o/n 对中的独立标记
        pair_intervals = [range(m.start(), m.end()) for m in pair_matches]
        standalone_single_matches = [
            m
            for m in single_matches
            if not any(m.start() in interval and (m.end() - 1) in interval for interval in pair_intervals)
        ]

        # 合并后从后往前处理（避免索引错位）
        all_relevant_matches = sorted(pair_matches + standalone_single_matches, key=lambda m: m.start(), reverse=True)

        for match in all_relevant_matches:
            start, end = match.span()

            if match.re is on_pair_pattern:
                # 处理 o/n 对
                _, o_content, _, _, _ = match.groups()
                swapped_content = f"{cls.TAG_START_MARK}{cls.TAG_REPLACE_NEW}:{o_content}{cls.TAG_END_MARK}"
                modified_text = modified_text[:start] + swapped_content + modified_text[end:]
            else:
                # 处理独立的 a/d 标记
                tag = match.group(0)
                tag_type = tag[len(cls.TAG_START_MARK)]
                content = tag[len(cls.TAG_START_MARK) + 2 : -len(cls.TAG_END_MARK)]
                swapped_tag = ""

                if tag_type == cls.TAG_ADD:
                    swapped_tag = f"{cls.TAG_START_MARK}{cls.TAG_DELETE}:{content}{cls.TAG_END_MARK}"
                elif tag_type == cls.TAG_DELETE:
                    swapped_tag = f"{cls.TAG_START_MARK}{cls.TAG_ADD}:{content}{cls.TAG_END_MARK}"

                if swapped_tag:
                    modified_text = modified_text[:start] + swapped_tag + modified_text[end:]

        return modified_text

    @classmethod
    def strip_all_tags(cls, text: str) -> str:
        """
        移除文本中所有特定格式的标签
        - o 和 d 类型的标签连同内容一起移除
        - n 和 a 类型的标签只移除标签结构，保留内容
        """
        if not text:
            return text

        start_mark = re.escape(cls.TAG_START_MARK)
        end_mark = re.escape(cls.TAG_END_MARK)

        # 1. 针对整行删除：标签独占整行时，连同其后的换行符一起移除
        whole_line_remove_pattern = re.compile(
            f"^{start_mark}[{cls.TAG_REPLACE_OLD}{cls.TAG_DELETE}]:.*?{end_mark}\\n", re.M
        )
        text = whole_line_remove_pattern.sub("", text)

        # 2. 移除剩余非独占一行的 'o' (旧内容) 和 'd' (删除) 标签及其包含的内容
        inline_remove_pattern = re.compile(f"{start_mark}[{cls.TAG_REPLACE_OLD}{cls.TAG_DELETE}]:.*?{end_mark}")
        text = inline_remove_pattern.sub("", text)

        # 3. 剥离 'a' (新增) 和 'n' (新内容) 标签的外壳，仅保留其内部内容 (利用 \1 提取捕获组内容)
        keep_pattern = re.compile(f"{start_mark}[{cls.TAG_ADD}{cls.TAG_REPLACE_NEW}]:(.*?){end_mark}")
        text = keep_pattern.sub(r"\1", text)

        return text
