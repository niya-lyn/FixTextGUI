<?php

namespace App\Service;

use App\Exception\AppException;
use App\Util\Util;
use App\Service\Diff\Option;
use App\Service\Diff\Extractor;

class ZhuyinProcessor
{
    protected string $pinyinStr = 'a-zA-Zāáǎàōóǒòēéěèīíǐìūúǔùüǖǘǚǜê̄ế̌ềḿ̀ńňǹẑĉŝŋĀÁǍÀŌÓǑÒĒÉĚÈĪÍǏÌŪÚǓÙÜǕǗǙǛÊẾỀḾŃŇǸẐĈŜŊ';

    protected TextFixer $textFixer;

    const ZHUYIN_ONCE                = 0; // 每个生僻字只注音一次
    const ZHUYIN_ALL                 = 1; // 所有位置的生僻字都注音，同一个字重复注音多次
    const ZHUYIN_ONCE_AND_KEEP_FIRST = 2; // 每个字只注音一次，且多音字只取第一种读音
    const ZHUYIN_ALL_AND_KEEP_FIRST  = 3; // 所有位置都注音，且多音字只取第一种读音

    public function __construct(TextFixer $textFixer)
    {
        $this->textFixer = $textFixer;
    }

    public function processZhuyin(string &$content): void
    {
        $zhuyinMode = $this->textFixer->getZhuyinMode();

        if (in_array(
            $zhuyinMode,
            [self::ZHUYIN_ONCE, self::ZHUYIN_ONCE_AND_KEEP_FIRST]
        )) { // 每个字只注音一次
            $this->zhuyinOnce($content);
        }

        $this->clearRepeatedZhuyin($content);

        if (in_array(
            $zhuyinMode,
            [self::ZHUYIN_ONCE_AND_KEEP_FIRST, self::ZHUYIN_ALL_AND_KEEP_FIRST]
        )) { // 只取第一种注音
            $this->extractTheFirstZhuyin($content);
        }

        if ($this->textFixer->getSplitMultiZhuyin()) { // 将词语注音拆分成单字注音
            $this->splitMultiZhuyin($content);
        }
    }

    protected function zhuyinOnce(string &$content): void
    {
        // 1. 生成替换报告
        $option = new Option;
        $option->contextLen = 5;
        (new Extractor($option))->genReplaceCountReport(BOOK_DIR, false);

        // 2. 从报告文件中提取注音映射
        $pinyinMappings = $this->extractPinyinMappings(TEMP_MAP_FILE);

        // 3. 如果提取到映射，则记录到报告文件中
        if (!empty($pinyinMappings)) {
            $this->logPinyinMappingsToFile($pinyinMappings, TEMP_MAP_FILE);
        }

        // 4. 恢复书籍文件内容到处理前的状态
        $content = $this->revertBookFromBakThenRead();

        // 5. 如果有注音映射，则对内容进行一次性注音
        if (!empty($pinyinMappings)) {
            $content = $this->applyPinyinToContentOnce($content, $pinyinMappings);
        }

        // 6. 还原工作目录
        chdir($this->textFixer->getBookDir());
    }

    /**
     * 从指定的映射文件中提取注音映射
     *
     * @param string $mapFilePath 映射文件的路径
     * @return array 字符到“字符+注音”的映射数组
     */
    protected function extractPinyinMappings(string $mapFilePath): array
    {
        $mapContent = file_get_contents($mapFilePath);
        if ($mapContent === false) {
            return [];
        }

        $pinyinMappings = [];

        // 这个正则表达式是故意贪婪的，稍后会从其结果中精确截取需要的部分
        preg_match_all(
            "/([^\n，。…？！；、—\-～~（）【】：<>《》,.?!\[\]]+)(\[[{$this->pinyinStr} 或]+?\])/u",
            $mapContent,
            $matches,
            PREG_SET_ORDER
        );

        foreach ($matches as $match) {
            $greedyHanzi = $match[1];    // 贪婪匹配到的汉字串, e.g., "他是啊啊啊啊啊沨"
            $pinyinBlock = $match[2];    // 带方括号的注音, e.g., "[fēng]"

            $pinyinContent = trim(substr($pinyinBlock, 1, -1)); // 移除方括号 [] 的纯注音

            // 提取逻辑说明：
            //
            // 比如 泀[sī] 或者 泂[jiǒng 或 yíng 或 yǐng 或 jiōng]
            // 这两种都是提取“单个字符[单个注音]”（包含“ 或 ”的优先当成单字来处理）
            //
            // 但是 泂泂[jiǒng jiǒng]，这种就需要提取“多个字符[多个注音]”
            // 方括号内有几个注音（以空格分隔），就要准确截取前面的几个字符，暂时最多支持 5 个字长度

            // 情况 1: 处理单字多音 (包含 " 或 ")
            if (strpos($pinyinContent, ' 或 ') !== false) {
                // 这种格式总是对应单个汉字
                $actualHanzi = mb_substr($greedyHanzi, -1, null);
                if (!isset($pinyinMappings[$actualHanzi])) {
                    $pinyinMappings[$actualHanzi] = $actualHanzi . $pinyinBlock;
                }
                continue;
            }

            // 情况 2: 处理以空格分隔的拼音 (或单个拼音)
            $pinyins = array_filter(explode(' ', $pinyinContent));
            $pinyinCount = count($pinyins);

            // 忽略无效情况：空的注音块，或贪婪匹配的汉字长度小于拼音数
            if ($pinyinCount === 0 || mb_strlen($greedyHanzi) < $pinyinCount) {
                continue;
            }

            // 关键步骤：根据拼音数量，从贪婪匹配的汉字串末尾截取正确的部分
            $actualHanzi = mb_substr($greedyHanzi, -$pinyinCount, null);

            // 统一的映射逻辑：为截取到的正确汉字部分创建映射
            if (!isset($pinyinMappings[$actualHanzi])) {
                $pinyinMappings[$actualHanzi] = $actualHanzi . $pinyinBlock;
            }
        }

        return $pinyinMappings;
    }

