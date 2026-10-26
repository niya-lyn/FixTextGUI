<?php

namespace App\Command;

use App\Service\Note\WordsGenerator;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;

class GenerateWords extends Command
{
    protected static string $name = 'generate-words';
    protected static string $desc = '从各类阅读批注中生成词条';

    public function execute(Input $input, Output $output): void
    {
        (new WordsGenerator)->generate();
    }
}
