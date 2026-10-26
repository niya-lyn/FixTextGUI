<?php
/**
 * FixText 词库导出脚本（验证一：以真实 PHP 加载结果为对照基准）
 * 用法: php export_maps.php <mapsDir> <outDir>
 * 对每个词库文件 include 后收集 get_defined_vars()，逐变量 json_encode 导出，
 * 并记录条目数/类型/编码错误等元信息。
 */

error_reporting(E_ALL & ~E_DEPRECATED);
$mapsDir = rtrim($argv[1], '/');
$outDir  = rtrim($argv[2], '/');
if (!is_dir($outDir)) {
    mkdir($outDir, 0755, true);
}

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

function loadFileVars(string $path): array
{
    // 与 Map.php loadUseMaps 同构：include 到函数作用域，收集变量
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

$meta = [];
foreach ($files as $f) {
    $path = $mapsDir . '/' . $f;
    if (!file_exists($path)) {
        $meta[$f] = ['error' => 'file not found'];
        continue;
    }

    $entry = ['variables' => [], 'errors' => []];
    try {
        [$result, $vars] = loadFileVars($path);
    } catch (Throwable $e) {
        $meta[$f] = ['error' => 'include failed: ' . $e->getMessage()];
        continue;
    }

    // return 值（return 风格文件：config/map.php、config/general.php、书籍专有词库）
    if ($result !== false && $result !== 1 && $result !== null) {
        $json = json_encode($result, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($json === false) {
            $entry['errors'][] = 'return-value json_encode failed: ' . json_last_error_msg();
        } else {
            $safe = str_replace(['/', '\\', '【', '】'], '_', $f);
            file_put_contents($outDir . '/' . $safe . '.__return__.json', $json);
            $entry['return'] = varInfo($result);
        }
    }

    ksort($vars);
    foreach ($vars as $name => $v) {
        $json = json_encode($v, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($json === false) {
            $entry['errors'][] = "$name json_encode failed: " . json_last_error_msg();
            $entry['variables'][$name] = array_merge(varInfo($v), ['exported' => false]);
            continue;
        }
        $safe = str_replace(['/', '\\', '【', '】'], '_', $f);
        $outFile = $outDir . '/' . $safe . '__' . $name . '.json';
        if (file_put_contents($outFile, $json) === false) {
            $entry['errors'][] = "$name write failed: $outFile";
        }
        $entry['variables'][$name] = array_merge(varInfo($v), ['exported' => true]);
    }

    $meta[$f] = $entry;
}

file_put_contents($outDir . '/__meta__.json', json_encode($meta, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT));
echo "EXPORT DONE\n";
foreach ($meta as $f => $entry) {
    if (isset($entry['error'])) {
        echo "  [ERR] $f => {$entry['error']}\n";
        continue;
    }
    $names = implode(', ', array_keys($entry['variables']));
    echo "  [OK] $f => $names\n";
}
