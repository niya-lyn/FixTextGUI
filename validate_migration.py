#!/usr/bin/env python3
"""FixText 验证一：词库迁移一致性验证（Python 侧）

1. JSON 回读：exported/*.json 全量 json.loads，验证 PHP json_encode → Python json.loads 往返无损
2. 条目数对照：Python len() vs PHP meta 记录的 count
3. 结构校验：词条型 *Map 的 before/after/mark 结构合法性
4. 语义比对：Python 镜像实现 Map.php flattenWord/processReplaceHolder，
   与 PHP 真实展开结果（flattened/flat_*.json）逐条全量比对
"""
import json
import os
import sys
from itertools import product

BASE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.join(BASE, 'exported')
FLAT = os.path.join(BASE, 'flattened')

# ---------- PHP 语义工具 ----------

def php_falsy(x):
    """PHP 的布尔取反语义（针对 JSON 反序列化后的值）"""
    if x is None or x is False:
        return True
    if isinstance(x, float) or isinstance(x, int):
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
    elem = {
        'before': before,
        'after': after,
        'replaceHolder': word.get('replaceHolder', []),
    }
    if 'mark' in word:
        elem['mark'] = word['mark']
    return elem


def is_array(x):
    """PHP is_array：list 和 dict 都算数组（dict 键被 foreach 忽略）"""
    return isinstance(x, (list, dict))


def arr_values(x):
    """PHP foreach 数组：按插入序取值，键被忽略"""
    return list(x.values()) if isinstance(x, dict) else x


def flatten_word(w):
    if not is_valid_word(w):
        return []
    after, before = w['after'], w['before']
    if is_array(after):
        if not is_array(before):
            raise ValueError('after 为数组时，before 必须也为数组')
        if len(after) != len(before):
            raise ValueError('after/before 数量不等')
        ret = []
        after_items = after.items() if isinstance(after, dict) else enumerate(after)
        for k, a in after_items:  # PHP foreach $k => $after，键用于配对 before
            if php_falsy(a) and a != '0':
                continue
            ret.append(create_word(before[k], a, w))
        return ret
    if is_array(before):
        ret = []
        for b in arr_values(before):
            if php_falsy(b):  # 注意：此处 "0" 也会被跳过（与 PHP 一致）
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
        holder_mark = '@'
        holder_count = word['before'].count(holder_mark)  # PHP mb_substr_count 等价（单字节字符）
        if holder_count != len(rh):
            raise ValueError(f"replaceHolder 设置有误: {word['after']}")
        before_parts = word['before'].split(holder_mark)
        after_parts = word['after'].split(holder_mark)
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
        maps = [maps]  # 自动包装
    ret = []
    for m in maps:
        for w in m:
            ret.extend(flatten_word(w))
    return process_replace_holder(ret)

# ---------- 验证流程 ----------

