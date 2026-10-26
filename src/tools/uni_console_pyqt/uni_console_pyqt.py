import sys
import os
import configparser
import shutil
import ctypes
import subprocess

TARGET_API = os.environ.get("QT_API", "pyqt5").lower()

if TARGET_API == "pyqt5":
    import PyQt5

    dirname = os.path.dirname(PyQt5.__file__)
    plugin_path = os.path.join(dirname, "Qt5", "plugins")
elif TARGET_API == "pyside6":
    import PySide6

    dirname = os.path.dirname(PySide6.__file__)
    plugin_path = os.path.join(dirname, "Qt", "plugins")

os.environ["QT_PLUGIN_PATH"] = plugin_path

from qtpy.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QStackedWidget,
    QWidget,
    QMessageBox,
    QLabel,
    QFileDialog,
)
from qtpy.QtCore import Qt, QCoreApplication, QSettings, QProcess
from qtpy.QtGui import QGuiApplication, QIcon, QBrush, QColor

from command_tab import CommandTab


class MainWindow(QMainWindow):
    """直接显示命令界面的主窗口 (FixText 统一控制台)"""

    def __init__(self, current_dir):
        super().__init__()
        self.setWindowTitle("FixText 统一控制台")
        self.resize(1366, 768)

        self.tabs = []
        self.tabs_by_name = {}
        self.tab_mapping = {}

        # 运行时记忆
        self.settings = QSettings("FixText", "UniConsole")
        self.last_import_dir = self.settings.value("last_import_dir", "")
        self.last_export_dir = self.settings.value("last_export_dir", "")

        # 加载配置
        self.current_dir = current_dir
        self.config = load_app_config(current_dir)
        self.init_config()
        self.init_ui()

    def init_config(self):
        """根据配置文件动态构建命令字典"""
        cfg = self.config
        php_program = cfg["php_program"]
        main_php = cfg["main_php"]
        php_cmd_base = [php_program, main_php]  # PHP 命令基础列表

        # 工具函数：根据路径后缀生成外部命令列表（.bat -> cmd /c, .sh -> sh）
        def external_cmd(cmd_path):
            if not cmd_path:
                return ["echo", "未配置命令"]  # 防御

            lower_cmd_path = cmd_path.lower()
            if lower_cmd_path.endswith(".bat"):
                return ["cmd.exe", "/c", cmd_path]
            elif lower_cmd_path.endswith(".ps1"):
                return ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", cmd_path]
            else:
                return ["sh", cmd_path]

        self.config_dict = {
            "建议流程": {
                "a. 查找重复段落": {
                    "type": "interactive",
                    "cmd": php_cmd_base + ["find-dupl-text", "from-gui"],
                },
                "b. 文本排版": {
                    "type": "interactive",
                    "cmd": php_cmd_base + ["formatting", "from-gui"],
                },
                "c. 书籍校正": {
                    "type": "interactive",
                    "cmd": php_cmd_base + ["fix-text", "from-gui"],
                },
                "d. 检查引号问题": {
                    "type": "external_gui",
                    "cmd": external_cmd(cfg["quotation_checker_cmd"]),
                },
                "e. 文件全局搜索": {
                    "type": "external_gui",
                    "cmd": external_cmd(cfg["file_global_search_cmd"]),
                },
                "f. 手动检索": {
                    "type": "interactive",
                    "cmd": php_cmd_base + ["manual-search", "from-gui"],
                },
                "g. 书籍清理（全部删除，包括备份）": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["clear-books", "from-gui"],
                    "style_class": "alert",
                },
            },
            "EPUB 相关": {
                "合并 EPUB 文本，转为 TXT（含标签）": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["merge-epub-text", "from-gui"],
                    "msg": "这个命令是将 epub 的文本原样转为 txt，所有的 html 标签都完整保留。\n"
                    "如果需要将 epub 的文本内容提取为纯文本（txt，不含 html 标签），\n"
                    "请使用【文本排版】中的【提取 epub 中的文本】功能。",
                },
                "拆分 TXT 文本，还原为 EPUB": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["split-epub-text", "from-gui"],
                },
                "EPUB 解压": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["extract-epubs", "from-gui"],
                },
                "EPUB 压缩还原": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["make-epubs", "from-gui"],
                },
                "移除伪 DRM 加密": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["de-drm", "from-gui"],
                },
                "多 EPUB 合并": {
                    "type": "external_gui",
                    "cmd": external_cmd(cfg["epub_merger_cmd"]),
                    "style_class": "warning",
                },
            },
            "批注/笔记相关": {
                "从批注中生成校对表": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["generate-words", "from-gui"],
                    "pre_action": self._prompt_file_for_generate_words,
                },
                "通过批注校对表替换": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["fix-text", "temp-fix", "from-gui"],
                },
            },
            "替换报告": {
                "生成本轮校正的替换报告": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["generate-report", "from-gui"],
                },
                "将替换报告应用到 booksBak": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["temp-fix-books-bak", "from-gui"],
                },
                "生成【书籍专有词库】的词条": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["generate-book-maps", "from-gui"],
                    "style_class": "warning",
                },
            },
            "其他工具": {
                "使用临时校对表替换": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["fix-text", "temp-fix", "from-gui"],
                },
                "词库与 CSV 互转（导出导入）": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["csv-operation", "from-gui"],
                },
                "词条相关操作": {
                    "type": "external_gui",
                    "cmd": external_cmd(cfg["words_operations_cmd"]),
                },
                "比较时重命名文件": {
                    "type": "one-off",
                    "cmd": php_cmd_base + ["rename-files-for-compare", "from-gui"],
                },
                "调整章节顺序": {
                    "type": "external_gui",
                    "cmd": external_cmd(cfg["chapter_sorter_cmd"]),
                },
            },
        }

    def _prompt_file_for_generate_words(self):
        """为“从批注中生成校对表”选择文件并复制到 log_dir"""
        log_dir = self.config.get("log_dir", "")
        if not log_dir:
            QMessageBox.warning(self, "错误", "配置中未设置 log_dir 路径！")
            return False

        files, _ = QFileDialog.getOpenFileNames(
            self, "选择要导入的批注文件", "", "文本文件 (*.txt *.md *.docx *.json);;所有文件 (*)"
        )
        if not files:
            return False  # 用户取消

        os.makedirs(log_dir, exist_ok=True)
        for src in files:
            fname = os.path.basename(src)
            dest = os.path.join(log_dir, fname)
            if os.path.exists(dest):
                reply = QMessageBox.question(
                    self,
                    "批注文件已存在",
                    f"批注文件【{fname}】已存在，是否覆盖？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    continue
            try:
                shutil.copy2(src, dest)
            except Exception as e:
                QMessageBox.warning(self, "复制失败", f"批注文件【{fname}】复制失败：{str(e)}")
                return False  # 复制失败时终止流程
        return True

    def init_ui(self):
        # ========== 全局深色主题样式 ==========
        qss_path = os.path.join(self.current_dir, "style.qss")
        if os.path.exists(qss_path):
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        else:
            # 兜底：保留一个最小化的深色样式防止界面错乱
            self.setStyleSheet("QMainWindow { background-color: #2C2F40; color: #e1e1e1; }")

        # ========== 界面布局 ==========
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        self.setAcceptDrops(True)

        outer_layout = QVBoxLayout(central_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        h_layout = QHBoxLayout()

        # 1. 左侧树形菜单
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setMaximumWidth(350)
        self.tree_widget.setAlternatingRowColors(True)  # 开启交替行颜色（样式表中已定义颜色）

        # 2. 右侧堆叠面板
        self.stacked_widget = QStackedWidget()

        # 空白提示页
        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_label = QLabel(
            "1. 请点击【导入书籍】按钮，或直接将 TXT/EPUB 文件拖入本窗口，会自动复制到 books 文件夹。\n\n"
            "2. 请在左侧选择需要执行的具体任务，每次切换点击均会直接触发任务运行。\n\n"
            "3. 如果遇到长时间卡住没反应、打不开界面等问题，可以尝试点击命令面板右下角的【重启进程】。"
        )
        empty_label.setStyleSheet("color: #aaaaaa; font-size: 16px; font-family: 黑体;")
        empty_layout.addWidget(empty_label, 0, Qt.AlignCenter)
        self.stacked_widget.addWidget(empty_page)

        # 遍历配置，构建树节点与命令面板
        for group_name, tasks in self.config_dict.items():
            group_item = QTreeWidgetItem(self.tree_widget, [group_name])

            for task_name, task_info in tasks.items():
                if task_name in self.config.get("exclude", []):
                    continue  # 跳过被排除的任务

                task_item = QTreeWidgetItem(group_item, [task_name])

                style_class = task_info.get("style_class")
                if style_class == "alert":
                    # 设置为警告红
                    task_item.setForeground(0, QBrush(QColor("#f15d5d")))
                elif style_class == "warning":
                    # 设置为警告黄
                    task_item.setForeground(0, QBrush(QColor("#ffcc33")))
                elif style_class == "success":
                    # 绿色的安全项
                    task_item.setForeground(0, QBrush(QColor("#6a9955")))

                tab_widget = CommandTab(task_info, task_name, self)
                self.tabs.append(tab_widget)
                self.tabs_by_name[task_name] = tab_widget

                index = self.stacked_widget.addWidget(tab_widget)
                self.tab_mapping[id(task_item)] = index

        if self.tree_widget.topLevelItemCount() > 0:
            first_item = self.tree_widget.topLevelItem(0)
            self.tree_widget.expandItem(first_item)
        else:
            self.tree_widget.expandAll()  # 保底

        self.tree_widget.currentItemChanged.connect(self.on_tree_item_changed)
        self.tree_widget.itemPressed.connect(self.on_tree_item_pressed)
        self.tree_widget.itemClicked.connect(self.on_tree_item_clicked)

        # 左侧垂直布局：树形控件 + 底部按钮
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.tree_widget)

        # 第一行：展开/折叠
        row1_layout = QHBoxLayout()
        row1_layout.setContentsMargins(5, 4, 5, 0)
        self.expand_all_btn = QPushButton("展开所有")
        self.collapse_all_btn = QPushButton("折叠所有")
        self.expand_all_btn.clicked.connect(self.tree_widget.expandAll)
        self.collapse_all_btn.clicked.connect(self.collapse_except_first)
        row1_layout.addWidget(self.expand_all_btn)
        row1_layout.addWidget(self.collapse_all_btn)
        left_layout.addLayout(row1_layout)

        # 第二行：管理文件夹
        row2_layout = QHBoxLayout()
        row2_layout.setContentsMargins(5, 4, 5, 0)
        self.file_manager_btn = QPushButton("打开 books")
        self.file_manager_btn.clicked.connect(self.open_books_dir)
        self.bak_manager_btn = QPushButton("打开 booksBak")
        self.bak_manager_btn.clicked.connect(self.open_bak_dir)
        row2_layout.addWidget(self.file_manager_btn)
        row2_layout.addWidget(self.bak_manager_btn)
        left_layout.addLayout(row2_layout)

        # 第三行：导入/导出（不同颜色，带悬停）
        row3_layout = QHBoxLayout()
        row3_layout.setContentsMargins(5, 4, 5, 0)
        self.upload_btn = QPushButton("导入书籍")
        self.upload_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078D7;
                color: white;
                font-weight: bold;
                border: 1px solid #727593;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #3399ff;
            }
            QPushButton:pressed {
                background-color: #005fa3;
            }
        """)
        self.upload_btn.clicked.connect(self.upload_files)

        self.export_btn = QPushButton("导出结果")
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #0dbc79;
                color: white;
                font-weight: bold;
                border: 1px solid #727593;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #1edc99;
            }
            QPushButton:pressed {
                background-color: #09995e;
            }
        """)
        self.export_btn.clicked.connect(self.export_results)

        row3_layout.addWidget(self.upload_btn)
        row3_layout.addWidget(self.export_btn)
        left_layout.addLayout(row3_layout)

        # 将左侧整体加入水平布局
        h_layout.addLayout(left_layout)
        h_layout.addWidget(self.stacked_widget)

        # 3. 底部常驻提示
        hint_label = QLabel(
            "校对时可按照第一个【建议流程】分组从上到下依次执行，其他分组的功能可按需尝试。\n\n"
            "完成所有步骤，并导出结果文件后，建议执行【建议流程 → 书籍清理】清除残留的书籍文件。"
        )
        hint_label.setAlignment(Qt.AlignCenter)
        hint_label.setStyleSheet(
            "color: #aaaaaa; font-size: 16px; font-family: 黑体; "
            "padding: 6px; background-color: #2C2F3B; border-top: 1px solid #727593;"
        )

        outer_layout.addLayout(h_layout)
        outer_layout.addWidget(hint_label)

    def on_tree_item_changed(self, current, previous):
        if not current:
            return

        item_id = id(current)
        if item_id in self.tab_mapping:
            index = self.tab_mapping[item_id]
            self.stacked_widget.setCurrentIndex(index)
            # 触发面板特定类型的启动逻辑
            tab_widget = self.stacked_widget.widget(index)
            tab_widget.on_selected()
        else:
            # 点击的是分组标题，切回空白提示页
            self.stacked_widget.setCurrentIndex(0)

    def on_tree_item_pressed(self, item, column):
        """鼠标按下时触发，记录此时被按下的 item 是否已经是当前选中项"""
        # 如果按下时它本身就是 currentItem，说明是重复点击
        self._was_current_when_pressed = item == self.tree_widget.currentItem()

    def on_tree_item_clicked(self, item, column):
        """鼠标点击完成时触发"""
        # 只有在按下时已经是当前项（即真正的重复点击同一 tab）才触发该逻辑
        if getattr(self, "_was_current_when_pressed", False):
            item_id = id(item)
            if item_id in self.tab_mapping:
                index = self.tab_mapping[item_id]
                tab_widget = self.stacked_widget.widget(index)

                # 调用 CommandTab 中的校验和重启方法
                if hasattr(tab_widget, "check_reclick_run"):
                    tab_widget.check_reclick_run()

    def collapse_except_first(self):
        """折叠所有树节点，但保持第一个分组展开"""
        # 先全部折叠
        self.tree_widget.collapseAll()

        # 检查是否存在根节点，如果存在则把第一个根节点展开
        if self.tree_widget.topLevelItemCount() > 0:
            first_item = self.tree_widget.topLevelItem(0)
            self.tree_widget.expandItem(first_item)

    def upload_files(self):
        file_dir = self.config.get("file_dir")
        if not file_dir:
            QMessageBox.warning(self, "错误", "配置文件中未设置 file_dir 路径！")
            return

        files, _ = QFileDialog.getOpenFileNames(
            self, "选择书籍文件", self.last_import_dir or "", "书籍文件 (*.txt *.epub)"  # 使用上次记忆的目录
        )

        if files:
            # 更新记忆目录（取第一个文件所在目录）
            self.last_import_dir = os.path.dirname(files[0])
            self.settings.setValue("last_import_dir", self.last_import_dir)

            self.process_upload_files(files, file_dir)

    def export_results(self):
        """导出前检查是否为 EPUB 合并文件，若是则必须先拆分再导出"""
        file_dir = self.config.get("file_dir")
        if not file_dir or not os.path.isdir(file_dir):
            QMessageBox.warning(self, "错误", "books 文件夹未设置或不存在！")
            return

        # 检查是否存在以“【EPUB 合并文件】”开头的 txt 文件
        need_split = False
        try:
            for f in os.listdir(file_dir):
                if f.lower().endswith(".txt") and f.startswith("【EPUB 合并文件】"):
                    need_split = True
                    break
        except Exception:
            pass

        if need_split:
            reply = QMessageBox.question(
                self,
                "检测到 EPUB 合并文件",
                "当前工作目录中存在 EPUB 合并文件，导出前需要先执行\n"
                "【EPUB 相关操作 → 拆分 TXT 文本，还原为 EPUB】\n\n"
                "是否立即拆分并导出？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if reply != QMessageBox.Yes:
                return

            # 获取拆分任务标签
            split_tab = self.tabs_by_name.get("拆分 TXT 文本，还原为 EPUB")
            if not split_tab:
                QMessageBox.warning(self, "错误", "未找到拆分任务配置！")
                return

            # 连接完成信号（先断开旧连接，避免重复绑定）
            try:
                split_tab.process.finished.disconnect()
            except TypeError:
                pass

            def on_split_finished(exit_code, exit_status):
                if exit_code == 0 and exit_status == QProcess.NormalExit:
                    QMessageBox.information(self, "提示", "EPUB 拆分完成，即将开始导出。")
                    self._do_export(file_dir)
                else:
                    QMessageBox.warning(self, "拆分失败", "EPUB 拆分未成功，请检查问题后重试。")

            split_tab.process.finished.connect(on_split_finished)

            # 执行拆分任务
            split_tab.execute_one_off()
            return

        # 不需要拆分，直接进入导出选择
        self._do_export(file_dir)

    def _do_export(self, file_dir):
        """执行文件导出选择与复制操作（由 export_results 或拆分完成后调用）"""
        extensions = (".txt", ".epub")
        files = [f for f in os.listdir(file_dir) if f.lower().endswith(extensions)]
        if not files:
            QMessageBox.information(self, "提示", "books 文件夹中没有可导出的文件。")
            return

        # 选择文件
        file_dialog = QFileDialog(
            self, "第一步：选择要导出的文件", file_dir, "书籍文件 (*.txt *.epub);;文本文件 (*.txt);;EPUB文件 (*.epub)"
        )
        file_dialog.setFileMode(QFileDialog.ExistingFiles)
        file_dialog.setViewMode(QFileDialog.List)
        if file_dialog.exec_() != QFileDialog.Accepted:
            return
        selected_files = file_dialog.selectedFiles()
        if not selected_files:
            return

        # 选择目标目录
        dest_dir = QFileDialog.getExistingDirectory(
            self, "第二步：选择导出目标目录", self.last_export_dir or "", QFileDialog.ShowDirsOnly
        )
        if not dest_dir:
            return

        # 记忆导出目录
        self.last_export_dir = dest_dir
        self.settings.setValue("last_export_dir", dest_dir)

        # 复制文件
        success_count = 0
        for src_path in selected_files:
            file_name = os.path.basename(src_path)
            dest_path = os.path.join(dest_dir, file_name)

            if os.path.exists(dest_path):
                reply = QMessageBox.question(
                    self,
                    "文件已存在",
                    f"文件【{file_name}】在目标目录中已存在，是否覆盖？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    continue

            try:
                shutil.copy2(src_path, dest_path)
                success_count += 1
            except Exception as e:
                QMessageBox.warning(self, "导出失败", f"文件【{file_name}】复制失败：\n{str(e)}")

        if success_count > 0:
            QMessageBox.information(self, "导出完成", f"成功导出 {success_count} 个文件到：\n{dest_dir}")

    def open_books_dir(self):
        """打开 books 文件夹"""
        file_dir = self.config.get("file_dir")
        if not file_dir:
            QMessageBox.warning(self, "错误", "配置文件中未设置 file_dir 路径！")
            return
        self._open_folder(file_dir)

    def open_bak_dir(self):
        """打开 booksBak 文件夹"""
        bak_dir = self.config.get("bak_dir")
        if not bak_dir:
            QMessageBox.warning(self, "错误", "配置文件中未设置 bak_dir 路径！")
            return
        self._open_folder(bak_dir)

    def _open_folder(self, folder_path):
        os.makedirs(folder_path, exist_ok=True)

        if sys.platform == "win32":
            os.startfile(folder_path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder_path])
        else:
            subprocess.Popen(["xdg-open", folder_path])

    def dragEnterEvent(self, event):
        """拖拽进入窗口时触发，仅接受包含 txt 或 epub 的本地文件"""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile() and url.toLocalFile().lower().endswith((".txt", ".epub")):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        """松开拖拽时触发"""
        file_dir = self.config.get("file_dir")
        if not file_dir:
            QMessageBox.warning(self, "错误", "配置文件中未设置 file_dir 路径！")
            return

        files = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                file_path = url.toLocalFile()
                if file_path.lower().endswith((".txt", ".epub")):
                    files.append(file_path)

        if files:
            self.process_upload_files(files, file_dir)

    def process_upload_files(self, files, dest_dir):
        """执行复制逻辑及覆盖询问"""
        os.makedirs(dest_dir, exist_ok=True)  # 确保目录存在
        success_count = 0
        has_epub = False

        for file_path in files:
            file_name = os.path.basename(file_path)
            dest_path = os.path.join(dest_dir, file_name)

            # 查重并询问是否覆盖
            if os.path.exists(dest_path):
                reply = QMessageBox.question(
                    self,
                    "文件已存在",
                    f"文件【{file_name}】已存在，是否覆盖？",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    continue

            try:
                shutil.copy2(file_path, dest_path)
                success_count += 1
                if file_name.lower().endswith(".epub"):  # 新增判断
                    has_epub = True
            except Exception as e:
                QMessageBox.warning(self, "导入失败", f"文件【{file_name}】复制失败：\n{str(e)}")

        if success_count > 0:
            QMessageBox.information(self, "导入完成", f"成功将 {success_count} 个文件复制到 books 文件夹")

        # 如果有 epub 文件成功导入，自动执行“合并 EPUB 文本”任务
        if has_epub:
            merge_tab = self.tabs_by_name.get("合并 EPUB 文本，转为 TXT（含标签）")
            if merge_tab:
                merge_tab.execute_one_off()

    def closeEvent(self, event):
        """主窗口关闭时，遍历销毁所有后台驻留的进程"""
        for tab in self.tabs:
            tab.terminate_process()
        event.accept()


# ==================== 应用初始化 ====================
def setup_environment():
    """设置应用环境"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(current_dir)

    # Windows 任务栏图标设置
    if sys.platform == "win32":
        myappid = "fix_text.uni_console"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    return current_dir


def load_app_config(current_dir):
    """加载应用配置，从 env/config.ini 的 [uni_console] 节读取命令路径"""
    config = configparser.ConfigParser()
    config.read(os.path.join(current_dir, "../env/config.ini"), encoding="utf-8")

    def get_abs_path(key, fallback=""):
        """从 uni_console 节读取指定键，若为相对路径则转为绝对路径（基于 current_dir）"""
        value = config.get("uni_console", key, fallback=fallback)
        if value and not os.path.isabs(value):
            value = os.path.abspath(os.path.join(current_dir, value))
        return value

    # 读取所有路径配置（自动处理绝对/相对）
    file_dir = get_abs_path("file_dir")
    bak_dir = get_abs_path("bak_dir")
    log_dir = get_abs_path("log_dir")
    php_program = get_abs_path("php_program")
    main_php = get_abs_path("main_php")
    quotation_cmd = get_abs_path("quotation_checker_cmd")
    chapter_sorter_cmd = get_abs_path("chapter_sorter_cmd")
    epub_merger_cmd = get_abs_path("epub_merger_cmd")
    words_operations_cmd = get_abs_path("words_operations_cmd")
    file_global_search_cmd = get_abs_path("file_global_search_cmd")

    # 排除列表（逗号分隔的任务名）
    exclude_str = config.get("uni_console", "exclude", fallback="")
    exclude_list = [name.strip() for name in exclude_str.split(",") if name.strip()]

    return {
        "file_dir": file_dir,
        "bak_dir": bak_dir,
        "log_dir": log_dir,
        "php_program": php_program,
        "main_php": main_php,
        "quotation_checker_cmd": quotation_cmd,
        "chapter_sorter_cmd": chapter_sorter_cmd,
        "epub_merger_cmd": epub_merger_cmd,
        "words_operations_cmd": words_operations_cmd,
        "file_global_search_cmd": file_global_search_cmd,
        "exclude": exclude_list,
    }


if __name__ == "__main__":
    if TARGET_API == "pyside6":
        if hasattr(QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
            QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)
    else:
        if hasattr(Qt, "AA_EnableHighDpiScaling"):
            QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        if hasattr(Qt, "AA_UseHighDpiPixmaps"):
            QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
        if hasattr(QCoreApplication, "setHighDpiScaleFactorRoundingPolicy"):
            QCoreApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 设置环境
    current_dir = setup_environment()

    window = MainWindow(current_dir)
    window.setWindowIcon(QIcon("icon.png"))
    window.show()
    sys.exit(app.exec_())
