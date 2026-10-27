"""fixtext_error_center 单元测试（M2-T2.4）。

运行：
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q
（禁用插件自动加载：共享 site-packages 的 libtmux 插件与 pytest 9 不兼容。）
"""

from __future__ import annotations

import errno
import os
import sys
import tempfile
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fixtext_error_center as ec
from fixtext_error_center import ErrorCode
from fixtext_error_center.center import UserFacingError


@pytest.fixture()
def logdir(tmp_path):
    ec.init(str(tmp_path / "logs"))
    return ec.log_dir()


# ---------------------------------------------------------------------------
# 1. 映射表完备性（验收标准 2：每类错误有指引，无空文案）
# ---------------------------------------------------------------------------

class TestCatalog:
    def test_every_code_has_message(self):
        codes = {e.value for e in ErrorCode}
        assert set(ec.all_codes()) == codes, "错误码枚举与映射表必须一一对应"

    def test_every_message_complete(self):
        for code in ec.all_codes():
            m = ec.get_message(code)
            assert m["title"].strip(), code
            assert m["what"].strip(), code
            assert m["guidance"].strip(), code
            assert len(m["guidance"]) >= 12, f"{code} 指引过短，近似空文案"

    def test_no_forbidden_terms_in_user_text(self):
        for code in ec.all_codes():
            m = ec.get_message(code)
            for field in ("title", "what", "guidance"):
                for term in ec.FORBIDDEN_TERMS:
                    assert term not in m[field], f"{code}.{field} 泄漏技术词 {term!r}"

    def test_unknown_code_falls_back(self):
        m = ec.get_message("U-Z99")
        assert m["code" if "code" in m else "title"]  # 不抛异常
        assert m["guidance"], "未知码也必须有兜底指引"
        assert m["category"] == "运行"

    def test_every_code_has_category(self):
        from fixtext_error_center.error_codes import CATEGORY_OF

        for code in ec.all_codes():
            assert code in CATEGORY_OF, code


# ---------------------------------------------------------------------------
# 2. 归类器（异常 → 码），覆盖四层来源
# ---------------------------------------------------------------------------

