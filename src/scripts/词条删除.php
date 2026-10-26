<?php

// 从原文件检索词条并移出来后，将词条从原文件删掉，便于重新整合词条

chdir(__DIR__);

include("autoload.php");

if (isset($argv[1]) && !empty($argv[1])) {
    $argv[1] = file_get_contents($argv[1]);
    if (!$argv[1]) {
        echo "【参数为空】";
        exit;
    }

    $input = $argv[1];
} else {
    $input = <<<INPUT
        ['before' => "喝得酪酊", 'after' => "喝得酩酊"],
        ['before' => "的奶酷", 'after' => "的奶酪"],
        ['before' => "残酪", 'after' => "残酷"],
        ['before' => "奶酷", 'after' => "奶酪"],
        ['before' => "乳酷", 'after' => "乳酪"],
    INPUT;
}

if (isset($argv[2]) && !empty($argv[2])) {
    $mapFilename = $argv[2];
} else {
    $mapFilename = "1.自定义词库.php";
    // $mapFilename = "3.txtFormat 词库.php";
    // $mapFilename = "2.繁转简词库.php";
    // $mapFilename = "4.的地得词库.php";
}

$mapFile = dirname(__DIR__) . "/maps/{$mapFilename}";

$input = preg_replace([
    '/\r\n/',
    '/\/\/\s+【第.*?行】$/um' // 移除行号标记
], [
    "\n",
    ''
], $input);

$input = array_filter(
    array_unique(explode("\n", $input)),
    function ($v) {
        return strlen(trim($v)) > 0;
    }
);

$input = array_values(array_map('trim', $input));

$fp = fopen($mapFile, 'r');
$result = [];
while (!feof($fp)) {
    $line = fgets($fp);

    $found = false;
    foreach ($input as $k => $v) {
        if (str_contains($line, $v) && !str_contains($line, "原已有词条")) {
            unset($input[$k]);
            $found = true;
            break;
        }
    }

    if ($found) {
        continue;
    }

    $result[] = $line;
}
fclose($fp);

file_put_contents($mapFile, implode($result));

writeToOutputFile("【已删除完毕】");
