from qtpy.QtCore import QObject, Signal, QThreadPool
from tasks.save_task import SaveTask

from typing import List

class SaveService(QObject):
    # 对外暴露的业务信号，供 Controller 监听
    askBackupNeeded = Signal()
    progressStarted = Signal()
    progressUpdated = Signal(int, int)
    saveFinished = Signal(str)
    saveError = Signal(str)
    saveCancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thread_pool = QThreadPool.globalInstance()
        self.save_task = None

    def execute_save(self, file_path: str, initial_search_result: List, raw_text: str, skip_backup: bool, is_patch_search: bool):
        self.save_task = SaveTask(file_path, initial_search_result, raw_text)

        self.save_task.skip_backup_prompt = skip_backup
        self.save_task.is_patch_search = is_patch_search

        # 将 Task 的信号桥接到 Service 的信号
        self.save_task.signals.askBackup.connect(self.askBackupNeeded.emit)
        self.save_task.signals.showProgress.connect(self.progressStarted.emit)
        self.save_task.signals.progressUpdated.connect(self.progressUpdated.emit)
        self.save_task.signals.saveFinished.connect(self.saveFinished.emit)
        self.save_task.signals.saveError.connect(self.saveError.emit)
        self.save_task.signals.saveCancelled.connect(self.saveCancelled.emit)

        self.thread_pool.start(self.save_task)

    def set_backup_decision(self, is_cancelled: bool, overwrite: bool):
        """由 Controller 调用，通知后台线程用户的弹窗选择"""
        if not self.save_task: return

        if is_cancelled:
            self.save_task.is_cancelled = True
        else:
            self.save_task.backup_confirmed = overwrite

        # 解除后台线程的阻塞
        self.save_task.backup_event.set()
