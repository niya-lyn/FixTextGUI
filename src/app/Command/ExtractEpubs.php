<?php

namespace App\Command;

use Exception;
use App\Service\EpubFixer;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;

class ExtractEpubs extends Command
{
    protected static string $name = 'extract-epubs';
    protected static string $desc = '解压所有 epub 文件';

    /**
     * @throws Exception
     */
    public function execute(Input $input, Output $output): void
    {
        // 递归解压 books 和 booksBak 文件夹中的所有 epub
        $fixer = new EpubFixer();
        $fixer->bulkExtractEpubs(BOOK_BAK_DIR);
        $fixer->bulkExtractEpubs(BOOK_DIR);
    }
}
