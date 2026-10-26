<?php

namespace App\Service;

use App\Util\Util;
use App\Util\Console\Show;
use App\Util\Console\Color;
use App\Util\ChapterAnalyzer;
use App\Exception\AppException;
use Inhere\Console\Util\Interact;

class DuplTextFinder
{
    /**
     * 高频字或标点
     *
     * @var array
     */
    protected array $chars = ['的', '是', '了', '一', '，', '。'];

    /**
     * 每次截取的结尾标点
     *
     * @var array
     */
    protected array $ends = ['。', '！', '？', '…'];

    /**
     * 筛选截取内容时限定的最小长度
     *
     * @var int
     */
    protected int $extractMinLen = 20;

    /**
     * 认定为连续段落的行号差阈值
     *
     * @var int
     */
    protected int $seqLnThreshold = 3;

    /**
     * 内容长度超过此值时不直接打印展示
     *
     * @var int
     */
    protected int $strlenLimit = 30000;

    /**
     * 记录行号所在的章节，结构为 [['行号 1' => '章节标题 1'], ['行号 2' => '章节标题 2']...]
     *
     * @var array
     */
    protected array $lineChapterMap = [];

    protected array $duplicateChapters = [];

    public function findDuplText(): void
    {
        chdir(BOOK_DIR);

        while (true) {
            $filename = $this->fileOptions();

            $tempFile = $this->prepareTempFile($filename);

            if (!$this->checkDuplicateChapters()) {
                if (is_file($tempFile)) {
                    unlink($tempFile);
                }

                if (!$this->restart()) { // 此处不继续就停止整个文件的检测
                    break;
                }
                continue;
            }

            $sortBy = $this->sortByOptions();

            $charsSlices = $this->extractSlices($tempFile);

            $result = $this->findDuplSlices($charsSlices);

            $this->sortResult($result, $sortBy);

            if (is_file($tempFile)) {
                unlink($tempFile);
            }

            $this->outputResult($result);

            while ($this->resort($result)) {
                continue;
            }

            $charsSlices = null;
            $result = null;

            if (!$this->restart()) {
                break;
            }
        }
    }

    protected function fileOptions(): string
    {
        $files = Util::globOnlyFiles();
        if (!$files) {
            throw new AppException('books 文件夹中没有 txt 文件');
        }

        $selection = Interact::select('选择需要查重的文件：', $files, '0', false);

        return $files[$selection];
    }

    /**
     * 检查重复章节名并阻断流程询问用户
     *
     * @return bool
     */
    protected function checkDuplicateChapters(): bool
    {
        if (empty($this->duplicateChapters)) {
            return true;
        }

        Show::warnWithNL('【警告】检测到以下重复的章节名：');

        $jsonOutput = Util::jsonEncode($this->duplicateChapters);
        Show::writeWithNL(Color::yellow($jsonOutput));

        Show::primaryWithNL('如上有疑似整章重复的内容，建议先自行检查并修复文档中的重复章节结构。');

        // 询问用户是否继续
        return (bool)Interact::select(
            '是否已经检查上面显示的重复章节标题，继续进行下一步（重复段落检测）？',
            ['否，终止当前文件的检测', '是，继续下一步'],
            '0',
            false
        );
    }

    protected function getSortFunctions(): array
    {
        return [
            '按出现位置排序' => fn($a, $b) => $a['行号'][0]['实际行号'] <=> $b['行号'][0]['实际行号'],
            '字数多的往后放' => fn($a, $b) => [mb_strlen($a['内容']), $a['次数']] <=> [mb_strlen($b['内容']), $b['次数']],
            '重复次数多的往后放' => fn($a, $b) => [$a['次数'], mb_strlen($a['内容'])] <=> [$b['次数'], mb_strlen($b['内容'])],
        ];
    }

