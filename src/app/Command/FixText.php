<?php

namespace App\Command;

use Exception;
use App\Util\Util;
use App\Service\Map;
use App\Util\Config;
use App\Service\EpubFixer;
use App\Service\Note\ReplacementChecker;
use App\Service\TextFixer;
use App\Util\Console\Show;
use App\Util\Console\Color;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;
use Inhere\Console\Util\Interact;

class FixText extends Command
{
    protected static string $name = 'fix-text';
    protected static string $desc = '书籍校正';

    public function execute(Input $input, Output $output): void
    {
        while (true) {
            $this->process();
        }
    }

    /**
     * @throws Exception
     */
    protected function process()
    {
        // 每一次执行校正前都先自动统一文件编码和换行符
        Util::unifyAllBooksFormat();

        $useStrictMode = $this->strictModeOptions();

        $useMapsConfigIndex = 0;
        if ($useStrictMode !== 1) { // 单独使用“严格模式”时，不需要选择词库索引
            $useMapsConfigIndex = $this->useMapsOptions();
        }

        $zhuyinMode = 0;
        $splitMultiZhuyin = 0;
        if ($useMapsConfigIndex === Config::getMap('shengpiziIndex')) {
            $zhuyinMode = $this->zhuyinOptions();
            $splitMultiZhuyin = $this->splitMultiZhuyinOptions();
        }

        do {
            // 执行实际的校正任务
            $this->doFixText($useStrictMode, $useMapsConfigIndex, $zhuyinMode, $splitMultiZhuyin);
            // 获取下一步操作意图
            $restart = $this->restart();
        } while ($restart === 3); // 当 restart === 3 时，跳过配置选项，直接用当前选项重跑校正

        if ($restart === 0) {
            Show::writeWithNL('【退出脚本】', true);
        }
    }

    /**
     * 核心的校正任务
     *
     * @throws Exception
     */
    protected function doFixText(int $useStrictMode, int $useMapsConfigIndex, int $zhuyinMode, int $splitMultiZhuyin): void
    {
        Show::opStart('备份文件');
        // 自动清除 booksBak 文件夹中的残留备份文件
        Util::recursiveDelete(BOOK_BAK_DIR, false);
        Util::recursiveDelete(BOOK_FIX_DIR, false);
        // 若备份目录存在，先把 books 目录中的所有文件备份到 booksBak 目录中，
        // 并对 booksBak 文件夹中的原书籍备份文件进行预处理
        Util::recursiveCopy(BOOK_DIR, BOOK_BAK_DIR);
        Show::opEnd();

        (new EpubFixer())->mergeAllEpubText();

        Show::opStart(' booksBak 预处理');
        if (
            !TextFixer::isNoPreprocessFix()    // 先写死……
            && !TextFixer::isTempFix()         // 临时校对表替换时无需预处理
            && $useStrictMode !== 1            // 严格模式替换时无需预处理
        ) {
            $textFixer = TextFixer::getInstance(true);
            $textFixer->setPreprocessing(true);
            $textFixer->setUseStrictMode($useStrictMode);
            $textFixer->setUseMapsConfigIndex($useMapsConfigIndex);
            $textFixer->setZhuyinMode($zhuyinMode);
            $textFixer->setSplitMultiZhuyin($splitMultiZhuyin);
            $textFixer->fixBooks(BOOK_BAK_DIR);
        }
        Show::opEnd();

        // 对 books 文件夹中的书籍进行校正
        Show::opStart(' books 校正', 'note');
        $textFixer = TextFixer::getInstance(true);
        $textFixer->setPreprocessing(false);
        $textFixer->setUseStrictMode($useStrictMode);
        $textFixer->setUseMapsConfigIndex($useMapsConfigIndex);
        $textFixer->setZhuyinMode($zhuyinMode);
        $textFixer->setSplitMultiZhuyin($splitMultiZhuyin);
        $textFixer->fixBooks(BOOK_DIR);
        Show::opEnd('', 'note');

        // 备份全量修改的书籍文件，用于后续自动生成书籍专有词条
        Util::recursiveCopy(BOOK_DIR, BOOK_FIX_DIR, 'txt');

        if (REPACK_AFTER_FIX) {
            (new EpubFixer())->bulkSplitEpubs();
        }

        // 清除该轮校正的词库设置
        Map::resetAll();
    }

