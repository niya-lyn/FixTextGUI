<?php

namespace App\Command;

use Exception;
use App\Service\EpubFixer;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;

class MakeEpubs extends Command
{
    protected static string $name = 'make-epubs';
    protected static string $desc = '压缩还原所有 epub 文件';

    /**
     * @throws Exception
     */
    public function execute(Input $input, Output $output): void
    {
        // 压缩还原 books 和 booksBak 文件夹中的所有 epub
        (new EpubFixer)->bulkMakeEpubs();
    }
}
