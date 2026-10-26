<?php

namespace App\Command;

use App\Service\Csv;
use App\Exception\AppException;
use App\Util\Util;
use App\Util\Config;
use App\Util\Console\Show;
use App\Util\Console\Color;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;
use Inhere\Console\Util\Interact;

class CsvOperation extends Command
{
    protected static string $name = 'csv-operation';
    protected static string $desc = '在词库 php 文件与 csv 之间进行转换';

    public function execute(Input $input, Output $output): void
    {
        while (true) {
            $this->process();
        }
    }

    /**
     * 处理词库与 CSV 文件的转换操作
     *
     * @throws AppException
     */
    protected function process(): void
    {
        $this->showOutputDirectoryMessage();
        $selection = $this->getUserSelection();

        match ($selection) {
            0       => $this->exportCsvFromMap(),
            1       => $this->generateMapFileFromCsv(),
            default => throw new AppException('无效的选择，请输入有效的索引数字。'),
        };

        Show::successWithNL('【已完成该轮操作，进入下一轮】');
    }

    /**
     * 显示输出文件的目录信息
     */
    private function showOutputDirectoryMessage(): void
    {
        Show::writeWithNL(
            Color::note('生成的 csv 和 php 词库文本文件都在 src/maps 文件夹内')
        );
    }

    /**
     * 获取用户的操作选择
     *
     * @return int 用户选择的操作索引
     */
    private function getUserSelection(): int
    {
        $options = [
            '将词库导出为 csv 文件',
            '通过 csv 生成词库格式的 txt 文件',
        ];
        $selection = (int)Interact::select(
            '选择操作：',
            $options,
            '0',
            false
        );
        Show::showSelectedOpt($selection, $options, false);

        return $selection;
    }

    /**
     * 从词库导出 CSV 文件
     */
    private function exportCsvFromMap(): void
    {
        $mapNames = array_keys(Config::getMap('fileMapping'));
        $mapIndex = (int)Interact::select(
            '请输入以下各 map 前的索引数字，以导出对应 map 的 csv 文件：',
            $mapNames,
            '0',
            false
        );
        Show::showSelectedOpt($mapIndex, $mapNames);

        Csv::mapToCsvFile($mapIndex);
    }

    /**
     * 从 CSV 文件生成词库文本文件
     *
     * @throws AppException 如果 maps 文件夹中未找到 csv 文件
     */
    private function generateMapFileFromCsv(): void
    {
        chdir(SCRIPT_DIR . '/maps');
        $csvFiles = Util::globOnlyFiles('*.csv');

        if (empty($csvFiles)) {
            throw new AppException('maps 文件夹中未找到 csv 文件，退出操作');
        }

        $csvIndex = (int)Interact::select(
            '请输入以下各 csv 文件前的索引数字，以生成对应的词库文本文件：',
            $csvFiles,
            '0',
            false
        );
        Show::showSelectedOpt($csvIndex, $csvFiles);

        Csv::csvToMapFile($csvFiles[$csvIndex]);
    }
}
