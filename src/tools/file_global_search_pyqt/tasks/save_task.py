import os
import regex
import json
import logging
import shutil
import threading
import subprocess
from typing import Dict, Optional, List

from qtpy.QtCore import Signal, QObject, QRunnable

from core.env_config import env_config
from core.constants import PatchSearchAction


class SaveSignals(QObject):
    askBackup = Signal()
    showProgress = Signal()
    progressUpdated = Signal(int, int)
    saveFinished = Signal(str)
    saveError = Signal(str)
    saveCancelled = Signal()


class SaveTask(QRunnable):
    # --- 正则表达式预编译 ---
    # 1. 用于清理章节序号等干扰行的正则
    RE_MARKER_CLEAR = regex.compile(r"(?<=】)【章节名：.*?】|【章节行.*?】|【乱序行.*?】|【字数行.*?】.*?\n")
    # 2. 用于提取整个 Section 块的正则
    RE_SECTION_EXTRACT = regex.compile(r"【匹配项.*?】.*?※※※（下文省略）※※※", regex.DOTALL)
    # 3. 用于提取匹配项索引 (Match Index)
    RE_INDEX_MATCH = regex.compile(r"【匹配项：(\d+)/\d+】")
    # 4. 用于提取每行实际内容的正则 (多行模式)
    RE_LINE_CONTENT = regex.compile(r"^(?!【匹配项：|.*※※※（)(?:\[(?:行号|匹配).*?\])?(.*)$", regex.MULTILINE)
    # 5. 用于检测是否跳过该块的正则
    RE_SKIP_CHECK = regex.compile(r"※※※（上文省略）※※※[xX]|【匹配项：\d+/\d+.*】[xX]")

    # --- 差异项标识清理 ---
    # 整行删除，需要将尾部的换行符也移除，否则会多出一个空行，无法匹配原始的 initial_search_result
    RE_FULLLINE_REMOVE = regex.compile(r"^(?:\[(?:行号|匹配).*?\])?<［d:.*?］>\n", regex.MULTILINE)

    # 匹配并删除 'd' (删除) 和 'o' (旧值) 标记
    # 示例: <［d:被删除内容］> 或 <［o:旧内容］>
    RE_DO_MARKER_REMOVE = regex.compile(r"<［[do]:.*?］>")

    # 将 'a' (添加) 和 'n' (新值) 标记替换为其内部内容
    # 示例: <［a:新内容］> 会被替换为 "新内容"
    # 第一个捕获组 (.*?) 会获取冒号和结束标记之间的所有文本
    RE_AN_MARKER_REPLACE = regex.compile(r"<［[an]:(.*?)］>")

    # 如果用户手动去改差异项，因为都把这些标记字体的设置得很小，
    # 可能会留有一些前后标记没有清理干净
    RE_REMAINING_MARKER = regex.compile(r"<［[ando]: ?|］>")

    def __init__(self, file_path: str, initial_search_result: str, cur_text: str):
        super().__init__()

        self.file_path = file_path
        self.file_directory = os.path.dirname(file_path)
        self.filename = os.path.basename(file_path)
        self.initial_search_result = initial_search_result
        self.cur_text = cur_text
        self.go_replace_cmd = env_config.go_replace_cmd
        self.signals = SaveSignals()
        self.is_cancelled = False
        self.backup_confirmed = False
        self.backup_event = threading.Event()
        self.skip_backup_prompt = False
        self.is_patch_search = PatchSearchAction.NOT_PATCH_SEARCH

    def run(self):
        try:
            if not os.path.isfile(self.file_path):
                self.signals.saveError.emit("【所选文件不存在，无法保存】")
                return

            if not self.skip_backup_prompt:
                # 发出请求备份确认的信号
                self.signals.askBackup.emit()
                # 等待备份确认事件 (主线程弹窗选择后解锁)
                self.backup_event.wait()

                if self.is_cancelled:
                    self.signals.saveCancelled.emit()
                    return
            else:
                # 跳过弹窗，默认不备份
                self.backup_confirmed = False

            self.signals.showProgress.emit()

            if self.backup_confirmed:
                # 创建备份目录并备份文件
                self._backup_file()

            # -- 提取原始和当前的匹配部分 --

            # 特殊处理，清理章节序号标识，待整理
            original_clean = self.RE_MARKER_CLEAR.sub("", self.initial_search_result)
            current_clean = self.RE_MARKER_CLEAR.sub("", self.cur_text)

            # 清理差异项标识，待整理
            original_clean = self.RE_FULLLINE_REMOVE.sub("", original_clean)
            current_clean = self.RE_FULLLINE_REMOVE.sub("", current_clean)

            original_clean = self.RE_DO_MARKER_REMOVE.sub("", original_clean)
            current_clean = self.RE_DO_MARKER_REMOVE.sub("", current_clean)

            original_clean = self.RE_AN_MARKER_REPLACE.sub(r"\1", original_clean)
            current_clean = self.RE_AN_MARKER_REPLACE.sub(r"\1", current_clean)

            original_clean = self.RE_REMAINING_MARKER.sub("", original_clean)
            current_clean = self.RE_REMAINING_MARKER.sub(r"", current_clean)

            original_sections = self._extract_sections(original_clean)
            current_sections = self._extract_sections(current_clean)

            # -- 生成新的文件内容 --
            if len(original_sections) > 0:
                self._perform_save(original_sections, current_sections)

            self.signals.saveFinished.emit("Save Finished.")

        except Exception as e:
            error_msg = f"【保存过程中发生意外错误: {str(e)}】"
            logging.error(error_msg)
            self.signals.saveError.emit(error_msg)

    def _get_backup_file_path(self) -> str:
        backup_dir = os.path.join(os.path.dirname(self.file_directory), "booksBak")
        os.makedirs(backup_dir, exist_ok=True)

        return os.path.join(backup_dir, self.filename)

    def _backup_file(self):
        # 复制文件到备份目录
        backup_file_path = self._get_backup_file_path()
        shutil.copy2(self.file_path, backup_file_path)

    def _extract_sections(self, text: str) -> List[str]:
        return self.RE_SECTION_EXTRACT.findall(text)

    def _perform_save(self, original_sections: List[str], current_sections: List[str]):
        # --- 1. 预处理原始 sections ---
        original_data: Dict[int, str] = {}
        for section in original_sections:
            index = self._get_match_index_safe(section)
            if index is not None:
                content = self._extract_line_contents(section)
                original_data[index] = content

        # --- 2. 预处理当前 sections ---
        current_data: Dict[int, str] = {}
        for section in current_sections:
            if self._should_skip_section(section):  # 检查是否跳过
                continue
            index = self._get_match_index_safe(section)
            if index is not None:
                content = self._extract_line_contents(section)
                current_data[index] = content

        # --- 3. 比较并构建替换列表 ---
        before_sections = []
        after_sections = []
        processed_indices_count = 0  # 用于进度更新
        total_comparable_indices = len(original_data)  # 总的可比较项

        # 遍历原始数据的索引进行比较
        for index, original_content in original_data.items():
            processed_indices_count += 1

            # 在当前数据中查找对应索引的内容 (O(1) 查找)
            current_content = current_data.get(index)

            # 只有在当前内容存在且与原始内容不同时，才添加到替换列表
            # 如果 current_content is None，表示该项在当前编辑中被删除或跳过了，
            # 这种情况不添加到替换列表
            # 还有个坑是当匹配项中的文字被完全删除（变成 ""），只留下上下文的边界行，这时无法撤销还原
            if current_content is not None and original_content != "" and original_content != current_content:
                if original_content and not current_content:
                    original_content += "\n"  # 完全删除某一项，需要带上末尾换行符，将原来的整段删掉

                before_sections.append(original_content)
                after_sections.append(current_content)

            # 更新进度条
            if processed_indices_count % 500 == 0 or processed_indices_count == total_comparable_indices:
                self.signals.progressUpdated.emit(processed_indices_count, total_comparable_indices)

        # --- 4. 执行替换 ---
        if before_sections:  # 仅当有实际变化时才执行替换
            self._do_replace(before_sections, after_sections)

    def _get_match_index_safe(self, section: str) -> Optional[int]:
        match = self.RE_INDEX_MATCH.search(section)
        try:
            return int(match.group(1)) if match else None
        except (ValueError, TypeError):
            logging.warning(f"警告：无法从 section 提取有效的匹配项索引。Section: {section[:100]}...")
            return None

    def _extract_line_contents(self, section: str) -> str:
        return "\n".join(self.RE_LINE_CONTENT.findall(section))

    def _should_skip_section(self, section: str) -> bool:
        # 检查是否跳过，可在对应的行末增加 x 字符，表示忽略当前项
        return self.RE_SKIP_CHECK.search(section) is not None

    def _do_replace(self, before_sections: List[str], after_sections: List[str]):
        file_dir = self.file_directory
        go_replace_before = os.path.join(file_dir, "go_replace_before.json")
        go_replace_after = os.path.join(file_dir, "go_replace_after.json")

        temp_files = [go_replace_before, go_replace_after]

        try:
            with open(go_replace_before, "w", encoding="utf-8") as f:
                json.dump(before_sections, f, ensure_ascii=False, indent=2)

            with open(go_replace_after, "w", encoding="utf-8") as f:
                json.dump(after_sections, f, ensure_ascii=False, indent=2)

            save_file_path = self.file_path
            if self.is_patch_search == PatchSearchAction.BAK_VS_BOOKS:
                # 将文本框的改动保存到 booksBak
                save_file_path = self._get_backup_file_path()

            # 执行替换命令
            cmd = [
                f'"{self.go_replace_cmd}"',
                f'"{save_file_path}"',
                f'"{go_replace_before}"',
                f'"{go_replace_after}"',
                "1",
            ]
            subprocess.run(" ".join(cmd), check=True, shell=True)

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"替换命令执行失败 (Exit Code {e.returncode}): {str(e)}") from e
        except TypeError as e:
            raise ValueError("JSON 序列化失败，数据可能包含非法字符") from e
        finally:
            # 清理临时文件
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except OSError:
                        pass
