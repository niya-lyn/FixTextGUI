MRG.6 合并验收证据（小组长独立复跑，2026-11-04）

合并对象：V1.1-D3 导入预览分组与查重分组（提交 17a2df5，父 4a8d06d=MRG.5 dev HEAD，
作者 Doubao Agent Engineer A <doubao-engineer-a@local>，单提交，工作树干净）。
合并方式：fast-forward（17a2df5 的父即 dev HEAD，无冲突面）。
包：FixTextGUI_V1.1-D3_v1.zip，68,494,103 B，md5 e79a74a9acae5b25fb6c2a445dc78de8（下载回读一致）。

【D3 专项复跑】
- test_d3_preview_groups.py + test_d3_preview_ui.py：27 passed（24.12s）
- D1+D2+E4 合跑（test_d1_vocab_import / test_d2_batching_rejects / test_e4_batch_confirm）：163 passed（4.28s）
- t31 四件（book_words / vocab_store / vocab_merge_click / vocab_ui）：26 + 17 passed
- t32_vocab_safety + t12_vocab_states_ui：36 passed（22.86s）
- ex2b_empty_states 单跑：10 passed（0.61s）；c2_book_vocab_ui 单跑：17 passed（11.52s）

【已知测试组合问题（非 D3 引入）】
test_c2_book_vocab_ui.py 与 test_ex2b_empty_states.py 合跑会卡死（500s+ 无输出），
两文件各自单跑均全绿、秒级完成。MRG.5 时六文件合跑亦曾 300s 超时拆组分跑，同源。
本轮口径：合跑不做，各自单跑计成绩。

【五批全量回归（tools/run_regression.sh 固定清单，逐批单独执行）】
- batch1：101 passed（189.70s，EXIT=139 收尾段错误=已知噪声，用例全绿，MRG.4/MRG.5 同源）
- batch2：89 passed（3.91s）
- batch3：110 passed（4.10s）
- batch4：68 passed（24.07s）
- batch5：124 passed（55.65s）
合计 492 passed / 0 failed，与 MRG.5 基线（492/0）完全一致。

【固定清单外专项】
- test_e3_manual_rules.py：39 passed, 1 skipped
- test_c2_book_vocab_ui.py：17 passed

【D3 关键验收点核验】
- 冲突判定收敛：fixtext_vocab.conflict_list 为模块级唯一实现（单条 conflicts_for_add
  与批量 conflicts_for_add_many 均转调），未新写比对逻辑。
- 预览 vs 预演数字对照（成员实测，样表 7 行）：新增 2/2、冲突 3/3、不合格 1/1、
  被改动 0/0、被删除 0/0，全一致；预演写落在 custom_vocab.json 临时副本，
  真实库指纹前后不变（da529a48… → da529a48…）。
- 逐条取消：取消行不再出现在任何分组；取消同表重复的前一条后，后一条从「冲突」
  自动重判为「新增」（防「预览说冲突、真导入却写入」）。
- 性能改动报备核实：fixtext_vocab.py 的 exact_word/exact_value 加词/值惰性索引
  （判定语义未变，边界照抄，抽样单测钉住）；t31/t32/t12 词库套件全绿佐证无回归。

【遗留】
- E5（已执行记忆）上轮轮次耗尽：代码主体在 v0.5 包（VlgjbMSiHoDvgMxG2CtcCjfsnZg），
  缺 manual_module 界面与测试；已派 E5-R1 收尾卡（task 7704249293800000780），
  回来后 MRG.7 合并。
- EX.1-R1（导出目录统一）运行中，用户将手动取消。
