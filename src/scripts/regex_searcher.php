<?php

chdir(__DIR__);

include("autoload.php");

// 增加错误处理，将 PHP 警告（如无效的正则表达式）转换为可捕获的异常
set_error_handler(function ($severity, $message, $file, $line) {
    throw new ErrorException($message, 0, $severity, $file, $line);
});

class RegexSearcher
{
    /**
     * 执行搜索并将结果写入文件
     *
     * @param string $regexFilepath   包含正则表达式的临时文件路径
     * @param string $targetFilepath  待搜索的目标文件路径
     * @param string $resultFilepath  用于写入 JSON 结果的临时文件路径
     */
    public function search(string $regexFilepath, string $targetFilepath, string $resultFilepath): void
    {
        try {
            // 步骤 1: 验证并加载输入文件
            [$pattern, $content] = $this->loadInputs($regexFilepath, $targetFilepath);
            if (empty($content)) {
                // 如果文件内容为空，直接返回成功和空数组
                $this->writeResult($resultFilepath, ['status' => 'success', 'data' => []]);
                return;
            }

            // 步骤 2: 执行正则表达式匹配
            $matches = $this->findMatches($pattern, $content);

            // 步骤 3: 将字节偏移量转换为字符偏移量
            $charPositions = $this->byteToCharOffsets($matches, $content);

            // 步骤 4: 写入最终结果
            $this->writeResult($resultFilepath, ['status' => 'success', 'data' => $charPositions]);
        } catch (Throwable $e) {
            // 构造详细的错误信息
            $errorMessage = 'PHP Error: ' . $e->getMessage() . ' in ' . $e->getFile() . ' on line ' . $e->getLine();

            // 将错误信息同时输出到 stderr 和结果文件
            fwrite(STDERR, $errorMessage . "\n");
            $this->writeResult($resultFilepath, ['status' => 'error', 'message' => $errorMessage]);

            // 以非零状态码退出，明确表示执行失败
            exit(1);
        }
    }

    /**
     * 验证并加载输入文件内容
     *
     * @param string $regexFilepath
     * @param string $targetFilepath
     * @return array{0: string, 1: string} 返回包含正则表达式和目标内容的数组
     * @throws Exception 如果文件无法读取
     */
    private function loadInputs(string $regexFilepath, string $targetFilepath): array
    {
        if (!file_exists($regexFilepath) || !is_readable($regexFilepath)) {
            throw new Exception("无法读取正则表达式文件: {$regexFilepath}");
        }

        if (!file_exists($targetFilepath) || !is_readable($targetFilepath)) {
            throw new Exception("无法读取目标文件: {$targetFilepath}");
        }

        $pattern = file_get_contents($regexFilepath);
        if ($pattern === false) {
            throw new Exception('读取正则表达式文件失败');
        }

        $content = file_get_contents($targetFilepath);
        if ($content === false) {
            throw new Exception('读取目标文件内容失败');
        }

        return [$pattern, $content];
    }

    /**
     * 执行正则匹配，获取所有匹配项及其字节偏移量
     *
     * @param string $pattern 正则表达式
     * @param string $content 目标内容
     * @return array 返回 preg_match_all 的匹配结果
     * @throws Exception 如果正则执行出错
     */
    private function findMatches(string $pattern, string $content): array
    {
        // 使用 @ 来抑制 preg_match_all 可能产生的 E_WARNING, 错误将通过 preg_last_error() 捕获
        @preg_match_all($pattern, $content, $matches, PREG_OFFSET_CAPTURE);

        if (preg_last_error() !== PREG_NO_ERROR) {
            throw new Exception('正则表达式执行错误: ' . preg_last_error());
        }

        return $matches;
    }

    /**
     * 将匹配结果中的【字节】偏移量高效地转换为【字符】偏移量
     *
     * @param array $matches 来自 findMatches() 的原始匹配结果
     * @param string $content 完整的搜索内容
     * @return int[] 包含所有匹配项【字符】偏移量的数组
     */
    private function byteToCharOffsets(array $matches, string $content): array
    {
        // PREG_OFFSET_CAPTURE 返回的是【字节】偏移量，必须转换，否则位置和 python 搜索结果对不上……
        // 现在的结构为二维数组： [[start_char, end_char], [start_char, end_char], ...]
        $charPositions = [];

        if (isset($matches[0]) && is_array($matches[0])) {
            // 初始化计数器
            $lastCharOffset = 0;
            $lastByteOffset = 0;

            // 使用增量计算法，避免对长字符串重复调用 mb_strlen
            foreach ($matches[0] as $match) {
                $matchedString = $match[0]; // a.1 匹配到的具体文本
                $currentByteOffset = $match[1]; // a.2 获取当前匹配的字节偏移量

                // b. 计算从上一个匹配到当前匹配之间的字节长度
                $byteLengthOfSegment = $currentByteOffset - $lastByteOffset;

                // c. 如果存在间隙，则计算这个【小片段】的字符数
                if ($byteLengthOfSegment > 0) {
                    // 通过字节偏移量获取【小片段】
                    $segment = substr($content, $lastByteOffset, $byteLengthOfSegment);
                    // 此处计算【小片段】的【字符】长度
                    $charsInSegment = mb_strlen($segment, 'UTF-8');
                    // d. 累加到总字符偏移量上
                    $lastCharOffset += $charsInSegment;
                }

                // e. 此时 $lastCharOffset 就是起点字符偏移量
                $startCharOffset = $lastCharOffset;

                // f. 计算匹配文本本身的字符长度
                $matchCharLength = mb_strlen($matchedString, 'UTF-8');
                $endCharOffset = $startCharOffset + $matchCharLength;

                // g. 保存起点和终点
                $charPositions[] = [$startCharOffset, $endCharOffset];
                $lastByteOffset = $currentByteOffset + strlen($matchedString);
                // 字符指针也同步推进到末尾
                $lastCharOffset = $endCharOffset;
            }
        }

        return $charPositions;
    }

    /**
     * 将结果数组编码为 JSON 并写入文件
     *
     * @param string $filepath 结果文件路径
     * @param array $data 待写入的数据
     */
    private function writeResult(string $filepath, array $data): void
    {
        $jsonData = json_encode($data, JSON_UNESCAPED_UNICODE);

        if ($jsonData === false || file_put_contents($filepath, $jsonData) === false) {
            // 如果连结果文件都无法写入，这是一个致命问题，直接向 stderr 输出错误
            fwrite(STDERR, "致命错误：无法写入结果文件 {$filepath}\n");
            exit(1);
        }
    }
}

// --- 脚本入口 ---

// 检查命令行参数数量是否正确
if ($argc !== 4) {
    fwrite(STDERR, "用法: php {$argv[0]} <regex_file> <target_file> <result_file>\n");
    exit(1);
}

$regexFilepath = $argv[1];
$targetFilepath = $argv[2];
$resultFilepath = $argv[3];

$searcher = new RegexSearcher();
$searcher->search($regexFilepath, $targetFilepath, $resultFilepath);

// 正常执行完毕，以状态码 0 退出
exit(0);
