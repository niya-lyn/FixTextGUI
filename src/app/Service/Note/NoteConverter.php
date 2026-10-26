<?php

namespace App\Service\Note;

use App\Util\Console\Show;
use App\Util\NumberConverter;

/**
 * 批注转换处理器 - 负责将批注内容按规则转换
 */
class NoteConverter
{
    protected array $fixedNoteRules;
    protected array $allFixedRules;
    protected array $simpleFixedCombos;
    protected array $puncts = ['，', '。', '！', '？', '：', '…', '……', '-', '—', '——', '”', '’', '、'];

    public function __construct(
        array $fixedNoteRules,
        array $simpleFixedCombos
    ) {
        $this->fixedNoteRules = $fixedNoteRules;
        $this->simpleFixedCombos = array_flip($simpleFixedCombos);
        // 包含所有 FixedRules，用于快速判断 after 是否存在固定值
        $this->allFixedRules = array_flip(array_merge(...$fixedNoteRules));
    }

    /**
     * 创建批注数组
     */
    public function createNote(array $match): array
    {
        $note = [
            'before' => $match[1],
            'after'  => $match[2] ?? NoteConstants::SAME_MAP_ESCAPER_1, // 先假定值相等
        ];

        // 无批注标记
        if (!isset($match[2]) || !$match[2]) {
            $note['mark'] = '无批注';
        }

        return $note;
    }

    /**
     * 转换批注（主入口）
     *
     * 处理流程：
     * 1. 应用手动规则（基于操作符）
     * 2. 应用自动规则（基于配置的 FixedRules）
     *
     * @param array $note
     * @return array|null 为 null 时表示是直接复制粘贴修改的“普通映射”，分类时不需要标记为 convertedByRules 并进入 MAP_FIXED
     */
    public function convertNoteByRules(array $note): ?array
    {
        $originalBefore = $note['before'];
        $originalAfter = $note['after'];

        // 根据 # 对标注内容进行分割（支持多规则）
        $words = explode(NoteConstants::WORD_SEPERATOR, $note['after']);

        // 1. 应用手动规则（需要手动写各种 processor 进行不同的转换）
        // 处理 a@b 定向转换、去除后引号、转换阿拉伯数字、定位转换、多行合并、增加分隔行等等……
        // 每处理一个规则，就会移除 words 中对应的部分
        $note = $this->applyManualRules($note, $words);

        // 如果所有规则都已处理（$words 被缩减为空），直接返回
        if (empty($words)) {
            unset($note['_afterConverted']);
            if ($note['after'] == $note['before']) { // 执行了规则却未改变内容，可能是规则写法出错
                $note['needsReview'] = true;
            }

            return $note;
        }

        // 2. 应用自动规则（根据配置的 FixedRules 自动替换，不用写 processor）
        if (!$this->allWordsInFixedRules($words)) {
            // 只要有一条找不到就判定为不符合条件
            if ($note['_afterConverted']) {
                $note['mark'] = "批注内容：{$originalAfter} | 【批注中有尚未配置的转换规则】";
                unset($note['_afterConverted']);
                return $note;
            }

            unset($note['_afterConverted']);
            return null; // 若内容未改变，返回 null 表示为“普通映射”
        }

        // 应用字典规则
        $note['after'] = $this->applyFixedRules($note, $words);

        // 检查是否成功转换
        if ($originalBefore == $note['after']) {
            // 如果【批注的字符】和【预期要替换的字符】分布在【不同的规则】中
            // 则无法进行对应替换，结果什么也没改动，只能先增加 needsReview 的标记
            $note['mark'] = "批注内容：{$originalAfter} | 【批注字符和预期替换字符分布在不同规则中，无法替换】";
            $note['needsReview'] = true;
        } else {
            $note['mark'] = $note['mark'] ?? "批注内容：{$originalAfter}";
        }

        // 清理临时标志
        unset($note['_afterConverted']);

        return $note;
    }

