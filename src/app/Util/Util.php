<?php

namespace App\Util;

use DOMXPath;
use Exception;
use Throwable;
use DOMDocument;
use App\Service\Map;
use App\Util\Console\Show;
use App\Exception\AppException;

class Util
{
    const HTML_CHAPTER_MARK = '◎【chapter_mark】';

    // 自定义一些优先级，确保带标点的词条都放到一起
    const WORD_SORT_REF = ['，', '。', '！', '？', '…', '—', '：', '“', '”', '、'];

    /**
     * 在不同字符编码之间转换字符串内容
     *
     * 此方法说明如下：
     * 1. 自动检测编码时，使用优化的检测顺序以提高性能和准确性。
     * 2. 智能处理 GB 系列编码（GB2312, GBK），强制使用其超集 GB18030 进行解码，
     *    以防止因误判而导致的数据丢失。
     * 3. 在转换过程中，使用替代字符来处理无法解码的字节，防止程序中断。
     *
     * @param string $content      要转换的字符串内容（通过引用传递，会被直接修改）
     * @param string $toEncoding   目标编码，默认为 "UTF-8"
     * @param string $fromEncoding 源编码。如果为空，则会自动检测
     * @return void
     * @throws AppException
     */
    public static function convertEncoding(string &$content, string $toEncoding = 'UTF-8', string $fromEncoding = ''): void
    {
        // 如果内容为空，无需任何操作
        if (empty($content)) {
            return;
        }

        // 步骤 1: 如果未提供源编码，则进行自动检测
        if (!$fromEncoding) {
            // 先检查 BOM 头
            if (str_starts_with($content, "\xEF\xBB\xBF")) {
                $fromEncoding = 'UTF-8';
            }
            if (str_starts_with($content, "\xFE\xFF")) {
                $fromEncoding = 'UTF-16BE';
            }
            if (str_starts_with($content, "\xFF\xFE")) {
                $fromEncoding = 'UTF-16LE';
            }

            // 使用优化的编码检测顺序，以提高性能和准确性
            $detectionOrder = [
                'ASCII',
                'UTF-8',
                'GB18030', // 使用 GB18030 代替 GBK 和 GB2312 进行检测
                'UTF-16BE',
                'UTF-16LE',
                'BIG-5',
                'EUC-JP',
                'SJIS',
            ];

            if (!$fromEncoding) {
                $detectedEncoding = false;

                // 采样时先统一换行符
                $normalizedContent = str_replace(["\r\n", "\r"], "\n", $content);
                $lines = explode("\n", $normalizedContent);
                $lineCount = count($lines);

                // 对于大文件，先尝试基于头部 100 行样本进行检测，以提高性能
                if ($lineCount > 100) {
                    $sampleLines = array_slice($lines, 0, 100);
                    $sample = implode("\n", $sampleLines);
                    $detectedEncoding = mb_detect_encoding($sample, $detectionOrder, true);
                    // 启发式修正：处理 UTF-8 文本被误判为 UTF-16 的情况
                    // 如果检测结果为 UTF-16，但内容本身也完全符合 UTF-8 规范，
                    // 则优先采信 UTF-8，因为这种歧义情况多数是 UTF-8 引起的
                    if (
                        ($detectedEncoding === 'UTF-16LE' || $detectedEncoding === 'UTF-16BE')
                        && mb_check_encoding($sample, 'UTF-8')
                    ) {
                        $fromEncoding = 'UTF-8';
                    } else {
                        $fromEncoding = $detectedEncoding;
                    }
                }
            }

            // 如果基于样本的检测失败，或者文件不够大，则对完整内容进行检测
            if (!$fromEncoding) {
                $fromEncoding = mb_detect_encoding($content, $detectionOrder, true);
            }
        }

        // 如果检测失败，或者内容本身没有编码（如纯二进制），抛出异常
        if (!$fromEncoding) {
            throw new AppException('检测到文件使用了未知编码，无法转换，请先使用其他编辑器调整编码');
        }

        // 步骤 2: 检查是否需要转换，使用不区分大小写的比较更稳妥
        if (strcasecmp($fromEncoding, $toEncoding) === 0) {
            return;
        }

        // 步骤 3: 智能处理 GB 系列编码
        // PHP 中，GB2312 常被称为 'EUC-CN'，GBK 被称为 'CP936'
        // 为确保最大兼容性，无论检测到哪个变体，都强制使用 'GB18030' 作为源编码
        $gbFamily = ['GB2312', 'EUC-CN', 'GBK', 'CP936', 'GB18030'];
        if (in_array(strtoupper($fromEncoding), $gbFamily, true)) {
            $fromEncoding = 'GB18030';

            // 再次检查，如果修正后的源编码与目标编码相同，则无需转换
            if (strcasecmp($fromEncoding, $toEncoding) === 0) {
                return;
            }
        }

        // 步骤 4: 执行转换
        $convertedContent = mb_convert_encoding($content, $toEncoding, $fromEncoding);

        // 如果转换失败，保持原内容不变，避免清空变量
        if ($convertedContent !== false) {
            $content = $convertedContent;
        }
    }

    /**
     * @throws AppException
     */
    public static function recursiveUnifyTextFormat(string $dir, string $toEncoding = "", string $newLineType = ""): void
    {
        self::recursiveFileActionHook(
            $dir,
            [Util::class, 'recursiveUnifyTextFormat'],
            $toEncoding,
            $newLineType
        );

        chdir($dir);
        $textFiles = self::globOnlyFiles();
        foreach ($textFiles as $file) {
            $content = file_get_contents($file);
            self::changeEncodingAndNewLineType($content, $toEncoding, $newLineType);
            file_put_contents($file, $content);
        }
    }

    /**
     * @throws AppException
     */
    public static function changeEncodingAndNewLineType(string &$content, string $toEncoding = 'UTF-8', string $newLineType = "\n"): void
    {
        self::convertEncoding($content); // 先偷懒，全部转成 utf-8 之后再转一次
        if ($toEncoding && $toEncoding != 'UTF-8') {
            self::convertEncoding($content, $toEncoding, 'UTF-8');
        }

        if ($newLineType == "\r\n") {
            $content = str_replace(["\r\n", "\n"], ["\n", "\r\n"], $content);
        } else {
            $content = str_replace(["\r\n", "\r"], "\n", $content);
        }

        if ($toEncoding == 'UTF-8') { // 这里的写法仅支持 UTF-8 编码
            // 移除 BOM 头和其他不可见字符，但可能有如下影响：
            // 例子1: 在一个需要精确排版的系统中，\x200A (Hair Space) 可能被用来微调字间距。
            // 例子2: 在处理阿拉伯语或希伯来语等多向文本时，\x200E 和 \x200F 是正确显示混合文本所必需的。粗暴删除会导致显示错乱。
            // 例子3: \x200D (零宽连接符) 是组合复杂 emoji 的关键。删除它会将组合 emoji "拆散" 成单个的 emoji
            $result = preg_replace(
                // "/[\x{FEFF}\x{2028}-\x{202F}\x{205F}-\x{206F}\x{007F}]/u", // 暂时保留了 \x200A \x200D \x200E \x200F
                "/[\x{FEFF}\x{200B}\x{200C}\x{2028}-\x{202F}\x{205F}-\x{206F}\x{007F}]/u",
                "",
                $content
            );

            if ($result != null) { // 转换出错时保持原样
                $content = $result;
            }
        }
    }

