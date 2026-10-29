#!/usr/bin/env bash
# 绿色试用包组装（Linux 侧镜像，对应 构建绿色版.bat 第 5 步）
#
# 与 .bat 的拷贝清单**逐条对齐**：
#   data/rules     出厂词库（只此一份，绝不从 workspace/ 来）
#   reference/     设计依据
#   示例书/        一本示例书
#   引擎二进制     只带**本平台那一个**
#   workspace/     一个字节都不带（存在即失败）
#
# 用法：SRC=<源码包根> OUT=<输出目录> bash tools/assemble_green.sh
set -u

SRC=${SRC:-$(cd "$(dirname "$0")/.." && pwd)}
OUT=${OUT:-/tmp/u/green}
DIST="$SRC/dist/FixText"
D="$OUT/FixText"

echo "SRC=$SRC"
echo "OUT=$OUT"

if [ ! -x "$DIST/FixText" ]; then
    echo "[FAIL] 找不到打包产物 $DIST/FixText，先跑 PyInstaller"
    exit 1
fi

rm -rf "$OUT"
mkdir -p "$OUT"
cp -a "$DIST" "$D"

# ---- 出厂词库（唯一来源 data/rules） -------------------------------------
if [ ! -d "$SRC/data/rules" ]; then
    echo "[FAIL] 找不到词库目录 data/rules"
    exit 1
fi
mkdir -p "$D/data"
cp -a "$SRC/data/rules" "$D/data/rules"

# ---- 设计依据 -----------------------------------------------------------
if [ -d "$SRC/reference" ]; then
    cp -a "$SRC/reference" "$D/reference"
fi

# ---- 示例书：源码包有 示例书/ 就用它，没有就从测试样例取一本 ------------
if [ -d "$SRC/示例书" ]; then
    cp -a "$SRC/示例书" "$D/示例书"
elif [ -f "$SRC/tests/samples/book_paohuo.epub" ]; then
    mkdir -p "$D/示例书"
    cp -a "$SRC/tests/samples/book_paohuo.epub" "$D/示例书/book_paohuo.epub"
else
    echo "[FAIL] 没有可放的示例书（示例书/ 与 tests/samples/book_paohuo.epub 都没有）"
    exit 1
fi

# ---- 引擎：只带本平台那一个 ---------------------------------------------
ENGDIR="$D/pipeline/vendor/fixtext/engine/go_src/bin"
mkdir -p "$ENGDIR"
case "$(uname -s)" in
    Linux*)  ENG=replace_by_go-linux-amd64 ;;
    Darwin*) ENG=replace_by_go-linux-amd64 ; echo "（macOS 无专用二进制，试打包按 linux 处理）" ;;
    *)       ENG=replace_by_go-windows-amd64.exe ;;
esac
SRCENG="$SRC/pipeline/vendor/fixtext/engine/go_src/bin/$ENG"
if [ ! -f "$SRCENG" ]; then
    echo "[FAIL] 找不到本平台引擎 $SRCENG"
    exit 1
fi
cp -a "$SRCENG" "$ENGDIR/"
chmod +x "$ENGDIR/$ENG"
# 明确剔除非本平台二进制
for other in replace_by_go-linux-amd64 replace_by_go-windows-amd64.exe; do
    [ "$other" = "$ENG" ] || rm -f "$ENGDIR/$other"
done
echo "引擎：$ENG（另一个已剔除）"

# ---- 使用说明 -----------------------------------------------------------
if [ -f "$SRC/使用说明（绿色版）.txt" ]; then
    cp -a "$SRC/使用说明（绿色版）.txt" "$D/"
else
    echo "[FAIL] 缺少 使用说明（绿色版）.txt"
    exit 1
fi

# ---- 打包冒烟模块以 .pyc 形式进包（正式版不带） -------------------------
python3.12 - "$SRC" "$D" <<'PY'
import compileall, sys
from pathlib import Path
src, dst = Path(sys.argv[1]), Path(sys.argv[2])
f = src / "fxbundle_smoke.py"
if not f.is_file():
    print("[FAIL] 缺少 fxbundle_smoke.py")
    sys.exit(1)
ok = compileall.compile_file(str(f), optimize=2, quiet=1, ddir=".")
if not ok:
    print("[FAIL] fxbundle_smoke.py 编译失败")
    sys.exit(1)
import py_compile
py_compile.compile(str(f), cfile=str(dst / "fxbundle_smoke.pyc"), doraise=True, optimize=2)
print("冒烟模块已编译为 .pyc（包内不含 .py 源码）")
PY
if [ $? -ne 0 ]; then exit 1; fi

# ---- 硬防线：包内不得出现 workspace/ -----------------------------------
if [ -e "$D/workspace" ]; then
    echo "[FAIL] 打包结果里出现了 workspace/ —— 用户区不能随包分发"
    ls -la "$D/workspace"
    exit 1
fi
echo "[OK] 已确认包内不含 workspace/"

# ---- 硬防线：包内不得有 .py 源码残留 ------------------------------------
CNT=$(find "$D" -name "*.py" -not -path "*/workspace/*" | wc -l)
echo "包内 .py 源码数：$CNT"
if [ "$CNT" -ne 0 ]; then
    echo "[FAIL] 包内仍有 .py 源码残留"
    find "$D" -name "*.py" -not -path "*/workspace/*"
    exit 1
fi

echo
echo "绿色试用包：$D"
du -sh "$D"
ls "$D"
