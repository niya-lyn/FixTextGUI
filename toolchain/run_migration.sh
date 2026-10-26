#!/usr/bin/env bash
#
# FixText T0.2 · 词库 JSON 迁移 · 一键重跑入口
#
# 用法:
#   ./run_migration.sh                                  # 用 config/paths.env 的默认配置
#   ./run_migration.sh --src <FixText/src 目录> --out <输出目录>
#   ./run_migration.sh --php /path/to/php               # 指定 PHP 可执行文件
#   ./run_migration.sh --clean                          # 先清空输出目录再跑
#
# 流程（9 步，全部为脚本化、可重复执行）：
#   1) 01_export_maps.php        PHP 变量导出（含运行时闭包检测与报警）
#   2) 02_flatten_export.php     PHP 侧按 Map.php 语义展开（P0 口径基线）
#   3) 03_roundtrip_check.php    编解码往返一致性（P0 口径基线）
#   4) 04_validate_migration.py  Python 镜像 vs PHP 展开逐条全量比对（P0 口径基线）
#   5) 05_detect_closure_static.php  源码层闭包静态扫描 + 报警
#   6) 06_clean_and_flatten.php  strictMap 数据清洗 + 清洗后展开
#   7) 07_export_manual_rules.php 手动检索规则表迁移（扩展单元 B，闭包显式标注）
#   8) 08_build_dict.py          正式 JSON 词库产物装配 + 自验报告
#   9) 09_make_report.py         迁移报告生成（数字全部取自本次运行产物）
#
# 退出码：0 = 全部步骤完成；非 0 = 某步失败（详见 logs/migration.log）

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS="$HERE/scripts"

# ---------- 参数 ----------
SRC=""
OUT=""
PHP_OVERRIDE=""
CLEAN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --src)  SRC="$2"; shift 2;;
    --out)  OUT="$2"; shift 2;;
    --php)  PHP_OVERRIDE="$2"; shift 2;;
    --clean) CLEAN=1; shift;;
    -h|--help) sed -n '2,25p' "$0"; exit 0;;
    *) echo "未知参数: $1" >&2; exit 2;;
  esac
done

# ---------- 配置 ----------
# shellcheck disable=SC1091
source "$HERE/config/paths.env"
: "${SRC:=$DEFAULT_SRC}"
: "${OUT:=$DEFAULT_OUT}"
: "${PHP_BIN:=$DEFAULT_PHP}"

resolve_php() {
  if [[ -n "$PHP_OVERRIDE" && -x "$PHP_OVERRIDE" ]]; then echo "$PHP_OVERRIDE"; return 0; fi
  if [[ -n "$PHP_BIN" && -x "$PHP_BIN" ]]; then echo "$PHP_BIN"; return 0; fi
  if command -v php >/dev/null 2>&1; then command -v php; return 0; fi
  for cand in /home/gem/.aily/.cli/php/php /usr/local/bin/php /usr/bin/php /opt/homebrew/bin/php; do
    if [[ -x "$cand" ]]; then echo "$cand"; return 0; fi
  done
  return 1
}
if ! PHP_BIN="$(resolve_php)"; then
  echo "[FATAL] 找不到 PHP 可执行文件，请用 --php 指定，或安装 PHP 8.x" >&2
  exit 2
fi
if [[ ! -d "$SRC" ]]; then
  echo "[FATAL] 词库源码目录不存在: $SRC（可用 --src 指定 FixText/src）" >&2
  exit 2
fi

if [[ "$CLEAN" == "1" ]]; then rm -rf "$OUT"; fi
mkdir -p "$OUT"/{exported,flattened,manual,reports,logs} "$OUT"/dictionary/{cleaned,flat,rules,manual}

LOG="$OUT/logs/migration.log"
: > "$LOG"
ALARM_LOG="$OUT/logs/closure_alarm.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }
step() { log "--- 步骤 $1 ---"; }

log "FixText T0.2 词库迁移开始"
log "  PHP   : $PHP_BIN ($("$PHP_BIN" -r 'echo PHP_VERSION;'))"
log "  源码  : $SRC"
log "  输出  : $OUT"

step "1/9 导出词库变量（含运行时闭包检测）"
"$PHP_BIN" "$SCRIPTS/01_export_maps.php" "$SRC/maps" "$OUT/exported" --alarm-log "$ALARM_LOG" | tee -a "$LOG"

step "2/9 PHP 侧展开（P0 口径基线）"
"$PHP_BIN" "$SCRIPTS/02_flatten_export.php" "$SRC/maps" "$OUT/flattened" | tee -a "$LOG"

step "3/9 编解码往返一致性（P0 口径基线）"
"$PHP_BIN" "$SCRIPTS/03_roundtrip_check.php" "$SRC/maps" "$OUT/exported" "$OUT/reports/roundtrip_result.json" | tee -a "$LOG"

step "4/9 Python 镜像 vs PHP 展开全量比对（P0 口径基线）"
FT_EXP_DIR="$OUT/exported" FT_FLAT_DIR="$OUT/flattened" FT_VALIDATION_OUT="$OUT/reports/validation1_result.json" \
  python3 "$SCRIPTS/04_validate_migration.py" | tee -a "$LOG"

step "5/9 PHP 闭包静态扫描 + 报警（退出码 3 = 发现闭包并已留痕，非失败）"
set +e
"$PHP_BIN" "$SCRIPTS/05_detect_closure_static.php" "$SRC" "$OUT/reports" --alarm-log "$ALARM_LOG" | tee -a "$LOG"
static_rc=${PIPESTATUS[0]}
set -e
if [[ "$static_rc" != "0" && "$static_rc" != "3" ]]; then
  echo "[FATAL] 静态闭包扫描异常退出: $static_rc" | tee -a "$LOG"
  exit "$static_rc"
fi

step "6/9 strictMap 数据清洗 + 清洗后展开"
"$PHP_BIN" "$SCRIPTS/06_clean_and_flatten.php" "$SRC/maps" "$OUT/dictionary/cleaned" "$OUT/dictionary/flat" \
  --report "$OUT/reports/cleaning_report.json" | tee -a "$LOG"

step "7/9 手动检索规则表迁移（扩展单元 B）"
"$PHP_BIN" "$SCRIPTS/07_export_manual_rules.php" "$SRC" "$OUT/manual" --alarm-log "$ALARM_LOG" | tee -a "$LOG"

step "8/9 正式 JSON 词库产物装配 + 自验"
python3 "$SCRIPTS/08_build_dict.py" \
  --clean-dir "$OUT/dictionary/cleaned" \
  --flat-dir "$OUT/dictionary/flat" \
  --base-export-dir "$OUT/exported" \
  --base-flat-dir "$OUT/flattened" \
  --manual-dir "$OUT/manual" \
  --out-dir "$OUT/dictionary" \
  --reports-dir "$OUT/reports" | tee -a "$LOG"

step "9/9 生成迁移报告"
python3 "$SCRIPTS/09_make_report.py" --build-dir "$OUT" --out "$OUT/迁移报告.md" | tee -a "$LOG"

log "迁移完成。产物: $OUT/dictionary/index.json"
log "迁移报告: $OUT/迁移报告.md"
log "报警留痕: $ALARM_LOG"
exit 0
