<?php

namespace App\Util;

/**
 * 用于分析文本并根据正则表达式提取章节信息
 * 它可以识别章节边界，支持 TXT 的卷章识别及 HTML 的 H1-H6 层级识别
 */
class ChapterAnalyzer
{
    // TXT 备用，目前基本废弃，直接改 src/config/general.php 中的 txtChapterRegex 和 txtVolRegex 即可
    // private const TXT_H1_REGEX = '/^[ 　]*([第][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾.\-—]+[部]?(?:[ 　]+|(?<=[部])[：:]|(?<![.\-—])$)+)/um';
    // private const TXT_H2_REGEX = '/^[ 　]*([第][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾.\-—]+[册集]?(?:[ 　]+|(?<=[册集])[：:]|(?<![.\-—])$)+)/um';
    // private const TXT_H3_REGEX = '/^[ 　]*([第卷][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾.\-—]+[卷]?(?:[ 　]+|(?<=[卷])[：:]|(?<![.\-—])$)+)/um';
    // private const TXT_H4_REGEX = '/^([ 　]*([第][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾至到.\-—]+[篇]?(?:[ 　]+|(?<=[篇])[：:]|(?<![.\-—])$)+))/um';
    // private const TXT_H5_REGEX = '/<^([ 　]*([第章][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾至到.\-—]+[章回话]?(?:[ 　]+|(?<=[章回话])[：:]|(?<![.\-—])$)+)|^[ 　]*◎)/um';
    // private const TXT_H6_REGEX = '/^([ 　]*([第][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾至到.\-—]+[节]?(?:[ 　]+|(?<=[节])[：:]|(?<![.\-—])$)+)|^[ 　]*◎)/um';

    // HTML 层级标题正则
    private const HTML_H_REGEXES = [
        1 => '/<h1([^>]*?)>(.*?)<\/h1>/usi',
        2 => '/<h2([^>]*?)>(.*?)<\/h2>/usi',
        3 => '/<h3([^>]*?)>(.*?)<\/h3>/usi',
        4 => '/<h4([^>]*?)>(.*?)<\/h4>/usi',
        5 => '/<h5([^>]*?)>(.*?)<\/h5>/usi',
        6 => '/<h6([^>]*?)>(.*?)<\/h6>/usi',
    ];

    /**
     * 分析给定的文本以查找章节，并返回它们的详细信息
     *
     * @param string $text 要分析的输入文本
     * @return array 章节数组。每个章节都是一个关联数组，
     *               包含 'start_line'（开始行）、'end_line'（结束行）和 'title'（章节标题）
     *               如果未找到章节，则返回空数组
     */
    public static function analyze(string $text): array
    {
        // [NOTICE] 这里不能进行 changeTextFormat 的操作，否则会影响行号的准确性
        $isHtml = str_contains($text, '</html>');
        $mixedMatches = [];

        if ($isHtml) {
            // 循环匹配 HTML H1 - H6
            foreach (self::HTML_H_REGEXES as $level => $regex) {
                if (preg_match_all($regex, $text, $matches, PREG_OFFSET_CAPTURE)) {
                    foreach ($matches[0] as $index => $fullMatch) {
                        $content = $matches[2][$index][0]; // 获取标签内的 HTML 内容
                        $attributes = $matches[1][$index][0]; // 获取标签内的属性字符串

                        // 如果内容为空（只包含空白字符），尝试从 title 属性中提取
                        if (trim(strip_tags($content)) === '') {
                            if (preg_match('/title=["\'](.*?)["\']/i', $attributes, $attrMatches)) {
                                $content = $attrMatches[1];
                            }
                        }

                        $mixedMatches[] = [
                            'type'    => 'html_h',
                            'level'   => $level,
                            'content' => $content, // 提取捕获组 (.*?) 中的文本
                            'offset'  => $fullMatch[1], // 整个标签的起始字节偏移
                        ];
                    }
                }
            }
        } else {
            // 查找 TXT 章节信息
            if (preg_match_all(Config::getGeneral('txtChapterRegex'), $text, $chapterMatches, PREG_OFFSET_CAPTURE)) {
                foreach ($chapterMatches[0] as $item) {
                    $mixedMatches[] = ['type' => 'chapter', 'offset' => $item[1]];
                }
            }
            // 查找 TXT 卷信息
            if (preg_match_all(Config::getGeneral('txtVolRegex'), $text, $volMatches, PREG_OFFSET_CAPTURE)) {
                foreach ($volMatches[0] as $item) {
                    $mixedMatches[] = ['type' => 'volume', 'offset' => $item[1]];
                }
            }
        }

        if (empty($mixedMatches)) {
            return [];
        }

        // 按照在文本中出现的字节偏移量排序，这对于生成正确的面包屑至关重要
        usort($mixedMatches, function ($a, $b) {
            return $a['offset'] <=> $b['offset'];
        });

        return self::processMatches($text, $mixedMatches, $isHtml);
    }