    /**
     * @throws Exception
     */
    protected function strictModeOptions(): int
    {
        if (TextFixer::isTempFix()) { // 先写死……
            return 0;
        }

        $danger = <<<DOC
        ！！！【注意事项】使用该脚本进行【每一轮校正】前，都会自动清除 booksBak 的备份文件！！！
        ！！！请确认 booksBak 文件夹内已经没有所需要的备份文件！！！
        DOC;
        Show::writeWithNL(Color::backRed($danger));

        Show::opTitle('请选择是否单独使用“严格模式”进行校正');
        $msg = <<<DOC
        若使用“严格模式”，将对某些口语化（以及不符合常规校对标准）的用词和表达进行更进一步的修正。

        目前在“严格模式”中，额外修正的词汇包括但不限于：
        <primary>不曾想 涉及到 来自于 近乎于 其它 ×地一声 ×地一下 滋滋 门栓（拴） 涛涛</primary>

        额外修正的正则包括但不限于：
        <primary>将“出乎意料之外”的写法，强制规范为“出乎意料”</primary>

        <info>可以随时自行调整“自定义词库”的【strictMap】和【strictRegexMap】变量中使用的词条和正则</info>

        输入 <primary>0</primary> 跳过“严格模式”，选用其他的词库进行校正。
        输入 <primary>1</primary> 则启用（注意此时不会进行在“严格模式”以外的词条和正则的修正）。
        DOC;
        Show::writeWithNL($msg);
        Show::warning('如果不认为上面列出的词汇写法有问题，或者想选择其他词库，输入 0 即可。');
        Show::warning('如果本次选择了 1，下一轮则可选 0 跳过，一般只需进行一次“严格模式”校正。');
        $useStrictMode = (int)Interact::readln('请输入：');
        $info = $useStrictMode === 0 ? '不启用“严格模式”进行校正' : '单独启用“严格模式”进行校正';
        Show::showSelectedOpt($useStrictMode, $info);

        return $useStrictMode === 0 ? 0 : 1;
    }

    /**
     * @throws Exception
     */
    protected function useMapsOptions(): int
    {
        if (TextFixer::isTempFix()) { // 先写死……
            return Config::getMap('tempFixIndex');
        }

        $mapNames = array_column(Config::getMap('useMapsConfig'), 'configTitle');
        $useMapsConfigIndex = (int)Interact::select(
            '请选择校正时使用的对应词库：',
            $mapNames,
            '0',
            false
        );
        Show::showSelectedOpt($useMapsConfigIndex, $mapNames);

        return $useMapsConfigIndex;
    }

    protected function zhuyinOptions(): int
    {
        $zhuyinMode = (int)Interact::select(
            '选择注音方式：',
            [
                '每个生僻字只注音一次',
                '给文本中所有位置的生僻字注音（同一个字注音多次）',
                '每个字只注音一次，且多音字只取第一种读音',
                '所有位置都注音，且多音字只取第一种读音',
            ],
            '0',
            false
        );

        return $zhuyinMode;
    }

    protected function splitMultiZhuyinOptions(): int
    {
        $splitMultiZhuyin = (int)Interact::select(
            '是否需要将“泂泂[jiǒng jiǒng]”这种词语注音拆分成单字注音，如：“泂[jiǒng]泂[jiǒng]”',
            ['否', '是'],
            '0',
            false
        );
        Show::showSelectedOpt($splitMultiZhuyin, '请到【maps/5.临时替换表.php】查看注音结果报告');

        return $splitMultiZhuyin;
    }

    /**
     * @throws Exception
     */
    protected function restart(): int
    {
        if (TextFixer::isTempFix()) { // 先写死……
            // 检查批注替换结果
            (new ReplacementChecker(TEMP_MAP_FILE, BOOK_DIR))->check();

            return 0;
        }

        $msg = <<<DOC
        ==================================
        <success>【已完成该轮校正】</success>
        ==================================

        请输入数字：
        输入 <primary>0</primary> 不做任何操作，直接退出脚本。
        输入 <primary>1</primary> 则可以继续选用不同的词库，进行下一轮校正。
        输入 <primary>2</primary> 则可重新拆分当前所有的 epub 文本，还原为 epub 文件。
        输入 <primary>3</primary> 则可直接以当前选项重新跑一轮校正（如果修改了词库规则）。

        <red1>【请在 BC 或“文件全局搜索”中比较确认完当前这一轮的校正结果后，再进行下一轮的校正】</red1>

        DOC;
        Show::write($msg);

        $restart = Interact::readln('请输入：');

        if ($restart === '') { // 不输入也继续校正
            return 1;
        }

        $restart = (int)$restart;

        if ($restart === 3) { // rerun
            return 3;
        }

        if ($restart === 2) { // 重新拆分还原当前所有 epub 文件
            chdir(__DIR__);
            (new EpubFixer)->bulkSplitEpubs();
            return 1;
        }

        if ($restart === 1) {
            return 1;
        }

        return 0;
    }
}
