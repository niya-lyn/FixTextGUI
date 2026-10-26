<?php

// 将分散的含有多个 before 值的词条进行合并，转为多对一的形式
//
// 此过程中会进行查重：
// - 如果是完全重复的，只打印出“已有重复词条”
// - 如果是部分重复的，则会注释“原已有词条”，需要将这部分词条使用“词条写入”整合到原 normalMap

use App\Service\Map;

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

// 目前词条大概都整理好了，没有重复和错乱的
// 后续加新词条的时候也是能整合就整合，不要偷懒先不整合
$normalMap = [];
$extraMap = [];
$strictMap = [];
$accurateDddMap = [];
$oldStyleMap = [];
$dei2deMap = [];

if (isset($argv[2]) && !empty($argv[2])) {
    $mapName = $argv[2];
} else {
    $mapName = "normalMap";
    // $mapName = "extraMap";
    // $mapName = "strictMap";
    // $mapName = "accurateDddMap";
    // $mapName = "oldStyleMap";
}

$integrateAll = false; // 是否需要将原有表的词条全部都整合一遍，没有必要的话不用开启，

// 修改调用 flattenMaps 时的词库变量即可
include("../maps/1.自定义词库.php");
include("../maps/1.自定义词库【旧式、通假写法】.php");
include("../maps/2.繁转简词库.php");
include("../maps/4.的地得词库.php");

// 设置目标 map，需要等词库文件都 include 完之后再设置
$targetMap = $$mapName;

$srcWords = $oSrcWords = [['before' => "", 'after' => ""]];
$comments = [];

if ($integrateAll) {
    $input = $targetMap;
    $input = Map::flattenMaps($input, false);
    $content = file_get_contents($srcFile);
    // 无多余转义：\[['"]before['"] => (.*?), ['"]after['"] => ".*"\], \/\/ (.*)
    preg_match_all("/\[['\"]before['\"] =\> (.*?), ['\"]after['\"] \=\> \".*\"\], \/\/ (.*)/um", $content, $matches);
    foreach ($matches[1] as $bK => $bStr) {
        if (str_contains($bStr, "[")) {
            $bStr = trim($bStr, "[]\"'");
            $bArr = explode("\", \"", $bStr);
            foreach ($bArr as $bV) {
                $comments[] = ["word" => $bV, "comment" => $matches[2][$bK]];
            }
        } else {
            $bStr = trim($bStr, "\"'");
            $comments[] = ["word" => $bStr, "comment" => $matches[2][$bK]];
        }
    }
} else {
    $srcWords = $oSrcWords = array_merge($targetMap, $strictMap);
    $srcWords = Map::flattenMaps($srcWords, false);
}

$scrBefores = array_column($srcWords, "before");
$scrAfters = array_column($srcWords, "after");

$retMap = [];
foreach ($input as $key => $value) {
    if (!isset($input[$key])) {
        continue;
    }

    $tempV = $value;
    foreach ($input as $k => $v) {
        if ($value['after'] != $v['after']) {
            continue;
        }

        $tempV['before'] = (array)$tempV['before'];
        if (is_array($v['before'])) {
            $tempV['before'] = array_merge($tempV['before'], $v['before']);
        } else {
            $tempV['before'][] = $v['before'];
        }
        $tempV['before'] = array_values(array_unique($tempV['before']));
        unset($input[$k]);
    }

    if (count($tempV['before']) == 1) {
        $tempV['before'] = $tempV['before'][0];
    }

    $retMap[] = $tempV;
}

$ret = "";
if (!$integrateAll) {
    $retMapTmp = [];
    foreach ($retMap as $v) {
        // array_search 只能返回第一个匹配项
        // 故 oSrcWords 需要保证是整理过，没有重复 after 项的
        $aK = array_search($v['after'], array_column($oSrcWords, "after"));
        if ($aK !== false) {
            $oWord = $oSrcWords[$aK];
            $v['before'] = array_merge((array)$oWord['before'], (array)$v['before']);
            $v['before'] = array_values(array_unique($v['before']));

            if (count($v['before']) == 1) {
                $v['before'] = $v['before'][0];
            }

            if ($v['before'] == $oWord['before']) {
                $ret .= "    // 已有重复词条：【{$oWord['after']}】" . PHP_EOL;
                continue;
            }
        }

        $retMapTmp[] = $v;
    }

    $retMap = $retMapTmp;
}

$oExistedRet = "";
foreach ($retMap as $v) {
    if (is_array($v['before'])) {
        if ($comments) {
            foreach ($v['before'] as $bv) {
                $commentK = array_search($bv, array_column($comments, "word"));
                if ($commentK !== false) {
                    $v['comment'] = $comments[$commentK]['comment'];
                    break;
                }
            }
        }

        $v["before"] = '["' . implode('", "', $v['before']) . '"]';
        $ret .= "    ['before' => {$v['before']},";
    } else {
        if ($comments) {
            $commentK = array_search($v['before'], array_column($comments, "word"));
            if ($commentK !== false) {
                $v['comment'] = $comments[$commentK]['comment'];
            }
        }

        $ret .= "    ['before' => \"{$v['before']}\",";
    }

    if (is_array($v['after'])) {
        $v["after"] = '["' . implode('", "', $v['after']) . '"]';
        $ret .= " 'after' => {$v['after']}";
    } else {
        $ret .= " 'after' => \"{$v['after']}\"";
    }

    if (in_array($v['after'], $scrAfters)) {
        $ret .= "], // 原已有词条" . PHP_EOL;
        $oExistedRet .= "'after' => \"{$v['after']}\"]," . PHP_EOL;
    } else if (isset($v['comment'])) {
        $ret .= "], // {$v['comment']}" . PHP_EOL;
    } else {
        $ret .= "]," . PHP_EOL;
    }
}

$lines = explode(PHP_EOL, $ret);
usort($lines, function ($a, $b) {
    if (str_contains($a, "原已有词条")) {
        return -1;
    }

    if (str_contains($b, "原已有词条")) {
        return 1;
    }

    return 0;
});
$ret = implode(PHP_EOL, $lines);

if ($integrateAll) {
    file_put_contents("newMap.php", $ret);
} else {
    // file_put_contents("out.txt", $ret);
    writeToOutputFile($ret);
    // echo "======== 以下是原已有词条列表 =========" . PHP_EOL;
    // echo $oExistedRet;
}
