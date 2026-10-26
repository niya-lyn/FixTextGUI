"""协议对象与错误码表的静态单测（不起子进程）。"""

from __future__ import annotations

import json

import pytest

from fixtext.engine.errors import EngineError, EngineErrorCode, error_catalog_table, map_engine_stderr
from fixtext.engine.protocol import (
    ENGINE_SUCCESS_PREFIX,
    PROTOCOL_VERSION,
    EngineRequest,
    EngineResponse,
    InputMode,
    OutputMode,
    RuleSet,
    parse_engine_stdout,
    request_to_dict,
)


def test_protocol_version_is_stable() -> None:
    assert PROTOCOL_VERSION == "fixtext-engine/1"


def test_success_prefix_matches_go_source() -> None:
    """摘要行前缀必须与 Go 源码 fmt.Printf 一致，否则 parse 会静默失配。"""
    assert ENGINE_SUCCESS_PREFIX == "✓ 替换完成，共执行 "


class TestRuleSet:
    def test_valid_rules(self) -> None:
        rs = RuleSet(["a"], ["b"])
        assert len(rs) == 1
        assert rs.unique_before == 1

    def test_length_mismatch(self) -> None:
        with pytest.raises(EngineError) as ei:
            RuleSet(["a", "b"], ["c"])
        assert ei.value.code == EngineErrorCode.RULES_LENGTH_MISMATCH

    def test_empty(self) -> None:
        with pytest.raises(EngineError) as ei:
            RuleSet([], [])
        assert ei.value.code == EngineErrorCode.RULES_EMPTY

    def test_non_list(self) -> None:
        with pytest.raises(EngineError) as ei:
            RuleSet("abc", "def")  # type: ignore[arg-type]
        assert ei.value.code == EngineErrorCode.RULES_INVALID_JSON

    def test_from_files_roundtrip(self, tmp_path) -> None:
        before = ["的的地", "ＡＢ"]
        after = ["的地得", "AB"]
        (tmp_path / "before.json").write_text(json.dumps(before, ensure_ascii=False), encoding="utf-8")
        (tmp_path / "after.json").write_text(json.dumps(after, ensure_ascii=False), encoding="utf-8")
        rs = RuleSet.from_files(tmp_path / "before.json", tmp_path / "after.json")
        assert rs.before == before
        assert rs.after == after
        assert rs.source == "before.json+after.json"

    def test_from_files_missing(self, tmp_path) -> None:
        (tmp_path / "after.json").write_text("[]", encoding="utf-8")
        with pytest.raises(EngineError) as ei:
            RuleSet.from_files(tmp_path / "before.json", tmp_path / "after.json")
        assert ei.value.code == EngineErrorCode.RULES_MISSING

    def test_from_files_object_array_rejected(self, tmp_path) -> None:
        (tmp_path / "before.json").write_text('[{"a": 1}]', encoding="utf-8")
        (tmp_path / "after.json").write_text('["x"]', encoding="utf-8")
        with pytest.raises(EngineError) as ei:
            RuleSet.from_files(tmp_path / "before.json", tmp_path / "after.json")
        assert ei.value.code == EngineErrorCode.RULES_INVALID_JSON

    def test_from_files_bad_json(self, tmp_path) -> None:
        (tmp_path / "before.json").write_text("{not json", encoding="utf-8")
        (tmp_path / "after.json").write_text("[]", encoding="utf-8")
        with pytest.raises(EngineError) as ei:
            RuleSet.from_files(tmp_path / "before.json", tmp_path / "after.json")
        assert ei.value.code == EngineErrorCode.RULES_INVALID_JSON


