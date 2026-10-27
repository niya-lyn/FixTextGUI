# FixText M2-T2.4 · 人话错误体系（v1）

全应用统一错误出口：任何异常路径都不向用户暴露堆栈 / 异常类名 / 命令行输出；
每类错误有人话文案 + 下一步指引；技术细节只进诊断日志。

## 包内容

| 路径 | 内容 |
| --- | --- |
| `fixtext_error_center/` | 错误体系独立模块（后续各卡统一 import 的接缝，不改 `src/` 各页源码） |
| `docs/错误码映射表.md` | 14 个用户错误码 → 人话文案 + 指引全表；引擎码翻译表；接入指南 |
| `tests/test_error_center.py` | 28 项单测（映射表完备性 / 归类器 / report / guard / 日志 / 钩子） |
| `tools/make_evidence.py` | 验收实测取证脚本（13 个真实异常场景，可重复运行） |
| `tools/render_evidence.py` | 把 records.json 渲染成 evidence/实测记录.md |
| `tools/demo_wiring.py` | 接线演示（init + hooks + guard + worker 上报的最小可运行样例） |
| `evidence/` | 实测证据：13+1 张错误卡截图、records.json、实测记录.md、stderr.log、诊断日志 |

## 快速上手（接线方）

```python
import fixtext_error_center as error_center

error_center.init(log_dir=...)        # 诊断日志
error_center.install_app_hooks()      # 应用级兜底（sys/threading excepthook）
error_center.set_dialog_host(win)     # 错误卡挂靠主窗口

@error_center.guard                   # 槽函数：异常自动归类+日志+弹卡
def on_import_clicked(self): ...

raise error_center.UserFacingError("U-I02", safe_hint="《书名》.epub")   # 已判定时
error_center.report(exc, context="export", parent=self)                 # 主动上报
error_center.open_log_dir()                                            # 设置页：打开日志目录
```

## 测试与实测

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3.12 -m pytest tests/ -q     # 28 passed
QT_QPA_PLATFORM=offscreen python3.12 tools/make_evidence.py 2> evidence/stderr.log
```

实测结果见 `evidence/实测记录.md`（13/13 PASS，stderr 零输出）。
