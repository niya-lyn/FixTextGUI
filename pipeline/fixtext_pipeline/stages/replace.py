"""阶段 3：词库替换（T0.3 Go 引擎子进程协议 + T0.2 词库）。

**本阶段不实现任何字符串替换逻辑**：规则集、请求、进程调度、错误归类全部走
T0.3 的 ``fixtext.engine`` 集成层——

    RuleSet.from_files(before.json, after.json)   # 规则
    EngineRequest(count=2, input_mode=FILE, output_mode=FILE)
    GoEngineClient.run(request)                    # 真正起子进程

替换趟数 ``count`` 默认 2，与上游 ``TextFixer`` 的 ``$replaceCount = 2`` 一致。

自定义词生效（M3-T3.7）
-----------------------
**不直接读随包发布的词库原件**：运行前先用
:mod:`fixtext_pipeline.vocab_bridge` 把「当前生效的通用词库 + 我的词库里的
自定义词」合成为派生的 ``before.json`` / ``after.json``（落在用户区，
出厂文件一个字节都不动），本阶段读的是这份派生文件。于是用户在词库里
新增 / 合并 / 删除的词，下一次校正真正被引擎用上。

派生文件的两份 sha **进入阶段指纹**：规则一变指纹就变，断点恢复不会因为
「状态还是 done」而误判缓存命中、拿旧正文当新结果。

替换完成后做一次 **边界完整性复检**：用账本严格切分替换后的 TXT，
标记一旦被词条打坏，切分就会失败，阶段直接报错而不是把坏文本往下传。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..config import dump_json
from ..state import sha256_file
from .. import vocab_bridge
from .base import Stage, StageError


class GoEngineUnavailableError(StageError):
    """Go 引擎不可用（缺失 / 无法执行 / 启动失败）——降级路径的触发判据。

    M4-T4.2：worker 捕获本异常后向界面发 ``engine_failed``，由用户决定
    是否改走 Python 引擎完成本次校正；CLI / 编排器路径则按普通阶段失败
    报错（明确报错，不硬跑）。
    """


class ReplaceStage(Stage):
    name = "replace"
    title = "词库替换（T0.3 引擎双轨 + T0.2 词库）"
    depends_on = ("layout",)

    def outputs(self) -> list[Path]:
        return [
            self.cfg.replace_before(),
            self.cfg.replace_after(),
            self.cfg.stage_dir(self.name) / "replace_report.json",
        ]

    # ---- 派生规则（M3-T3.7）----

    def derived_rules(self) -> dict:
        """生成（或复用）本次运行要用的派生规则，返回桥接摘要。

        派生文件落在用户区 ``workspace/vocab/derived_rules/``，**不碰**
        ``data/rules/*.json``。生成失败按失败处理：宁可这里报错，也不让
        用户的自定义词在一次"看起来成功"的运行里被静默丢掉。
        """
        try:
            return vocab_bridge.write_derived_rules(
                self.cfg.rules_before,
                self.cfg.rules_after,
                self.cfg.custom_vocab_path,
                self.cfg.derived_rules_dir,
            )
        except vocab_bridge.DerivedRulesError as exc:
            raise StageError(f"替换规则无法就绪：{exc}") from exc

    def active_rules_paths(self) -> tuple[Path | None, Path | None]:
        """当前生效的规则文件：有派生文件就用派生文件，否则退回随包原件。

        ``fingerprint()`` 不能抛异常（编排器把它当"是否跳过"的判据，抛了会
        让整段流程失败），所以这里读不到派生摘要时退化为 None，指纹退回
        用原件 sha —— 真的缺文件时 ``run()`` 会自己报错。
        """
        try:
            meta = self.derived_rules()
        except StageError:
            return None, None
        before = Path(str(meta.get("before_path") or ""))
        after = Path(str(meta.get("after_path") or ""))
        if before.is_file() and after.is_file():
            return before, after
        return None, None

    def fingerprint(self) -> str:
        before, after = self.active_rules_paths()
        # 规则一律按**实际生效的那一份**取 sha：自定义词一改，派生文件就变，
        # 指纹随之变，断点恢复才不会拿旧正文当新结果。
        rules_sha = sha256_file(before) if before else sha256_file(self.cfg.rules_before)
        rules_after_sha = sha256_file(after) if after else sha256_file(self.cfg.rules_after)
        return self.fingerprint_of(
            f"input={sha256_file(self.cfg.layout_text())}",
            f"rules={rules_sha}",
            f"rules_after={rules_after_sha}",
            f"count={self.cfg.replace_count}",
            f"engine={self.cfg.engine}",
            f"engine_bin={sha256_file(self.cfg.engine_path) if self.cfg.engine_path.exists() else 'missing'}",
        )

    def run(self) -> dict[str, Any]:
        from fixtext.engine import EngineRequest, InputMode, OutputMode, RuleSet

        engine_path = self.cfg.engine_path
        if self.cfg.engine == "python":
            from fixtext.engine.py_engine import PyGreedyEngineClient

            engine_kind = "python"
        else:
            from fixtext.engine import GoEngineClient

            engine_kind = "go"
            # Go 路径的引擎可用性检查：不可用属「降级触发条件」，抛类型化异常
            # 让 worker / 编排器分流（M4-T4.2 §3.3），不当成普通替换失败。
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
                # T0.3 产物解包后不带执行位，这里补上（builder.chmod_executable 同款动作）
                engine_path.chmod(engine_path.stat().st_mode | 0o111)
                self.log.log(f"[replace] 已补执行位：{engine_path}")

        # 自定义词生效：运行前合成派生规则，本阶段只读派生文件
        derived = self.derived_rules()
        rule_before = Path(str(derived["before_path"]))
        rule_after = Path(str(derived["after_path"]))
        if not (rule_before.is_file() and rule_after.is_file()):
            raise StageError("替换规则未就绪（派生规则文件缺失）")
        self.log.log(
            f"[replace] 派生规则：通用 {derived.get('base_rules')} 条 + "
            f"自定义生效 {derived.get('custom_applied')} 条 "
            f"= {derived.get('total_rules')} 条"
            + (f"（复用上次结果）" if derived.get("reused") else "")
        )
        if derived.get("custom_error"):
            self.log.log(f"[replace][WARN] {derived['custom_error']}")
        if derived.get("skipped_empty") or derived.get("skipped_identity") \
                or derived.get("skipped_duplicate"):
            self.log.log(
                "[replace][WARN] 有自定义词未参与替换："
                f"空值 {len(derived.get('skipped_empty') or [])} / "
                f"原词等于替换值 {len(derived.get('skipped_identity') or [])} / "
                f"同原词重复 {len(derived.get('skipped_duplicate') or [])}"
            )

        rules = RuleSet.from_files(rule_before, rule_after)
        self.log.log(
            f"[replace] 规则载入完成：{len(rules)} 条（去重前 {rules.unique_before}），"
            f"替换趟数 {self.cfg.replace_count}"
        )

        out_dir = self.ensure_dir(self.cfg.stage_dir(self.name))
        before_dir = self.ensure_dir(out_dir / "before")
        after_dir = self.ensure_dir(out_dir / "after")
        before_path = before_dir / f"{self.cfg.book_stem}.txt"
        after_path = after_dir / f"{self.cfg.book_stem}.txt"

        request = EngineRequest(
            rules=rules,
            count=self.cfg.replace_count,
            input_mode=InputMode.FILE,
            input_path=self.cfg.layout_text(),
            output_mode=OutputMode.FILE,
            output_path=after_path,
            encoding="utf-8",
            timeout_s=self.cfg.engine_timeout_s,
        )

        if engine_kind == "python":
            client = PyGreedyEngineClient(default_timeout_s=self.cfg.engine_timeout_s)
            self.log.log("[replace] 调起 Python 替换引擎（pyahocorasick 贪心）")
        else:
            client = GoEngineClient(engine_path, default_timeout_s=self.cfg.engine_timeout_s)
            self.log.log(f"[replace] 调起 Go 引擎：{engine_path.name}")
        response = client.run(request)
        if not response.ok:
            assert response.error is not None
            detail = response.error.as_dict()
            self.log.log(f"[replace][FAIL] {detail['code']} {detail['message']}")
            if engine_kind == "go" and detail["code"] in ("E1001", "E1002"):
                # 启动层面失败（含杀软隔离后二进制不可执行）：同降级触发条件
                raise GoEngineUnavailableError(
                    f"Go 引擎替换失败：{detail['code']} {detail['message']}；"
                    f"处置建议：{detail['remedy']}"
                )
            raise StageError(
                f"Go 引擎替换失败：{detail['code']} {detail['message']}；"
                f"处置建议：{detail['remedy']}"
                if engine_kind == "go" else
                f"Python 引擎替换失败：{detail['code']} {detail['message']}；"
                f"处置建议：{detail['remedy']}"
            )

        result = response.result
        assert result is not None
        shutil.copyfile(self.cfg.layout_text(), before_path)

        self.log.log(
            f"[replace] 引擎完成（{engine_kind}）：{result.engine_stdout}；"
            f"字符 {result.chars_in} → {result.chars_out}，"
            f"耗时 {result.elapsed_s:.2f}s"
        )

        integrity = self._check_boundaries(after_path)
        if not integrity["ok"]:
            raise StageError(
                "替换后边界完整性复检失败："
                + "；".join(integrity["problems"][:5])
            )

        report = {
            # 派生规则摘要（M3-T3.7）：自定义词是否真的参与了这次替换
            "derived_rules": {
                k: derived.get(k) for k in (
                    "compose_key", "base_rules", "custom_input", "custom_applied",
                    "total_rules", "reused", "custom_error", "skipped_empty",
                    "skipped_identity", "skipped_duplicate", "short_custom",
                    "applied_words", "derived_before_sha256",
                    "derived_after_sha256", "base_before_sha256",
                    "base_after_sha256", "custom_sha256",
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
            "after_path": str(after_path),
            "before_sha256": sha256_file(before_path),
            "after_sha256": sha256_file(after_path),
            "boundary_check": integrity,
        }
        dump_json(out_dir / "replace_report.json", report)
        return report

    def _check_boundaries(self, text_path: Path) -> dict[str, Any]:
        """用账本严格切分替换后的 TXT，确认边界标记没被打坏。"""
        from epubtext.bundle import Ledger, split_bundle

        problems: list[str] = []
        chunks: list[Any] = []
        ledger = Ledger.load(self.cfg.stage_dir("layout") / f"{self.cfg.book_stem}.bundle.json")
        try:
            text = text_path.read_text(encoding="utf-8")
            chunks = split_bundle(text, ledger, strict=True)
        except Exception as exc:  # noqa: BLE001 - 任何切分失败都是边界被破坏
            problems.append(f"切分失败：{exc.__class__.__name__}: {exc}")

        if not problems and len(chunks) != len(ledger.chapters):
            problems.append(f"切出 {len(chunks)} 章，账本 {len(ledger.chapters)} 章")
        return {
            "ok": not problems,
            "chapters": len(chunks),
            "problems": problems,
        }
