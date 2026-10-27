<?php
/**
 * 生成核心函数的权威基准向量（第二组）。
 *
 * 直接调用上游真实的 Util / Extractor 方法，输出结果作为 Python 测试的
 * 外部权威断言源：extractStrDiff、trimUnicodeChars、getFilename、
 * getWordsPrintStr、changeEncodingAndNewLineType 等。
 *
 * 用法: php scripts/gen_core_fixtures.php <fixtext_src_dir> > tests/fixtures/core_php.json
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);

$srcDir = rtrim($argv[1], '/');

// 上游 main.php 中的全局常量，Util::removeEpubMergePrefix 依赖它
const EPUB_MERGE_PREFIX = "【EPUB 合并文件】";

require_once($srcDir . '/vendor/autoload.php');

use App\Util\Util;

function probe(string $fn, string $label, array $args, callable $call): array
{
    try {
        return ['fn' => $fn, 'label' => $label, 'args' => $args, 'expected' => $call(), 'error' => null];
    } catch (Throwable $e) {
        return ['fn' => $fn, 'label' => $label, 'args' => $args, 'expected' => null,
                'error' => get_class($e) . ': ' . $e->getMessage()];
    }
}

$out = [];

// ---------------- extractStrDiff ----------------
$extractCases = [
    ["abcXdef", "abcYdef", 0],
    ["abcXdef", "abcYdef", 1],
    ["abcXdef", "abcYdef", 3],
    ["abcXdef", "abcYdef", 10],
    ["完全相同的字符串", "完全相同的字符串", 3],
    ["前缀", "前缀延伸", 2],
    ["前缀延伸", "前缀", 2],
    ["短的", "长的内容完全多一点", 1],
    ["他说：“你好”。", "他说：“你好！”", 3],
    ["他慢慢的走过来", "他慢慢地走过来", 3],
    ["", "abc", 2],
    ["abc", "", 2],
    ["甲乙丙丁戊", "甲乙X丁戊", 2],
];
foreach ($extractCases as $i => $c) {
    $out[] = probe('extractStrDiff', "case$i", $c, function () use ($c) {
        return Util::extractStrDiff($c[0], $c[1], $c[2]);
    });
}

// ---------------- trimUnicodeChars ----------------
$trimCases = [
    ["  内容  ", " 　", "both"],
    ["　全角空格内容　", " 　", "both"],
    ["  left", " ", "left"],
    ["right  ", " ", "right"],
    ["不裁剪", " 　", "both"],
    ["", " ", "both"],
    ["内容", "", "both"],
    ["　，。内容。，　", "　，。", "both"],
    ["\t\n内容\n\t", " \n\r\t", "both"],
];
foreach ($trimCases as $i => $c) {
    $out[] = probe('trimUnicodeChars', "case$i", $c, function () use ($c) {
        return Util::trimUnicodeChars($c[0], $c[1], $c[2]);
    });
}

// ---------------- getFilename ----------------
$fnCases = [
    "普通书名.txt",
    "【EPUB 合并文件】某书.txt",
    "带.点.的书名.txt",
    "noext",
    ".hidden",
    "路径/子目录/书名.txt",
];
foreach ($fnCases as $i => $c) {
    $out[] = probe('getFilename', "case$i", [$c], function () use ($c) {
        return Util::getFilename($c);
    });
    $out[] = probe('getFilenameEpub', "case$i", [$c, true], function () use ($c) {
        return Util::getFilename($c, true);
    });
}

// ---------------- removeEpubMergePrefix ----------------
foreach (["【EPUB 合并文件】某书", "无前缀书名", "中【EPUB 合并文件】间"] as $i => $c) {
    $out[] = probe('removeEpubMergePrefix', "case$i", [$c], function () use ($c) {
        return Util::removeEpubMergePrefix($c);
    });
}

// ---------------- getWordsPrintStr ----------------
$printCases = [
    ['single', [['before' => '错字', 'after' => '正字']], '', false],
    ['single_info', [['before' => '错字', 'after' => '正字']], '替换次数: 【3】', false],
    ['multi', [['before' => '错字', 'after' => '正字']], '', true],
    ['multi_info', [['before' => '错字', 'after' => '正字']], '说明', true],
    ['batch', [['before' => 'A', 'after' => 'B'], ['before' => 'C', 'after' => 'D']], '', false],
    ['with_mark', [['before' => 'A', 'after' => 'B', 'mark' => 'm']], '', false],
];
foreach ($printCases as $i => $c) {
    $out[] = probe('getWordsPrintStr', $c[0], array_slice($c, 1), function () use ($c) {
        return Util::getWordsPrintStr($c[1], $c[2], $c[3]);
    });
}

// ---------------- changeEncodingAndNewLineType ----------------
$nlCases = [
    "行一\r\n行二\r\n",
    "行一\r行二\r",
    "\xEF\xBB\xBF带BOM内容",
    "零宽\xE2\x80\x8B字符",
    "普通内容\n",
];
foreach ($nlCases as $i => $c) {
    $out[] = probe('changeEncodingAndNewLineType', "case$i", [$c], function () use ($c) {
        $copy = $c;
        Util::changeEncodingAndNewLineType($copy);
        return $copy;
    });
}

echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT), "\n";
