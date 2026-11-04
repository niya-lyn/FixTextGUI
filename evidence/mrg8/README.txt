MRG.8 合并验收证据（2026-11-04，小组长独立实测）
====================================================
合并对象：
- 基线 dev HEAD 145f01a（MRG.7，含 E5+EX.1+D3）
- D7 线：dedcda0 → 1aa2672 → b696f75（V1.1-D7 导出备份 CSV，基线 145f01a）已在树内
- D4 线：4ef14bf（V1.1-D4 冲突处置与确认执行，基线 2ba5bf6=MRG.6）→ 合并提交 321b85c，零冲突
- 文件集不相交：D4 改 preview_module/fixtext_vocab_preview/groups+word_states 接线；D7 新增 fixtext_vocab_export/vocab_module 入口；与 E5/EX.1/D3 均不重叠。

独立复跑测试（合并树）：
- D4 专项 29 + D3 专项 27 + D7 专项 23 = 79 passed（45.07s）
- D7 包独立复跑：test_d7_export_csv 23 passed
- D4 包独立复跑：D3+D4 56 passed（52.33s）
- 五批全量回归：B1=101 / B2=89 / B3=110 / B4=68 / B5=124，共 492 passed 0 failed
  （脚本 EXIT=139 为 batch1 收尾段错误已知噪声，MRG.6 起同源；batch1 内 101 用例全绿）

D4 口径裁定（小组长）：「更新 Y」= 改值撞库内同词异值时更新该条值（custom.update），同词同值改值按跳过记账——采纳成员自定口径，已写入其验收报告第四节。

打包门禁：干净解压 + 中性 CWD 下 opens_on_first_run() = True（详见验收报告）

已知既有问题（非本次合并引入）：
- C2+EX2b 合跑卡死为既有测试组合问题（单跑均全绿）
- tests/_smoke_history.py 为冒烟脚本非 pytest 文件，不计入清单
