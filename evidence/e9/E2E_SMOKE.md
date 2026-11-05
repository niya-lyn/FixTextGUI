# V1.1-E9 端到端冒烟（2026-11-05，主窗真实构建）

环境：python3.12 + offscreen + FIXTEXT_SETTINGS_FILE=workspace/settings.ini（wizardSeen=1）

```
E2E-1 export-file entry: OK, rows = 2477 | where = 📄  替换报告
E2E-2 oneclick entry: OK
E2E-3 compare entry: OK
rail stays 6: OK
```

三个入口（导出结果卡文件直开 / 一键校正信号 / 前后对比按钮）全部真实切到
报告页并装载内容；左轨保持 6 项不变。

## 既有问题记录（非本卡引入）

`tests/test_e2_compare.py` 的 20 项断言全部通过，但 pytest 进程在解释器退出
阶段崩溃（malloc_consolidate / SIGSEGV，退出码 134/139）。已用 git worktree
在**纯基线 0fa797d（零改动）**上复现同样崩溃（20 passed, exit 134），证明为
基线既有的 Qt 退出期堆问题，与本卡改动无关。回归 runner 按退出码记该文件
FAIL，特此说明。
