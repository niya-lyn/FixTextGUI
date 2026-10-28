# M3-EX.1b Windows 引擎路径修复说明

## 问题
用户在 Windows 上点「一键校正」报：
`Go 引擎替换失败：E1002 启动引擎失败: OSError: [WinError 193] %1 不是有效的 Win32 应用程序`

原因：界面两处把替换引擎写死成 Linux 版 `replace_by_go-linux-amd64`，
没有按操作系统判断。包里两个平台的引擎都带了，所以 Windows 上
「文件存在」检查照样通过，一路放行到真正执行 ELF 时才炸。

## 改了什么
1. 新增 `pipeline/fixtext_pipeline/engine_selector.py` —— **全工程唯一的引擎选择入口**：
   - `win32` → `replace_by_go-windows-amd64.exe`
   - `linux` / `linux2` → `replace_by_go-linux-amd64`
   - 其他系统（macOS 等）→ `None`，并给出人话原因（不含 Linux 专属的 chmod 建议）
   - 关键点：**先按平台定文件名再看文件在不在**，不是「两个名字都试一遍、谁先存在用谁」。后者在两引擎并存的包里会让 Windows 又拿到 ELF。
2. `fixtext_ui/main_window.py`：新增 `_pick_engine()` 静态方法；`build_run_context`（一键校正）与 `_refresh_export_ctx`（历史页重新导出/继续）两处注入点都改走它。源码里已无任何写死的引擎文件名。
3. `pipeline/fixtext_pipeline/cli.py`：`discover_engine()` 改为委托同一入口，原来「先 Linux 后 Windows」的固定顺序已按平台修正。

## 验证（在 Linux 沙箱实测，非推测）
- `tools/probe_engine_platform.py`：win32→.exe、linux→ELF、linux2→ELF、darwin→None、freebsd13→None 全部通过；
  两个反向对照通过——「目录里只有 .exe 时 Windows 选到它」「目录里只有 ELF 时 Windows 返回 None（证明不回落 Linux）」。
- `tests/test_engine_platform.py` 8 项通过，其中最关键的 `test_build_run_context_injects_platform_engine`
  是**真的构造导入记录、真的调用主窗口 `build_run_context`**，断言 win32 下注入 `.exe`、linux 下注入 ELF
  —— 不是只测选择器自己。
- 全量测试：**212 passed**（基线 204 + 新增 8），无回归。
- 离屏启动 `QT_QPA_PLATFORM=offscreen python3.12 main_app.py`：13 秒后进程存活、stderr 为空。

## 仍然未验证（必须由你在 Windows 上确认）
**这个 `.exe` 从未在真实 Windows 上运行过。** 沙箱是 Linux，这一层在这里无法验证。
所以「Windows 一键校正能跑通」目前只是**代码路径正确 + 有单元与注入断言**，不等于真机通过。
请在你的 Windows 上重新点一次一键校正；如果还有报错，把完整 traceback 贴给我。

## 复现命令
```
python3.12 tools/probe_engine_platform.py
QT_QPA_PLATFORM=offscreen python3.12 -m pytest tests/test_engine_platform.py -q
```
