import regex
from qtpy.QtCore import QObject, QRunnable, Signal


class NavigationCounterSignals(QObject):
    finished = Signal(list)


class NavigationCounterTask(QRunnable):

    def __init__(self, pattern: regex.Pattern, text_content: str):
        super().__init__()
        self.pattern = pattern
        self.text_content = text_content
        self.signals = NavigationCounterSignals()
        self._is_cancelled = False

    def run(self):
        all_matches = []
        try:
            # 查找所有匹配，可中断
            for match in self.pattern.finditer(self.text_content):
                if self._is_cancelled:
                    return
                all_matches.append(match)

            if not self._is_cancelled:
                self.signals.finished.emit(all_matches)
        except Exception:
            pass

    def cancel(self):
        self._is_cancelled = True
