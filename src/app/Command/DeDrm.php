<?php

namespace App\Command;

use Exception;
use App\Service\EpubFixer;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;

class DeDrm extends Command
{
    protected static string $name = 'de-drm';
    protected static string $desc = '解除 epub 的伪 drm 加密';

    /**
     * @throws Exception
     */
    public function execute(Input $input, Output $output): void
    {
        (new EpubFixer)->deDrm(BOOK_DIR);
    }
}
