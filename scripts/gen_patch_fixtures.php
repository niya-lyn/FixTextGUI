<?php
/**
 * 生成 PatchAnalyzer 权威基准向量。
 *
 * 对若干组「原文 / 改后文」用 diff -u 生成真实 patch，
 * 再用上游真实的 App\Util\PatchAnalyzer 解析，
 * 输出 (befores, afters)，供 Python 测试作为外部权威断言源。
 *
 * 用法: php scripts/gen_patch_fixtures.php <fixtext_src_dir> > tests/fixtures/patch_analyzer_php.json
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_NOTICE);

$srcDir = rtrim($argv[1], '/');
require_once($srcDir . '/vendor/autoload.php');

use App\Util\PatchAnalyzer;

// 每组：原始文本 -> 校正后文本
$cases = [
    'single_change' => [
        "第一行\n第二行\n第三行\n",
        "第一行\n第二行改了\n第三行\n",
    ],
    'insert_line' => [
        "第一行\n第三行\n",
        "第一行\n第二行\n第三行\n",
    ],
    'delete_line' => [
        "第一行\n第二行\n第三行\n",
        "第一行\n第三行\n",
    ],
    'two_separated' => [
        "A1\nA2\nA3\nA4\nA5\nA6\nA7\nA8\nA9\nA10\nA11\nA12\n",
        "B1\nA2\nA3\nA4\nA5\nA6\nA7\nA8\nA9\nA10\nA11\nB12\n",
    ],
    'merged_multi' => [
        "A\nB\nC\nD\n",
        "A2\nB2\nC2\nD\n",
    ],
    'no_change' => [
        "同样的内容\n第二行\n",
        "同样的内容\n第二行\n",
    ],
    'punct_change' => [
        "他说：“你好”。\n然后走了\n",
        "他说：“你好！”\n然后走了\n",
    ],
    'cjk_typo' => [
        "他慢慢的走过来\n站在原地\n",
        "他慢慢地走过来\n站在原地\n",
    ],
];

$tmpDir = sys_get_temp_dir() . '/patch_fixture_' . getmypid();
@mkdir($tmpDir, 0777, true);

$out = [];
foreach ($cases as $name => $pair) {
    list($orig, $fixed) = $pair;
    $origFile  = "$tmpDir/$name.orig.txt";
    $fixedFile = "$tmpDir/$name.fixed.txt";
    $patchFile = "$tmpDir/$name.patch";

    file_put_contents($origFile, $orig);
    file_put_contents($fixedFile, $fixed);

    exec("diff -u " . escapeshellarg($origFile) . " " . escapeshellarg($fixedFile)
        . " > " . escapeshellarg($patchFile) . " 2>/dev/null", $o, $rc);

    $patchContent = file_get_contents($patchFile);

    $entry = [
        'name'          => $name,
        'orig'          => $orig,
        'fixed'         => $fixed,
        'patch'         => $patchContent,
    ];

    if ($rc === 0) {
        // 无差异：上游不会调用分析器，这里也不解析
        $entry['befores'] = [];
        $entry['afters']  = [];
        $entry['error']   = null;
    } else {
        try {
            $analyzer = new PatchAnalyzer();
            $ret = $analyzer->getDiffFromPatchFile($patchFile);
            $entry['befores'] = $ret[0];
            $entry['afters']  = $ret[1];
            $entry['error']   = null;
        } catch (Throwable $e) {
            $entry['befores'] = [];
            $entry['afters']  = [];
            $entry['error']   = get_class($e) . ': ' . $e->getMessage();
        }
    }

    $out[] = $entry;
}

// 清理
foreach (glob("$tmpDir/*") as $f) { @unlink($f); }
@rmdir($tmpDir);

echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT), "\n";
