import os
import shutil
import chardet
from typing import Optional
from qtpy.QtCore import QObject, Signal, QThreadPool

import utils.util as util
from config import MAX_FILE_SIZE_FOR_COUNT
from tasks.file_count_chars_task import FileCountCharsTask
from models.file_model import FileModel


class FileService(QObject):
    """
    文件服务层：只处理磁盘 I/O、编码检测、合并脚本执行及后台任务
    成功后更新 FileModel，发生需要提示的情况发出信号
    """

    notifyInfo = Signal(str, str)  # title, message (一般提示)
    notifyError = Signal(str, str)  # title, message (错误提示)

    def __init__(self, file_model: FileModel, file_dir: str, parent=None):
        super().__init__(parent)

        self.file_model = file_model
        self.file_dir = file_dir

        self.thread_pool = QThreadPool.globalInstance()
        self.counter_task: Optional[FileCountCharsTask] = None

    def get_current_file_path(self) -> str:
        """获取当前正在编辑的文件的完整绝对路径"""
        filename = self.file_model.get_current_filename()
        if not filename:
            return ""

        return os.path.join(self.file_dir, filename)

    def get_backup_file_path(self) -> str:
        """获取备份路径，并确保备份目录存在"""
        filename = self.file_model.get_current_filename()
        if not filename:
            return ""

        # 在 file_dir 的同级目录下 booksBak 的同一文件名
        backup_dir = os.path.join(os.path.dirname(self.file_dir), "booksBak")
        os.makedirs(backup_dir, exist_ok=True)

        return os.path.join(backup_dir, filename)

    def load_file_list(self, file_dir: str):
        if file_dir and os.path.exists(file_dir):
            txt_files = [f for f in os.listdir(file_dir) if f.endswith(".txt")]
            self.file_model.set_file_list(txt_files)
        else:
            self.file_model.set_file_list([])

    def select_file(self, file_dir: str, filename: str):
        if not filename:
            self.file_model.set_char_count("（字数：无文件）")
            return

        file_path = os.path.join(file_dir, filename)
        try:
            # 优先尝试用 UTF-8 读取
            self._read_and_process_file(file_path)
            self.file_model.set_file(filename)
            self._update_char_count(file_path)

        except UnicodeDecodeError:
            # 当且仅当 UTF-8 解码失败时，触发自动转换流程
            self._convert_to_utf8_and_retry(file_path, filename)
        except Exception as e:
            self.notifyError.emit("读取错误", f"读取文件时发生未知错误：\n{e}")
            self.file_model.set_char_count("（字数：读取失败）")

    def _read_and_process_file(self, file_path: str) -> str:
        with open(file_path, "rb") as f:
            content_bytes = f.read()

        # 统一换行符
        if b"\r" in content_bytes:
            text = content_bytes.decode("utf-8")
            normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
            if normalized_text != text:
                with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(normalized_text)
                return normalized_text
            return text
        else:
            return content_bytes.decode("utf-8")

    def _convert_to_utf8_and_retry(self, file_path: str, filename: str):
        self.notifyInfo.emit(
            "编码转换", f"文件 '{filename}' 可能不是 UTF-8 编码。\n\n接下来自动将编码转为 UTF-8。\n开始检测编码……"
        )

        try:
            with open(file_path, "rb") as f:
                raw_data = f.read()

            encoding_to_use = None
            text_content = None

            if raw_data.startswith(b"\xef\xbb\xbf"):
                encoding_to_use = "utf-8-sig"
            elif raw_data.startswith(b"\xff\xfe"):
                encoding_to_use = "utf-16-le"
            elif raw_data.startswith(b"\xfe\xff"):
                encoding_to_use = "utf-16-be"

            if encoding_to_use:
                self.notifyInfo.emit("转换提示", f"检测到 BOM，编码为: {encoding_to_use}，开始转换……")
                text_content = raw_data.decode(encoding_to_use, errors="replace")
            else:
                normalized_data = raw_data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                lines = normalized_data.split(b"\n")
                sample = b"\n".join(lines[:100]) if len(lines) > 100 else raw_data

                detection = chardet.detect(sample)
                original_encoding = detection.get("encoding")
                confidence = detection.get("confidence")

                if original_encoding is None or confidence < 0.7:
                    raise ValueError("无法可靠地检测到文件编码")
                if "utf-8" in original_encoding.lower():
                    raise ValueError("文件已是 UTF-8，但读取出错，可能已损坏")

                encoding_to_use = original_encoding
                if original_encoding.lower() in ["gb2312", "gbk", "gb18030"]:
                    encoding_to_use = "gb18030"

                self.notifyInfo.emit(
                    "转换提示", f"检测到编码: {original_encoding} (置信度: {confidence:.0%})，开始转换……"
                )
                text_content = raw_data.decode(encoding_to_use, errors="replace")

            with open(file_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text_content)

            self.notifyInfo.emit("转换提示", "文件已成功转换为 UTF-8，重新加载……")

            # 重新加载
            self._read_and_process_file(file_path)
            self.file_model.set_file(filename)
            self._update_char_count(file_path)

        except Exception as e:
            error_msg = f"自动转换文件 '{filename}' 失败。\n\n错误详情: {e}\n\n建议手动使用工具进行转换"
            self.notifyError.emit("转码失败", error_msg)
            self.file_model.set_char_count("（字数：转码失败）")

    def _update_char_count(self, file_path: str):
        try:
            file_size = os.path.getsize(file_path)
            if file_size > MAX_FILE_SIZE_FOR_COUNT:
                self.file_model.set_char_count(f"（大小：{util.bytes_to_readable_size(file_size)}）")
                return
        except OSError:
            self.file_model.set_char_count("（字数：读取失败）")
            return

        if self.counter_task:
            self.counter_task.cancel()

        self.file_model.set_char_count("（字数：计算中...）")
        self.counter_task = FileCountCharsTask(file_path)
        self.counter_task.signals.finished.connect(lambda count: self.file_model.set_char_count(f"（字数：{count}）"))
        self.thread_pool.start(self.counter_task)

    # --- 拖拽处理辅助方法 (供 Controller 调用) ---
    def copy_file(self, source_path: str, dest_path: str):
        shutil.copy2(source_path, dest_path)

    def delete_epub_text_file(self, file_path: str, script_path: str):
        util.run_php_script(script_path, "merge-epub-text", file_path, "delete")

    def merge_epub_text_file(self, script_path: str, merged_filepath: str):
        util.run_php_script(script_path, "merge-epub-text", merged_filepath)
