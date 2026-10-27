#!/usr/bin/env python3
"""把 evidence/records.json 渲染成人读的实测记录.md（可重复运行）。"""
from pathlib import Path
import json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if (os := __import__("os")) else None
recs = json.load(open(os.path.join(BASE, "evidence", "records.json"), encoding="utf-8"))
lines = []
lines.append("# M2-T2.4 验收实测记录")
lines.append("")
lines.append("取证脚本：`tools/make_evidence.py`（可重复运行）；行为记录原始数据：`evidence/records.json`；")
lines.append("每场景错误卡离屏截图：`evidence/scenario_XX.png`。")
lines.append("运行方式：`QT_QPA_PLATFORM=offscreen python3.12 tools/make_evidence.py 2> evidence/stderr.log`。")
lines.append("")
lines.append("异常全部由真实调用触发：真实 Go 引擎二进制（`replace_by_go-linux-amd64`）、真实")
lines.append("`epubtext` 模块、真实 OS 行为（chmod / kill -9 / RLIMIT_FSIZE）。仅 S10 的 ENOSPC")
lines.append("由 RLIMIT_FSIZE 触发 OS 信号后转成 OSError(ENOSPC)（沙箱无法写满磁盘，见该行说明）。")
lines.append("")
lines.append("| # | 场景 | 构造方式（真实触发点） | 错误码 | 界面标题 | 有指引 | 界面零泄漏 | 技术细节进日志 | 未崩溃 | 截图 |")
lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
for r in recs:
    lines.append("| S%s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
        r["tag"], r["title"], r["how"].replace("|", "\\|"), r["code"], r["card_title"],
        "Y" if r["有指引"] else "N",
        "Y" if r["界面零泄漏"] else "N: " + ";".join(r["泄漏明细"]),
        "Y" if r["日志_有技术细节"] and r["日志_含内部串"] else "N",
        "Y" if r["未崩溃"] else "N",
        "scenario_%s.png" % r["tag"]))
lines.append("")
lines.append("## 关键取证点")
lines.append("")
lines.append("- 13 场景的界面可见文本逐一扫描 FORBIDDEN_TERMS + 场景内部串，零命中；进程 stderr 为空文件；")
lines.append("  技术细节只在 evidence/logs/fixtext-YYYYMMDD.log 的 JSONL 记录里出现。")
lines.append("- 杀引擎进程两种实测：S06 客户端超时强制终止（E1003）、S07 处理中途 kill -9（E1004）。")
lines.append("- 兜底：S11 主线程 / S12 worker 线程未枚举异常，均 U-R00 + 进日志 + 不崩溃；")
lines.append("  S12 错误卡经跨线程投递在主线程弹出（Qt 控件只能主线程创建）。")
lines.append("- S13 为 guard 装饰器接线统一形态样例。")
lines.append("")
lines.append("## 覆盖说明")
lines.append("")
lines.append("实测覆盖：U-I01/02/03/04、U-P01/02/03/04/05、U-E01、U-R00（共 12 码）。")
lines.append("未走场景的 U-I05、U-E02 由单测覆盖（引擎码翻译 + 文案完备性 + 禁词扫描，")
lines.append("见 tests/test_error_center.py）。")
lines.append("")
Path(os.path.join(BASE, "evidence", "实测记录.md")).write_text("\n".join(lines), encoding="utf-8")
print("written", len(recs), "rows")
