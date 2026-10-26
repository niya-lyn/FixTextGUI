import os
import json
import regex
from typing import Dict, Tuple


class StyleService:
    """纯后台服务：只负责根据路径读取文件，返回字符串和字典，没有任何 UI 依赖"""

    def __init__(self, project_root: str):
        self.project_root = project_root

    def get_qss_path(self, theme_name: str, file_name: str) -> str:
        return os.path.join(self.project_root, "resources", "themes", theme_name, "qss", file_name)

    def get_qss(self, theme_name: str, file_name: str) -> str:
        qss_path = self.get_qss_path(theme_name, file_name)
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def get_function_colors(self, theme_name: str) -> Dict[str, Tuple[str, str]]:
        json_path = os.path.join(
            self.project_root, "resources", "themes", theme_name, "highlight", "function_highlight_rules.json"
        )
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                rules_data = json.loads(f.read())

            colors_dict = {}
            for key, config in rules_data.items():
                colors_dict[key] = (config.get("background", "yellow"), config.get("color", "black"))
            return colors_dict
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def get_highlight_rules(self, theme_name: str, file_name: str) -> str:
        json_path = os.path.join(self.project_root, "resources", "themes", theme_name, "highlight", file_name)
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    @staticmethod
    def parse_qss_selector_props(qss_content: str, selector: str) -> Dict[str, str]:
        """从完整的 QSS 字符串中提取指定选择器的属性字典"""
        pattern = regex.compile(rf"{regex.escape(selector)}\s*\{{\s*([^}}]*)\}}", regex.DOTALL)
        match = pattern.search(qss_content)
        if not match:
            return {}

        block = match.group(1)
        props = {}
        for line in block.split(";"):
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, val = line.split(":", 1)
            props[key.strip()] = val.strip()

        return props

    def update_qss_file(self, qss_path: str, selector: str, new_props: Dict[str, str]) -> bool:
        """
        更新 QSS 文件中指定选择器的样式属性块

        :param qss_path:  QSS 文件的完整路径
        :param selector:  选择器名称，例如 'CustomPlainTextEdit'
        :param new_props: 需要更新的属性字典，例如 {'font-family': '"Arial", sans-serif', 'font-size': '14pt'}
        :return: 是否成功更新
        """
        try:
            with open(qss_path, "r", encoding="utf-8") as f:
                content = f.read()

        except FileNotFoundError:
            # 文件不存在，则创建新文件并写入该选择器的块
            new_block = self._generate_qss_block(selector, new_props)
            try:
                with open(qss_path, "w", encoding="utf-8") as f:
                    f.write(new_block + "\n")
                return True
            except Exception as e:
                print(f"写入文件失败: {e}")
                return False

        # 尝试替换已有块
        pattern = regex.compile(rf"{regex.escape(selector)}\s*\{{\s*([^}}]*)\}}", regex.DOTALL)
        new_block = self._generate_qss_block(selector, new_props)
        if pattern.search(content):
            new_content = pattern.sub(new_block, content)
        else:
            # 若选择器不存在，则在末尾追加
            if content and not content.endswith("\n"):
                content += "\n"
            new_content = content + new_block + "\n"

        try:
            with open(qss_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            return True
        except Exception as e:
            print(f"写入文件失败: {e}")
            return False

    @staticmethod
    def _generate_qss_block(selector: str, props: Dict[str, str]) -> str:
        """根据选择器和属性字典生成 QSS 块字符串。"""
        if not props:
            return ""
        lines = [f"{k}: {v};" for k, v in props.items()]
        return f"{selector} {{\n  " + "\n  ".join(lines) + "\n}"
