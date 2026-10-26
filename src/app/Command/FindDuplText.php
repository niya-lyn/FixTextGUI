<?php

namespace App\Command;

use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;
use App\Service\DuplTextFinder;

class FindDuplText extends Command
{
    protected static string $name = 'find-dupl-text';
    protected static string $desc = '查找文本中的重复段落';

    public function execute(Input $input, Output $output): void
    {
        (new DuplTextFinder)->findDuplText();
    }
}
