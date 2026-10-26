import json
import portalocker
import logging
from qtpy.QtCore import QObject

class HistoryService(QObject):
    def __init__(self, log_file_path: str):
        super().__init__()
        self.log_file_path = log_file_path

    def load_raw_data(self) -> dict:
        try:
            with open(self.log_file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (IOError, json.JSONDecodeError, FileNotFoundError) as e:
            logging.error(f"读取或解析历史文件失败: {e}")
            return {}

    def get_theme(self) -> str:
        return self.load_raw_data().get("theme") or "light"

    def save_raw_data(self, history_data: dict):
        try:
            with portalocker.Lock(self.log_file_path, "w", encoding="utf-8", timeout=5) as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)
        except (IOError, portalocker.LockException) as e:
            logging.error(f"保存历史文件失败: {e}")
