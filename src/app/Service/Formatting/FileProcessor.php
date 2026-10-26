<?php

namespace App\Service\Formatting;

use App\Exception\AppException;
use App\Util\Util;
use App\Util\Config;
use App\Service\EpubFixer;
use App\Util\Console\Show;
use App\Trait\FileWalkerTrait;
use App\Util\NumberConverter;

class FileProcessor
{
    use FileWalkerTrait;

    protected bool $isTxtFile = false;
    protected bool $isHtmlFile = false;

    public Option $option;

    // 这里匹配了如下几种空格：
    // 1.` ` (第一个字符) - 普通空格 (Space)
    //     * Unicode 码：`U+0020`
    //     * 描述：最常见、标准的空格，由键盘空格键输入。用于分隔单词。其宽度通常是可变的，取决于字体和上下文。允许在此处自动换行。
    //
    // 2.`　` (第二个字符) - 全角空格 (Ideographic Space)
    //     * Unicode 码：`U+3000`
    //     * 描述：主要用于中日韩 (CJK) 文字排版。宽度固定，等于一个标准汉字字符的宽度（全角）。常用于 CJK 文本的对齐或创建视觉上较宽的间隔。
    //
    // 3.` ` (第三个字符) - 半角空格 (En Space)
    //     * Unicode 码：`U+2002`
    //     * 描述：排版用空格。传统上宽度等于大写字母 'N' 的宽度，或 1/2 Em 空格的宽度。通常比普通空格 (U+0020) 宽，但比 Em 空格 (U+2003) 窄。用于精确控制间距。
    //
    // 4.` ` (第四个字符) - 全角空格 (Em Space)
    //     * Unicode 码：`U+2003`
    //     * 描述：排版用空格。传统上宽度等于当前字体的磅值（point size），或约等于大写字母 'M' 的宽度。通常比 En 空格 (U+2002) 宽。用于段落缩进或创建较大的视觉间隔。（注意：虽然也可能俗称全角空格，但其定义和 CJK 的 U+3000 不同）。
    //
    // 5.` ` (第五个字符) - 不换行空格 (No-Break Space / NBSP)
    //     * Unicode 码：`U+00A0`
    //     * 描述：视觉上通常和普通空格 (U+0020) 宽度相同，但其最重要的特性是不允许在此空格处自动换行。常用于需要将特定单词或符号组合保持在同一行的情况（例如 "10 kg"）。HTML 中常用 `&nbsp;` 表示。
    //
    // 6.`\x{E000}-\x{F8FF}` (字符集合) - 据说是 PUA 专用区（Private Use Area，范围 U+E000 至 U+F8FF）字符，总之就是一种不能正常显示的空格
    const SPACE_PATTERN = " 　   \x{E000}-\x{F8FF}\t\f";

    public function __construct(Option $option)
    {
        $this->option = $option;
    }

    /**
     * @throws AppException
     */
    public function process(string $bookDir): void
    {
        // 按标点强制分行和转换特殊生僻字时，同步处理 booksBak 中的内容
        $shouldProcessBooksBak = (
            $this->option->splitByPunctuations
            || $this->option->processSpecialChars
            || in_array($this->option->quotationType, [1, 2])
        );

        if (!$shouldProcessBooksBak) { // 同步处理 booksBak 时，不进行删除等动作
            Show::opStart("备份文件");
            // 自动清除 booksBak 文件夹中的残留备份文件
            Util::recursiveDelete(BOOK_BAK_DIR, false);
            Util::recursiveDelete(BOOK_FIX_DIR, false);

            // 提取 epub 文本时不自动进行备份
            if (!$this->option->extractTextFromHtml) {
                Util::recursiveCopy(BOOK_DIR, BOOK_BAK_DIR);
            }
            Show::opEnd();
        }

        if ($this->option->isDefaultEncoding()) {
            (new EpubFixer())->mergeAllEpubText();
        }

        $this->setInWalkFunc(function ($dir, $file) {
            $this->processFile($file);
        });

        $this->walkFiles($bookDir);

        if ($shouldProcessBooksBak) { // 某些操作需要同步处理 booksBak
            $this->walkFiles(BOOK_BAK_DIR);
        }

        if ($this->option->extractTextFromHtml) {
            echo PHP_EOL;
            (new EpubFixer())->bulkSplitEpubs();

            // 删除残留的其他合并记录
            Util::recursiveDelete(EPUB_MERGE_LOG_DIR, false);
        }
    }

