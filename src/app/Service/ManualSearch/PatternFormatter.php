<?php

namespace App\Service\ManualSearch;

use App\Util\Util;
use App\Util\Console\Color;

class PatternFormatter
{
    public function highlightUsefulPatterns(array $usefulPatterns, int $selectKey): string
    {
        $info = $this->buildPatternInfoList($usefulPatterns);
        $usefulPatternsInfo = Util::getArrStrWithIndex($info);
        $lines = explode("\n", $usefulPatternsInfo);

        return implode("\n", array_map(
            fn($line) => $this->formatLine($line, $selectKey),
            $lines
        ));
    }

    protected function buildPatternInfoList(array $usefulPatterns): array
    {
        $info = [];
        $patternCountLen = strlen(count($usefulPatterns));

        foreach ($usefulPatterns as $k => $p) {
            $lenDiff = $patternCountLen - strlen($k);
            $status = $p['status'] == 1 ? '已执行' : '未执行';
            $infoStr = "预计替换次数" . str_pad("【{$p['count']}】", 11 + $lenDiff)
                . " 【{$status}】 " . $p['mark'];
            if ($p['color']) {
                $infoStr .= " Color：【{$p['color']}】";
            }
            $info[] = $infoStr;
        }

        return $info;
    }

    protected function formatLine(string $line, int $selectKey): string
    {
        if (str_contains($line, "\"索引-{$selectKey}\"")) {
            $line = Color::backPurple($line) . ' ← 当前执行到此条';
            return $this->removeLineColorMark($line);
        }

        if (str_contains($line, '【已执行】')) {
            $line = Color::foreGray($line);
            return $this->removeLineColorMark($line);
        }

        $line = $this->setLineColor($line);
        return Color::foreYellow($line);
    }

    protected function setLineColor(string $line): string
    {
        if (!str_contains($line, 'Color：')) {
            return $line;
        }

        $colorExp = '/Color：【(.*?)】/um';
        preg_match($colorExp, $line, $matches);
        $colorMethod = 'fore' . $matches[1];

        if (is_callable([Color::class, $colorMethod])) {
            $line = Color::$colorMethod($line);
        }

        return $this->removeLineColorMark($line);
    }

    protected function removeLineColorMark(string $line): string
    {
        return preg_replace('/Color：【(.*?)】/um', '', $line);
    }
}
