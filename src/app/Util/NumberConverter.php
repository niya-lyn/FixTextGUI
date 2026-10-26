<?php

namespace App\Util;

/**
 * 中文数字转换器
 */
class NumberConverter
{
    /**
     * 标准数字 (用于两种模式)
     */
    private const CHINESE_DIGITS = [
        '〇' => 0,
        '零' => 0,
        '一' => 1,
        '二' => 2,
        '三' => 3,
        '四' => 4,
        '五' => 5,
        '六' => 6,
        '七' => 7,
        '八' => 8,
        '九' => 9,
        // 大写数字 (仅用于语义模式)
        '壹' => 1,
        '贰' => 2,
        '叁' => 3,
        '肆' => 4,
        '伍' => 5,
        '陆' => 6,
        '柒' => 7,
        '捌' => 8,
        '玖' => 9,
        // 特殊数字 (仅用于语义模式)
        '两' => 2,
        '廿' => 20,
        '卅' => 30,
        '卌' => 40,
    ];

    /**
     * 中文单位
     */
    private const CHINESE_UNITS = [
        '十' => 10,
        '拾' => 10,
        '百' => 100,
        '佰' => 100,
        '千' => 1000,
        '仟' => 1000,
    ];

    /**
     * 中文大单位
     */
    private const CHINESE_LARGE_UNITS = [
        '万' => 10000,
        '萬' => 10000,
        '亿' => 100000000,
        '億' => 100000000,
    ];

    /**
     * 仅用于逐位表示法判断的基础数字字符
     */
    private const POSITIONAL_DIGITS_CHARS = [
        '〇',
        '一',
        '二',
        '三',
        '四',
        '五',
        '六',
        '七',
        '八',
        '九',
        '零'
    ];

    public static function arabicToChnNum($num)
    {
        // 节权位的位置
        $unitSectionPos = 0;
        $chnStr = '';
        // 单个数字转换用的数组
        $chnNumChar = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九'];
        // 节权位转换用的数组
        $chnUnitSection = ['', '万', '亿', '万亿', '亿亿'];
        // 节内权位换算的数组
        $chnUnitChar = ['', '十', '百', '千'];
        $needZero = false;

        if ($num === 0) {
            return $chnNumChar[0];
        }

        // 节内换算的闭包
        $sectionToChn = function ($section) use ($chnNumChar, $chnUnitChar) {
            $chnStr = '';
            // 节内的位置
            $unitPos = 0;
            $zero = true;

            while ($section > 0) {
                $v = $section % 10;
                if ($v === 0) {
                    if (!$zero) {
                        $zero = true;
                        $chnStr = $chnNumChar[$v] . $chnStr;
                    }
                } else {
                    $zero = false;
                    $strInsert = $chnNumChar[$v];
                    $strInsert .= $chnUnitChar[$unitPos];
                    $chnStr = $strInsert . $chnStr;
                }
                $unitPos++;
                $section = floor($section / 10);
            }
            return $chnStr;
        };

        while ($num > 0) {
            $section = $num % 10000;
            if ($needZero) {
                $chnStr = $chnNumChar[0] . $chnStr;
            }
            $strInsert = $sectionToChn($section);
            $strInsert .= ($section !== 0) ? $chnUnitSection[$unitSectionPos] : $chnUnitSection[0];
            $chnStr = $strInsert . $chnStr;
            $needZero = ($section < 1000) && ($section > 0);
            $num = floor($num / 10000);
            $unitSectionPos++;
        }

        $search = '一十';
        $replacement = '十';
        // 处理含一十开头的（这个可根据需求处理）
        if (mb_substr($chnStr, 0, 2) === $search) {
            $position = strpos($chnStr, $search);
            $chnStr = substr_replace($chnStr, $replacement, $position, strlen($search));
        }

        return $chnStr;
    }

    /**
     * 将中文数字字符串（支持语义和逐位表示法）转换为阿拉伯整数
     *
     * 支持类型:
     * - 语义: '一百零八', '两千', '十五', '一亿'
     * - 逐位: '一〇八' (108), '〇一〇' (10), '九九' (99)
     *
     * 如果输入无效或无法解析，则返回 null。
     * 对于逐位表示法的 '〇一〇'，返回整数 10。
     *
     * @param string $chineseNumStr 中文数字字符串
     * @return int|null 转换后的阿拉伯数字，失败返回 null
     */
    public static function chnToArabicNum(string $chineseNumStr): ?int
    {
        // 输入校验
        if (empty($chineseNumStr)) {
            return null;
        }

        // 去除空白字符
        $chineseNumStr = trim($chineseNumStr);
        if ($chineseNumStr === '') {
            return null;
        }

        // 处理直接传入的阿拉伯数字字符串
        if (preg_match('/^[0-9]+$/', $chineseNumStr)) {
            return (int)$chineseNumStr;
        }

        // 模式判断与处理
        $isPositional = self::isPositionalFormat($chineseNumStr);

        if ($isPositional) {
            return self::parsePositional($chineseNumStr);
        }

        return self::parseSemantic($chineseNumStr);
    }

    /**
     * 判断是否为逐位表示法
     *
     * @param string $str 输入字符串
     * @return bool
     */
    private static function isPositionalFormat(string $str): bool
    {
        $chars = self::mbStrSplit($str);
        foreach ($chars as $char) {
            if (!in_array($char, self::POSITIONAL_DIGITS_CHARS, true)) {
                return false;
            }
        }

        return true;
    }