    /**
     * @throws AppException
     */
    public static function unifyAllBooksFormat(): void
    {
        Show::opStart('统一文件编码和换行符');
        echo PHP_EOL;
        Show::writeWithNL('（文件较大或较多时会消耗较多时间）');
        Util::recursiveUnifyTextFormat(BOOK_DIR);
        Show::opEnd();
    }

    public static function jsonEncode(mixed $value, int $flags = JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT): string
    {
        return json_encode($value, $flags);
    }

    /**
     * 如果目录名中含有 . 后缀，原有 glob 函数会误判为文件
     *
     * @param string $pattern
     * @param int $flags
     * @return array
     */
    public static function globOnlyFiles(string $pattern = '*.txt', int $flags = GLOB_BRACE): array
    {
        return array_filter(glob($pattern, $flags), 'is_file');
    }

    public static function bytesToReadableSize(int $fileBytes, int $precision = 2): string
    {
        if ($fileBytes <= 0) {
            return '0 B';
        }

        $units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
        $i = 0;

        while ($fileBytes >= 1024 && $i < count($units) - 1) {
            $fileBytes /= 1024;
            $i++;
        }

        return sprintf("%.{$precision}f %s", $fileBytes, $units[$i]);
    }

    public static function recursiveCopy(string $entryDir, string $destDir, string $ext = ''): void
    {
        if ($handle = opendir($entryDir)) {
            while (($file = readdir($handle)) !== false) {
                if (!is_dir($destDir)) {
                    mkdir($destDir);
                }

                if (($file == '.') || ($file == '..')) {
                    continue;
                }

                if (is_dir($entryDir . '/' . $file)) {
                    self::recursiveCopy($entryDir . '/' . $file, $destDir . '/' . $file, $ext);
                } else if (is_file($entryDir . '/' . $file)) {
                    if (file_exists($destDir . '/' . $file)) {
                        // 不重复覆盖备份文件
                        continue;
                    }

                    // 某些情况下只复制指定后缀的文件
                    if ($ext && self::getFileExt($file) != $ext) {
                        continue;
                    }

                    copy($entryDir . '/' . $file, $destDir . '/' . $file);
                }
            }
            closedir($handle);
        }
    }

    public static function recursiveDelete(string $dir, bool $rmRootDir = true, int $depth = 0): void
    {
        if ($depth == 0 && !is_dir($dir)) {
            mkdir($dir, 0777, true);
        }

        if ($handle = opendir($dir)) {
            while (($file = readdir($handle)) !== false) {
                if (($file == '.') || ($file == '..')) {
                    continue;
                }
                if (is_dir($dir . '/' . $file)) {
                    self::recursiveDelete($dir . '/' . $file, $rmRootDir, $depth + 1);
                } else if (is_file($dir . '/' . $file)) {
                    unlink($dir . '/' . $file);
                }
            }
            closedir($handle);

            if ($rmRootDir) {
                rmdir($dir); // 如果要删根目录，那就都删
            } else if ($depth > 0) {
                rmdir($dir); // 如果不删根目录，那就只删深度大于 0 的（即子目录）
            }
        }
    }

    public static function getTimeStr(int|string $time = '', bool $withDate = false): string
    {
        $timestamp = $time ?: time();
        $timeStr = date('H:i:s', $timestamp);
        $withDate && $timeStr = date('Y-m-d', $timestamp) . " {$timeStr}";

        return $timeStr;
    }

    public static function getDirSize(string $directory): int
    {
        $size = 0;
        $files = glob($directory . '/*');
        foreach ($files as $path) {
            is_file($path) && $size += filesize($path);
            is_dir($path) && $size += self::getDirSize($path);
        }

        return $size;
    }

    public static function usleepSeconds(int|float $seconds): void
    {
        usleep($seconds * 1000 * 1000);
    }

    public static function commandExists(string $cmd): bool
    {
        $ret = false;
        if (stripos(PHP_OS, 'linux') !== false || stripos(PHP_OS, 'Darwin') !== false) {
            $ret = shell_exec(sprintf('which %s', escapeshellarg($cmd)));
        } else if (stripos(PHP_OS, 'win') !== false) {
            $ret = shell_exec(sprintf('where %s', escapeshellarg($cmd)));
        }

        return !empty($ret);
    }

    /**
     * @throws AppException
     */
    public static function generatePatch($originalFile, $updateFile, $patch)
    {
        if (!file_exists($originalFile) || !file_exists($updateFile)) {
            throw new AppException("originalFile: {$originalFile} updateFile: {$updateFile} 路径有误");
        }

        is_file($patch) && unlink($patch);

        $diffCmd = self::commandExists('diff') ? 'diff' : SCRIPT_DIR . '/tools/diff.exe';
        $diffCmd = escapeshellarg($diffCmd);
        exec("{$diffCmd} -u \"{$originalFile}\" \"{$updateFile}\" > \"{$patch}\"");

        if (!file_exists($patch)) {
            throw new AppException("patch: {$patch} 生成 patch 失败");
        }
    }

    /**
     * @throws AppException
     */
    public static function applyPatch($patch, $file)
    {
        if (!file_exists($patch) || !file_exists($file)) {
            throw new AppException("patch: {$patch} file: {$file} 路径有误");
        }

        $patchCmd = self::commandExists('patch') ? 'patch' : SCRIPT_DIR . '/tools/patch.exe';
        $patchCmd = escapeshellarg($patchCmd);
        exec("{$patchCmd} \"{$file}\" \"{$patch}\"");
    }