class TestClassify:
    def test_os_read_errors(self):
        assert ec.classify(FileNotFoundError(errno.ENOENT, "x"), "import") == "U-I01"
        assert ec.classify(IsADirectoryError(errno.EISDIR, "x")) == "U-I01"

    def test_disk_full(self):
        assert ec.classify(OSError(errno.ENOSPC, "x")) == "U-P04"

    def test_permission_context_split(self):
        exc = PermissionError(errno.EACCES, "denied")
        assert ec.classify(exc, "export") == "U-E01"
        assert ec.classify(exc, "import") == "U-P05"
        assert ec.classify(exc) == "U-P05"

    def test_bad_zip(self):
        assert ec.classify(zipfile.BadZipFile("bad")) == "U-I02"

    def test_unicode_and_lookup(self):
        assert ec.classify(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")) == "U-I03"
        assert ec.classify(LookupError("unknown encoding: ascii9")) == "U-I03"

    def test_unexpected_falls_back(self):
        assert ec.classify(ValueError("any")) == "U-R00"
        assert ec.classify(RuntimeError("any")) == "U-R00"

    def test_user_facing_passthrough(self):
        exc = UserFacingError("U-I03")
        assert ec.classify(exc) == "U-I03"

    def test_engine_error_code_translation(self):
        class FakeEngine(Exception):
            def __init__(self, code, msg="m"):
                self.code = code
                super().__init__(msg)

        cases = {
            "E1001": "U-P01", "E1002": "U-P01", "E1003": "U-P03",
            "E1004": "U-P02", "E1005": "U-P02", "E1900": "U-P02",
            "E2101": "U-I01", "E2102": "U-I01",
            "E2201": "U-I05", "E2202": "U-I05", "E2203": "U-I05",
            "E2204": "U-I05", "E2301": "U-I05", "E2401": "U-E02",
        }
        for ecode, ucode in cases.items():
            assert ec.classify(FakeEngine(ecode)) == ucode, ecode

    def test_epub_structure_by_class_name(self):
        # 按名字匹配（模块加载不到时也工作）：造一个同名类
        epubtext = type(sys)("epubtext.errors")
        epubtext.EpubStructureError = type(
            "EpubStructureError", (Exception,), {"__module__": "epubtext.errors"})
        sys.modules["epubtext.errors"] = epubtext
        try:
            E = epubtext.EpubStructureError
            assert ec.classify(E("container.xml 中没有 rootfile 节点")) == "U-I04"
            assert ec.classify(E("x.epub 的 ZIP 结构损坏")) == "U-I02"
            assert ec.classify(E("不是合法的 ZIP/EPUB：a.epub")) == "U-I02"
        finally:
            del sys.modules["epubtext.errors"]

    def test_classify_never_raises(self):
        class Evil(Exception):
            def __str__(self):
                raise RuntimeError("no str for you")

        assert ec.classify(Evil()) == "U-R00"


# ---------------------------------------------------------------------------
# 3. report：人话返回 + 技术细节只进日志（验收标准 1/3 的数据面）
# ---------------------------------------------------------------------------

class TestReport:
    def test_report_returns_human_text_not_raw(self, logdir):
        r = ec.report(ValueError("secret-internal: /home/gem/x.py"), context="import")
        assert r.code == "U-R00"
        blob = r.title + r.what + r.guidance
        assert "secret-internal" not in blob
        assert "ValueError" not in blob

    def test_report_logs_technical(self, logdir):
        ec.report(OSError(errno.ENOSPC, "No space left on device /dev/sda"))
        rec = ec.last_record()
        assert rec["code"] == "U-P04"
        assert rec["errno"] == errno.ENOSPC
        assert "Traceback" in rec["traceback"] or "OSError" in rec["traceback"]

    def test_report_by_code_string(self, logdir):
        r = ec.report("U-I02", safe_hint="《坏书》.epub")
        assert r.code == "U-I02"
        assert r.safe_hint == "《坏书》.epub"

    def test_report_never_raises(self, logdir, monkeypatch):
        monkeypatch.setattr(ec.diaglog, "write_record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("log down")))
        r = ec.report(ValueError("x"))
        assert r.code == "U-R00"


# ---------------------------------------------------------------------------
# 4. guard 装饰器
# ---------------------------------------------------------------------------

class TestGuard:
    def test_guard_passes_value(self, logdir):
        @ec.guard
        def f(x):
            return x * 2

        assert f(21) == 42

    def test_guard_swallows_and_reports(self, logdir):
        @ec.guard
        def f():
            raise ValueError("inner-secret")

        assert f() is None
        rec = ec.last_record()
        assert rec["code"] == "U-R00"
        assert "inner-secret" in rec["traceback"]

    def test_guard_lets_systemexit_through(self, logdir):
        @ec.guard
        def f():
            raise SystemExit(2)

        with pytest.raises(SystemExit):
            f()


# ---------------------------------------------------------------------------
# 5. 诊断日志行为
# ---------------------------------------------------------------------------

class TestDiaglog:
    def test_records_are_jsonl(self, logdir):
        for i in range(3):
            ec.report(ValueError(f"n{i}"))
        recs = ec.read_records()
        assert len(recs) == 3
        assert [r["message"] for r in recs] == ["n0", "n1", "n2"]

    def test_rotation(self, logdir, monkeypatch):
        monkeypatch.setattr(ec.diaglog, "_ROTATE_BYTES", 200)
        for i in range(40):
            ec.report(ValueError("x" * 30))
        files = sorted(os.listdir(logdir))
        assert any(f.endswith(".log.1") for f in files), f"应产生滚动副本: {files}"
        assert len(ec.read_records()) > 0

    def test_disabled_writes_nothing(self, tmp_path):
        ec.init(str(tmp_path), enabled=False)
        assert ec.report(ValueError("x")).log_path is None


# ---------------------------------------------------------------------------
# 6. 应用级钩子（验收标准 3：未枚举异常兜底、不崩溃、不露堆栈）
# ---------------------------------------------------------------------------

class TestHooks:
    def test_sys_excepthook_routes_to_report(self, logdir, monkeypatch):
        captured = []
        monkeypatch.setattr(ec.center, "_DIALOG_SHOWER", lambda r, p: captured.append(r))
        ec.install_app_hooks()
        try:
            try:
                raise ValueError("hook-secret")
            except ValueError as exc:
                sys.excepthook(type(exc), exc, exc.__traceback__)
        finally:
            ec.uninstall_app_hooks()
        assert captured and captured[0].code == "U-R00"
        rec = ec.last_record()
        assert "hook-secret" in rec["traceback"]
        assert rec["code"] == "U-R00"

    def test_thread_excepthook(self, logdir, monkeypatch):
        import threading

        captured = []
        monkeypatch.setattr(ec.center, "_DIALOG_SHOWER", lambda r, p: captured.append(r))
        ec.install_app_hooks()
        try:
            done = threading.Event()

            def worker():
                try:
                    # 未捕获异常：由 threading 机制真实调用 threading.excepthook
                    raise RuntimeError("thread-secret")
                finally:
                    done.set()

            t = threading.Thread(target=worker)
            t.start(); t.join(2)
            assert done.is_set(), "worker 未在时限内结束"
        finally:
            ec.uninstall_app_hooks()
        assert captured and captured[0].code == "U-R00"


# ---------------------------------------------------------------------------
# 7. Resolved 界面契约
# ---------------------------------------------------------------------------

class TestResolvedContract:
    def test_resolved_fields_no_tech(self, logdir):
        r = ec.report(ValueError("traceback-ish detail"))
        assert not r.exc_type or "ValueError" not in (r.title + r.what + r.guidance)
        assert r.guidance
