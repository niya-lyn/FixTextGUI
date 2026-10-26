from qtpy.QtWidgets import (
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QTextEdit,
    QLineEdit,
    QMessageBox,
)
from qtpy.QtCore import QProcess
from qtpy.QtGui import QTextCursor, QFont

from output_formatter import OutputFormatter


class CommandTab(QWidget):
    """单独的命令面板，包含输出框、输入框和重启按钮"""

    def __init__(self, task_info, task_name, parent=None):
        super().__init__(parent)
        self.task_info = task_info
        self.task_name = task_name
        # 提取任务类型：interactive, one-off, message, external_gui
        self.task_type = task_info.get("type", "interactive")
        self.task_msg = task_info.get("msg", "")
        self.cmd_list = task_info.get("cmd", [])

        self.process = QProcess(self)
        self.has_started = False
        self.is_restarting = False
        self.output_formatter = OutputFormatter()

        self.init_ui()
        if self.task_type != "message":
            self.init_process()
        else:
            # 如果仅仅是显示信息，直接把信息渲染到屏幕上
            msg = task_info.get("text", "无信息")
            self.append_sys_msg("prompt", msg, br_before=True, custom_style="font-size: 14pt;")

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 实时输出显示框
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)

        # 统一设置字体和字号
        font = QFont("黑体", 11)
        font.setStyleHint(QFont.Monospace)
        self.output_text.setFont(font)

        self.output_text.setStyleSheet("background-color: #202331; color: #d4d4d4; white-space: pre-wrap;")
        self.output_text.document().setMaximumBlockCount(2000)

        layout.addWidget(self.output_text)

        # 如果是“仅显示信息”，不需要底部的操作栏
        if self.task_type == "message":
            return

        # === 底部布局 (水平) ===
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        self.input_line = QLineEdit()
        self.input_line.setPlaceholderText("在此输入交互指令并按回车或右侧按键发送……")
        self.input_line.returnPressed.connect(self.send_input)

        self.send_btn = QPushButton("发送内容")
        self.send_btn.clicked.connect(self.send_input)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078D7;
                color: white;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #3399ff;
            }
        """)
        bottom_layout.addWidget(self.input_line)
        bottom_layout.addWidget(self.send_btn)

        self.restart_btn = QPushButton("重启进程")
        self.restart_btn.clicked.connect(self.restart_process)
        self.restart_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffcc33;
                color: black;
                padding: 5px 10px;
            }
            QPushButton:hover {
                background-color: #FFE69C;
            }
        """)
        bottom_layout.addWidget(self.restart_btn)

        layout.addLayout(bottom_layout)

    def init_process(self):
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.errorOccurred.connect(self.handle_error)
        self.process.finished.connect(self.handle_finished)

    # ==========================
    # 统一样式与消息输出封装
    # ==========================
    def append_output(self, html_text):
        """最底层的插入 HTML 方法"""
        self.output_text.insertHtml(html_text)
        self.output_text.moveCursor(QTextCursor.End)

    def append_sys_msg(self, msg_type, text, br_before=False, custom_style=""):
        """统一的系统消息发送方法"""
        type_config = {
            "info": {"color": "#569cd6", "prefix": "[系统] "},
            "success": {"color": "#6a9955", "prefix": "[系统] "},
            "error": {"color": "red", "prefix": "[系统] "},
            "sys_error": {"color": "#f44747", "prefix": "[系统异常] "},
            "external": {"color": "#c586c0", "prefix": "[系统] "},
            "external_bg": {"color": "#808080", "prefix": "[系统] "},
            "exit": {"color": "#ce9178", "prefix": "[系统] "},
            "prompt": {"color": "#4ec9b0", "prefix": "[提示] "},
            "input": {"color": "#4ec9b0", "prefix": "> "},
        }

        cfg = type_config.get(msg_type, {"color": "#d4d4d4", "prefix": ""})
        color = cfg["color"]
        prefix = cfg["prefix"]

        style = f"color:{color}; {custom_style}"
        html = f'<span style="{style}">{prefix}{text}</span><br>\n'

        if br_before:
            html = f"<br>{html}"

        self.append_output(html)

    # ==========================
    # 核心交互逻辑
    # ==========================
    def on_selected(self):
        """当该面板被从左侧树选中时触发的逻辑"""
        if self.task_type == "message":
            return

        elif self.task_type == "one-off":
            prompt_str = f"即将执行命令：\n【{self.task_name}】\n\n是否继续？"
            if self.task_msg:
                prompt_str = f"即将执行命令：\n【{self.task_name}】\n\n【提示】\n{self.task_msg}\n\n是否继续？"

            # 先清屏，再询问是否执行
            self.output_text.clear()
            reply = QMessageBox.question(
                self,
                "确认执行",
                prompt_str,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                # 若有预处理动作（如选择文件），先执行
                pre_action = self.task_info.get("pre_action")
                if pre_action:
                    if not pre_action():   # 返回 False 表示用户取消或出错
                        return

                self.restart_process()

        elif self.task_type == "interactive":
            # 交互脚本：只有在没启动过的情况下才自动启动
            if not self.has_started:
                self.start_process()

        elif self.task_type == "external_gui":
            # 外部 GUI 脚本：如果进程已死，就重启它；如果还在，只提示用户
            if self.process.state() == QProcess.NotRunning:
                self.start_process()
            else:
                self.append_sys_msg(
                    "external_bg", "此任务界面仍在后台运行中，请自行切换到对应窗口。如果卡死，可点击下方按钮重启。"
                )

    def check_reclick_run(self):
        """重复点击同一 Tab 时的检测与弹窗逻辑 (由 MainWindow 触发)"""
        if self.task_type == "message":
            return

        text = self.output_text.toPlainText().strip()
        lines = [line for line in text.split("\n") if line.strip()]
        if not lines:
            return

        last_line = lines[-1]

        # 场景一：正常完毕
        if "任务已正常执行完毕" in last_line or "continue" in last_line or "任意键" in last_line:
            reply = QMessageBox.question(
                self,
                "确认重新执行",
                f"任务【{self.task_name}】已执行完毕。\n\n是否确认重新运行该任务？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.restart_process()

        # 场景二：异常退出
        elif "上次任务异常退出" in last_line:
            reply = QMessageBox.question(
                self,
                "确认重新执行",
                f"任务【{self.task_name}】上次异常退出。\n\n是否确认重启？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self.restart_process()

        # 场景三：外部 GUI 运行中
        elif "外部 GUI 进程仍在后台运行中" in last_line:
            QMessageBox.information(
                self,
                "外部进程运行中",
                "此任务界面仍在后台运行中，请自行切换到对应的应用窗口。\n\n（如果应用卡死，可点击面板底部的“重启进程”按钮强制重启）",
            )

    def start_process(self):
        """启动进程"""
        if self.process.state() == QProcess.NotRunning:
            self.output_text.clear()
            cmd_str = " ".join(self.cmd_list)

            if self.task_type == "external_gui":
                self.append_sys_msg("external", f"正在唤起外部 GUI 应用……<br>命令: {cmd_str}<br>")
            else:
                self.append_sys_msg("info", f"正在启动任务【{self.task_name}】……<br>命令: {cmd_str}<br>")

            self.process.setProgram(self.cmd_list[0])
            self.process.setArguments(self.cmd_list[1:])
            self.process.start()
            self.has_started = True

    def restart_process(self):
        self.is_restarting = True
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished()
        self.is_restarting = False
        self.start_process()

    def send_input(self):
        if not hasattr(self, "input_line"):
            return

        text = self.input_line.text()
        if self.process.state() == QProcess.Running:
            self.append_sys_msg("input", text)
            command = f"{text}\n".encode("utf-8")
            self.process.write(command)
            self.input_line.clear()
        else:
            QMessageBox.information(self, "提示", "进程尚未运行，无法发送输入。")

    def read_stdout(self):
        while self.process.canReadLine():
            data = self.process.readLine().data()
            text = data.decode("utf-8", errors="replace")
            self.append_output(self.output_formatter.format_html(text))

        if self.process.bytesAvailable() > 0:
            data = self.process.readAllStandardOutput().data()
            text = data.decode("utf-8", errors="replace")
            self.append_output(self.output_formatter.format_html(text))

    def read_stderr(self):
        while self.process.canReadLine():
            data = self.process.readLine().data()
            text = data.decode("utf-8", errors="replace")
            html_text = self.output_formatter.format_html(text)
            self.append_output(f'<span style="color:#f44747;">{html_text}</span>')

        if self.process.bytesAvailable() > 0:
            data = self.process.readAllStandardError().data()
            text = data.decode("utf-8", errors="replace")
            html_text = self.output_formatter.format_html(text)
            self.append_output(f'<span style="color:#f44747;">{html_text}</span>')

    def handle_error(self, error):
        if self.is_restarting:
            return
        error_msg = "未知错误"
        if error == QProcess.FailedToStart:
            error_msg = "进程启动失败 (找不到命令或文件)"
        elif error == QProcess.Crashed:
            error_msg = "进程意外崩溃"

        self.append_sys_msg("sys_error", error_msg, br_before=True)
        QMessageBox.warning(self, "进程异常", f"执行出现异常:\n{error_msg}\n\n请检查配置后点击底部按钮重试。")

    def handle_finished(self, exitCode, exitStatus):
        if self.is_restarting:
            return

        self.append_sys_msg("exit", f"进程已结束 (退出码: {exitCode})", br_before=True)

        if exitCode != 0 or exitStatus == QProcess.CrashExit:
            QMessageBox.critical(self, "进程异常", f"命令异常退出 (退出码: {exitCode})\n请修改后点击底部重试。")
            self.append_sys_msg(
                "error", "上次任务异常退出，请检查报错信息并修正问题。如需再次运行，请点击下方的“重启进程”按钮。"
            )
        else:
            self.append_sys_msg("success", "任务已正常执行完毕。如需再次运行，请点击下方的“重启进程”按钮。")

    def terminate_process(self):
        self.is_restarting = True
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)

    def execute_one_off(self):
        """外部直接触发一次性任务，不弹确认，直接清屏并执行"""
        if self.task_type == "one-off":
            self.output_text.clear()
            self.restart_process()
