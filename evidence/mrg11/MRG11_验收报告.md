# FixTextGUI MRG.11 验收报告

- 日期：2026-11-05
- 验收人：研发小组长（独立于两名交付成员）
- 基线：MRG.10 主干包 `db066b2`（token PdCHbz6QroEKnxx1ncpcPim9nge，md5 c9acee875ca92ac73f526fe2c71382b6）

## 一、合并对象

| 卡片 | 分支起点 | 包内 HEAD | 改动文件数 | md5 实测 | 与自报一致 |
|---|---|---|---|---|---|
| V1.1-E7 重复段落清单与处置（#254） | db066b2 | de59b44 | 7（全部 fixtext_ui/ + 1 测试） | da9f7fa389285695431bd7ed688ff199 | 是 |
| V1.1-E8 报告 GUI 数据读取（#257） | db066b2 | 340d2e5 | 8（fixtext_report/ 4 + fixtures 3 + 1 测试） | f9a23a456fd106cf33566df9d503ac66 | 是 |

两者同基线 `db066b2`，改动文件集**交集为空**（E7 只碰 `fixtext_ui/`，E8 只新增 `fixtext_report/`），实合并不冲突。

## 二、合并结果

- 合并提交 `4c02f57`，双亲实测 `de59b44`（E7）+ `340d2e5`（E8）
- 合并后改动文件集 = 15 个 = E7 的 7 个 + E8 的 8 个，逐一对得上，无夹带
- 合并树上 `git status` 干净

## 三、独立复跑（合并树上实测，非成员口述）

| 项目 | 结果 |
|---|---|
| 专项测试（E7 17 项 + E8 39 项） | **56 passed**，7.9s / 8.8s 两次一致 |
| 全量回归（61 个测试文件，分 17 批，每批 3–4 文件避 OOM） | **1024 passed / 4 skipped / 0 failed** |
| 全量账目核对 | 1024 = 基线 968 + E7 新增 17 + E8 新增 39，逐项对齐 |
| 4 项 skip | 与基线一致（环境性：3×e1 无真实运行产物、1×e3 原版 PHP 源码不在旁边） |
| 词库与引擎树变更（`data/rules` `pipeline/vendor`） | `git diff --stat` **为空**，零变更 |
| 冻结 UI 文件 | 仅 E7 的 6 个（check_module / duplicate_module / fixtext_duplicate_list / fixtext_duplicate_marks / fixtext_tokens / main_window）；E8 未碰任何界面文件 |

## 四、打包与门禁

- 终版包：`FixTextGUI_MRG11_合并E7E8主干_v1.zip`，71,154,618 B，md5 `813994de03c48ec9ed9cbe7869d3b285`
- 包内：1461 条目；`__pycache__` / `.pytest_cache` / workspace / runs / logs / 导出 **残留 0**；`.git` 保留（可 `git log` 复查）；Linux 引擎 `replace_by_go-linux-amd64` 执行位 **755**
- 首启门禁（直接解终版 zip、中性 CWD `/tmp`）：`opens_on_first_run() = True`，且解压后无 `workspace/` 目录（新用户首启能看到向导）
- 模块自检：`fixtext_report.parser`、`fixtext_duplicates` 在解包树可导入

## 五、两卡交付内容要点（成员成果，经我核对）

**E7（重复段落清单与处置）**
- 不新造导航入口：左轨仍 6 项，由检查页「批量操作」卡入口进平级路由页（与 E4 同一范式）
- 清单沿用 E6 的 `E-x`/`S-x` 稳定组号，四套定位口径（段序号 / 章节 / 行区间 / 字符偏移）逐行列示
- 跳转落在预览卡 `QTextCursor` 选中行区间 + 高亮 + `ensureCursorVisible()`，并 emit `jumpRequested`
- 处置状态机三态（未处置 / 标记 / 忽略），**不存在删除动作**（传 deleted/remove 直接 ValueError）；随书持久化到 `vocab/books/<书 id>/duplicate_marks.json`
- 实测抓到并修复真缺陷：未分章书的定位文案丢行号（原只有「未分章」三字），改为「未分章 · 第 24 行」
- 新增测试 17 项（16 + 该缺陷回归 1）

**E8（报告 GUI 数据读取）**
- 报告格式是现场跑真链路读出来的（炮火弧线 788 章），非猜测：CSV 为 BOM+CRLF 键值区+明细表，TXT 为 `['before' => ...]` 段
- 解析覆盖字段齐全（总量/命中/词库/明细/小节/异常），并给出 `top(n)`、`count_distribution()`、`search()` 等供 E9 消费
- 三处数字真实样本互相对齐：命中 2638 = 明细合计 2638；明细 2477 行 = TXT 序号分母 2477
- 20 例容错均不崩、均带行号人话（缺列 / 次数非数字 / 负数 / 空文件 / 非报告 / GBK / 非法字节 / 文件夹路径等）
- 一处诚实缺口：报告明细是带上下文的片段而非词库原词条，故 `hits_by_library()` 返回空并写明原因，不编造拆分
- 新增测试 39 项

## 六、已知事项与边界

1. **E7 跳转落点在预览卡内**，不是主编辑区；`jumpRequested` 已带全四套口径，正文区接收方属后续卡片范围。
2. **`test_e2_compare.py` 进程退出码非 0**（`malloc_consolidate` Qt 离屏收尾崩溃），但 20 个用例全过；在基线干净副本上复跑同一文件同样复现，属既有问题、非本两卡引入。
3. **E8 验收报告未落成云文档**（证据 JSON 完整），其报告以任务评论正文交付；本报告已覆盖其验收结论。
4. **UI 文件冻结前提已解除**：E7 动了 6 个界面文件。用户待上传的 UI 调整包若与这 6 个文件重叠，合并时以用户包为准、E7 改动需按新基线重接——届时需评估顺序。
5. 反馈 #17（锁定开关未置灰）等 UI 类问题仍在 UI 合并批次处理。

## 七、下一步

- 反馈 #14 词库重构卡：用户要求等 UI 调整包合并后再派。
- E9（报告界面呈现）依赖 E8 已完成，可派；但要动 UI，建议排在 UI 合并之后。
- 待用户上传 UI 调整包 → 小组长合并（MRG.12）→ 重排 E9 与词库重构。
