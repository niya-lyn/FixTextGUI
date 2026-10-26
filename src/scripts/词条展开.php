<?php

use App\Service\Map;
use App\Util\Util;

chdir(__DIR__);

include("autoload.php");

$sortByLen = false;
if (isset($argv[1]) && !empty($argv[1])) {
    $argv[1] = file_get_contents($argv[1]);
    if (!$argv[1]) {
        echo "【参数为空】";
        exit;
    }

    $v = preg_replace('/\s*\/\/.*$/um', '', $argv[1]); // 移除注释

    if (str_contains($v, "【排序】")) {
        $sortByLen = true;
        $v = str_replace("【排序】", "", $v);
    }

    $words = eval("return [{$v}];");
} else {
    // 需要包在这层数组的内部
    $words = [
        [
            'before'        => ["在@@", "载@@"],
            'after'         => "再@@",
            'replaceHolder' => [
                ["去", "来"],
                ["看看", "瞧瞧", "闻闻", "听听"],
            ],
        ],
    ];
}

$words = Map::flattenMaps($words, $sortByLen);
$result = Util::getWordsPrintStr($words);
writeToOutputFile($result);
// file_put_contents("out.txt", $result);
