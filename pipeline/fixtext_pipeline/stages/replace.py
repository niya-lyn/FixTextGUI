"""词库替换（含 M5-EX.1 分袋多轮）。

主轮仍落在 ``03_replace/``；预处理 / 严格为前置轮；注音在主轮之后写回
``after``，并把注音前正文存 ``after_raw`` 供 bookmap。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .. import bags, vocab_bridge
from ..config import dump_json
from ..state import sha256_file
from .base import Stage, StageError


class GoEngineUnavailableError(StageError):
    """Go 引擎不可用——降级路径触发判据（M4-T4.2）。"""


def _chain_input(cfg, round_id: str) -> Path:
    """按已启用轮次决定本轮输入文件。"""
    base = cfg.replace_input_text()
    if round_id == "preprocess":
        return base
    # 严格：若跑过预处理则读预处理产物
    if round_id == "strict":
        if cfg.enable_preprocess:
            return cfg.stage_dir("replace_preprocess") / "after" / f"{cfg.book_stem}.txt"
        return base
    # 主轮
    if round_id == "main":
        if cfg.enable_strict:
            return cfg.stage_dir("replace_strict") / "after" / f"{cfg.book_stem}.txt"
        if cfg.enable_preprocess:
            return cfg.stage_dir("replace_preprocess") / "after" / f"{cfg.book_stem}.txt"
        return base
    # 注音
    return cfg.replace_after()


class ReplaceStage(Stage):
    """主替换轮（``replace``）。子类改 ``round_id`` / ``name`` / ``title``。"""

    name = "replace"
    title = "词库替换（分袋主轮）"
    depends_on = ("layout",)  # 编排器侧以动态 stages 为准；跳过排版时 worker 不跑 layout
    round_id = "main"

    def outputs(self) -> list[Path]:
        if self.round_id == "main":
            return [
                self.cfg.replace_before(),
                self.cfg.replace_after(),
                self.cfg.stage_dir(self.name) / "replace_report.json",
            ]
        out = self.cfg.stage_dir(self.name)
        return [out / "after" / f"{self.cfg.book_stem}.txt", out / "replace_report.json"]

    def fingerprint(self) -> str:
        try:
            inp = _chain_input(self.cfg, self.round_id)
            inp_sha = sha256_file(inp) if inp.is_file() else "missing"
        except Exception:
            inp_sha = "missing"
        return self.fingerprint_of(
            f"round={self.round_id}",
            f"input={inp_sha}",
            f"bags={','.join(self.cfg.selected_bags)}",
            f"prep={self.cfg.enable_preprocess}",
            f"strict={self.cfg.enable_strict}",
            f"zhuyin={self.cfg.zhuyin_mode}",
            f"count={self.cfg.replace_count}",
            f"engine={self.cfg.engine}",
        )

    def _prepare_rules(self) -> dict[str, Any]:
        derived_root = Path(self.cfg.derived_rules_dir) / f"round_{self.round_id}"
        if self.round_id == "preprocess":
            return bags.write_round_rules(
                ["preprocess"], derived_root, include_custom=False
            )
        if self.round_id == "strict":
            return bags.write_round_rules(
                ["strict"], derived_root, include_custom=False
            )
        if self.round_id == "zhuyin":
            return bags.write_round_rules(
                ["zhuyin"], derived_root, include_custom=False
            )
        # main
        ids = bags.main_bag_ids(self.cfg.selected_bags)
        include_custom = "custom" in self.cfg.selected_bags
        return bags.write_round_rules(
            ids,
            derived_root,
            custom_path=self.cfg.custom_vocab_path if include_custom else None,
            include_custom=include_custom,
        )

    def _replace_count(self) -> int:
        if self.round_id == "zhuyin":
            return 1
        return int(self.cfg.replace_count)

    def run(self) -> dict[str, Any]:
        from fixtext.engine import EngineRequest, InputMode, OutputMode, RuleSet

        engine_path = self.cfg.engine_path
        if self.cfg.engine == "python":
            from fixtext.engine.py_engine import PyGreedyEngineClient

            engine_kind = "python"
        else:
            from fixtext.engine import GoEngineClient

            engine_kind = "go"
            if not engine_path.exists():
                raise GoEngineUnavailableError(
                    f"Go 引擎不存在：{engine_path.name}"
                    "。可在设置里改用 Python 引擎（较慢）后重试。"
                )
            if not engine_path.is_file():
                raise GoEngineUnavailableError(
                    f"Go 引擎不是普通文件：{engine_path.name}"
                    "。可在设置里改用 Python 引擎（较慢）后重试。"
                )
            import os

            if os.name != "nt" and not os.access(engine_path, os.X_OK):
                engine_path.chmod(engine_path.stat().st_mode | 0o111)
                self.log.log(f"[replace] 已补执行位：{engine_path}")

        derived = self._prepare_rules()
        rule_before = Path(str(derived["before_path"]))
        rule_after = Path(str(derived["after_path"]))
        if not (rule_before.is_file() and rule_after.is_file()):
            raise StageError("替换规则未就绪（分袋派生文件缺失）")
        self.log.log(
            f"[replace/{self.round_id}] 规则 {derived.get('total_rules')} 条 "
            f"（袋 {derived.get('bag_ids')}）"
        )

        rules = RuleSet.from_files(rule_before, rule_after)
        count = self._replace_count()
        self.log.log(
            f"[replace/{self.round_id}] 载入 {len(rules)} 条，趟数 {count}"
        )

        input_path = _chain_input(self.cfg, self.round_id)
        if not input_path.is_file():
            raise StageError(f"替换输入不存在：{input_path}")

        out_dir = self.ensure_dir(self.cfg.stage_dir(self.name))
        before_dir = self.ensure_dir(out_dir / "before")
        after_dir = self.ensure_dir(out_dir / "after")
        before_path = before_dir / f"{self.cfg.book_stem}.txt"
        after_path = after_dir / f"{self.cfg.book_stem}.txt"

        # 主轮：权威 before 快照；其它轮也落 before 便于排查
        shutil.copyfile(input_path, before_path)
        if self.round_id == "zhuyin":
            # bookmap 用注音前正文（主轮 after），与注音后 after 分离
            raw_dir = self.ensure_dir(self.cfg.stage_dir("replace") / "after_raw")
            shutil.copyfile(input_path, raw_dir / f"{self.cfg.book_stem}.txt")

        request = EngineRequest(
            rules=rules,
            count=count,
            input_mode=InputMode.FILE,
            input_path=input_path,
            output_mode=OutputMode.FILE,
            output_path=after_path,
            encoding="utf-8",
            timeout_s=self.cfg.engine_timeout_s,
        )

        if engine_kind == "python":
            client = PyGreedyEngineClient(default_timeout_s=self.cfg.engine_timeout_s)
            self.log.log(f"[replace/{self.round_id}] Python 引擎")
        else:
            client = GoEngineClient(engine_path, default_timeout_s=self.cfg.engine_timeout_s)
            self.log.log(f"[replace/{self.round_id}] Go 引擎：{engine_path.name}")
        response = client.run(request)
        if not response.ok:
            assert response.error is not None
            detail = response.error.as_dict()
            self.log.log(f"[replace][FAIL] {detail['code']} {detail['message']}")
            if engine_kind == "go" and detail["code"] in ("E1001", "E1002"):
                raise GoEngineUnavailableError(
                    f"Go 引擎替换失败：{detail['code']} {detail['message']}；"
                    f"处置建议：{detail['remedy']}"
                )
            raise StageError(
                f"{'Go' if engine_kind == 'go' else 'Python'} 引擎替换失败："
                f"{detail['code']} {detail['message']}；处置建议：{detail['remedy']}"
            )

        result = response.result
        assert result is not None
        zhuyin_report: dict[str, Any] | None = None
        if self.round_id == "zhuyin":
            text = after_path.read_text(encoding="utf-8")
            from .. import zhuyin_post

            mode = self.cfg.zhuyin_mode if self.cfg.zhuyin_mode != "off" else "0"
            text2, zhuyin_report = zhuyin_post.apply(text, mode)
            after_path.write_text(text2, encoding="utf-8", newline="\n")
            # 同步到主轮 after，供 quote/restore
            main_after = self.cfg.replace_after()
            main_after.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(after_path, main_after)

        if self.round_id == "main":
            integrity = self._check_boundaries(after_path)
            if not integrity["ok"]:
                raise StageError(
                    "替换后边界完整性复检失败："
                    + "；".join(integrity["problems"][:5])
                )
            # 无注音时 after_raw = after，方便 bookmap 统一读
            if str(self.cfg.zhuyin_mode) in ("", "off", "None"):
                raw_dir = self.ensure_dir(self.cfg.stage_dir("replace") / "after_raw")
                shutil.copyfile(after_path, raw_dir / f"{self.cfg.book_stem}.txt")
        else:
            integrity = {"ok": True, "chapters": 0, "problems": []}

        self.log.log(
            f"[replace/{self.round_id}] 完成：字符 {result.chars_in} → {result.chars_out}，"
            f"{result.elapsed_s:.2f}s"
        )
        report = {
            "round": self.round_id,
            "derived_rules": {
                k: derived.get(k)
                for k in (
                    "bag_ids", "base_rules", "custom_input", "custom_applied",
                    "total_rules", "custom_error", "include_custom",
                )
            },
            "engine": engine_kind,
            "engine_path": str(engine_path) if engine_kind == "go" else result.engine_path,
            "engine_stdout": result.engine_stdout,
            "rules": result.rules,
            "unique_rules": result.unique_rules,
            "count": result.count,
            "chars_in": result.chars_in,
            "chars_out": result.chars_out,
            "bytes_in": result.bytes_in,
            "bytes_out": result.bytes_out,
            "sha256_in": result.sha256_in,
            "sha256_out": result.sha256_out,
            "changed": result.changed,
            "engine_elapsed_s": round(result.elapsed_s, 3),
            "before_path": str(before_path),
            "after_path": str(
                self.cfg.replace_after() if self.round_id == "zhuyin" else after_path
            ),
            "before_sha256": sha256_file(before_path),
            "after_sha256": sha256_file(after_path),
            "boundary_check": integrity,
            "zhuyin": zhuyin_report,
        }
        dump_json(out_dir / "replace_report.json", report)
        return report

    def _check_boundaries(self, text_path: Path) -> dict[str, Any]:
        from epubtext.bundle import Ledger, split_bundle

        problems: list[str] = []
        chunks: list[Any] = []
        if self.cfg.skip_layout:
            ledger_path = self.cfg.merged_ledger()
        else:
            ledger_path = self.cfg.stage_dir("layout") / f"{self.cfg.book_stem}.bundle.json"
        ledger = Ledger.load(ledger_path)
        try:
            text = text_path.read_text(encoding="utf-8")
            chunks = split_bundle(text, ledger, strict=True)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"切分失败：{exc.__class__.__name__}: {exc}")

        if not problems and len(chunks) != len(ledger.chapters):
            problems.append(f"切出 {len(chunks)} 章，账本 {len(ledger.chapters)} 章")
        return {
            "ok": not problems,
            "chapters": len(chunks),
            "problems": problems,
        }


class ReplacePreprocessStage(ReplaceStage):
    name = "replace_preprocess"
    title = "预处理替换"
    round_id = "preprocess"
    depends_on = ("merge",)


class ReplaceStrictStage(ReplaceStage):
    name = "replace_strict"
    title = "严格替换"
    round_id = "strict"
    depends_on = ("merge",)


class ReplaceZhuyinStage(ReplaceStage):
    name = "replace_zhuyin"
    title = "生僻字注音"
    round_id = "zhuyin"
    depends_on = ("replace",)