    public static function getProcessor($option = null): self
    {
        if (!$option) {
            $option = new Option;
        }

        return new self($option);
    }

    /**
     * 给外部直接调用
     *
     * @param string $bookDir
     * @return void
     */
    public function publicChangeTextFormat(string $bookDir = BOOK_DIR): void
    {
        Util::unifyAllBooksFormat();

        $this->option->changeTextFormat = true;
        $this->process($bookDir);
    }

    /**
     * @throws AppException
     */
    protected function processFile(string $file): void
    {
        $this->isTxtFile = Util::isTxtFile($file);
        $this->isHtmlFile = Util::isHtmlFile($file);

        $content = file_get_contents($file);

        // 转换编码、换行符
        if ($this->isTxtFile && !$this->option->isDefaultEncoding()) {
            Util::changeEncodingAndNewLineType($content, $this->option->toEncoding, $this->option->newLineType);
        }

        // 转换英文大小写
        if ($this->option->changeCaseInText) {
            $this->changeCaseInText($content);
        }

        // 阿拉伯数字转中文
        if ($this->option->arabicToChineseNum) {
            $this->arabicToChnNum($content);
        }

        // 移除中文间空格
        if ($this->option->rmSpacesBetweenChnChars) {
            $this->rmSpacesBetweenChnChars($content);
        }

        // 按照结尾标点强制进行分行，方便 BC 比对
        if ($this->option->splitByPunctuations) {
            $this->splitByEndPunctuations($content);
        }

        // 对特殊字符进行转义和还原
        if ($this->option->processSpecialChars) {
            $this->processSpecialChars($content);
        }

        // 规范标点符号
        if ($this->option->normalizePunctuations) {
            $this->normalizePunctuations($content);
        }

        // html 转 txt
        if ($this->option->extractTextFromHtml && $this->isHtmlFile) {
            Util::extractTextFromHtml($content);
        }

        // 更改弯引号、直角引号
        $this->changeQuotationType($content);

        // 更改空行、缩进等排版
        if (
            (
                $this->option->changeTextFormat
                || $this->option->extractTextFromHtml
            )
            && $this->option->isDefaultEncoding()
            && $this->option->consecutiveQuotationsType == 0
        ) {
            $this->changeTextFormat($content);
        }

        // 识别无缩进的多级标题，自动进行标记
        if ($this->option->formatHeadings && $this->isTxtFile) {
            $this->formatHeadings($content);
        }

        // 从 epub 中提取 txt 时，获取书籍信息
        if ($this->option->extractTextFromHtml && $this->isHtmlFile) {
            $this->getBookInfoFromHtml($content);
        }

        // 添加个人校对信息
        if (
            ($this->option->addOpInfo && $this->isTxtFile)
            || (
                $this->isHtmlFile
                && $this->option->extractTextFromHtml
                && $this->option->setExtraTextInfo
            )
        ) {
            $this->addOpInfo($content, Config::getFormatting("username"));
        }

        // 在中文和英文、数字之间加空格，目前无法处理单位和数字间的空格
        if ($this->option->paranoidTextSpacing && $this->isTxtFile) {
            $content = Util::pangu($content);
        }

        $outputFile = $file;
        if ($this->option->extractTextFromHtml && $this->isHtmlFile) {
            $outputFile = "【EPUB提取】" . Util::removeEpubMergePrefix($file);
        }

        file_put_contents($outputFile, trim($content) . $this->option->newLineType);

        if ($this->option->isDefaultEncoding()) {
            $charCount = "（" . Util::countTextChars($outputFile, $content) . "）";
            $this->extraProgressInfo = $charCount;
        }
    }

