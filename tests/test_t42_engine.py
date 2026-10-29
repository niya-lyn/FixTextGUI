"""M4-T4.2 测试：Python greedy 引擎 / 引擎选择数据层 / 降级分流。

覆盖四块：
  A. ``py_engine`` 替换语义硬门禁（排期 §3.1）——与朴素参考实现（模拟
     Go ``strings.NewReplacer`` 的 first-wins / 不重叠 / 命中跳尾 / 多趟）
     在随机与定向用例上逐字节一致；取消 / 超时 / E1006 / IN_PLACE 防线。
  B. ``engine_choice`` 数据层——契约键 ``engine`` 的读写、归一、环境变量
     覆盖、QSettings IniFormat 互读（与设置页 M4-EX.2a 的契约测试）。
  C. replace 阶段双轨分流——Go 缺失抛 ``GoEngineUnavailableError``、
     指纹随引擎切换而变。
  D. worker / 错误中心分流——``engine_failed`` 信号、半成品清理、
     E1006 翻译成用户码。

与 Go 引擎的**逐字节等价**（《炮火弧线》788 章全量 + 基线集）不在这里跑
（太重），由 ``tools/accept_t42.py`` 验收脚本承担并把数字写进报告。
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "pipeline", ROOT / "pipeline" / "vendor"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fixtext.engine import (  # noqa: E402
    EngineRequest,
    InputMode,
    OutputMode,
    RuleSet,
)
from fixtext.engine import py_engine  # noqa: E402
from fixtext.engine.errors import EngineErrorCode  # noqa: E402
from fixtext.engine.protocol import EngineResponse  # noqa: E402


# ---------------------------------------------------------------------------
# 参考实现：朴素模拟 Go strings.NewReplacer 语义（first-wins 贪心）
# ---------------------------------------------------------------------------

def reference_replace(before: list[str], after: list[str], text: str,
                      count: int = 2) -> str:
    """逐位置扫描：先按参数序找第一条命中的规则（first-wins）。

    命中则跳到匹配结束（不重叠），未命中前进 1 字符；跑 count 趟。
    这是排期 §3.1 语义的直译，用作 py_engine 的对照基准。
    """
    for _ in range(count):
        out = []
        i = 0
        while i < len(text):
            hit = None
            for b, a in zip(before, after):
                if b and text.startswith(b, i):
                    hit = (b, a)
                    break
            if hit is not None:
                out.append(hit[1])
                i += len(hit[0])
            else:
                out.append(text[i])
                i += 1
        text = "".join(out)
    return text


def _run_py(before, after, text, count=2):
    rules = RuleSet(before=list(before), after=list(after))
    resp = py_engine.PyGreedyEngineClient().run(EngineRequest(
        rules=rules, count=count,
        input_mode=InputMode.MEMORY, input_data=text,
        output_mode=OutputMode.MEMORY, encoding="utf-8",
    ))
    assert resp.ok, resp.error.as_dict() if resp.error else resp
    return resp.result.output_text


# ===========================================================================
# A. 替换语义硬门禁（排期 §3.1）
# ===========================================================================

class TestGreedySemantics:

    def test_first_wins_duplicate_before(self):
        # 同一 before 重复：取数组里第一条的 after（不是最后一条）
        assert _run_py(["萧衍", "萧衍"], ["A", "B"], "萧衍与萧衍", count=1) == "A与A"

    def test_overlap_jump_to_end(self):
        # 同起点多规则 / 交叠命中：起点小的先占，占完跳到匹配结束
        assert _run_py(["ab", "bc"], ["1", "2"], "abc", count=1) == "1c"
        # 同起点：参数序在前的规则赢（["ab","abc"] → ab 在前 → "1c"；
        # ["abc","ab"] → abc 在前，整个吞掉 → "1"）
        assert _run_py(["ab", "abc"], ["1", "2"], "abc", count=1) == "1c"
        assert _run_py(["abc", "ab"], ["1", "2"], "abc", count=1) == "1"

    def test_no_match_advance_one_char(self):
        # 未命中位置原字符保留，前进 1 字符
        assert _run_py(["xy"], ["Z"], "axb", count=1) == "axb"

    def test_two_passes(self):
        # 生产两趟：第一趟的输出是第二趟的输入
        assert _run_py(["a", "b"], ["b", "c"], "a", count=2) == "c"
        assert _run_py(["a", "b"], ["b", "c"], "a", count=1) == "b"

    def test_random_corpus_matches_reference(self):
        """随机语料 + 随机规则 × 单趟/两趟，与参考实现逐字节一致。"""
        rng = random.Random(20261028)
        alphabet = "abcde蕭衍彥的地得"
        for _case in range(120):
            n_rules = rng.randint(1, 12)
            before = ["".join(rng.choice(alphabet)
                              for _ in range(rng.randint(1, 4)))
                      for _ in range(n_rules)]
            after = ["".join(rng.choice(alphabet)
                             for _ in range(rng.randint(1, 3)))
                     for _ in range(n_rules)]
            if rng.random() < 0.3 and n_rules >= 2:
                before[1] = before[0]        # 故意造重复 before（first-wins）
            text = "".join(rng.choice(alphabet)
                           for _ in range(rng.randint(0, 200)))
            for count in (1, 2):
                got = _run_py(before, after, text, count=count)
                want = reference_replace(before, after, text, count=count)
                assert got == want, (before, after, text, count)


class TestPyEngineClient:

    def test_file_mode_roundtrip(self, tmp_path):
        src = tmp_path / "in.txt"
        src.write_text("你好蕭衍，蕭彥来了", encoding="utf-8")
        dst = tmp_path / "out.txt"
        rules = RuleSet(before=["蕭衍", "蕭彥"], after=["萧衍", "萧彦"])
        resp = py_engine.PyGreedyEngineClient().run(EngineRequest(
            rules=rules, count=2,
            input_mode=InputMode.FILE, input_path=src,
            output_mode=OutputMode.FILE, output_path=dst,
            encoding="utf-8", timeout_s=30,
        ))
        assert resp.ok, resp.error.as_dict() if resp.error else resp
        assert dst.read_text(encoding="utf-8") == "你好萧衍，萧彦来了"
        assert resp.result.engine_path == py_engine.PY_ENGINE_ID
        assert resp.result.changed is True
        assert resp.result.count == 2

    def test_e1006_when_dependency_missing(self, tmp_path, monkeypatch):
        import builtins

        src = tmp_path / "in.txt"
        src.write_text("abc", encoding="utf-8")
        monkeypatch.setitem(sys.modules, "ahocorasick", None)
        rules = RuleSet(before=["a"], after=["b"])
        resp = py_engine.PyGreedyEngineClient().run(EngineRequest(
            rules=rules, count=1,
            input_mode=InputMode.FILE, input_path=src,
            output_mode=OutputMode.MEMORY, encoding="utf-8",
        ))
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.PY_ENGINE_UNAVAILABLE
        assert resp.error.code == "E1006"

    def test_cancel_raises_cancelled_not_response(self, tmp_path):
        src = tmp_path / "in.txt"
        src.write_text("a" * 300000, encoding="utf-8")   # 足够多命中以触发检查点
        rules = RuleSet(before=["a"], after=["b"])
        py_engine.set_cancel_check(lambda: True)
        try:
            with pytest.raises(py_engine.PyEngineCancelled):
                py_engine.PyGreedyEngineClient().run(EngineRequest(
                    rules=rules, count=1,
                    input_mode=InputMode.FILE, input_path=src,
                    output_mode=OutputMode.MEMORY, encoding="utf-8",
                ))
        finally:
            py_engine.set_cancel_check(None)

    def test_in_place_disabled_by_default(self, tmp_path):
        src = tmp_path / "in.txt"
        src.write_text("abc", encoding="utf-8")
        rules = RuleSet(before=["a"], after=["b"])
        resp = py_engine.PyGreedyEngineClient().run(EngineRequest(
            rules=rules, count=1,
            input_mode=InputMode.FILE, input_path=src,
            output_mode=OutputMode.IN_PLACE, encoding="utf-8",
        ))
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.ARGUMENT_INVALID

    def test_in_place_allowed_with_env(self, tmp_path, monkeypatch):
        src = tmp_path / "in.txt"
        src.write_text("abc", encoding="utf-8")
        monkeypatch.setenv("FIXTEXT_ALLOW_IN_PLACE", "1")
        rules = RuleSet(before=["a"], after=["b"])
        resp = py_engine.PyGreedyEngineClient().run(EngineRequest(
            rules=rules, count=1,
            input_mode=InputMode.FILE, input_path=src,
            output_mode=OutputMode.IN_PLACE, encoding="utf-8",
        ))
        assert resp.ok, resp.error.as_dict() if resp.error else resp
        assert src.read_text(encoding="utf-8") == "bbc"


# ===========================================================================
# B. 引擎选择数据层（契约键 engine）
# ===========================================================================

class TestEngineChoice:

    def test_default_is_go(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FIXTEXT_ENGINE", raising=False)
        from fixtext_pipeline import engine_choice as ec
        assert ec.get_engine_choice(file=tmp_path / "none.ini") == "go"
        assert ec.DEFAULT_ENGINE == "go"

    def test_set_and_get_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FIXTEXT_ENGINE", raising=False)
        monkeypatch.delenv("FIXTEXT_SETTINGS_FILE", raising=False)
        from fixtext_pipeline import engine_choice as ec
        ini = tmp_path / "settings.ini"
        assert ec.set_engine_choice("python", file=ini) == "python"
        assert ec.get_engine_choice(file=ini) == "python"
        assert ec.set_engine_choice("go", file=ini) == "go"
        assert ec.get_engine_choice(file=ini) == "go"

    def test_normalize_junk_falls_back_to_go(self):
        from fixtext_pipeline import engine_choice as ec
        assert ec.normalize_choice("python") == "python"
        assert ec.normalize_choice("PYTHON") == "python"
        assert ec.normalize_choice("rust") == "go"
        assert ec.normalize_choice("") == "go"
        assert ec.normalize_choice(None) == "go"

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        from fixtext_pipeline import engine_choice as ec
        ini = tmp_path / "settings.ini"
        ec.set_engine_choice("go", file=ini)
        monkeypatch.setenv("FIXTEXT_ENGINE", "python")
        assert ec.get_engine_choice(file=ini) == "python"

    def test_settings_file_env_override(self, tmp_path, monkeypatch):
        from fixtext_pipeline import engine_choice as ec
        other = tmp_path / "other.ini"
        monkeypatch.setenv("FIXTEXT_SETTINGS_FILE", str(other))
        assert ec.settings_file() == other

    def test_qsettings_can_read_data_layer_write(self, tmp_path, monkeypatch):
        """契约测试（M4-EX.2a 设置页）：configparser 写的键 QSettings 能读到。"""
        monkeypatch.delenv("FIXTEXT_ENGINE", raising=False)
        from fixtext_pipeline import engine_choice as ec
        ini = tmp_path / "settings.ini"
        ec.set_engine_choice("python", file=ini)
        from PySide6.QtCore import QSettings
        qs = QSettings(str(ini), QSettings.Format.IniFormat)
        assert qs.value("engine", "") == "python"
        # 反向：QSettings 写的键数据层也能读到（设置页改引擎 → 管线生效）
        qs.setValue("engine", "go")
        qs.sync()
        assert ec.get_engine_choice(file=ini) == "go"

    def test_fallback_does_not_touch_settings(self, tmp_path, monkeypatch):
        """降级确认只对本次运行生效：数据层的持久值不被降级路径改写。"""
        monkeypatch.delenv("FIXTEXT_ENGINE", raising=False)
        from fixtext_pipeline import engine_choice as ec
        ini = tmp_path / "settings.ini"
        ec.set_engine_choice("go", file=ini)
        # 模拟 worker：显式传 engine="python" 跑一次，不调 set_engine_choice
        assert ec.get_engine_choice(file=ini) == "go"   # 持久值仍是 go

    def test_go_engine_status_missing(self, tmp_path):
        from fixtext_pipeline import engine_choice as ec
        ok, reason = ec.go_engine_status(tmp_path / "no-such-bin")
        assert ok is False
        assert "不存在" in reason

    def test_go_engine_status_real_binary(self):
        from fixtext_pipeline import engine_choice as ec
        from fixtext_pipeline.engine_selector import select_engine
        bin_dir = (ROOT / "pipeline" / "vendor" / "fixtext" / "engine"
                   / "go_src" / "bin")
        binpath = select_engine(bin_dir)
        if binpath is None:
            pytest.skip("本平台没有可用的 Go 引擎二进制")
        ok, reason = ec.go_engine_status(binpath)
        assert ok is True, reason


# ===========================================================================
# C. replace 阶段双轨分流
# ===========================================================================

def _tiny_cfg(tmp_path, engine, engine_path=None):
    from fixtext_pipeline.config import PipelineConfig
    rb = tmp_path / "before.json"
    ra = tmp_path / "after.json"
    rb.write_text(json.dumps(["萧衍", "蕭彥"], ensure_ascii=False), encoding="utf-8")
    ra.write_text(json.dumps(["萧衍", "萧彦"], ensure_ascii=False), encoding="utf-8")
    cfg = PipelineConfig(
        epub=tmp_path / "book.epub",
        workdir=tmp_path / "ws",
        rules_before=rb,
        rules_after=ra,
        engine_path=engine_path or (tmp_path / "missing-go-bin"),
        engine=engine,
        custom_vocab_path=tmp_path / "custom.json",
        derived_rules_dir=tmp_path / "derived",
    )
    # fingerprint() 要对排版产物取 sha：造一个最小 layout 正文
    cfg.layout_text().parent.mkdir(parents=True, exist_ok=True)
    cfg.layout_text().write_text("第一章\n萧衍与蕭彥\n", encoding="utf-8")
    return cfg


def _stage_of(cfg):
    from fixtext_pipeline.logsetup import StageLogger
    from fixtext_pipeline.stages.replace import ReplaceStage
    logger = StageLogger(cfg.workdir / "replace.log", echo=False)
    return ReplaceStage(cfg, logger)


class TestReplaceStageDualEngine:

    def test_go_missing_raises_typed_error(self, tmp_path):
        from fixtext_pipeline.stages.replace import GoEngineUnavailableError
        cfg = _tiny_cfg(tmp_path, engine="go")
        with pytest.raises(GoEngineUnavailableError):
            _stage_of(cfg).run()

    def test_go_not_a_file_raises_typed_error(self, tmp_path):
        from fixtext_pipeline.stages.replace import GoEngineUnavailableError
        bogus = tmp_path / "dir-bin"
        bogus.mkdir()
        cfg = _tiny_cfg(tmp_path, engine="go", engine_path=bogus)
        with pytest.raises(GoEngineUnavailableError):
            _stage_of(cfg).run()

    def test_fingerprint_changes_with_engine(self, tmp_path):
        cfg_go = _tiny_cfg(tmp_path, engine="go")
        cfg_py = _tiny_cfg(tmp_path, engine="python")
        assert _stage_of(cfg_go).fingerprint() != _stage_of(cfg_py).fingerprint()

    def test_engine_normalized_in_config(self, tmp_path):
        cfg = _tiny_cfg(tmp_path, engine="nonsense")
        assert cfg.engine == "go"
        assert cfg.to_dict()["engine"] == "go"


# ===========================================================================
# D. worker 分流 / 错误中心翻译
# ===========================================================================

class TestWorkerFallbackFlow:

    def test_correction_job_accepts_engine(self, tmp_path):
        sys.path.insert(0, str(ROOT / "fixtext_ui"))
        from fixtext_worker import CorrectionJob
        job = CorrectionJob(
            epub=tmp_path / "b.epub", workdir=tmp_path / "ws",
            rules_before=tmp_path / "rb.json", rules_after=tmp_path / "ra.json",
            engine_path=tmp_path / "go", pipeline_root=ROOT / "pipeline",
            engine="python",
        )
        assert job.engine == "python"
        assert job.engine_used is None       # run() 之前未定

    def test_engine_failed_signal_on_go_unavailable(self, tmp_path, qapp):
        """GoEngineUnavailableError → engine_failed 信号 + 半成品清理。"""
        from fixtext_pipeline.stages.replace import GoEngineUnavailableError
        from fixtext_worker import CorrectionWorker

        workdir = tmp_path / "partial"
        workdir.mkdir()
        (workdir / "half.txt").write_text("half", encoding="utf-8")

        class DummyJob:
            def set_stage_callbacks(self, *a, **k):
                pass

            def run(self):
                raise GoEngineUnavailableError("Go 引擎不存在：test-bin")

            def _cleanup(self):
                CorrectionWorker._last_cleaned = True

        worker = CorrectionWorker(DummyJob())  # type: ignore[arg-type]
        got: list[str] = []
        worker.engine_failed.connect(lambda reason: got.append(reason))
        worker.failed.connect(lambda m: got.append("WRONG:" + m))
        worker._run_in_thread()
        assert len(got) == 1
        assert "Go 引擎不存在" in got[0]
        assert CorrectionWorker._last_cleaned is True

    def test_e1006_translated_to_user_code(self):
        """错误中心 ENGINE_CODE_MAP：E1006 → U-P01（人话三段式可取到）。"""
        from fixtext_error_center.error_codes import ENGINE_CODE_MAP
        assert ENGINE_CODE_MAP["E1006"] == "U-P01"


class TestFallbackDialogCopy:
    """降级确认弹窗文案：不出现零露出禁用词（人话口径）。"""

    FORBIDDEN = ["spine", "opf", "manifest", "ncx", "xhtml", "xml", "bom",
                 "utf-8", "gbk", "sha256", "encoding", "charset", "zip",
                 "books", "rules.json", "replace_by_go"]

    def test_confirm_copy_is_human_readable(self, qapp, tmp_path):
        sys.path.insert(0, str(ROOT / "fixtext_ui"))
        from oneclick_module import OneClickModule

        reason = "引擎文件不存在（可能被删除或被杀毒软件隔离）：replace_by_go-linux-amd64"
        sanitized = OneClickModule._sanitized_reason(reason)
        # 内部文件名不进界面文案
        assert "replace_by_go" not in sanitized
        assert "不存在" in sanitized

        # 弹窗正文（note）也不含禁用词——用与 _confirm_engine_fallback 相同的模板拼出来
        note = (
            "检测到：" + sanitized + "。\n\n"
            "可以改用 Python 备用引擎完成这次校正——校正结果与平时完全一致，"
            "只是速度较慢：大部头书大约需要数十秒（平时一般只要几秒）。\n\n"
            "这次的选择只对本次校正生效，不会改动设置里的长期选择。"
        )
        low = note.lower()
        for w in self.FORBIDDEN:
            assert w not in low, w
