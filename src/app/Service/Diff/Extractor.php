<?php

namespace App\Service\Diff;

use App\Service\Map;
use Exception;
use App\Util\Util;
use App\Util\Config;
use App\Util\PatchAnalyzer;
use App\Trait\FileWalkerTrait;

class Extractor
{
    use FileWalkerTrait;

    protected $reports = []; // 每一项都是单本书的替换报告

    protected array $beforeKeywords = [];
    protected array $afterKeywords  = [];

    protected Option $option;

    public function __construct(Option $option)
    {
        $this->beforeKeywords = Config::getDiff('beforeKeywords');
        $this->afterKeywords  = Config::getDiff('afterKeywords');
        $this->option = $option;
    }

    /**
     * 生成书籍专有词条
     *
     * @param string $bookFixDir
     * @return void
     * @throws Exception
     */
    public function generateBookMaps($bookFixDir = BOOK_FIX_DIR)
    {
        $this->setInWalkFunc(function ($bookFixDir, $bookFixFile) {
            $this->printFinished = false;

            $bookName = Util::getFilename($bookFixFile);
            $bookFixFile = $bookFixDir . '/' . $bookFixFile;
            $bookFile = str_replace(BOOK_FIX_DIR, BOOK_DIR, $bookFixFile);
            if (!is_file($bookFile)) { // 文件不存在时不处理
                return;
            }

            $patchFile = "【专有词条】{$bookName}";
            $patchFile = "{$bookFixDir}/{$patchFile}.patch";
            $bookWords = $this->genDiffWordsMap($patchFile, $bookFixFile, $bookFile);

            // 同时检查并写入单独的书籍词库文件
            $origBookName = Util::removeEpubMergePrefix($bookName);
            $this->mergeToBookMapFile($origBookName, $bookWords);
        });

        $this->walkFiles($bookFixDir);
    }

    /**
     * @param $bookName
     * @param $bookWords
     * @return bool|void
     */
    protected function mergeToBookMapFile($bookName, $bookWords)
    {
        if (!$bookWords || !isset($bookWords[0]['before'])) {
            return false;
        }

        if (!is_dir(Map::getMapFilepath('书籍专有替换词库'))) {
            return false;
        }

        $bookMapFile = Map::getBookMapFileWithTags($bookName);
        if (!$bookMapFile) { // 无文件则新建
            $bookMapFile = Map::getMapFilepath("书籍专有替换词库/{$bookName}.php");
            $content = "<?php\n\nreturn [\n    'bookNotes' => [\n    ],\n];\n";
            file_put_contents($bookMapFile, $content);
        }

        foreach ($bookWords as &$word) {
            $word['before'] = str_replace('"', '\"', $word['before']);  // html 代码中的引号需要转义
            $word['after']  = str_replace('"', '\"', $word['after']);   // html 代码中的引号需要转义
        }
        unset($word);

        $mergeContent = '';
        if ($this->option->addCurrentTime) {
            $mergeContent = "    /* 新增下列词条的时间点：" . Util::getTimeStr('', true) . " */\n";
        }
        $mergeContent .= Util::getWordsPrintStr($bookWords);
        $mergeContent = preg_replace('/^/m', '    ', $mergeContent);
        $mergeContent = rtrim($mergeContent) . "\n";

        $content = file_get_contents($bookMapFile);

        if (!str_contains($content, "'bookNotes' => ")) {
            $content = str_replace("\n];", "\n    'bookNotes' => [\n    ],\n];", $content);
        }

        $insertPos = $this->findBookNotesInsertPosition($content);
        if ($insertPos === false) {
            return false;
        }

        $content = substr($content, 0, $insertPos) . $mergeContent . substr($content, $insertPos);
        file_put_contents($bookMapFile, $content);
    }

    /**
     * 在 bookNotes 数组中找到最后一个 before/after 词条所在行的末尾位置
     * 若无词条则返回 bookNotes 开头 [ 之后的下一行位置
     */
    protected function findBookNotesInsertPosition($content)
    {
        if (!preg_match("/'bookNotes'\s*=>\s*\[/", $content, $m, PREG_OFFSET_CAPTURE)) {
            return false;
        }
        $sectionStart = $m[0][1] + strlen($m[0][0]);

        $sectionEnd = $this->findClosingBracket($content, $sectionStart);
        if ($sectionEnd === false) {
            return false;
        }

        $sectionContent = substr($content, $sectionStart, $sectionEnd - $sectionStart);
        $lines = explode("\n", $sectionContent);

        // 逐行查找最后一个包含 ['before' ... 'after' 的行
        $lastEntryLine = -1;
        foreach ($lines as $i => $line) {
            if (str_contains($line, "['before'") && str_contains($line, "'after'")) {
                $lastEntryLine = $i;
            }
        }

        if ($lastEntryLine >= 0) {
            $offset = $sectionStart;
            for ($i = 0; $i <= $lastEntryLine; $i++) {
                $offset += strlen($lines[$i]) + 1; // +1 对应 \n
            }
            return $offset;
        }

        // 无现有词条，插入到 [ 后的下一行起始处
        $newlinePos = strpos($content, "\n", $sectionStart);
        return $newlinePos !== false ? $newlinePos + 1 : $sectionStart;
    }

