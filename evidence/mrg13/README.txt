MRG.13 合并证据（小组长独立实测，2026-11-05）
==============================================
基线：MRG.12 v3 规范历史 dev=44f05e9（tree 与 0fa797d 逐字节一致，实证 diff 为空）
合并：cherry-pick 双线（提交/信息保留、作者按规范改写）+ 两个 --no-ff 真合并节点
  - E9 线：e15c395→3e639fb→09e96a3 摘为 6bec90b→c19059b→dda546f，作者 Doubao Agent Engineer A
  - EX.2R 线：e882993→13ec0ac→8877b85 摘为 d8200fd→b5c2f8f→4179af7，作者 Doubao Agent Engineer B
  - 树对照：摘取后 dda546f vs 09e96a3、4179af7 vs 8877b85 diff 均为空（零丢失）
  - 合并提交：f9c25fe（merge E9）、6fde7f8（merge EX.2R）
  - 两线文件集交集为空（E9: report/tokens/main_window/oneclick/export/compare；EX.2R: vocab/widgets/settings/vocab_module）

验证（合并树 /tmp/mrg13/v3）：
1. E9 专项 test_e9_report_page.py：23 passed
2. EX.2R 词库五文件合批（t12/t31_merge/t31_ui/t32/t37）：66 passed（与成员自报一致）
3. verify_m2t21 门禁：4/4 全 PASS，扫描 3835 条命中 0、令牌 80/80 差异 0（EXIT=0）
4. 全量回归 62 文件：1049 passed / 4 skipped / 0 failed
   （分 8 块跑完；e2 系与 e7-e9 组合批出现退出段错误/malloc_consolidate 为基线既有 Qt 退出期噪声，用例全绿，
    E9 卡在纯基线 0fa797d 上已复现证明非本合并引入）

对照：E9 线成员自报 62 文件 1046 passed / 4 skipped；合并树 1049（EX.2R 修订 t31/t37 测试带来的计数变化）。
