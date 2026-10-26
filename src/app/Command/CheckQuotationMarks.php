<?php

namespace App\Command;

use Exception;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;
use App\Service\Quotation\QuotationChecker;

class CheckQuotationMarks extends Command
{
    protected static string $name = 'check-quotation-marks';
    protected static string $desc = '检查中文引号';

    /**
     * @throws Exception
     */
    public function execute(Input $input, Output $output): void
    {
        (new QuotationChecker)->process();
    }
}
