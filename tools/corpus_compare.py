#!/usr/bin/env python3
"""语料级逐字节比对：Python 排版引擎 vs PHP 真实源码参考输出。

用法:
    python3 tools/corpus_compare.py [--ref-dir ../tmp/php_ref] [--out report.json]
"""
import argparse
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fixtext_layout.options import LayoutOptions  # noqa: E402
from fixtext_layout.engine import LayoutEngine  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, '..', '..', 'in', 'x_base',
                      'FixText_T0.4_回归基线集_v1', 'baseline', 'corpus')


def load(path):
    with io.open(path, 'r', encoding='utf-8', newline='') as f:
        return f.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref-dir', default=os.path.join(HERE, '..', '..', 'tmp', 'php_ref'))
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    opt = LayoutOptions(change_text_format=True, add_indentation=True, add_html_tag=0)
    engine = LayoutEngine(opt)

    rows = []
    identical = 0
    for name in sorted(os.listdir(CORPUS)):
        if not name.endswith('.txt'):
            continue
        base = name[:-4]
        ref_path = os.path.join(args.ref_dir, name)
        if not os.path.exists(ref_path):
            rows.append({'corpus': base, 'status': '缺参考输出', 'identical': False})
            continue
        src = load(os.path.join(CORPUS, name))
        ref = load(ref_path)
        t0 = time.time()
        got = engine.format(src)
        elapsed = time.time() - t0
        if got == ref:
            identical += 1
            rows.append({'corpus': base, 'status': '逐字节一致', 'identical': True,
                         'bytes': len(ref.encode('utf-8')), 'seconds': round(elapsed, 2)})
        else:
            # 定位第一个差异
            k = 0
            while k < min(len(got), len(ref)) and got[k] == ref[k]:
                k += 1
            rows.append({
                'corpus': base, 'status': '不一致', 'identical': False,
                'diff_offset': k, 'py_len': len(got), 'ref_len': len(ref),
                'py_context': repr(got[max(0, k - 30):k + 30]),
                'ref_context': repr(ref[max(0, k - 30):k + 30]),
            })
    report = {
        'config': 'changeTextFormat + addIndentation（与 php_harness/ref_format.php 相同口径）',
        'total': len(rows), 'identical': identical,
        'mismatched': len(rows) - identical,
        'rows': rows,
    }
    if args.out:
        with io.open(args.out, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    for r in rows:
        if r['identical']:
            print("  一致   %-28s %8d 字节  %.1fs" % (r['corpus'], r['bytes'], r['seconds']))
        else:
            print("  不一致 %-28s 偏移 %s" % (r['corpus'], r.get('diff_offset')))
            print("         py : %s" % r.get('py_context'))
            print("         ref: %s" % r.get('ref_context'))
    print("\n合计: %d/%d 逐字节一致" % (identical, len(rows)))
    return 0 if identical == len(rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