    /**
     * 处理手动替换规则
     */
    protected function applyManualRules(array $note, array &$words): array
    {
        $toRemove = [];

        $note['_afterConverted'] = false;

        // 定义处理器链
        $processors = $this->getManualProcessors();

        foreach ($words as $k => $word) {
            // 对每个 # 分割的部分，依次尝试每个处理器
            foreach ($processors as $processor) {
                if ($processor($note, $word)) {
                    $toRemove[] = $k;
                    // 标记为 after 已变动，后续步骤均以上一步结束的 after 为源文本
                    // 而不是以 before 为源文本，避免造成无效覆盖
                    $note['_afterConverted'] = true;
                    break; // 找到匹配的处理器就停止，处理下一个 # 分割的部分
                }
            }
        }

        // 移除已处理的词
        $words = $this->removeProcessedWords($words, $toRemove);

        return $note;
    }

    /**
     * 获取处理器链
     */
    protected function getManualProcessors(): array
    {
        return [
            // 1. 结构性处理（分隔行、合并行）
            fn(&$note, $word) => $this->manualAddStarSeparator($note, $word),
            fn(&$note, $word) => $this->manualAddEllipsisSeparator($note, $word),
            fn(&$note, $word) => $this->manualMergeLines($note, $word),
            fn(&$note, $word) => $this->manualRmEndcharMergeLines($note, $word),

            // 2. 内容转换
            fn(&$note, $word) => $this->manualProcessSimpleFixedCombos($note, $word),
            fn(&$note, $word) => $this->manualProcessLocators($note, $word),
            fn(&$note, $word) => $this->manualRemoveRQuotation($note, $word),
            fn(&$note, $word) => $this->manualConvertQuotation($note, $word),
            fn(&$note, $word) => $this->manualRemoveRepetition($note, $word),
            fn(&$note, $word) => $this->manualArabicToChnNum($note, $word),
            fn(&$note, $word) => $this->manualChnToArabicNum($note, $word),

            // 3. @ 操作符转换
            fn(&$note, $word) => $this->manualProcessNoteConverter($note, $word),
        ];
    }

    /**
     * 移除已处理的规则
     */
    protected function removeProcessedWords(array $words, array $toRemove): array
    {
        foreach ($toRemove as $key) {
            unset($words[$key]);
        }

        return array_values($words);
    }

    /**
     * 追加 mark 描述
     */
    protected function appendMark(array &$note, string $description): void
    {
        $note['mark'] = $note['mark'] ?? "批注内容：" . $note['after'];
        if (!str_contains($note['mark'], $description)) {
            $note['mark'] .= " | 【{$description}】";
        }
    }

    /**
     * 根据词条变动情况，选择应更改的源文本字段（支持规则追加链式处理）
     */
    protected function getSourceText(array $note): string
    {
        return $note['_afterConverted'] ? $note['after'] : $note['before'];
    }

    /**
     * 处理※※※分隔行
     */
    protected function manualAddStarSeparator(array &$note, string $word): bool
    {
        if (!in_array($word, NoteConstants::ADD_STAR_SEPARATOR)) {
            return false;
        }

        $this->appendMark($note, '增加※※※分隔行');

        $source = $this->getSourceText($note);
        $note['after'] = '※※※\n' . $source;

        return true;
    }

    /**
     * 处理省略号分隔行
     */
    protected function manualAddEllipsisSeparator(array &$note, string $word): bool
    {
        if (!in_array($word, NoteConstants::ADD_ELLIPSIS_SEPARATOR)) {
            return false;
        }

        $this->appendMark($note, '增加省略号分隔行');

        $source = $this->getSourceText($note);
        $note['after'] = '……\n' . $source;

        return true;
    }