    public function changeTextFormat(string &$content): void
    {
        if ($this->option->addHtmlTag == 1) {
            $content = preg_replace("/^(?![ 　\n])(.+)$/umi", "<title>$1</title>", $content);
        } else if ($this->option->addHtmlTag == 2) {
            $this->option->addIndentation = 1; // 移除标签时顺便增加缩进
            $content = preg_replace("/<title>(.*?)<\/title>\n<title>.*?<\/title>/umi", "◎$1", $content);
            $content = strip_tags($content);
        }

        // 移除所有空行和行首行尾空格
        $spacePattern = self::SPACE_PATTERN;
        $content = preg_replace("/^[{$spacePattern}]*$\n/um", "", $content);
        $content = preg_replace("/^[{$spacePattern}]+/um", "", $content);
        $content = preg_replace("/[{$spacePattern}]+$/um", "", $content);

        // 增加首行缩进和章节间的分隔空行
        if ($this->option->addIndentation) {
            $content = preg_replace("/^/um", "　　", $content);
            // 转换空格：【^第([\d一二三四五六七八九十零〇百千万亿两廿卅卌壹贰叁肆伍陆柒捌玖拾佰仟萬億.\-]+)章[：:]】 转为：【第\1章 】
            $content = preg_replace(
                "/^[ 　]*((?:(?:[第卷章续]之?[\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾.\-—至到章]+[章回卷部集节篇册话]?)|[（(][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾.\-—至到章]+[)）]|楔子|引[言子]?|前言|序[\d言曲章]?|续[篇章]?|跋|后记|番外篇?|篇外篇|特别篇|后日谈|小剧场|间章|.{0,8}总结|最?终[卷篇]|大?结局[卷篇]?|终章|.{0,6}感言|后记|尾声|内容简介)(?:[ 　]|(?<=[章回卷部集节篇册话记跋])[：:]|(?<![.\-])$)+)/um",
                "\n\n$1",
                $content
            );
            // 其他的特殊章节可以统一在前面加【◎】这个特殊符号（注：在输入法中可输入“同心圆”打出，或使用特殊符号功能输入）
            // 查找无缩进标题：^[^ 　  \t第◎【\[※\n]
            $content = preg_replace("/^[ 　]*◎(.*)/um", "\n\n◎$1", $content);
        }

        // txt 套标签
        if ($this->option->addHtmlTag == 1) {
            $content = preg_replace("/^(?!<title>)(.*)$/umi", "<p>$1</p>", $content);
            $content = preg_replace("/<p>※※※<\/p>/umi", '<p class="brline"><img alt="" src="../Images/transpacep.png"/>　</p>', $content); // 空行
            $content = preg_replace("/^<title>.*?<\/title>/umi", "$0\n$0", $content); // 复制 title 行以应对 html 中的两处标题
        } else if ($this->option->addHtmlTag == 2) {
            $content = preg_replace("/^◎(?!◎)/umi", "", $content); // 移除 title 中的◎（如果自带◎则不移除）
        }

        // 提取 epub 文本后，移除特殊章节标记
        if (str_contains($content, Util::HTML_CHAPTER_MARK)) {
            $content = str_replace(Util::HTML_CHAPTER_MARK, "", $content);
        }
    }