    /**
     * 核心处理逻辑：计算行号并根据类型生成标题（支持 HTML 层级面包屑）
     *
     * @param string $text         完整文本
     * @param array  $mixedMatches 经过排序的匹配项
     * @param bool   $isHtml       是否为 HTML
     * @return array 处理后的章节列表
     */
    private static function processMatches(string $text, array $mixedMatches, bool $isHtml): array
    {
        $currentLine = 1;      // 行号从 1 开始
        $lastOffset = 0;       // 上一次处理到的字节位置
        $tempChapters = [];

        // 状态维护
        $htmlHierarchy = [];     // 用于 HTML：存储 [level => title]
        $currentVolTitle = null; // 用于 TXT：存储当前所属卷名

        foreach ($mixedMatches as $item) {
            $offset = $item['offset'];

            // 增量计算行号
            if ($offset > $lastOffset) {
                $segment = substr($text, $lastOffset, $offset - $lastOffset);
                $currentLine += substr_count($segment, "\n");
            }

            if ($isHtml) {
                // HTML 面包屑逻辑
                $level = $item['level'];
                $cleanTitle = self::cleanHtmlTitle($item['content']);

                // 更新当前级别标题
                $htmlHierarchy[$level] = $cleanTitle;

                // 核心逻辑：当遇到 H(n) 时，清空所有大于 n 的子层级
                foreach (array_keys($htmlHierarchy) as $hLevel) {
                    if ($hLevel > $level) {
                        unset($htmlHierarchy[$hLevel]);
                    }
                }

                // 排序并拼接面包屑，例如 "第一卷 » 第一章"
                ksort($htmlHierarchy);
                $displayTitle = implode(' » ', $htmlHierarchy);

                $tempChapters[] = [
                    'title'      => $displayTitle,
                    'start_line' => $currentLine,
                ];
            } else {
                // TXT 逻辑
                $title = self::cleanTxtTitle($text, $offset);

                if ($item['type'] === 'volume') {
                    $currentVolTitle = $title;
                    $tempChapters[] = [
                        'title'      => $title,
                        'start_line' => $currentLine,
                    ];
                } else {
                    $displayTitle = $currentVolTitle ? "$currentVolTitle » $title" : $title;
                    $tempChapters[] = [
                        'title'      => $displayTitle,
                        'start_line' => $currentLine,
                    ];
                }
            }

            $lastOffset = $offset;
        }

        // 统计最后一部分剩余文本的行数，得出总行数
        $totalLines = $currentLine + substr_count(substr($text, $lastOffset), "\n");

        return self::finalizeEndLines($tempChapters, $totalLines);
    }

    /**
     * 清洗 HTML 标题内部文本
     *
     * @param string $content 标签内的 HTML
     * @return string
     */
    private static function cleanHtmlTitle(string $content): string
    {
        // 去除 HTML 标签
        Util::extractTextFromHtml($content);

        // 替换标记位并 trim
        return trim(str_replace([Util::HTML_CHAPTER_MARK, "\n"], '', $content));
    }

    /**
     * 根据字节偏移量提取 TXT 模式下的整行文本
     *
     * @param string $text   完整文本
     * @param int    $offset 字节偏移量
     * @return string
     */
    private static function cleanTxtTitle(string $text, int $offset): string
    {
        $textLength = strlen($text);

        // 寻找行首
        $lineStartPos = 0;
        if ($offset > 0) {
            $searchOffset = $offset - $textLength;
            $foundPos = strrpos($text, "\n", $searchOffset);
            $lineStartPos = ($foundPos === false) ? 0 : $foundPos + 1;
        }

        // 寻找行尾
        $lineEndPos = strpos($text, "\n", $offset);
        if ($lineEndPos === false) {
            $lineEndPos = $textLength;
        }

        // 截取当前行并 Trim
        return trim(substr($text, $lineStartPos, $lineEndPos - $lineStartPos));
    }

    /**
     * 根据开始行号计算各章节的结束行号
     *
     * @param array $chapters 仅包含开始行的列表
     * @param int   $totalLines 文本总行数
     * @return array
     */
    private static function finalizeEndLines(array $chapters, int $totalLines): array
    {
        $count = count($chapters);
        $results = [];

        for ($i = 0; $i < $count; $i++) {
            $startLine = $chapters[$i]['start_line'];

            // 如果是最后一章，结束行就是总行数
            if ($i === $count - 1) {
                $endLine = $totalLines;
            } else {
                // 否则，结束行是下一章开始行的前一行
                $endLine = $chapters[$i + 1]['start_line'] - 1;

                // 边缘情况处理：如果两个章节在同一行（极少见），确保结束行不小于开始行
                if ($endLine < $startLine) {
                    $endLine = $startLine;
                }
            }

            $results[] = [
                'title'      => $chapters[$i]['title'],
                'start_line' => $startLine,
                'end_line'   => $endLine,
            ];
        }

        return $results;
    }

    /**
     * 获取 行号 => 章节名 的映射数组
     *
     * @param string $content
     * @return array
     */
    public static function getLineChapterMap(string $content): array
    {
        $result = [];
        $chapters = self::analyze($content);
        foreach ($chapters as $chapter) {
            for ($i = $chapter['start_line']; $i <= $chapter['end_line']; $i++) {
                $result[$i] = $chapter['title'];
            }
        }

        return $result;
    }

    /**
     * 检查并获取重复的章节列表
     * 该方法会基于拼接完整层级（面包屑）后的章节名进行查重
     *
     * @param string $text 完整文本
     * @return array 返回重复章节数组，格式为 [['章节名' => '...', '重复次数' => N], ...]
     */
    public static function getDuplicateChapters(string $text): array
    {
        // 1. 复用 analyze 方法
        $chapters = self::analyze($text);

        if (empty($chapters)) {
            return [];
        }

        // 2. 提取所有章节的 title（此处 title 已经是包含层级结构的完整字符串）
        $titles = array_column($chapters, 'title');

        // 3. 统计每个 title 出现的次数
        $titleCounts = array_count_values($titles);

        // 4. 过滤出重复的章节并格式化为你需要的返回结构
        $duplicates = [];
        foreach ($titleCounts as $title => $count) {
            if ($count > 1) {
                $duplicates[] = [
                    '章节名'   => $title,
                    '重复次数' => $count,
                ];
            }
        }

        return $duplicates;
    }
}
