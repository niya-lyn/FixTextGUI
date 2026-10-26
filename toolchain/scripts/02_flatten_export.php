<?php
/**
 * FixText 词库 flatten 语义导出（验证一第二部分）
 * 以 Map.php 的 flattenWord / processReplaceHolder 纯逻辑（剥离 TextFixer/Config 依赖、
 * 不含 excludedRules 过滤与 Go 逆序长度排序）计算每个 *Map 变量的展开结果，
 * 供 Python 侧镜像实现全量比对。
 * 用法: php flatten_export.php <mapsDir> <outDir>
 * 本脚本是 T0.2 正式迁移流程的第 2 步，逻辑与 P0 版 flatten_export.php 完全一致
 * （PHP 侧按 Map.php 语义展开，作为 Python 镜像实现的比对基准）。
 */

error_reporting(E_ALL & ~E_DEPRECATED);
ini_set('memory_limit', '-1');
$mapsDir = rtrim($argv[1], '/');
$outDir  = rtrim($argv[2], '/');
if (!is_dir($outDir)) mkdir($outDir, 0755, true);

function isValidWord(array|string $word): bool
{
    if (!is_array($word)) return false;
    if (!isset($word['before']) || !isset($word['after'])) return false;
    if ((!$word['before'] && $word['before'] !== "0") || (!$word['after'] && $word['after'] !== "0")) return false;
    return true;
}

function createWord($before, $after, array $word): array
{
    $elem = [
        'before'        => $before,
        'after'         => $after,
        'replaceHolder' => $word['replaceHolder'] ?? [],
    ];
    if (isset($word['mark'])) $elem['mark'] = $word['mark'];
    return $elem;
}

function flattenWord(array|string $word): array
{
    if (!isValidWord($word)) return [];
    if (is_array($word['after'])) {
        if (!is_array($word['before'])) throw new RuntimeException("after 为数组时，before 必须也为数组");
        if (count($word['after']) != count($word['before'])) throw new RuntimeException("after/before 数量不等");
        $ret = [];
        foreach ($word['after'] as $k => $after) {
            if (!$after && $after !== "0") continue;
            $ret[] = createWord($word['before'][$k], $after, $word);
        }
        return $ret;
    }
    if (is_array($word['before'])) {
        $ret = [];
        foreach ($word['before'] as $before) {
            if (!$before) continue;
            $ret[] = createWord($before, $word['after'], $word);
        }
        return $ret;
    }
    return [createWord($word['before'], $word['after'], $word)];
}

function generateCombinations($holderLines)
{
    $result = [[]];
    foreach ($holderLines as $holderLine) {
        $temp = [];
        foreach ($result as $product) {
            foreach ($holderLine as $value) {
                $temp[] = array_merge($product, [$value]);
            }
        }
        $result = $temp;
    }
    return $result;
}

function expandWordsWithReplaceHolder($word)
{
    $combinations = generateCombinations($word['replaceHolder']);
    $resultArr = [];
    foreach ($combinations as $combination) {
        $resultBefore = $word['beforeParts'][0];
        $resultAfter  = $word['afterParts'][0];
        $combinationLen = count($combination);
        for ($i = 0; $i < $combinationLen; $i++) {
            $resultBefore .= $combination[$i] . $word['beforeParts'][$i + 1];
            $resultAfter  .= $combination[$i] . $word['afterParts'][$i + 1];
        }
        $resultWord = ['before' => $resultBefore, 'after' => $resultAfter];
        if (isset($word['mark'])) $resultWord['mark'] = $word['mark'];
        $resultArr[] = $resultWord;
    }
    return $resultArr;
}

function processReplaceHolder(&$words)
{
    $ret = [];
    foreach ($words as $word) {
        if (!isset($word['replaceHolder']) || !$word['replaceHolder']) {
            $ret[] = $word;
            continue;
        }
        $holderMark = '@';
        $holderCount = mb_substr_count($word['before'], $holderMark);
        if ($holderCount !== count($word['replaceHolder'])) {
            throw new RuntimeException("{$word['after']} 的 replaceHolder 设置有误");
        }
        $word['beforeParts'] = explode($holderMark, $word['before']);
        $word['afterParts']  = explode($holderMark, $word['after']);
        $ret = array_merge($ret, expandWordsWithReplaceHolder($word));
    }
    $words = $ret;
}

function flattenMaps(array $maps): array
{
    if (!$maps) return [];
    // 自动包装：单个 map（首个元素含 before 键）
    if (isset($maps[0]['before'])) $maps = [$maps];
    $ret = [];
    foreach ($maps as $map) {
        foreach ($map as $word) {
            foreach (flattenWord($word) as $elem) $ret[] = $elem;
        }
    }
    processReplaceHolder($ret);
    return $ret;
}

function loadFileVars(string $path): array
{
    $result = include($path);
    $vars = get_defined_vars();
    unset($vars['path'], $vars['result']);
    return [$result, $vars];
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
];

$meta = [];
foreach ($files as $f) {
    $path = $mapsDir . '/' . $f;
    [$result, $vars] = loadFileVars($path);
    foreach ($vars as $name => $v) {
        if (!str_ends_with($name, 'Map')) continue;   // 只展开词条型 *Map
        $flat = null; $err = null; $rawCount = null;
        try {
            $rawCount = is_array($v) ? count($v) : null;
            $flat = flattenMaps($v);
        } catch (Throwable $e) {
            $err = $e->getMessage();
        }
        $safe = str_replace(['/', '\\', '【', '】'], '_', $f);
        $key = $safe . '__' . $name;
        if ($flat !== null) {
            file_put_contents(
                $outDir . '/flat_' . $key . '.json',
                json_encode($flat, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
            );
        }
        $meta[$key] = [
            'raw_count'  => $rawCount,
            'flat_count' => $flat === null ? null : count($flat),
            'error'      => $err,
        ];
    }
}

file_put_contents($outDir . '/flat__meta__.json', json_encode($meta, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
$totalRaw = 0; $totalFlat = 0;
foreach ($meta as $k => $e) {
    echo str_pad((string)$e['raw_count'], 8), str_pad((string)$e['flat_count'], 8), $k, $e['error'] ? " [ERR: {$e['error']}]" : '', "\n";
    $totalRaw += $e['raw_count'] ?? 0; $totalFlat += $e['flat_count'] ?? 0;
}
echo "TOTAL raw=$totalRaw flat=$totalFlat\n";
echo "FLATTEN EXPORT DONE\n";
