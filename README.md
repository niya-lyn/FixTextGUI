# FixText（Python 重写版）

中文小说校对工具 FixText 的 Python 重写工程。本仓库当前处于 **T0.1 工程骨架**阶段：**不含任何校对业务功能**，只提供工程底座、CI 与评审门禁。

- 上游规划：《FixText 第一版功能范围与开发排期》4.2 T0.1、3.5 重写注意事项
- 技术基线：Python 3.11+ / PySide6；替换引擎 Go 为默认、Python greedy 为可选与降级路径（见排期 3.1 / 3.3）

## 快速开始

```bash
# 1. 安装依赖（含开发工具）
python -m pip install -e ".[dev]"

# 2. 启动空壳应用（有显示器时）
python -m fixtext.app

# 3. 无头方式验证启动与退出（CI 口径）
python scripts/smoke_launch.py

# 4. 一键 CI：lint → format-check → gates → tests
python scripts/ci.py
```

Windows 下也可直接双击 `scripts/ci.bat`。

## 目录职责

```
fixtext/
├── src/fixtext/              # 应用源码（src 布局，安装后包名为 fixtext）
│   ├── app.py                # 入口：QApplication 装配 + 事件循环；含 --smoke-test
│   ├── common/               # 公共基础设施（跨层共享，无业务语义）
│   │   ├── app_meta.py       #   应用名、版本、首屏六入口标签
│   │   ├── paths.py          #   用户数据目录 / 日志目录解析（不写安装目录）
│   │   └── logging_setup.py  #   控制台 + 文件双通道日志初始化
│   ├── ui/                   # 界面层：窗口、面板、通用控件（可导入 PySide6）
│   │   └── main_window.py    #   主窗口骨架：六入口导航 + 占位面板 + 退出
│   ├── core/                 # 领域核心层：排版、引号检查、闭包重实现等业务逻辑
│   ├── engine/               # 替换引擎层：Go 子进程后端、Python greedy 引擎
│   └── storage/              # 存储层：工作区、快照、历史记录、词库持久化
├── tests/                    # pytest 单测（GUI 用例打 gui 标记，CI 走 offscreen）
│   ├── conftest.py           #   强制 QT_QPA_PLATFORM=offscreen 并注入 src 路径
│   ├── test_app_launch.py    #   启动 / 退出验收
│   ├── test_main_window.py   #   六入口与路由结构
│   └── test_gate_checker.py  #   门禁脚本自身的有效性验证
├── scripts/                  # 工程脚本（CI、门禁、冒烟）
│   ├── ci.py                 #   一键 CI 编排（跨平台，Windows/Linux 同一入口）
│   ├── ci.bat                #   Windows 双击入口
│   ├── check_gates.py        #   门禁静态检查（禁用依赖 + 分层约束）
│   └── smoke_launch.py       #   独立进程启动冒烟（offscreen）
├── docs/
│   └── code-review-gates.md  # 代码评审门禁清单（含 3.5 四条固定检查项）
├── .github/workflows/ci.yml  # CI 流水线定义（Linux + Windows 双平台）
└── pyproject.toml            # 依赖、ruff、pytest 配置
```

### 分层约定

| 层 | 可以依赖 | 不得依赖 | 原因 |
|-|-|-|-|
| `common` | 标准库 | 其它业务层 | 最底层，避免循环依赖 |
| `core` | `common` | PySide6 | 业务逻辑须能在无界面环境单测（门禁 S1） |
| `engine` | `common`、第三方引擎库 | PySide6 | 同上；且引擎语义须与 Go 逐字节对齐 |
| `storage` | `common` | `ui` | 存储不感知界面 |
| `ui` | `common`、`core`、`storage` | — | 界面是装配层 |

`scripts/check_gates.py` 会实际拦截 `core` / `engine` 中的 PySide6 导入。

## 本骨架明确不做的事

- 不实现导入、校正、引号检查、词库、导出、历史任一业务功能（占位页只声明归属任务卡）
- 不做词库迁移（T0.2）、不做引擎集成（T0.3）
- 不打包 exe（T4.1）

## 验收留痕（T0.1）

| 验收项 | 状态 | 说明 |
|-|-|-|
| 空壳应用 offscreen 启动并正常退出 | 已验证 | `scripts/smoke_launch.py` 独立进程验证，退出码 0 |
| 门禁清单入库 | 已验证 | `docs/code-review-gates.md` |
| lint 与单测入口一键跑通 | 已验证 | `scripts/ci.py` 四环节全 PASS |
| Windows 10/11 真机启动验证 | **未验证** | 当前环境为 Linux 容器，无 Windows 真机 |
