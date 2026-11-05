MRG.11 合并证据（2026-11-05，研发小组长独立验收）
合并提交 4c02f57，双亲 de59b44(E7)+340d2e5(E8)，基线 db066b2
两包 md5 实测：E7 da9f7fa389285695431bd7ed688ff199；E8 f9a23a456fd106cf33566df9d503ac66（与成员自报一致）
文件集交集为空；合并后 15 个改动文件 = 7+8 无夹带
独立复跑：专项 56 passed；全量 1024 passed / 4 skipped / 0 failed（= 968 基线 + 17 + 39）
冻结区：data/rules 与 pipeline/vendor 零变更；E8 未碰 UI
门禁：终版 zip 解压后 opens_on_first_run()=True，无 workspace 目录；排除项残留 0；Linux 引擎 755
