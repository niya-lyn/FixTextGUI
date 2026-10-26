@echo off
REM FixText 一键 CI（Windows 双击入口）
REM 等价于：python scripts\ci.py
setlocal
cd /d "%~dp0.."

set PYTHONIOENCODING=utf-8
set QT_QPA_PLATFORM=offscreen

where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] 未找到 python，请先安装 Python 3.11+ 并加入 PATH
    pause
    exit /b 1
)

python scripts\ci.py %*
if errorlevel 1 (
    echo.
    echo CI 未通过，请检查上方输出
    pause
    exit /b 1
)

echo.
echo CI 全部通过
pause
exit /b 0
