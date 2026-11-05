#!/bin/bash
# D6 全量回归分批 runner：逐文件跑 pytest，进度落 progress.log，可续跑。
# 用法: bash tools/_run_all_d6.sh
cd "$(dirname "$0")/.."
export PYTHONPATH=/home/gem/.aily/.cli/py312/lib/python3.12/site-packages
export QT_QPA_PLATFORM=offscreen
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
PROG=../artifacts_progress_d6.log
touch "$PROG"
START=$(date +%s)
for f in tests/test_*.py; do
  grep -q "^DONE $f " "$PROG" && continue
  ELAPSED=$(( $(date +%s) - START ))
  if [ "$ELAPSED" -gt 500 ]; then
    echo "TIMEBOX HIT after ${ELAPSED}s, resume with another run"
    exit 42
  fi
  OUT=$(python3.12 -m pytest -q -p no:cacheprovider "$f" 2>&1)
  CODE=$?
  TAIL=$(echo "$OUT" | grep -E "passed|failed|error" | tail -1)
  echo "DONE $f EXIT=$CODE :: $TAIL" >> "$PROG"
done
echo "ALL FILES PROCESSED"