    /**
     * 解析逐位表示法
     *
     * @param string $str 中文数字字符串
     * @return int|null
     */
    private static function parsePositional(string $str): ?int
    {
        $chars = self::mbStrSplit($str);

        // 如果只有一个字符
        if (count($chars) === 1) {
            $char = $chars[0];
            if (in_array($char, ['〇', '零'], true)) {
                return 0;
            }
            if (isset(self::CHINESE_DIGITS[$char])) {
                return self::CHINESE_DIGITS[$char];
            }
        }

        // 多位数字，逐位转换
        $arabicStr = '';
        foreach ($chars as $char) {
            if (isset(self::CHINESE_DIGITS[$char])) {
                $arabicStr .= (string)self::CHINESE_DIGITS[$char];
            } else {
                return null;
            }
        }

        // 转换为整数，处理 "010" -> 10 的情况
        return (int)$arabicStr;
    }

    /**
     * 解析语义表示法
     *
     * @param string $str 中文数字字符串
     * @return int|null
     */
    private static function parseSemantic(string $str): ?int
    {
        // 检查是否包含无效字符
        if (!self::isValidSemanticString($str)) {
            // error_log("警告：输入 '{$str}' 包含无法识别的语义字符。");
            return null;
        }

        // 处理特殊开头的 "十" (如 "十五") -> "一十五"
        if (self::mbStrStartsWith($str, '十') || self::mbStrStartsWith($str, '拾')) {
            $str = '一' . $str;
        }

        $total = 0;
        $currentSection = 0;  // 当前大单位(万/亿)内的数值
        $lastDigitVal = 0;    // 记录遇到的最后一个数字的值 (1-9)
        $readingZero = false;  // 标记是否刚读过零/〇

        $chars = self::mbStrSplit($str);

        foreach ($chars as $char) {
            if (isset(self::CHINESE_DIGITS[$char])) {
                $digit = self::CHINESE_DIGITS[$char];

                if ($digit === 0) {
                    // 遇到零，标记一下，清空最后读到的数字值
                    $readingZero = true;
                    $lastDigitVal = 0;
                } else {
                    // 遇到1-9, 或 两/廿/卅/卌
                    if (in_array($char, ['廿', '卅', '卌'], true)) {
                        // 这些字符本身代表一个值 (20, 30, 40)
                        $currentSection += $digit;
                        $lastDigitVal = 0;
                    } else {
                        $lastDigitVal = $digit;  // 普通数字 1-9, 两
                    }
                    $readingZero = false;
                }
            } elseif (isset(self::CHINESE_UNITS[$char])) {
                $unit = self::CHINESE_UNITS[$char];

                // 如果 lastDigitVal > 0，说明是 "三千", "五百" 等
                if ($lastDigitVal > 0) {
                    $currentSection += $lastDigitVal * $unit;
                } elseif ($readingZero) {
                    // 零后面跟单位，单位作用于已有的 currentSection
                    // 不做处理
                }

                // 应用单位后，重置最后数字值
                $lastDigitVal = 0;
                $readingZero = false;
            } elseif (isset(self::CHINESE_LARGE_UNITS[$char])) {
                $unit = self::CHINESE_LARGE_UNITS[$char];

                // 结算当前大单位(万/亿)之前的部分
                $sectionValue = $currentSection + $lastDigitVal;

                // 特殊处理：如果 sectionValue 是 0，默认系数为 1
                if ($sectionValue === 0) {
                    $sectionValue = 1;
                }

                // 累加到总数
                $total += $sectionValue * $unit;

                // 重置当前段的值
                $currentSection = 0;
                $lastDigitVal = 0;
                $readingZero = false;
            }
        }

        // 循环结束后，加上最后一部分
        $total += $currentSection + $lastDigitVal;

        // 对结果进行最后确认
        if ($total === 0) {
            return self::isAllZeroChars($str) ? 0 : null;
        }

        return $total;
    }

    /**
     * 检查是否为有效的语义字符串
     *
     * @param string $str 输入字符串
     * @return bool
     */
    private static function isValidSemanticString(string $str): bool
    {
        $allSemanticChars = array_merge(
            array_keys(self::CHINESE_DIGITS),
            array_keys(self::CHINESE_UNITS),
            array_keys(self::CHINESE_LARGE_UNITS)
        );

        $chars = self::mbStrSplit($str);
        foreach ($chars as $char) {
            if (!in_array($char, $allSemanticChars, true)) {
                return false;
            }
        }

        return true;
    }

    /**
     * 检查字符串是否全为零字符
     *
     * @param string $str 输入字符串
     * @return bool
     */
    private static function isAllZeroChars(string $str): bool
    {
        $chars = self::mbStrSplit($str);
        foreach ($chars as $char) {
            if (!in_array($char, ['零', '〇'], true)) {
                return false;
            }
        }

        return true;
    }

    /**
     * 多字节字符串分割为字符数组
     *
     * @param string $str 输入字符串
     * @return array<int, string>
     */
    private static function mbStrSplit(string $str): array
    {
        return preg_split('//u', $str, -1, PREG_SPLIT_NO_EMPTY) ?: [];
    }

    /**
     * 检查字符串是否以指定前缀开始（多字节安全）
     *
     * @param string $haystack 被检查的字符串
     * @param string $needle 前缀
     * @return bool
     */
    private static function mbStrStartsWith(string $haystack, string $needle): bool
    {
        return mb_substr($haystack, 0, mb_strlen($needle)) === $needle;
    }
}
