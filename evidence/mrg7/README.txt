MRG.7 合并验收证据（2026-11-04，小组长独立实测）
====================================================
合并对象：
- 基线 dev HEAD 2ba5bf6（MRG.6，含 D3 17a2df5）
- E5 线：3051784（V1.1-E5-R1 已执行记忆与按书排除，父 4a8d06d）→ 合并提交 d3615fe，零冲突
- EX.1 线：2710520（V1.1-EX.1-R1 导出目录统一单层口径，父 4a8d06d）→ 合并提交 43b4280，零冲突
- 两线文件集不相交（E5: executed_rules/rule_memory/batch_confirm/book_scope/replace/manual_module+tests；EX.1: fixtext_paths/history_module/main_window/audit_t44+tests），与 D3 亦不重叠。

独立复跑测试（合并树 /tmp/mrg7/trunk）：
- E3+E4+E5 三组：78 passed, 1 skipped（6.63s）
- EX.1 定向（ex1_export_dir + export_meta_rebind + export_resolve + t210_history + t210_reexport_sha + m5_ex1_runtime）：56 passed（7.35s）
- D3 专项（d3_preview_groups + d3_preview_ui）：27 passed（25.46s）
- 五批全量回归：B1=101 / B2=89 / B3=110 / B4=68 / B5=124，共 492 passed 0 failed，run_regression.sh EXIT=0（本次 batch1 无段错误）
- 注意：tests/_smoke_history.py 为冒烟脚本非 pytest 文件，不计入清单

打包门禁：干净解压 + 中性 CWD 下 opens_on_first_run() = True（详见验收报告）

已知既有问题（非本次合并引入）：
- C2+EX2b 合跑会卡死为既有测试组合问题（单跑均全绿），五批清单不含该组合
