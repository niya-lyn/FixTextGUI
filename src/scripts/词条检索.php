<?php

chdir(__DIR__);

include("autoload.php");

// 注意有可能会搜出 extraMap 和 strictMap 等不同 map 中的词条
// 需要对照输出的 Map 信息，自行区分
if (isset($argv[1]) && !empty($argv[1])) {
    $argv[1] = file_get_contents($argv[1]);
    if (!$argv[1]) {
        echo "【参数为空】";
        exit;
    }

    $keywords = explode("|", $argv[1]);
} else {
    $keywords = ["兮兮"];
    // $keywords = ["肆", "肄"];
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

$ret = [];
$metMapLine = false;
$lastMapLineKey = 0;
$lineNum = $prevLineNum = 1;

$fp = fopen($mapFile, 'r');
while (!feof($fp)) {
    $line = fgets($fp);

    if (
        str_starts_with($line, "$")
        && str_ends_with($line, "Map = [\n")
        && !(
            str_contains($line, "regex")
            || str_contains($line, "Regex")
        )
    ) {
        if ($metMapLine) {
            // 如果 metMapLine 持续为 true，说明该 map 中搜不到对应词条，
            // 直接遍历到了下一个 map 行，此时无需记录 map 信息
            unset($ret[$lastMapLineKey]);
            // 需要重置 key，否则会与 lastMapLineKey 记录的不一致
            $ret = array_values($ret);
        }

        $metMapLine = true;
        $trimmedLine = trim($line, "= [\n");
        $mapLine = "// =========================================\n"
            . "// 当前所处的 Map：{$trimmedLine}\n";
        $ret[] = $mapLine;
        $lastMapLineKey = count($ret) - 1;
    }

    foreach ($keywords as $keyword) {
        // 把被注释的也搜出来，后面一起删掉
        if (
            str_contains($line, $keyword)
            && str_contains($line, "before")
        ) {
            if (!str_contains($line, " // 【第")) {
                if ($lineNum - $prevLineNum == 1) {
                    // 连续
                    $line = str_replace("\n", " // 【第 {$lineNum} 行+】\n", $line);
                } else {
                    $line = str_replace("\n", " // 【第 {$lineNum} 行】\n", $line);
                }
                $prevLineNum = $lineNum;
            }
            $ret[] = $line;
            $metMapLine = false;
        }
    }

    $lineNum++;
}
fclose($fp);

// 整个文件遍历完成后，删除最后一个空 map 行
if ($metMapLine) {
    unset($ret[$lastMapLineKey]);
}

if (!$ret) {
    echo "【无匹配记录】";
    exit;
}

$ret = array_values(array_unique($ret));
writeToOutputFile($ret);