    /**
     * 从 $startPos 开始，找到与已打开的 [ 匹配的闭合 ] 的位置
     * 正确跳过单/双引号字符串内的括号
     */
    protected function findClosingBracket($content, $startPos)
    {
        $depth = 1;
        $pos = $startPos;
        $len = strlen($content);
        $inString = false;
        $stringChar = '';
        $escape = false;

        while ($pos < $len && $depth > 0) {
            $char = $content[$pos];
            if ($escape) {
                $escape = false;
            } elseif ($inString) {
                if ($char === '\\') {
                    $escape = true;
                } elseif ($char === $stringChar) {
                    $inString = false;
                }
            } else {
                if ($char === '"' || $char === "'") {
                    $inString = true;
                    $stringChar = $char;
                } elseif ($char === '[') {
                    $depth++;
                } elseif ($char === ']') {
                    $depth--;
                }
            }
            if ($depth > 0) $pos++;
        }

        return $depth === 0 ? $pos : false;
    }

    protected function getBookCommentSection(string $content): string
    {
        preg_match('/.*\'after\'.*?,\n([\n]+.*?)(?=^    \],)/ms', $content, $matches);
        if (isset($matches[1]) && $matches[1]) {
            return $matches[1];
        }

        return '';
    }

    /**
     * 生成每轮校正的替换次数报告
     *
     * @param string $bookDir
     * @param bool $enablePrint 是否打印文件进度
     * @return void
     * @throws Exception
     */
    public function genReplaceCountReport(string $bookDir = BOOK_DIR, bool $enablePrint = true): void
    {
        if (!$enablePrint) {
            $this->disablePrint();
        }

        $this->setInWalkFunc(function ($bookDir, $bookFile) {
            $bookName = Util::getFilename($bookFile);
            $bookFile = $bookDir . "/" . $bookFile;
            $bookBakFile = str_replace(BOOK_DIR, BOOK_BAK_DIR, $bookFile);
            $patchFile = "【替换次数报告】{$bookName}";
            $reportDir = str_replace(BOOK_DIR, REPORT_DIR, $bookDir);
            $patchFile = "{$reportDir}/{$patchFile}.patch";
            $bookWords = $this->genDiffWordsMap(
                $patchFile,
                $bookBakFile,
                $bookFile,
                $this->option->contextLen,
                true,
            );

            $reportArr = [];
            $splitMark = '【FixText 替换为】';
            $charsToTrim = '　，。“”…！？、';
            foreach ($bookWords as $word) {
                $before = $word['before'];
                $after = $word['after'];

                // 判断是否需要移除首尾部字符，以修剪字符形态
                list($before, $after) = $this->customTrimDiff(
                    $this->option->removeLOrRChar,
                    $this->option->contextLen,
                    $before,
                    $after
                );

                if ($this->option->trimPunctuations) {
                    $before = Util::trimUnicodeChars($before, $charsToTrim);
                    $after = Util::trimUnicodeChars($after, $charsToTrim);
                }

                if (!$this->option->getMultiLineContent) {
                    if (str_contains($before, "\\n") || str_contains($after, "\\n")) {
                        continue;
                    }
                }

                $reportArr[] = $before . $splitMark . $after;
            }

            $this->writeToReports($reportArr, $splitMark, $patchFile);
        });

        $this->walkFiles($bookDir);

        $this->mergeReportsToTempMapFile();
    }

    protected function customTrimDiff(int $rmLOrRChar, int $contextLen, string $before, string $after): array
    {
        $beforeLen = mb_strlen($before);
        $afterLen = mb_strlen($after);
        $contextLimitLen = $contextLen * 2 - 1;

        if ($rmLOrRChar > 0) { // 移除首部
            $before = $beforeLen > $contextLimitLen ? mb_substr($before, $rmLOrRChar) : $before;
            $after = $afterLen > $contextLimitLen ? mb_substr($after, $rmLOrRChar) : $after;
        } else if ($rmLOrRChar < 0) { // 移除尾部
            $before = $beforeLen > $contextLimitLen ? mb_substr($before, 0, $rmLOrRChar) : $before;
            $after = $afterLen > $contextLimitLen ? mb_substr($after, 0, $rmLOrRChar) : $after;
        }

        return [$before, $after];
    }

