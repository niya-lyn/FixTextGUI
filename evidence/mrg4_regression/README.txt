MRG.4 合并树五批全量回归（研发小组长实测，2026-11-04）

合并提交：ad92a7f（双亲 1cdce0e E3线 + 921b044 D1恢复重建线，基线 2faf5d7）
批次口径：与 tools/run_regression.sh 完全一致（固定文件列表，不含 D1/E3 新增测试文件）

结果：
  batch1  101 passed
  batch2   89 passed
  batch3  110 passed
  batch4   68 passed
  batch5  124 passed
  合计    492 passed / 0 failed

已知噪声：批量脚本运行时某批 pytest 进程在解释器收尾阶段 Segmentation fault
（EXIT=139），但该批用例已全部跑完且 passed（见各 batch*.log 末行）。
batch4 单独复跑：68 passed、EXIT=0。属偶发收尾问题，不影响用例结果。

专项合跑（同一棵合并树）：
  tests/test_d1_vocab_import.py + test_e3_manual_rules.py
  + test_c2_book_vocab_ui.py + test_t42_engine.py
  = 158 passed / 1 skipped / EXIT=0