    /**
     * 截取两个字符串中，从第一个正向差异字符到第一个反向差异字符之间的部分
     *
     * @param string $str1
     * @param string $str2
     * @param int $contextLen 额外截取的上下文字符串长度
     * @return array 无差异时返回空数组，有差异时返回包含 str1 和 str2 的各自截取部分的数组
     */
    public static function extractStrDiff(string $str1, string $str2, int $contextLen = 0): array
    {
        if ($str1 === $str2) {
            return [];
        }

        // 转换为字符数组
        $chars1 = mb_str_split($str1);
        $chars2 = mb_str_split($str2);
        $len1 = count($chars1);
        $len2 = count($chars2);
        $minLen = min($len1, $len2);

        // 正向查找：第一个不同字符的位置
        $diffStart = $minLen; // 默认值：一个字符串是另一个的前缀
        for ($i = 0; $i < $minLen; $i++) {
            if ($chars1[$i] !== $chars2[$i]) {
                $diffStart = $i;
                break;
            }
        }

        // 反向查找：从尾部开始找第一个不同的字符
        $diffEnd1 = $len1 - 1;
        $diffEnd2 = $len2 - 1;
        while ($diffEnd1 >= $diffStart && $diffEnd2 >= $diffStart) {
            if ($chars1[$diffEnd1] !== $chars2[$diffEnd2]) {
                break;
            }
            $diffEnd1--;
            $diffEnd2--;
        }

        // 确保差异结束位置不小于差异开始位置的前一个位置
        $diffEnd1 = max($diffEnd1, $diffStart - 1);
        $diffEnd2 = max($diffEnd2, $diffStart - 1);

        // 计算需要提取的范围（包含上下文）
        $extractStart1 = max(0, $diffStart - $contextLen);
        $extractEnd1 = min($len1 - 1, $diffEnd1 + $contextLen);

        $extractStart2 = max(0, $diffStart - $contextLen);
        $extractEnd2 = min($len2 - 1, $diffEnd2 + $contextLen);

        return [
            mb_substr($str1, $extractStart1, $extractEnd1 - $extractStart1 + 1),
            mb_substr($str2, $extractStart2, $extractEnd2 - $extractStart2 + 1)
        ];
    }

    /**
     * 支持 unicode 字符的 trim 函数
     * 原有的 trim 函数在移除中文字符时会产生乱码
     *
     * @param string $string
     * @param string $charsToTrim
     * @param string $direction 可选值：both left right
     * @return string
     */
    public static function trimUnicodeChars(string $string, string $charsToTrim = " \n\r\t\v\0", string $direction = "both")
    {
        // 如果字符串为空，或者没有要过滤的字符，直接返回
        if ($string === '' || $charsToTrim === '') {
            return $string;
        }

        // 1. 转义过滤字符
        // 第二个参数 '/' 确保了如果 $charsToTrim 包含定界符，会被转义成 \/
        // preg_quote 也会转义 [ ] - 等在正则集合中有特殊意义的字符
        $escapedChars = preg_quote($charsToTrim, '/');

        // 2. 使用 match (PHP 8.0+) 匹配方向
        $pattern = match ($direction) {
            'left'  => '/^[' . $escapedChars . ']+/u',
            'right' => '/[' . $escapedChars . ']+$/u',
            'both'  => '/^[' . $escapedChars . ']+|[' . $escapedChars . ']+$/u',
            default => null,
        };

        if ($pattern === null) {
            return $string;
        }

        return preg_replace($pattern, '', $string);
    }

    public static function ltrimUnicodeChars(string $string, string $charsToTrim = " \n\r\t\v\0")
    {
        return self::trimUnicodeChars($string, $charsToTrim, 'left');
    }

    public static function rtrimUnicodeChars(string $string, string $charsToTrim = " \n\r\t\v\0")
    {
        return self::trimUnicodeChars($string, $charsToTrim, 'right');
    }

    public static function getArgvByIndex($index, $defaultValue = "")
    {
        if (isset($_SERVER['argv'])) {
            return $_SERVER['argv'][$index] ?? $defaultValue;
        }

        return $defaultValue;
    }

    public static function isFromGUI(): bool
    {
        if (isset($_SERVER['argv'])) {
            foreach ($_SERVER['argv'] as $argv) {
                if ($argv == 'from-gui') {
                    return true;
                }
            }
        }

        return false;
    }

    /**
     * 移除文件的扩展后缀
     * [可选] 同时移除【EPUB 合并文件】前缀
     *
     * @param string $filename
     * @param bool $removeEpubMergePrefix
     * @return string
     */
    public static function getFilename(string $filename, $removeEpubMergePrefix = false): string
    {
        $filename = pathinfo($filename, PATHINFO_FILENAME);
        if ($removeEpubMergePrefix) {
            $filename = self::removeEpubMergePrefix($filename);
        }

        return $filename;
    }

    /**
     * 只移除【EPUB 合并文件】前缀，不移除扩展名
     *
     * @param string $filename
     * @return string
     */
    public static function removeEpubMergePrefix(string $filename): string
    {
        return str_replace(EPUB_MERGE_PREFIX, '', $filename);
    }

    public static function getFileExt(string $filename, bool $strToLower = true): string
    {
        $fileExt = pathinfo($filename, PATHINFO_EXTENSION);
        $strToLower && $fileExt = mb_strtolower($fileExt);

        return $fileExt;
    }

    public static function isHtmlFile(string $filename): bool
    {
        $fileExt = self::getFileExt($filename);
        if (str_contains($fileExt, 'htm') || str_contains($filename, EPUB_MERGE_PREFIX)) {
            return true;
        }

        return false;
    }

    public static function isTxtFile(string $filename): bool
    {
        $fileExt = self::getFileExt($filename);
        if ($fileExt == 'txt' && !str_contains($filename, EPUB_MERGE_PREFIX)) {
            return true;
        }

        return false;
    }

    public static function detectNewlineType(string $content): string
    {
        if (strpos($content, "\r\n") !== false) {
            return "\r\n";
        }

        if (strpos($content, "\n") !== false) {
            return "\n";
        }

        if (strpos($content, "\r") !== false) {
            return "\r";
        }

        return "\n";
    }

    /**
     * 安全执行外部命令的函数，支持多级子命令、管道和重定向
     *
     * @param string          $command     命令路径
     * @param array           $subcommands 子命令数组（支持多级）
     * @param array           $options     选项数组
     * @param array           $arguments   参数数组
     * @param array           $pipes       管道操作数组（每个元素是一个命令）
     * @param array           $redirects   重定向操作数组（例如 ['>' => 'output.txt']）
     * @return array          包含输出和返回状态的数组
     */
    public static function safeExec(
        string $command,
        array $subcommands = [],
        array $options = [],
        array $arguments = [],
        array $pipes = [],
        array $redirects = []
    ): array {
        // 转义命令路径（可能包含空格）
        $escapedCommand = escapeshellarg($command);

        // 转义子命令（支持多级子命令）
        $escapedSubcommands = array_map('escapeshellarg', $subcommands);

        // 处理选项
        $escapedOptions = [];
        foreach ($options as $key => $value) {
            if (is_int($key)) {
                // 短选项或长选项（无值）
                $escapedOptions[] = escapeshellarg($value);
            } else {
                // 带值的选项
                if (strpos($key, '--') === 0) {
                    // 长选项（--option=value）
                    $escapedOptions[] = escapeshellarg($key . '=' . $value);
                } else {
                    // 短选项（-o value）
                    $escapedOptions[] = escapeshellarg($key);
                    $escapedOptions[] = escapeshellarg($value);
                }
            }
        }

        // 转义参数
        $escapedArguments = array_map('escapeshellarg', $arguments);

        // 拼接基本命令
        $fullCommand = $escapedCommand . ' ' .
            implode(' ', $escapedSubcommands) . ' ' .
            implode(' ', $escapedOptions) . ' ' .
            implode(' ', $escapedArguments);

        // 处理管道
        if (!empty($pipes)) {
            $pipedCommands = [];
            foreach ($pipes as $pipeCommand) {
                $pipedCommands[] = is_array($pipeCommand) ? implode(' ', array_map('escapeshellarg', $pipeCommand)) : $pipeCommand;
            }
            $fullCommand .= ' | ' . implode(' | ', $pipedCommands);
        }

        // 处理重定向
        foreach ($redirects as $operator => $file) {
            $fullCommand .= ' ' . $operator . ' ' . escapeshellarg($file);
        }

        // 执行命令
        exec($fullCommand, $output, $returnVar);

        // 返回输出和状态码
        return [
            'output'     => $output,
            'return_var' => $returnVar,
        ];
    }

