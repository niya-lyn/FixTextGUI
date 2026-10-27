#!/usr/bin/env python3
"""M2-T2.4 验收实测：构造异常场景 → 统一错误出口 → 取证。

运行（沙箱内）：
    cd artifacts/product
    QT_QPA_PLATFORM=offscreen python3.12 tools/make_evidence.py 2> evidence/stderr.log

产出（evidence/ 下）：
- scenario_XX.png      每个异常场景的错误卡离屏截图
- records.json         每场景的行为记录（码 / 界面文案 / 日志验证 / 泄漏扫描）
- 实测记录.md          人读汇总表（由 tools/render_evidence.py 生成）

场景全部走「真实调用」触发异常（真实引擎二进制、真实 epubtext、真实 OS 行为）；
磁盘满（U-P04）用 RLIMIT_FSIZE 触发 OS 信号后转 OSError(ENOSPC)（见该场景记录）。
"""

from __future__ import annotations

import codecs
import errno
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))           # product/
WORK = os.path.dirname(os.path.dirname(BASE))                                 # workdir
ENG = os.path.join(WORK, "in", "eng")
GOBIN = os.path.join(ENG, "goengine", "src", "fixtext", "engine",
                     "go_src", "bin", "replace_by_go-linux-amd64")
RULES = os.path.join(ENG, "goengine", "tests", "fixtures", "rules")
EVID = os.path.join(BASE, "evidence")

for p in (BASE,
          os.path.join(ENG, "goengine", "src"),
          os.path.join(ENG, "epubtext", "epubtext", "src")):
    sys.path.insert(0, p)

from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import fixtext_error_center as ec  # noqa: E402
from fixtext_error_center import qt_bridge  # noqa: E402

app = QApplication([])

os.makedirs(EVID, exist_ok=True)
ec.init(os.path.join(EVID, "logs"))

RECORDS = []


# ---------------------------------------------------------------------------
# 取证工具
# ---------------------------------------------------------------------------

def _card_visible_text():
    card = qt_bridge._active_card
    if card is None:
        return []
    texts = [card.windowTitle()]
    for w in card.findChildren(QLabel):
        texts.append(w.text())
    for w in card.findChildren(QPushButton):
        texts.append(w.text())
    return [t for t in texts if t]


def _grab(name):
    card = qt_bridge._active_card
    if card is None:
        return None
    app.processEvents()
    path = os.path.join(EVID, name)
    ok = card.grab().save(path)
    return path if ok else None


def _leaks_of(visible, secrets):
    leaks = []
    for t in visible:
        for term in ec.FORBIDDEN_TERMS:
            if term in t:
                leaks.append("界面泄漏技术词 " + repr(term) + ": " + t[:60])
        for s in secrets:
            if s and s in t:
                leaks.append("界面泄漏内部串 " + repr(s))
    return leaks


def record_from_report(tag, title, how, secrets, resolved=None, context=None,
                       safe_hint=None, force_code=None):
    """report 已由调用方完成（或在这里补做）后取证。"""
    app.processEvents()
    visible = _card_visible_text()
    shot = _grab("scenario_" + tag + ".png")
    log_rec = ec.last_record() or {}
    leaks = _leaks_of(visible, secrets)
    code = resolved.code if resolved else (force_code or log_rec.get("code"))
    msg = ec.get_message(code)
    RECORDS.append({
        "tag": tag, "title": title, "how": how, "code": code,
        "card_title": msg["title"], "what": msg["what"], "guidance": msg["guidance"],
        "visible_text": visible, "screenshot": shot,
        "界面零泄漏": not leaks, "泄漏明细": leaks,
        "有指引": bool(msg["guidance"]),
        "日志_有技术细节": bool(log_rec.get("traceback")) and bool(log_rec.get("exc_type")),
        "日志_含内部串": all(s in (log_rec.get("traceback", "") + str(log_rec.get("message", "")))
                            for s in secrets) if secrets else True,
        "未崩溃": True,
        "log_exc_type": log_rec.get("exc_type"),
        "log_engine_code": log_rec.get("engine_code"),
    })


def scenario(tag, title, how, secrets, context=None, safe_hint=None):
    """返回 run(exc)：归类 → 日志 → 弹卡 → 取证。"""
    def run(exc):
        print("[进度] S%s begin" % tag, flush=True)
        r = ec.report(exc, context=context, parent=None, safe_hint=safe_hint)
        record_from_report(tag, title, how, secrets, resolved=r)
        print("[进度] S%s done -> %s" % (tag, r.code), flush=True)
        return r
    return run


def make_truncated_epub(path):
    """自造「下载不完整」的损坏 EPUB：合法 zip 写出后截断后半。"""
    src = path + ".full"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("OPS/a.html", "<html><body>字</body></html>" * 500)
    data = open(src, "rb").read()
    open(path, "wb").write(data[: int(len(data) * 0.55)])


