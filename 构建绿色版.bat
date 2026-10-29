@echo off
rem 不开延迟展开：路径里若有 ! 字符，延迟展开会把它当变量吃掉
setlocal
chcp 65001 >nul 2>&1

rem =====================================================================
rem  FixText 绿色版一键构建（M4-T4.1b）
rem
rem  用法：把本文件放在源码包根目录，双击运行即可。
rem  产出：release\FixText_绿色版_v<版本>_<日期>.zip
rem
rem  每一步失败都会停下来给出人话提示，不会继续往下跑。
rem  本脚本**不会联网下载 Python**，只在缺失时告诉你去哪下载。
rem =====================================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "VERSION=v1"
set "REQ_MIN=3.11"
set "PY_URL=https://www.python.org/downloads/windows/"
set "DISTDIR=%ROOT%dist\FixText"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "DATE=%%i"
if "%DATE%"=="" set "DATE=unknown"

echo ==========================================================
echo   FixText 绿色版构建开始
echo   源码目录：%ROOT%
echo   构建日期：%DATE%
echo ==========================================================
echo.

rem ---------------------------------------------------------------------
rem 第 1 步：检查 Python 版本（3.11 及以上）
rem ---------------------------------------------------------------------
echo [1/7] 检查 Python 版本（需要 %REQ_MIN% 或更高）...
set "PY="
where py >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%v in ('py -3 --version 2^>nul') do set "PYVER=%%v"
    set "PY=py -3"
)
if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "tokens=*" %%v in ('python --version 2^>nul') do set "PYVER=%%v"
        set "PY=python"
    )
)
if not defined PY (
    echo.
    echo   [需要你操作] 这台电脑上没找到 Python。
    echo   请先安装 Python %REQ_MIN% 或更高版本，安装时务必勾选
    echo   "Add python.exe to PATH"，装完再双击本文件重试。
    echo.
    echo   官方下载地址（本脚本不会替你下载）：
    echo   %PY_URL%
    echo.
    pause
    exit /b 1
)

rem 从 "Python 3.12.4" 里取出主次版本号，逐项比较
set "PYM="
set "PYN="
for /f "tokens=2 delims= " %%a in ("%PYVER%") do (
    for /f "tokens=1,2 delims=." %%b in ("%%a") do (
        set "PYM=%%b"
        set "PYN=%%c"
    )
)
set "PYNUM=0"
if defined PYM if defined PYN set /a PYNUM=PYM*100+PYN
if not defined PYNUM set "PYNUM=0"
rem 版本号解析不出来时按「未知」处理：宁可停下让用户手动确认，也不硬跑
if %PYNUM% EQU 0 (
    echo.
    echo   [需要你操作] 无法识别 Python 版本（读到的输出："%PYVER%"）。
    echo   请打开命令行执行  python --version  确认它能正常运行，
    echo   或直接安装 %REQ_MIN% 以上的版本再重试：
    echo   %PY_URL%
    echo.
    pause
    exit /b 1
)
if %PYNUM% LSS 311 (
    echo.
    echo   [需要你操作] 当前 Python 版本太低：%PYVER%
    echo   本软件需要 %REQ_MIN% 或更高版本（界面依赖新版本的语言特性）。
    echo   请到下面地址下载新版，安装时勾选 "Add python.exe to PATH"：
    echo   %PY_URL%
    echo.
    pause
    exit /b 1
)
echo       已找到 %PYVER% —— 通过
echo.

rem ---------------------------------------------------------------------
rem 第 2 步：建独立虚拟环境（不污染你电脑上已有的 Python）
rem ---------------------------------------------------------------------
echo [2/7] 创建独立构建环境（.build_env）...
if exist "%ROOT%.build_env" (
    echo       复用已有的 .build_env
) else (
    %PY% -m venv "%ROOT%.build_env"
    if errorlevel 1 (
        echo.
        echo   [需要你操作] 创建构建环境失败。
        echo   最常见的原因是源码放在 OneDrive / 网盘同步目录里，
        echo   同步程序锁住文件导致创建失败。
        echo   办法：把整个源码包复制到本地磁盘（例如 D:\build\fixtext），
        echo   再双击本文件重试。
        echo.
        pause
        exit /b 1
    )
)
set "VENVPY=%ROOT%.build_env\Scripts\python.exe"
if not exist "%VENVPY%" (
    echo.
    echo   [需要你操作] 构建环境不完整：找不到 %VENVPY%
    echo   请删掉源码目录里的 .build_env 文件夹后重新运行本文件。
    echo.
    pause
    exit /b 1
)
echo       完成
echo.

