from qtpy.QtCore import QObject, QEventLoop, Qt, Signal
from qtpy.QtWidgets import QMessageBox, QProgressDialog, QDialog

from core.constants import SaveAction, PatchSearchAction
from widgets.dialogs.backup_confirm_dialog import BackupConfirmDialog
from widgets.dialogs.post_save_dialog import PostSaveDialog

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main_window import MainWindow
    from widgets.text_editor_widget import TextEditorWidget
    from widgets.bottom_button_widget import BottomButtonWidget
    from services.file_service import FileService
    from services.save_service import SaveService
    from models.search_model import SearchModel


class SaveController(QObject):
    saveCompleted = Signal()
    patchSearchRequested = Signal()

    def __init__(
        self,
        main_window: "MainWindow",
        text_editor_widget: "TextEditorWidget",
        bottom_button_widget: "BottomButtonWidget",
        file_service: "FileService",
        save_service: "SaveService",
        search_model: "SearchModel",
    ):
        super().__init__()
        self.main_window = main_window
        self.text_editor_widget = text_editor_widget
        self.bottom_button_widget = bottom_button_widget
        self.file_service = file_service
        self.save_service = save_service
        self.search_model = search_model

        self.progress_dialog = None
        self._final_save_action = SaveAction.CANCELLED
        self._save_loop = None

        self._is_sync_diff = False

        self._setup_connections()

    def _setup_connections(self):
        self.save_service.askBackupNeeded.connect(self._on_ask_backup)
        self.save_service.progressStarted.connect(self._show_progress_dialog)
        self.save_service.progressUpdated.connect(self._update_progress_dialog)
        self.save_service.saveFinished.connect(self._on_save_finished)
        self.save_service.saveError.connect(self._on_save_error)
        self.save_service.saveCancelled.connect(self._on_save_cancelled)

        self.bottom_button_widget.ui.save_button.clicked.connect(self.request_direct_save)
        self.text_editor_widget.get_text_edit().textChanged.connect(self._set_save_button_hint)

    # =============== 公开 API ===============
    def request_direct_save(self):
        """
        供外部调用的 API：用户主动点击保存按钮或按 Ctrl+S 时调用
        不询问是否保存，直接进入保存流程
        """
        if not self.text_editor_widget.is_normal_search_result():
            return

        self._final_save_action = SaveAction.CANCELLED
        self._save_loop = QEventLoop(self)

        # 直接调用私有的执行方法
        self._execute_save(skip_backup=False)

        self._save_loop.exec_()

    def sync_diff_to_books_bak(self, old_text: str, new_text: str):
        """将一些 diff 同步到 booksBak，避免生成比对视图时重复显示"""
        self._is_sync_diff = True

        self.save_service.execute_save(
            file_path=self.file_service.get_current_file_path(),
            initial_search_result=old_text,
            raw_text=new_text,
            skip_backup=True,
            is_patch_search=PatchSearchAction.BAK_VS_BOOKS,
        )

    def check_and_prompt_save(self, skip_backup: bool = False) -> SaveAction:
        """
        检查是否需要保存，并根据用户选择执行操作
        返回 SaveAction 枚举，供调用方决定后续流程
        """
        # 1. 如果没有修改，直接返回 NO_CHANGES
        if not (self.text_editor_widget.is_content_modified() and self.text_editor_widget.is_normal_search_result()):
            return SaveAction.NO_CHANGES

        # 2. 弹出对话框
        reply = QMessageBox.question(
            self.main_window,
            "保存提示",
            "当前内容已修改，是否保存？",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )

        # 3. 处理用户选择
        if reply == QMessageBox.Yes:
            # 1. 预设最终结果为 CANCELLED (防止意外中断)
            self._final_save_action = SaveAction.CANCELLED

            # 2. 创建一个局部事件循环
            self._save_loop = QEventLoop(self)

            # 3. 启动异步保存任务（如果 skip_backup=True 则不弹备份框）
            self._execute_save(skip_backup)

            # 4. 开启事件循环，代码会在这里“挂起”，等待 _quit_save_loop() 被调用
            #    在此期间 GUI 依然响应，备份弹窗和进度条可以正常工作
            self._save_loop.exec_()

            # 5. 循环结束后，返回最终真实的保存结果
            return self._final_save_action

        elif reply == QMessageBox.No:
            return SaveAction.DISCARD_SAVE
        else:
            return SaveAction.CANCELLED

    def is_save_cancelled(self, skip_backup: bool = False) -> bool:
        """
        供外部方便调用的方法：
        如果用户取消了保存，或者保存过程中出错中止，返回 True
        外部接收到 True 时，应该跳过（return）后续的逻辑
        """
        action = self.check_and_prompt_save(skip_backup=skip_backup)
        return action == SaveAction.CANCELLED

    # =============== 内部业务流程 ===============
    def _set_save_button_hint(self):
        if self.text_editor_widget.is_normal_search_result():
            self.bottom_button_widget.set_save_button_hint(self.text_editor_widget.is_content_modified())

    def _execute_save(self, skip_backup: bool):
        # 保存前禁用主窗口，防止进行其他的误操作
        self.main_window.setEnabled(False)

        file_path = self.file_service.get_current_file_path()
        raw_text = self.text_editor_widget.get_raw_text()
        initial_search_result = self.search_model.get_initial_search_result()
        is_patch_search = self.search_model.is_patch_search()

        if is_patch_search != PatchSearchAction.NOT_PATCH_SEARCH:
            skip_backup = True  # 若是处于“比对视图”中，默认不覆盖备份

        self.save_service.execute_save(
            file_path=file_path,
            initial_search_result=initial_search_result,
            raw_text=raw_text,
            skip_backup=skip_backup,
            is_patch_search=is_patch_search,
        )

    # =============== 信号响应处理 (UI 弹窗) ===============
    def _on_ask_backup(self):
        dialog = BackupConfirmDialog(self.main_window)
        reply = dialog.exec_()

        if reply == QMessageBox.Cancel:
            self.save_service.set_backup_decision(is_cancelled=True, overwrite=False)
        else:
            overwrite = reply == QMessageBox.Yes
            self.save_service.set_backup_decision(is_cancelled=False, overwrite=overwrite)

        self.text_editor_widget.set_focus()

    def _show_progress_dialog(self):
        # 将创建进度条的逻辑单独抽离出来，不管是否跳过备份弹窗，都需要显示它
        self.progress_dialog = QProgressDialog("保存中，请稍候...", "取消", 0, 100, self.main_window)
        self.progress_dialog.setWindowTitle("保存进度")
        self.progress_dialog.setWindowModality(Qt.ApplicationModal)
        self.progress_dialog.show()

    def _update_progress_dialog(self, processed, total):
        if self.progress_dialog:
            self.progress_dialog.setValue(int(processed / total * 100))
            self.progress_dialog.setLabelText(f"保存中，已处理 {processed}/{total} 处匹配项")

    def _on_save_finished(self, message: str):
        self._final_save_action = SaveAction.DO_SAVE  # 只有真正完成才标记为 DO_SAVE
        self._finalize_save_operation()

        if self._is_sync_diff:
            self._is_sync_diff = False  # 重置标志位
            return  # sync diff 时不弹窗，不更新 initial_search_result，避免正常保存时结果失效

        # 保存动作已完整完成
        self.saveCompleted.emit()

        dialog = PostSaveDialog(self.main_window)
        if dialog.exec_() == QDialog.Accepted:
            # 用户点击了“比对检查”
            self.patchSearchRequested.emit()

        self.text_editor_widget.set_focus()

    def _on_save_error(self, message: str):
        self._final_save_action = SaveAction.CANCELLED  # 报错视为未完成保存
        self._finalize_save_operation()

        self.text_editor_widget.load_raw_text(message)
        QMessageBox.warning(self.main_window, "保存失败", message)
        self.text_editor_widget.set_focus()

    def _on_save_cancelled(self):
        self._final_save_action = SaveAction.CANCELLED
        self._finalize_save_operation()

    def _finalize_save_operation(self):
        if self.progress_dialog:
            self.progress_dialog.close()

        # 保存完成后恢复主窗口
        self.main_window.setEnabled(True)
        # 退出阻塞循环
        if self._save_loop and self._save_loop.isRunning():
            self._save_loop.quit()
