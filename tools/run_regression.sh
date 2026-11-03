#!/usr/bin/env bash
# V1.1-F1（A 组入口卡）：全量回归跑批脚本。
#
# 为什么要分批而不是一把梭：
#   1 核沙箱里把 44 个 UI 测试文件合到一条 pytest 里会撞上 600s 上限；
#   5 批的切分是**按文件名字母序的连续段**（见下），和小组长实测基线
#   （dev 6c339f2，478 passed / 14 failed）的切分完全一致，
#   因此「改动前 / 改动后」两轮可以直接对账。
#
# 用法：
#   bash tools/run_regression.sh <日志目录>
# 退出码：任一批失败即返回非 0（脚本本身不判定通过，只负责跑完并留档）。
set -uo pipefail

PKG_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${1:-$PKG_ROOT/evidence/f1_regression}"
PY="${PYTHON:-/usr/local/bin/python3.12}"
SITE="/home/gem/.aily/.cli/py312/lib/python3.12/site-packages"

export PYTHONPATH="$SITE:$PKG_ROOT:$PKG_ROOT/fixtext_ui"
export QT_QPA_PLATFORM=offscreen
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

mkdir -p "$LOG_DIR"

B1="tests/test_atomic_write_win.py tests/test_encoding.py tests/test_engine_platform.py tests/test_error_center.py tests/test_ex2b_empty_states.py tests/test_ex3a_shelf.py tests/test_ex3b_linkage.py tests/test_ex4d_topbar_popup_anchor.py"
B2="tests/test_ex6_quotation_fixer.py tests/test_ex6_r2_check_page.py tests/test_ex6_r3_autofix_quote.py tests/test_ex7_ui_align.py tests/test_export_meta_rebind.py tests/test_export_resolve.py tests/test_first_run_wizard.py tests/test_import.py"
B3="tests/test_layout_cancel.py tests/test_m4ex5_unidiff.py tests/test_m5_ex1_runtime.py tests/test_m5_ex2_check_segments.py tests/test_m5_ex3_import.py tests/test_m5_ex4_1_layout.py tests/test_no_jargon.py tests/test_settings_module.py"
B4="tests/test_t12_vocab_states_ui.py tests/test_t13_disabled_filter.py tests/test_t210_check_inject.py tests/test_t210_history.py tests/test_t210_reexport_sha.py tests/test_t31_book_words.py tests/test_t31_vocab_merge_click.py tests/test_t31_vocab_store.py"
B5="tests/test_t31_vocab_ui.py tests/test_t32_vocab_safety.py tests/test_t33_book_words_ui.py tests/test_t34_snapshot.py tests/test_t37_vocab_bridge.py tests/test_t42_engine.py tests/test_word_states_migration_fix.py tests/test_word_states.py"

cd "$PKG_ROOT"
rc=0
for i in 1 2 3 4 5; do
    eval "files=\$B$i"
    echo "=== batch $i ===" | tee -a "$LOG_DIR/summary.txt"
    # shellcheck disable=SC2086
    "$PY" -m pytest $files -p no:cacheprovider -q >"$LOG_DIR/batch$i.log" 2>&1
    code=$?
    tail -3 "$LOG_DIR/batch$i.log" | tee -a "$LOG_DIR/summary.txt"
    [ $code -ne 0 ] && rc=$code
done
exit $rc