    /**
     * @param string $cmd
     * @param bool $escapeCmd 如果为 false，就要在外面自己处理好 args 前的部分，包括可能的各种选项和子命令
     * @param mixed $args
     * @return array{0:array, 1:int}
     */
    public static function formatArgsAndExec(string $cmd, bool $escapeCmd, ...$args)
    {
        $escapeCmd && $cmd = escapeshellarg($cmd);

        foreach ($args as $arg) {
            $cmd .= ' ' . escapeshellarg($arg);
        }

        exec($cmd, $output, $resultCode);

        return [$output, $resultCode];
    }

    public static function multiStrContains($haystack, $needles)
    {
        $needles = (array)$needles;
        foreach ($needles as $needle) {
            if (str_contains($haystack, $needle)) {
                return true;
            }
        }

        return false;
    }

    public static function multiStrStartsWith($haystack, $needles)
    {
        $needles = (array)$needles;
        foreach ($needles as $needle) {
            if (str_starts_with($haystack, $needle)) {
                return true;
            }
        }

        return false;
    }

    public static function isDirEmpty($dir)
    {
        if (!is_dir($dir)) {
            return true;
        }

        return (count(glob($dir . '/*')) === 0);
    }

    public static function getArrStrWithIndex($arr)
    {
        $arrKeys = array_map(function ($v) {
            return "索引-{$v}";
        }, range(0, count($arr) - 1));

        return Util::jsonEncode(array_combine($arrKeys, $arr));
    }

    public static function computeUniqueChars(string $method = 'merge', string ...$strings): string
    {
        if (empty($strings)) {
            return "";
        }

        $charArrays = array_map('mb_str_split', $strings);

        $result = [];
        if ($method == 'merge') {
            $result = array_merge(...$charArrays);
        } else if ($method == 'intersect') {
            $result = array_intersect(...$charArrays);
        } else if ($method == 'diff') {
            $result = array_diff(...$charArrays);
        }

        $result = array_values(array_unique($result));
        // sort($result);

        return str_replace("\n", '', implode($result));
    }

    public static function mergeUniqueChars(string ...$strings): string
    {
        return self::computeUniqueChars('merge', ...$strings);
    }

    public static function intersectUniqueChars(string ...$strings): string
    {
        return self::computeUniqueChars('intersect', ...$strings);
    }

    public static function diffUniqueChars(string ...$strings): string
    {
        return self::computeUniqueChars('diff', ...$strings);
    }

    /**
     * @param array $words
     * @param bool $sortByPrefix true-用于扩展标点（前缀） false-用于扩展字符串
     * @param bool $print
     * @param int $prefixLen
     * @return array
     */
    public static function sortWordsWithPrefix(array $words, $sortByPrefix = false, $print = true, $prefixLen = 1): array
    {
        usort($words, function ($a, $b) use ($sortByPrefix, $prefixLen) {
            if ($sortByPrefix) {
                // 按指定前缀排序（如标点）
                // 适用于为【指定前缀】扩展新的类型
                $aPrefix = mb_substr($a['after'], 0, $prefixLen);
                $bPrefix = mb_substr($b['after'], 0, $prefixLen);
                $wordSortRef = self::WORD_SORT_REF;
                if (in_array($aPrefix, $wordSortRef) && in_array($bPrefix, $wordSortRef)) {
                    // 如果两个字符串都以标点符号开头，则根据标点符号的优先级进行排序
                    $aPriority = array_search($aPrefix, $wordSortRef);
                    $bPriority = array_search($bPrefix, $wordSortRef);
                    return $aPriority <=> $bPriority;
                } else if (in_array($aPrefix, $wordSortRef)) {
                    // 如果只有一个字符串以标点符号开头，则将其放在前面
                    return -1;
                } else if (in_array($bPrefix, $wordSortRef)) {
                    // 如果只有一个字符串以标点符号开头，则将其放在前面
                    return 1;
                } else {
                    // 否则直接按原前缀排序
                    return $a['after'] <=> $b['after'];
                }
            } else {
                // 忽略指定前缀，按字符串本身排序
                // 适用于为【指定前缀】后面的【字符串本身】扩展新的类型
                //
                // 以下的 substr 执行之后，相同的字符串会被排列到一起，相当于分组
                // 如果不用 substr 移除共同的前缀或后缀，每个字符串都不相同，顺序会乱掉
                // 因此应该先【扩展标点】，再将排序后的结果数组作为【扩展字符串】时的输入
                // 才能按照输入顺序重新分组排列
                return mb_substr($b['after'], $prefixLen) <=> mb_substr($a['after'], $prefixLen);
            }
        });

        self::formatWordsAfterSort($words, $print);

        return $words;
    }

    /**
     * @param array $words
     * @param bool $sortBySuffix true-用于扩展标点（后缀） false-用于扩展字符串
     * @param bool $print
     * @param int $suffixLen
     * @return void
     */
    public static function sortWordsWithSuffix(array $words, $sortBySuffix = false, $print = true, $suffixLen = 1): void
    {
        usort($words, function ($a, $b) use ($sortBySuffix, $suffixLen) {
            if ($sortBySuffix) {
                // 按指定后缀排序（如标点）
                // 适用于为【指定后缀】扩展新的类型
                $aSuffix = mb_substr($a['after'], -$suffixLen);
                $bSuffix = mb_substr($b['after'], -$suffixLen);
                $wordSortRef = self::WORD_SORT_REF;
                if (in_array($aSuffix, $wordSortRef) && in_array($bSuffix, $wordSortRef)) {
                    // 如果两个字符串都以标点符号结尾，则根据标点符号的优先级进行排序
                    $aPriority = array_search($aSuffix, $wordSortRef);
                    $bPriority = array_search($bSuffix, $wordSortRef);
                    return $aPriority <=> $bPriority;
                } else if (in_array($aSuffix, $wordSortRef)) {
                    // 如果只有一个字符串以标点符号结尾，则将其放在前面
                    return -1;
                } else if (in_array($bSuffix, $wordSortRef)) {
                    // 如果只有一个字符串以标点符号结尾，则将其放在前面
                    return 1;
                } else {
                    // 否则直接按原后缀排序
                    return mb_substr($b['after'], -$suffixLen) <=> mb_substr($a['after'], -$suffixLen);
                }
            } else {
                // 忽略指定后缀，按字符串本身排序
                // 适用于为【指定后缀】前面的【字符串本身】扩展新的类型
                //
                // 以下的 substr 执行之后，相同的字符串会被排列到一起，相当于分组
                // 如果不用 substr 移除共同的前缀或后缀，每个字符串都不相同，顺序会乱掉
                // 因此应该先【扩展标点】，再将排序后的结果数组作为【扩展字符串】时的输入
                // 才能按照输入顺序重新分组排列
                return mb_substr($a['after'], 0, mb_strlen($a['after']) - 1)
                    <=>
                    mb_substr($b['after'], 0, mb_strlen($b['after']) - 1);
            }
        });

        self::formatWordsAfterSort($words, $print);
    }

