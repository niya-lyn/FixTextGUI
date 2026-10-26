<?php

namespace App\Service\Formatting;

class Option
{
    public string $toEncoding             = "UTF-8";
    public string $newLineType            = "\n";
    public bool $changeTextFormat         = false;          // 处理空行、缩进等排版
    public bool $addIndentation           = true;           // 若为 false，就是去除所有缩进和空行，强制让文本格式一致
    public int $addHtmlTag                = 0;              // 0-保持原样 1-套上 p 标签 2-移除 p 标签
    public int $consecutiveQuotationsType = 0;              // 0-保持原样 1-使用规范的多行引号形式 2-在连续段落中仅保留开头结尾引号
    public bool $extractTextFromHtml      = false;          // 从 epub 中提取文本，转为 txt
    public bool $setExtraTextInfo         = false;          // 开启时，会自动给从 epub 提取的 txt 文本增加论坛信息和书籍信息
    public bool $normalizePunctuations    = false;          // 规范标点符号
    public int $quotationType             = 0;              // 0-保持原样 1-弯引号 2-直角引号
    public bool $addOpInfo                = false;          // 添加论坛信息
    public int $changeCaseInText          = 0;              // 0-保持原样 1-英文首字母大写 2-所有英文改成小写 3-所有英文改成大写 4-只改固定词组
    public bool $arabicToChineseNum       = false;          // 将六位及以下的一些阿拉伯数字改成中文
    public bool $rmSpacesBetweenChnChars  = false;          // 移除中文间的空格
    public int $splitByPunctuations       = 0;              // 0-保持原样 1-按照标点分行 2-去除分行标记，还原分行
    public string $punctuationPartBreak   = "\n【brk】\n";
    public bool $paranoidTextSpacing      = false;          // 在中文字符和英文字母、数字之间【添加空格】
    public bool $formatHeadings           = false;          // 自动给含 ◎ 的标题分级，生成可被分章插件识别的标题标记
    public int $processSpecialChars       = 0;              // 1-给特殊字符（包括 Emoji）添加标记，转义为可识别的 Unicode 码点表示 2-移除标记，还原特殊字符
    public int $specialCharsScope         = 0;              // 0-处理所有字符 1-只处理 CJK 扩展区的生僻字

    public function isDefaultEncoding(): bool
    {
        return $this->toEncoding == "UTF-8" && $this->newLineType == "\n";
    }
}