    protected function sortByOptions(): string
    {
        Show::primaryWithNL("【提示】建议可以先选择默认的“按出现位置排序”\n"
            . "然后观察检测出来的相邻段落行号是否【连续】\n"
            . '一般重复的章节内容会有明显的【连续段落】被检测出来');

        $sortOptions = array_keys($this->getSortFunctions());
        $choice = (int)Interact::select('选择排序方式：', $sortOptions, '0', false);
        Show::showSelectedOpt($choice, $sortOptions);

        return $sortOptions[$choice];
    }

    protected function prepareTempFile(string $filename): string
    {
        Show::primaryWithNL('开始检测……');

        $tempDir = BOOK_FIX_DIR . '/duplTemp';
        if (!is_dir($tempDir)) {
            if (!mkdir($tempDir, 0777, true) && !is_dir($tempDir)) {
                throw new AppException("无法创建临时目录: {$tempDir}");
            }
        }

        // 统一格式，并且记录行号所在的章节
        $tempFile = $tempDir . "/{$filename}";
        $content = file_get_contents(BOOK_DIR . "/{$filename}");
        Util::changeEncodingAndNewLineType($content);
        $this->lineChapterMap = ChapterAnalyzer::getLineChapterMap($content);
        $this->duplicateChapters = ChapterAnalyzer::getDuplicateChapters($content);
        file_put_contents($tempFile, $content);

        return $tempFile;
    }

    protected function getChapterTitleByLine(int $lineNum): string
    {
        return $this->lineChapterMap[$lineNum] ?? '未知章节';
    }

    /**
     * 简单在每个段落中分组截取 chars 字符到 ends 字符之间的内容
     * 寻找其中最长的部分，同时限定截取内容的长度下限
     *
     * @param string $tempFile
     * @return array [$char => [$slice => [$lineNum, ...], $slice => [$lineNum, ...]...]...]
     */
    protected function extractSlices(string $tempFile): array
    {
        $charsSlices = [];
        $lineKey = 0;

        $lines = file($tempFile);
        $totalLines = count($lines);

        foreach ($lines as $line) {
            $lineKey++;

            // 每 10000 行打印进度信息
            if ($lineKey % 10000 === 0) {
                Show::block("已处理：$lineKey/$totalLines 行");
            }

            if (!Util::multiStrContains($line, array_merge($this->ends, $this->chars))) {
                continue;
            }

            // 同时存一份完整行
            $fullLine = Util::trimUnicodeChars($line, " 　   \t\f\n");
            if (mb_strlen($fullLine) > $this->extractMinLen) {
                $charsSlices[''][$fullLine][] = $lineKey;
            }

            // 分字符检测，如果某些作者把人名之类的换一换再复制粘贴，也同样可以查出
            // 这里暂时存了多份冗余数据，取决于 chars 的元素数量，如果文本太大，需要考虑优化写法
            foreach ($this->chars as $char) {
                $firstPosition = mb_strpos($line, $char);
                if ($firstPosition === false) {
                    continue;
                }

                $endPositions = [];
                foreach ($this->ends as $end) {
                    $endPositions[] = (int)mb_strrpos($line, $end);
                }

                $endPosition = max($endPositions);
                if (($endPosition - $firstPosition) < $this->extractMinLen) {
                    continue;
                }

                // 截取内容不包含最后的标点，可以覆盖更多的重复内容
                $slice = mb_substr($line, $firstPosition, $endPosition - $firstPosition);
                $charsSlices[$char][$slice][] = $lineKey;
            }
        }

        $lines = null;

        return $charsSlices;
    }

