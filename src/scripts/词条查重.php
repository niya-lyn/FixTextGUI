<?php

use App\Util\Util;

chdir(__DIR__);

include("autoload.php");

// 词条查重
$normalMap = [];
$extraMap = [];
$strictMap = [];
$accurateDddMap = [];
$oldStyleMap = [];
$shengpiziMap = [];

if (isset($argv[2]) && !empty($argv[2])) {
    $mapName = $argv[2];
} else {
    $mapName = "normalMap";
    // $mapName = "extraMap";
    // $mapName = "strictMap";
    // $mapName = "accurateDddMap";
    // $mapName = "oldStyleMap";
}

$srcFile = "../maps/1.自定义词库.php";
include($srcFile);

$srcFile1 = "../maps/1.自定义词库【旧式、通假写法】.php";
include($srcFile1);

$srcFile2 = "../maps/4.的地得词库.php";
include($srcFile2);

$srcFile3 = "../maps/7.生僻字词库.php";
include($srcFile3);

$srcFile4 = "../maps/2.繁转简词库.php";
include($srcFile4);

// 设置目标 map
$targetMap = $$mapName;

// after+mark 连在一起还是重复的才算重复
$combinedStrings = [];
foreach ($targetMap as $element) {
    $mark = $element['mark'] ?? "";
    $combinedStrings[] = $element['after'] . $mark;
}

$duplicates = Util::findDuplicatesInArray($combinedStrings);

// 提前创建哈希表以优化查找性能
$duplicatesSet = array_flip($duplicates);

$ret = array_filter($targetMap, function ($value) use ($duplicatesSet) {
    $mark = $value['mark'] ?? "";
    $after = $value['after'] . $mark;

    // 含 replaceHolder 的一律不算重复
    return isset($duplicatesSet[$after]) && !str_contains($after, "@");
});

$ret = Util::getWordsPrintStr($ret) ?: "【无重复词条】";
writeToOutputFile($ret);