    /**
     * 合并多行
     */
    protected function manualMergeLines(array &$note, string $word): bool
    {
        if ($word !== NoteConstants::MERGE_LINES) {
            return false;
        }

        $this->appendMark($note, '合并多行');

        // 1. `(”\n“)|(’\n[‘|’])`: 合并连续的对话行，移除中间的首尾引号
        // 2. `(\n[“‘|’])`: 合并段落，当段落的每一行都以引号开头时，移除换行符和下一行的起始引号
        // 3. `(\n)`: 合并所有其他普通换行
        $pattern = '/(”\n“)|(’\n[‘|’])|(\n[“‘|’])|(\n)/u';
        $source = $this->getSourceText($note);
        $note['after'] = preg_replace($pattern, '', $source);

        return true;
    }

    /**
     * 移除当前行末尾的多余标点，然后和下一行合并
     */
    protected function manualRmEndcharMergeLines(array &$note, string $word): bool
    {
        if ($word !== NoteConstants::RM_ENDCHAR_MERGE_LINES) {
            return false;
        }

        $this->appendMark($note, '移除行尾多余标点，合并多行');

        // 1. 移除各行的多余结尾标点
        // 2. 将换行符替换为空，合并为一行
        $source = $this->getSourceText($note);
        $source = preg_replace('/(?:——|……|。|，|！|？|…|—|；)+$/mu', '', $source);
        $note['after'] = str_replace("\n", '', $source);

        return true;
    }

    /**
     * 处理简单组合转换
     */
    protected function manualProcessSimpleFixedCombos(array &$note, string $word): bool
    {
        if (!isset($this->simpleFixedCombos[$word])) {
            return false;
        }

        $this->appendMark($note, '处理简单组合');

        $punctParts = mb_str_split($word);
        $source = $this->getSourceText($note);
        $note['after'] = str_replace($punctParts[0], $punctParts[1], $source);

        return true;
    }

    /**
     * 处理定位标记（【。。】开头的规则）
     */
    protected function manualProcessLocators(array &$note, string $word): bool
    {
        if (!str_starts_with($word, NoteConstants::LOCATOR_START)) {
            return false;
        }

        $word = $this->preConvertWords($word);
        $targetChars = mb_str_split($this->getSourceText($note));

        // 位置转换：【。。12@xy】
        if (str_contains($word, NoteConstants::LOCATE_THEN_CONVERT)) {
            $targetChars = $this->convertByPositions($word, $targetChars);
        }
        // 位置插入：【。。1+xy】
        else if (str_contains($word, NoteConstants::LOCATE_THEN_ADD)) {
            $targetChars = $this->insertByPositions($word, $targetChars);
        }
        // 位置删除：【。。1-】
        else if (str_ends_with($word, NoteConstants::LOCATE_THEN_DEL)) {
            $targetChars = $this->deleteByPositions($word, $targetChars);
        }
        // 位置替换：【。。1=abc】
        else if (str_contains($word, NoteConstants::LOCATE_THEN_REPLACE)) {
            $targetChars = $this->replaceByPositions($word, $targetChars);
        }
        // 增加换行：【。。1！！】
        else if (str_ends_with($word, NoteConstants::LOCATE_THEN_ADD_NEW_LINE)) {
            $targetChars = $this->addNewLineByPositions($word, $targetChars);
        }
        // 位置替换的简写形式：【。。1x】
        else {
            $targetChars = $this->simpleReplaceByPositions($word, $targetChars);
        }

        $this->appendMark($note, '处理定位标记转换');

        $note['after'] = implode($targetChars);

        return true;
    }