    protected function findDuplSlices(array $charsSlices): array
    {
        $result = [];
        foreach ($charsSlices as $charSlices) {
            foreach ($charSlices as $slice => $lineNums) {
                $sliceCount = count($lineNums);
                if ($sliceCount == 1) {
                    continue;
                }

                $lineDetails = [];
                foreach ($lineNums as $lineNum) {
                    $lineDetails[] = [
                        '实际行号' => $lineNum,
                        '所在章节' => $this->getChapterTitleByLine($lineNum),
                    ];
                }

                $result[] = [
                    '内容' => html_entity_decode($slice),
                    '次数' => $sliceCount,
                    '行号' => $lineDetails,
                ];
            }

            $charSlices = null;
        }

        // 按“次数”从高到低排序，确保重复次数多的优先处理
        usort($result, function ($a, $b) {
            return $b['次数'] <=> $a['次数'];
        });

        $finalResult = [];
        $seenLineNums = []; // 跟踪已知的行号

        foreach ($result as $item) {
            // 计算当前片段中，还未被记录的行号
            $currentLineNums = array_column($item['行号'], '实际行号');
            $uniqueLineNums = array_diff($currentLineNums, array_keys($seenLineNums));

            // 如果过滤后，当前片段仍有独占的行号
            if (!empty($uniqueLineNums)) {
                $finalResult[] = $item;
                // 将这些新发现的独占行号加入到“已知行号”中
                $seenLineNums += array_flip($uniqueLineNums);
            }
        }

        // 标记连续段落
        if (!empty($finalResult)) {
            $lineNumMap = [];
            foreach ($finalResult as $index => $item) {
                if (!empty($item['行号'])) {
                    $lineNumMap[$item['行号'][0]['实际行号']] = $index;
                }
            }

            $sortedLineNums = array_keys($lineNumMap);
            sort($sortedLineNums, SORT_NUMERIC);

            $i = 0;
            $count = count($sortedLineNums);
            while ($i < $count) {
                $j = $i;
                while (
                    $j + 1 < $count
                    // 如果相邻的行数小于阈值，就算成连续段落
                    && ($sortedLineNums[$j + 1] - $sortedLineNums[$j] <= $this->seqLnThreshold)
                ) {
                    $j++;
                }

                if ($j > $i) {
                    for ($k = $i; $k <= $j; $k++) {
                        $finalResultIndex = $lineNumMap[$sortedLineNums[$k]];
                        $sequenceNumber = $k - $i + 1;
                        $finalResult[$finalResultIndex]['行号'][0]['连续段落'] = "上下文的第【{$sequenceNumber}】个【连续段落】";
                    }
                }
                $i = $j + 1;
            }
        }

        return $finalResult;
    }

    protected function sortResult(array &$result, string $sortBy): void
    {
        $sortFunctions = $this->getSortFunctions();

        if (isset($sortFunctions[$sortBy])) {
            usort($result, $sortFunctions[$sortBy]);
        }
    }

    protected function outputResult(array $result): void
    {
        if (!$result) {
            Show::successWithNL('没有找到重复段落');
            return;
        }

        echo PHP_EOL;
        Show::clearScreen();

        Show::primaryWithNL('重复段落如下：');
        $reportContent = Util::getArrStrWithIndex($result);
        file_put_contents(REPORT_DIR . '/重复段落检测结果.txt', $reportContent);
        if (Util::isFromGUI() && mb_strlen($reportContent) > $this->strlenLimit) {
            Show::warnWithNL("检测结果过长，请使用其他编辑器打开 logs/report 文件夹中的【重复段落检测结果.txt】查看报告");
        } else {
            Show::writeWithNL(Color::yellow($reportContent));

            Show::primary('可以选中上方任意的文字内容，右键复制，到编辑器中搜索查看');
            Show::primaryWithNL('如果结果过长，无法完整显示，可以到 logs/report 文件夹中的【重复段落检测结果.txt】查看报告');
        }

        $count = count($result);
        Show::successWithNL("检测完成，共有 {$count} 处重复段落");
    }

    protected function resort(array &$result): bool
    {
        if (!$result) {
            return false;
        }

        $shouldResort = (bool)Interact::select(
            '是否需要对结果重新排序？',
            ['否', '是'],
            '0',
            false
        );

        if ($shouldResort) {
            $sortBy = $this->sortByOptions();
            $this->sortResult($result, $sortBy);
            $this->outputResult($result);
        }

        return $shouldResort;
    }

    protected function restart(): bool
    {
        return (bool)Interact::select(
            '是否继续下一轮：',
            ['否，退出脚本', '是'],
            '1',
            false
        );
    }
}
