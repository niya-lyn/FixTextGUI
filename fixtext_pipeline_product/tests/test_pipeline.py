"""编排器核心逻辑的单元测试。

覆盖：配置校验、状态机读写、指纹与产物存在性判定、断点恢复的三条件规则、
CLI 参数解析。这些都是「中断后能安全恢复」的关键，必须有测试锁住。

跑法::

    python -m pytest product/tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PRODUCT_ROOT = Path(__file__).resolve().parent.parent
if str(PRODUCT_ROOT) not in sys.path:
    sys.path.insert(0, str(PRODUCT_ROOT))

from fixtext_pipeline.cli import build_parser, main, parse_layout_overrides  # noqa: E402
from fixtext_pipeline.config import STAGE_META, PipelineConfig  # noqa: E402
from fixtext_pipeline.state import (  # noqa: E402
    StateStore,
    fingerprint,
    outputs_exist,
    sha256_file,
)


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #


@pytest.fixture()
def cfg(tmp_path: Path) -> PipelineConfig:
    """造一份最小可用的配置（不需要真实引擎文件）。"""
    (tmp_path / "book.epub").write_bytes(b"PK\x03\x04epub")
    (tmp_path / "before.json").write_text("{}", encoding="utf-8")
    (tmp_path / "after.json").write_text("{}", encoding="utf-8")
    (tmp_path / "engine").write_bytes(b"\x7fELF")
    return PipelineConfig(
        epub=tmp_path / "book.epub",
        workdir=tmp_path / "work",
        rules_before=tmp_path / "before.json",
        rules_after=tmp_path / "after.json",
        engine_path=tmp_path / "engine",
    )


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #


class TestPipelineConfig:
    def test_阶段顺序与目录映射一致(self):
        assert list(STAGE_META) == ["merge", "layout", "replace", "quote", "bookmap", "restore"]
        assert STAGE_META["merge"][0] == "01_merge"
        assert STAGE_META["restore"][0] == "06_restore"

    def test_未知排版档案被拒(self, tmp_path: Path):
        with pytest.raises(ValueError, match="未知排版档案"):
            PipelineConfig(
                epub=tmp_path / "a.epub",
                workdir=tmp_path / "w",
                rules_before=tmp_path / "b.json",
                rules_after=tmp_path / "a.json",
                engine_path=tmp_path / "e",
                layout_profile="不存在的档案",
            )

    def test_替换趟数必须为正(self, tmp_path: Path):
        with pytest.raises(ValueError, match="replace_count"):
            PipelineConfig(
                epub=tmp_path / "a.epub",
                workdir=tmp_path / "w",
                rules_before=tmp_path / "b.json",
                rules_after=tmp_path / "a.json",
                engine_path=tmp_path / "e",
                replace_count=0,
            )

    def test_路径被展开为绝对路径(self, cfg: PipelineConfig):
        assert cfg.epub.is_absolute()
        assert cfg.workdir.is_absolute()

    def test_排版覆盖项生效(self, cfg: PipelineConfig):
        cfg.layout_overrides = {"normalize_punctuations": False}
        assert cfg.layout_options["normalize_punctuations"] is False
        # 没被覆盖的项保持档案默认值
        assert cfg.layout_options["is_txt_file"] is False

    def test_配置可序列化并能还原(self, cfg: PipelineConfig):
        raw = json.loads(json.dumps(cfg.to_dict()))
        restored = PipelineConfig.from_state(raw)
        assert restored.epub == cfg.epub
        assert restored.replace_count == cfg.replace_count
        assert restored.layout_profile == cfg.layout_profile
        assert restored.bookmap_add_current_time == cfg.bookmap_add_current_time

    def test_各阶段产物路径落在对应阶段目录(self, cfg: PipelineConfig):
        assert cfg.merged_text().parent.name == "01_merge"
        assert cfg.layout_text().parent.name == "02_layout"
        assert cfg.replace_after().parent.name == "after"
        assert cfg.quote_report_txt().parent.name == "04_quote"
        assert cfg.bookmap_file().parent.name == "书籍专有替换词库"
        assert cfg.restored_epub().parent.name == "06_restore"


# --------------------------------------------------------------------------- #
# 状态机
# --------------------------------------------------------------------------- #


class TestStateStore:
    def test_空目录也能加载(self, tmp_path: Path):
        store = StateStore(tmp_path / "state.json").load()
        assert store.stage("merge").status == "pending"
        assert store.config == {}

    def test_状态可写入并读回(self, tmp_path: Path):
        path = tmp_path / "state.json"
        store = StateStore(path)
        store.mark("merge", status="done", elapsed_s=1.5, outputs=["a", "b"])
        store.save()

        again = StateStore(path).load()
        stage = again.stage("merge")
        assert stage.status == "done"
        assert stage.elapsed_s == 1.5
        assert stage.outputs == ["a", "b"]

    def test_状态文件损坏时按无状态处理(self, tmp_path: Path):
        path = tmp_path / "state.json"
        path.write_text("{这不是 JSON", encoding="utf-8")
        store = StateStore(path).load()
        assert store.stage("merge").status == "pending"

    def test_配置被持久化(self, tmp_path: Path):
        path = tmp_path / "state.json"
        store = StateStore(path)
        store.set_config({"replace_count": 2})
        store.save()
        assert StateStore(path).load().config["replace_count"] == 2


class TestOutputsExist:
    def test_全部存在才为真(self, tmp_path: Path):
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.write_text("x", encoding="utf-8")
        assert outputs_exist([str(a)]) is True
        assert outputs_exist([str(a), str(b)]) is False
        assert outputs_exist([]) is True


class TestFingerprint:
    def test_相同输入指纹一致(self):
        assert fingerprint(["a", "b"]) == fingerprint(["a", "b"])

    def test_任一部分变化指纹即变(self):
        assert fingerprint(["a", "b"]) != fingerprint(["a", "c"])

    def test_分隔符防止拼接歧义(self):
        assert fingerprint(["ab", "c"]) != fingerprint(["a", "bc"])

    def test_文件指纹随内容变化(self, tmp_path: Path):
        f = tmp_path / "x"
        f.write_text("one", encoding="utf-8")
        first = sha256_file(f)
        f.write_text("two", encoding="utf-8")
        assert sha256_file(f) != first


# --------------------------------------------------------------------------- #
# 断点恢复的三条件
# --------------------------------------------------------------------------- #


class TestResumeRules:
    """恢复判定：状态 done + 指纹一致 + 产物齐全，三条缺一不可。"""

    @staticmethod
    def _should_skip(cfg, store, name, fp):
        from fixtext_pipeline.runner import _should_skip

        return _should_skip(cfg, store, name, fp)

    def test_三条全中才跳过(self, cfg: PipelineConfig, tmp_path: Path):
        store = StateStore(cfg.paths.state_file)
        out = tmp_path / "out.txt"
        out.write_text("x", encoding="utf-8")
        store.mark("merge", status="done", fingerprint="fp1", outputs=[str(out)])

        skip, reason = self._should_skip(cfg, store, "merge", "fp1")
        assert skip is True
        assert "指纹一致" in reason

    def test_状态非done不跳过(self, cfg: PipelineConfig, tmp_path: Path):
        store = StateStore(cfg.paths.state_file)
        out = tmp_path / "out.txt"
        out.write_text("x", encoding="utf-8")
        store.mark("merge", status="failed", fingerprint="fp1", outputs=[str(out)])

        skip, reason = self._should_skip(cfg, store, "merge", "fp1")
        assert skip is False
        assert "failed" in reason

    def test_指纹变了不跳过(self, cfg: PipelineConfig, tmp_path: Path):
        store = StateStore(cfg.paths.state_file)
        out = tmp_path / "out.txt"
        out.write_text("x", encoding="utf-8")
        store.mark("merge", status="done", fingerprint="fp1", outputs=[str(out)])

        skip, reason = self._should_skip(cfg, store, "merge", "fp2")
        assert skip is False
        assert "指纹" in reason

    def test_产物缺失不跳过(self, cfg: PipelineConfig):
        store = StateStore(cfg.paths.state_file)
        store.mark("merge", status="done", fingerprint="fp1", outputs=["/不存在的/路径.txt"])

        skip, reason = self._should_skip(cfg, store, "merge", "fp1")
        assert skip is False
        assert "产物" in reason

    def test_关闭resume时不跳过(self, cfg: PipelineConfig, tmp_path: Path):
        cfg.resume = False
        store = StateStore(cfg.paths.state_file)
        out = tmp_path / "out.txt"
        out.write_text("x", encoding="utf-8")
        store.mark("merge", status="done", fingerprint="fp1", outputs=[str(out)])

        skip, reason = self._should_skip(cfg, store, "merge", "fp1")
        assert skip is False
        assert "resume" in reason

    def test_force时强制重跑(self, cfg: PipelineConfig, tmp_path: Path):
        cfg.force = True
        store = StateStore(cfg.paths.state_file)
        out = tmp_path / "out.txt"
        out.write_text("x", encoding="utf-8")
        store.mark("merge", status="done", fingerprint="fp1", outputs=[str(out)])

        skip, reason = self._should_skip(cfg, store, "merge", "fp1")
        assert skip is False
        assert "force" in reason


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class TestCli:
    def test_默认子命令是run(self):
        from fixtext_pipeline.cli import normalize_argv

        assert normalize_argv(["--epub", "a.epub", "--workdir", "w"]) == [
            "run", "--epub", "a.epub", "--workdir", "w",
        ]
        assert normalize_argv(["doctor"]) == ["doctor"]
        assert normalize_argv([]) == ["run"]

    def test_显式子命令不被改写(self):
        from fixtext_pipeline.cli import normalize_argv

        assert normalize_argv(["report", "--workdir", "w"]) == ["report", "--workdir", "w"]

    def test_run子命令可显式指定(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--epub", "a.epub", "--workdir", "w"])
        assert args.command == "run"
        assert args.layout_profile == "html-safe"
        assert args.replace_count == 2

    def test_排版覆盖解析为JSON类型(self):
        parsed = parse_layout_overrides(
            ["normalize_punctuations=false", "quotation_type=2", "new_line_type=\\n"]
        )
        assert parsed["normalize_punctuations"] is False
        assert parsed["quotation_type"] == 2
        assert parsed["new_line_type"] == "\\n"

    def test_排版覆盖格式错误被拒(self):
        with pytest.raises(SystemExit, match="key=value"):
            parse_layout_overrides(["没有等号"])

    def test_未知排版选项被拒(self):
        with pytest.raises(SystemExit, match="未知的排版选项"):
            parse_layout_overrides(["不存在的选项=1"])

    def test_缺少必需参数时报错(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run"])

    def test_doctor在缺输入时返回非零(self, tmp_path: Path, capsys):
        code = main(["doctor", "--epub", str(tmp_path / "没有.epub")])
        assert code == 2

    def test_report在缺报告时返回非零(self, tmp_path: Path):
        assert main(["report", "--workdir", str(tmp_path)]) == 2

    def test_unknown阶段被拒(self, tmp_path: Path):
        parser = build_parser()
        args = parser.parse_args(
            ["run", "--epub", "a.epub", "--workdir", "w", "--stages", "merge,不存在的"]
        )
        # main 里做阶段校验，走 main 路径
        code = main(
            [
                "run",
                "--epub", str(tmp_path / "a.epub"),
                "--workdir", str(tmp_path / "w"),
                "--stages", "merge,不存在的",
            ]
        )
        assert code == 2
