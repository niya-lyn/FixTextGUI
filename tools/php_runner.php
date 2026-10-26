<?php
/**
 * 排版基准运行器（JSON 接口）：把一段文本按给定 Option 跑一遍 FixText 的排版流水线，
 * 返回 JSON，供 Python 侧的差分测试逐条比对。
 *
 * 用法:
 *     echo '{"options":{...},"input":"..."}' | php php_runner.php
 *
 * 输出: {"output":"..."} 或 {"error":"..."}
 *
 * 变换顺序复刻 App\Service\Formatting\FileProcessor::processFile() 中与排版相关的步骤。
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
use App\Service\Formatting\Option;
use App\Util\Util;

class RefProcessor extends FileProcessor
{
    public function setFileFlags(bool $isTxt, bool $isHtml): void
    {
        $this->isTxtFile  = $isTxt;
        $this->isHtmlFile = $isHtml;
    }

    public function transformAll(string &$content): void
    {
        if ($this->option->rmSpacesBetweenChnChars) {
            $this->rmSpacesBetweenChnChars($content);
        }
        if ($this->option->normalizePunctuations) {
            $this->normalizePunctuations($content);
        }
        $this->changeQuotationType($content);
        if (
            ($this->option->changeTextFormat || $this->option->extractTextFromHtml)
            && $this->option->isDefaultEncoding()
            && $this->option->consecutiveQuotationsType == 0
        ) {
            $this->changeTextFormat($content);
        }
        if ($this->option->formatHeadings && $this->isTxtFile) {
            $this->formatHeadings($content);
        }
        if ($this->option->paranoidTextSpacing && $this->isTxtFile) {
            $content = Util::pangu($content);
        }
        $content = trim($content) . $this->option->newLineType;
    }
}

$raw = stream_get_contents(STDIN);
$payload = json_decode($raw, true);
if (!is_array($payload)) {
    fwrite(STDOUT, json_encode(['error' => 'invalid json'], JSON_UNESCAPED_UNICODE));
    exit(1);
}

// 支持单条用例与批量用例两种输入
$cases = array_is_list($payload) ? $payload : [$payload];
$results = [];

foreach ($cases as $case) {
    $opt = new Option;
    foreach (($case['options'] ?? []) as $k => $v) {
        if (property_exists($opt, $k)) {
            $opt->$k = $v;
        }
    }

    $proc = new RefProcessor($opt);
    $proc->setFileFlags(
        !isset($case['is_html']) || !$case['is_html'],
        !empty($case['is_html'])
    );

    $content = (string)($case['input'] ?? '');
    try {
        $proc->transformAll($content);
        $results[] = ['output' => $content];
    } catch (Throwable $e) {
        $results[] = ['error' => $e->getMessage()];
    }
}

fwrite(STDOUT, json_encode($results, JSON_UNESCAPED_UNICODE));
