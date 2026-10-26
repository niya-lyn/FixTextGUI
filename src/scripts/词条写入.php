<?php

// 暂时只支持写入自定义词库，基本是用于整合别人提交的词条
// 只处理“词条合并”报告出来的“原已有词条”那一部分
// 如果是全新的词条自行手动插入即可
//
// （现在已经自动排序，基本不用 grep 了）记得善用 grep 取出或排除“原已有词条”
// 若条数过多，使用 file_put_contents 输出到文件

chdir(__DIR__);

include("autoload.php");

if (isset($argv[1]) && !empty($argv[1])) {
    $argv[1] = file_get_contents($argv[1]);
    if (!$argv[1]) {
        echo "【参数为空】";
        exit;
    }

    $v = preg_replace('/\s*\/\/.*$/um', '', $argv[1]); // 移除注释
    $input = eval("return [{$v}];");
} else {
    $input = [
        ['before' => "鹰博兔", 'after' => "鹰搏兔"],
        ['before' => "鹰搏免", 'after' => "鹰搏兔"],
        ['before' => "狮子博兔", 'after' => "狮子搏兔"],
        ['before' => "狮子搏免", 'after' => "狮子搏兔"],
    ];
}

if (isset($argv[2]) && !empty($argv[2])) {
    // 暂时只支持写入自定义词库
    $mapFilename = "1.自定义词库.php";
    // $mapFilename = $argv[2];
} else {
    $mapFilename = "1.自定义词库.php";
    // $mapFilename = "3.txtFormat 词库.php";
    // $mapFilename = "2.繁转简词库.php";
    // $mapFilename = "4.的地得词库.php";
}

$mapFile = dirname(__DIR__) . "/maps/{$mapFilename}";

mergeToOld($input, $mapFile);

function mergeToOld($input, $mapFile)
{
    $newLines = [];
    $oldLines = file($mapFile);
    $startMerge = false;
    $afters = array_column($input, "after");
    foreach ($oldLines as $oldLine) {
        if (str_contains($oldLine, "normalMap")) {
            $startMerge = true;
        }

        if ($startMerge && str_contains($oldLine, "regex")) {
            $startMerge = false;
        }

        if ($startMerge) {
            preg_match("/'after' => \"(.*?)\"/um", $oldLine, $matches);
            if (!isset($matches[1])) {
                $newLines[] = $oldLine;
                continue;
            }
            $after = $matches[1];

            $searchKey = array_search($after, $afters);
            if ($searchKey !== false) {
                $newWord = $input[$searchKey];
                $newBefore = implode("\", \"", (array)$newWord['before']);
                $newLines[] = "    ['before' => [\"$newBefore\"], 'after' => \"{$after}\"]," . "\n";
            } else {
                $newLines[] = $oldLine;
            }
        } else {
            $newLines[] = $oldLine;
        }
    }

    file_put_contents($mapFile, implode($newLines));
}

writeToOutputFile("【已写入完毕】");
