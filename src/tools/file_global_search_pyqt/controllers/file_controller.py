import os
from qtpy.QtCore import QObject
from qtpy.QtWidgets import QMessageBox

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from widgets.file_widget import FileWidget
    from widgets.text_editor_widget import TextEditorWidget
    from services.file_service import FileService
    from models.file_model import FileModel


class FileController(QObject):
    def __init__(
        self,
        file_widget: "FileWidget",
        text_editor_widget: "TextEditorWidget",
        file_service: "FileService",
        file_model: "FileModel",
        file_dir: str,
        epub_merger_script: str
    ):
        super().__init__()

        self.file_widget = file_widget
        self.text_editor_widget = text_editor_widget
        self.file_service = file_service
        self.file_model = file_model

        self.file_dir = file_dir
        self.epub_merger_script = epub_merger_script

        self._setup_connections()

        # 初始加载列表
        self.file_service.load_file_list(self.file_dir)

    def _setup_connections(self):
        # View -> Controller/Service (用户操作)
        self.file_widget.fileSelected.connect(self._on_file_selected)
        self.file_widget.fileDropped.connect(self._on_file_dropped)
        self.file_widget.refreshRequested.connect(lambda: self.file_service.load_file_list(self.file_dir))

        # Service -> View (业务提示弹窗)
        self.file_service.notifyInfo.connect(lambda t, m: QMessageBox.information(self.file_widget, t, m))
        self.file_service.notifyError.connect(lambda t, m: QMessageBox.critical(self.file_widget, t, m))

        # Model -> View (状态改变 -> 更新 UI)
        self.file_model.fileListChanged.connect(self.file_widget.set_file_list)
        self.file_model.charCountChanged.connect(self.file_widget.set_char_count_label)
        self.file_model.fileLoaded.connect(self._on_file_loaded)

    def _on_file_selected(self, filename: str):
        # 委托给 Service 去读取和处理
        self.file_service.select_file(self.file_dir, filename)
        self.file_widget.is_html_file = self.file_model.is_html_file()

    def _on_file_loaded(self):
        self.text_editor_widget.handle_major_content_change()

    def _on_file_dropped(self, source_path: str):
        if not os.path.isfile(source_path):
            return

        dest_dir = self.file_dir
        if not dest_dir or not os.path.isdir(dest_dir):
            QMessageBox.warning(self.file_widget, "错误", "未设置有效的文件目录，无法移动文件")
            return

        file_name = os.path.basename(source_path)

        if file_name.lower().endswith(".epub"):
            self._handle_epub_drop(source_path, dest_dir, file_name)
        elif file_name.lower().endswith(".txt"):
            self._handle_txt_drop(source_path, dest_dir, file_name)
        else:
            QMessageBox.warning(self.file_widget, "错误", "只支持 EPUB 和 TXT 文件的拖放操作")

    def _handle_txt_drop(self, source_path: str, dest_dir: str, file_name: str):
        dest_path = os.path.join(dest_dir, file_name)

        if os.path.abspath(source_path) == os.path.abspath(dest_path):
            QMessageBox.information(self.file_widget, "同一文件", "这是同一个文件，通过下拉列表选取即可")
            return

        # 判断并询问用户
        if os.path.exists(dest_path):
            reply = QMessageBox.question(
                self.file_widget,
                "文件已存在",
                f"文件 '{file_name}' 已存在于目标目录中。要覆盖它吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                self.file_widget.set_current_file(file_name)  # 不覆盖，直接选中
                return

        try:
            self.file_service.copy_file(source_path, dest_path)
        except Exception as e:
            QMessageBox.critical(self.file_widget, "移动文件失败", f"出错：\n{e}")
            return

        self.file_service.load_file_list(dest_dir)
        self.file_widget.set_current_file(file_name)

    def _handle_epub_drop(self, source_path: str, dest_dir: str, file_name: str):
        file_name_without_ext = os.path.splitext(file_name)[0]
        merged_txt_filename = f"【EPUB 合并文件】{file_name_without_ext}.txt"
        merged_txt_filepath = os.path.join(dest_dir, merged_txt_filename)
        epub_merger_script = self.epub_merger_script

        if not epub_merger_script or not os.path.exists(epub_merger_script):
            QMessageBox.critical(self.file_widget, "错误", "未找到 EPUB 合并脚本，请检查配置")
            return

        if os.path.exists(merged_txt_filepath):
            reply = QMessageBox.question(
                self.file_widget,
                "文件已存在",
                f"合并后的文件 '{merged_txt_filename}' 已存在。要覆盖它吗？\n\n（这将会删除旧文件并重新合并）",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                self.file_widget.set_current_file(merged_txt_filename)
                return

            try:
                self.file_service.delete_epub_text_file(merged_txt_filepath, epub_merger_script)
            except Exception as e:
                QMessageBox.critical(self.file_widget, "删除失败", f"删除出错：\n{e}")
                return

        try:
            epub_dest_path = os.path.join(dest_dir, file_name)
            if os.path.abspath(source_path) != os.path.abspath(epub_dest_path):
                self.file_service.copy_file(source_path, epub_dest_path)

            self.file_service.merge_epub_text_file(epub_merger_script, merged_txt_filepath)
        except Exception as e:
            QMessageBox.critical(self.file_widget, "处理失败", f"处理 EPUB 文件时出错：\n{e}")
            return

        self.file_service.load_file_list(dest_dir)
        self.file_widget.set_current_file(merged_txt_filename)
