<?php

namespace App\Command;

use Exception;
use App\Service\EpubFixer;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;

class SplitEpubText extends Command
{
    protected static string $name = 'split-epub-text';
    protected static string $desc = '拆分还原 epub 文本（从 txt 中拆分）';

    /**
     * @throws Exception
     */
    public function execute(Input $input, Output $output): void
    {
        // 将 books 中被合并的文本文件进行拆分还原，
        // 生成新的 epub 覆盖原 epub 文件
        (new EpubFixer)->bulkSplitEpubs();
    }
}
