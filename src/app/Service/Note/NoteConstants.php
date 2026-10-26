<?php

namespace App\Service\Note;

/**
 * 批注处理相关常量定义
 */
class NoteConstants
{
    // 批注规则标记
    const WORD_SEPERATOR = '#';             // word1#word2#word3... 分隔每种规则
    const WORD_CONVERTER = '@';             // a@b，表示 a->b 的转换
    const ADD_CHARS      = '+';             // aa@+bb，表示在 aa 后补充 bb
    const RM_RQUOTATION  = ['”', '“”'];     // 移除连续上下文中的后引号
    const CV_QUOTATION   = ['’', '‘’'];     // 单双引号互转
    const RM_REPETITION  = '-';             // 移除叠字叠词，a- 会将 aa 变为 a
    const AN_2_CN        = ['==', '%%'];    // 表示阿拉伯数字转中文数字
    const CN_2_AN        = ['===', '%%%'];  // 表示中文数字转阿拉伯数字

    // 对多行内容的操作
    const ADD_STAR_SEPARATOR     = ['-', '—'];    // 表示在上方增加※※※分隔行
    const ADD_ELLIPSIS_SEPARATOR = ['。。', '..'];  // 表示在上方增加省略号分隔行
    const MERGE_LINES            = '++';          // 合并选中的多行内容
    const RM_ENDCHAR_MERGE_LINES = '+++';         // 移除当前行末尾的多余标点，然后和下一行合并。有些人乱改硬回车，粗暴地在每一个断行末尾都加句号之类的，就有可能需要这样还原

    // 定位标记（涉及的字符位置，只能处于 1-9 之间）
    //
    // 非数字开头的【。。xy】等同于【。。1=xy】，从第 1 个字符开始，用 xy 替换后续字符（这个是最简单的写法）
    // 支持使用空格来右移位置（或使用【。】来代替空格，可以写成【。。。xy】，表示从第 2 个字符开始，用 xy 替换后续字符）
    // 同上面的写法，支持【。。-】和【 。。+xy】的转换（非数字开头），也支持空格右移
    //
    // 【。。12@xy】，表示将第 1、2 个的字符对应换成 xy，或可简写成【。。15xy】，将第 1 个字符换成 x，第 5 个字符换成 y，省去 @
    // 【。。1！】。在第 1 个字符后面追加！（如果是特定的标点，直接追加）
    // 【。。1=abc】，从第 1 个字符开始（包括第 1 个字符），将第 1、2、3 个字符换成 abc（取决于 abc 的长度），相当于是【。。123@abc】，但不用写多个位置
    // 【。。1+xy】。表示在第 1 个字符后增加 xy
    // 【。。12-】，表示移除第 1、2 个字符
    // 【。。2！！】，表示在 2 个字符后面增加换行
    const LOCATOR_START            = '。。';
    const LOCATE_THEN_CONVERT      = '@';
    const LOCATE_THEN_ADD          = '+';
    const LOCATE_THEN_DEL          = '-';
    const LOCATE_THEN_REPLACE      = '=';
    const LOCATE_THEN_ADD_NEW_LINE = '！！';

    // 特殊转义标记
    const EXTRA_MSG_ESCAPER_1 = '！';
    const EXTRA_MSG_ESCAPER_2 = '!';
    const SAME_MAP_ESCAPER_1  = '！！';
    const SAME_MAP_ESCAPER_2  = '!!';

    // 特殊引文标记 [标记符 => [开始符, 结束符, 描述]]
    const SPECIAL_MARKS = [
        '##'   => ['【', '】', '保留标记的引文'],
        '@@'   => ['〖', '〗', '不保留标记的引文'],
        '@@@'  => ['〖〖', '〗〗', '右对齐'],
        '@@@@' => ['【【', '】】', '左顶格'],
    ];

    // 批注分类
    const MAP_SAME       = 'same';       // before 与 after 值相等
    const MAP_LACK       = 'lack';       // 缺少对应规则的词条
    const MAP_FIXED      = 'fixed';      // 通过规则自动生成的词条
    const MAP_MARKS      = 'marks';      // 增加排版标记
    const MAP_NORMAL     = 'normal';     // 常规词条
    const MAP_EXTRA_MSGS = 'extraMsgs';  // 额外信息
}
