MRG.9 主干推进验收证据（2026-11-05，小组长独立实测）
====================================================
推进对象：
- 基线 dev HEAD da99f13（MRG.8，含 D4+D7+D3+E5+EX.1）
- D5 线：817bbc8 → 690ab76（V1.1-D5 批量事务写入与整批撤销，基线 da99f13）
- D5 为 MRG.8 之后唯一在途分支，本推进为快进（fast-forward），无并行分支合并、零冲突。
- 本提交为 MRG.9 证据提交（evidence/mrg9）。

包独立核验（小组长，干净 /tmp 解压）：
- md5 f967ba400c6246c1451de18552d07e5f 一致；69,802,555 B
- git HEAD 690ab76，链 817bbc8→690ab76→da99f13，工作区干净
- workspace/ 无 settings.ini（干净包门禁通过）

独立复跑测试（合并树，1 核沙箱分 11 批）：
- 专项：test_d5_transaction(17) + test_d3_preview_groups(21) + test_d4_preview_ui(10) + test_d7_export_csv(23) = 71 passed
- 全量 57 个测试文件分批跑完：927 passed / 4 skipped / 0 failed
  —— 与成员自报数字完全一致（批10 末尾 malloc_consolidate 为解释器退出堆噪声，无测试失败）
- 五批口径历史基线 492/0 已被本次全量 927/0 覆盖（全量为更强口径）

D5 核心验收点（成员证据 + 报告口径，逐字节 sha256 运行时真算）：
1. 失败回滚：磁盘截半 → rolled_back=True，磁盘字节与导入前 sha 相同，无半批无空还原点
2. 整批撤销：undo / undo_to 两路均逐字节回到导入前
3. 快照恢复：快照「操作前」载荷 == 导入前字节；恢复到此刻与导入后逐字节一致
4. 整批只占 1 个还原点；undo_import() 只复用 store.undo()/undo_to()，无另造撤销体系

已知既有问题（非本次引入）：
- C2+EX2b 合跑卡死为既有测试组合问题（单跑均全绿）
- tests/_smoke_history.py 为冒烟脚本非 pytest 文件，不计入清单
