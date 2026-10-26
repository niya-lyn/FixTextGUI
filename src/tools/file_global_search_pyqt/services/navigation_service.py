import regex
from qtpy.QtCore import QObject, QThreadPool
from typing import Optional, List, Tuple
from tasks.navigation_counter_task import NavigationCounterTask
import utils.util as util


class NavigationService(QObject):
    def __init__(self):
        super().__init__()

        # --- 匹配计数的后台任务 ---
        self.thread_pool = QThreadPool.globalInstance()
        self.counter_task = None

        # --- 缓存属性 ---
        # 这些属性用于存储上次完整搜索的结果，避免重复计算
        self.cached_pattern: Optional[regex.Match] = None
        self.cached_text_hash: Optional[int] = None
        self.cached_all_matches: List[regex.Match] = []

        # 傻逼写法：用于暂存回调所需数据的实例变量，防止被垃圾回收
        self._pending_pattern = None
        self._pending_text = None
        self._pending_callback = None

    def compile_pattern(self, pattern_str: str, use_regex: bool, flags: int) -> Optional[regex.Pattern]:
        try:
            if not use_regex:
                pattern_str = regex.escape(pattern_str)
            return regex.compile(pattern_str, flags)
        except regex.error:
            return None

    def invalidate_cache(self):
        """
        当搜索词、选项或文本内容改变时，必须调用此方法来使缓存失效
        这会强制下一次导航时执行一次全新的搜索
        """
        # 如果有正在运行的计数任务，取消它
        if self.counter_task:
            self.counter_task.cancel()
            self.counter_task = None
            return True

        self.cached_pattern = None
        self.cached_text_hash = None
        self.cached_all_matches = []

        return False

    def find_match(
        self, pattern: regex.Pattern, text: str, search_pos: int, forward: bool
    ) -> Tuple[Optional[regex.Match], List[regex.Match]]:
        """
        在文本中查找匹配项
        如果缓存有效，从缓存中查找
        如果缓存无效，只快速查找下一个/上一个匹配项，返回空列表，让 Controller 开启后台任务来计算全部
        """
        current_hash = hash(text)

        # 检查缓存是否有效。条件：pattern 对象和文本内容都没有改变
        if self.cached_pattern == pattern and self.cached_text_hash == current_hash:
            # 缓存命中
            found = None
            matches = self.cached_all_matches
            if forward:
                found = next((m for m in matches if m.start() >= search_pos), None)
            else:  # backward
                found = next((m for m in reversed(matches) if m.end() <= search_pos), None)
            return found, matches
        else:
            # 缓存失效，执行快速查找（不扫描全文）
            found = None
            if forward:
                found = pattern.search(text, pos=search_pos)
            else:
                found = util.find_last_match_by_regex(pattern, text, search_pos, alignment_marker="【匹配项：")

            return found, []

    def start_background_counting(self, pattern: regex.Pattern, text: str, callback):
        """开启后台统计任务"""
        # 如果上一个任务还在跑，直接返回，无需启动新任务
        # 这时很有可能是在持续进行导航跳转，且文本并未发生变更
        # 如果文本有变更，会自动调用 invalidate_cache 取消任务
        if self.counter_task:
            return

        # 暂存到实例变量中，傻逼写法
        self._pending_pattern = pattern
        self._pending_text = text
        self._pending_callback = callback

        self.counter_task = NavigationCounterTask(pattern, text)

        self.counter_task.signals.finished.connect(self._on_counting_task_finished)
        self.thread_pool.start(self.counter_task)

    def _on_counting_task_finished(self, matches):
        self.counter_task = None

        if matches:
            self.cached_pattern = self._pending_pattern
            self.cached_text_hash = hash(self._pending_text)
            self.cached_all_matches = matches

        # 触发 Controller 传进来的回调
        if self._pending_callback:
            self._pending_callback(matches)

        # 清理引用
        self._pending_pattern = None
        self._pending_text = None
        self._pending_callback = None
