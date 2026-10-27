<?php
/**
 * 生成第三组权威基准向量：多行 ^ 替换、词库文件合并、插入位置定位。
 *
 * 直接调用上游真实实现（含 protected 方法，用 Reflection 访问），
 * 作为 Python 测试的外部权威断言源。
 *
 * 用法: php scripts/gen_map_fixtures.php <fixtext_src_dir> > tests/fixtures/map_php.json
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);

$srcDir = rtrim($argv[1], '/');

define("SCRIPT_DIR", $srcDir);
define("BOOK_DIR", $srcDir . "/../books");
define("BOOK_BAK_DIR", $srcDir . "/../books");
define("BOOK_FIX_DIR", $srcDir . "/../booksFix");
define("EPUB_MERGE_LOG_DIR", $srcDir . "/../logs/merge");
define("EPUB_LIST_LOG", $srcDir . "/../logs/epub_list.log");
define("REPORT_DIR", $srcDir . "/../logs/report");
const EPUB_EXTRACT_PREFIX = "【EPUB 解压文件夹】";
const EPUB_MERGE_PREFIX = "【EPUB 合并文件】";
const RECURSIVE_FIX = true;
const REPACK_AFTER_FIX = false;
const EXCLUDE_DIRS = [];
define("TEMP_MAP_FILE", SCRIPT_DIR . "/maps/5.临时校对表.php");
const REPLACE_BY_GO = false;
define("GO_REPLACE_CMD_FILE", $srcDir . "/tools/replace_by_go.exe");
const TXT_REPLACE_BEFORE = SCRIPT_DIR . "/TXT_REPLACE_BEFORE.txt";
const TXT_REPLACE_AFTER = SCRIPT_DIR . "/TXT_REPLACE_AFTER.txt";
const TOKENIZE_CONTENT = false;
define("GOJIEBA_CMD_FILE", $srcDir . "/tools/gojieba.exe");
const GOJIEBA_DICT = SCRIPT_DIR . "/tools/gojieba_dict.txt";

require_once($srcDir . '/vendor/autoload.php');

use App\Service\Diff\Extractor;
use App\Service\Diff\Option;

$out = [];

// ---------- 1. preg_replace('/^/m') ----------
$mlCases = [
    "'before' => \"A\", 'after' => \"B\",",
    "行一\n行二",
    "行一\n",
    "",
    "单行无换行",
    "a\n\nb",
    // 边界：末尾换行、连续末尾换行、纯换行
    "a\n\n",
    "\n",
    "a\nb\n",
    "\n\n",
    "a\n\nb\n",
];
foreach ($mlCases as $i => $c) {
    $out[] = [
        'fn' => 'pregReplaceMultilineStart', 'label' => "case$i", 'args' => [$c],
        'expected' => preg_replace('/^/m', '    ', $c), 'error' => null,
    ];
}

// ---------- 2. 词库文件合并 / 插入位置 ----------
function reflectCall($obj, string $method, array $args)
{
    $ref = new ReflectionMethod($obj, $method);
    $ref->setAccessible(true);
    return $ref->invokeArgs($obj, $args);
}

$extractor = new Extractor(new Option());

// 已有词条的词库：插入位置
$existing = <<<'PHP'
<?php

return [
    'bookNotes' => [
        ['before' => "错字A", 'after' => "正字A"],
        ['before' => "错字B", 'after' => "正字B"],
    ],
];
PHP;

$empty = <<<'PHP'
<?php

return [
    'bookNotes' => [
    ],
];
PHP;

$out[] = [
    'fn' => 'findBookNotesInsertPosition', 'label' => 'existing', 'args' => [$existing],
    'expected' => reflectCall($extractor, 'findBookNotesInsertPosition', [$existing]), 'error' => null,
];
$out[] = [
    'fn' => 'findBookNotesInsertPosition', 'label' => 'empty', 'args' => [$empty],
    'expected' => reflectCall($extractor, 'findBookNotesInsertPosition', [$empty]), 'error' => null,
];

// findClosingBracket
// 注意：上游 $startPos 是「'[' 之后」的位置（depth 初始为 1），
// 若传入 '[' 本身的下标，深度会先自增而永不归零 —— 这是探针参数语义，非实现差异。
$fbCases = [
    ['abc[def]ghi', 4],        // '[' at 3 -> 应从 4 起扫，配对 ']' at 7
    ['[a[b]c]d', 1],           // 从 1 起扫，内层 [ at 3、] at 5，外层 ] at 6
    ['not a bracket', 0],      // 无 '['，直接扫描到串尾 -> False
    ['["a]b"]tail', 1],        // 引号内的 ']' 不算，真正配对 ']' at 6
    ['[unclosed', 1],          // 未闭合 -> False
    ['[]', 1],                 // 空括号，']' at 1
];
foreach ($fbCases as $i => $c) {
    $out[] = [
        'fn' => 'findClosingBracket', 'label' => "case$i", 'args' => $c,
        'expected' => reflectCall($extractor, 'findClosingBracket', $c), 'error' => null,
    ];
}

// ---------- 3. mergeToBookMapFile ----------
$tmpRoot = sys_get_temp_dir() . '/mapfx_' . getmypid();
@mkdir($tmpRoot . '/maps/书籍专有替换词库', 0777, true);

// 场景 A：新建词库文件
$bookWordsA = [
    ['before' => '错字甲', 'after' => '正字甲'],
];
try {
    reflectCall($extractor, 'mergeToBookMapFile', ['测试书A', $bookWordsA]);
    $fileA = $tmpRoot . '/maps/书籍专有替换词库/测试书A.php';
    // 上游 SCRIPT_DIR 指向真实 src，这里直接读真实写入位置做对照
    $realA = $srcDir . '/maps/书籍专有替换词库/测试书A.php';
    $contentA = file_exists($realA) ? file_get_contents($realA) : null;
    $out[] = [
        'fn' => 'mergeToBookMapFile', 'label' => 'new_file',
        'args' => ['测试书A', $bookWordsA],
        'expected' => $contentA, 'error' => null,
    ];
    if (file_exists($realA)) { @unlink($realA); }
} catch (Throwable $e) {
    $out[] = ['fn' => 'mergeToBookMapFile', 'label' => 'new_file',
              'args' => ['测试书A', $bookWordsA], 'expected' => null,
              'error' => get_class($e) . ': ' . $e->getMessage()];
}

// 场景 B：向已有词条的词库追加
$existingBook = '测试书B';
$realB = $srcDir . '/maps/书籍专有替换词库/' . $existingBook . '.php';
file_put_contents($realB, $existing);
try {
    reflectCall($extractor, 'mergeToBookMapFile', [$existingBook, [
        ['before' => '错字C', 'after' => '正字C'],
    ]]);
    $out[] = [
        'fn' => 'mergeToBookMapFile', 'label' => 'append_existing',
        'args' => [$existingBook, [['before' => '错字C', 'after' => '正字C']]],
        'expected' => file_get_contents($realB), 'error' => null,
    ];
} catch (Throwable $e) {
    $out[] = ['fn' => 'mergeToBookMapFile', 'label' => 'append_existing',
              'args' => [$existingBook, []], 'expected' => null,
              'error' => get_class($e) . ': ' . $e->getMessage()];
}
@unlink($realB);

// 场景 C：空词条应返回 false
try {
    $ret = reflectCall($extractor, 'mergeToBookMapFile', ['测试书C', []]);
    $out[] = [
        'fn' => 'mergeToBookMapFile', 'label' => 'empty_words', 'args' => ['测试书C', []],
        'expected' => $ret, 'error' => null,
    ];
    $rc = $srcDir . '/maps/书籍专有替换词库/测试书C.php';
    if (file_exists($rc)) { @unlink($rc); }
} catch (Throwable $e) {
    $out[] = ['fn' => 'mergeToBookMapFile', 'label' => 'empty_words',
              'args' => ['测试书C', []], 'expected' => null,
              'error' => get_class($e) . ': ' . $e->getMessage()];
}

// 清理临时目录
@rmdir($tmpRoot . '/maps/书籍专有替换词库');
@rmdir($tmpRoot . '/maps');
@rmdir($tmpRoot);

echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT), "\n";
