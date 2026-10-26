<?php

namespace App\Command;

use Exception;
use App\Util\Util;
use App\Service\EpubFixer;
use App\Util\Console\Show;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;

class MergeEpubText extends Command
{
    protected static string $name = 'merge-epub-text';
    protected static string $desc = '合并所有 epub 的文本，原样转成 txt';

    /**
     * @throws Exception
     */
    public function execute(Input $input, Output $output): void
    {
        chdir(BOOK_DIR);

        $fixer = new EpubFixer();
        $action = Util::getArgvByIndex(3);
        if ($action === 'delete') {
            // 删除原有的 epub 文件
            $fixer->bulkSplitEpubs();
            $inputFile = Util::getArgvByIndex(2); // 这个是带前缀的 txt 文件名，需要转成对应的 epub 文件名
            $epubFile = str_replace([EPUB_MERGE_PREFIX, '.txt'], '', $inputFile) . '.epub';
            unlink($epubFile);
        } else {
            // 递归合并 booksBak 和 books 文件夹中的所有 epub 文本文件
            $fixer->bulkSplitEpubs(); // 合并前检查原先是否有已合并文件，有则拆分之
            $fixer->mergeAllEpubText();

            Show::successWithNL('操作已完成');
            Show::primary("【注意】这个命令是将 epub 的文本原样转为 txt，所有的 html 标签都完整保留。\n"
                . '如果需要将 epub 的文本内容提取为纯文本（不含 html 标签），'
                . '请使用【0.文本排版.bat】中的【提取 epub 中的文本】功能。');
        }
    }
}