    /**
     * @throws AppException
     */
    protected function formatHeadings(string &$content): void
    {
        $patterns = [
            [
                // 没有明确标题标记的顶格行统一加上 ◎
                'search'  => "^(?!第.*?[章回卷部集节篇册])(?=[^ 　\n章卷部集节篇册◎=+])(.*?)$",
                'replace' => "◎$1",
            ],
            [
                // 先最多只支持三级
                // 如果明确是多个连续的同级 ◎ 行，则只能手动调整了
                // 限制 30000 是为了强行终止搜索，避免触及 backtrack 限制
                'search'  => "^◎([^◎]{0,30000})^◎◎([^◎]{0,30000})^◎◎◎([^◎]*?)\n",
                'replace' => "第0.0部 ◎$1\n\n\n第0.0卷 ◎$2\n\n\n第0.0章 ◎$3\n",
            ],
            [
                // 先最多只支持三级
                'search'  => "^◎(.*?)\n+◎(.*?)\n+◎(.*?)\n",
                'replace' => "第0.0部 ◎$1\n\n\n第0.0卷 ◎$2\n\n\n第0.0章 ◎$3\n",
            ],
            [
                'search'  => "^◎(.*?)\n+◎(.*?)\n+([第章][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾至到.\-—]+[章回节篇话])",
                'replace' => "第0.0部 ◎$1\n\n\n第0.0卷 ◎$2\n\n\n$3",
            ],
            [
                'search'  => "^◎(.*?)\n+([第卷][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾.\-—]+[卷部集册])",
                'replace' => "第0.0部 ◎$1\n\n\n$2$3$4",
            ],
            [
                'search'  => "^◎([^◎]{0,30000})^◎◎([^◎]*?)\n",
                'replace' => "第0.0卷 ◎$1\n\n\n第0.0章 ◎$2\n",
            ],
            [
                // 如果明确是多个连续的同级 ◎ 行，则只能手动调整了
                'search'  => "^◎(.*?)\n+◎(.*?)\n",
                'replace' => "第0.0卷 ◎$1\n\n\n第0.0章 ◎$2\n",
            ],
            [
                'search'  => "^◎(.*?)\n+([第章][\d一二三四五六七八九十零〇百千万两廿卅卌壹贰叁肆伍陆柒捌玖拾至到.\-—]+[章回节篇话])",
                'replace' => "第0.0卷 ◎$1\n\n\n$2",
            ],
            [
                'search'  => "^◎(.*?)\n",
                'replace' => "第0.0章 ◎$1\n",
            ],
        ];

        // 统一调整描述符为 um，否则换行符要写成 [\n] 才不会出错
        Util::multiRegexReplace($patterns, $content, 'um');

        $this->option->addIndentation = true;
        $this->changeTextFormat($content);
    }

    protected function changeQuotationType(string &$content): void
    {
        $quotationMap = [];
        if ($this->option->quotationType == 1) {
            $quotationMap = array_combine(
                ['「', '」', '『', '』'],
                ['“', '”', '‘', '’'],
            );
        } else if ($this->option->quotationType == 2) {
            $quotationMap = array_combine(
                ['“', '”', '‘', '’'],
                ['「', '」', '『', '』'],
            );
        }

        if ($quotationMap) {
            $content = strtr($content, $quotationMap);
        }
    }

    protected function rmSpacesBetweenChnChars(string &$content): void
    {
        // 先将不在行首的连续空格转为一个空格，可以处理标题行的多余分隔空格
        $spacePattern = self::SPACE_PATTERN;
        $pattern = "/(?<!^)(?<=[^{$spacePattern}])[{$spacePattern}]+(?=[^{$spacePattern}])/um";
        $content = preg_replace($pattern, " ", $content);

        // 需要排除掉一些英文标点，避免误伤正常的英文句子
        // 因此这个步骤应该必须放到 normalizePunctuations 之后再来做
        $pattern = "/([^\n 　]{0,20})(?:(?<![\n 　章卷册集◎,.!?;:'\"{}])[{$spacePattern}]+(?![\da-zA-Z 　第\"'{}])|(?<![\n\da-zA-Z 　章回卷部集节篇册◎,.!?;:'\"{}])[{$spacePattern}]+(?![第\"'{}]))/um";
        $content = preg_replace_callback(
            $pattern,
            function ($matches) {
                $firstChar = mb_substr($matches[1], 0, 1);
                if (in_array($firstChar, ['章', '卷', '册', '集', '◎'])) {
                    // 强行检查首字符，匹配到这些内容时原样返回
                    return $matches[0];
                }

                return $matches[1];
            },
            $content
        );
    }

