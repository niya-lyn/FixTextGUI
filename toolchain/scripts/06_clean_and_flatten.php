<?php
/**
 * FixText T0.2 · 步骤 6：strictMap 数据清洗 + 清洗后展开（PHP 侧权威）
 *
 * 用法: php 06_clean_and_flatten.php <mapsDir> <cleanDir> <flatDir> [--report <json>]
 *
 * 背景（排期文档 3.5 门禁 b）：strictMap 瑕疵按数据清洗处理，不作代码缺陷阻塞迁移。
 * 瑕疵形态：'mark' 被写成 before 数组的一个"键"，而不是词条级的"值"：
 *     ['before' => ["悬殊太大", …, 'mark' => "{处理“悬殊”的问题}"], 'after' => "差距太大"]
 * 后果（Map.php 语义）：
 *     1) flattenWord 走 `foreach ($word['before'] as $before)` —— 键被忽略，
 *        mark 的字符串被当成一个 before 取值，生成一条伪规则
 *        {"before": "{处理“悬殊”的问题}", "after": "差距太大"}；
 *     2) createWord 只在 `isset($word['mark'])` 时写 mark 键，词条级 mark 因此丢失（null）。
 *
 * 清洗动作（仅改数据，不改 PHP 源码）：
 *     把 before 数组中的 'mark' 键提升为词条级 'mark' 字段，并从 before 数组移除该键。
 *     清洗后伪规则消失，词条级 mark 恢复。
 *
 * 产出：
 *     <cleanDir>/<safe>__<var>.json   清洗后的原始变量值（迁移产物口径）
 *     <flatDir>/flat_<safe>__<var>.json 清洗后按 Map.php 语义展开的结果
 *     <report> 清洗报告（逐条记录改动前后、伪规则内容）
 */

error_reporting(E_ALL & ~E_DEPRECATED);
ini_set('memory_limit', '-1');

$mapsDir  = rtrim($argv[1] ?? '', '/');
$cleanDir = rtrim($argv[2] ?? '', '/');
$flatDir  = rtrim($argv[3] ?? '', '/');
$reportPath = $flatDir . '/cleaning_report.json';
for ($i = 4; $i < count($argv); $i++) {
    if ($argv[$i] === '--report' && isset($argv[$i + 1])) {
        $reportPath = $argv[++$i];
    }
}
if ($mapsDir === '' || !is_dir($mapsDir)) {
    fwrite(STDERR, "用法: php 06_clean_and_flatten.php <mapsDir> <cleanDir> <flatDir> [--report <json>]\n");
    exit(2);
}
foreach ([$cleanDir, $flatDir] as $d) {
    if (!is_dir($d)) {
        mkdir($d, 0755, true);
    }
}

// ---------- Map.php 语义镜像 ----------
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

// ---------- 清洗规则 ----------
/**
 * 把 before 数组里的 'mark' 键提升为词条级 mark。
 * 返回 [清洗后词条, 改动描述|null]
 */
function cleanWord(array $word): array
{
    if (!isset($word['before']) || !is_array($word['before'])) {
        return [$word, null];
    }
    if (!array_key_exists('mark', $word['before'])) {
        return [$word, null];
    }
    $markValue = $word['before']['mark'];
    if (!is_string($markValue) || $markValue === '') {
        return [$word, null];   // 非字符串/空值不属于本清洗规则范围，不动
    }
    $beforeList = $word['before'];
    unset($beforeList['mark']);
    $cleaned = $word;
    $cleaned['before'] = $beforeList;
    $conflict = array_key_exists('mark', $word) && $word['mark'] !== $markValue;
    if (!array_key_exists('mark', $word)) {
        $cleaned['mark'] = $markValue;
    }
    $desc = [
        'mark_value'        => $markValue,
        'before_before'     => array_values($word['before']),
        'before_after'      => array_values($beforeList),
        'word_mark_before'  => $word['mark'] ?? null,
        'word_mark_after'   => $cleaned['mark'] ?? null,
        'conflict'          => $conflict,
        'bogus_rule_removed' => [
            'before' => $markValue,
            'after'  => is_array($word['after']) ? null : $word['after'],
        ],
    ];
    return [$cleaned, $desc];
}

// ---------- 主流程 ----------
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

$cleanLog = [];       // 逐条清洗记录
$flatMeta = [];       // 清洗后展开统计
$cleanMeta = [];      // 清洗后变量元信息

function loadFileVars(string $path): array
{
    $result = include($path);
    $vars = get_defined_vars();
    unset($vars['path'], $vars['result']);
    return [$result, $vars];
}

