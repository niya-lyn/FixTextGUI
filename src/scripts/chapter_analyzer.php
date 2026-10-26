<?php

use App\Util\ChapterAnalyzer;
use App\Util\Util;

chdir(__DIR__);

include("autoload.php");

// 1. 获取输入文件内容
$inputFile = Util::getArgvByIndex(1);
if (!file_exists($inputFile)) {
    exit(1); // 文件不存在，非零退出
}
$content = file_get_contents($inputFile);

// 2. 分析章节
$analysisResult = ChapterAnalyzer::analyze($content);

// 3. 生成临时文件路径
$tempFilePath = tempnam(sys_get_temp_dir(), 'chapter_json_');
if ($tempFilePath === false) {
    fwrite(STDERR, "Failed to create temporary file.\n");
    exit(1);
}

// 4. 将 JSON 数据写入临时文件
$jsonData = json_encode($analysisResult, JSON_UNESCAPED_UNICODE);
if (file_put_contents($tempFilePath, $jsonData) === false) {
    fwrite(STDERR, "Failed to write to temporary file.\n");
    exit(1);
}

// 5. 输出临时文件的路径
echo $tempFilePath;
