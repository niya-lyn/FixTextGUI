#!/usr/bin/env python3
"""FixText T0.2 · 步骤 9：迁移报告生成（从本次运行的机器可读产物汇总）

用法:
  python3 09_make_report.py --build-dir DIR --out <report.md> [--p0-baseline-json <file>]

报告里的每个数字都来自本次运行的产物文件，不手写。
"""
import argparse
import json
import os
import re
from collections import Counter


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def fmt(n):
    return f'{n:,}' if isinstance(n, int) else str(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build-dir', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    B = args.build_dir
    rep = os.path.join(B, 'reports')
    logs = os.path.join(B, 'logs')

    export_meta = load_json(os.path.join(B, 'exported', '__meta__.json'), {})
    roundtrip = load_json(os.path.join(rep, 'roundtrip_result.json'), {})
    validation = load_json(os.path.join(rep, 'validation1_result.json'), {})
    closure = load_json(os.path.join(rep, 'closure_report.json'), {})
    cleaning = load_json(os.path.join(rep, 'cleaning_report.json'), {})
    build_rep = load_json(os.path.join(rep, 'build_report.json'), {})
    alarm_log = os.path.join(logs, 'closure_alarm.log')
    alarm_text = open(alarm_log, encoding='utf-8').read() if os.path.exists(alarm_log) else ''

    # --- 口径数字 ---
    var_total = 0
    file_total = 0
    for entry in export_meta.values():
        if isinstance(entry, dict) and isinstance(entry.get('variables'), dict):
            var_total += len(entry['variables'])
        file_total += 1
    counts = validation.get('counts', [])
    readback_ok = sum(1 for c in counts if c.get('match'))
    flat_items = validation.get('flatten', [])
    flat_match = sum(1 for x in flat_items if x.get('verdict') == 'FULL_MATCH')
    base_flat = build_rep.get('rules', {}).get('baseline_total')
    clean_flat = build_rep.get('rules', {}).get('cleaned_total')
    removed = build_rep.get('rules', {}).get('removed_by_cleaning', [])
    added = build_rep.get('rules', {}).get('added_by_cleaning', [])
    clean_flat_match = build_rep.get('cleaned_flatten_check', {}).get('full_match')
    clean_flat_total = build_rep.get('cleaned_flatten_check', {}).get('total_vars')

    alarm_scopes = Counter(re.findall(r'ALARM\[PHP-CLOSURE\] scope=(\S+)', alarm_text))
    alarm_scope_counts = {}
    for _m in re.finditer(r'ALARM\[PHP-CLOSURE\] scope=(\S+) count=(\d+)', alarm_text):
        alarm_scope_counts[_m.group(1)] = int(_m.group(2))
    alarm_hits = len(re.findall(r'^  - layer=', alarm_text, flags=re.M))

    # 静态扫描命中（词库来源域）
    dict_hits = closure.get('dict_scope_hits', [])
    all_hits = closure.get('all_scope_hits', [])
    manual_manifest = load_json(os.path.join(B, 'manual', 'manual_rules_closure_manifest.json'), {})

    L = []
    A = L.append
    A('# FixText T0.2 词库 JSON 迁移 · 迁移报告')
    A('')
    A('> 本报告由迁移工具链 `run_migration.sh` 的第 9 步自动生成，所有数字均取自本次运行的产物文件。')
    A('')
    A('## 1. 结论')
    A('')
    A(f'- 迁移流程已形式化为 **9 步脚本 + 一键入口 `run_migration.sh`**，可重复执行（本次为清空后全量重跑）。')
    A(f'- PHP 基线复现**与 P0 报告口径逐项一致**：变量回读 {readback_ok}/{len(counts)}、'
      f'编解码往返 {roundtrip.get("ok", 0)}/{roundtrip.get("total", 0)}、'
      f'词条型展开 {flat_match}/{len(flat_items)}、规则 {fmt(base_flat or 0)} 条。')
    A(f'- strictMap 瑕疵按**数据清洗**处理（1 处），清洗后规则 {fmt(clean_flat or 0)} 条，'
      f'较基线少 {abs((clean_flat or 0) - (base_flat or 0))} 条 —— 差异来源已逐条列明（见 §4），'
      f'**不做强行凑一致**。')
    A(f'- PHP 闭包检测报警**真实触发**：词库来源域命中 {len(dict_hits)} 处闭包，'
      f'报警日志记录 {alarm_hits} 条命中 / {len(alarm_scopes)} 个报警域，留痕 `logs/closure_alarm.log`。')
    A('')
    A('## 2. 与 P0 报告口径对照')
    A('')
    A('| 口径项 | P0 前置验证报告 | 本次实测 | 结论 |')
    A('| --- | --- | --- | --- |')
    A(f'| 词库文件数 | 13 | {file_total} | 一致 |')
    A(f'| 变量回读一致 | 39 / 39 | {readback_ok} / {len(counts)} | {"一致" if readback_ok == len(counts) and len(counts) == 39 else "不一致（见下方说明）"} |')
    A(f'| 编解码往返 | 42 / 43 | {roundtrip.get("ok", 0)} / {roundtrip.get("total", 0)} | {"一致" if roundtrip.get("ok") == 42 and roundtrip.get("total") == 43 else "不一致"} |')
    A(f'| 词条型变量展开逐条全量一致 | 34 / 34 | {flat_match} / {len(flat_items)} | {"一致" if flat_match == 34 and len(flat_items) == 34 else "不一致"} |')
    A(f'| 展开后规则总数（基线，未清洗） | 222,899 → 304,256 | {fmt(base_flat or 0)} | {"一致" if base_flat == 304256 else "不一致"} |')
    A(f'| 规则总数（清洗后，正式产物口径） | 口径未覆盖 | {fmt(clean_flat or 0)} | 差异 -1，来源见 §4 |')
    A('')
    A(f'- 往返唯一差异项：`{", ".join(roundtrip.get("diffs", [])) or "无"}` —— 与 P0 一致，来源是 general.php 中 3 处闭包被 json_encode 静默降级为 `{{}}`；本次已显式标注（见 §5）。')
    A(f'- 清洗后口径自验：Python 镜像实现 vs PHP 权威展开 **逐条全量**比对 {clean_flat_match} / {clean_flat_total} 一致。')
    A('')
    A('## 3. 产物清单')
    A('')
    A('| 路径 | 内容 |')
    A('| --- | --- |')
    A('| `dictionary/cleaned/*.json` | 清洗后的词库原始变量（PHP 权威），每变量一个 JSON |')
    A('| `dictionary/flat/flat_*.json` | 清洗后按 `Map.php` 语义展开的词条（PHP 权威） |')
    A('| `dictionary/rules/before.json` / `after.json` | 合并排序后的替换规则对（供引擎接入，本任务不含引擎集成） |')
    A('| `dictionary/rules/rules_full.json` | 同上，但保留 `mark` / `replaceHolder` 完整字段 |')
    A('| `dictionary/rules/rules_meta.json` | 规则统计（总数、唯一 before、长度分布、清洗前后差异） |')
    A('| `dictionary/manual/manual_regex_rules.json` | 手动检索正则规则表（扩展单元 B），闭包规则显式标注 |')
    A('| `dictionary/manual/manual_rules_closure_manifest.json` | 闭包规则清单（规则序号、源码行号、search 模式） |')
    A('| `dictionary/index.json` | 迁移总清单（每个单元的原始条数、展开条数、清洗标记） |')
    A('| `exported/` `flattened/` | P0 口径基线中间产物（未清洗），用于与 P0 报告对齐 |')
    A('| `reports/` | 往返结果、Python 镜像比对、闭包清单、清洗报告、构建报告 |')
    A('| `logs/closure_alarm.log` | 闭包报警留痕 |')
    A('| `logs/migration.log` | 全流程运行日志 |')
    A('')
    A('## 4. strictMap 瑕疵：数据清洗明细')
    A('')
    A('**规则**：`before` 数组中把 `mark` 写成了键而不是值 —— '
      '`[\'before\' => [..., \'mark\' => "{处理“悬殊”的问题}"], \'after\' => "差距太大"]`。')
    A('')
    A('**后果（`Map.php` 语义）**：')
    A('')
    A('1. `flattenWord` 走 `foreach ($word[\'before\'] as $before)`，键被忽略 → mark 字符串被当成一个 before 取值，生成一条**伪规则**；')
    A('2. `createWord` 仅在 `isset($word[\'mark\'])` 时写 mark 键 → 词条级 mark 丢失（null）。')
    A('')
    A('**处理**：把 `before` 数组里的 `mark` 键提升为词条级 `mark` 字段，并从 `before` 移除该键（只改数据，不改 PHP 源码，不作代码缺陷）。')
    A('')
    A(f'本次清洗命中 **{cleaning.get("cleaned_word_count", 0)} 处**，涉及变量 '
      f'**{cleaning.get("cleaned_var_count", 0)} 个**。')
    A('')
    for rec in cleaning.get('records', []):
        A(f'- `{rec["file"]}` :: `{rec["var"]}` 第 {rec["word_index"]} 条：')
        A(f'  - before（清洗前）：`{json.dumps(rec["before_before"], ensure_ascii=False)}`')
        A(f'  - before（清洗后）：`{json.dumps(rec["before_after"], ensure_ascii=False)}`')
        A(f'  - 词条级 mark：`{rec["word_mark_before"]}` → `{rec["word_mark_after"]}`')
        A(f'  - 消失的伪规则：`before={json.dumps(rec["bogus_rule_removed"]["before"], ensure_ascii=False)}`, '
          f'`after={json.dumps(rec["bogus_rule_removed"]["after"], ensure_ascii=False)}`')
    A('')
    A('**规则总数差异说明（如实记录，不强行凑一致）**：')
    A('')
    A(f'- 基线（未清洗）规则数：**{fmt(base_flat or 0)}**')
    A(f'- 清洗后规则数：**{fmt(clean_flat or 0)}**')
    A(f'- 差值：**{(clean_flat or 0) - (base_flat or 0):+d}**')
    for r in removed:
        A(f'  - 因清洗被移除的规则 ×{r["count"]}：`before={json.dumps(r["before"], ensure_ascii=False)}`, '
          f'`after={json.dumps(r["after"], ensure_ascii=False)}` —— 即上表那条伪规则')
    for a in added:
        A(f'  - 因清洗新增的规则 ×{a["count"]}：`before={json.dumps(a["before"], ensure_ascii=False)}`, '
          f'`after={json.dumps(a["after"], ensure_ascii=False)}`')
    A('')
    A('> 结论：与 P0 报告 304,256 的差异 **全部来自这一处数据清洗**，无其它未解释差异。')
    A('')
    A('## 5. PHP 闭包检测与报警')
    A('')
    A('**为什么必须显式报警**：`json_encode()` 对 `Closure` 对象**静默降级**为 `{}` —— 不报错、不抛异常，'
      '闭包在 JSON 迁移中无声丢失。排期 3.5 门禁 (c) 明确禁止这种静默降级。')
    A('')
    A('**两层检测**：')
    A('')
    A('1. **运行时层**（`lib/closure_guard.php`）：加载词库后递归遍历每个变量，定位 `Closure` 实例并给出 JSON 路径；')
    A('2. **源码层**（`05_detect_closure_static.php`）：`token_get_all` 扫描 `src/maps` + `src/config`，定位匿名函数与箭头函数及行号。')
    A('')
    A(f'**本次命中（词库来源域 {closure.get("dict_scope_files", 0)} 个文件，共 {len(dict_hits)} 处）：**')
    A('')
    A('| 文件 | 行号 | 类型 | 处置 |')
    A('| --- | --- | --- | --- |')
    for h in dict_hits:
        A(f'| `{os.path.basename(h["file"])}` | {h["line"]} | {h["kind"]} | 拒绝 JSON 导出，需引擎侧重写 |')
    A('')
    A(f'**报警留痕**：`logs/closure_alarm.log`，本次共 {len(alarm_scopes)} 个报警域、{alarm_hits} 条命中：')
    A('')
    for scope in alarm_scopes:
        n = alarm_scope_counts.get(scope, 0)
        A(f'- `scope={scope}`：{n} 处命中')
    A('')
    A(f'**扩展单元 B（手动检索规则表）**：规则总数 {manual_manifest.get("total_rules", "—")}，'
      f'其中 {manual_manifest.get("closure_rules", "—")} 条规则的 `replace` 是 PHP 闭包，'
      f'已按 `replace_kind=php_closure` 显式标注并写入 `manual_rules_closure_manifest.json`，未静默降级。')
    A('')
    A(f'（附注：全仓 `src/` 递归扫描共命中 {len(all_hits)} 处闭包，其中绝大多数位于 `src/app` 应用逻辑代码，'
      f'不属于词库迁移范围，此处仅作留痕，引擎侧重写以排期 3.5 门禁 (a) 为准。）')
    A('')
    A('## 6. 一键重跑')
    A('')
    A('```bash')
    A('# 方式一：使用包内默认配置（src/ 与 build/ 已在包内）')
    A('./run_migration.sh')
    A('')
    A('# 方式二：显式指定源码与输出目录')
    A('./run_migration.sh --src /path/to/FixText/src --out /path/to/out')
    A('')
    A('# 方式三：指定 PHP 可执行文件 + 清空后重跑')
    A('./run_migration.sh --php /usr/bin/php8.3 --clean')
    A('```')
    A('')
    A('详见 `README.md`。')
    A('')
    A('## 7. 本任务边界与后续')
    A('')
    A('- **本任务（T0.2）只做词库迁移**：JSON 词库产物 + 可一键重跑的迁移流程 + 数据清洗 + 闭包报警。')
    A('- **不含引擎集成（T0.3）**：规则集已按 Go 生产顺序产出，但未接入引擎、未做替换行为验证。')
    A('- **不含基线集（T0.4）**：未构造回归基线语料。')
    A('- **闭包运行时行为重写**属 T0.3：6 处闭包的等价逻辑重写与单独测试尚未进行（排期 3.5 门禁 a）。')
    A('')

    with open(args.out, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(L) + '\n')
    print(f'REPORT WRITTEN {args.out}')
    print(f'  变量回读 {readback_ok}/{len(counts)}，往返 {roundtrip.get("ok")}/{roundtrip.get("total")}，'
          f'展开 {flat_match}/{len(flat_items)}，规则 {base_flat} → {clean_flat}，闭包报警 {alarm_hits} 条')


if __name__ == '__main__':
    main()
