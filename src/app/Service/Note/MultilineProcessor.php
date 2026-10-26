<?php

namespace App\Service\Note;

use App\Util\Util;

/**
 * 多行批注处理器
 */
class MultilineProcessor
{
    protected string $bookExt;

    public function __construct(string $bookExt)
    {
        $this->bookExt = $bookExt;
    }

    /**
     * 合并多行批注的变体
     */
    public function mergeMultilineVariants(array $note): array
    {
        $beforeHasNewline = Util::multiStrContains($note['before'], ['\n', "\n"]);
        $afterHasNewline = Util::multiStrContains($note['after'], ['\n', "\n"]);

        // 确定需要处理的字段
        $fields = [];
        if ($beforeHasNewline) {
            $fields[] = 'before';
        }
        if ($afterHasNewline) {
            $fields[] = 'after';
        }

        // 如果没有多行内容，则直接将 note 包装一层后返回
        if (empty($fields)) {
            return [$note];
        }

        return $this->createMultilineVariants($note, $fields);
    }

    /**
     * 创建多行变体
     */
    protected function createMultilineVariants(array $note, array $fields): array
    {
        $variants = $this->getNewlineVariantsByBookExt();
        $notes = [];

        foreach ($variants as $variant) {
            $newNote = $note;
            foreach ($fields as $field) {
                // 顺序不能乱：先替换 \n，再替换 真实换行符
                $newNote[$field] = str_replace(['\n', "\n"], $variant, $note[$field]);
            }
            $notes[] = $newNote;
        }

        return $notes;
    }

    /**
     * 根据书籍格式获取换行符变体
     */
    protected function getNewlineVariantsByBookExt(): array
    {
        if ($this->bookExt == "txt") {
            return ['\n　　'];
        }

        // epub 格式，暂时最多处理两层缩进
        return [
            '</p>\n    <p>',
            '</p>\n  <p>',
        ];
    }
}