def main():
    meta = json.load(open(os.path.join(EXP, '__meta__.json'), encoding='utf-8'))
    flat_meta = json.load(open(os.path.join(FLAT, 'flat__meta__.json'), encoding='utf-8'))

    report = {'roundtrip': [], 'counts': [], 'structure': [], 'flatten': [], 'errors': []}

    # 1+2+3: JSON 回读 + 条目数对照 + 结构校验
    for fname, entry in meta.items():
        if 'error' in entry:
            report['errors'].append(f'{fname}: PHP include 失败 {entry["error"]}')
            continue
        safe = fname.replace('/', '_').replace('\\', '_').replace('【', '_').replace('】', '_')
        variables = entry.get('variables') if isinstance(entry.get('variables'), dict) else {}
        for vname, vinfo in variables.items():
            if not vinfo.get('exported'):
                continue
            jf = os.path.join(EXP, f'{safe}__{vname}.json')
            try:
                data = json.load(open(jf, encoding='utf-8'))
            except Exception as e:
                report['errors'].append(f'{fname}::{vname}: Python json.loads 失败: {e}')
                continue
            # 条目数对照
            py_count = len(data) if isinstance(data, (list, dict)) else None
            ok_count = (py_count == vinfo.get('count')) if vinfo.get('type') == 'array' else True
            report['counts'].append({
                'file': fname, 'var': vname, 'php_count': vinfo.get('count'),
                'py_count': py_count, 'match': ok_count,
            })
            # 结构校验（词条型 *Map 且为 list）
            if vname.endswith('Map') and isinstance(data, list) and len(data) > 0:
                bad_keys = 0
                bad_types = 0
                for w in data:
                    if not isinstance(w, dict):
                        bad_types += 1
                        continue
                    ks = set(w.keys())
                    core = {'before', 'after'} & ks
                    if not core:
                        # regexMap 等非词条型条目：允许（标记说明）
                        bad_keys += 1
                    b, a = w.get('before'), w.get('after')
                    if b is not None and not (isinstance(b, str) or isinstance(b, list) or isinstance(b, int) or isinstance(b, float)):
                        bad_types += 1
                    if a is not None and not (isinstance(a, str) or isinstance(a, list) or isinstance(a, int) or isinstance(a, float)):
                        bad_types += 1
                report['structure'].append({
                    'file': fname, 'var': vname, 'entries': len(data),
                    'non_word_entries': bad_keys, 'bad_types': bad_types,
                })

    # 4: flatten 语义全量比对
    py_flat_cache = {}
    for fname, entry in meta.items():
        if 'error' in entry:
            continue
        safe = fname.replace('/', '_').replace('\\', '_').replace('【', '_').replace('】', '_')
        variables = entry.get('variables') if isinstance(entry.get('variables'), dict) else {}
        for vname, vinfo in variables.items():
            if not vname.endswith('Map') or not vinfo.get('exported'):
                continue
            key = f'{safe}__{vname}'
            if key not in flat_meta:
                continue
            raw = json.load(open(os.path.join(EXP, f'{safe}__{vname}.json'), encoding='utf-8'))
            try:
                py_flat = flatten_maps(raw)
                py_err = None
            except Exception as e:
                py_flat, py_err = None, str(e)
            fmeta = flat_meta[key]
            php_flat = None
            ffile = os.path.join(FLAT, f'flat_{key}.json')
            if fmeta['flat_count'] is not None:
                php_flat = json.load(open(ffile, encoding='utf-8'))
            item = {
                'var': key, 'raw': fmeta['raw_count'],
                'php_flat': fmeta['flat_count'],
                'py_flat': len(py_flat) if py_flat is not None else None,
                'php_err': fmeta['error'], 'py_err': py_err,
            }
            if py_err or fmeta['error']:
                item['verdict'] = 'BOTH_ERROR_MATCH' if (py_err and fmeta['error']) else 'ERROR_MISMATCH'
            else:
                if py_flat == php_flat:
                    item['verdict'] = 'FULL_MATCH'
                else:
                    # 找出差异条目
                    diffs = []
                    n = max(len(py_flat), len(php_flat))
                    for i in range(n):
                        a = py_flat[i] if i < len(py_flat) else None
                        b = php_flat[i] if i < len(php_flat) else None
                        if a != b:
                            diffs.append({'index': i, 'py': a, 'php': b})
                            if len(diffs) >= 5:
                                break
                    item['verdict'] = 'MISMATCH'
                    item['diff_sample'] = diffs
            report['flatten'].append(item)

    # ---------- 汇总 ----------
    print('=' * 72)
    print('1) JSON 回读（PHP json_encode → Python json.loads）')
    n_ok = sum(1 for c in report['counts'] if c['match'])
    n_all = len(report['counts'])
    print(f'   变量总数 {n_all}，回读+条目数一致 {n_ok}，不一致 {n_all - n_ok}')
    for c in report['counts']:
        if not c['match']:
            print(f'   [COUNT-MISMATCH] {c["file"]}::{c["var"]} php={c["php_count"]} py={c["py_count"]}')

    print('2) flatten 语义比对（Python 镜像 vs PHP 真实展开，逐条全量）')
    fm = [x['verdict'] for x in report['flatten']]
    print(f'   变量总数 {len(fm)}：FULL_MATCH={fm.count("FULL_MATCH")} '
          f'BOTH_ERROR_MATCH={fm.count("BOTH_ERROR_MATCH")} MISMATCH={fm.count("MISMATCH")} '
          f'ERROR_MISMATCH={fm.count("ERROR_MISMATCH")}')
    for item in report['flatten']:
        flag = 'OK ' if item['verdict'] == 'FULL_MATCH' else ('E-E' if item['verdict'] == 'BOTH_ERROR_MATCH' else '!!!')
        print(f'   [{flag}] {item["var"]:<48} raw={item["raw"]} php_flat={item["php_flat"]} py_flat={item["py_flat"]}')
        if item['verdict'] == 'MISMATCH':
            for d in item.get('diff_sample', []):
                print(f'        idx={d["index"]} py={json.dumps(d["py"], ensure_ascii=False)[:120]}')
                print('             php=' + json.dumps(d['php'], ensure_ascii=False)[:120])
        if item['verdict'] not in ('FULL_MATCH', 'BOTH_ERROR_MATCH'):
            print(f'        php_err={item["php_err"]} py_err={item["py_err"]}')

    print('3) 结构校验异常项')
    for s in report['structure']:
        if s['non_word_entries'] or s['bad_types']:
            print(f'   [NOTE] {s["file"]}::{s["var"]} 非词条条目={s["non_word_entries"]} 类型异常={s["bad_types"]}（词条型结构 otherwise OK）')

    print('4) 其他错误')
    for e in report['errors']:
        print(f'   [ERR] {e}')
    if not report['errors']:
        print('   无')

    with open(os.path.join(BASE, 'validation1_result.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print('\n结果已写入 validation1_result.json')


if __name__ == '__main__':
    main()
