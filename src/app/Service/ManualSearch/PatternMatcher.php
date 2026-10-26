<?php

namespace App\Service\ManualSearch;

use Exception;
use App\Util\Console\Show;
use App\Service\PatternFileLoader;

class PatternMatcher
{
    public function findUsefulPatterns(string $file, array $patterns): array
    {
        $usefulPatterns = [];
        $patternCount = count($patterns);
        $content = file_get_contents($file);

        foreach ($patterns as $key => $pattern) {
            $this->showMatchProgress($key, $patternCount);

            try {
                // 搜索时也要支持多行写法
                $matchCount = preg_match_all('/' . $pattern['search'] . '/umx', $content);
                if ($matchCount) {
                    $usefulPatterns[] = $this->preparePattern($pattern, $matchCount);
                }
            } catch (Exception $e) {
                var_dump($pattern);
                Show::error('正则表达式有误，匹配出错，请检查下面的报错信息，修复后重试：');
                throw $e;
            }
        }

        return $usefulPatterns;
    }

    protected function showMatchProgress(int $key, int $total): void
    {
        $progressKey = $key + 1;
        if ($progressKey % 50 === 0) {
            Show::write("当前检测进度：{$progressKey}/{$total}");
        }
    }

    protected function preparePattern(array $pattern, int $matchCount): array
    {
        return array_merge($pattern, [
            'count'  => $matchCount,
            'status' => 0,
            'color'  => $pattern['color'] ?? '',
        ]);
    }

    public function sortPatterns(array &$usefulPatterns, int $sort): void
    {
        match ($sort) {
            // 按替换次数
            1 => usort($usefulPatterns, fn($a, $b) => $a['count'] <=> $b['count']),
            // 按颜色分组
            2 => usort($usefulPatterns, fn($a, $b) => [$a['color'], $a['count']] <=> [$b['color'], $b['count']]),
            default => null,
        };
    }

    public function reloadUsefulPatterns(array &$usefulPatterns): void
    {
        $usefulMarksMap = [];
        foreach ($usefulPatterns as &$v) {
            $usefulMarksMap[$v['mark']] = &$v; // 持有引用
        }
        unset($v);

        $patterns = PatternFileLoader::loadPatterns();
        foreach ($patterns as $p) {
            $pMark = $p['mark'];
            if (isset($usefulMarksMap[$pMark])) {
                $usefulMarksMap[$pMark]['search'] = $p['search'];
                $usefulMarksMap[$pMark]['replace'] = $p['replace'];
            }
        }
    }
}
