<?php

// 一次性脚本，用于增加 bookNotes 索引字段

chdir(__DIR__);

include("autoload.php");

// --- 配置区 ---
// 请将此路径设置为您存放书籍专有词库的目录
$mapDir = "../maps/书籍专有替换词库";
// ---------------------

// --- 脚本主体 ---
if (empty($mapDir) || !is_dir($mapDir)) {
    die("错误：请在 \$mapDir 变量中提供一个有效的目录路径。\n");
}

echo "开始处理目录: {$mapDir}\n\n";

$iterator = new DirectoryIterator($mapDir);

foreach ($iterator as $fileinfo) {
    if (!$fileinfo->isFile() || $fileinfo->getExtension() !== 'php') {
        continue;
    }

    $filePath = $fileinfo->getPathname();
    echo "正在处理文件: {$filePath}\n";

    $lines = file($filePath, FILE_IGNORE_NEW_LINES);

    if ($lines === false) {
        echo "  -> 跳过: 无法读取文件。\n";
        continue;
    }

    $contentAsString = implode("\n", $lines);
    if (strpos($contentAsString, "'bookNotes' =>") !== false) {
        echo "  -> 跳过: 文件似乎已经处理过。\n";
        continue;
    }

    $returnStartIndex = -1;
    $returnEndIndex = -1;

    // 寻找 return [...] 的边界
    foreach ($lines as $i => $line) {
        if (trim($line) === 'return [') {
            $returnStartIndex = $i;
            break;
        }
    }
    for ($i = count($lines) - 1; $i >= 0; $i--) {
        if (trim($lines[$i]) === '];') {
            $returnEndIndex = $i;
            break;
        }
    }

    if ($returnStartIndex === -1 || $returnEndIndex === -1 || $returnStartIndex >= $returnEndIndex) {
        echo "  -> 跳过: 未找到 'return [...]' 结构。\n";
        continue;
    }

    // 寻找第一个标记行或词条行
    $targetStartIndex = -1;
    for ($i = $returnStartIndex + 1; $i < $returnEndIndex; $i++) {
        $trimmedLine = trim($lines[$i]);
        if (strpos($trimmedLine, '/* 新增下列词条的时间点：') === 0 || strpos($trimmedLine, "['before' =>") === 0) {
            $targetStartIndex = $i;
            break;
        }
    }

    if ($targetStartIndex === -1) {
        echo "  -> 跳过: 未找到需要格式化的标记行或词条行。\n";
        continue;
    }

    // --- 构建新文件内容 ---
    $newContent = [];

    // 1. 添加目标区块之前的所有内容 (包括 <?php, return[, 'excludedWords' => ... 等)
    $newContent = array_merge($newContent, array_slice($lines, 0, $targetStartIndex));

    // 2. 获取基础缩进
    preg_match('/^(\s*)/', $lines[$targetStartIndex], $matches);
    $baseIndent = $matches[1] ?? '';

    // 3. 添加 'bookNotes' 的起始部分
    $newContent[] = $baseIndent . "'bookNotes' => [";

    // 4. 提取需要被包裹和缩进的词条行
    $targetLines = array_slice($lines, $targetStartIndex, $returnEndIndex - $targetStartIndex);
    foreach ($targetLines as $line) {
        // 为每行增加 4 个空格的缩进，空行保持不变
        if (trim($line) === '') {
            $newContent[] = '';
        } else {
            $newContent[] = '    ' . $line;
        }
    }

    // 5. 闭合 'bookNotes' 数组
    $newContent[] = $baseIndent . "],";

    // 6. 添加文件的结束部分 '];'
    $newContent[] = $lines[$returnEndIndex];

    // 7. 如果 '];' 后面还有内容，也一并添加
    if ($returnEndIndex < count($lines) - 1) {
        $newContent = array_merge($newContent, array_slice($lines, $returnEndIndex + 1));
    }

    // 将新内容写回文件
    $newContent = implode("\n", $newContent) . "\n";
    file_put_contents($filePath, $newContent);
    echo "  -> 成功: 文件已格式化并保存。\n";
}

echo "\n所有文件处理完毕。\n";