    protected function splitByEndPunctuations(string &$content): void
    {
        if ($this->option->splitByPunctuations == 1) { // 分行
            // 给每个结尾标点后面附加一个“分隔符+换行”，
            // 后续只需要去除“分隔符+换行”即可恢复文件原状
            $partBreak = $this->option->punctuationPartBreak;
            $content = preg_replace(
                "/(.*?[，。、；”’？！）：」』\n])/umi",
                "$1{$partBreak}",
                $content
            );

            // 同时移除所有缩进
            $content = preg_replace("/^[ 　]+/umi", "", $content);
            $content = preg_replace("/[ 　]+$/umi", "", $content);
        } else if ($this->option->splitByPunctuations == 2) { // 还原
            $content = str_replace($this->option->punctuationPartBreak, "", $content);
        }
    }

    protected function processSpecialChars(string &$content): void
    {
        if ($this->option->processSpecialChars == 1) { // 转义
            $content = Util::encodeSpecialCharsToText($content, $this->option->specialCharsScope);
        } else if ($this->option->processSpecialChars == 2) { // 还原
            $content = Util::decodeTextToSpecialChars($content);
        }
    }

    protected function getBookInfoFromHtml(string &$content): void
    {
        preg_match("/制作说明\n　　(.*?)\n/u", $content, $matches);
        $bookName = $matches[1] ?? "";
        if (!$bookName) {
            return;
        }

        preg_match("/　　(.*?)·著\n/u", $content, $matches);
        $author = $matches[1] ?? "";
        if (!$author) {
            return;
        }

        preg_match("/{$author}·.*?·(.*?)\n/u", $content, $matches);
        $charCount = $matches[1] ?? "";
        if (!$charCount) {
            return;
        }

        $content = preg_replace("/封面\n(.*?)内容简介\n/us", "", $content);

        $info = <<<DOC
        书籍信息
        　　书名：{$bookName}
        　　作者：{$author}
        　　字数：{$charCount}


        内容简介
        DOC;

        if ($this->option->setExtraTextInfo) {
            $content = $info . $content;
            $content = str_replace("内容简介\n", "内容简介", $content);
        } else {
            $content = "内容简介\n" . trim($content);
            $content = preg_replace("/内容简介.*?\n(?=[^　])/us", "", $content);
        }
    }

    /**
     * @throws AppException
     */
    protected function normalizePunctuations(string &$content): void
    {
        // 先统一转换一些标点
        $content = Util::strtrWithWordsMap($content, Config::getFormatting('punctuationMap'), true);

        // 检查 txt 文件中是否存在 html 实体
        if ($this->isTxtFile) {
            $content = html_entity_decode($content);
        }

        // 规范中文内容的常见标点
        // 将英文标点转为中文标点（不影响纯英文内容），去除标点间的空格
        Util::multiRegexReplace(Config::getFormatting('punctuationPatterns'), $content);

        // 修改连续多行引号的使用方式
        if ($this->option->consecutiveQuotationsType != 0) {
            $this->changeConsecutiveQuotations(
                $content,
                $this->option->consecutiveQuotationsType
            );
        }
    }

    protected function changeConsecutiveQuotations(string &$content, int $quotationType): void
    {
        $config = $this->getQuotationReplacementConfig($quotationType);
        $content = preg_replace_callback(
            $config['searchPattern'],
            function ($matches) use ($config) {
                $lines = explode("\n", $matches[2]);
                $isHtmlFile = $this->isHtmlFile;
                foreach ($lines as &$line) {
                    $line = preg_replace(
                        $isHtmlFile ? $config['htmlPattern'] : $config['txtPattern'],
                        $isHtmlFile ? $config['htmlReplacement'] : $config['txtReplacement'],
                        $line
                    );
                }

                return $matches[1] . implode("\n", $lines) . "”";
            },
            $content
        );
    }

    protected function getQuotationReplacementConfig(int $type): array
    {
        $configs = [
            1 => [
                'searchPattern'   => "/((?<!“)“[^”“]*?\n+)(.*?)”/us",
                'htmlPattern'     => "/([ 　]*)(<p[^\/>]*?>)(?!“)/um",
                'htmlReplacement' => "$1$2“",
                'txtPattern'      => "/^([ 　]*)(?!“)([^ 　]+)/um",
                'txtReplacement'  => "$1“$2",
            ],
            2 => [
                'searchPattern'   => "/((?<!“)“[^”]*?\n+)(.*?)”/us",
                'htmlPattern'     => "/([ 　]*)(<p[^\/>]*?>)“/um",
                'htmlReplacement' => "$1$2",
                'txtPattern'      => "/^([ 　]*?)“/um",
                'txtReplacement'  => "$1",
            ],
        ];

        return $configs[$type] ?? throw new AppException("不支持的引号类型: $type");
    }

