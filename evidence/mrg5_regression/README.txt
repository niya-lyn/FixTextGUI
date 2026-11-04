MRG.5 合并树回归证据（研发小组长实测，2026-11-04）

合并线：
  V1.1-D2 超限分批与不合格清单  提交 53a3a79（父 bb76955）
  V1.1-E4 手动检索逐批确认交互  提交 f4353c3（父 bb76955）
合并提交：e08fa44（D2）→ 其后 E4 合并提交（双亲 e08fa44 + f4353c3）
基线：bb76955（MRG.4）

五批全量回归（口径与 tools/run_regression.sh 完全一致，固定文件清单不含新增测试文件）：
  batch1  101 passed (188.60s)
  batch2   89 passed
  batch3  110 passed
  batch4   68 passed
  batch5  124 passed
  合计    492 passed / 0 failed

已知噪声（与 MRG.4 同源、非本次引入）：批量脚本在最后一批跑完后的解释器收尾阶段
报告 Segmentation fault，脚本 EXIT=139。各批用例已全部跑完且 passed，见各 batch*.log
末行。逐批结果不受影响。

专项合跑（同一棵合并树）：
  test_d1_vocab_import + test_d2_batching_rejects
  + test_e3_manual_rules + test_e4_batch_confirm
  = 202 passed / 1 skipped
  test_t42_engine = 27 passed
  test_c2_book_vocab_ui = 17 passed

备注：六文件一次性合跑曾在 300s 超时（C2 界面用例较慢且与批量 pytest 组合放大耗时），
拆为「四卡(202/1skip) + T4.2(27) + C2(17)」三组分别跑，均按上表通过。
