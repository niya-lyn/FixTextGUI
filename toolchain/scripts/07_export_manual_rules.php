<?php
/**
 * FixText T0.2 · 步骤 7（扩展单元 B）：手动检索规则表迁移
 *
 * 用法: php 07_export_manual_rules.php <srcRoot> <outDir> [--alarm-log <path>]
 *
 * 为什么单列一步：
 *   手动检索规则表.php 位于 src/maps/ 下，属于词库来源域，但它不是"词条型 *Map"，
 *   而是"正则规则表"（search / replace / mark / color），
 *   且其中 3 条规则的 'replace' 是 PHP 闭包（静态扫描已定位：611 / 618 / 1245 行），
 *   json_encode 会把闭包静默降级成 {}。因此单列一步单独处理 + 单独报警。
 *
 * 该文件依赖 composer autoload 与 SCRIPT_DIR 常量，需带引导加载。
 *
 * 产出：
 *   <outDir>/manual_regex_rules.json   可 JSON 化的规则（闭包规则显式标注，不静默降级）
 *   <outDir>/manual_rules_closure_manifest.json  闭包规则清单（含源码行号、search 模式）
 */

error_reporting(E_ALL & ~E_DEPRECATED);
ini_set('memory_limit', '-1');

$srcRoot  = rtrim($argv[1] ?? '', '/');
$outDir   = rtrim($argv[2] ?? '', '/');
$alarmLog = $outDir . '/closure_alarm.log';
for ($i = 3; $i < count($argv); $i++) {
    if ($argv[$i] === '--alarm-log' && isset($argv[$i + 1])) {
        $alarmLog = $argv[++$i];
    }
}
if ($srcRoot === '' || !is_dir($srcRoot)) {
    fwrite(STDERR, "用法: php 07_export_manual_rules.php <srcRoot> <outDir> [--alarm-log <path>]\n");
    exit(2);
}
if (!is_dir($outDir)) {
    mkdir($outDir, 0755, true);
}

require_once __DIR__ . '/../lib/closure_guard.php';

if (!defined('SCRIPT_DIR')) {
    define('SCRIPT_DIR', $srcRoot);
}
$autoload = $srcRoot . '/vendor/autoload.php';
if (file_exists($autoload)) {
    require_once $autoload;
}

$manualFile = $srcRoot . '/maps/手动检索规则表.php';
if (!file_exists($manualFile)) {
    fwrite(STDERR, "未找到手动检索规则表.php\n");
    exit(2);
}

$rules = include $manualFile;
if (!is_array($rules)) {
    fwrite(STDERR, "手动检索规则表返回类型异常: " . gettype($rules) . "\n");
    exit(2);
}

$outRules = [];
$closureRules = [];
$findings = [];

foreach ($rules as $i => $rule) {
    if (!is_array($rule)) {
        $outRules[] = $rule;
        continue;
    }
    $entry = $rule;
    if (isset($rule['replace']) && $rule['replace'] instanceof Closure) {
        $r = new ReflectionFunction($rule['replace']);
        $line = (int)$r->getStartLine();
        $entry['replace'] = null;
        $entry['replace_kind'] = 'php_closure';
        $entry['replace_unavailable'] = 'json_encode 会把 Closure 静默降级为 {}，已拒绝导出，需引擎侧重写';
        $entry['source_line'] = $line;
        $closureRules[] = [
            'rule_index'  => $i,
            'source_line' => $line,
            'search'      => $rule['search'] ?? null,
            'mark'        => $rule['mark'] ?? null,
            'color'       => $rule['color'] ?? null,
            'action'      => '迁移为 JSON 时不可表达；由引擎侧重写为等价逻辑并单独测试（排期 3.5 门禁 a）',
        ];
        $findings[] = [
            'layer'  => 'runtime',
            'source' => 'maps/手动检索规则表.php',
            'path'   => '[' . $i . '].replace',
            'file'   => $manualFile,
            'line'   => $line,
            'kind'   => 'Closure',
            'detail' => 'replace 为 PHP 闭包，无法 JSON 化',
        ];
    }
    $outRules[] = $entry;
}

file_put_contents(
    $outDir . '/manual_regex_rules.json',
    json_encode($outRules, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT)
);
file_put_contents(
    $outDir . '/manual_rules_closure_manifest.json',
    json_encode([
        'file'         => 'maps/手动检索规则表.php',
        'total_rules'  => count($rules),
        'closure_rules'=> count($closureRules),
        'rules'        => $closureRules,
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT)
);

$alarm = closure_alarm($findings, $alarmLog, 'manual-regex-rules');

echo "MANUAL RULES EXPORT\n";
echo "  规则总数: " . count($rules) . "，其中闭包规则: " . count($closureRules) . "，已 JSON 化: " . (count($rules) - count($closureRules)) . "\n";
foreach ($closureRules as $c) {
    echo "  [CLOSURE] rule#{$c['rule_index']} line={$c['source_line']} search={$c['search']}\n";
}
if ($alarm['alarm']) {
    echo "  ALARM 已触发，留痕: {$alarmLog}\n";
}
echo "MANUAL RULES DONE\n";
