#!/usr/bin/env python3
"""FixText T0.2 · 步骤 8：正式 JSON 词库产物装配 + 自验

用法:
  python3 08_build_dict.py --clean-dir DIR --flat-dir DIR --base-export-dir DIR \
      --base-flat-dir DIR --manual-dir DIR --out-dir DIR --reports-dir DIR

做四件事：
  1) 用 Python 镜像实现复算"清洗后"的展开结果，与 PHP 权威展开逐条全量比对（清洗后口径）；
  2) 合并词条型变量生成规则集（沿用 P0 build_rules.py 的 Go 生产排序语义）；
  3) 装配正式 JSON 词库产物（清洗后原始值 + 展开值 + 规则 + 手动检索规则 + 索引清单）；
  4) 输出自验报告（口径对照如实记录，不强行凑一致）。
"""
import argparse
import json
import os
from itertools import product

# 与 P0 build_rules.py 同口径：参与合并的词条型变量（19 个）
WORD_VARS = [
    ('1.自定义词库.php', 'punctuationMap'),
    ('1.自定义词库.php', 'preprocessMap'),
    ('1.自定义词库.php', 'extraPreprocessMap'),
    ('1.自定义词库.php', 'normalMap'),
    ('1.自定义词库.php', 'extraMap'),
    ('1.自定义词库.php', 'strictMap'),
    ('1.自定义词库.php', 'postFixMap'),
    ('1.自定义词库_旧式、通假写法_.php', 'oldStyleMap'),
    ('2.繁转简词库.php', 't2sMap'),
    ('2.繁转简词库.php', 't2sRadicalMap'),
    ('2.繁转简词库.php', 'radicalsSupplementMap'),
    ('3.txtFormat 词库.php', 'txtFormatMap'),
    ('4.的地得词库.php', 'dddMap'),
    ('4.的地得词库.php', 'dei2deMap'),
    ('4.的地得词库.php', 'accurateDddMap'),
    ('5.临时校对表.php', 'tempMap'),
    ('7.生僻字词库.php', 'shengpiziMap'),
    ('7.生僻字词库_扩展区_.php', 'cjkExtMap'),
    ('7.生僻字词库_扩展区_.php', 'cjkRecoverMap'),
]


# ---------- PHP 语义镜像（与 Map.php / validate_migration.py 同源） ----------
def php_falsy(x):
    if x is None or x is False:
        return True
    if isinstance(x, (int, float)):
        return x == 0
    if isinstance(x, str):
        return x == '' or x == '0'
    if isinstance(x, (list, dict)):
        return len(x) == 0
    return False


def is_valid_word(w):
    if not isinstance(w, dict):
        return False
    if 'before' not in w or 'after' not in w:
        return False
    if (php_falsy(w['before']) and w['before'] != '0') or (php_falsy(w['after']) and w['after'] != '0'):
        return False
    return True


def create_word(before, after, word):
    elem = {'before': before, 'after': after, 'replaceHolder': word.get('replaceHolder', [])}
    if 'mark' in word:
        elem['mark'] = word['mark']
    return elem


def arr_values(x):
    return list(x.values()) if isinstance(x, dict) else x


def flatten_word(w):
    if not is_valid_word(w):
        return []
    after, before = w['after'], w['before']
    if isinstance(after, (list, dict)):
        if not isinstance(before, (list, dict)):
            raise ValueError('after 为数组时，before 必须也为数组')
        if len(after) != len(before):
            raise ValueError('after/before 数量不等')
        ret = []
        items = after.items() if isinstance(after, dict) else enumerate(after)
        for k, a in items:
            if php_falsy(a) and a != '0':
                continue
            ret.append(create_word(before[k], a, w))
        return ret
    if isinstance(before, (list, dict)):
        ret = []
        for b in arr_values(before):
            if php_falsy(b):
                continue
            ret.append(create_word(b, after, w))
        return ret
    return [create_word(before, after, w)]


def process_replace_holder(words):
    ret = []
    for word in words:
        rh = word.get('replaceHolder')
        if not rh:
            ret.append(word)
            continue
        holder_count = word['before'].count('@')
        if holder_count != len(rh):
            raise ValueError(f"replaceHolder 设置有误: {word['after']}")
        before_parts = word['before'].split('@')
        after_parts = word['after'].split('@')
        for combination in product(*rh):
            rb, ra = before_parts[0], after_parts[0]
            for i, c in enumerate(combination):
                rb += c + before_parts[i + 1]
                ra += c + after_parts[i + 1]
            rw = {'before': rb, 'after': ra}
            if 'mark' in word:
                rw['mark'] = word['mark']
            ret.append(rw)
    return ret