    protected static function formatWordsAfterSort(&$words, $print)
    {
        usort($words, function ($a, $b) {
            return strlen($a['after']) <=> strlen($b['after']);
        });

        if ($print) {
            echo self::getWordsPrintStr($words);
        }
    }

    public static function getWordsPrintStr($words, $extraInfo = '', $multiLine = false)
    {
        isset($words['before']) && $words = [$words];

        $result = '';
        foreach ($words as $word) {
            if ($multiLine) {
                // ========== 多行模式 ==========
                // 使用数组收集元素，自动处理逗号和换行
                $elements = [];

                if (is_array($word['before'])) {
                    $elements[] = "'before' => " . '["' . implode('", "', $word['before']) . '"]';
                } else {
                    $elements[] = "'before' => \"{$word['before']}\"";
                }

                // 为了美观，利用空格将 => 对齐
                $elements[] = "'after'  => \"{$word['after']}\"";

                if (isset($word['mark'])) {
                    $elements[] = "'mark'   => \"{$word['mark']}\"";
                }

                if (isset($word['id'])) {
                    $elements[] = "'id'     => \"{$word['id']}\"";
                }

                // 拼装：元素之间用 "逗号+换行+缩进" 连接
                $inner = implode(",\n        ", $elements);
                $extra = $extraInfo ? " // {$extraInfo}" : "";

                $result .= "    [\n        {$inner}\n    ],{$extra}\n";
            } else {
                // ========== 单行模式 ==========
                if (is_array($word['before'])) {
                    $beforeStr = "'before' => " . '["' . implode('", "', $word['before']) . '"]';
                } else {
                    $beforeStr = "'before' => \"{$word['before']}\"";
                }

                $afterStr = ", 'after' => \"{$word['after']}\"";
                $markStr  = isset($word['mark']) ? ", 'mark' => \"{$word['mark']}\"" : "";
                $idStr    = isset($word['id'])   ? ", 'id' => \"{$word['id']}\""   : "";

                $result .= "    [{$beforeStr}{$afterStr}{$markStr}{$idStr}],"
                    . ($extraInfo ? " // {$extraInfo}" : "") . "\n";
            }
        }

        return $result;
    }

    public static function strtrWithWordsMap(string &$content, array $wordsMap, bool $shouldFlattern = false): string
    {
        $shouldFlattern && $wordsMap = Map::flattenMaps($wordsMap);
        $wordsMap = array_combine(
            array_column($wordsMap, 'before'),
            array_column($wordsMap, 'after'),
        );
        $content = strtr($content, $wordsMap);

        return $content;
    }

    /**
     * @param array $array
     * @param bool $onlyReturnKeys true-只查找值；false-把 count 次数同时返回
     * @return array
     */
    public static function findDuplicatesInArray(array $array, bool $onlyReturnKeys = true): array
    {
        $count = array_count_values($array);
        $duplicates = array_filter($count, fn($v) => $v > 1);

        if ($onlyReturnKeys) {
            return array_keys($duplicates);
        } else {
            return $duplicates;
        }
    }

    /**
     * 多条正则批量替换
     *
     * @param array $patterns 规则参考 doRegexReplace() 中的 pattern 参数
     * @param string $content
     * @param string $modifiers
     * - 描述符，参考：https://www.php.net/manual/zh/reference.pcre.pattern.modifiers.php
     * - 默认加上了 x 描述符，会忽略表达式中的所有换行和空格。
     * 如果确实要用到，必须把空格和换行放到 [] 中，或者在表达式配置中调整描述符，去掉 x，否则会出错
     * @return void
     */
    public static function multiRegexReplace(array $patterns, string &$content, string $modifiers = 'umx'): void
    {
        foreach ($patterns as $pattern) {
            self::doRegexReplace($pattern, $content, $modifiers);
        }
    }

    /**
     * 正则替换，支持直接执行 pattern 的 replace 字段中设置的替换回调函数
     *
     * @param array $pattern
     * - 必须至少含有 search 和 replace 两个字段
     * - search 中的斜杠【/】必须转义为【\/】
     * - replace 可直接填写替换表达式，或设置回调函数
     * - 可额外在每条正则中使用 modifiers 字段来指定修饰符，优先级高于传入的 $modifiers 参数
     * @param string $content
     * @param string $modifiers
     * - 描述符，参考：https://www.php.net/manual/zh/reference.pcre.pattern.modifiers.php
     * - 默认加上了 x 描述符，会忽略表达式中的所有换行和空格。
     * 如果确实要用到，必须把空格和换行放到 [] 中，或者在表达式配置中调整描述符，去掉 x，否则会出错
     * @return void
     * @throws AppException
     */
    public static function doRegexReplace(array $pattern, string &$content, $modifiers = 'umx')
    {
        if (!isset($pattern['search']) || !isset($pattern['replace'])) {
            throw new AppException('正则规则中必须至少含有 search 和 replace 字段');
        }

        // 也可以在每条表达式中单独设置描述符
        $modifiers = $pattern['modifiers'] ?? $modifiers;

        try {
            if (is_callable($pattern['replace'])) {
                $content = preg_replace_callback(
                    "/{$pattern['search']}/{$modifiers}",
                    $pattern['replace'],
                    $content
                );
            } else {
                $content = preg_replace(
                    "/{$pattern['search']}/{$modifiers}",
                    $pattern['replace'],
                    $content
                );
            }
        } catch (Exception $e) {
            var_dump($pattern);
            Show::warning('正则表达式有误：' . $e->getMessage() . "\n此条未执行，请修复后重试");
        }

        if ($content === null) {
            $errMsg = preg_last_error_msg();
            $errPattern = self::jsonEncode($pattern);
            throw new AppException("正则替换失败，文本内容被错误清除：\n{$errMsg}\n{$errPattern}");
        }
    }