    /**
     * 将提取到的注音映射记录到指定的文件中
     *
     * @param array $mappings 要记录的注音映射
     * @param string $filePath 目标文件的路径
     */
    protected function logPinyinMappingsToFile(array $mappings, string $filePath): void
    {
        $currentContent = file_get_contents($filePath);
        $logComment = "/* 已注音生僻字列表：\n" . Util::jsonEncode($mappings) . "\n*/\n";

        $newContent = str_replace(
            "?php\n",
            "?php\n\n" . $logComment,
            $currentContent
        );

        file_put_contents($filePath, $newContent);
    }

    /**
     * 从备份恢复当前书籍文件，并重读
     */
    protected function revertBookFromBakThenRead(): string
    {
        $textFixer = $this->textFixer;
        $bookFilepath = $textFixer->getBookFilepath($textFixer->getBookFile());
        $bookBakFilepath = str_replace(BOOK_DIR, BOOK_BAK_DIR, $bookFilepath);

        if (file_exists($bookBakFilepath) && is_readable($bookBakFilepath)) {
            if (!copy($bookBakFilepath, $bookFilepath)) {
                throw new AppException('恢复失败，无法复制备份文件');
            }
        } else {
            throw new AppException('恢复失败，备份文件不可读');
        }

        return file_get_contents($bookFilepath);
    }

    /**
     * 对给定的内容进行一次性注音处理
     * 每个目标字符在内容中第一次出现时会被替换为“字符[注音]”的形式
     *
     * @param string $content 原始文本内容
     * @param array $pinyinMappings 字符到“字符+注音”的映射
     * @return string 处理后的文本内容
     */
    protected function applyPinyinToContentOnce(string $content, array $pinyinMappings): string
    {
        $targetChars = array_keys($pinyinMappings);
        if (empty($targetChars)) {
            return $content; // 如果没有映射，直接返回原内容
        }

        $escapedChars = array_map(function ($char) {
            return preg_quote($char, '/'); // 使用 '/' 作为分隔符
        }, $targetChars);
        // 构建正则表达式，例如 /字1|字2|字3/u
        $pattern = '/' . implode('|', $escapedChars) . '/u';

        // 初始化替换标记数组，记录每个字符是否已被替换过
        $replacedFlags = array_fill_keys($targetChars, false);

        return preg_replace_callback(
            $pattern,
            function ($matches) use ($pinyinMappings, &$replacedFlags) {
                $char = $matches[0]; // 匹配到的单个字符

                // 检查该字符是否存在于替换列表，并且尚未被替换
                if (isset($replacedFlags[$char]) && !$replacedFlags[$char]) {
                    $replacedFlags[$char] = true; // 标记为已替换
                    return $pinyinMappings[$char]; // 返回“字符[注音]”
                } else {
                    // 如果已替换过，则返回原字符
                    return $char;
                }
            },
            $content
        );
    }

    protected function clearRepeatedZhuyin(string &$content): void
    {
        $content = preg_replace(
            "/\[[{$this->pinyinStr} 或]+?\](\[[{$this->pinyinStr} 或]+?\])/u",
            '$1', // 应该保留后面这个，是之前有判断过的注音
            $content,
        );
    }

    protected function extractTheFirstZhuyin(string &$content): void
    {
        $content = preg_replace(
            "/\[([{$this->pinyinStr}]+)(?: 或 [{$this->pinyinStr}]+)+\]/u",
            '[$1]',
            $content,
        );
    }

    protected function splitMultiZhuyin(string &$content): void
    {
        $content = preg_replace_callback(
            // 注音的部分只包含空格，不包含“或”，避免和多音字混淆
            "/([^\n，。…？！；、—\-～~（）【】：<>《》,.?!\[\]]+)\[([{$this->pinyinStr} ]+?)\]/u",
            function ($matches) {
                $chars = $matches[1];
                $annotation = $matches[2];

                // 分割汉字和对应的注音
                $charParts = mb_str_split($chars);
                $zhuyinParts = explode(' ', trim($annotation));

                $zhuyinCount = count($zhuyinParts);
                $charCount = count($charParts);

                // 仅当注音部分多于一个，且汉字数量不少于注音数量时处理
                if ($zhuyinCount > 1 && $charCount >= $zhuyinCount) {
                    // 根据注音数量，从末尾截取需要添加注音的汉字
                    $charsToAnnotate = array_slice($charParts, -$zhuyinCount);

                    // 获取不需要处理的汉字前缀
                    $prefix = implode('', array_slice($charParts, 0, $charCount - $zhuyinCount));

                    $result = '';
                    for ($i = 0; $i < $zhuyinCount; $i++) {
                        $result .= $charsToAnnotate[$i] . '[' . $zhuyinParts[$i] . ']';
                    }

                    return $prefix . $result;
                }

                return $matches[0]; // 如果不匹配，返回原始字符串
            },
            $content
        );
    }
}