    /**
     * 预处理 word
     *
     * 非数字开头的【。。xy】等同于【。。1=xy】，从第 1 个字符开始，用 xy 替换后续对应位置字符（写单个字符 x 也行）
     * 支持使用空格来右移位置（或使用【。】来代替空格）
     * 同上面的写法，支持【。。-】和【 。。+xy】的转换，也支持空格右移
     */
    protected function preConvertWords(string $word): string
    {
        $word = mb_substr($word, mb_strlen(NoteConstants::LOCATOR_START)); // 移除【。。】

        $offset = 0;
        while ($offset < mb_strlen($word) && mb_substr($word, $offset, 1) === '。') {
            $offset++;
        }
        if ($offset > 0) {
            $word = str_repeat(' ', $offset) . mb_substr($word, $offset); // 将开头的其他【。】转为空格
        }

        if (!preg_match('/^\d/', $word)) {
            $ltrimmedWord = ltrim($word, ' '); // 计算一下开头空格数，如果有空格就右移对应的位置
            $index = 1 + mb_strlen($word) - mb_strlen($ltrimmedWord);

            if (str_starts_with($ltrimmedWord, NoteConstants::LOCATE_THEN_ADD)) {
                $word = $index . $ltrimmedWord; // 转为 1+xy
            } else if (str_starts_with($ltrimmedWord, NoteConstants::LOCATE_THEN_DEL)) {
                $word = $index . NoteConstants::LOCATE_THEN_DEL; // 转为 1-
            } else if (str_starts_with($ltrimmedWord, NoteConstants::LOCATE_THEN_ADD_NEW_LINE)) {
                $word = $index . NoteConstants::LOCATE_THEN_ADD_NEW_LINE; // 转为 1！！
            } else {
                $word = $index . NoteConstants::LOCATE_THEN_REPLACE . $ltrimmedWord; // 转为 1=xy
            }
        }

        return $word;
    }

    /**
     * 位置转换：【。。12@xy】将第 1、2 个字符转换为 x、y
     */
    protected function convertByPositions(string $word, array $targetChars): array
    {
        $parts = explode(NoteConstants::WORD_CONVERTER, $word);
        $positions = mb_str_split($parts[0]);
        $replacements = mb_str_split($parts[1]);

        foreach ($positions as $k => $pos) {
            if (!is_numeric($pos)) {
                Show::warnWithNL("批注格式有误：【{$word}】，@ 前面不是正确的位置数字，此条批注未转换");
                break;
            }

            $index = $pos - 1;
            if (isset($targetChars[$index]) && isset($replacements[$k])) {
                $targetChars[$index] = $replacements[$k];
            }
        }

        return $targetChars;
    }

    /**
     * 位置插入：【。。1+xy】在第 1 个字符后插入 xy
     */
    protected function insertByPositions(string $word, array $targetChars): array
    {
        $parts = explode(NoteConstants::LOCATE_THEN_ADD, $word, 2);
        $insertionIndex = max($parts[0], 0);
        array_splice($targetChars, $insertionIndex, 0, [$parts[1]]);

        return $targetChars;
    }

    /**
     * 位置删除：【。。12-】删除第 1、2 个字符
     */
    protected function deleteByPositions(string $word, array $targetChars): array
    {
        $positions = mb_str_split(rtrim($word, NoteConstants::LOCATE_THEN_DEL));
        foreach ($positions as $pos) {
            unset($targetChars[$pos - 1]);
        }

        return $targetChars;
    }

    /**
     * 【。。1！！】，表示在第 1 个字符后面增加换行
     */
    protected function addNewLineByPositions(string $word, array $targetChars): array
    {
        $parts = explode(NoteConstants::LOCATE_THEN_ADD_NEW_LINE, $word, 2);
        $insertionIndex = max($parts[0], 0);
        array_splice($targetChars, $insertionIndex, 0, ["\n"]);

        return $targetChars;
    }

    /**
     * 位置替换：【。。1=abc】从第 1 个字符开始（包括第 1 个字符），将第 1、2、3 个字符换成 abc（取决于 abc 的长度），相当于是 【。。123@abc】，但不用写多个位置
     */
    protected function replaceByPositions(string $word, array $targetChars): array
    {
        $parts = explode(NoteConstants::LOCATE_THEN_REPLACE, $word, 2);
        if (count($parts) !== 2) {
            return $targetChars;
        }

        $indexStr = $parts[0];
        $replacementStr = $parts[1];
        $startIndex = (int)$indexStr - 1;

        $replacementChars = mb_str_split($replacementStr);
        $replacementLength = count($replacementChars);

        for ($i = 0; $i < $replacementLength; $i++) {
            $targetIndex = $startIndex + $i;
            if (isset($targetChars[$targetIndex])) {
                $targetChars[$targetIndex] = $replacementChars[$i];
            }
        }

        return $targetChars;
    }

