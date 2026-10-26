<?php

namespace App\Service\ManualSearch;

use App\Exception\AppException;
use App\Util\Util;

class PatternValidator
{
    /**
     * @throws AppException
     */
    public function validate(array $patterns): void
    {
        $this->validateRequiredFields($patterns);
        $this->validateUniqueMarks($patterns);
    }

    /**
     * @throws AppException
     */
    protected function validateRequiredFields(array $patterns): void
    {
        $errPatterns = [];
        foreach ($patterns as $pattern) {
            if (
                !isset($pattern['search']) || !$pattern['search']
                || !isset($pattern['replace']) || !$pattern['replace']
                || !isset($pattern['mark']) || !$pattern['mark']
            ) {
                $errPatterns[] = $pattern;
            }
        }

        if ($errPatterns) {
            var_dump($errPatterns);
            throw new AppException('表中存在字段设置有误的规则（看上方的打印信息），'
                . '需要保证每条规则都有 search replace mark 三个字段');
        }
    }

    /**
     * @throws AppException
     */
    protected function validateUniqueMarks(array $patterns): void
    {
        $marks = array_column($patterns, 'mark');
        $duplicatedMarks = Util::findDuplicatesInArray($marks);
        if ($duplicatedMarks) {
            $errStr = implode('、', $duplicatedMarks);
            throw new AppException('表中的这些规则 mark 存在重复：'
                . "\n\n{$errStr}\n\n需要保证每条规则的 mark 都是唯一的");
        }
    }
}
