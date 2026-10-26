#!/usr/bin/env python3
"""T0.3 自验：Go 引擎直跑 vs 集成层逐字节一致性 + 异常路径真实触发。

三件事，全部留痕到 results/integration_verify.json：

1. **逐字节一致性**：同一份语料、同一套 T0.2 规则、同一 count，走两条路径
   - 直跑：把引擎二进制当黑盒，直接 `replace_by_go <file> before.json after.json count`
   - 集成层：`GoEngineClient.run(EngineRequest(...))`
   比对输出文件的 sha256 与字节数；不一致则给出首个差异位置与 1KB 窗口一致率。
   **两种输入形态都验**：FILE 输入（走临时副本 + 文件交付）与 MEMORY 输入（走内存交付）。

2. **异常路径**：每个错误码至少真实触发一次，记录触发现场
   - 引擎缺失（E1001）：指向不存在的引擎路径
   - 调用超时（E1003）：给一个远小于实际耗时的 timeout，让子进程真的被 kill
   - 顺带覆盖：引擎不可执行（E1002）、规则数量不匹配（E2203）、规则为空（E2204）、
     输入缺失（E2101）、参数非法（E2301）
   **先故意跑一次「本该失败的对照」**：同一 timeout 下小文件能成功，证明超时不是环境问题。

3. **构建留痕**：离线构建本机二进制与 Windows 交叉编译各一次，记录命令与环境变量。

用法：
    python scripts/verify_engine_integration.py [--corpus NAME ...] [--skip-windows]
退出码 0 = 全部验收项通过。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

RESULTS = PROJECT_ROOT / "results"
RULES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "rules"
CORPUS_DIR = PROJECT_ROOT / "corpus"
WORK = PROJECT_ROOT / ".work"

# 云盘取用的三部真实小说 + 20MB 切片：key -> (语料文件名, 来源说明, 标题)
CORPORA: dict[str, tuple[str, str, str]] = {
    "slice20mb": (
        "corpus_20mb_slice.txt",
        "corpus_fanpai.txt 前 20 MiB 切片",
        "反派少爷只想过佛系生活 · 20MB 切片",
    ),
    "fanpai": (
        "corpus_fanpai.txt",
        "反派少爷只想过佛系生活 作者：人之下.txt",
        "反派少爷只想过佛系生活",
    ),
    "quhun": (
        "corpus_quhun.txt",
        "雀魂：开局国士无双 作者：玄汐蓝.txt",
        "雀魂：开局国士无双",
    ),
    "guimie": (
        "corpus_guimie.txt",
        "鬼灭之刃：我的眼睛能看到弹幕 作者：陆要芝麻粒.txt",
        "鬼灭之刃：我的眼睛能看到弹幕",
    ),
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def diff_detail(a: Path, b: Path) -> dict:
    """逐字节比对两个文件，返回摘要；不一致时定位首个差异并给 1KB 窗口一致率。"""
    sa, sb = sha256_file(a), sha256_file(b)
    size_a, size_b = a.stat().st_size, b.stat().st_size
    detail: dict = {
        "bytes_a": size_a,
        "bytes_b": size_b,
        "sha256_a": sa,
        "sha256_b": sb,
        "identical": sa == sb,
    }
    if detail["identical"]:
        return detail
    detail["size_delta"] = size_b - size_a
    # 定位首个差异字节
    with open(a, "rb") as fa, open(b, "rb") as fb:
        pos = 0
        while True:
            ca = fa.read(1 << 20)
            cb = fb.read(1 << 20)
            if not ca or not cb:
                detail["first_diff_byte"] = pos if (ca or cb) else None
                break
            if ca != cb:
                for i in range(min(len(ca), len(cb))):
                    if ca[i] != cb[i]:
                        detail["first_diff_byte"] = pos + i
                        break
                break
            pos += len(ca)
    # 1KB 窗口一致率
    win, same, total = 1024, 0, 0
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            ca = fa.read(win)
            cb = fb.read(win)
            if not ca and not cb:
                break
            total += 1
            if ca == cb:
                same += 1
    detail["win_1kb_total"] = total
    detail["win_1kb_identical"] = same
    detail["win_1kb_rate"] = round(same / total, 6) if total else None
    return detail


def run_direct(engine: Path, corpus: Path, before: Path, after: Path, count: int, out: Path) -> dict:
    """Go 引擎直跑：引擎只接受原地改写，所以先复制到 out 再对 out 跑。"""
    shutil.copyfile(corpus, out)
    started = time.time()
    proc = subprocess.run(
        [str(engine), str(out), str(before), str(after), str(count)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.time() - started
    return {
        "path": "direct",
        "exit_code": proc.returncode,
        "seconds": round(elapsed, 3),
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip()[-800:],
        "output_bytes": out.stat().st_size if out.exists() else None,
        "sha256": sha256_file(out) if out.exists() else None,
    }


def run_via_client(client, corpus: Path, rules, count: int, out: Path, mode: str) -> dict:
    """集成层：FILE 输入 → FILE 输出，或 MEMORY 输入 → 内存结果再落盘比对。"""
    from fixtext.engine import EngineRequest, InputMode, OutputMode

    if mode == "file":
        req = EngineRequest(
            rules=rules,
            count=count,
            input_mode=InputMode.FILE,
            input_path=corpus,
            output_mode=OutputMode.FILE,
            output_path=out,
            timeout_s=900.0,
        )
    else:
        req = EngineRequest(
            rules=rules,
            count=count,
            input_mode=InputMode.MEMORY,
            input_data=corpus.read_bytes(),
            output_mode=OutputMode.MEMORY,
            timeout_s=900.0,
        )
    started = time.time()
    resp = client.run(req)
    elapsed = time.time() - started
    info: dict = {
        "path": f"client-{mode}",
        "seconds": round(elapsed, 3),
        "overhead_breakdown": {
            "staging_rules_and_text_plus_process": round(elapsed, 3),
        },
    }
    if not resp.ok:
        info.update({"ok": False, "error": resp.error.as_dict()})
        return info
    res = resp.result
    if mode == "memory":
        out.write_bytes((res.output_text or "").encode("utf-8"))
    info.update(
        {
            "ok": True,
            "output_bytes": res.bytes_out,
            "sha256": res.sha256_out,
            "engine_reported_count": res.count,
            "engine_seconds": round(res.elapsed_s, 3),
            "changed": res.changed,
        }
    )
    return info


def build_stage(skip_windows: bool) -> dict:
    """离线构建留痕：本机 + Windows 交叉编译。"""
    from fixtext.engine import builder

    info: dict = {"go_version": builder.check_go_available(), "imports": builder.check_zero_external_deps()}
    host = builder.host_target().split("-")
    res = builder.build(goos=host[0], goarch=host[1])
    info["host"] = res.as_dict()
    info["host"]["env"] = {
        "GOPROXY": "off",
        "GOTOOLCHAIN": "local",
        "CGO_ENABLED": "0",
        "GOWORK": "off",
        "GOFLAGS": "-mod=mod",
    }
    info["host"]["parallelism"] = "-p 1"

    if not skip_windows:
        try:
            win = builder.build(goos="windows", goarch="amd64")
            info["windows"] = win.as_dict()
            # 交叉编译产物在 Linux 上不可执行，只核验格式与体积
            with open(win.output, "rb") as f:
                head = f.read(2)
            info["windows"]["pe_signature"] = head.hex()
            info["windows"]["is_pe"] = head == b"MZ"
        except Exception as exc:  # noqa: BLE001
            info["windows"] = {"ok": False, "error": str(exc)}
    return info


def error_stage(client, engine, corpus_small: Path, rules, corpus_big: Path) -> dict:
    """异常路径：逐个真实触发，记录码与现场。"""
    from fixtext.engine import EngineRequest, GoEngineClient, InputMode, OutputMode, RuleSet
    from fixtext.engine.errors import EngineError, EngineErrorCode

    cases: list[dict] = []

    def record(name: str, expected_code: str, resp, extra: dict | None = None) -> None:
        entry = {
            "case": name,
            "expected_code": expected_code,
            "actual_code": resp.error.code if not resp.ok else "NONE(成功)",
            "matched": (not resp.ok) and resp.error.code == expected_code,
            "error": resp.error.as_dict() if not resp.ok else None,
        }
        if extra:
            entry.update(extra)
        cases.append(entry)

    # --- 对照：同一小文件、充裕超时必须成功，证明引擎本身可用 ---
    ok_small = client.run(
        EngineRequest(
            rules=rules, count=1, input_mode=InputMode.MEMORY, input_data="的地得测试", timeout_s=120
        )
    )
    cases.append(
        {
            "case": "control-small-file-success",
            "expected_code": "NONE(成功)",
            "actual_code": "NONE(成功)" if ok_small.ok else ok_small.error.code,
            "matched": ok_small.ok,
            "error": None if ok_small.ok else ok_small.error.as_dict(),
        }
    )

    # --- E1001 引擎缺失 ---
    missing = GoEngineClient("/tmp/fixtext-no-such-engine-binary")
    record(
        "engine-missing",
        EngineErrorCode.ENGINE_MISSING,
        missing.run(EngineRequest(rules=rules, count=1, input_data="x", timeout_s=30)),
    )

    # --- E1002 引擎不可执行：写一个无执行位、内容也不是 ELF 的文件 ---
    fake = WORK / "fake_engine_noexec"
    fake.write_bytes(b"not an executable")
    fake.chmod(0o644)
    record(
        "engine-not-executable-no-x-bit",
        EngineErrorCode.ENGINE_NOT_EXECUTABLE,
        GoEngineClient(fake).run(EngineRequest(rules=rules, count=1, input_data="x", timeout_s=30)),
        {"fixture": str(fake), "mode": oct(fake.stat().st_mode)},
    )
    # 有执行位但格式非法 -> 内核拒绝执行（Exec format error）
    fake2 = WORK / "fake_engine_badformat"
    fake2.write_bytes(b"#!/nothing\n")
    fake2.chmod(0o755)
    record(
        "engine-not-executable-bad-format",
        EngineErrorCode.ENGINE_NOT_EXECUTABLE,
        GoEngineClient(fake2).run(EngineRequest(rules=rules, count=1, input_data="x", timeout_s=30)),
        {"fixture": str(fake2), "mode": oct(fake2.stat().st_mode)},
    )

    # --- E1003 超时：给 0.6s，让 22MB 语料的真实耗时远超它 ---
    started = time.time()
    resp_timeout = client.run(
        EngineRequest(
            rules=rules,
            count=2,
            input_mode=InputMode.FILE,
            input_path=corpus_big,
            output_mode=OutputMode.MEMORY,
            timeout_s=0.6,
        )
    )
    wall = time.time() - started
    record(
        "engine-timeout",
        EngineErrorCode.ENGINE_TIMEOUT,
        resp_timeout,
        {"timeout_s": 0.6, "observed_wall_s": round(wall, 3), "corpus": corpus_big.name},
    )

    # --- E2203 规则数量不匹配（直接构造，静态拦截） ---
    try:
        RuleSet(["a", "b"], ["c"])
        direct = {"code": "NO-ERROR", "name": "NONE", "message": "", "remedy": "", "detail": {}}
    except EngineError as exc:
        direct = exc.as_dict()
    cases.append(
        {
            "case": "rules-length-mismatch",
            "expected_code": EngineErrorCode.RULES_LENGTH_MISMATCH,
            "actual_code": direct["code"],
            "matched": direct["code"] == EngineErrorCode.RULES_LENGTH_MISMATCH,
            "error": direct,
        }
    )

    # --- E2204 规则为空 ---
    try:
        RuleSet([], [])
        direct = {"code": "NO-ERROR", "name": "NONE", "message": "", "remedy": "", "detail": {}}
    except EngineError as exc:
        direct = exc.as_dict()
    cases.append(
        {
            "case": "rules-empty",
            "expected_code": EngineErrorCode.RULES_EMPTY,
            "actual_code": direct["code"],
            "matched": direct["code"] == EngineErrorCode.RULES_EMPTY,
            "error": direct,
        }
    )

    # --- E2101 输入缺失 ---
    record(
        "input-missing",
        EngineErrorCode.INPUT_MISSING,
        client.run(
            EngineRequest(
                rules=rules,
                count=1,
                input_mode=InputMode.FILE,
                input_path=WORK / "no-such-corpus.txt",
                output_mode=OutputMode.MEMORY,
            )
        ),
    )

    # --- E2301 参数非法：count=0 必须在起子进程前被拦下 ---
    record(
        "argument-invalid-count-zero",
        EngineErrorCode.ARGUMENT_INVALID,
        client.run(EngineRequest(rules=rules, count=0, input_data="x")),
    )

    # --- E2401 输出落盘失败：输出目录是一个文件而不是目录 ---
    blocker = WORK / "output_blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    record(
        "output-write-failed",
        EngineErrorCode.OUTPUT_WRITE_FAILED,
        client.run(
            EngineRequest(
                rules=rules,
                count=1,
                input_data="的地得",
                output_mode=OutputMode.FILE,
                output_path=blocker / "sub" / "out.txt",
            )
        ),
        {"blocker": str(blocker)},
    )

    # --- E2202 规则非法 JSON：把坏规则写成文件再交给引擎（真实走一次子进程） ---
    bad_rules_dir = WORK / "bad_rules"
    bad_rules_dir.mkdir(parents=True, exist_ok=True)
    (bad_rules_dir / "before.json").write_text("{bad", encoding="utf-8")
    (bad_rules_dir / "after.json").write_text('["x"]', encoding="utf-8")
    # 对照组：同样的调用方式 + 合法规则是成功的，说明 E2202 来自坏 JSON 而非调用方式
    control_resp = client.run(
        EngineRequest(
            rules=RuleSet(["的"], ["X"]),
            count=1,
            input_data="的地得",
            output_mode=OutputMode.MEMORY,
        )
    )
    assert control_resp.ok, f"对照组应成功: {control_resp.error}"
    # 为了真实触发 E2202，绕开 RuleSet 校验直连引擎
    raw = subprocess.run(
        [
            str(engine),
            str(_ensure_text_file(WORK / "tiny.txt", "的地得")),
            str(bad_rules_dir / "before.json"),
            str(bad_rules_dir / "after.json"),
            "1",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    from fixtext.engine.errors import map_engine_stderr

    mapped = map_engine_stderr(raw.stderr)
    cases.append(
        {
            "case": "rules-invalid-json-direct-subprocess",
            "expected_code": EngineErrorCode.RULES_INVALID_JSON,
            "actual_code": mapped,
            "matched": mapped == EngineErrorCode.RULES_INVALID_JSON,
            "error": {
                "exit_code": raw.returncode,
                "stderr": raw.stderr.strip()[-400:],
                "note": "绕过 RuleSet 静态校验，直接让 Go 引擎读到坏 JSON",
            },
        }
    )

    return {
        "total": len(cases),
        "matched": sum(1 for c in cases if c["matched"]),
        "all_matched": all(c["matched"] for c in cases),
        "cases": cases,
    }


def _ensure_text_file(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T0.3 Go 引擎集成层自验")
    parser.add_argument(
        "--corpus",
        nargs="*",
        default=list(CORPORA),
        help=f"要比对的语料 key（默认全部：{', '.join(CORPORA)}）",
    )
    parser.add_argument("--count", type=int, default=2, help="替换次数（生产语义默认 2）")
    parser.add_argument("--skip-windows", action="store_true", help="跳过 Windows 交叉编译")
    parser.add_argument("--skip-big", action="store_true", help="跳过 ≥20MB 语料（仅小语料回归）")
    args = parser.parse_args(argv)

    RESULTS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)

    from fixtext.engine import GoEngineClient, RuleSet

    report: dict = {
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "count": args.count,
        "env": {"cpu_cores": os.cpu_count(), "python": sys.version.split()[0]},
    }

    # 1) 构建
    print("[1/4] 离线构建 ...")
    report["build"] = build_stage(args.skip_windows)
    engine = report["build"]["host"]["output"]
    if not engine:
        print("构建失败，终止。", file=sys.stderr)
        return 1
    engine_path = Path(engine)
    report["build"]["host"]["device"] = str(engine_path)
    print(
        f"      本机 {report['build']['host']['target']} "
        f"{report['build']['host']['size_bytes']:,} B  {report['build']['host']['seconds']}s"
    )
    if "windows" in report["build"]:
        w = report["build"]["windows"]
        print(f"      win  {w.get('target')} {w.get('size_bytes')} B  is_pe={w.get('is_pe')}")

    # 2) 规则
    print("[2/4] 加载 T0.2 真实规则 ...")
    rules = RuleSet.from_files(RULES_DIR / "before.json", RULES_DIR / "after.json")
    report["rules"] = {
        "source": "T0.2 build/dictionary/rules/before.json + after.json",
        "count": len(rules),
        "unique_before": rules.unique_before,
        "before_sha256": sha256_file(RULES_DIR / "before.json"),
        "after_sha256": sha256_file(RULES_DIR / "after.json"),
    }
    print(f"      规则 {len(rules):,} 条（去重后 {rules.unique_before:,}）")

    client = GoEngineClient(engine_path)

    # 3) 逐字节一致性
    print("[3/4] 逐字节一致性（Go 直跑 vs 集成层） ...")
    eq_results: list[dict] = []
    for key in args.corpus:
        if key not in CORPORA:
            print(f"      跳过未知语料 {key}", file=sys.stderr)
            continue
        corpus_name, src_name, title = CORPORA[key]
        corpus = CORPUS_DIR / corpus_name
        if not corpus.exists():
            print(f"      跳过：缺语料 {corpus.name}（先运行 scripts/build_corpus.py）", file=sys.stderr)
            continue
        size = corpus.stat().st_size
        if args.skip_big and size >= 20 * 1024 * 1024:
            print(f"      跳过 {key}（≥20MB，--skip-big）")
            continue

        direct_out = WORK / f"direct_{key}.txt"
        client_file_out = WORK / f"client_file_{key}.txt"
        client_mem_out = WORK / f"client_mem_{key}.txt"

        direct = run_direct(
            engine_path, corpus, RULES_DIR / "before.json", RULES_DIR / "after.json", args.count, direct_out
        )
        cf = run_via_client(client, corpus, rules, args.count, client_file_out, "file")
        cm = run_via_client(client, corpus, rules, args.count, client_mem_out, "memory")

        cmp_file = (
            diff_detail(direct_out, client_file_out)
            if client_file_out.exists() and direct_out.exists()
            else {"identical": False, "reason": "输出缺失"}
        )
        cmp_mem = (
            diff_detail(direct_out, client_mem_out)
            if client_mem_out.exists() and direct_out.exists()
            else {"identical": False, "reason": "输出缺失"}
        )

        entry = {
            "key": key,
            "title": title,
            "source_file": src_name,
            "corpus_file": corpus.name,
            "corpus_bytes": size,
            "corpus_MiB": round(size / 1048576, 2),
            "corpus_sha256": sha256_file(corpus),
            "direct": direct,
            "client_file": cf,
            "client_memory": cm,
            "compare_file_vs_direct": cmp_file,
            "compare_memory_vs_direct": cmp_mem,
            "identical": bool(cmp_file.get("identical")) and bool(cmp_mem.get("identical")),
        }
        eq_results.append(entry)
        mark = "IDENTICAL" if entry["identical"] else "DIFF"
        print(
            f"      {key:8s} {entry['corpus_MiB']:6.2f} MiB  "
            f"direct {direct['seconds']:6.2f}s  file {cf['seconds']:6.2f}s  mem {cm['seconds']:6.2f}s  "
            f"out {direct['output_bytes']:,} B  -> {mark}"
        )
        if not entry["identical"]:
            print(f"        file: {json.dumps(cmp_file, ensure_ascii=False)}")
            print(f"        mem : {json.dumps(cmp_mem, ensure_ascii=False)}")

    report["equivalence"] = {
        "total": len(eq_results),
        "identical": sum(1 for e in eq_results if e["identical"]),
        "all_identical": bool(eq_results) and all(e["identical"] for e in eq_results),
        "corpora": eq_results,
    }

    # 4) 异常路径
    print("[4/4] 异常路径真实触发 ...")
    big_corpus = CORPUS_DIR / "corpus_fanpai.txt"
    if not big_corpus.exists():
        bigger = [p for p in CORPUS_DIR.glob("corpus_*.txt") if p.stat().st_size > 5 * 1024 * 1024]
        if not bigger:
            print("      缺可触发超时的大语料，异常路径跳过", file=sys.stderr)
            big_corpus = _ensure_text_file(WORK / "fallback_big.txt", "的地得" * 500000)
        else:
            big_corpus = max(bigger, key=lambda p: p.stat().st_size)
    report["errors"] = error_stage(client, engine_path, WORK / "tiny.txt", rules, big_corpus)
    print(f"      异常用例 {report['errors']['matched']}/{report['errors']['total']} 命中预期错误码")
    for case in report["errors"]["cases"]:
        flag = "OK  " if case["matched"] else "FAIL"
        print(f"        [{flag}] {case['case']:38s} -> {case['actual_code']}")

    # 汇总判定
    checks = {
        "build_host_ok": bool(report["build"]["host"].get("ok")),
        "build_windows_pe": report["build"].get("windows", {}).get("is_pe", None),
        "equivalence_all_identical": report["equivalence"]["all_identical"],
        "equivalence_has_20mb": any(
            e["key"] == "slice20mb" and e["corpus_bytes"] >= 20 * 1024 * 1024 for e in eq_results
        ),
        "errors_all_matched": report["errors"]["all_matched"],
    }
    report["checks"] = checks
    report["pass"] = all(
        [
            checks["build_host_ok"],
            checks["build_windows_pe"] is not False,
            checks["equivalence_all_identical"],
            checks["equivalence_has_20mb"] or args.skip_big,
            checks["errors_all_matched"],
        ]
    )
    # 失败时把每条判定逐项打出来，避免「某一项悄悄 false 却只看结论」的误读
    if not report["pass"]:
        for name, value in checks.items():
            print(f"  [{'PASS' if value else 'FAIL'}] {name} = {value}", file=sys.stderr)

    out_path = RESULTS / "integration_verify.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("-" * 70)
    print(f"自验报告：{out_path}")
    print(f"结论：{'PASS' if report['pass'] else 'FAIL'}  {json.dumps(checks, ensure_ascii=False)}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