    /**
     * 简写规则：
     * 【。。1x】将第 1 个字符替换为 x，只有前面的数字和后面的文字【数量相等】时才执行，否则还是需要写成【。。1=xy】才能生效
     * 【。。15xy】多字符替换，第 1 个字符换成 x，第 5 个字符换成 y
     * 【。。1，】在第 1 个字符后面追加【，】（如果是 $this->puncts 中的标点，直接追加）
     */
    protected function simpleReplaceByPositions(string $word, array $targetChars): array
    {
        // 处理标点符号插入逻辑, 例如: "1，"
        // 格式为单个数字后跟一个指定的标点符号
        if (preg_match('/^(\d)([^\d])$/u', $word, $matches)) {
            $indexStr = $matches[1];
            $punctCandidate = $matches[2];

            // 确保后续字符是合法的标点
            if (in_array($punctCandidate, $this->puncts)) {
                $index = (int)$indexStr - 1;
                if (isset($targetChars[$index])) {
                    // 在指定位置的字符后面追加标点
                    $targetChars[$index] .= $punctCandidate;
                }

                return $targetChars;
            }
        }

        // 处理多字符替换逻辑, 例如: "12xy"
        // 格式为数字串后跟一个非数字的字符串
        if (preg_match('/^(\d+)([^\d].*)$/u', $word, $matches)) {
            $indicesStr = $matches[1];
            $replacementsStr = $matches[2];

            $indices = str_split($indicesStr);
            $replacements = mb_str_split($replacementsStr);

            // 仅当位置数字的数量和替换字符的数量相同时才执行操作
            if (count($indices) === count($replacements)) {
                foreach ($indices as $i => $charIndex) {
                    $index = (int)$charIndex - 1;
                    if (isset($targetChars[$index])) {
                        $targetChars[$index] = $replacements[$i];
                    }
                }
            }
        }

        return $targetChars;
    }

    /**
     * 移除后引号
     */
    protected function manualRemoveRQuotation(array &$note, string $word): bool
    {
        if (!in_array($word, NoteConstants::RM_RQUOTATION)) {
            return false;
        }

        $this->appendMark($note, '移除句末后引号');

        $source = $this->getSourceText($note);
        $note['after'] = preg_replace('/”(?=(?:<\/span>)?(?:<\/p>)?(?:\\\\n|$))/m', '', $source);

        return true;
    }

    /**
     * 单双引号转换
     */
    protected function manualConvertQuotation(array &$note, string $word): bool
    {
        if (!in_array($word, NoteConstants::CV_QUOTATION)) {
            return false;
        }

        $this->appendMark($note, '单双引号互转');

        $source = $this->getSourceText($note);
        $note['after'] = strtr($source, [
            '“' => '‘',
            '”' => '’',
            '‘' => '“',
            '’' => '”'
        ]);

        return true;
    }

    /**
     * 处理叠字叠词移除
     */
    protected function manualRemoveRepetition(array &$note, string $word): bool
    {
        if (!str_ends_with($word, NoteConstants::RM_REPETITION)) {
            return false;
        }

        $chars = rtrim($word, NoteConstants::RM_REPETITION);

        $this->appendMark($note, '移除叠字叠词');

        $source = $this->getSourceText($note);
        $note['after'] = str_replace(str_repeat($chars, 2), $chars, $source);

        return true;
    }

