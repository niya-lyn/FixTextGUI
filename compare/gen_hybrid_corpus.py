# -*- coding: utf-8 -*-
"""
生成"全尺寸混合语料"：把 3 个品牌的批注块追加到每个 T0.4 语料尾部，
让品牌闭包在真实语料全文规模上被完整触发（供 run_compare.py --corpus-hybrid 用）。

用法：
  python3 compare/gen_hybrid_corpus.py --corpus <T0.4 corpus 目录> --out <输出目录>

产出：每个语料 × {moonreader, calibre, weread} 各一份，共 15×3=45 个 .txt。
批注块格式严格取自 FixText/src/config/general.php 中 noteMatchPatterns 各键的注释示例。
"""

import argparse
from pathlib import Path

BLOCKS = {
    "moonreader": "\n书名 (高亮: 0; 标注: 2)\n\n───────────────\n\n◆ 第一章\n\n▪ 满纸荒唐言 (一把辛酸泪)\n\n▪ 都云作者痴 (谁解其中味)\n",
    "calibre": "\n路见不平一声吼\n2026/10/26 08:00\n\n该出手时就出手\n\n───\n\n# 第二节\n单纯划线没有批注\n\n───\n",
    "weread": "\n◆ 2026/01/01发表想法\n哀其不幸，怒其不争\n原文：我翻开历史一查\n\n◆ 纯划线：从来如此，便对么？\n-- 来自微信读书\n",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    for p in sorted(Path(args.corpus).glob("*.txt")):
        text = p.read_text(encoding="utf-8")
        for brand, block in BLOCKS.items():
            (out / f"{brand}__{p.name}").write_text(text + block, encoding="utf-8")
            count += 1
    print(f"生成混合语料 {count} 个 → {out}")


if __name__ == "__main__":
    main()
