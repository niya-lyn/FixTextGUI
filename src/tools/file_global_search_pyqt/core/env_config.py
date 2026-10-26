import os
import configparser
import shutil


class EnvConfig:

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(EnvConfig, cls).__new__(cls)
        return cls._instance

    def __init__(self, config_file: str = "config.ini") -> None:
        if not hasattr(self, "config"):
            self.current_dir = os.path.dirname(os.path.abspath(__file__))
            absolute_config_path = os.path.abspath(os.path.join(self.current_dir, config_file))

            self.config = configparser.ConfigParser()
            self.config.read(absolute_config_path, encoding="utf-8")
            self.absolute_config_dir = os.path.dirname(absolute_config_path)

            if not self.config.sections():
                raise FileNotFoundError(f"配置文件未找到或内容为空: {absolute_config_path}")

    def _get_path(self, section: str, option: str) -> str:
        path = self.config.get(section, option)
        if not path:
            return ""

        if os.path.isabs(path):
            return path

        # 这里要改成以 ini 文件所在目录进行拼接
        return os.path.abspath(os.path.join(self.absolute_config_dir, path))

    @property
    def php_program(self) -> str:
        # 这里为了支持不需要拼接的 php 程序名，直接获取配置就行了
        return self.config.get("words_operations", "php_program", fallback="php")

    @property
    def file_dir(self) -> str:
        return self._get_path("file_global_search", "file_dir")

    @property
    def go_replace_cmd(self) -> str:
        return self._get_path("file_global_search", "go_replace_cmd")

    @property
    def regex_searcher_script(self) -> str:
        return self._get_path("file_global_search", "regex_searcher_script")

    @property
    def regex_intro_md(self) -> str:
        return self._get_path("file_global_search", "regex_intro_md")

    @property
    def compare_guidance_md(self) -> str:
        return self._get_path("file_global_search", "compare_guidance_md")

    @property
    def history_log_file(self) -> str:
        return self._get_path("file_global_search", "history_log_file")

    @property
    def formatting_config_file(self) -> str:
        return self._get_path("file_global_search", "formatting_config_file")

    @property
    def fixed_rules_converter_script(self) -> str:
        return self._get_path("file_global_search", "fixed_rules_converter")

    @property
    def chapter_analyzer_script(self) -> str:
        return self._get_path("file_global_search", "chapter_analyzer")

    @property
    def epub_merger_script(self) -> str:
        return self._get_path("file_global_search", "epub_merger")

    @property
    def diff_cmd(self) -> str:
        return "diff" if shutil.which("diff") else self._get_path("file_global_search", "diff_cmd")

    @property
    def patch_dir(self) -> str:
        return self._get_path("file_global_search", "patch_dir")


current_dir = os.path.dirname(__file__)
config_path = os.path.join(current_dir, "..", "..", "env", "config.ini")
env_config = EnvConfig(os.path.abspath(config_path))
