#!/usr/bin/env python3
"""全流程口径比对：normalizePunctuations + rmSpaces + pangu + formatHeadings 全开。"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fixtext_layout.options import LayoutOptions  # noqa: E402
from fixtext_layout.engine import LayoutEngine  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, '..', '..', 'in', 'x_base',
                      'FixText_T0.4_回归基线集_v1', 'baseline', 'corpus')
REF = os.path.join(HERE, '..', '..', 'tmp', 'php_ref_full')

NAMES = ['novel_fanpai_ch001-060', 'novel_quehun_ch001-060', 'pg24032_儒林外史',
         'pg27166_呐喊', 'pg51828_聊齋志異']

opt = LayoutOptions(
    rm_spaces_between_chn_chars=True,
    normalize_punctuations=True,
    change_text_format=True,
    add_indentation=True,
    format_headings=True,
    paranoid_text_spacing=True,
)
engine = LayoutEngine(opt)

ok = 0
for base in NAMES:
    src = io.open(os.path.join(CORPUS, base + '.txt'), encoding='utf-8', newline='').read()
    ref = io.open(os.path.join(REF, base + '.txt'), encoding='utf-8', newline='').read()
    got = engine.format(src)
    if got == ref:
        ok += 1
        print("  一致   %-28s %8d 字节" % (base, len(ref.encode('utf-8'))))
    else:
        k = 0
        while k < min(len(got), len(ref)) and got[k] == ref[k]:
            k += 1
        print("  不一致 %-28s 偏移 %d py_len=%d ref_len=%d" % (base, k, len(got), len(ref)))
        print("         py : %s" % repr(got[max(0, k - 40):k + 40]))
        print("         ref: %s" % repr(ref[max(0, k - 40):k + 40]))
print("\n合计: %d/%d 逐字节一致" % (ok, len(NAMES)))
sys.exit(0 if ok == len(NAMES) else 1)
