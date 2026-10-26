#!/usr/bin/env bash
# M1-T1.0 回归基线（304,255 口径）· 一键复现入口
#
# 用法：
#   ./run.sh                  # 验收比对模式：重跑 15 语料并与本包冻结输出比对
#   ./run.sh --build          # 重新冻结：用本包 rules/（304,255）重写 expected/ 与 manifest/
#   ./run.sh --verify-vs-old  # 与旧 304,256 口径冻结输出逐字节对比（需旧基线包，见下）
#
# 环境：php CLI + python3；go 工具链可选（缺失时用随包预编译 linux/amd64 二进制）
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="$HERE/baseline"

# 预编译二进制需要执行位（zip 解压后可能丢失）
chmod +x "$BASE/scripts/go/replace_by_go.bin" "$BASE/scripts/go/count_hits.bin" 2>/dev/null || true

cmd="${1:-}"
case "$cmd" in
  --build)
    exec python3 "$BASE/scripts/run_baseline.py" --build --json "$HERE/reports/build_rerun.json"
    ;;
  --verify-vs-old)
    OLD="${2:-}"
    if [ -z "$OLD" ] || [ ! -d "$OLD/expected/go" ]; then
      echo "用法: ./run.sh --verify-vs-old <旧基线目录（含 expected/go 与 expected/php）>" >&2
      exit 2
    fi
    echo "== 新冻结 vs 旧冻结 逐字节比对 =="
    diff -rq "$OLD/expected/go"  "$BASE/expected/go";  echo "go_diff_exit=$?"
    diff -rq "$OLD/expected/php" "$BASE/expected/php"; echo "php_diff_exit=$?"
    python3 - "$OLD" "$BASE" <<'PY'
import json, sys, pathlib
old, new = map(pathlib.Path, sys.argv[1:3])
om = json.loads((old/'manifest'/'baseline_manifest.json').read_text())
nm = json.loads((new/'manifest'/'baseline_manifest.json').read_text())
o = {i['file']: i for i in om['items']}; n = {i['file']: i for i in nm['items']}
print(f"规则条数: 旧 {om['rules']['meta']['total_rules']} -> 新 {nm['rules']['meta']['total_rules']}")
print(f"{'file':<34}{'go':>8}{'php':>8}{'cnt_old':>10}{'cnt_new':>10}")
diffs = []
for f, b in n.items():
    a = o[f]
    g = a['go']['sha256'] == b['go']['sha256']; p = a['php']['sha256'] == b['php']['sha256']
    co, cn = a['counts']['replacements'], b['counts']['replacements']
    print(f"{f:<34}{'same' if g else 'DIFF':>8}{'same' if p else 'DIFF':>8}{co:>10}{cn:>10}")
    if not (g and p and co == cn): diffs.append(f)
print()
print('差异条目数:', len(diffs), diffs)
print('总替换: 旧', sum(i['counts']['replacements'] for i in om['items']),
      '-> 新', sum(i['counts']['replacements'] for i in nm['items']))
PY
    ;;
  "")
    exec python3 "$BASE/scripts/run_baseline.py" --json "$HERE/reports/check_rerun.json"
    ;;
  *)
    echo "未知参数: $cmd（可用: --build / --verify-vs-old <旧基线目录> / 无参数）" >&2
    exit 2
    ;;
esac
