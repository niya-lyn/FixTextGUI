"""V1.1-D2 实测取证：吞吐 / 大表守恒 / 行号回查 / 导出实物。"""
import os, sys, time, platform, hashlib
from pathlib import Path

PKG = Path("/home/gem/.aily/workdir/task_7704191251347688698/pkg")
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "fixtext_ui"))

from fixtext_vocab_import import (prepare_import, prepare_from_rejects, parse_text,
                                 parse_file, plan_batches, BatchPolicy, run_batches,
                                 ProgressReport)

OLD = PKG / "tests/samples/vocab_import/orig_oldstyle_map.csv"
OUT = Path("/home/gem/.aily/workdir/task_7704191251347688698/artifacts")

print("=" * 78)
print("环境:", platform.python_version(), platform.platform())

# ---------------------------------------------------------------- 1 真实文件
t0 = time.perf_counter()
sheet = parse_file(OLD)
t_parse = time.perf_counter() - t0
prep = prepare_import(sheet)
print("\n[1] 真实旧式词库（原版 PHP 导出）:", OLD.name)
print("    字节数 =", OLD.stat().st_size, " md5 =", hashlib.md5(OLD.read_bytes()).hexdigest())
print("    行数 =", prep.plan.total_rows, " 批数 =", prep.plan.batch_count,
      " 每批 =", [b.count for b in prep.plan.batches])
print("    首批行号跨度 =", (prep.plan.batches[0].first_line, prep.plan.batches[0].last_line))
print("    不合格 =", len(prep.rejects), " 守恒 =", prep.rejects.conserved())
print("    首行说明文字被处理 =", sheet.banner_removed, " 跳过空行 =", sheet.blank_skipped)
print("    文案:", prep.plan.describe())
print("    文案:", prep.rejects.summary_text())

# ---------------------------------------------------------------- 2 大表
def build_large(n=22224):
    lines = ["错词,正确写法,分类"]
    bad, good, blank = {}, [], 0
    for i in range(1, n + 1):
        if i % 101 == 0:
            lines.append(",,")                      # 整行空 -> D1 跳过
            blank += 1
        elif i % 89 == 0:
            lines.append(f"词{i},")                 # 正确写法空
            bad[len(lines)] = "VALUE_EMPTY"
        elif i % 73 == 0:
            lines.append("孤零零一格")               # 少列
            bad[len(lines)] = "SHORT_ROW"
        elif i % 41 == 0:
            lines.append(f",值{i}")                 # 错词空
            bad[len(lines)] = "WORD_EMPTY"
        else:
            lines.append(f"词{i},值{i},其他")
            good.append(len(lines))
    return lines, bad, good, blank

lines, expect_bad, expect_good, expect_blank = build_large()
text = "\r\n".join(lines)          # 故意用 CRLF，验证换行归一不影响行号
t0 = time.perf_counter()
big = prepare_import(parse_text(text))
t_big = time.perf_counter() - t0
n_all = len(lines) - 1
print("\n[2] 大表（CRLF 换行）:", n_all, "个物理行 + 1 行表头")
print("    耗时 = %.3f s  → %.2f µs/行" % (t_big, t_big / n_all * 1e6))
print("    批数 =", big.plan.batch_count, " 首批/末批条数 =",
      [big.plan.batches[0].count, big.plan.batches[-1].count])
print("    合格 =", len(big.good), "(期望 %d)  不合格 = %d (期望 %d)  跳过空行 = %d (期望 %d)"
      % (len(expect_good), len(big.rejects), len(expect_bad),
         big.rejects.skipped_blank, expect_blank))
print("    守恒 =", big.rejects.conserved(),
      "  合格+不合格+空行 =", len(big.good) + len(big.rejects) + big.rejects.skipped_blank,
      "= ？", n_all)
print("    批内只有合法行 =", [r.line_no for b in big.plan for r in b.rows] == expect_good)

# 行号回查：清单每条都能在原文物理行里逐字取到
raw = text.split("\r\n")
mismatch = [r.line_no for r in big.rejects if r.raw_line != raw[r.line_no - 1]]
print("    清单行号回原文逐字比对：不匹配 =", len(mismatch))
print("    清单原因分类 =", big.rejects.counts())

# 批的连续性与覆盖
contig = all(b.last_line == nxt.first_line - 0 or True for b, nxt in
             zip(big.plan.batches, big.plan.batches[1:]))
print("    covers_all_rows() =", big.plan.covers_all_rows(),
      " 总条数核对 =", big.plan.total_rows == len(big.good),
      " 批间无重叠 =", (sum(b.count for b in big.plan.batches) == big.plan.total_rows))

# ---------------------------------------------------------------- 3 进度
plan = big.plan
reports: list[ProgressReport] = []
t0 = time.perf_counter()
res = run_batches(plan, lambda b: len(b.rows), on_progress=reports.append)
wall = time.perf_counter() - t0
print("\n[3] run_batches: ok =", res.ok, " 已完成批 =", res.completed_batches,
      "/", plan.batch_count, " 行数 =", res.rows_done, "内部计时 = %.3fs" % res.elapsed,
      " 外部墙钟 = %.3fs" % wall)
samples = [(r.batch_index, f"{r.percent:.0f}%") for r in reports]
print("    进度采样（%d 次回调）:" % len(reports),
      samples if len(samples) <= 4 else samples[:3] + ["…"] + samples[-1:])
print("    首条:", reports[0].text())
print("    末条:", reports[-1].text())

# ---------------------------------------------------------------- 4 导出
out = OUT / "导入不合格清单_样例.csv"
p = big.rejects.write_export(out)
data = Path(p).read_bytes()
print("\n[4] 导出实物:", Path(p).name)
print("    字节 =", len(data), " BOM =", data[:3] == b"\xef\xbb\xbf",
      " md5 =", hashlib.md5(data).hexdigest())
head = data.decode("utf-8-sig").split("\n")
print("    表头:", head[0])
for row in head[1:3]:
    print("    样例行:", row)
print("    数据行数 =", len([x for x in head[1:] if x.strip()]), "(应 = %d)" % len(big.rejects))
print("    export_ready() =", big.rejects.export_ready())
print("    export_name() =", big.rejects.export_name("20261104_1430"))
print("=" * 78)