    public static function countTextChars(string $file, string $text, bool $countPunctuations = true, bool $readableCount = true): string|int
    {
        if (self::isHtmlFile($file)) {
            self::extractTextFromHtml($text);
        }

        $text = preg_replace("/^[ 　   \t\f]+/um", "", $text);
        $text = preg_replace("/[ 　   \t\f]+$/um", "", $text);
        $text = str_replace("\n", "", $text);
        $text = str_replace(self::HTML_CHAPTER_MARK, "", $text);

        if (!$countPunctuations) { // 不计算空格和标点
            $text = preg_replace(
                "/[\s&%#￥\$*\/，。？！…；、～~\-—－：:（）“”‘’'\"《》【】〖〗「」『』\[\]·]/u",
                "",
                $text,
            );
        }

        $count = mb_strlen($text);
        if ($readableCount) {
            if ($count > 1000 && $count < 10000) {
                $count = sprintf('%.1f', $count / 1000) . ' 千字';
            } else if ($count >= 10000 && $count < 10000 * 10000) {
                $count = sprintf('%.2f', $count / 10000) . ' 万字';
            } else {
                $count .= ' 字';
            }
        }

        return $count;
    }

    public static function extractTextFromHtml(string &$content): void
    {
        // 处理多余的样式、标题等
        $content = preg_replace("/<title.*?\/title>/usi", "", $content);
        $content = preg_replace("/<style.*?\/style>/usi", "", $content);
        $content = preg_replace('/<div class="head1">.*?<div class="head".*?>.*?<\/div>.*?<\/div>.*?<p class="head">.*?<\/p>/usi', "", $content); // 样式3
        $content = preg_replace("/<p class=\"v-head\">(.*?)<\/p>/um", "", $content); // 样式5
        $content = preg_replace("/<p class=\".*?duokan-image-maintitle.*?\">(.*?)<\/p>/um", "", $content); // 图注
        $content = preg_replace("/<p class=\".*?duokan-image-subtitle.*?\">(.*?)<\/p>/um", "", $content); // 图注
        $content = preg_replace("/<span class=\"review-count\">(.*?)<\/span>/um", "", $content);

        // 处理注释，注标序号为页内计数
        $content = preg_replace("/note-num=\"(.*?)\".*?>/ui", "note-num=\"$1\">（注$1）", $content);
        $content = preg_replace("/note-content-num=\"(.*?)\".*?>(.*)<\/a>/ui", "href=\"#noteref_$1\">（注$1：$2）", $content);
        // 下面的是全局计数
        // $content = preg_replace("/href=\"#note_(.*?)\".*? *>/i", "href=\"#note_$1\">（注$1）", $content);
        // $content = preg_replace("/href=\"#noteref_(.*?)\".*? *>(.*)<\/a>/i", "href=\"#noteref_$1\">（注$1：$2）", $content);

        // 处理分隔符和其他需要手动调整的符号
        $content = strtr(
            $content,
            array_merge(
                ['</h1><p' => "</h1>\n<p", '</h2><p' => "</h2>\n<p", '</h3><p' => "</h3>\n<p",],
                ['</h4><p' => "</h4>\n<p", '</h5><p' => "</h5>\n<p", '</h6><p' => "</h6>\n<p", '</p><p' => "</p>\n<p",],
                ['</h1> <p' => "</h1>\n<p", '</h2> <p' => "</h2>\n<p", '</h3> <p' => "</h3>\n<p",],
                ['</h4> <p' => "</h4>\n<p", '</h5> <p' => "</h5>\n<p", '</h6> <p' => "</h6>\n<p", '</p> <p' => "</p>\n<p",],
                ['</h1><div' => "</h1>\n<div", '</h2><div' => "</h2>\n<div", '</h3><div' => "</h3>\n<div",],
                ['</h4><div' => "</h4>\n<div", '</h5><div' => "</h5>\n<div", '</h6><div' => "</h6>\n<div", '</div><div' => "</div>\n<div",],
                ['</h1> <div' => "</h1>\n<div", '</h2> <div' => "</h2>\n<div", '</h3> <div' => "</h3>\n<div",],
                ['</h4> <div' => "</h4>\n<div", '</h5> <div' => "</h5>\n<div", '</h6> <div' => "</h6>\n<div", '</div> <div' => "</div>\n<div",],
                [
                    '<p class="brline"><img src="../Images/transpacep.png"/>　</p>' => '※※※',
                    '<p class="brline"><img alt="" src="../Images/transpacep.png"/>　</p>' => '※※※',
                    '<p class="brline">※ ※ ※</p>' => '※※※',
                    '<p class="break">……</p>' => '※※※',
                    '<p><br/></p>' => '※※※',
                    '<p></p>' => '※※※',
                    '<p>&#160;</p>' => '',
                    '&#160;' => ' ',
                    '<br class="note-br"/>' => "\n", // 弹注中的 br 多加一个 class 用以区分
                    '<br/> ' => " ", // 只有标题分行使用 br 标签，其他地方尽量都不用，这样就可以把 br 统一换成空格
                    '<br/>' => " ",
                ],
            ),
        );

        // 标题强制加标记，格式化排版时再移除
        // 查找所有顶格标题行：^[^　]
        $content = preg_replace("/<h(.*?)title=['\"](.*?)['\"].*>\s*<\/h/ui", "<h$1>$2</h", $content); // 无内容时取 title
        $content = preg_replace("/<h(.*?)>(.*?)<\/h/ui", "<h$1>" . self::HTML_CHAPTER_MARK . "$2</h", $content);

        // 恢复某些引言标记。改用单独的方法，可以正确识别和处理嵌套标签
        $content = self::processHtmlQuotes($content);

        // 使用自带函数移除其他所有标签
        $content = strip_tags($content);

        // 处理 html 实体
        // 需要放到最后面，不然那个 <> 会误伤标签，替换完之后可以用 & 再搜一下有没有漏转的
        $content = html_entity_decode($content);
        $content = preg_replace("/^封面$/um", "", $content);
    }