rem ---------------------------------------------------------------------
rem 第 3 步：安装打包工具与运行依赖
rem ---------------------------------------------------------------------
echo [3/7] 安装打包工具与运行依赖（需要联网，可能要几分钟）...
"%VENVPY%" -m pip install --upgrade pip >nul 2>&1
"%VENVPY%" -m pip install pyinstaller
if errorlevel 1 (
    echo.
    echo   [需要你操作] 安装 pyinstaller 失败。
    echo   通常是网络问题。可以试这几种办法：
    echo     1. 确认能正常打开网页后重试；
    echo     2. 公司网络需要代理时，先设置环境变量 HTTP_PROXY / HTTPS_PROXY；
    echo     3. 国内网络可换成镜像源：
    echo        .build_env\Scripts\python.exe -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
)
if exist "%ROOT%requirements.txt" (
    "%VENVPY%" -m pip install -r "%ROOT%requirements.txt"
    if errorlevel 1 (
        echo.
        echo   [需要你操作] 安装运行依赖（requirements.txt）失败。
        echo   同上：先确认网络，再考虑换镜像源重试。
        echo.
        pause
        exit /b 1
    )
)
echo       完成
echo.

rem ---------------------------------------------------------------------
rem 第 4 步：打包（onedir 绿色版）
rem ---------------------------------------------------------------------
echo [4/7] 打包程序（PyInstaller onedir）...
if exist "%ROOT%build" rmdir /s /q "%ROOT%build"
if exist "%ROOT%dist" rmdir /s /q "%ROOT%dist"
"%VENVPY%" -m PyInstaller --noconfirm --clean fixtext.spec
if errorlevel 1 (
    echo.
    echo   [需要你操作] 打包失败。
    echo   请看上面最后 20 行报错。常见原因：
    echo     - 源码路径里有特殊字符或过长的中文路径 —— 换到 D:\build\fixtext 再试；
    echo     - 内存不足 —— 关掉其它占内存的程序后重试；
    echo     - 杀毒软件正在扫描 dist 目录 —— 把源码目录加入白名单后重试。
    echo.
    pause
    exit /b 1
)
if not exist "%DISTDIR%\FixText.exe" (
    echo.
    echo   [需要你操作] 打包没有产出 FixText.exe（%DISTDIR%）：
    echo   请把上面完整输出发给技术支持，这属于打包配置问题。
    echo.
    pause
    exit /b 1
)
echo       完成
echo.

rem ---------------------------------------------------------------------
rem 第 5 步：拷贝用户可见目录与目标平台引擎
rem ---------------------------------------------------------------------
echo [5/7] 拷贝词库、设计依据、示例书与替换引擎...
if not exist "%ROOT%data\rules" (
    echo.
    echo   [需要你操作] 找不到词库目录 data\rules。
    echo   源码包不完整，请重新解压一份完整的源码包再构建。
    echo.
    pause
    exit /b 1
)
xcopy /e /i /y /q "%ROOT%data\rules" "%DISTDIR%\data\rules" >nul
if errorlevel 1 goto :copyfail
if exist "%ROOT%reference" (
    xcopy /e /i /y /q "%ROOT%reference" "%DISTDIR%\reference" >nul
    if errorlevel 1 goto :copyfail
)
if exist "%ROOT%示例书" (
    xcopy /e /i /y /q "%ROOT%示例书" "%DISTDIR%\示例书" >nul
    if errorlevel 1 goto :copyfail
)

rem Windows 包**只带 Windows 引擎**，Linux 版一个字节都不带
set "ENGDIR=%DISTDIR%\pipeline\vendor\fixtext\engine\go_src\bin"
if not exist "%ENGDIR%" mkdir "%ENGDIR%"
set "ENGWIN=%ROOT%pipeline\vendor\fixtext\engine\go_src\bin\replace_by_go-windows-amd64.exe"
if not exist "%ENGWIN%" (
    echo.
    echo   [需要你操作] 找不到 Windows 替换引擎：
    echo   %ENGWIN%
    echo   源码包不完整，请重新解压一份完整的源码包再构建。
    echo.
    pause
    exit /b 1
)
copy /y "%ENGWIN%" "%ENGDIR%\" >nul
if errorlevel 1 goto :copyfail
rem 明确不带 Linux 引擎（避免包里两个平台并存导致取错）
if exist "%ENGDIR%\replace_by_go-linux-amd64" del /q "%ENGDIR%\replace_by_go-linux-amd64"
if exist "%ROOT%使用说明（绿色版）.txt" copy /y "%ROOT%使用说明（绿色版）.txt" "%DISTDIR%\" >nul
echo       完成
echo.

