<?php

namespace App\Service\Note;

/**
 * 标签变体处理器 - 专门用于 EPUB 格式下的标点符号变体生成
 */
class TagVariantWrapper
{
    protected string $bookExt;

    // 定义需要处理的成对标点及其对应的 CSS 类
    protected array $tagMap = [
        'quote-2'   => ['【', '】', '“', '”', '‘', '’'],
        'bracket-1' => ['（', '）'],
        'bracket-2' => ['《', '》'],
    ];

    public function __construct(string $bookExt)
    {
        $this->bookExt = $bookExt;
    }

    /**
     * 合并变体
     * 如果是 epub，返回 [原文, 加了标签的变体]
     * 否则返回 [原文]
     */
    public function processTagVariants(array $note): array
    {
        // 只有 epub 格式需要生成标签变体
        if ($this->bookExt !== 'epub') {
            return [$note];
        }

        $variantNote = $note;
        $fields = ['before', 'after'];
        $hasChanged = false;

        foreach ($fields as $field) {
            if (isset($variantNote[$field]) && !empty($variantNote[$field])) {
                $originalText = $variantNote[$field];
                $processedText = $this->applyEpubTags($originalText);

                if ($processedText !== $originalText) {
                    $variantNote[$field] = $processedText;
                    $hasChanged = true;
                }
            }
        }

        // 如果内容有变化，返回包含变体的数组；否则只返回原文
        return $hasChanged ? [$note, $variantNote] : [$note];
    }

    /**
     * 执行标签包装逻辑
     */
    protected function applyEpubTags(string $text): string
    {
        // 1. 处理完整成对的情况
        // 【测试】 -> <span class="quote-2">【测试】</span>
        foreach ($this->tagMap as $class => $puncts) {
            // 每两个一组，生成正则表达式
            for ($i = 0; $i < count($puncts); $i += 2) {
                $open = preg_quote($puncts[$i], '/');
                $close = preg_quote($puncts[$i + 1], '/');

                // 匹配成对标点，内部不包含同类结束标点
                $pattern = "/{$open}([^$close]+){$close}/u";
                $replacement = "<span class=\"{$class}\">{$open}$1{$close}</span>";
                $replacement = str_replace('"', '\"', $replacement);  // html 代码中的引号需要转义
                $text = preg_replace($pattern, $replacement, $text);
            }
        }

        // 2. 处理孤立的后标点（非完整标点逻辑）
        // 如果后标点前方是 [\dA-Za-z一-﨩]，且该标点后面没有紧跟 </span> (说明不是第一步刚处理过的)
        $charRange = '0-9a-zA-Z一-﨩';
        $closePuncts = '》';
        // $closePuncts = '”’】）'; // 如果在这些括号和引号前补标点，可能导致修改后标签丢失

        // 正则解释：
        // ([...]) : 捕获前面的一个字符
        // ([$closePuncts]) : 捕获后标点
        // (?!<\/span>) : 负向断言，确保该标点后面不是刚才处理完的闭合标签，防止重复
        $patternOrphan = "/([$charRange])([$closePuncts])(?!<\/span>)/u";

        // 替换为：字符 + 后标点 + </span>
        $text = preg_replace($patternOrphan, '$1$2</span>', $text);

        return $text;
    }
}
