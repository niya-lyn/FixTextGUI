"""V1.1-E2 · 大书（20MB 级）打开耗时实测。

口径：
  * 差异计算（E1 的 build_diff）在后台线程跑，界面线程只负责结果落地；
  * 用 20ms 心跳定时器量「界面线程最长空档」＝卡死指标；
  * 再单独量「结果落地到界面」这段同步耗时。

用法：python3.12 tools/measure_e2_perf.py
"""
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "fixtext_ui", ROOT / "pipeline", ROOT / "pipeline" / "vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

from fixtext_compare import CompareModule               # noqa: E402
from fixtext_diff_view import (                         # noqa: E402
    RuleIndex, build_diff, build_diff_for_run,
)

OUT = ROOT / "evidence" / "e2_perf.json"


def _make_book(target_bytes: int):
    """造一本 ~target_bytes 的书：多章、多行、少量改词。"""
    n_rules = 300
    before_rules = [f"测试{i:03d}词" for i in range(n_rules)]
    after_rules = [f"校正{i:03d}词" for i in range(n_rules)]
    filler = "风从江面上吹过来，屋里点着一盏灯，字迹在纸上慢慢干透。"  # 31 字

    lines_per_chapter = 40
    chapter_bytes = (len(filler) * 3 + 1) * lines_per_chapter + 200
    n_chapters = max(1, target_bytes // chapter_bytes)

    before_lines, after_lines = [], []
    for c in range(n_chapters):
        before_lines.append(f"第{c + 1}章  夜航")
        after_lines.append(f"第{c + 1}章  夜航")
        for i in range(lines_per_chapter):
            tail = f"（{before_rules[(c * lines_per_chapter + i) % n_rules]}）" if i % 20 == 0 else "。"
            line = filler + tail
            before_lines.append(line)
            after_lines.append(line.replace(before_rules[(c * lines_per_chapter + i) % n_rules],
                                            after_rules[(c * lines_per_chapter + i) % n_rules])
                               if i % 20 == 0 else line)
    before = "\n".join(before_lines)
    after = "\n".join(after_lines)
    return before, after, before_rules, after_rules, n_chapters


def _measure_ui_stall(fn):
    """fn() 在后台线程跑；界面线程持续跳心跳，量最长空档。"""
    app = QApplication.instance()
    gaps = []
    last = [time.perf_counter()]
    timer = QTimer()
    timer.setInterval(20)

    def tick():
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now

    timer.timeout.connect(tick)
    timer.start()
    result = {}

    def worker():
        t0 = time.perf_counter()
        result["value"] = fn()
        result["seconds"] = time.perf_counter() - t0

    th = threading.Thread(target=worker)
    t_start = time.perf_counter()
    th.start()
    while th.is_alive():
        app.processEvents()
        time.sleep(0.005)
    th.join()
    app.processEvents()
    timer.stop()
    result["ui_max_gap_ms"] = round(max(gaps) * 1000, 1) if gaps else 0.0
    result["ui_ticks"] = len(gaps)
    result["wall_s"] = round(time.perf_counter() - t_start, 3)
    return result


def main():
    app = QApplication.instance() or QApplication([])
    data = {"python": sys.version.split()[0]}

    # ---- 1) 真实 301 章书（仓库自带的 t33_real 运行） ----
    real_run = ROOT / "runs" / "t33_real"
    if real_run.exists():
        t0 = time.perf_counter()
        report = build_diff_for_run(str(real_run))
        t_real = time.perf_counter() - t0
        mod = CompareModule()
        t0 = time.perf_counter()
        mod.set_report(report)
        t_apply = time.perf_counter() - t0
        data["real_301"] = {
            "items": report.item_count,
            "chapters": len(report.chapters),
            "hits": report.hits,
            "build_diff_s": round(t_real, 3),
            "ui_apply_s": round(t_apply, 3),
            "book_bytes": Path(report.before_path).stat().st_size
            if report.before_path and Path(report.before_path).exists() else 0,
        }
        mod.shutdown()

    # ---- 2) 20MB 级大书 ----
    t0 = time.perf_counter()
    before, after, br, ar, n_chapters = _make_book(20 * 1024 * 1024)
    t_gen = time.perf_counter() - t0
    tmp = Path("/tmp/e2_perf")
    tmp.mkdir(exist_ok=True)
    (tmp / "before.txt").write_text(before, encoding="utf-8")
    (tmp / "after.txt").write_text(after, encoding="utf-8")
    import json as _json
    (tmp / "before.json").write_text(_json.dumps(br, ensure_ascii=False), encoding="utf-8")
    (tmp / "after.json").write_text(_json.dumps(ar, ensure_ascii=False), encoding="utf-8")

    rules = RuleIndex.from_paths(tmp / "before.json", tmp / "after.json")
    holder = {}

    def do_build():
        return build_diff(before, after, rules=rules,
                          before_path=str(tmp / "before.txt"),
                          after_path=str(tmp / "after.txt"),
                          verify_hits=True)

    build = _measure_ui_stall(do_build)
    report = build.pop("value")
    data["big_20mb"] = {
        "book_mb": round(len(before.encode("utf-8")) / 1024 / 1024, 2),
        "chapters_synth": n_chapters,
        "lines": before.count("\n") + 1,
        "items": report.item_count,
        "hits": report.hits,
        "build_s": round(build["seconds"], 3),
        "ui_max_gap_ms": build["ui_max_gap_ms"],
        "ui_ticks": build["ui_ticks"],
        "wall_s": build["wall_s"],
    }

    # 结果落到界面（同步段）
    mod = CompareModule()
    t0 = time.perf_counter()
    mod.set_report(report)
    t_apply = time.perf_counter() - t0
    t0 = time.perf_counter()
    mod.step(1)
    mod._compare_view.scrollTo(mod.compare_model.index(0, 0))
    app.processEvents()
    t_first = time.perf_counter() - t0
    data["big_20mb"]["ui_apply_s"] = round(t_apply, 3)
    data["big_20mb"]["first_row_s"] = round(t_first, 3)
    data["big_20mb"]["gen_s"] = round(t_gen, 2)
    mod.shutdown()

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
