<?php

namespace App\Service;

use App\Util\Config;
use App\Util\Util;
use App\Exception\AppException;

class Csv
{
    protected static array $csvEscapedChars = [
        ","  => "【英文逗号】",
        "'"  => "【英文单引号】",
        "\"" => "【英文双引号】",
        "\n" => "【换行符】",
    ];

    /**
     * @throws AppException
     */
    public static function mapToCsvFile(int $index): void
    {
        $fileMapping = Config::getMap("fileMapping");
        $mapKeys = array_keys($fileMapping);
        !isset($mapKeys[$index]) && throw new AppException("未输入正确词库索引，无法转换");

        chdir(SCRIPT_DIR . "/maps");
        $mapContent = [];
        $mapName = $mapKeys[$index];
        $mapFile = $fileMapping[$mapName];
        require($mapFile);

        $vars = get_defined_vars();
        foreach ($vars as $var) {
            $var == $mapName && $mapContent = $$var;
        }

        $csvFile = str_replace($mapFile, $mapName . ".csv", $mapFile);
        $csvLines = ["【英文逗号】【英文单引号】【英文双引号】【换行符】，这几种符号都被转成了以【】包裹的特殊标记，如果要在程序中用到，需要自行还原" . PHP_EOL];
        $mapContent = Map::flattenMaps($mapContent, false);
        foreach ($mapContent as $value) {
            $before = $value['before'];
            $after = $value['after'];
            if (self::containsCsvEscapedChars($value)) {
                $before = str_replace(
                    array_keys(self::$csvEscapedChars),
                    array_values(self::$csvEscapedChars),
                    $before,
                );
                $after = str_replace(
                    array_keys(self::$csvEscapedChars),
                    array_values(self::$csvEscapedChars),
                    $after,
                );
            }

            $csvLines[] = "{$before},{$after}" . PHP_EOL;
        }

        file_put_contents($csvFile, $csvLines);
    }

    /**
     * @throws AppException
     */
    public static function csvToMapFile(string $csvFile): void
    {
        chdir(SCRIPT_DIR . "/maps");
        !file_exists($csvFile) && throw new AppException("无对应 csv 文件：{$csvFile}");

        $csvContent = file_get_contents($csvFile);
        $csvContent = explode(PHP_EOL, $csvContent);
        $mapLines = [];
        foreach ($csvContent as $csvLine) {
            $mapArr = explode(",", $csvLine);
            if (count($mapArr) < 2) {
                continue;
            }

            $line = "['before' => \"{$mapArr[0]}\", 'after' => \"{$mapArr[1]}\"]," . PHP_EOL;
            $line = str_replace(
                array_values(self::$csvEscapedChars),
                array_keys(self::$csvEscapedChars),
                $line,
            );
            $mapLines[] = $line;
        }

        $mapFile = str_replace([".csv"], [".txt"], $csvFile);
        file_put_contents($mapFile, $mapLines);
    }

    /**
     * 【暂时未调用】
     * 若有对应词库的 csv 文件，优先使用 csv 里的词条，不再使用 php 词库中的
     *
     * @param array $var
     * @param string $key
     * @return array
     */
    public static function loadMapFromCsv(array $var, string $key): array
    {
        $csvFilepath = Map::getMapFilepath("{$key}.csv");
        if (!file_exists($csvFilepath)) {
            return $var;
        }

        $csvContent = file_get_contents($csvFilepath);
        $csvContent = explode(PHP_EOL, $csvContent);
        $mapLines = [];
        foreach ($csvContent as $csvLine) {
            $mapArr = explode(",", $csvLine);
            if (count($mapArr) < 2) {
                continue;
            }

            $before = $mapArr[0];
            $after  = $mapArr[1];
            $word = compact("before", "after");
            if (self::containsCsvEscapedChars($word, "values")) {
                $before = str_replace(
                    array_values(self::$csvEscapedChars),
                    array_keys(self::$csvEscapedChars),
                    $before,
                );
                $after = str_replace(
                    array_values(self::$csvEscapedChars),
                    array_keys(self::$csvEscapedChars),
                    $after,
                );
            }

            $mapLines[] = $word;
        }

        return $mapLines;
    }

    protected static function containsCsvEscapedChars(array $word, string $type = "keys"): bool
    {
        if ($type == "keys") {
            return Util::multiStrContains($word['before'], array_keys(self::$csvEscapedChars))
                || Util::multiStrContains($word['after'], array_keys(self::$csvEscapedChars));
        } else if ($type == "values") {
            return Util::multiStrContains($word['before'], array_values(self::$csvEscapedChars))
                || Util::multiStrContains($word['after'], array_values(self::$csvEscapedChars));
        }

        return false;
    }
}
