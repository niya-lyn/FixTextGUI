<?php

namespace App\Service\ManualSearch;

use App\Exception\AppException;
use App\Util\Util;
use App\Service\EpubFixer;
use App\Util\Console\Show;
use App\Util\Console\Color;
use Inhere\Console\Util\Interact;
use App\Service\PatternFileLoader;
use App\Service\ManualSearch\PatternValidator;
use App\Service\ManualSearch\PatternMatcher;
use App\Service\ManualSearch\PatternFormatter;
use App\Service\ManualSearch\PatternReplacer;
use App\Service\ManualSearch\BookMapManager;

// 主要用于处理一些常见且自动替换时容易漏改的混淆字
// 通过人工判断每条正则的修改结果
// 仅支持单文件修改
class ManualSearcher
{
    protected PatternValidator $validator;
    protected PatternMatcher $matcher;
    protected PatternFormatter $formatter;
    protected PatternReplacer $replacer;
    protected BookMapManager $bookMapManager;

    public function process(): void
    {
        $this->initServices();

        while (true) {
            (new EpubFixer())->mergeAllEpubText();

            chdir(BOOK_DIR);
            $file = $this->getSingleFile();

            copy($file, BOOK_BAK_DIR . "/{$file}");

            $patterns = PatternFileLoader::loadPatterns();
            $this->validator->validate($patterns);

            $usefulPatterns = $this->getUsefulPatterns($file, $patterns);
            $restart = $this->selectPatterns($usefulPatterns, $file);

            if (!$restart) {
                Show::success('【已完成所有规则替换】', true);
            }
        }
    }

    protected function initServices(): void
    {
        $this->bookMapManager = new BookMapManager();
        $this->validator = new PatternValidator();
        $this->matcher = new PatternMatcher();
        $this->formatter = new PatternFormatter();
        $this->replacer = new PatternReplacer($this->bookMapManager, $this->matcher);
    }

    /**
     * @throws AppException
     */
    protected function getSingleFile(): string
    {
        $files = Util::globOnlyFiles();
        if (count($files) != 1) {
            throw new AppException('此命令只支持对单个文本文件的处理，请确保 books 文件夹中有且仅有一个 txt 文件。');
        }

        return $files[0];
    }

    /**
     * @throws AppException
     */
    protected function getUsefulPatterns(string $file, array $patterns): array
    {
        $sort = $this->getSortOption();

        Show::opStart('检测文件中匹配的检索规则');
        // 根据书籍专有词库中的 mark 记录，排除已执行过的规则
        $this->bookMapManager->excludeSearchedMarks($file, $patterns);

        $usefulPatterns = $this->matcher->findUsefulPatterns($file, $patterns);
        if (empty($usefulPatterns)) {
            throw new AppException('该文件匹配不到任意一条规则，无需修改');
        }

        $this->matcher->sortPatterns($usefulPatterns, $sort);
        Show::opEnd();

        return $usefulPatterns;
    }

    protected function getSortOption(): int
    {
        $opts = [
            '按照【手动检索规则表】文件中的规则所在位置进行显示',
            '按照【预计替换次数】从少到多的顺序显示各项匹配规则',
            '根据每条规则中的【color】属性按颜色分组并排序显示',
        ];
        $desc = "请选择【规则列表】的显示顺序：\n"
            . "推荐先用【1】或【2】进行排序，然后输入【连续规则索引的数字范围】，"
            . "先批量处理一些替换次数少的规则\n"
            . "可看【手动检索规则表】文件开头关于 color 的说明，"
            . "使用不同的颜色给规则做一些优先级区分\n";

        $sort = (int)Interact::select($desc, $opts, "1", false);
        Show::showSelectedOpt($sort, $opts);

        return $sort;
    }