rem ---------------------------------------------------------------------
rem 第 5.5 步：确认包里没有夹带用户区 workspace/
rem ---------------------------------------------------------------------
rem  workspace/ 存的是「当前打开哪本书 / 看过向导没有」这类运行时状态。
rem  打进包会让新用户首次启动直接跳过新手向导，必须从中断构建。
if exist "%DISTDIR%\workspace" (
    echo.
    echo   [需要你操作] 打包结果里出现了 workspace 文件夹，构建已中止。
    echo   workspace 是运行时才生成的用户区（当前书籍 / 向导状态），
    echo   不能随包分发，否则新用户第一次打开会跳过新手向导。
    echo   这是打包配置问题，请把本文件与 fixtext.spec 一起发给技术支持。
    echo.
    pause
    exit /b 1
)
echo [5.5/7] 已确认包内不含 workspace/（用户区将首次启动时生成）
echo.

rem ---------------------------------------------------------------------
rem 第 6 步：自检（用打出来的程序自己验证一遍）
rem ---------------------------------------------------------------------
echo [6/7] 自检（程序自己检查词库、引擎与首启向导）...
rem FixText.exe 是窗口程序（没有控制台），它的屏幕输出不会出现在本窗口里，
rem 所以让程序自己把自检结果写成文件（--self-check-out），再把文件打印出来。
rem 只靠 "> 文件" 重定向在窗口程序上拿不到内容，这里必须用参数让程序写。
set "SELFCHK=%ROOT%release\self-check.txt"
if not exist "%ROOT%release" mkdir "%ROOT%release"
"%DISTDIR%\FixText.exe" --self-check --self-check-out "%SELFCHK%"
set "CHKRC=%ERRORLEVEL%"
if exist "%SELFCHK%" (
    type "%SELFCHK%"
) else (
    echo （自检没有生成结果文件，可能是程序启动失败或被杀毒软件拦截）
)
if %CHKRC% NEQ 0 (
    echo.
    echo   [需要你操作] 自检未通过，上面 JSON 里 ok=false 的那几项就是原因。
    echo   （完整结果也留在 release\self-check.txt，可直接发给技术支持）
    echo   最常见：替换引擎被杀毒软件隔离了。
    echo   办法：把 %DISTDIR% 加入杀毒软件白名单，重新运行本文件。
    echo.
    pause
    exit /b 1
)
echo       自检通过
echo.

rem ---------------------------------------------------------------------
rem 第 7 步：打 zip
rem ---------------------------------------------------------------------
echo [7/7] 打包成发布 zip...
set "RELDIR=%ROOT%release"
if not exist "%RELDIR%" mkdir "%RELDIR%"
set "ZIPNAME=FixText_绿色版_%VERSION%_%DATE%.zip"
set "ZIPPATH=%RELDIR%\%ZIPNAME%"
if exist "%ZIPPATH%" del /q "%ZIPPATH%"
powershell -NoProfile -Command "Compress-Archive -Path '%DISTDIR%' -DestinationPath '%ZIPPATH%' -CompressionLevel Optimal -Force"
if errorlevel 1 (
    echo.
    echo   [需要你操作] 压缩失败。
    echo   可能是 release 目录被占用 / 磁盘空间不足。
    echo   可以手动把 dist\FixText 整个文件夹打包成 zip，
    echo   效果一样（内部目录结构必须原样保留）。
    echo.
    pause
    exit /b 1
)
echo.
echo ==========================================================
echo   构建完成
echo   产物：%ZIPPATH%
echo.
echo   下一步：
echo     1. 自己先解压试跑一遍，确认能打开、能导入示例书；
echo     2. 再发给用户 / 上传到发布渠道。
echo ==========================================================
echo.
pause
exit /b 0

:copyfail
echo.
echo   [需要你操作] 拷贝文件失败。
echo   常见原因：目标目录被资源管理器 / 杀毒软件占用。
echo   办法：关掉正在浏览 dist 目录的窗口，把杀毒软件白名单加上后重试。
echo.
pause
exit /b 1
