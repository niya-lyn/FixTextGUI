<?php

namespace App\Service\Note;

use App\Util\Util;

/**
 * 批注分类器 - 负责将批注分类到不同的 map 中
 */
class NoteClassifier
{
    protected array $maps = [
        NoteConstants::MAP_SAME       => [],
        NoteConstants::MAP_LACK       => [],
        NoteConstants::MAP_FIXED      => [],
        NoteConstants::MAP_MARKS      => [],
        NoteConstants::MAP_NORMAL     => [],
        NoteConstants::MAP_EXTRA_MSGS => [],
    ];

    /**
     * 对批注进行分类
     */
    public function classify(array $note): void
    {
        // 1. 特殊标记
        if ($this->classifyAsSpecialMark($note)) {
            return;
        }

        // 2. 相同映射
        if ($this->classifyAsSameMap($note)) {
            return;
        }

        // 3. 固定规则（由外部传入已转换的结果）
        if (isset($note['convertedByRules'])) {
            $this->classifyAsFixedMap($note);
            return;
        }

        // 4. 缺少规则
        if ($this->classifyAsLackMap($note)) {
            return;
        }

        // 5. 额外信息
        if ($this->classifyAsExtraMsg($note)) {
            return;
        }

        // 6. 普通映射
        $this->maps[NoteConstants::MAP_NORMAL][] = $note;
    }

    /**
     * 分类为特殊标记
     */
    protected function classifyAsSpecialMark(array $note): bool
    {
        if (isset(NoteConstants::SPECIAL_MARKS[$note['after']])) {
            $mark = NoteConstants::SPECIAL_MARKS[$note['after']];
            $note['after'] = $mark[0] . $note['before'] . $mark[1];
            $note['mark'] = $mark[2];
            $this->maps[NoteConstants::MAP_MARKS][] = $note;

            return true;
        }

        return false;
    }

    /**
     * 分类为相同映射
     */
    protected function classifyAsSameMap(array $note): bool
    {
        $escapers = [
            NoteConstants::SAME_MAP_ESCAPER_1,
            NoteConstants::SAME_MAP_ESCAPER_2,
        ];

        if (in_array($note['after'], $escapers)) {
            $note['after'] = $note['before'];
            $this->maps[NoteConstants::MAP_SAME][] = $note;

            return true;
        }

        return false;
    }

    /**
     * 分类为固定规则映射
     */
    protected function classifyAsFixedMap(array $note): void
    {
        if (isset($note['needsReview'])) {
            // 需要人工审核的放到 same map（看成内容未改变，需要放在文件开头）
            unset($note['needsReview'], $note['convertedByRules']);
            $this->maps[NoteConstants::MAP_SAME][] = $note;
        } else {
            unset($note['convertedByRules']);
            $this->maps[NoteConstants::MAP_FIXED][] = $note;
        }
    }

    /**
     * 分类为缺少规则映射
     */
    protected function classifyAsLackMap(array $note): bool
    {
        $escapers = [
            NoteConstants::EXTRA_MSG_ESCAPER_1,
            NoteConstants::EXTRA_MSG_ESCAPER_2,
        ];

        // 不是额外信息，且没有换行符
        $isNotExtraMsg = !str_starts_with($note['after'], $escapers[0])
            && !str_starts_with($note['after'], $escapers[1])
            && !str_contains($note['after'], '\n')
            && !str_contains($note['before'], '\n');

        // 字符数量差异过大，或包含未配置的多个关键字
        $hasLargeDifference = abs(mb_strlen($note['before']) - mb_strlen($note['after'])) > 4
            || Util::multiStrContains($note['after'], ["#"]);

        if ($isNotExtraMsg && $hasLargeDifference) {
            if (!isset($note['mark'])) {
                $note['mark'] = "批注内容：{$note['after']}";
            }
            $this->maps[NoteConstants::MAP_LACK][] = $note;

            return true;
        }

        return false;
    }

    /**
     * 分类为额外信息
     */
    protected function classifyAsExtraMsg(array $note): bool
    {
        if (
            str_starts_with($note['after'], NoteConstants::EXTRA_MSG_ESCAPER_1)
            || str_starts_with($note['after'], NoteConstants::EXTRA_MSG_ESCAPER_2)
        ) {
            $this->maps[NoteConstants::MAP_EXTRA_MSGS][] = $note;

            return true;
        }

        return false;
    }

    /**
     * 获取所有分类结果
     */
    public function getMaps(): array
    {
        return $this->maps;
    }
}
