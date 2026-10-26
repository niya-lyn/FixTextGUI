#!/usr/bin/env python3
"""T0.4 回归基线集 · 一键重跑比对脚本

用法：
    python run_baseline.py                # 重跑两个引擎并与冻结基线比对（验收模式）
    python run_baseline.py --build       # （重新）生成/冻结基线输出与清单
    python run_baseline.py --json r.json # 额外把结果写成 JSON（CI 用）

重跑内容（全部离线，不访问外网）：
  1. 语料完整性：corpus/ 下每个文件与 corpus_manifest.json 中的 sha256 比对；
  2. Go 后端：上游 src/tools/replace_by_go.go（原样编译）对语料执行 count=2 替换；
  3. PHP 后端：复刻上游 TextFixer::replaceByPHP（Go 降级语义）执行 count=2 替换；
  4. 命中计数：count_hits 重放替换，统计替换次数，并要求其输出与 Go 引擎逐字节一致；
  5. 比对：Go / PHP 输出与 baseline 期望（expected/go、expected/php）逐字节（sha256）比对，
     并校验替换计数与 baseline_manifest.json 一致。

退出码：0 = 全部一致；1 = 存在不一致或缺依赖；2 = 参数/环境错误。

依赖：python3（仅标准库）；php（CLI）；go（可选，缺失时使用随包预编译二进制，仅限 linux/amd64）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE = SCRIPT_DIR.parent
GO_DIR = SCRIPT_DIR / "go"
GO_BIN = GO_DIR / "replace_by_go.bin"
CNT_BIN = GO_DIR / "count_hits.bin"
REPLACE_COUNT = 2  # 生产口径：Map.php useMapsConfig[*]['singleReplace']=false → doReplace 执行 2 次
BASELINE_MANIFEST = BASE / "manifest" / "baseline_manifest.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def which(name: str) -> str | None:
    return shutil.which(name)


def ensure_go_tools(rebuild: bool) -> tuple[Path | None, Path | None, str]:
    """返回 (replace_by_go, count_hits, 说明)。优先用 go build 编译，其次预编译二进制。"""
    if rebuild or (not GO_BIN.exists() or not CNT_BIN.exists()):
        go = which("go")
        if go:
            for pkg, out in (("replace_by_go", GO_BIN), ("count_hits", CNT_BIN)):
                proc = subprocess.run(
                    [go, "build", "-o", str(out), "./" + pkg],
                    cwd=str(GO_DIR), capture_output=True, text=True, timeout=300,
                )
                if proc.returncode != 0:
                    return None, None, f"go build 失败（{pkg}）：{proc.stderr.strip()}"
            return GO_BIN, CNT_BIN, "go build 编译"
    if GO_BIN.exists() and CNT_BIN.exists():
        return GO_BIN, CNT_BIN, "随包预编译二进制（linux/amd64）"
    return None, None, "缺少 go 工具链，且无预编译二进制"


def run_cmd(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T0.4 回归基线集 · 一键重跑比对")
    ap.add_argument("--build", action="store_true", help="生成/冻结基线而非比对")
    ap.add_argument("--rebuild-go", action="store_true", help="强制用 go build 重新编译 Go 工具")
    ap.add_argument("--corpus-dir", default=str(BASE / "corpus"))
    ap.add_argument("--rules-dir", default=str(BASE / "rules"))
    ap.add_argument("--expected-dir", default=str(BASE / "expected"))
    ap.add_argument("--count", type=int, default=REPLACE_COUNT, help="替换轮数（生产口径 2）")
    ap.add_argument("--json", help="结果 JSON 输出路径")
    args = ap.parse_args(argv)

    corpus_dir = Path(args.corpus_dir)
    rules_dir = Path(args.rules_dir)
    expected_dir = Path(args.expected_dir)
    before_json = rules_dir / "before.json"
    after_json = rules_dir / "after.json"

    for p in (corpus_dir, before_json, after_json):
        if not p.exists():
            print(f"[环境错误] 缺少 {p}")
            return 2

    php = which("php")
    go_bin, cnt_bin, tool_note = ensure_go_tools(args.rebuild_go)
    missing = [n for n, v in (("php", php), ("replace_by_go", go_bin), ("count_hits", cnt_bin)) if not v]
    if missing:
        print(f"[环境错误] 缺少依赖：{', '.join(missing)}（{tool_note}）")
        return 2

    corpus_files = sorted(p for p in corpus_dir.iterdir() if p.is_file() and p.suffix == ".txt")
    if not corpus_files:
        print("[环境错误] 语料目录为空")
        return 2

    manifest_path = corpus_dir / "corpus_manifest.json"
    corpus_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    sha_by_file = {i["corpus_file"]: i["sha256"] for i in (corpus_manifest or {}).get("items", [])}

    print(f"FixText T0.4 回归基线 · {'生成' if args.build else '比对'}模式")
    print(f"语料 {len(corpus_files)} 个文件 · 规则 {before_json.parent.name} · 替换轮数 {args.count}")
    print(f"Go 工具来源：{tool_note}")
    print("-" * 96)

    results = []
    n_ok = 0
    t_all = time.time()
    baseline_manifest = {
        "baseline_version": "v1",
        "generator": "baseline/scripts/run_baseline.py --build",
        "replace_count": args.count,
        "rules": {
            "before_sha256": sha256_file(before_json),
            "after_sha256": sha256_file(after_json),
            "meta": json.loads((rules_dir / "rules_meta.json").read_text(encoding="utf-8"))
            if (rules_dir / "rules_meta.json").exists() else None,
        },
        "items": [],
    }

    with tempfile.TemporaryDirectory(prefix="fixtext_t04_") as td:
        work = Path(td)
        for cf in corpus_files:
            name = cf.name
            t0 = time.time()
            item = {"file": name, "corpus_sha256": sha256_file(cf)}

            # 语料完整性
            expect_sha = sha_by_file.get(name)
            corpus_ok = expect_sha in (None, item["corpus_sha256"]) if expect_sha is None else item["corpus_sha256"] == expect_sha
            if not corpus_ok:
                item["corpus_integrity"] = "FAIL（与 corpus_manifest.json 的 sha256 不一致）"
            else:
                item["corpus_integrity"] = "OK"

            # Go 引擎（上游原样）
            go_out = expected_dir / "go" / name if args.build else work / "go" / name
            go_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cf, go_out)
            p = run_cmd([str(go_bin), str(go_out), str(before_json), str(after_json), str(args.count)])
            if p.returncode != 0:
                print(f"[FAIL] {name}: Go 引擎退出码 {p.returncode}: {p.stderr.strip()[:200]}")
                results.append({**item, "go": "ERROR"})
                continue
            item["go"] = {"sha256": sha256_file(go_out), "bytes": go_out.stat().st_size}

            # PHP 后端（生产降级语义）
            php_out = expected_dir / "php" / name if args.build else work / "php" / name
            php_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cf, php_out)
            p = run_cmd([php, str(SCRIPT_DIR / "php_strtr.php"), str(before_json), str(after_json), str(php_out), str(args.count)])
            if p.returncode != 0:
                print(f"[FAIL] {name}: PHP 退出码 {p.returncode}: {p.stderr.strip()[:200]}")
                results.append({**item, "php": "ERROR"})
                continue
            try:
                php_stat = json.loads(p.stdout.strip().splitlines()[-1])
            except Exception:
                php_stat = {}
            item["php"] = {"sha256": sha256_file(php_out), "bytes": php_out.stat().st_size}

            # 命中计数（重放，并要求与 Go 输出逐字节一致）
            cnt_out = work / "cnt" / name
            cnt_out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cf, cnt_out)
            p = run_cmd([str(cnt_bin), str(before_json), str(after_json), str(cnt_out), str(args.count),
                         str(work / "cnt_stat.json")])
            if p.returncode != 0:
                print(f"[FAIL] {name}: count_hits 退出码 {p.returncode}: {p.stderr.strip()[:200]}")
                results.append({**item, "counts": "ERROR"})
                continue
            stat = json.loads((work / "cnt_stat.json").read_text(encoding="utf-8"))
            item["counts"] = {
                "replacements": stat["replacements"],
                "distinct_rules": stat["distinct_rules"],
                "hits_per_pass": stat["hits_per_pass"],
                "in_bytes": stat["in_bytes"],
                "out_bytes": stat["out_bytes"],
            }
            item["top_rules"] = stat["top_rules"][:10]
            cnt_matches_go = cnt_out.read_bytes() == go_out.read_bytes()
            item["count_replay_matches_go"] = cnt_matches_go

            # 引擎一致性：PHP == Go
            item["php_equals_go"] = php_out.read_bytes() == go_out.read_bytes()

            if args.build:
                baseline_manifest["items"].append(item)
                print(f"[冻结] {name:<34} {item['counts']['replacements']:>8} 次替换  php==go:{item['php_equals_go']}  计数重放一致:{cnt_matches_go}")
            else:
                exp_go = expected_dir / "go" / name
                exp_php = expected_dir / "php" / name
                ok = True
                go_ok = exp_go.exists() and exp_go.read_bytes() == go_out.read_bytes()
                php_ok = exp_php.exists() and exp_php.read_bytes() == php_out.read_bytes()
                counts_ok = True
                if BASELINE_MANIFEST.exists():
                    prev = {i["file"]: i for i in json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))["items"]}
                    if name in prev and "counts" in prev[name]:
                        counts_ok = prev[name]["counts"]["replacements"] == item["counts"]["replacements"]
                all_ok = go_ok and php_ok and item["php_equals_go"] and cnt_matches_go and counts_ok and corpus_ok
                n_ok += 1 if all_ok else 0
                item.update({"baseline_go_match": go_ok, "baseline_php_match": php_ok, "counts_match": counts_ok, "PASS": all_ok})
                print(f"[{'PASS' if all_ok else 'FAIL'}] {name:<34} go:{'✓' if go_ok else '✗'} php:{'✓' if php_ok else '✗'} "
                      f"php==go:{'✓' if item['php_equals_go'] else '✗'} 计数:{item['counts']['replacements']}"
                      f"{'✓' if counts_ok else '✗'} 计时{time.time() - t0:.1f}s")
            results.append(item)

    elapsed = time.time() - t_all
    print("-" * 96)
    summary = {
        "mode": "build" if args.build else "check",
        "replace_count": args.count,
        "corpus_files": len(corpus_files),
        "elapsed_s": round(elapsed, 1),
        "go_tool": tool_note,
    }
    if args.build:
        (BASE / "manifest" ).mkdir(exist_ok=True)
        (BASE / "manifest" / "baseline_manifest.json").write_text(
            json.dumps(baseline_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        agree = all(i.get("php_equals_go") for i in baseline_manifest["items"])
        replay = all(i.get("count_replay_matches_go") for i in baseline_manifest["items"])
        total_repl = sum(i["counts"]["replacements"] for i in baseline_manifest["items"])
        print(f"基线已冻结：{len(baseline_manifest['items'])} 个语料 · 共 {total_repl} 次替换 · "
              f"PHP 输出与 Go 全部逐字节一致：{agree} · 计数重放与 Go 全部一致：{replay}")
        summary.update({"frozen_items": len(baseline_manifest["items"]), "total_replacements": total_repl,
                        "php_equals_go_all": agree, "count_replay_all": replay})
        ok = agree and replay and len(baseline_manifest["items"]) == len(corpus_files)
    else:
        fails = [i for i in results if not i.get("PASS")]
        print(f"比对结论：{n_ok}/{len(corpus_files)} 通过，{len(fails)} 失败，耗时 {elapsed:.1f}s")
        ok = not fails and n_ok == len(corpus_files)
        summary.update({"pass": n_ok, "fail": len(fails),
                        "failed_files": [i["file"] for i in fails]})
        if fails:
            for i in fails:
                keys = [k for k, v in i.items() if v is False]
                print(f"  失败明细 {i['file']}: {keys}")

    summary["verdict"] = "PASS" if ok else "FAIL"
    if args.json:
        Path(args.json).write_text(
            json.dumps({"summary": summary, "items": results}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {args.json}")
    print(f"总判定：{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
