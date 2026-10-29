# FixText M4-T4.5 · 杀软矩阵验收报告

- 日期：2026-10-29
- 包：`FixText_M4收尾_P1-7取消粒度_绿色版_windows.zip`
- 机器：Windows 11（本机）

## 结论

| 产品 | 结果 |
|---|---|
| 微软 Defender | **PASS**（命令行全盘扫 + 自检 + 788 章冒烟；无威胁记录） |
| 火绒安全软件 | **PASS**（实时防护下自检/冒烟 + **自定义查杀截图：未发现风险**） |
| 360 安全卫士 | **跳过**（主程序只打开官网，疑似流氓/残缺安装；用户明确不测） |

T4.5 在本机以 **Defender + 火绒** 关单；360 不纳入本轮矩阵。

---

## Defender（已测）

| 检查 | 结果 |
|---|---|
| `MpCmdRun` 扫整包 | found no threats |
| 威胁记录含 FixText/引擎 | 0 |
| self-check / 788 章 smoke | passed；引擎未丢 |

试跑目录：`C:\build\fixtext_t45_av\extract\FixText`  
证据：`evidence_t45/defender_self-check.json`、`defender_smoke.json`

## 火绒（已测）

| 检查 | 结果 |
|---|---|
| 进程 | `HipsTray` / `HipsDaemon`（`D:\Program Files\Huorong\...`） |
| 隔离目录 | 测前/后均为 0 文件 |
| `--self-check` / `--smoke` | passed；引擎仍在 |
| **自定义查杀（人工）** | **未发现风险**（对象 307 / 风险 0 / 用时 1s） |

截图：`evidence_t45/huorong.png`（界面文案：「本次扫描未发现风险」「扫描已完成」）  
其它证据：`huorong_self-check.json`、`huorong_smoke.json`  
试跑目录：`C:\build\fixtext_t45_huorong\extract\FixText`（冒烟）/ `...\fixtext_t45_av\extract\FixText`（界面扫）

## 360（跳过）

- 启动 `360Safe.exe` 与手动启动相同，只打开官网，无完整查杀 UI。
- 用户判定疑似流氓安装，**本项不做、不阻塞 T4.5 关单**。

## SHA256（同包）

- `FixText.exe`：`CBEEF4DC9D5B8BA40E90165A6DE3BDA9C6A624D35BB1334DF388C03191FB7BCE`
- `replace_by_go-windows-amd64.exe`：`868D535D420ECB4085E03E6F4F447985D31E13871D60206E346CAE4CB6CD1DFA`

## 关单状态

| 项 | 状态 |
|---|---|
| Defender | **PASS** |
| 火绒（含界面自定义查杀截图） | **PASS** |
| 360 | **跳过（用户决定）** |
| SmartScreen 人工截图 | 可选，未做 |

建议下一步：把 `已知缺口.md` 第 5 条改为「本机已测 Defender + 火绒，未隔离；360 未测」。需要的话我可以直接改并提交。
