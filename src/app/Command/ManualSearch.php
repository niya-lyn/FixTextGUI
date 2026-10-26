<?php

namespace App\Command;

use App\Service\ManualSearch\ManualSearcher;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;

class ManualSearch extends Command
{
    protected static string $name = 'manual-search';
    protected static string $desc = '手动检索';

    public function execute(Input $input, Output $output): void
    {
        (new ManualSearcher)->process();
    }
}
