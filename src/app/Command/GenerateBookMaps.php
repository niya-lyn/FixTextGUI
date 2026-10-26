<?php

namespace App\Command;

use Exception;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;
use App\Service\Diff\Extractor;
use App\Service\Diff\Option;
use App\Util\Console\Show;
use Inhere\Console\Util\Interact;

class GenerateBookMaps extends Command
{
    protected static string $name = 'generate-book-maps';
    protected static string $desc = '生成书籍的专有词条';

    protected Option $option;

    /**
     * @throws Exception
     */
    public function execute(Input $input, Output $output): void
    {
        // 利用已备份的全量修改书籍文件，自动生成书籍的专有词条
        $this->option = new Option;
        $this->addCurrentTimeOption();
        (new Extractor($this->option))->generateBookMaps();
    }

    protected function addCurrentTimeOption(): void
    {
        $opts = [
            '否',
            '是',
        ];
        $selection = Interact::select('是否记录添加当前词条的时间', $opts, '1', false);
        Show::showSelectedOpt($selection, $opts);
        $this->option->addCurrentTime = !($selection == 0);
    }
}
