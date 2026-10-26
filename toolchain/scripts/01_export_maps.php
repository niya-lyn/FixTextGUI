<?php
/**
 * FixText T0.2 · 步骤 1：词库变量导出（含 PHP 闭包显式检测与报警）
 *
 * 用法: php 01_export_maps.php <mapsDir> <outDir> [--alarm-log <path>]
 *
 * 相对 P0 版 export_maps.php 的增强：
 *   1) 接入 closure_guard：每个变量导出前做运行时闭包扫描；
 *      命中闭包的变量不再"静默"导出为 {}，而是显式标注 degraded=true
 *      并列出闭包路径，同时触发 ALARM 报警。
 *   2) 报警留痕写入 alarm log（默认 <outDir>/../logs/closure_alarm.log）。
 *   3) 逐文件处理并及时释放内存（词库文件最大 6MB）。
 *
 * 产出：
 *   <outDir>/<safe>__<var>.json          每个变量的原始值（PHP 侧权威）
 *   <outDir>/<safe>.__return__.json      return 风格文件的返回值
 *   <outDir>/__meta__.json               元信息（含闭包命中记录）
 */

error_reporting(E_ALL & ~E_DEPRECATED);
ini_set('memory_limit', '-1');

$mapsDir = rtrim($argv[1] ?? '', '/');
$outDir  = rtrim($argv[2] ?? '', '/');
$alarmLog = $outDir . '/closure_alarm.log';
for ($i = 3; $i < count($argv); $i++) {
    if ($argv[$i] === '--alarm-log' && isset($argv[$i + 1])) {
        $alarmLog = $argv[++$i];
    }
}
if ($mapsDir === '' || !is_dir($mapsDir)) {
    fwrite(STDERR, "用法: php 01_export_maps.php <mapsDir> <outDir> [--alarm-log <path>]\n");
    exit(2);
}
if (!is_dir($outDir)) {
    mkdir($outDir, 0755, true);
}

require_once __DIR__ . '/../lib/closure_guard.php';

/** 与 Map.php loadUseMaps 同构：include 到函数作用域，收集变量 */
function loadFileVars(string $path): array
{
    $result = include($path);
    $vars = get_defined_vars();
    unset($vars['path'], $vars['result']);
    return [$result, $vars];
}

function varInfo($v): array
{
    $info = ['type' => gettype($v)];
    if (is_array($v)) {
        $info['count'] = count($v);
        $info['is_list'] = array_is_list($v);
    } elseif (is_string($v)) {
        $info['strlen'] = strlen($v);
        $info['mb_len'] = mb_strlen($v, 'UTF-8');
    }
    return $info;
}

// 与 P0 导出清单一致（13 个文件；口径基准见 P0 前置验证报告 1.2）
$files = [
    '1.自定义词库.php',
    '1.自定义词库【旧式、通假写法】.php',
    '2.繁转简词库.php',
    '3.txtFormat 词库.php',
    '4.的地得词库.php',
    '5.临时校对表.php',
    '6.用户扩展词库.php',
    '7.生僻字词库.php',
    '7.生僻字词库【扩展区】.php',
    '书籍专有替换词库/天之下.php',
    '书籍专有替换词库/铁鹤书.php',
    '../config/map.php',
    '../config/general.php',
];

$meta = [];
$alarmFindings = [];

foreach ($files as $f) {
    $path = $mapsDir . '/' . $f;
    if (!file_exists($path)) {
        $meta[$f] = ['error' => 'file not found'];
        continue;
    }

    $entry = ['variables' => [], 'errors' => [], 'closures' => []];
    try {
        [$result, $vars] = loadFileVars($path);
    } catch (Throwable $e) {
        $meta[$f] = ['error' => 'include failed: ' . $e->getMessage()];
        unset($vars, $result);
        continue;
    }

    $safe = str_replace(['/', '\\', '【', '】'], '_', $f);

    // return 值（return 风格文件：config/map.php、config/general.php、书籍专有词库）
    if ($result !== false && $result !== 1 && $result !== null) {
        $enc = closure_encode_safe($result);
        if ($enc['ok']) {
            file_put_contents($outDir . '/' . $safe . '.__return__.json', $enc['json']);
            $entry['return'] = varInfo($result);
        } else {
            // 含闭包：写出"已标注降级"的文件，闭包位置在 __meta__ 与报警日志中留痕
            file_put_contents(
                $outDir . '/' . $safe . '.__return__.json',
                json_encode($result, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
            );
            $entry['return'] = varInfo($result);
            $entry['return_degraded'] = true;
            $entry['return_error'] = $enc['error'];
            foreach ($enc['closures'] as $c) {
                $entry['closures'][] = ['unit' => '__return__', 'path' => $c['path'], 'file' => $c['file'], 'line' => $c['line']];
                $alarmFindings[] = [
                    'layer'  => 'runtime',
                    'source' => $f,
                    'path'   => $c['path'],
                    'file'   => $c['file'],
                    'line'   => $c['line'],
                    'kind'   => 'Closure',
                    'detail' => $enc['error'],
                ];
            }
        }
    }

    ksort($vars);
    foreach ($vars as $name => $v) {
        $enc = closure_encode_safe($v);
        $info = array_merge(varInfo($v), ['exported' => $enc['ok']]);
        if (!$enc['ok']) {
            $info['degraded'] = true;
            $info['error'] = $enc['error'];
            $entry['errors'][] = "$name 未导出: " . $enc['error'];
            foreach ($enc['closures'] as $c) {
                $entry['closures'][] = ['unit' => $name, 'path' => $c['path'], 'file' => $c['file'], 'line' => $c['line']];
                $alarmFindings[] = [
                    'layer'  => 'runtime',
                    'source' => $f,
                    'path'   => $name . $c['path'],
                    'file'   => $c['file'],
                    'line'   => $c['line'],
                    'kind'   => 'Closure',
                    'detail' => $enc['error'],
                ];
            }
        } else {
            file_put_contents($outDir . '/' . $safe . '__' . $name . '.json', $enc['json']);
        }
        $entry['variables'][$name] = $info;
        unset($enc);
    }
    unset($vars, $result);

    $meta[$f] = $entry;
}

file_put_contents(
    $outDir . '/__meta__.json',
    json_encode($meta, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT)
);

// 闭包报警（运行时层）
$alarm = closure_alarm($alarmFindings, $alarmLog, 'runtime-export');

$varCount = 0;
foreach ($meta as $entry) {
    if (isset($entry['variables'])) {
        $varCount += count($entry['variables']);
    }
}
echo "EXPORT DONE\n";
echo "  文件数: " . count($meta) . "，变量数: $varCount\n";
foreach ($meta as $f => $entry) {
    if (isset($entry['error'])) {
        echo "  [ERR] $f => {$entry['error']}\n";
        continue;
    }
    $names = implode(', ', array_keys($entry['variables']));
    $tag = empty($entry['closures']) ? '' : '  [CLOSURE x' . count($entry['closures']) . ']';
    echo "  [OK] $f => $names$tag\n";
}
if ($alarm['alarm']) {
    echo "  ALARM 运行时闭包 " . $alarm['count'] . " 处，留痕: {$alarmLog}\n";
} else {
    echo "  运行时未发现闭包\n";
}
