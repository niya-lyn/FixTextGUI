MRG.10 合并证据（小组长 2026-11-05）
====================================

推进对象：合并 V1.1-D6（导入验收回归与底线核对，提交链 5fc0413→b42f6ed→aa7fd7e→9c678ea）
         与 V1.1-E6（重复段落检测算法与定位，提交链 5fc0413→2968ee8）。
合并提交：f6c58d9（双亲 9c678ea + 2968ee8，基线 5fc0413 = MRG.9）。
两分支改动文件集核对：D6 改 7 文件、E6 改 7 文件，交集为空（comm -12 无输出），合并零冲突。

独立复跑数字（合并树，非采信成员自报）：
1. 干净解压（git archive）+ 中性 CWD 门禁：预置 wizardSeen 后 opens_on_first_run()=False；干净树 =True。
2. 专项：tests/test_e6_duplicates_engine.py + test_e6_duplicates_model.py + test_d5_transaction.py = 58 passed（E6 40 + D5 18，D5 含 D6 新增 test_disabled_without_target_counts_once）。
3. 全量回归（git archive 树分 15 批 + 专项 d5）：
   collect 总数 972 = 基线 931 + D6 新增 1 + E6 新增 40，账目一致；
   门禁树（无 .git）967 passed / 5 skipped / 0 failed；带 .git 树上 e3_manual_rules 的「不在 git 仓库里」用例恢复运行（39 passed / 1 skipped），
   终版包口径 = 968 passed / 4 skipped / 0 failed（4 个 skip 均为环境性：3×e1 无真实运行产物、1×e3 原版 PHP 源码不在旁边）。
   注：门禁树上的第 5 个 skip 为 git archive 解压树无 .git 所致，非回归；终版包保留 .git 不受影响。
4. D6 端到端验收脚本合并树复跑：tools/accept_d6_e2e.py exit 0，整体结论 PASS（A/B/C + L1-L5），复跑控制台输出存本目录 accept_d6_rerun_on_merge.txt；
   复跑再生的 evidence/d6/* 已还原为 D6 提交版（git checkout），保持成员证据链原样。
5. 出厂词库与引擎零变更：git diff 5fc0413 HEAD --stat -- data/rules pipeline/vendor 无输出。

两包 md5 核对（下载后实测）：
- D6 包 889aa601d2daa412af90603e234d639c（与交付评论一致）
- E6 包 fcfb9023dd12f73778b94bb9408c2313（与交付评论一致）

已知事项：
- D6 卡纪律要求先传 v0.x 中间版，实际因轮次上限未传中间版直接传了 v1，中间状态由进展评论留痕（可接受）。
- E6 包 data/rules 文件清单口径（53 文件）与 D6 的 69 项运行时统计口径不同，两分支该目录相对 5fc0413 均零变更，以 git 为准，不构成差异。
