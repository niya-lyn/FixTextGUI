<?php

namespace App\Service\Note;

use App\Util\Util;

/**
 * 结果生成器 - 负责生成最终的校对表文件
 */
class ResultGenerator
{
    /**
     * 生成结果文件
     */
    public function generate(array $maps): void
    {
        $result = $this->buildResultContent($maps);
        file_put_contents(TEMP_MAP_FILE, $result);
    }

    /**
     * 构建结果内容
     */
    protected function buildResultContent(array $maps): string
    {
        $content = "<?php\n\n";

        // 额外信息
        $content .= $this->buildExtraMessages($maps[NoteConstants::MAP_EXTRA_MSGS]);

        // 临时校对表
        $content .= "\$genByNotes = true;\n\n";
        $content .= "// 临时校对表：\n";
        $content .= "\$tempMap = [\n";
        $content .= $this->buildMapSection($maps[NoteConstants::MAP_SAME],
            '【1】before 与 after 值相等');
        $content .= $this->buildMapSection($maps[NoteConstants::MAP_LACK],
            '【2】缺少对应的自动生成规则，需要及时补充到 fixedNoteRules 配置中');
        $content .= $this->buildMapSection($maps[NoteConstants::MAP_FIXED],
            '【3】通过固定规则自动生成');
        $content .= $this->buildMapSection($maps[NoteConstants::MAP_MARKS],
            '【4】增加排版标记');
        // 常规词条
        $content .= $this->buildMapSection($maps[NoteConstants::MAP_NORMAL]);
        $content .= "];\n";

        return $content;
    }

    /**
     * 构建额外信息部分
     */
    protected function buildExtraMessages(array $extraMsgs): string
    {
        if (empty($extraMsgs)) {
            return '';
        }

        $content = "// 额外提醒信息（以【！】开头的批注）：\n";
        $content .= "/*\n";
        $content .= Util::jsonEncode($extraMsgs);
        $content .= "\n*/\n\n";

        return $content;
    }

    /**
     * 构建 map 部分
     */
    protected function buildMapSection(array $map, string $description = ''): string
    {
        if (empty($map)) {
            return '';
        }

        return Util::getWordsPrintStr($map, $description, !empty($description));
    }

    /**
     * 转换单个固定规则（供外部调用）
     */
    public function convertSingleRule(array $fixedMap): string
    {
        if (empty($fixedMap)) {
            return '';
        }

        $result = $fixedMap[0] ?? '';
        if (!$result) {
            return '';
        }

        return $this->formatSingleResult($result['after']);
    }

    /**
     * 格式化单个结果
     */
    protected function formatSingleResult(string $content): string
    {
        $content = str_replace('\n　　[', "\n[", $content);
        $content = str_replace('\n　　【', "\n【", $content);
        $content = str_replace('\n　　※', "\n※", $content);
        $content = str_replace('\n', "\n", $content);
        $content = preg_replace('/([\[【])(行号|匹配项?)./u', '$1$2：', $content);

        return $content;
    }
}