    /**
     * @throws AppException
     */
    protected function selectPatterns(array $usefulPatterns, string $file): bool
    {
        $selectKey = 0;
        $patternCount = count($usefulPatterns);
        $usefulPatternsIdxes = range(0, $patternCount - 1);

        while ($selectKey < $patternCount) {
            $this->matcher->reloadUsefulPatterns($usefulPatterns);
            $this->displayPatternList($usefulPatterns, $selectKey, $file);

            read_select_keys:
            $this->showInputPrompt();

            [$selectKeys, $showPatternInfo] = $this->readSelectKeys($selectKey);

            if (array_diff($selectKeys, $usefulPatternsIdxes)) {
                Show::warnWithNL('输入的索引值不在匹配规则的范围内，请重试');
                goto read_select_keys;
            }

            if ($showPatternInfo) {
                $this->showPatternDetails($usefulPatterns[$selectKeys[0]]);
                goto read_select_keys;
            }

            $restart = $this->replacer->doPatternReplace(
                $file,
                $usefulPatterns,
                $selectKeys,
                $patternCount
            );

            if ($restart) {
                return true;
            }

            $selectKey = $this->getNextSelectKey($selectKeys, $usefulPatterns);
        }

        return false;
    }

    protected function displayPatternList(array $usefulPatterns, int $selectKey, string $file): void
    {
        Show::writeWithNL(
            $this->formatter->highlightUsefulPatterns($usefulPatterns, $selectKey)
        );

        $curPattern = $usefulPatterns[$selectKey];

        Show::writeWithNL(
            Color::red1("【经检测《{$file}》中匹配的规则列表如上】")
        );
        Show::writeWithNL([
            Color::yellow('当前时间：' . Util::getTimeStr()),
            Color::note("即将按顺序执行（索引-{$selectKey}）："),
            Color::yellow("{$curPattern['mark']} | 预计替换次数【{$curPattern['count']}】")
        ]);
    }

    protected function showInputPrompt(): void
    {
        Show::opTitle(
            "请输入当前需要执行的规则索引（如果不输入则不调整顺序，"
                . "将执行上面那一行所示的规则，后续依次往下执行）"
        );
        Show::writeWithNL(
            "可输入单个索引数字如【1】\n"
                . "可输入按空格分隔的多个索引数字如【1 2 3】\n"
                . "可输入连续索引数字的范围如【1-3】\n"
                . "如果输入多个区间，可用逗号分隔选项，如【1-3, 10-20, 35 38 40】\n"
                . "输入单个【+】号或【+规则的索引数字】，打印对应规则的内容"
        );
    }

    protected function showPatternDetails(array $pattern): void
    {
        if (is_callable($pattern['replace'])) {
            $pattern['replace'] = "[替换函数]";
        }

        Show::primaryWithNL('规则详情：');
        Show::writeWithNL(
            "标题：\n{$pattern['mark']}\n\n"
                . "查找：\n{$pattern['search']}\n\n"
                . "替换：\n{$pattern['replace']}"
        );
    }

    protected function readSelectKeys(int $selectKey): array
    {
        $input = Interact::readln('请输入：');
        echo PHP_EOL;

        $showPatternInfo = str_starts_with($input, '+');
        $input = str_replace(['【', '】', '+'], '', $input);

        $selectKeys = [];
        if ($input != '') {
            $selectKeys = $this->getSelectKeyArr($input);
        } else if (($selectKey == 0 && $input == '') || $input === '0') {
            $selectKeys = [0];
        } else if ($input == "") {
            $selectKeys = $this->getSelectKeyArr((string)$selectKey);
        }

        return [$selectKeys, $showPatternInfo];
    }

    /**
     * 根据输入格式，将 selectKey 整理成数组
     */
    protected function getSelectKeyArr(string $str): array
    {
        $result = [];
        $str = str_replace('，', ',', $str);
        $parts = explode(',', $str);

        foreach ($parts as $part) {
            $part = trim($part);
            if (str_contains($part, '-')) {
                list($start, $end) = explode('-', $part);
                $selectKeys = range($start, $end);
            } else if (str_contains($part, ' ')) {
                $selectKeys = array_filter(explode(' ', $part), fn($v) => $v !== '');
                $selectKeys = array_values($selectKeys);
            } else {
                $selectKeys = [$part];
            }

            $result = array_merge($result, $selectKeys);
        }

        return array_values(array_unique($result));
    }

    protected function getNextSelectKey(array $selectKeys, array $usefulPatterns): int
    {
        $curKey = max($selectKeys);

        do {
            $curKey++;
        } while (
            isset($usefulPatterns[$curKey])
            && $usefulPatterns[$curKey]['status'] == 1
        );

        return $curKey;
    }
}
