"""V1.1-F3 守卫：CorrectionJob 跑完之后必须把引擎客户端的 subprocess 还回去。

背景（V1.1-F1 的取证结论）：``CorrectionJob.run()`` 运行前把
``fixtext.engine.client.subprocess`` 换成绑定本次 job 的 ``_SubprocessProxy``，
好让「用户点取消」能真的 kill 掉 Go 引擎子进程。问题在于收尾：

* 代理里绑的是**那一次 job 的 cancel_requested**，被取消过的 job 永远是 True；
* 收尾只把 Python 引擎的协作钩子摘了，没把 ``subprocess`` 摘回标准库模块。

于是同一个进程里，之后任何一次**直调引擎**（不经 job 的路径）都会读到
那个已经置位的取消标记，抛出「已终止替换引擎」。

当前产品里引擎只有 job 一个入口，所以这个坑还没暴露；但它是可以预见
的：将来任何直调引擎的路径（批量验收脚本、检查页预演、诊断工具）都会中招。
这组守卫把两条路径都钉死：

1. 取消一次 job（走异常出口）→ ``subprocess`` 必须是标准库模块，且同进程
   直调引擎能正常返回；
2. 正常跑完一次 job（走正常出口）→ 同样必须还回去。

断言只认「模块属性现在是什么」和「引擎这次调用真的返回 ok」，不看任何
函数自报。
"""

from __future__ import annotations

import json
import subprocess as _stdlib_subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui", PKG / "pipeline", PKG / "pipeline" / "vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RULES = PKG / "data" / "rules"
_BIN = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"

_PROBE_TEXT = "萧衍 起身，众人皆看向萧衍。\n唯萧衍旧部尚在，萧衍 已去。\n"


def _engine():
    from fixtext_pipeline.engine_selector import select_engine

    return select_engine(_BIN)


_ENGINE = _engine()
needs_engine = pytest.mark.skipif(_ENGINE is None, reason="缺少真实替换引擎")


def _mini_rules(tmp_path: Path) -> tuple[Path, Path]:
    """两条自造规则，够跑通一次引擎调用，不碰随包 30 万条词库。"""
    tmp_path.mkdir(parents=True, exist_ok=True)
    before = tmp_path / "rules_before.json"
    after = tmp_path / "rules_after.json"
    before.write_text(json.dumps(["萧衍"], ensure_ascii=False), encoding="utf-8")
    after.write_text(json.dumps(["萧彦"], ensure_ascii=False), encoding="utf-8")
    return before, after


def _direct_engine_call(tmp_path: Path) -> dict:
    """直调引擎（不经 CorrectionJob）：返回 {ok, code, out}。"""
    from fixtext.engine import EngineRequest, InputMode, OutputMode, RuleSet
    from fixtext.engine.client import GoEngineClient

    before, after = _mini_rules(tmp_path)
    rs = RuleSet.from_files(before, after)
    client = GoEngineClient(_ENGINE)
    resp = client.run(EngineRequest(
        rules=rs,
        count=2,
        input_mode=InputMode.MEMORY,
        input_data=_PROBE_TEXT,
        output_mode=OutputMode.MEMORY,
    ))
    if not resp.ok:
        err = getattr(resp, "error", None)
        return dict(ok=False,
                    code=getattr(getattr(err, "code", None), "name", str(err)),
                    message=getattr(err, "message", str(err)))
    return dict(ok=True,
                out=str(getattr(resp.result, "output_text", "") or ""),
                changed=bool(getattr(resp.result, "changed", False)))


def _job(tmp_path: Path, *, cancel: bool):
    from plain_book import plain_source_epub
    from fixtext_worker import CorrectionJob

    work = tmp_path / "run"
    work.mkdir(parents=True, exist_ok=True)
    text = work / "probe.txt"
    text.write_text(_PROBE_TEXT, encoding="utf-8")
    src = plain_source_epub(text, work / "src", title="探针")
    job = CorrectionJob(
        epub=src,
        workdir=work / "job",
        rules_before=RULES / "before.json",
        rules_after=RULES / "after.json",
        engine_path=_ENGINE,
        pipeline_root=PKG / "pipeline",
        title="探针",
    )
    if cancel:
        # 在第一个阶段开始前就置位：代理已经装好，异常出口一定走 finally
        job.request_cancel()
    return job


def _restored() -> bool:
    from fixtext.engine import client as engine_client

    return engine_client.subprocess is _stdlib_subprocess


@needs_engine
def test_cancelled_job_hands_subprocess_back(tmp_path):
    """取消一次 job 后：subprocess 回到标准库，同进程直调引擎不误报。"""
    from fixtext_worker import CorrectionCancelled

    job = _job(tmp_path, cancel=True)
    with pytest.raises(CorrectionCancelled):
        job.run()

    assert _restored(), (
        "取消后的 job 必须把 fixtext.engine.client.subprocess 还原回标准库模块，"
        "否则代理里那个已置位的取消标记会一直跟着整个进程"
    )

    res = _direct_engine_call(tmp_path / "after_cancel")
    assert res["ok"], f"同进程再直调引擎被上一次取消误伤：{res}"
    assert "萧衍" not in res["out"] and "萧彦" in res["out"]


@needs_engine
def test_completed_job_hands_subprocess_back(tmp_path):
    """正常跑完一次 job 后：同样必须还回去。"""
    job = _job(tmp_path, cancel=False)
    summary = job.run()
    assert summary["chapters"] >= 1

    assert _restored(), (
        "跑完的 job 也必须把 subprocess 还原回标准库模块——代理不摘掉，"
        "后续直调引擎就会读到那次 job 的取消标记"
    )

    res = _direct_engine_call(tmp_path / "after_done")
    assert res["ok"], f"跑完一次 job 后直调引擎失败：{res}"
