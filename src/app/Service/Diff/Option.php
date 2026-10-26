<?php

namespace App\Service\Diff;

class Option
{
    public int $replaceCountThreshold = 0;      // 表示只有重复替换次数大于此值的词条需要进行报告
    public int $contextLen            = 3;      // 截取的差异字符上下文长度
    public int $removeLOrRChar        = 0;      // 0-不移除；大于 0-移除头部对应长度字符；小于 0-移除尾部对应长度字符
    public bool $filterKeywords       = false;  // 是否依据特定关键字进行筛选
    public bool $getMultiLineContent  = false;  // 是否需要提取跨行差异
    public bool $trimPunctuations     = false;  // 是否需要移除每处差异的首尾标点符号
    public bool $addHtmlStrippedCopy  = true;   // 是否另外存一份移除了 html 标签的内容
    public bool $addCurrentTime       = true;   // 是否记录当前时间
}
