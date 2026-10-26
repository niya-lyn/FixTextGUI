"""Go 引擎客户端单测：真实起子进程，覆盖成功路径与全部可触发错误码。

这些用例的价值在于「真的跑过」——每条错误码都由一次真实进程调用或真实静态拦截产生，
不是 mock。慢用例（20MB）打 slow 标记但仍默认执行：它是集成层最核心的回归护栏。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fixtext.engine import EngineRequest, GoEngineClient, InputMode, OutputMode, RuleSet
from fixtext.engine.errors import EngineError, EngineErrorCode

pytestmark = pytest.mark.usefixtures("engine_bin")


def _rules(before: list[str], after: list[str]) -> RuleSet:
    return RuleSet(before, after, source="unit-test")


class TestSuccessPaths:
    def test_memory_in_memory_out(self, go_client: GoEngineClient) -> None:
        resp = go_client.run(EngineRequest(rules=_rules(["的地得"], ["X"]), input_data="的地得", count=1))
        assert resp.ok, resp.error.as_dict() if resp.error else ""
        assert resp.result.output_text == "X"
        assert resp.result.changed is True
        assert resp.result.exit_code == 0
        assert "替换完成" in resp.result.engine_stdout

    def test_count_two_applies_twice(self, go_client: GoEngineClient) -> None:
        """两趟替换是生产语义：链式规则只有第二趟才会收敛。"""
        rs = _rules(["甲", "乙"], ["乙", "丙"])
        resp = go_client.run(EngineRequest(rules=rs, input_data="甲", count=2))
        assert resp.ok
        assert resp.result.output_text == "丙", "count=2 应让 甲→乙→丙 链式收敛"
        assert resp.result.count == 2

    def test_count_one_does_not_chain(self, go_client: GoEngineClient) -> None:
        rs = _rules(["甲", "乙"], ["乙", "丙"])
        resp = go_client.run(EngineRequest(rules=rs, input_data="甲", count=1))
        assert resp.ok
        assert resp.result.output_text == "乙"

    def test_file_input_file_output_leaves_input_untouched(
        self, go_client: GoEngineClient, tmp_path: Path
    ) -> None:
        src = tmp_path / "in.txt"
        src.write_text("的地得测试", encoding="utf-8")
        original = src.read_bytes()
        dst = tmp_path / "out" / "result.txt"
        resp = go_client.run(
            EngineRequest(
                rules=_rules(["的地得"], ["X"]),
                input_mode=InputMode.FILE,
                input_path=src,
                output_mode=OutputMode.FILE,
                output_path=dst,
                count=1,
            )
        )
        assert resp.ok
        assert src.read_bytes() == original, "只读保护：原始文件不得被改动"
        assert dst.read_text(encoding="utf-8") == "X测试"
        assert resp.result.sha256_out == resp.result.sha256_in or resp.result.changed

    def test_in_place_overwrites_when_explicitly_requested(
        self, go_client: GoEngineClient, tmp_path: Path
    ) -> None:
        src = tmp_path / "in.txt"
        src.write_text("的地得", encoding="utf-8")
        resp = go_client.run(
            EngineRequest(
                rules=_rules(["的地得"], ["X"]),
                input_mode=InputMode.FILE,
                input_path=src,
                output_mode=OutputMode.IN_PLACE,
                count=1,
            )
        )
        assert resp.ok
        assert src.read_text(encoding="utf-8") == "X"
        assert not src.with_name(src.name + ".fixtext-tmp").exists(), "临时文件应已被 replace 清理"

    def test_multibyte_and_overlap_semantics(self, go_client: GoEngineClient) -> None:
        """首字符共用的规则：Go strings.NewReplacer 的 first-wins 语义要保持。"""
        rs = _rules(["ABC", "AB"], ["1", "2"])
        resp = go_client.run(EngineRequest(rules=rs, input_data="ABABC", count=1))
        assert resp.ok
        # NewReplacer 每位置优先最长匹配 -> AB->2, ABC->1
        assert resp.result.output_text == "21"

    def test_no_match_keeps_bytes_identical(self, go_client: GoEngineClient) -> None:
        rs = _rules(["绝不存在这个词组"], ["X"])
        data = "一段完全无关的文本，包含标点、数字 123 与换行。\n第二行。"
        resp = go_client.run(EngineRequest(rules=rs, input_data=data, count=2))
        assert resp.ok
        assert resp.result.changed is False
        assert resp.result.sha256_in == resp.result.sha256_out

    def test_empty_input(self, go_client: GoEngineClient) -> None:
        resp = go_client.run(EngineRequest(rules=_rules(["a"], ["b"]), input_data="", count=1))
        assert resp.ok
        assert resp.result.bytes_in == 0
        assert resp.result.bytes_out == 0

    def test_t02_real_rules_smoke(self, go_client: GoEngineClient, t02_rules_dir: Path) -> None:
        """用 T0.2 真实词库（30 万条）跑一次真实替换。"""
        rs = RuleSet.from_files(t02_rules_dir / "before.json", t02_rules_dir / "after.json")
        text = "他的目的达到了。\u201c你好\u201d\n"
        resp = go_client.run(EngineRequest(rules=rs, input_data=text, count=1, timeout_s=120))
        assert resp.ok, resp.error.as_dict() if resp.error else ""
        assert resp.result.rules == 304255
        assert resp.result.unique_rules == 243535


class TestErrorPaths:
    def test_engine_missing(self) -> None:
        client = GoEngineClient("/tmp/fixtext-definitely-no-engine-here")
        resp = client.run(EngineRequest(rules=_rules(["a"], ["b"]), input_data="x"))
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.ENGINE_MISSING
        assert resp.error.detail["engine_path"].endswith("fixtext-definitely-no-engine-here")

    def test_engine_path_is_directory(self, tmp_path: Path) -> None:
        resp = GoEngineClient(tmp_path).run(EngineRequest(rules=_rules(["a"], ["b"]), input_data="x"))
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.ENGINE_NOT_EXECUTABLE

    def test_engine_without_exec_bit(self, tmp_path: Path) -> None:
        fake = tmp_path / "engine"
        fake.write_bytes(b"not executable")
        fake.chmod(0o644)
        resp = GoEngineClient(fake).run(EngineRequest(rules=_rules(["a"], ["b"]), input_data="x"))
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.ENGINE_NOT_EXECUTABLE
        assert "执行位" in resp.error.message

    def test_engine_bad_format_with_exec_bit(self, tmp_path: Path) -> None:
        """有执行位但格式非法 -> 内核拒绝执行，必须归到 E1002 而不是 E1900。"""
        fake = tmp_path / "engine"
        fake.write_bytes(b"#!/nonexistent-interpreter\n")
        fake.chmod(0o755)
        resp = GoEngineClient(fake).run(EngineRequest(rules=_rules(["a"], ["b"]), input_data="x"))
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.ENGINE_NOT_EXECUTABLE

    def test_timeout_is_really_killed(self, go_client: GoEngineClient, t02_rules_dir: Path) -> None:
        """真超时：用 T0.2 全量规则（30 万条，仅加载与建索引就约 1s），给 0.1s 必超。"""
        rs = RuleSet.from_files(t02_rules_dir / "before.json", t02_rules_dir / "after.json")
        resp = go_client.run(EngineRequest(rules=rs, input_data="的地得测试", count=2, timeout_s=0.1))
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.ENGINE_TIMEOUT
        assert resp.error.detail["timeout_s"] == 0.1
        assert resp.error.detail["command"][-1] == "2"

    def test_control_same_rules_succeeds_with_enough_timeout(
        self, go_client: GoEngineClient, t02_rules_dir: Path
    ) -> None:
        """与超时用例同源规则、同输入，只放宽超时 -> 成功。证明超时归因正确，不是环境坏了。"""
        rs = RuleSet.from_files(t02_rules_dir / "before.json", t02_rules_dir / "after.json")
        resp = go_client.run(EngineRequest(rules=rs, input_data="的地得测试", count=2, timeout_s=300))
        assert resp.ok, resp.error.as_dict() if resp.error else ""

    def test_input_missing(self, go_client: GoEngineClient, tmp_path: Path) -> None:
        resp = go_client.run(
            EngineRequest(
                rules=_rules(["a"], ["b"]),
                input_mode=InputMode.FILE,
                input_path=tmp_path / "nope.txt",
                output_mode=OutputMode.MEMORY,
            )
        )
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.INPUT_MISSING

    def test_input_is_directory(self, go_client: GoEngineClient, tmp_path: Path) -> None:
        resp = go_client.run(
            EngineRequest(
                rules=_rules(["a"], ["b"]),
                input_mode=InputMode.FILE,
                input_path=tmp_path,
                output_mode=OutputMode.MEMORY,
            )
        )
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.INPUT_UNREADABLE

    def test_output_write_failed(self, go_client: GoEngineClient, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file", encoding="utf-8")
        resp = go_client.run(
            EngineRequest(
                rules=_rules(["的地得"], ["X"]),
                input_data="的地得",
                output_mode=OutputMode.FILE,
                output_path=blocker / "sub" / "out.txt",
                count=1,
            )
        )
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.OUTPUT_WRITE_FAILED

    def test_argument_invalid_count(self, go_client: GoEngineClient) -> None:
        resp = go_client.run(EngineRequest(rules=_rules(["a"], ["b"]), input_data="x", count=0))
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.ARGUMENT_INVALID

    def test_rules_length_mismatch_is_static(self, go_client: GoEngineClient) -> None:
        with pytest.raises(EngineError) as ei:
            RuleSet(["a", "b"], ["c"])
        assert ei.value.code == EngineErrorCode.RULES_LENGTH_MISMATCH

    def test_rules_empty_is_static(self) -> None:
        with pytest.raises(EngineError) as ei:
            RuleSet([], [])
        assert ei.value.code == EngineErrorCode.RULES_EMPTY

    def test_protocol_violation_when_engine_silent(self, tmp_path: Path) -> None:
        """引擎退出 0 但无摘要行 -> E1005。用一个假「引擎」模拟：只 exit 0 不动文件。"""
        fake = tmp_path / "silent_engine"
        fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake.chmod(0o755)
        resp = GoEngineClient(fake).run(EngineRequest(rules=_rules(["a"], ["b"]), input_data="x"))
        assert not resp.ok
        assert resp.error.code == EngineErrorCode.ENGINE_OUTPUT_UNEXPECTED

    def test_engine_nonzero_exit_maps_rules_invalid_json(self, engine_bin: Path, tmp_path: Path) -> None:
        """绕过 RuleSet 校验，直接让真引擎读坏 JSON，验证 stderr -> 码的映射。"""
        target = tmp_path / "t.txt"
        target.write_text("的地得", encoding="utf-8")
        before = tmp_path / "before.json"
        before.write_text("{bad json", encoding="utf-8")
        after = tmp_path / "after.json"
        after.write_text('["x"]', encoding="utf-8")
        proc = subprocess.run(
            [str(engine_bin), str(target), str(before), str(after), "1"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.returncode == 1
        from fixtext.engine.errors import map_engine_stderr

        assert map_engine_stderr(proc.stderr) == EngineErrorCode.RULES_INVALID_JSON

    def test_error_response_is_json_serializable(self) -> None:
        resp = GoEngineClient("/tmp/none").run(EngineRequest(rules=_rules(["a"], ["b"]), input_data="x"))
        payload = json.dumps(resp.as_dict(), ensure_ascii=False)
        restored = json.loads(payload)
        assert restored["ok"] is False
        assert restored["error"]["code"] == EngineErrorCode.ENGINE_MISSING
        assert restored["error"]["remedy"]


class TestCorpusEquivalence:
    """20MB 级真实语料：集成层输出必须与 Go 直跑逐字节一致。"""

    @pytest.mark.slow
    def test_20mb_slice_matches_direct_run(self, go_client: GoEngineClient, t02_rules_dir: Path) -> None:
        project_root = Path(__file__).resolve().parent.parent
        corpus = project_root / "corpus" / "corpus_20mb_slice.txt"
        if not corpus.exists():
            pytest.skip("缺 corpus/corpus_20mb_slice.txt（先运行 scripts/build_corpus.py）")
        assert corpus.stat().st_size >= 20 * 1024 * 1024

        rs = RuleSet.from_files(t02_rules_dir / "before.json", t02_rules_dir / "after.json")
        from fixtext.engine.builder import default_engine_path

        # 直跑：引擎原地改写，故先复制
        direct_out = corpus.parent.parent / ".work" / "pytest_direct.txt"
        direct_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(corpus, direct_out)
        proc = subprocess.run(
            [
                str(default_engine_path()),
                str(direct_out),
                str(t02_rules_dir / "before.json"),
                str(t02_rules_dir / "after.json"),
                "2",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.returncode == 0, proc.stderr

        # 集成层：FILE -> FILE
        client_out = direct_out.with_name("pytest_client.txt")
        resp = go_client.run(
            EngineRequest(
                rules=rs,
                count=2,
                input_mode=InputMode.FILE,
                input_path=corpus,
                output_mode=OutputMode.FILE,
                output_path=client_out,
                timeout_s=600,
            )
        )
        assert resp.ok, resp.error.as_dict() if resp.error else ""

        import hashlib

        def sha(p: Path) -> str:
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()

        assert sha(client_out) == sha(direct_out), "20MB 样例：集成层与 Go 直跑输出必须逐字节一致"
        assert client_out.stat().st_size == direct_out.stat().st_size
        assert corpus.stat().st_size == 20971524, "20MB 切片应为 20,971,524 B（≥20MiB 且切在行边界）"
