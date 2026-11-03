"""V1.1-T1.3 端到端证据：禁用一条真的参与校正的词条，校正结果必须变。

不只看函数返回值，而是**真跑一遍管线**（真引擎、真六阶段），拿改前 / 改后
两次运行的产物做逐字节对比：

  A 全启用          → 正文里 N 处「告之」被换成「告知」
  B 禁用「告之→告知」→ 正文里「告之」原样保留、且在派生规则里消失
  C 再启用（还原）   → 正文与 A 逐字节一致

词条选的是出厂词库 ``normal`` 袋里的 ``告之 → 告知``——它在公版样本里真实
出现 54 次，且**不在** T1.1 的迁入禁用集里（T1.1 默认禁用集与出厂袋的交集
只有孤儿词条「费劲思量」，那条在样本里一次都不出现，做不了实证）。

用法：
    python3.12 tools/accept_t13.py --json out.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
for _p in (PKG, PKG / "fixtext_ui", PKG / "pipeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_pipeline.engine_selector import select_engine  # noqa: E402

_BIN = PKG / "pipeline" / "vendor" / "fixtext" / "engine" / "go_src" / "bin"
ENGINE = select_engine(_BIN) or (_BIN / "__no_platform_engine__")
RULES = PKG / "data" / "rules"
SAMPLE = PKG / "tests" / "samples" / "book_public_domain.epub"

#: 实证词条：出厂 normal 袋，样本内真实出现
PROBE_WORD = "告之"
PROBE_VALUE = "告知"


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_text(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_states(path: Path, disabled: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    obj = {"version": 1, "disabled": sorted(disabled)}
    path.write_bytes(
        json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"
    )


def _body_sha(path: Path) -> tuple[str, str]:
    """正文指纹 + nonce。

    每次运行都是独立工作区，合并阶段会生成新的 nonce（未公开的随机标识），
    所以同一份输入跑两遍、章节注释里的 nonce 必然不同——这是流水线的既有
    行为，与本卡无关。比对「结果是否一致」必须先把 nonce 归一，否则比的是
    随机标识而不是正文。
    """
    import re

    text = path.read_text(encoding="utf-8")
    m = re.search(r"nonce=([0-9a-f]{16})", text) or re.search(
        r"EPUBTEXT-(?:BOOK|BUNDLE):([0-9a-f]{16})", text)
    # 归一两类随机标识：``nonce=xxxx`` 与注释里的 ``EPUBTEXT-BOOK/SPLIT:xxxx``
    # （后者是同一个 nonce 在章节注释里的写法，只归一 nonce= 会漏掉 301 行）
    norm = re.sub(r"nonce=[0-9a-f]{16}", "nonce=X", text)
    norm = re.sub(r"(EPUBTEXT-(?:BOOK|SPLIT|BUNDLE):)[0-9a-f]{16}", r"\1X", norm)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest(), (m.group(1) if m else "")


def _run(tag: str, root: Path, states: Path) -> dict:
    """跑一次真实校正（EPUB 进全链路六阶段），返回这次运行的自证数据。"""
    from fixtext_worker import CorrectionJob

    run_dir = root / tag / "run"
    job = CorrectionJob(
        epub=SAMPLE, workdir=run_dir,
        rules_before=RULES / "before.json", rules_after=RULES / "after.json",
        engine_path=ENGINE, pipeline_root=PKG / "pipeline",
        title="公版样本",
        derived_rules_dir=root / tag / "derived",
        word_states_path=states,
    )
    summary = job.run()
    rep = json.loads(
        (run_dir / "03_replace" / "replace_report.json").read_text(encoding="utf-8"))
    after = Path(rep["after_path"])
    before = Path(rep["before_path"])
    derived = rep.get("derived_rules") or {}
    meta = {}
    meta_path = root / tag / "derived" / "round_main" / "round_meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    body_sha, nonce = _body_sha(after)
    return dict(
        tag=tag,
        elapsed_s=round(float(summary.get("elapsed_s") or 0.0), 2),
        chapters=summary.get("chapters"),
        hits=summary.get("hits"),
        after_path=str(after),
        before_path=str(before),
        nonce=nonce,
        before_sha256=_sha_text(before),
        after_sha256=_sha_text(after),
        after_body_sha256=body_sha,
        counts={
            "告之": after.read_text(encoding="utf-8").count("告之"),
            "告知": after.read_text(encoding="utf-8").count("告知"),
        },
        before_counts={
            "告之": before.read_text(encoding="utf-8").count("告之"),
            "告知": before.read_text(encoding="utf-8").count("告知"),
        },
        derived=derived,
        round_meta_disabled=dict(
            disabled_sha=meta.get("disabled_sha"),
            disabled_keys_checked=meta.get("disabled_keys_checked"),
            disabled_base_applied=meta.get("disabled_base_applied"),
            disabled_custom_applied=meta.get("disabled_custom_applied"),
            disabled_applied=meta.get("disabled_applied"),
            base_rules=meta.get("base_rules"),
            base_kept=meta.get("base_kept"),
            total_rules=meta.get("total_rules"),
            ruleset_sha256=meta.get("ruleset_sha256"),
        ),
        probe_rule_in_derived=_rule_present(
            root / tag / "derived" / "round_main", PROBE_WORD, PROBE_VALUE),
        restored_sha256=summary.get("restored_sha256"),
    )


def _rule_present(round_dir: Path, word: str, value: str) -> bool | None:
    """派生规则里还有没有这条规则（None = 文件缺失）。"""
    bp = round_dir / "before.json"
    ap = round_dir / "after.json"
    if not (bp.is_file() and ap.is_file()):
        return None
    b = json.loads(bp.read_text(encoding="utf-8"))
    a = json.loads(ap.read_text(encoding="utf-8"))
    for w, v in zip(b, a):
        if w == word and v == value:
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=str(HERE.parent / "t13_work"))
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if not SAMPLE.is_file():
        print(f"FAIL 缺少样本：{SAMPLE}")
        return 2
    if not ENGINE.is_file():
        print(f"FAIL 缺少引擎：{ENGINE}")
        return 2

    root = Path(args.work)
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    from fixtext_pipeline import rule_keys, word_states as ws

    states = root / "word_states.json"
    probe_key = rule_keys.entry_key(PROBE_WORD, PROBE_VALUE)
    base_off = set(ws.initial_disabled_keys())     # 出厂初始禁用集（迁入 + 孤儿）

    print(f"[环境] 引擎={ENGINE.name}  样本={SAMPLE.name}")
    print(f"[词条] 探针「{PROBE_WORD}→{PROBE_VALUE}」内容键 {probe_key[:16]}…")
    print(f"[禁用集] 初始 {len(base_off)} 键")

    # ---- A 全启用（只保留初始禁用集；探针词条此时是启用的） -------------
    _write_states(states, base_off)
    print("\n=== A 全启用 ===")
    a = _run("A", root, states)
    print(f"  耗时 {a['elapsed_s']}s  章数 {a['chapters']}  命中 {a['hits']}")
    print(f"  正文「告之」{a['before_counts']['告之']} → {a['counts']['告之']}"
          f"　「告知」{a['before_counts']['告知']} → {a['counts']['告知']}")
    print(f"  派生规则含探针 {a['probe_rule_in_derived']}  "
          f"disabled_applied={a['derived'].get('disabled_applied')}")
    print(f"  after sha {a['after_sha256'][:16]}…  ruleset {str(a['derived'].get('ruleset_sha256'))[:16]}…")

    # ---- B 禁用探针词条 -------------------------------------------------
    off_b = base_off | {probe_key}
    _write_states(states, off_b)
    print("\n=== B 禁用「告之→告知」 ===")
    b = _run("B", root, states)
    print(f"  耗时 {b['elapsed_s']}s  章数 {b['chapters']}  命中 {b['hits']}")
    print(f"  正文「告之」{b['before_counts']['告之']} → {b['counts']['告之']}"
          f"　「告知」{b['before_counts']['告知']} → {b['counts']['告知']}")
    print(f"  派生规则含探针 {b['probe_rule_in_derived']}  "
          f"disabled_applied={b['derived'].get('disabled_applied')}")
    print(f"  after sha {b['after_sha256'][:16]}…  ruleset {str(b['derived'].get('ruleset_sha256'))[:16]}…")

    # ---- C 再启用（还原到 A） -------------------------------------------
    _write_states(states, base_off)
    print("\n=== C 再启用（应回到 A） ===")
    c = _run("C", root, states)
    print(f"  耗时 {c['elapsed_s']}s  章数 {c['chapters']}  命中 {c['hits']}")
    print(f"  正文「告之」{c['before_counts']['告之']} → {c['counts']['告之']}"
          f"　「告知」{c['before_counts']['告知']} → {c['counts']['告知']}")
    print(f"  after sha {c['after_sha256'][:16]}…")

    # ---- 判定 ------------------------------------------------------------
    a_base_off = a["derived"].get("disabled_base_applied") or 0
    b_base_off = b["derived"].get("disabled_base_applied") or 0
    checks = {
        "A 探针词条真的参与校正（原词被替换掉）":
            a["counts"]["告之"] < a["before_counts"]["告之"],
        "A 派生规则里有探针词条": a["probe_rule_in_derived"] is True,
        "B 禁用后派生规则里没有探针词条": b["probe_rule_in_derived"] is False,
        "B 禁用后原词一个都不少（禁用真生效）":
            b["counts"]["告之"] == b["before_counts"]["告之"],
        "B 禁用后替换值不再新增":
            b["counts"]["告知"] <= a["before_counts"]["告知"],
        "A/B 校正后正文逐字节不同（不是同一份缓存）":
            a["after_sha256"] != b["after_sha256"],
        "C 再启用后正文与 A 一致（nonce 归一后逐字节相同）":
            c["after_body_sha256"] == a["after_body_sha256"],
        "A/C 用了不同的 nonce（证明是两次独立运行，不是同一份产物）":
            a["nonce"] != c["nonce"] and a["nonce"] and c["nonce"],
        "A/B 规则集指纹不同（指纹与行为同步）":
            a["derived"].get("ruleset_sha256") != b["derived"].get("ruleset_sha256"),
        "B 比 A 多剔了正好 1 条出厂规则（就是探针那条）":
            b_base_off == a_base_off + 1,
        "A 的剔除数只来自出厂初始禁用集（孤儿词条数）":
            a_base_off >= 1,
        "C 规则集指纹与 A 相同（启用即复原）":
            c["derived"].get("ruleset_sha256") == a["derived"].get("ruleset_sha256"),
        "随包词库未被改动":
            _sha_file(RULES / "before.json") == BEFORE_SHA
            and _sha_file(RULES / "after.json") == AFTER_SHA,
    }
    print("\n=== 判定 ===")
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    payload = dict(
        probe=dict(word=PROBE_WORD, value=PROBE_VALUE, key=probe_key),
        runs=dict(A=a, B=b, C=c),
        checks=checks,
        rules_sha=dict(before=BEFORE_SHA, after=AFTER_SHA),
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    if args.json:
        Path(args.json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n证据已写 {args.json}")

    all_pass = all(checks.values())
    print(f"\n结论：{'ALL PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


BEFORE_SHA = _sha_file(RULES / "before.json") if RULES.joinpath("before.json").is_file() else ""
AFTER_SHA = _sha_file(RULES / "after.json") if RULES.joinpath("after.json").is_file() else ""

if __name__ == "__main__":
    raise SystemExit(main())