    protected function changeCaseInText(string &$content): void
    {
        // 1-英文首字母大写 2-所有英文改成小写 3-所有英文改成大写 4-只改固定词组
        // 模式 1, 2, 3: 应用通用的大小写转换规则
        if (in_array($this->option->changeCaseInText, [1, 2, 3])) {
            $this->applyGeneralCaseChange($content, $this->option->changeCaseInText);
        }

        // 模式 1, 4: 应用固定词组的大小写修正
        // 模式 1 (ucfirst) 之后也需要修正固定词组，如 "Iphone" -> "iPhone"
        if (in_array($this->option->changeCaseInText, [1, 4])) {
            $this->applyFixedWordCase($content);
        }
    }

    /**
     * 应用通用的大小写转换 (首字母大写, 全部小写, 全部大写)
     *
     * @param string &$content
     * @param int $mode 转换模式 (1, 2 或 3)
     */
    private function applyGeneralCaseChange(string &$content, $mode): void
    {
        // 1. 构建主匹配模式 (包含单词边界或不包含)
        $mainPattern = '([a-zA-Z0-9]+)';
        if (in_array($mode, [1, 4])) {
            // 模式 1 或 4，需要复杂的前缀来确定单词边界
            $prefix = "(?<![a-zA-Z\d@.,’ '])";
            $mainPattern = $prefix . $mainPattern;
        }

        // 2. 根据文件类型，用 HTML 标签跳过逻辑进行最终包装
        if ($this->isHtmlFile) {
            // 对于 HTML 文件，在主模式前加上跳过逻辑
            $pattern = '/<[^>]*>(*SKIP)(*F)|' . $mainPattern . '/um';
        } else {
            // 对于纯文本，直接使用主模式
            $pattern = '/' . $mainPattern . '/um';
        }

        $content = preg_replace_callback(
            $pattern,
            function ($matches) use ($mode) {
                switch ($mode) {
                    case 1:
                        return ucfirst($matches[1]);
                    case 2:
                        return strtolower($matches[1]);
                    case 3:
                        return strtoupper($matches[1]);
                    default:
                        return $matches[1];
                }
            },
            $content
        );
    }

    /**
     * 应用固定词组的大小写修正（例如：iphone -> iPhone）
     * @param string &$content
     */
    private function applyFixedWordCase(string &$content): void
    {
        $fixedCaseWords = Config::getFormatting("fixedCaseWords");
        if (empty($fixedCaseWords)) {
            return;
        }

        // 1. 构建动态正则表达式
        $fixedPattern = $this->buildFixedWordsPattern($fixedCaseWords);
        if ($fixedPattern === null) {
            return; // 如果没有有效的单词，则不执行任何操作
        }

        // 2. 创建大小写不敏感的映射表 (key 为小写，value 为正确的大小写)
        // 使用递归正则表达式来正确处理嵌套断言，例如 (?<=(?<!aaa)\d)
        $assertionPattern = '/\(\?(?:<=|<!|=|!)((?:[^()]|\((?1)\))*)\)/';
        $fixedMap = array_combine(
            array_map(function ($word) use ($assertionPattern) {
                // 移除断言结构，例如将 '(?<=\d)iPhone' 变为 'iPhone'，以便创建正确的查找键
                $cleanedWord = preg_replace($assertionPattern, '', $word);
                return strtolower($cleanedWord);
            }, $fixedCaseWords),
            array_map(function ($word) use ($assertionPattern) {
                // 同样移除值中的断言，保留原始大小写，用于替换
                return preg_replace($assertionPattern, '', $word);
            }, $fixedCaseWords)
        );

        // 3. 执行替换
        $content = preg_replace_callback(
            "/$fixedPattern/umi",
            fn($m) => $fixedMap[strtolower($m[1])] ?? $m[1],
            $content
        );
    }