    /**
     * 阿拉伯数字转中文
     */
    protected function manualArabicToChnNum(array &$note, string $word): bool
    {
        if (!in_array($word, NoteConstants::AN_2_CN)) {
            return false;
        }

        $this->appendMark($note, '阿拉伯数字转中文');

        $source = $this->getSourceText($note);

        $newText = preg_replace_callback("/\d+/u", static function ($matches) {
            return NumberConverter::arabicToChnNum($matches[0]) ?: $matches[0];
        }, $source);

        // 特殊处理“二”字
        $newText = preg_replace_callback(
            '/(?<![第十点])((?<![千万])二[千万](?![百千万])|二三?(?:分[米钟]|小时|公里|[年岁滴枚堆条个块根秒支枝柄把只张厘米吨斤克毫份桶口天次门杯下圈朵股波拨群名位碗盘盆框颗粒副幅瓶罐套])|[午晚晨]二点)/u',
            static function ($matches) {
                return str_replace('二', '两', $matches[0]);
            },
            $newText
        );

        $note['after'] = $newText;

        return true;
    }

    /**
     * 中文转阿拉伯数字
     */
    protected function manualChnToArabicNum(array &$note, string $word): bool
    {
        if (!in_array($word, NoteConstants::CN_2_AN)) {
            return false;
        }

        $this->appendMark($note, '中文转阿拉伯数字');

        $source = $this->getSourceText($note);
        $note['after'] = preg_replace_callback("/[一二三四五六七八九十零〇百千万亿两廿卅卌壹贰叁肆伍陆柒捌玖拾佰仟萬億]+/u", function ($matches) {
            return NumberConverter::chnToArabicNum($matches[0]) ?: $matches[0];
        }, $source);

        return true;
    }

    /**
     * 处理手动替换（@ 转换符）
     */
    protected function manualProcessNoteConverter(array &$note, string $word): bool
    {
        $wordParts = explode(NoteConstants::WORD_CONVERTER, $word);

        if (!$this->isValidManualReplacement($wordParts)) {
            return false;
        }

        // 标点补充处理
        if (
            in_array($wordParts[1], $this->puncts) // after 为单独标点，就是在 before 之后直接追加
            && !in_array($wordParts[0], $this->puncts) // 当 before 也为标点时，进行转换，不追加
        ) {
            $wordParts[1] = $wordParts[0] . $wordParts[1];
        }

        // + 号表示在特定字符后面追加内容
        if (str_starts_with($wordParts[1], NoteConstants::ADD_CHARS)) {
            $wordParts[1] = $wordParts[0] . ltrim($wordParts[1], NoteConstants::ADD_CHARS);
        }

        $this->appendMark($note, '处理 @ 操作符转换');

        $source = $this->getSourceText($note);
        $note['after'] = str_replace($wordParts[0], $wordParts[1], $source);

        return true;
    }

    /**
     * 验证手动替换是否有效
     */
    protected function isValidManualReplacement(array $wordParts): bool
    {
        return count($wordParts) == 2
            && !empty($wordParts[0])
            && (
                abs(mb_strlen($wordParts[0]) - mb_strlen($wordParts[1])) <= 3
                || empty($wordParts[1])
                || in_array($wordParts[1], $this->puncts)
            );
    }

    /**
     * 检查所有词是否都在固定规则中
     */
    protected function allWordsInFixedRules(array $words): bool
    {
        foreach ($words as $word) {
            if (!isset($this->allFixedRules[$word])) {
                return false;
            }
        }

        return true;
    }

    /**
     * 应用配置中的 FixedRules 到内容
     */
    protected function applyFixedRules(array $note, array $words): string
    {
        $after = $this->getSourceText($note);

        foreach ($words as $word) {
            foreach ($this->fixedNoteRules as $fixedRule) {
                if (!in_array($word, $fixedRule)) {
                    continue;
                }

                $before = $after;
                $after = str_replace($fixedRule, $word, $after);

                if ($before != $after) {
                    // 支持将同一个字词配置到不同的规则，放在前面的优先级更高
                    // 当前面的规则成功替换，改变了 before 的内容时，直接停止遍历后面的规则
                    break;
                }
            }
        }

        return $after;
    }
}
