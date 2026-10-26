<?php

use App\Util\Util;
use App\Service\Formatting\Option;
use App\Service\Formatting\FileProcessor;

ini_set("memory_limit", "4096M");
date_default_timezone_set("Asia/Shanghai");
mb_internal_encoding("UTF-8");

const REPLACE_BY_GO = true;
define("SCRIPT_DIR", dirname(__DIR__));
define("GO_REPLACE_CMD_FILE", __FILE__);

require(__DIR__ . "/../vendor/autoload.php");

function writeToOutputFile($data)
{
    file_put_contents(__DIR__ . "/tmp_output.txt", $data);
}

// 【数组去重】
// $a = [];
// $b = [];
// echo Util::jsonEncode(array_values(array_unique(array_merge($a, $b))));

// 【字符去重】
// echo Util::mergeUniqueChars("aaa");

// Util::sortWordsWithPrefix([
// ], true); // true-扩展标点 false-扩展字符串 需要执行两次

// Util::sortWordsWithSuffix([
// ], true); // true-扩展标点 false-扩展字符串 需要执行两次

// 【JSON 转词条】
// $json = <<<DOC
// [
//     {
//       "before": "“关键是就是看谁的势力大，如果掌门握住了权柄",
//       "after": "“关键就是看谁的势力大，如果掌门握住了权柄"
//     }
// ]
// DOC;

// echo Util::getWordsPrintStr(json_decode($json, true));
// echo "\n注意加上这个标记：\n\$genByNotes = true;\n";
