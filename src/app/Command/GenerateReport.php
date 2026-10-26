<?php

namespace App\Command;

use App\Exception\AppException;
use App\Util\Console\Show;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use App\Service\Diff\Option;
use Inhere\Console\IO\Output;
use App\Service\Diff\Extractor;
use App\Util\Config;
use Inhere\Console\Util\Interact;

class GenerateReport extends Command
{
    protected static string $name = 'generate-report';
    protected static string $desc = '生成替换报告';

    protected Option $option;

    public function execute(Input $input, Output $output): void
    {
        while (true) {
            $this->option = new Option;
            $this->process();
        }
    }

    /**
     * @throws AppException
     */
    protected function process()
    {
        Show::opTitle('【1.筛选替换次数大于 N 的词条】（默认为 1）');
        $replaceCountThreshold = Interact::readln('请输入：');
        $replaceCountThreshold = $replaceCountThreshold == '' ? 1 : (int)$replaceCountThreshold;
        $replaceCountThreshold = max(0, $replaceCountThreshold);
        Show::showSelectedOpt($replaceCountThreshold, '', false);

        Show::opTitle('【2.输入截取上下文的长度】（默认为 3）');
        Show::write('只支持 0-20 之间的数字');
        $contextLen = Interact::readln('请输入：');
        $contextLen = $contextLen == '' ? 3 : (int)$contextLen;
        $contextLen = max(0, $contextLen);
        $contextLen = min(20, $contextLen);
        Show::showSelectedOpt($contextLen, '', false);

        Show::opTitle('【3.选择是否需要移除一定长度的首尾字符】（默认为 1）');
        $msg = <<<DOC
        输入 0 不移除；
        输入大于 0 的值，移除对应长度的<primary>【首部字符】</primary>；
        输入小于 0 的值，移除对应长度的<primary>【尾部字符】</primary>。
        DOC;
        Show::writeWithNL($msg);
        $removeLOrRChar = Interact::readln('请输入：');
        $removeLOrRChar = $removeLOrRChar == '' ? 1 : (int)$removeLOrRChar;
        if (abs($removeLOrRChar) > $contextLen) {
            throw new AppException('移除的首尾字符长度大于了上下文字符长度，无法操作');
        }
        Show::showSelectedOpt($removeLOrRChar, '', false);

        $filterKeywords      = $this->option->filterKeywords;
        $getMultiLineContent = $this->option->getMultiLineContent;
        $trimPunctuations    = $this->option->trimPunctuations;
        $addHtmlStrippedCopy = $this->option->addHtmlStrippedCopy;

        if (Config::getGeneral('genReportWithAllOpts')) {
            Show::opTitle('【4.是否需要依据特定关键词进行筛选】');
            $filterKeywords = (bool)Interact::readln('请输入：');
            $msg = $filterKeywords ? '是' : '否';
            Show::showSelectedOpt($msg, '', false);

            Show::opTitle('【5.是否需要提取跨行的差异内容】');
            $getMultiLineContent = (bool)Interact::readln('请输入：');
            $msg = $getMultiLineContent ? '是' : '否';
            Show::showSelectedOpt($msg, '', false);

            Show::opTitle('【6.是否需要移除每处差异的首尾标点符号】');
            $trimPunctuations = (bool)Interact::readln('请输入：');
            $msg = $trimPunctuations ? '是' : '否';
            Show::showSelectedOpt($msg, '', false);

            Show::opTitle('【7.是否需要另外存一份移除了 html 标签的内容】');
            $addHtmlStrippedCopy = (bool)Interact::select(
                '请选择：',
                ['否', '是'],
                '0',
                false
            );
            $msg = $addHtmlStrippedCopy ? '是' : '否';
            Show::showSelectedOpt($msg, "", false);
        }

        $this->option->replaceCountThreshold = $replaceCountThreshold;
        $this->option->contextLen            = $contextLen;
        $this->option->removeLOrRChar        = $removeLOrRChar;
        $this->option->filterKeywords        = $filterKeywords;
        $this->option->getMultiLineContent   = $getMultiLineContent;
        $this->option->trimPunctuations      = $trimPunctuations;
        $this->option->addHtmlStrippedCopy   = $addHtmlStrippedCopy;

        (new Extractor($this->option))->genReplaceCountReport(BOOK_DIR);

        $msg = <<<DOC

        ==================================
        <success>已生成【替换次数报告】</success>
        请到 <primary>maps/5.临时校对表.php</primary> 查看
        ==================================
        DOC;
        Show::writeWithNL($msg);
    }
}