def flatten_maps(maps):
    if not maps:
        return []
    if isinstance(maps, list) and len(maps) > 0 and isinstance(maps[0], dict) and 'before' in maps[0]:
        maps = [maps]
    ret = []
    for m in maps:
        for w in m:
            ret.extend(flatten_word(w))
    return process_replace_holder(ret)


def safe_name(f):
    return f.replace('/', '_').replace('\\', '_').replace('【', '_').replace('】', '_')


def _var_names(entry):
    """PHP 空数组 json_encode 后是 []（list），有键时是 {}（dict），两种都要兼容"""
    if not isinstance(entry, dict):
        return []
    vs = entry.get('variables', {})
    if isinstance(vs, dict):
        return list(vs.keys())
    if isinstance(vs, list):
        return vs
    return []


def load_json(p):
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def build_rules(flat_dir, word_vars):
    """合并 + array_reverse + 按 before 字节长度稳定降序（Map.php → Go 生产顺序）"""
    merged = []
    per_var = {}
    missing = []
    for fname, var in word_vars:
        key = f'{safe_name(fname)}__{var}'
        p = os.path.join(flat_dir, f'flat_{key}.json')
        if not os.path.exists(p):
            missing.append(key)
            continue
        data = load_json(p)
        per_var[f'{fname}::{var}'] = len(data)
        merged.extend(data)
    merged.reverse()
    merged.sort(key=lambda w: len(w['before'].encode('utf-8')), reverse=True)
    return merged, per_var, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--clean-dir', required=True)
    ap.add_argument('--flat-dir', required=True)
    ap.add_argument('--base-export-dir', required=True)
    ap.add_argument('--base-flat-dir', required=True)
    ap.add_argument('--manual-dir', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--reports-dir', required=True)
    args = ap.parse_args()

    rules_dir = os.path.join(args.out_dir, 'rules')
    manual_out = os.path.join(args.out_dir, 'manual')
    for d in (rules_dir, manual_out):
        os.makedirs(d, exist_ok=True)

    # ---------- 1) 清洗后 Python 镜像 vs PHP 权威展开 ----------
    flat_meta = load_json(os.path.join(args.flat_dir, 'flat__meta__.json'))
    clean_meta = load_json(os.path.join(args.clean_dir, '__meta__.json'))
    clean_flat = []
    for key, fm in flat_meta.items():
        raw_p = os.path.join(args.clean_dir, f'{key}.json')
        php_p = os.path.join(args.flat_dir, f'flat_{key}.json')
        item = {'var': key, 'php_flat': fm['flat_count'], 'py_flat': None, 'verdict': None}
        if not os.path.exists(raw_p) or not os.path.exists(php_p):
            item['verdict'] = 'MISSING'
            clean_flat.append(item)
            continue
        raw = load_json(raw_p)
        try:
            py = flatten_maps(raw)
            item['py_flat'] = len(py)
            php = load_json(php_p)
            item['verdict'] = 'FULL_MATCH' if py == php else 'MISMATCH'
            if py != php:
                for i in range(max(len(py), len(php))):
                    a = py[i] if i < len(py) else None
                    b = php[i] if i < len(php) else None
                    if a != b:
                        item['diff_sample'] = [{'index': i, 'py': a, 'php': b}]
                        break
        except Exception as e:
            item['verdict'] = 'PY_ERROR'
            item['error'] = str(e)
        clean_flat.append(item)

    # ---------- 2) 规则集：基线（未清洗） vs 清洗后 ----------
    base_merged, base_per_var, base_missing = build_rules(args.base_flat_dir, WORD_VARS)
    clean_merged, clean_per_var, clean_missing = build_rules(args.flat_dir, WORD_VARS)

    def multiset_counts(merged):
        c = {}
        for w in merged:
            c[(w['before'], w['after'])] = c.get((w['before'], w['after']), 0) + 1
        return c

    base_c, clean_c = multiset_counts(base_merged), multiset_counts(clean_merged)
    removed = []
    for k, n in base_c.items():
        d = n - clean_c.get(k, 0)
        if d > 0:
            removed.append({'before': k[0], 'after': k[1], 'count': d})
    added = []
    for k, n in clean_c.items():
        d = n - base_c.get(k, 0)
        if d > 0:
            added.append({'before': k[0], 'after': k[1], 'count': d})

    with open(os.path.join(rules_dir, 'before.json'), 'w', encoding='utf-8') as fh:
        json.dump([w['before'] for w in clean_merged], fh, ensure_ascii=False)
    with open(os.path.join(rules_dir, 'after.json'), 'w', encoding='utf-8') as fh:
        json.dump([w['after'] for w in clean_merged], fh, ensure_ascii=False)
    with open(os.path.join(rules_dir, 'rules_full.json'), 'w', encoding='utf-8') as fh:
        json.dump(clean_merged, fh, ensure_ascii=False)

    len_dist = {}
    for w in clean_merged:
        n = len(w['before'].encode('utf-8'))
        len_dist[n] = len_dist.get(n, 0) + 1
    rules_meta = {
        'total_rules': len(clean_merged),
        'unique_before': len({w['before'] for w in clean_merged}),
        'per_var': clean_per_var,
        'before_byte_len_dist_top': dict(sorted(len_dist.items())[:10]),
        'max_before_bytes': max(len_dist) if len_dist else 0,
        'min_before_bytes': min(len_dist) if len_dist else 0,
        'baseline_total_rules': len(base_merged),
        'removed_by_cleaning': removed,
        'added_by_cleaning': added,
        'merge_vars': len(WORD_VARS),
    }
    with open(os.path.join(rules_dir, 'rules_meta.json'), 'w', encoding='utf-8') as fh:
        json.dump(rules_meta, fh, ensure_ascii=False, indent=2)

    # ---------- 3) 复制手动检索规则（扩展单元 B） ----------
    manual_files = {}
    for fn in ('manual_regex_rules.json', 'manual_rules_closure_manifest.json'):
        src = os.path.join(args.manual_dir, fn)
        if os.path.exists(src):
            with open(src, encoding='utf-8') as fh:
                data = fh.read()
            with open(os.path.join(manual_out, fn), 'w', encoding='utf-8') as fh:
                fh.write(data)
            manual_files[fn] = len(json.loads(data)) if fn.endswith('rules.json') else 'manifest'
    manual_manifest = {}
    mm_p = os.path.join(args.manual_dir, 'manual_rules_closure_manifest.json')
    if os.path.exists(mm_p):
        manual_manifest = load_json(mm_p)

    # ---------- 4) 索引清单 ----------
    base_meta = load_json(os.path.join(args.base_export_dir, '__meta__.json'))
    index = {
        'product': 'FixText 正式 JSON 词库（v1，T0.2）',
        'generated_by': 'FixText_T0.2 迁移工具链 run_migration.sh',
        'structure': {
            'cleaned/': '清洗后的词库原始变量（PHP 权威），每个文件一个变量一个 JSON',
            'flat/':    '清洗后按 Map.php 语义展开的词条（PHP 权威）',
            'rules/':   '合并后的替换规则：before.json / after.json / rules_full.json / rules_meta.json',
            'manual/':  '手动检索正则规则表（扩展单元 B，含闭包标注）',
            'index.json': '本清单',
        },
        'units': {},
        'baseline_meta': {f: {'variables': _var_names(v),
                              'return': v.get('return', {}).get('type') if isinstance(v.get('return'), dict) else None,
                              'closures': v.get('closures', [])}
                          for f, v in base_meta.items()},
        'word_vars': clean_per_var,
        'rules_meta': rules_meta,
        'manual_rules': manual_manifest,
    }
    for key, fm in flat_meta.items():
        cm = clean_meta.get(key, {})
        index['units'][key] = {
            'raw_count': cm.get('count'),
            'flat_count': fm.get('flat_count'),
            'cleaned': cm.get('cleaned', False),
            'type': cm.get('type'),
        }
    with open(os.path.join(args.out_dir, 'index.json'), 'w', encoding='utf-8') as fh:
        json.dump(index, fh, ensure_ascii=False, indent=2)

    # ---------- 5) 自验报告 ----------
    n_match = sum(1 for x in clean_flat if x['verdict'] == 'FULL_MATCH')
    n_total = len(clean_flat)
    report = {
        'cleaned_flatten_check': {
            'total_vars': n_total,
            'full_match': n_match,
            'mismatch': n_total - n_match,
            'details': clean_flat,
        },
        'rules': {
            'baseline_total': len(base_merged),
            'cleaned_total': len(clean_merged),
            'delta': len(clean_merged) - len(base_merged),
            'removed_by_cleaning': removed,
            'added_by_cleaning': added,
            'missing_base_vars': base_missing,
            'missing_clean_vars': clean_missing,
            'per_var': clean_per_var,
        },
    }
    with open(os.path.join(args.reports_dir, 'build_report.json'), 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print('BUILD DICT')
    print(f'  清洗后展开比对: {n_match}/{n_total} FULL_MATCH')
    for x in clean_flat:
        if x['verdict'] != 'FULL_MATCH':
            print(f"    [!!] {x['var']} {x['verdict']} {x.get('diff_sample', '')}")
    print(f'  规则数: 基线 {len(base_merged)} → 清洗后 {len(clean_merged)}（差 {len(clean_merged)-len(base_merged)}）')
    for r in removed:
        print(f"    [REMOVED] before={r['before']!r} after={r['after']!r} x{r['count']}")
    for a in added:
        print(f"    [ADDED]   before={a['before']!r} after={a['after']!r} x{a['count']}")
    print('BUILD DICT DONE')


if __name__ == '__main__':
    main()
