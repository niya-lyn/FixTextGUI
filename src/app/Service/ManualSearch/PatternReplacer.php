<?php

namespace App\Service\ManualSearch;

use App\Util\Util;
use App\Util\Console\Show;
use App\Util\Console\Color;
use Inhere\Console\Util\Interact;

class PatternReplacer
{
    public function __construct(
        protected BookMapManager $bookMapManager,
        protected PatternMatcher $matcher
    ) {}

    /**
     * @return bool 返回 true 时需要从头重新读取规则列表
     */
    public function doPatternReplace(
        string $file,
        array &$usefulPatterns,
        array $selectKeys,
        int $patternCount
    ): bool {
        $this->backupFiles($file);
        $selectedPatterns = array_intersect_key($usefulPatterns, array_flip($selectKeys));

        while (true) {
            $this->showReplaceInfo($selectedPatterns, $selectKeys, $patternCount);

            $selection = $this->confirmOperation();
            if ($selection == 1) {
                return false;
            } elseif ($selection == 2) {
                return true;
            }

            $selectedMarks = array_column($selectedPatterns, "mark");
            $this->bookMapManager->mergeMarksToBookMap($selectedMarks, $file);
            $this->executeReplace($file, $usefulPatterns, $selectKeys);

            Show::successWithNL('已完成修改，请到 BC 或“文件全局搜索”中确认此次修改结果');

            $nextAction = $this->selectNextAction();
            if ($nextAction == 0) {
                return false;
            } elseif ($nextAction == 2) {
                return true;
            }

            $this->matcher->reloadUsefulPatterns($usefulPatterns);
        }
    }

    protected function backupFiles(string $file): void
    {
        // 每次替换前在 BOOK_FIX_DIR 备份前一次的结果文件，以备误操作后恢复
        // 然后用当前文件覆盖 BOOK_BAK_DIR 的备份文件
        copy(BOOK_BAK_DIR . "/{$file}", BOOK_FIX_DIR . "/{$file}");
        copy($file, BOOK_BAK_DIR . "/{$file}");
    }

    protected function showReplaceInfo(array $selectedPatterns, array $selectKeys, int $patternCount): void
    {
        $selectedMarks = array_column($selectedPatterns, "mark");
        $patternInfo = implode(" & ", $selectedMarks);
        $replaceTotalCount = array_sum(array_column($selectedPatterns, "count"));
        $progressKey = max($selectKeys) + 1;

        Show::writeWithNL([
            Color::yellow("当前所选规则：{$patternInfo}"),
            Color::red1("预计替换总次数：【{$replaceTotalCount}】"),
            Color::note("进度：（{$progressKey}/{$patternCount}）"),
        ]);
    }

    protected function confirmOperation(): int
    {
        $opts = [
            '执行当前所选规则',
            '跳过当前所选规则',
            '刷新当前规则列表，排除【已执行】规则',
        ];
        $selection = (int)Interact::select('确认操作：', $opts, '0', false);
        Show::showSelectedOpt($selection, '', false);

        return $selection;
    }

    protected function selectNextAction(): int
    {
        $opts = [
            '不再次执行，继续进行下一项替换',
            '再次执行当前所选规则',
            '刷新当前规则列表，排除【已执行】规则',
        ];
        $selection = (int)Interact::select(
            "选择下一步操作：\n（如对规则文件有修改，可选择再次执行以实时应用修改后的规则）",
            $opts,
            '0',
            false
        );
        Show::showSelectedOpt($selection, '', false);

        return $selection;
    }

    protected function executeReplace(string $file, array &$usefulPatterns, array $selectKeys): void
    {
        $content = file_get_contents($file);

        foreach ($selectKeys as $sk) {
            $pattern = $usefulPatterns[$sk];
            Util::doRegexReplace($pattern, $content);
            $usefulPatterns[$sk]['status'] = 1;
        }

        file_put_contents($file, $content);
    }
}