def make_bad_structure_epub(path):
    """自造「结构异常」EPUB：zip 合法但没有 container.xml / OPF。"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("OPS/a.html", "<html><body>字</body></html>")


def big_text(mb):
    return "汉字替换测试文本行" * (mb * 1024 * 1024 // 21)


# ---------------------------------------------------------------------------
# 场景执行
# ---------------------------------------------------------------------------

tmp = tempfile.mkdtemp(prefix="t24_")

# S01 损坏 EPUB（导入侧真实调用 epubtext）
from epubtext.archive import EpubArchive  # noqa: E402

bad_epub = os.path.join(tmp, "坏书_下载不完整.epub")
make_truncated_epub(bad_epub)
s = scenario("01", "损坏 EPUB",
             "自造截断 zip（模拟下载不完整），真实调用 epubtext.EpubArchive 打开",
             secrets=["Traceback"], context="import")
try:
    EpubArchive(bad_epub).container_xml()
    raise SystemExit("S01 应当抛异常")
except Exception as exc:
    s(exc)

# S02 EPUB 结构异常（zip 合法但缺 container.xml）
bad2 = os.path.join(tmp, "结构异常.epub")
make_bad_structure_epub(bad2)
s = scenario("02", "EPUB 结构异常",
             "zip 合法但缺 container.xml，真实调用 epubtext 读取 container",
             secrets=["Traceback"], context="import")
try:
    with EpubArchive(bad2) as a:
        a.container_xml()
    raise SystemExit("S02 应当抛异常")
except Exception as exc:
    s(exc)

# S03 不存在的编码（真实 codecs.lookup）
s = scenario("03", "不存在的编码",
             "codecs.lookup('ascii9')（导入模块识别编码的真实底层调用）",
             secrets=["LookupError", "ascii9"], context="import")
try:
    codecs.lookup("ascii9")
except Exception as exc:
    s(exc)

# S04 只读目录导出（真实 PermissionError）
ro = os.path.join(tmp, "只读导出目录")
os.makedirs(ro)
os.chmod(ro, 0o555)
s = scenario("04", "只读目录导出",
             "目录 chmod 0555 后真实 open(..., 'w') 写入",
             secrets=["PermissionError"], context="export")
try:
    open(os.path.join(ro, "out.epub"), "wb")
except Exception as exc:
    s(exc)
os.chmod(ro, 0o755)

# S05 引擎缺失（真实 GoEngineClient 前置检查）
from fixtext.engine.client import GoEngineClient  # noqa: E402
from fixtext.engine.protocol import EngineRequest, RuleSet  # noqa: E402

s = scenario("05", "引擎缺失",
             "GoEngineClient 指向不存在的引擎路径后真实 run()（E1001）",
             secrets=["EngineError", "E1001"], context="processing")
client = GoEngineClient(engine_path=os.path.join(tmp, "不存在的引擎"))
resp = client.run(EngineRequest(rules=RuleSet(before=["一"], after=["二"]),
                                input_data="一", count=2))
assert not resp.ok
s(resp.error)

# S06 杀掉引擎进程 · 客户端超时强制终止（真实 subprocess kill）
rs = RuleSet.from_files(os.path.join(RULES, "before.json"), os.path.join(RULES, "after.json"))
client = GoEngineClient(engine_path=GOBIN)
req = EngineRequest(rules=rs, input_data=big_text(120), count=2, timeout_s=1.0)
t0 = time.time()
resp = client.run(req)
elapsed = time.time() - t0
assert not resp.ok, "S06 预期失败，实际成功（输入不够大）"
s = scenario("06", "杀掉引擎进程（超时终止）",
             "真实引擎处理 120MB 文本、timeout_s=1 → 客户端强制终止子进程（E1003），耗时 %.1fs" % elapsed,
             secrets=["EngineError", "E1003", "Traceback"], context="processing")
s(resp.error)

# S07 杀掉引擎进程 · 外部 kill -9（进程被外部强杀 → E1004）
box = {"res": None}

def _engine_thread():
    try:
        req2 = EngineRequest(rules=rs, input_data=big_text(120), count=2, timeout_s=60)
        box["res"] = client.run(req2)
    except Exception as exc:
        box["res"] = exc

th = threading.Thread(target=_engine_thread)
th.start()
killed = False
for _ in range(120):                      # 最多 12s 内找到并强杀引擎进程
    time.sleep(0.1)
    try:
        out = subprocess.run(["pgrep", "-f", "replace_by_go-linux"],
                             capture_output=True, text=True)
        pids = [p for p in out.stdout.split() if p]
        if pids:
            subprocess.run(["kill", "-9"] + pids, capture_output=True)
            killed = True
            break
    except Exception:
        pass
th.join(30)
res = box["res"]
assert res is not None
exc07 = res.error if hasattr(res, "error") else res
s = scenario("07", "杀掉引擎进程（外部 kill -9）",
             "真实引擎处理 120MB 文本期间用系统 kill -9 强杀引擎进程（E1004），已强杀=%s" % killed,
             secrets=["EngineError", "E1004", "Traceback"], context="processing")
s(exc07)

# S08 文件不存在（真实 FileNotFoundError）
s = scenario("08", "导入文件不存在", "open() 一个不存在的路径", secrets=["FileNotFoundError"], context="import")
try:
    open(os.path.join(tmp, "不存在的书.epub"), "rb")
except Exception as exc:
    s(exc)

# S09 读取权限不足（真实 PermissionError，chmod 000）
pf = os.path.join(tmp, "无权限文件.txt")
open(pf, "w").write("x")
os.chmod(pf, 0o000)
s = scenario("09", "读取权限不足", "文件 chmod 000 后真实 open 读", secrets=["PermissionError"], context="import")
try:
    open(pf, "rb")
except Exception as exc:
    s(exc)
os.chmod(pf, 0o644)

# S10 磁盘空间不足（RLIMIT_FSIZE 触发 OS 信号，handler 转 OSError(ENOSPC)）
try:
    import resource

    def _on_xfsz(signum, frame):
        raise OSError(errno.ENOSPC, "信号模拟：写入超出文件大小上限")

    old = signal.signal(signal.SIGXFSZ, _on_xfsz)
    old_lim = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (65536, old_lim[1]))
    try:
        with open(os.path.join(tmp, "大文件.bin"), "wb") as f:
            f.write(b"\0" * (1024 * 1024))
        raise SystemExit("S10 应当抛异常")
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, old_lim)
        signal.signal(signal.SIGXFSZ, old)
except OSError as exc:
    s = scenario("10", "磁盘空间不足",
                 "resource.setrlimit(RLIMIT_FSIZE, 64KB) 后写 1MB → SIGXFSZ 信号 → OSError(ENOSPC)",
                 secrets=["OSError"], context="processing")
    s(exc)

# S11 未枚举异常兜底 · 主线程（应用级钩子；stderr 不得出现 Traceback）
ec.install_app_hooks()
try:
    raise RuntimeError("secret-r00-marker 内部细节 /home/gem/x.py")
except RuntimeError as exc:
    sys.excepthook(type(exc), exc, exc.__traceback__)
record_from_report("11", "未枚举异常兜底（主线程）",
                   "安装 install_app_hooks 后触发 sys.excepthook（PySide6 槽异常真实落点）",
                   secrets=["secret-r00-marker"])

# S12 未枚举异常兜底 · worker 线程
done = threading.Event()

def _worker():
    try:
        raise ValueError("secret-thread-marker")
    finally:
        done.set()

threading.Thread(target=_worker).start()
done.wait(5)
for _ in range(100):
    app.processEvents()
    log_rec = ec.last_record() or {}
    if "secret-thread-marker" in log_rec.get("traceback", ""):
        break
    time.sleep(0.02)
record_from_report("12", "未枚举异常兜底（worker 线程）",
                   "worker 线程抛未捕获异常 → threading.excepthook 自动兜底",
                   secrets=["secret-thread-marker"])
ec.uninstall_app_hooks()

# S13 guard 装饰器接入样例（后续各卡接线统一形态）

@ec.guard
def on_button_clicked():
    raise ValueError("guard-secret-marker 内部堆栈细节")

try:
    out = on_button_clicked()
    assert out is None
except Exception:
    raise SystemExit("S13 guard 不应外抛")
record_from_report("13", "guard 装饰器接入样例",
                   "@error_center.guard 包住的槽函数抛异常 → 自动归类+日志+弹卡（接线统一形态）",
                   secrets=["guard-secret-marker"])

# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

with open(os.path.join(EVID, "records.json"), "w", encoding="utf-8") as f:
    json.dump(RECORDS, f, ensure_ascii=False, indent=2)

ok = all(r["界面零泄漏"] and r["有指引"] and r["日志_有技术细节"] and r["未崩溃"] for r in RECORDS)
print("场景数:", len(RECORDS), " 全部通过:", ok)
for r in RECORDS:
    flag = "PASS" if (r["界面零泄漏"] and r["有指引"] and r["日志_有技术细节"] and r["未崩溃"]) else "FAIL"
    shot = os.path.basename(r["screenshot"]) if r["screenshot"] else "无"
    print("[%s] S%s %s -> %s shot=%s" % (flag, r["tag"], r["title"], r["code"], shot))
    for lk in r["泄漏明细"]:
        print("      ", lk)

shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if ok else 1)
