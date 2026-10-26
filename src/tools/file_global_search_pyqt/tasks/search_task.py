import regex
import bisect
import tempfile
import json
import os
import subprocess
import time
import logging

from qtpy.QtCore import QRunnable, QObject, Signal

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.search_options import SearchOptions

import utils.util as util
from core.env_config import env_config
from core.errors import SearchCancelledError
from utils.patch_formatter import PatchFormatter
from core.constants import PatchSearchAction


class SearchSignals(QObject):
    formattingResult = Signal(int)
    searchFinished = Signal(str, int, int, list)
    searchError = Signal(str)


class SearchTask(QRunnable):

    _LINE_NUM_PATTERN = regex.compile(r"\[(?:匹配|行号)：(\d+)\]")

    def __init__(
        self,
        file_path,
        search_term,  # 单纯的搜索正则表达式
        search_condition,  # config 文件中的字典项，包括各种属性
        prev_lines,
        next_lines,
        search_options: "SearchOptions",
        is_patch_search=PatchSearchAction.NOT_PATCH_SEARCH,
        patch_merge_threshold=2,
    ):
        super().__init__()

        self.file_path = file_path
        self.search_term = search_term
        self.search_condition = search_condition
        self.prev_lines = prev_lines
        self.next_lines = next_lines
        self.search_options = search_options
        self.regex_searcher_script = env_config.regex_searcher_script
        self.php_program = env_config.php_program
        self.chapter_analyzer_script = env_config.chapter_analyzer_script

        self.is_patch_search = is_patch_search
        self.patch_formatter = PatchFormatter(self.file_path, is_patch_search, patch_merge_threshold)

        self.signals = SearchSignals()
        self._is_running = True

    def run(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as file:
                if self.is_patch_search == PatchSearchAction.NOT_PATCH_SEARCH:
                    merged_info, lines, matches_count, all_matched_line_numbers = self._run_file_search(file)
                    if not self._is_running:
                        return
                    total_lines = len(lines)
                else:
                    merged_info, lines, matches_count, all_matched_line_numbers = self._run_patch_search(file)
                    if not self._is_running:
                        return

                    # 在 patch 模式下，需要单独计算原始文件的总行数
                    file.seek(0)
                    total_lines = len(file.readlines())

                # 如果 merged_info 为 None，说明搜索被中断或没有结果，提前退出
                if merged_info is None:
                    # 对于 patch search，如果没差异，会在这里的早些时候返回
                    # 如果有差异但被中断，merged_info 可能是 None
                    return

                match_blocks = self._format_match_blocks(merged_info, lines)
                match_blocks_count = len(match_blocks)
                result_text = self._format_search_result(match_blocks, match_blocks_count, total_lines)

                if not self._is_running:
                    return

                self.signals.searchFinished.emit(
                    result_text, match_blocks_count, matches_count, all_matched_line_numbers
                )

        except regex.error as e:
            if self._is_running:
                self.signals.searchError.emit(f"无效的正则表达式，无法进行搜索：{str(e)}")
        except Exception as e:
            if self._is_running:
                self.signals.searchError.emit(f"搜索过程中发生错误: {e}")

    def check_cancel(self) -> bool:
        """提供给下游策略的回调，用于检查是否需要中断"""
        return not self._is_running

    def _run_file_search(self, file):
        # 首先尝试使用外部的 PHP 脚本进行正则搜索，会比直接用 Python 快很多
        match_positions = self._run_php_searcher()

        file_content = file.read()  # php 搜完再读文件

        # 如果 PHP 搜索失败（比如后行断言使用了变长的条件），则回退到 Python 的正则搜索
        # Python 的 regex 包可支持更复杂的正则写法，但同时效率显著下降
        if match_positions is None:
            if not self._is_running:
                return None, None, 0, []

            logging.info("回退到 Python 正则搜索")
            pattern = self._compile_python_regex()
            match_positions = self._run_python_searcher(pattern, file_content)

        if not self._is_running:
            return None, None, 0, []

        # 开始格式化搜索结果
        matches_count = len(match_positions)
        self.signals.formattingResult.emit(matches_count)

        lines = file_content.splitlines(True)
        merged_info, all_matched_line_numbers = self._merge_match_contexts(match_positions, lines)

        return merged_info, lines, matches_count, all_matched_line_numbers

    def _run_php_searcher(self):
        """
        尝试使用外部 PHP 脚本进行搜索，并支持在 Python 端中断
        成功则返回匹配位置列表，失败或被中断则返回 None
        """
        if not os.path.exists(self.regex_searcher_script):
            logging.error(f"PHP script not found at {self.regex_searcher_script}, skipping.")
            return None

        # 将临时文件路径的定义提前，以便在 finally 中可靠地清理
        regex_file_path = None
        result_file_path = None
        log_file_path = None

        try:
            php_pattern = self._get_php_regex_pattern()

            # 创建临时文件
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as regex_file:
                regex_file_path = regex_file.name
                regex_file.write(php_pattern)

            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as result_file:
                result_file_path = result_file.name

            # 再创建一个日志文件用于捕获输出，防止 PIPE 死锁
            with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".log", encoding="utf-8") as tmp_log:
                log_file_path = tmp_log.name

            command = [
                self.php_program,
                self.regex_searcher_script,
                regex_file_path,
                self.file_path,
                result_file_path,
            ]

            # --- 异步执行与轮询检查 ---

            with open(log_file_path, "w", encoding="utf-8") as log_file:
                # 1. 使用 Popen 启动子进程，这是非阻塞的
                creationflags = 0
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creationflags = subprocess.CREATE_NO_WINDOW
                p = subprocess.Popen(
                    command,
                    stdout=log_file,
                    stderr=log_file,
                    text=True,
                    creationflags=creationflags,
                )

                # 2. 进入轮询循环，等待子进程结束或被中断
                while p.poll() is None:  # 当子进程还在运行时，poll() 返回 None
                    # 2.1 检查中断标志
                    if not self._is_running:
                        logging.info("Stop signal received. Terminating PHP process...")
                        try:
                            p.terminate()  # 尝试友好地终止
                            p.wait(timeout=1)  # 等待一小段时间确保进程已终止
                        except subprocess.TimeoutExpired:
                            logging.error("PHP process did not terminate gracefully, killing it.")
                            p.kill()  # 如果无法友好终止，则强制杀死
                        logging.info("PHP process terminated.")
                        return None  # 返回 None 表示任务被中断

                    # 2.2 短暂休眠，避免 CPU 空转
                    # 单次休眠 0.1 秒的间隔意味着每秒检查 10 次，响应性足够高
                    time.sleep(0.1)

            # --- 子进程已自行结束，处理结果 ---

            # 获取进程的返回码和输出
            return_code = p.returncode
            if return_code != 0:
                logging.error(f"--- PHP 搜索失败 ---")
                logging.error(f"PHP 脚本以错误码退出: {return_code}")
                # 从日志文件中读取输出
                with open(log_file_path, "r", encoding="utf-8") as f:
                    log_content = f.read()
                logging.error(f"PHP 输出日志:\n{log_content.strip()}")

                return None

            # 读取并解析 JSON 结果
            with open(result_file_path, "r", encoding="utf-8") as f:
                result_content = f.read()

            if not result_content:
                logging.warning("PHP 脚本成功执行，但结果文件为空")
                return None

            result_data = json.loads(result_content)

            if result_data.get("status") == "success":
                # PHP 脚本和内部逻辑都成功
                return result_data.get("data", [])
            else:
                # PHP 脚本执行成功，但其内部逻辑报告了错误
                logging.error(f"PHP 脚本报告了一个内部错误: {result_data.get('message')}")
                return None

        except Exception as e:
            # 捕获其他潜在错误，例如 Popen 启动失败
            logging.error(f"An error occurred while running PHP searcher: {e}")
            if "p" in locals() and p.poll() is None:
                p.kill()  # 如果发生异常时进程仍在，也杀死它
            return None
        finally:
            # 确保无论如何都清理临时文件
            if regex_file_path and os.path.exists(regex_file_path):
                os.remove(regex_file_path)
            if result_file_path and os.path.exists(result_file_path):
                os.remove(result_file_path)
            if log_file_path and os.path.exists(log_file_path):
                os.remove(log_file_path)

    def _get_php_regex_pattern(self) -> str:
        """将 Python 的正则表达式和 flags 转换为 PHP 兼容的模式字符串"""
        pattern_str = self.search_term
        if not self.search_options.use_regex:
            pattern_str = regex.escape(self.search_term)
        else:
            # 如果是正则模式，需要将 Python 风格的 Unicode 写法转换为 PHP 的 \x{...} 格式
            pattern_str = util.change_unicode_to_pcre_format(pattern_str)

            # 如果是正则模式，需要将 Python 风格的反向引用 \1, \10 等
            # 转换为 PCRE 更兼容的 \g1, \g10 格式
            # 这可以解决 \1+ 在 PCRE 中存在的歧义问题
            pattern_str = regex.sub(r"(?<!\\)\\(\d+)", r"\\g\1", pattern_str)

        # 将 Python regex flags 转换为 PHP PCRE 修饰符
        py_flags = self.search_options.get_regex_flags()
        php_modifiers = ""
        if py_flags & regex.IGNORECASE:
            php_modifiers += "i"
        if py_flags & regex.MULTILINE:
            php_modifiers += "m"
        if py_flags & regex.DOTALL:
            php_modifiers += "s"
        php_modifiers += "u"

        # PCRE 的模式需要分隔符，通常使用 '/'
        # 需要对模式本身的分隔符进行转义
        escaped_pattern = pattern_str.replace("/", r"\/")

        return f"/{escaped_pattern}/{php_modifiers}"

    def _compile_python_regex(self) -> regex.Pattern:
        """编译 Python 的正则表达式对象"""
        pattern_str = self.search_term
        if not self.search_options.use_regex:
            pattern_str = regex.escape(self.search_term)
        flags = self.search_options.get_regex_flags()

        return regex.compile(pattern_str, flags)

    def _run_python_searcher(self, pattern: regex.Pattern, file_content: str):
        # 在原始文本上查找所有匹配，注意此处返回的是【字符】偏移量
        match_positions = []
        for match in pattern.finditer(file_content):
            if not self._is_running:
                # 如果任务被停止，立即返回空列表，中断耗时操作
                # 这里如果用 findall 就无法中断了
                return []

            # 返回起点和终点
            match_positions.append((match.start(), match.end()))

        return match_positions

    def _merge_match_contexts(self, match_positions, lines):
        """
        计算每处匹配位置的上下文行范围，并合并重叠或相邻的上下文块
        """
        if not match_positions:
            return [], []  # 修改返回值，顺便返回所有匹配的行号列表

        num_lines = len(lines)
        if num_lines == 0:
            return [], []

        # 1. 预计算每行的起始字符偏移量 O(L)
        line_start_offsets = [0] * num_lines
        current_offset = 0
        for i, line in enumerate(lines):
            if not self._is_running:
                return [], []

            line_start_offsets[i] = current_offset
            current_offset += len(line)
        # 添加文件末尾偏移量作为哨兵，方便 bisect_right 处理最后一行
        line_start_offsets.append(current_offset)

        # 结果列表
        merged_info = []

        # 当前正在构建的块的状态
        # 使用 -1 初始化，表示还没有开始构建块
        current_block_start_idx = -1
        current_block_end_idx = -1
        current_match_lines = set()
        all_matched_line_numbers = set()

        # 2. 流式遍历匹配项
        match_positions.sort()

        # 注意：这里的 pos 是 (start_pos, end_pos) 元组
        for start_pos, end_pos in match_positions:
            if not self._is_running:
                return [], []

            # 二分查找，计算起点所在的行号 (1-based)
            start_line_1_based = bisect.bisect_right(line_start_offsets, start_pos)

            # 计算终点所在的行号
            # 如果 end_pos 正好在一个换行符的下一位，它不应该算作跨越到了下一行
            # 因此使用 max(start_pos, end_pos - 1) 来寻找实际影响的行
            effective_end_pos = max(start_pos, end_pos - 1) if end_pos > start_pos else start_pos
            end_line_1_based = bisect.bisect_right(line_start_offsets, effective_end_pos)

            # 该匹配项跨越的所有行号的集合
            matched_lines_for_this = set(range(start_line_1_based, end_line_1_based + 1))
            all_matched_line_numbers.update(matched_lines_for_this)

            # 计算该匹配项期望的上下文范围 (0-based 索引)
            new_start = max(0, start_line_1_based - 1 - self.prev_lines)
            new_end = min(num_lines, end_line_1_based + self.next_lines)

            # --- 合并逻辑的核心 ---

            if current_block_start_idx == -1:
                # 初始化第一个块
                current_block_start_idx = new_start
                current_block_end_idx = new_end
                current_match_lines.update(matched_lines_for_this)

            elif new_start < current_block_end_idx:
                # 【发生重叠或相邻】：当前项的头部 在 上一个块的尾部之前
                # 动作：直接延长当前块的尾部，并将当前匹配行加入集合
                # 这就是"多米诺"的自然处理：只要连上了，就融为一体
                current_block_end_idx = max(current_block_end_idx, new_end)
                current_match_lines.update(matched_lines_for_this)

            else:
                # 【断开】：当前项的头部 在 上一个块的尾部之后
                # 动作：封存上一个块，开始一个新的块
                merged_info.append((current_block_start_idx, current_block_end_idx, current_match_lines))

                # 重置状态
                current_block_start_idx = new_start
                current_block_end_idx = new_end
                current_match_lines = set(matched_lines_for_this)

        # 循环结束后，处理最后一个块
        if current_block_start_idx != -1:
            merged_info.append((current_block_start_idx, current_block_end_idx, current_match_lines))

        # 将 all_matched_line_numbers 转为排序好的列表并返回
        sorted_all_lines_numbers = sorted(list(all_matched_line_numbers))
        return self._split_oversized_blocks(merged_info), sorted_all_lines_numbers

    def _split_oversized_blocks(self, merged_info):
        """
        将超过匹配行数限制的块拆分成多个小块，避免显示因无限级联形成的巨大块

        拆分规则：
        - 每个子块最多包含 MAX_MATCH_LINES 个匹配行
        - 第一个子块保留原块的上文边界
        - 最后一个子块保留原块的下文边界
        - 中间子块以边缘匹配行作为边界，无额外上下文
        """
        MAX_MATCH_LINES = self.search_options.max_match_lines

        result = []

        for start_idx, end_idx, match_lines_set in merged_info:
            if not self._is_running:
                return []

            match_lines_sorted = sorted(match_lines_set)
            total_matches = len(match_lines_sorted)

            # 不需要拆分的块直接保留
            if total_matches <= MAX_MATCH_LINES:
                result.append((start_idx, end_idx, match_lines_set))
                continue

            # 按上限分组拆分
            num_chunks = (total_matches + MAX_MATCH_LINES - 1) // MAX_MATCH_LINES

            for i in range(num_chunks):
                chunk_lines = match_lines_sorted[i * MAX_MATCH_LINES : (i + 1) * MAX_MATCH_LINES]
                first_match_1_based = chunk_lines[0]
                last_match_1_based = chunk_lines[-1]

                # 第一个子块：保留原块的上文边界
                if i == 0:
                    chunk_start = start_idx
                else:
                    chunk_start = first_match_1_based - 1  # 1-based 转 0-based

                # 最后一个子块：保留原块的下文边界
                if i == num_chunks - 1:
                    chunk_end = end_idx
                else:
                    chunk_end = last_match_1_based  # 1-based 行号 = 0-based 下一索引

                result.append((chunk_start, chunk_end, set(chunk_lines)))

        return result

    def _run_patch_search(self, _):
        patch_file_path = self.patch_formatter.generate_patch(self.next_lines)
        try:
            with open(patch_file_path, "r", encoding="utf-8") as f:
                patch_content = f.read()
        except FileNotFoundError:
            # 如果没有生成 patch 文件（意味着没有差异），则直接返回
            self.signals.searchFinished.emit("", 0, 0, [])
            # 返回值签名：merged_info, lines, matches_count, all_matched_line_numbers
            return None, None, 0, []

        if not self._is_running:
            return None, None, 0, []

        # 1. 直接从 patch_formatter 获取最终的、带内联差异的格式化块
        # 这个块内部已经包含了正确的行号，包括“借用”的行号
        try:
            formatted_blocks = self.patch_formatter.merge_patch_match_contexts(
                patch_content, self.check_cancel, self.search_options.max_match_lines
            )
        except SearchCancelledError:
            logging.info("patch 差异项格式化已被中断")
            return None, None, 0, []

        # 2. 从格式化块中提取 all_matched_line_numbers
        all_matched_line_numbers = sorted(
            list(set(ln for block in formatted_blocks for ln, is_match, _ in block if is_match))
        )
        matches_count = len(all_matched_line_numbers)
        self.signals.formattingResult.emit(matches_count)

        # 3. 返回格式化块给 _format_match_blocks 处理
        # 返回签名：merged_info, lines, matches_count, all_matched_line_numbers
        # 将 formatted_blocks 作为 merged_info 传递，并将 lines 设为 None
        # _format_match_blocks 将根据 lines 是否为 None 来区分处理模式
        return formatted_blocks, None, matches_count, all_matched_line_numbers

    def _format_match_blocks(self, merged_info, lines):
        """
        格式化合并后的匹配信息为可显示的字符串
        针对普通搜索和差异比对（patch）搜索有不同的处理逻辑
        """
        # 模式一：差异比对模式
        # merged_info 是预格式化的块(formatted_blocks)，lines 为 None
        if lines is None:
            if not merged_info:
                return []

            formatted_blocks = merged_info
            match_blocks = []
            for block in formatted_blocks:
                context_strs = []
                for line_num, is_match, line_content in block:
                    # is_match 在此模式下表示这是一个差异行 (+, -, o/n)
                    # 我们用 [匹配：] 标签来高亮这些差异行
                    if is_match:
                        line_display = f"[匹配：{line_num}]"
                    else:
                        line_display = f"[行号：{line_num}]"

                    # _merge_patch_match_contexts 返回的 line_content 不带换行符，在此处补上
                    context_strs.append(line_display + line_content + "\n")

                context_str = "".join(context_strs)
                match_blocks.append(context_str)
            return match_blocks

        # 模式二：普通搜索模式
        match_blocks = []
        for start_idx, end_idx, match_lines_1_based in merged_info:
            # 使用 0-based 索引切片 lines
            context = lines[start_idx:end_idx]
            context_strs = []
            # enumerate 提供相对于 context 切片的 0-based 索引 j_offset
            for j_offset, line_content in enumerate(context):
                # 计算当前行的实际 1-based 行号
                current_line_num_1_based = start_idx + j_offset + 1

                # 格式化行前缀
                if current_line_num_1_based in match_lines_1_based:
                    line_display = f"[匹配：{current_line_num_1_based}]"
                else:
                    line_display = f"[行号：{current_line_num_1_based}]"

                # 假设 line_content 本身包含换行符 (因为用了 splitlines(True))
                context_strs.append(line_display + line_content)

            context_str = "".join(context_strs)
            match_blocks.append(context_str)

        return match_blocks

    def _format_search_result(self, match_blocks, match_blocks_count, total_lines):
        if not match_blocks_count:
            return (
                "【无匹配内容】"
                if self.is_patch_search == PatchSearchAction.NOT_PATCH_SEARCH
                else "【books 和 booksBak 内容一致，无差异】"
            )

        # 1. 获取章节数据并预处理
        # chapters_data: 存储完整的章节详情，格式: [{'title': '第一章', 'start_line': 1, 'end_line': 200}, ...]
        chapters_data = []
        # chapter_starts: 仅存储所有章节的起始行号，有序列表，专门用于二分查找 [1, 201, 405, ...]
        chapter_starts = []

        if self.search_options.show_chapter_title:
            temp_result_path = None
            try:
                # 调用 PHP，获取到的输出是【临时文件的路径】
                temp_result_path = util.run_php_script(self.chapter_analyzer_script, self.file_path)

                if temp_result_path:
                    temp_result_path = temp_result_path.strip()

                if temp_result_path and os.path.exists(temp_result_path):
                    with open(temp_result_path, "r", encoding="utf-8") as f:
                        chapters_data = json.load(f)

                    # 提取起始行号用于二分查找
                    chapter_starts = [ch["start_line"] for ch in chapters_data]

            except Exception as e:
                logging.error(f"获取章节信息失败: {e}")

            finally:
                # 清理工作
                if temp_result_path and os.path.exists(temp_result_path):
                    try:
                        os.remove(temp_result_path)
                    except OSError as e:
                        logging.error(f"删除临时文件失败: {temp_result_path}, {e}")

        # 将所有字符串片段放入列表，最后用 join() 一次性拼接
        # 这避免了在循环中反复创建新字符串对象
        result_parts = []

        # 构造头部信息
        header = "=" * 64 + "\n" + f"匹配内容【共有 N 处匹配】\n" + "=" * 64 + "\n"
        result_parts.append(header)

        # 2. 循环处理每一个匹配块
        is_chapter_search = self.search_condition.get("isChapterSearch")
        for cur_index, match in enumerate(match_blocks, start=1):
            chapter_info_str = ""

            # 搜索当前块文本中出现的第一个行号（代表该块的起始位置）
            m = self._LINE_NUM_PATTERN.search(match)
            if m:
                line_num = int(m.group(1))

                if total_lines > 0:
                    progress = (line_num / total_lines) * 100
                    progress_str = f"[进度：{progress:.2f}%]"

            # 仅当成功获取到章节数据时才进行查找
            if chapters_data:
                if is_chapter_search:  # 特殊处理：获取章节行的下一行……
                    line_num += 1

                # --- 二分查找 ---
                idx = bisect.bisect_right(chapter_starts, line_num) - 1

                if idx >= 0:
                    chapter = chapters_data[idx]

                    # 严谨性校验：确保行号确实在当前章节的范围内
                    # 虽然通常章节是连续的，但防止文本中有未被识别的空隙区域
                    # 这里的 <= 是必须的，因为 end_line 是包含在章节内的
                    if line_num <= chapter["end_line"]:
                        chapter_info_str = f"【章节名：{chapter['title']}】"

            # 3. 组装最终的文本块
            # 确保 match 结尾有换行符，避免与下文省略标记粘连在同一行
            if not match.endswith("\n"):
                match += "\n"

            block = (
                # 将进度字符串插入到【匹配项：xxx】后面
                f"\n【匹配项：{cur_index}/{match_blocks_count}】{progress_str}{chapter_info_str}\n"
                f"※※※（上文省略）※※※\n"
                f"{match}"
                f"※※※（下文省略）※※※\n"
            )
            result_parts.append(block)

        return "".join(result_parts)

    def stop(self):
        self._is_running = False