    protected static function processHtmlQuotes($content)
    {
        if (empty($content)) {
            return '';
        }

        if (!self::multiStrContains($content, ['class="quote'])) {
            return $content;
        }

        // 移除所有 XML 和 DOCTYPE 声明，以及外层的 html head body 等，只保留主体
        $content = preg_replace('/<\?xml.*?\?>/si', '', $content);
        $content = preg_replace('/<!DOCTYPE.*?>/si', '', $content);
        $content = preg_replace('/<head>.*?<\/head>/si', '', $content);
        $content = preg_replace('/<html[^>]*>/si', '', $content);
        $content = preg_replace('/<\/html>/si', '', $content);
        $content = preg_replace('/<body[^>]*>/si', '', $content);
        $content = preg_replace('/<\/body>/si', '', $content);
        $content = preg_replace('/<svg.*?<\/svg>/si', '', $content);
        $content = preg_replace('/id="[^"]*?"/si', "", $content); // 避免 ID 冲突导致解析报错
        $allowedTags = array_merge( // 只保留 DOMDocument 支持的和文本相关的标签，其他全部移除
            ['p', 'span', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'],
        );
        $content = strip_tags($content, '<' . implode('><', $allowedTags) . '>');

        // 预处理，整理 div 的首尾分行
        $content = preg_replace("/<div class=\"quote([^<>]*?)\">\s*?<p.*?>/usi", "<div class=\"quote$1\"><p>", $content);
        $content = preg_replace("/<\/p>(\n\s*)+<\/div>/si", "</p></div>", $content);

        $processedHtml = '';
        try {
            $dom = new DOMDocument();
            // 为了稳定处理拼接的 HTML 片段，将其包裹在一个根 <div> 中
            $wrappedContent = '<div id="root-wrapper">' . $content . '</div>';
            // 抑制格式错误的 HTML 警告，并包装内容以确保正确解析
            @$dom->loadHTML('<?xml encoding="utf-8" ?>' . $wrappedContent, LIBXML_HTML_NOIMPLIED | LIBXML_HTML_NODEFDTD);
            $xpath = new DOMXPath($dom);

            $replacements = [
                // XPath 查询 => [前缀, 后缀]
                '//span[@class="quote"]' => ['〖', '〗'],
                '//span[@class="quote-3"]' => ['〔', '〕'],
                '//div[@class="quote"]' => ['〖', '〗'],
                '//div[@class="quote-3"]' => ['〔', '〕'],
                '//div[@class="quote-left"]' => ['【【', '】】'],
                '//div[@class="quote-right"]' => ['〖〖', '〗〗'],
                '//div[@class="quote-center"]' => ['〔〔', '〕〕'],
                '//*[self::p or self::h4][@class="subtitle"]' => ['【', '】'],
                '//*[self::p or self::h4][contains(@class, "subtitle-top")]' => ['【', '】'],
                // quote-2 不用处理，原样保留，主要是引号名词和【】括住的内容
            ];

            // 循环直到没有更多的替换可以进行。这样可以从内到外正确处理嵌套标签
            $madeChange = true;
            while ($madeChange) {
                $madeChange = false;
                foreach ($replacements as $query => $markers) {
                    $nodes = $xpath->query($query);
                    if ($nodes->length > 0) {
                        $madeChange = true;
                        // 反向处理节点以避免节点替换引起的问题
                        for ($i = $nodes->length - 1; $i >= 0; $i--) {
                            $node = $nodes->item($i);
                            // 获取文本内容，这会移除内部标签
                            $textContent = $node->textContent;
                            // 创建带有相应标记的新文本节点
                            $newNode = $dom->createTextNode($markers[0] . $textContent . $markers[1]);
                            // 用新的文本节点替换原始的 HTML 标签（例如 <span...>）
                            if ($node->parentNode) {
                                $node->parentNode->replaceChild($newNode, $node);
                            }
                        }
                    }
                }
            }

            // 获取处理后的内容
            $body = $xpath->query('//div[@id="root-wrapper"]')->item(0);
            if ($body) {
                foreach ($body->childNodes as $childNode) {
                    $processedHtml .= $dom->saveHTML($childNode);
                }
            }
        } catch (Throwable $e) {
            Show::warnWithNL('引言标记解析有误: ' . $e->getMessage());
            return $content;
        }

        // 清理 saveHTML 的输出
        $processedHtml = trim($processedHtml);

        return $processedHtml;
    }

    /**
     * 将字符串中极特殊的字符（包括部分 Emoji 和生僻字）编码为文本表示形式 [E:U+XXXX]
     * 这个函数不会影响中文、日文等其他语言的常规字符
     *
     * @param string $text 输入字符串
     * @param int $scope 字符范围，0 为处理全部特殊字符，1 为只处理 CJK 扩展区生僻字
     * @return string 编码了生僻字和 Emoji 的文本
     */
    public static function encodeSpecialCharsToText(string $text, int $scope = 0): string
    {
        $specialCharsPattern = '/(';

        // --- CJK 扩展 B 区及以上生僻字范围 ---
        $cjkExtCharsPattern =
            '[\x{20000}-\x{2A6DF}]|' .   // CJK 统一表意文字扩展 B 区
            '[\x{2A700}-\x{2B73F}]|' .   // CJK 统一表意文字扩展 C 区
            '[\x{2B740}-\x{2B81F}]|' .   // CJK 统一表意文字扩展 D 区
            '[\x{2B820}-\x{2CEAF}]|' .   // CJK 统一表意文字扩展 E 区
            '[\x{2CEB0}-\x{2EBEF}]|' .   // CJK 统一表意文字扩展 F 区
            '[\x{30000}-\x{3134F}]|' .   // CJK 统一表意文字扩展 G 区
            '[\x{31350}-\x{323AF}]|' .   // CJK 统一表意文字扩展 H 区
            '[\x{2EBF0}-\x{2EE5F}]|' .   // CJK 统一表意文字扩展 I 区
            '[\x{80000}-\x{8FFFF}]|' .   // 尚未被 Unicode 标准正式分配的区域
            '[\x{E000}-\x{F8FF}]|' .     // PUA (Private Use Area) 基本多文种平面私人使用区
            '[\x{F0000}-\x{FFFFF}]|' .   // PUA (Private Use Area) 补充私人使用区-A
            '[\x{100000}-\x{10FFFF}]|' . // PUA (Private Use Area) 补充私人使用区-B
            '[\x{2F800}-\x{2FA1F}]|';    // CJK 兼容表意文字补充

        // --- Emoji 和其他特殊字符范围 ---
        // 这个正则表达式尝试匹配包括各种各样的 Emoji 在内的特殊字符
        // 包括由零宽度连接符 (ZWJ) 连接的多个码位的序列（例如 👨‍👩‍👧‍👦）
        $emojiPattern =
            '[\x{1F600}-\x{1F64F}]|' .   // 表情符号
            '[\x{1F300}-\x{1F5FF}]|' .   // 杂项符号和象形文字 (包括肤色修饰符)
            '[\x{1F680}-\x{1F6FF}]|' .   // 交通和地图符号
            '(\x{1F700}-\x{1F77F})|' .   // 炼金术符号
            '(\x{1F780}-\x{1F7FF})|' .   // 几何图形扩展
            '(\x{1F800}-\x{1F8FF})|' .   // 补充箭头-C
            '[\x{1F900}-\x{1F9FF}]|' .   // 补充符号和象形文字
            '(\x{1FA00}-\x{1FA6F})|' .   // 国际象棋符号
            '(\x{1FA70}-\x{1FAFF})|' .   // 符号和象形文字扩展-A
            '[\x{1F1E0}-\x{1F1FF}]|' .   // 区域指示符符号 (用于旗帜)
            '(\x{2580}-\x{259F})|' .     // 方块元素 (颜文字常用)
            '(\x{25A0}-\x{25FF})|' .     // 几何图形 (颜文字常用)
            '[\x{2600}-\x{26FF}]|' .     // 杂项符号
            '[\x{2700}-\x{27BF}]|' .     // 装饰符号 (Dingbats)
            '(\x{2B50})|' .              // 星星
            '[\x{FE00}-\x{FE0F}]|' .     // 变体选择器
            '[\x{1F200}-\x{1F251}]|' .   // 带圈的表意文字补充
            '[\x{200D}]|';               // 零宽度连接符 (Zero-Width Joiner)，用于组合 Emoji

        // --- 表达式结尾 ---
        $otherCharsPattern =
            '(\p{So}\x{200D}\p{So})|' .  // 其他零宽度连接符序列
            '(\p{So})' .                 // 其他符号和象形文字
            ')+/u';

        if ($scope == 0) {
            $specialCharsPattern .= $cjkExtCharsPattern . $emojiPattern . $otherCharsPattern;
        } else {
            $specialCharsPattern .= $cjkExtCharsPattern . $otherCharsPattern;
        }

        return preg_replace_callback($specialCharsPattern, function ($matches) {
            $emojiStr = $matches[0];
            $result = '';
            // 将匹配到的字符串安全地分割成单个 Unicode 字符数组
            $chars = preg_split('//u', $emojiStr, -1, PREG_SPLIT_NO_EMPTY);
            foreach ($chars as $char) {
                // 将每个字符转换为其 Unicode 码位表示，例如 "[E:U+1F60A]"
                $result .= sprintf('[E:U+%X]', mb_ord($char, 'UTF-8'));
            }
            return $result;
        }, $text);
    }

    /**
     * 将自定义的文本格式 [E:U+XXXX] 解码回原始 Emoji 和特殊字符
     *
     * @param string $text 编码后的字符串
     * @return string 解码后的原始字符串
     */
    public static function decodeTextToSpecialChars(string $text): string
    {
        // 匹配自定义格式，例如 [E:U+1F468 U+200D U+1F469]
        $customFormatPattern = '/\[E:(U\+[^\]]+)\]/';

        return preg_replace_callback($customFormatPattern, function ($matches) {
            $unicodeCodesStr = $matches[1];
            $unicodeCodes = explode(' ', $unicodeCodesStr);
            $chars = [];

            foreach ($unicodeCodes as $code) {
                if (empty($code)) {
                    continue;
                }
                // 移除 "U+" 前缀并从十六进制转换为十进制
                $dec = hexdec(str_replace('U+', '', $code));
                // 使用 mb_chr 将码点转换为 UTF-8 字符
                $chars[] = mb_chr($dec, 'UTF-8');
            }

            return implode('', $chars);
        }, $text);
    }

    /**
     * 在【中文】和【英文、数字】之间加空格
     *
     * @param string $text
     * @return string
     */
    public static function pangu(string $text): string
    {
        $cjk = '' .
            '\x{2e80}-\x{2eff}' .
            '\x{2f00}-\x{2fdf}' .
            '\x{3040}-\x{309f}' .
            '\x{30a0}-\x{30ff}' .
            '\x{3100}-\x{312f}' .
            '\x{3200}-\x{32ff}' .
            '\x{3400}-\x{4dbf}' .
            '\x{4e00}-\x{9fff}' .
            '\x{f900}-\x{faff}';

        $patterns = [
            'cjk_quote' => [
                '([' . $cjk . '])(["\'])',
                '$1 $2'
            ],

            'quote_cjk' => [
                '(["\'])([' . $cjk . '])',
                '$1 $2'
            ],

            'fix_quote' => [
                '(["\']+)(\s*)(.+?)(\s*)(["\']+)',
                '$1$3$5'
            ],

            'cjk_hash' => [
                '([' . $cjk . '])(#(\S+))',
                '$1 $2'
            ],

            'hash_cjk' => [
                '((\S+)#)([' . $cjk . '])',
                '$1 $3'
            ],

            'cjk_operator_ans' => [
                '([' . $cjk . '])([a-zA-ZΑ-Ωα-ω0-9])([\+\-\*\/=&\\|<>])',
                '$1 $2 $3'
            ],

            'ans_operator_cjk' => [
                '([\+\-\*\/=&\\|<>])([a-zA-ZΑ-Ωα-ω0-9])([' . $cjk . '])',
                '$1 $2 $3'
            ],

            'bracket' => [
                [
                    '([' . $cjk . '])([<\[\{\(]+(.*?)[>\]\}\)]+)([' . $cjk . '])',
                    '$1 $2 $4'
                ],

                [
                    'cjk_bracket' => [
                        '([' . $cjk . '])([<>\[\]\{\}\(\)])',
                        '$1 $2'
                    ],

                    'bracket_cjk' => [
                        '([<>\[\]\{\}\(\)])([' . $cjk . '])',
                        '$1 $2'
                    ]
                ]
            ],

            'fix_bracket' => [
                '([<\[\{\(]+)(\s*)(.+?)(\s*)([>\]\}\)]+)',
                '$1$3$5'
            ],

            'cjk_ans' => [
                '([' . $cjk . '])([a-zA-ZΑ-Ωα-ω0-9`@&%\=\$\^\*\-\+\\/|\\\])',
                '$1 $2'
            ],

            'ans_cjk' => [
                '([a-zA-ZΑ-Ωα-ω0-9`~!%&=;\|\,\.\:\?\$\^\*\-\+\/\\\])([' . $cjk . '])',
                '$1 $2'
            ]
        ];

        foreach ($patterns as $key => $value) {
            if ($key === 'bracket') {
                $old = $text;
                $new = preg_replace('/' . $value[0][0] . '/iu', $value[0][1], $text);
                $text = $new;

                if ($old === $new) {
                    foreach ($value[1] as $val) {
                        $text = preg_replace('/' . $val[0] . '/iu', $val[1], $text);
                    }
                }

                continue;
            }

            $text = preg_replace('/' . $value[0] . '/iu', $value[1], $text);
        }

        return $text;
    }

    /**
     * 文件递归操作统一回调入口
     *
     * @param string $fileDir
     * @param array $callback 回调方法，形如 [$textFixer(对象), "fixBooks"(方法)]
     * @param mixed $args 额外参数，透传
     * @return void
     * @throws AppException
     */
    public static function recursiveFileActionHook(string $fileDir, array $callback = [], mixed ...$args): void
    {
        if (!$handle = opendir($fileDir)) {
            throw new AppException("目录有误：{$fileDir}");
        }

        if (!is_callable($callback)) {
            throw new AppException('未传入回调方法');
        }

        while (($file = readdir($handle)) !== false) {
            if (($file == '.') || ($file == '..')) {
                continue;
            }

            if (in_array($file, EXCLUDE_DIRS)) {
                continue;
            }

            $filePath = $fileDir . '/' . $file;
            if (!is_dir($filePath)) {
                continue;
            }

            // 深度优先递归，此处执行回调
            // 第一个参数固定传目标目录
            $callArgs = array_merge([$filePath], $args);
            call_user_func_array($callback, $callArgs);
        }

        closedir($handle);
    }
}