class TestEngineRequest:
    def test_count_must_be_positive_int(self) -> None:
        rs = RuleSet(["a"], ["b"])
        for bad in (0, -1, "2", 2.5, True):
            with pytest.raises(EngineError) as ei:
                EngineRequest(rules=rs, input_data="x", count=bad).validate()  # type: ignore[arg-type]
            assert ei.value.code == EngineErrorCode.ARGUMENT_INVALID

    def test_memory_input_requires_data(self) -> None:
        rs = RuleSet(["a"], ["b"])
        with pytest.raises(EngineError) as ei:
            EngineRequest(rules=rs, input_data=None).validate()
        assert ei.value.code == EngineErrorCode.ARGUMENT_INVALID

    def test_file_input_requires_path(self) -> None:
        rs = RuleSet(["a"], ["b"])
        with pytest.raises(EngineError) as ei:
            EngineRequest(rules=rs, input_mode=InputMode.FILE).validate()
        assert ei.value.code == EngineErrorCode.ARGUMENT_INVALID

    def test_in_place_requires_file_input(self) -> None:
        rs = RuleSet(["a"], ["b"])
        with pytest.raises(EngineError) as ei:
            EngineRequest(rules=rs, input_data="x", output_mode=OutputMode.IN_PLACE).validate()
        assert ei.value.code == EngineErrorCode.ARGUMENT_INVALID

    def test_unsupported_protocol(self) -> None:
        with pytest.raises(EngineError) as ei:
            EngineRequest(rules=RuleSet(["a"], ["b"]), input_data="x", protocol="v9").validate()
        assert ei.value.code == EngineErrorCode.ARGUMENT_INVALID

    def test_audit_dict_has_digest_not_body(self) -> None:
        rs = RuleSet(["a"], ["b"])
        info = request_to_dict(EngineRequest(rules=rs, input_data="中文"))
        assert info["input_bytes"] == len("中文".encode())
        assert len(info["input_sha256"]) == 64
        assert "input_data" not in info


class TestResponseShape:
    def test_ok_requires_result(self) -> None:
        with pytest.raises(ValueError):
            EngineResponse(ok=True)

    def test_fail_requires_error(self) -> None:
        with pytest.raises(ValueError):
            EngineResponse(ok=False)

    def test_failure_serializes(self) -> None:
        resp = EngineResponse.failure(EngineError(EngineErrorCode.ENGINE_TIMEOUT, "超时", {"s": 1}))
        data = resp.as_dict()
        assert data["ok"] is False
        assert data["error"]["code"] == EngineErrorCode.ENGINE_TIMEOUT
        assert data["error"]["name"] == "ENGINE_TIMEOUT"


class TestParseStdout:
    def test_parses_reported_count(self) -> None:
        assert parse_engine_stdout("✓ 替换完成，共执行 2 次替换\n", 2) == 2

    def test_missing_line_is_protocol_violation(self) -> None:
        with pytest.raises(EngineError) as ei:
            parse_engine_stdout("done\n", 2)
        assert ei.value.code == EngineErrorCode.ENGINE_OUTPUT_UNEXPECTED

    def test_count_mismatch(self) -> None:
        with pytest.raises(EngineError) as ei:
            parse_engine_stdout("✓ 替换完成，共执行 3 次替换\n", 2)
        assert ei.value.code == EngineErrorCode.ENGINE_OUTPUT_UNEXPECTED


class TestErrorCatalog:
    def test_catalog_covers_all_declared_codes(self) -> None:
        declared = {
            value
            for name, value in vars(EngineErrorCode).items()
            if not name.startswith("_") and isinstance(value, str)
        }
        catalog = {row["code"] for row in error_catalog_table()}
        assert declared == catalog, f"未登记到目录的码：{declared - catalog}"

    def test_codes_are_unique(self) -> None:
        rows = error_catalog_table()
        codes = [r["code"] for r in rows]
        assert len(codes) == len(set(codes))

    def test_stderr_mapping(self) -> None:
        cases = {
            "错误: 规则数量不匹配: 替换前=2, 替换后=1\n": EngineErrorCode.RULES_LENGTH_MISMATCH,
            "错误: 替换规则为空\n": EngineErrorCode.RULES_EMPTY,
            "错误: 读取替换前规则: JSON 解析失败": EngineErrorCode.RULES_INVALID_JSON,
            "错误: 读取文件失败: open x: no such file\n": EngineErrorCode.INPUT_UNREADABLE,
            "错误: 替换次数必须为正整数，当前: 0\n": EngineErrorCode.ARGUMENT_INVALID,
            "错误: 写入文件失败: permission denied\n": EngineErrorCode.OUTPUT_WRITE_FAILED,
            "错误: 某种全新失败\n": EngineErrorCode.ENGINE_FAILED,
        }
        for stderr, expected in cases.items():
            assert map_engine_stderr(stderr) == expected, stderr