foreach ($files as $f) {
    $path = $mapsDir . '/' . $f;
    if (!file_exists($path)) {
        continue;
    }
    $safe = str_replace(['/', '\\', '【', '】'], '_', $f);
    try {
        [$result, $vars] = loadFileVars($path);
    } catch (Throwable $e) {
        continue;
    }

    foreach ($vars as $name => $v) {
        if (!str_ends_with($name, 'Map') || !is_array($v)) {
            continue;
        }
        $key = $safe . '__' . $name;

        // --- 清洗：逐词条处理（含"自动包装"结构：单个 map 时 $maps[0]['before'] 存在）---
        $maps = $v;
        $autoWrapped = false;
        if (isset($maps[0]['before'])) {
            $maps = [$maps];
            $autoWrapped = true;
        }
        $cleanedMaps = [];
        $wordIndex = 0;
        foreach ($maps as $map) {
            if (!is_array($map)) {
                $cleanedMaps[] = $map;
                continue;
            }
            $cleanedMap = [];
            foreach ($map as $word) {
                if (is_array($word)) {
                    [$cw, $desc] = cleanWord($word);
                    if ($desc !== null) {
                        $cleanLog[] = [
                            'file'   => $f,
                            'var'    => $name,
                            'key'    => $key,
                            'word_index' => $wordIndex,
                            'auto_wrapped' => $autoWrapped,
                        ] + $desc;
                    }
                    $cleanedMap[] = $cw;
                } else {
                    $cleanedMap[] = $word;
                }
                $wordIndex++;
            }
            $cleanedMaps[] = $cleanedMap;
        }
        // 还原自动包装结构
        if ($autoWrapped) {
            $cleanedVars = $cleanedMaps[0];
        } else {
            $cleanedVars = $cleanedMaps;
        }

        // --- 清洗后展开 ---
        $flat = null;
        $err = null;
        try {
            $flat = flattenMaps($cleanedVars);
        } catch (Throwable $e) {
            $err = $e->getMessage();
        }
        if ($flat !== null) {
            file_put_contents(
                $flatDir . '/flat_' . $key . '.json',
                json_encode($flat, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
            );
        }
        $flatMeta[$key] = [
            'raw_count'  => count($v),
            'flat_count' => $flat === null ? null : count($flat),
            'error'      => $err,
        ];

        // --- 清洗后原始值导出 ---
        file_put_contents(
            $cleanDir . '/' . $key . '.json',
            json_encode($cleanedVars, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
        );
        $cleanMeta[$key] = [
            'type'      => gettype($cleanedVars),
            'count'     => count($cleanedVars),
            'is_list'   => array_is_list($cleanedVars),
            'cleaned'   => true,
        ];
        unset($cleanedVars, $cleanedMaps, $cleanedMap, $flat, $maps);
    }
    unset($vars, $result);
}

file_put_contents($flatDir . '/flat__meta__.json', json_encode($flatMeta, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
file_put_contents($cleanDir . '/__meta__.json', json_encode($cleanMeta, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));

$byVar = [];
foreach ($cleanLog as $c) {
    $byVar[$c['key']] = ($byVar[$c['key']] ?? 0) + 1;
}
$report = [
    'rule'        => "before 数组中的 'mark' 键 → 提升为词条级 'mark' 字段，并从 before 移除该键",
    'scope'       => '13 个词库文件中的全部词条型 *Map 变量',
    'cleaned_word_count' => count($cleanLog),
    'cleaned_var_count'  => count($byVar),
    'cleaned_vars' => $byVar,
    'records'     => $cleanLog,
];
file_put_contents($reportPath, json_encode($report, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT));

$totalRaw = 0;
$totalFlat = 0;
foreach ($flatMeta as $k => $e) {
    $totalRaw += $e['raw_count'] ?? 0;
    $totalFlat += $e['flat_count'] ?? 0;
    echo str_pad((string)$e['raw_count'], 8), str_pad((string)$e['flat_count'], 8), $k, $e['error'] ? " [ERR: {$e['error']}]" : '', "\n";
}
echo "CLEANED TOTAL raw=$totalRaw flat=$totalFlat\n";
echo "CLEANING: 清洗词条 " . count($cleanLog) . " 处，涉及变量 " . count($byVar) . " 个\n";
foreach ($byVar as $k => $n) {
    echo "  [CLEANED] $k x$n\n";
}
echo "CLEAN AND FLATTEN DONE\n";