    /**
     * 根据单词列表构建一个复杂的正则表达式
     * 这个正则能处理普通单词和以【.&-】等特殊字符开头的单词的不同边界要求
     *
     * @param array $words 单词列表
     * @return string|null 返回构建好的正则表达式字符串，如果列表为空则返回 null
     */
    private function buildFixedWordsPattern(array $words): ?string
    {
        // 长单词优先匹配，防止 "id=" 被 "ID" 这样的部分匹配优先捕获
        usort($words, fn($a, $b) => strlen($b) - strlen($a));

        $specialPrefixWords = [];
        $normalWords = [];
        foreach ($words as $word) {
            if (Util::multiStrContains($word, ["(?=", "(?!", "(?<=", "(?<!"])) {
                // 含有断言时，不转义，直接拼接，这时需要用户自己在正则中处理转义
                $normalWords[] = $word;
            } else if (Util::multiStrStartsWith($word, [".", "-", "#", "&"])) {
                $specialPrefixWords[] = preg_quote($word, '/');
            } else {
                $normalWords[] = preg_quote($word, '/');
            }
        }

        $patternClauses = [];

        // 为普通单词创建带负向后行断言的子模式
        if (!empty($normalWords)) {
            $patternClauses[] = "(?<![-<\/a-zA-Z])(" . implode("|", $normalWords) . ")";
        }

        // 为以 .&- 等特殊字符开头的单词创建不带该断言的子模式
        if (!empty($specialPrefixWords)) {
            $patternClauses[] = "(" . implode("|", $specialPrefixWords) . ")";
        }

        if (empty($patternClauses)) {
            return null;
        }

        // 使用 "分支重置组" (?|...) 将所有子模式合并
        // 这能确保无论哪个分支匹配成功，捕获的单词总是在捕获组 $m[1] 中
        // 最后加上统一的负向先行断言
        //
        // 示例生成的模式：
        // (?|(?<![-<\/a-zA-Z])(YouTube|iPhone|iMac)|(\.cn|\.com))(?![a-zA-Z]|[\"']?\/?\>)
        return "(?|" . implode('|', $patternClauses) . ")(?![a-zA-Z]|[\"']?\/?>)";
    }

    protected function arabicToChnNum(string &$content): void
    {
        $content = preg_replace_callback_array(
            [
                "/(?<![a-zA-Z\d.—\-－～~%％#&“”’'\"【】（）_:：∶\/◎注释註釋章卷第])(\d{1,6})(?![a-zA-Z\d.—\-－～~%％#&“”’'\"【】（）_:：∶\/\r\n◎℃年月日时分秒章回卷部集节篇册型号房室点版]|[步手]枪|千[克米焦瓦])/u" => function ($matches) {
                    // 不转换 007 等以 0 开头的编号
                    if (str_starts_with($matches[1], 0) && mb_strlen($matches[1]) > 1) {
                        return $matches[1];
                    }

                    return NumberConverter::arabicToChnNum($matches[1]);
                },
                "/(?<=[第])(\d{1,5})(?=[名位个人头只条朵年月日时分秒])/u" => function ($matches) {
                    // 补充一些被上面那条排除的“第××”
                    return NumberConverter::arabicToChnNum($matches[1]);
                },
            ],
            $content
        );

        $content = strtr($content, Config::getFormatting("fixedArabicNumWords"));
    }

    protected function addOpInfo(string &$content, string $username): void
    {
        $opInfo = <<<DOC



        ===============================================================
        +欢迎阅读【{$username}】个人校对电子书。转载请保留本声明，谢谢合作～
        +仅因个人爱好订阅及整理，如果您喜欢，望您购买VIP章节或正版纸质书。
        +本书仅供试阅，版权归原作者/网站/出版社所有，请勿用于任何商业用途～
        +★☆更多校对、精校版电子书下载及阅读敬请访问：★☆
        +——阡陌居：www.1000qm.vip
        ===============================================================



        DOC;

        $content = $opInfo . trim($content) . $opInfo;
    }
}
