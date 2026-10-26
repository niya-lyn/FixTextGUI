# FixText（Python 重写版）

中文小说校对工具 FixText 的 Python 重写工程。本仓库当前处于 **T0.3 Go 引擎集成层**阶段：在 T0.1 工程骨架底座上，**接入了 Go 替换引擎的子进程调用层**（协议 / 客户端 / 离线构建），但**仍不含任何校对业务功能**。

- 上游规划：《FixText 第一版功能范围与开发排期》4.2 T0.1、3.5 重写注意事项；T0.3 Go 引擎集成层
- 技术基线：Python 3.11+ / PySide6；替换引擎 Go 为默认、Python greedy 为可选与降级路径（见排期 3.1 / 3.3）
- 引擎侧约束：Go 源码仅 import 5 个标准库，**离线可编译**（`GOPROXY=off`），构建不触网

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

## Go 引擎（默认替换引擎）

```bash
# 离线构建当前主机引擎（自动交叉编译 Windows 版）
python -m fixtext.engine.builder --both

# 端到端自验：Go 直跑 vs 集成层逐字节一致性 + 异常路径真实触发
python scripts/verify_engine_integration.py --count 2
```

调用方式：

```python
from fixtext.engine import EngineRequest, GoEngineClient, RuleSet

rules = RuleSet.from_files("rules/before.json", "rules/after.json")
resp = GoEngineClient().run(EngineRequest(rules=rules, input_data="甲甲", count=2))
if resp.ok:
    print(resp.result.sha256_out)
else:
    print(resp.error.code, resp.error.remedy)  # 14 个稳定错误码，见接口文档
```

协议字段、输入输出形态、错误码定义见 [`docs/T0.3-engine-protocol.md`](docs/T0.3-engine-protocol.md)；
逐项验收留痕见 [`docs/T0.3-self-verification.md`](docs/T0.3-self-verification.md)。

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
│   ├── engine/               # 替换引擎层：Go 子进程后端（本卡实现）、Python greedy 引擎（M1）
│   │   ├── __init__.py       #   统一导出
│   │   ├── errors.py         #   错误码常量 + 目录 + 异常 + stderr→码映射
│   │   ├── protocol.py       #   EngineRequest / EngineResult / EngineResponse + 静态校验
│   │   ├── client.py         #   GoEngineClient：子进程调度 / 临时工作区 / 结果交付
│   │   ├── builder.py        #   离线构建（零依赖自检 + 默认引擎路径解析）
│   │   └── go_src/           #   Go 引擎源码与构建产物
│   │       ├── replace_by_go.go  #   引擎源码（165 行，仅 5 个标准库 import）
│   │       ├── go.mod        #     module fixtext/engine
│   │       └── bin/          #     构建产物（带平台后缀）
│   └── storage/              # 存储层：工作区、快照、历史记录、词库持久化
├── tests/                    # pytest 单测（GUI 用例打 gui 标记，CI 走 offscreen）
│   ├── conftest.py           #   强制 QT_QPA_PLATFORM=offscreen 并注入 src 路径
│   ├── test_app_launch.py    #   启动 / 退出验收
│   ├── test_main_window.py   #   六入口与路由结构
│   ├── test_gate_checker.py  #   门禁脚本自身的有效性验证
│   ├── test_engine_protocol.py  # 引擎协议静态用例（25 个）
│   └── test_engine_client.py    # 引擎真实子进程用例（25 个，含 20MB 逐字节等价）
├── scripts/                  # 工程脚本（CI、门禁、冒烟、语料、自验）
│   ├── ci.py                 #   一键 CI 编排（跨平台，Windows/Linux 同一入口）
│   ├── ci.bat                #   Windows 双击入口
│   ├── check_gates.py        #   门禁静态检查（禁用依赖 + 分层约束）
│   ├── smoke_launch.py       #   独立进程启动冒烟（offscreen）
│   ├── build_corpus.py       #   真实语料取用与 20MB 切片
│   └── verify_engine_integration.py  # 端到端自验（等价性 + 异常路径 + 构建留痕）
├── corpus/                   # 真实语料与元数据（corpus_meta.json 记录来源与 sha256）
├── results/                  # 自验留痕（integration_verify.json）
├── docs/
│   ├── code-review-gates.md  # 代码评审门禁清单（含 3.5 四条固定检查项）
│   ├── T0.3-engine-protocol.md    # 引擎接口文档（协议字段 + 错误码定义）
│   └── T0.3-self-verification.md  # T0.3 逐项验收留痕
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
- 不做 Python greedy 引擎本体（属 M1）——`engine/` 层只做 Go 子进程调度，不含替换语义
- 不做基线集（属 T0.4）
- 不打包 exe（T4.1）

## 验收留痕

### T0.1 工程骨架

| 验收项 | 状态 | 说明 |
|-|-|-|
| 空壳应用 offscreen 启动并正常退出 | 已验证 | `scripts/smoke_launch.py` 独立进程验证，退出码 0 |
| 门禁清单入库 | 已验证 | `docs/code-review-gates.md` |
| lint 与单测入口一键跑通 | 已验证 | `scripts/ci.py` 四环节全 PASS |
| Windows 10/11 真机启动验证 | **未验证** | 当前环境为 Linux 容器，无 Windows 真机 |

### T0.3 Go 引擎集成层

| 验收项 | 状态 | 说明 |
|-|-|-|
| 离线 go build 出 Linux 二进制 | 已验证 | `GOPROXY=off` 下退出码 0，产物 2,646,016 B，耗时 0.18 s |
| Windows 交叉编译方法 | 已验证（编译侧） | `GOOS=windows GOARCH=amd64` 产出 PE 头 `MZ` 的 2,763,776 B 产物；**真机执行未验证** |
| 20MB 样例与 Go 直跑逐字节一致 | 已验证 | 20,971,524 B 切片，direct / FILE / MEMORY 三路 sha256 全等；另三份语料同样 IDENTICAL |
| 引擎进程缺失（E1001）真实触发 | 已验证 | 指向不存在路径，`results/integration_verify.json` 留痕 |
| 调用超时（E1003）真实触发 | 已验证 | `timeout_s=0.6`、实测 wall 0.715 s，同批对照组 300 s 超时成功 |
| 异常路径错误码覆盖 | 11/11 命中 | 另 3 个码为兜底/协议违约类，原因见自验文档 |
| 集成层并入 T0.1 骨架结构 | 已验证 | 位于 `src/fixtext/engine/`，分层门禁仍通过 |
| 产物上传云盘 projects/fix_text | 已验证 | `FixText_T0.3_Go引擎集成_v1.zip` |
| PySide6 GUI 用例 | **未执行（skip）** | 本环境未安装 PySide6 |
