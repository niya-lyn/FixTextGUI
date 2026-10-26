<?php

namespace App\Command;

use Exception;
use App\Util\Config;
use App\Service\TextFixer;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;

class TempFixBooksBak extends Command
{
    protected static string $name = 'temp-fix-books-bak';
    protected static string $desc = '使用临时校对表词条（来自替换报告）校正 booksBak 中的文件';

    /**
     * @throws Exception
     */
    public function execute(Input $input, Output $output): void
    {
        // 将提取自【替换次数报告】的经确认可用的修改项先写到临时校对表
        // 然后用此脚本同步至 booksBak，在使用 BC 对比前减少一些明确的差异项
        $textFixer = TextFixer::getInstance(true);
        $textFixer->setUseMapsConfigIndex(Config::getMap('tempFixIndex'));

        // 为了防止 booksBak 中被改的项比 books 中的还多，需要同时处理两个目录中的文件
        $textFixer->fixBooks(BOOK_BAK_DIR);
        $textFixer->fixBooks(BOOK_DIR);
    }
}
