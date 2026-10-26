<?php
/**
 * 从 FixText 源码导出「生效后的排版规则表」，供 Python 移植版使用。
 *
 * 目的：保证 Python 与 PHP 使用同一份规则数据（单一事实源），
 *      避免人工誊写正则导致的偏差。
 *
 * 导出内容：
 *   - punctuation_map : strtrWithWordsMap() 实际生效的 strtr 映射表（已 flatten + combine）
 *   - punctuation_patterns : config/formatting.php 中的 44 条标点正则
 *   - space_pattern / html_chapter_mark : FileProcessor 常量
 *
 * 用法: php export_rules.php <out.json>
 */

define('SCRIPT_DIR', dirname(__DIR__, 2) . '/in/x_src/FixText/src');
define('BOOK_DIR', '/tmp/books');
define('BOOK_BAK_DIR', '/tmp/booksBak');
define('BOOK_FIX_DIR', '/tmp/booksFix');
define('EPUB_MERGE_LOG_DIR', '/tmp/logs/merge');
define('EPUB_LIST_LOG', '/tmp/logs/epub_list.log');
define('REPORT_DIR', '/tmp/logs/report');
const EPUB_EXTRACT_PREFIX = '【EPUB 解压文件夹】';
const EPUB_MERGE_PREFIX = '【EPUB 合并文件】';
const RECURSIVE_FIX = true;
const REPACK_AFTER_FIX = false;
const EXCLUDE_DIRS = [];
const TEMP_MAP_FILE = SCRIPT_DIR . '/maps/5.临时校对表.php';
const REPLACE_BY_GO = false;
const TXT_REPLACE_BEFORE = SCRIPT_DIR . '/TXT_REPLACE_BEFORE.txt';
const TXT_REPLACE_AFTER = SCRIPT_DIR . '/TXT_REPLACE_AFTER.txt';
const TOKENIZE_CONTENT = false;

ini_set('memory_limit', '4096M');
date_default_timezone_set('Asia/Shanghai');
mb_internal_encoding('UTF-8');

require_once(SCRIPT_DIR . '/vendor/autoload.php');

use App\Service\Formatting\FileProcessor;
use App\Service\Map;
use App\Util\Config;
use App\Util\Util;

$out = $argv[1] ?? '';
if ($out === '') {
    fwrite(STDERR, "usage: php export_rules.php <out.json>\n");
    exit(1);
}

// 1. strtr 映射表：完全复刻 Util::strtrWithWordsMap 内部的处理
$wordsMap = Map::flattenMaps(Config::getFormatting('punctuationMap'));
$wordsMap = array_combine(
    array_column($wordsMap, 'before'),
    array_column($wordsMap, 'after')
);

// 2. 标点正则规则表
$patterns = [];
foreach (Config::getFormatting('punctuationPatterns') as $p) {
    $patterns[] = [
        'search'   => $p['search'],
        'replace'  => is_callable($p['replace']) ? null : $p['replace'],
        'modifiers'=> $p['modifiers'] ?? null,
    ];
}

// 3. 常量
$ref = new ReflectionClass(FileProcessor::class);
$spacePattern = $ref->getConstant('SPACE_PATTERN');

$data = [
    'punctuation_map'      => $wordsMap,
    'punctuation_patterns' => $patterns,
    'space_pattern'        => $spacePattern,
    'html_chapter_mark'    => Util::HTML_CHAPTER_MARK,
];

file_put_contents($out, json_encode($data, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
fwrite(STDERR, "exported " . count($wordsMap) . " map entries, " . count($patterns) . " patterns\n");