    protected function writeToReports(
        array $reportArr,
        string $splitMark,
        string $patchFile,
    ): void {
        $reportArr = array_count_values($reportArr);
        $replaceTotalCount = array_sum($reportArr);

        // 只汇报替换次数大于下限值的内容
        $replaceCountThreshold = $this->option->replaceCountThreshold;
        $reportArr = array_filter($reportArr, fn($v) => $v > $replaceCountThreshold);
        $reportTotalCount = array_sum($reportArr);

        arsort($reportArr);

        $patchFilename = Util::getFilename($patchFile);
        $result = <<<DOC
            // {$patchFilename}

            // 总替换次数：【{$replaceTotalCount}】 | 重复次数大于 {$replaceCountThreshold} 的总替换次数：【{$reportTotalCount}】
            // 下方只显示替换次数大于 {$replaceCountThreshold} 的内容

        DOC;
        $reportArrCount = count($reportArr);
        $reportNum = 1;
        foreach ($reportArr as $reportKey => $count) {
            list($before, $after) = explode($splitMark, $reportKey);

            // 使用关键字筛选
            if ($this->option->filterKeywords) {
                if (!$this->customKeywordsFilter($before, $after)) {
                    continue;
                }

                // 交换方向，为恢复修改做准备……
                list($before, $after) = [$after, $before];
            }

            $before  = str_replace('"', '\"', $before); // html 代码中的引号需要转义
            $after   = str_replace('"', '\"', $after);  // html 代码中的引号需要转义
            $info = "替换次数: 【{$count}】 | 序号：【{$reportNum}/{$reportArrCount}】";
            $result .= Util::getWordsPrintStr(compact("before", "after"), $info);
            $reportNum++;
        }

        $this->reports[] = $result;
    }

    protected function mergeReportsToTempMapFile()
    {
        $wholeMap = "";
        foreach ($this->reports as $reportContent) {
            $wholeMap .= "\n    // ===========\n" . $reportContent;
        }

        $result = "<?php\n\n";
        $result .= "\$tempMap = [\n";
        $result .= $wholeMap;
        $result .= "];\n";
        file_put_contents(TEMP_MAP_FILE, $result);
    }

    /**
     * 寻找一些包含特定关键字的 diff 内容
     * 把一些个人认为多余的修改进行还原
     *
     * @param string $before
     * @param string $after
     * @return bool
     */
    protected function customKeywordsFilter(string $before, string $after): bool
    {
        foreach ($this->beforeKeywords as $bw) {
            if (str_contains($before, $bw) && !str_contains($after, $bw)) {
                return true;
            }
        }

        foreach ($this->afterKeywords as $aw) {
            if (str_contains($after, $aw) && !str_contains($before, $aw)) {
                return true;
            }
        }

        return false;
    }

    /**
     * 生成 patch 并转换成含 before 及 after 字段的 map
     *
     * @param string $patchFilepath patch 文件的全路径
     * @param string $beforeFilepath 更改前文件的全路径
     * @param string $afterFilepath 更改后文件的全路径
     * @param int $contextLen 截取的差异字符串上下文长度
     * @param bool $trimOrigStr 如不移除首尾空格，可保留原文缩进，避免多改误改
     * @return array
     * @throws Exception
     */
    protected function genDiffWordsMap(
        string $patchFilepath,
        string $beforeFilepath,
        string $afterFilepath,
        int $contextLen = 5,
        bool $trimOrigStr = false,
    ): array {
        // 目标目录不存在时递归创建
        $patchFileDir = dirname($patchFilepath);
        if (!is_dir($patchFileDir)) {
            mkdir($patchFileDir, 0777, true);
        }

        Util::generatePatch($beforeFilepath, $afterFilepath, $patchFilepath);
        // copy($patchFilepath, $patchFilepath . ".txt");

        list($befores, $afters) = (new PatchAnalyzer)->getDiffFromPatchFile($patchFilepath);

        $resultMap = [];
        foreach ($befores as $k => $before) {
            $after = $afters[$k];

            // 若存在跨行内容，则直接使用整行，而不使用截取后的结果
            if (!str_contains($before, "\\n") && !str_contains($after, "\\n")) {
                $diffRet = Util::extractStrDiff($before, $after, $contextLen);
                if (!$diffRet) {
                    continue;
                }

                list($before, $after) = $diffRet;
            }

            if ($trimOrigStr) {
                $before = trim(Util::trimUnicodeChars($before, " 　"));
                $after = trim(Util::trimUnicodeChars($after, " 　"));
            }

            if (!$before || !$after) {
                continue;
            }

            $origBefore = $before;
            $origAfter = $after;
            $resultMap[] = compact("before", "after");

            // 另存一份移除了 html 标签的备用
            if ($this->option->addHtmlStrippedCopy) {
                $before = $this->stripHtmlTag($before);
                $after = $this->stripHtmlTag($after);
                if ($origBefore != $before || $origAfter != $after) {
                    $resultMap[] = compact("before", "after");
                }
            }
        }

        return $resultMap;
    }

    protected function stripHtmlTag(string $str): string
    {
        if (!Util::multiStrContains($str, ["<", ">"])) {
            return trim(Util::trimUnicodeChars($str, " 　"));
        }

        $str = strip_tags($str);

        // 下列的两个判断实际无作用
        // 是为了应对之前并不是直接使用 strip_tags 的写法
        $start = mb_strpos($str, ">");
        $start = $start === false ? 0 : min(mb_strlen($str) - 1, $start + 1);

        $end = mb_strrpos($str, "<");
        $end = ($end === false || $end < $start) ? mb_strlen($str) : $end;

        return trim(mb_substr($str, $start, max($end - $start, 1)));
    }
}
