<?php

namespace App\Command;

use App\Exception\AppException;
use App\Util\Util;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;
use App\Service\Formatting\FileProcessor;

class RenameFilesForCompare extends Command
{
    protected static string $name = 'rename-files-for-compare';
    protected static string $desc = '比较文件时以基准文件名进行重命名';

    /**
     * @throws AppException
     */
    public function execute(Input $input, Output $output): void
    {
        $booksDir = BOOK_DIR;
        $booksBakDir = BOOK_BAK_DIR;

        // 先统一所有文件的排版格式
        FileProcessor::getProcessor()->publicChangeTextFormat();

        $targetBooknameMark = '！';
        $targetBooknameMark2 = '!';

        if (!is_dir($booksDir) || !is_dir($booksBakDir)) {
            throw new AppException('books 或 booksBak不可读，无法操作');
        }

        chdir($booksDir);

        // 清理备份目录的残留文件
        Util::recursiveDelete($booksBakDir, false);

        $targetFiles = [];
        $existedTargetFiles = []; // 重命名前刚好和【目标文件名】重名的文件，先移动到 booksBak
        foreach (scandir($booksDir) as $file) {
            if ($file === '.' || $file === '..') continue;
            $sourcePath = "$booksDir/$file";
            if (
                strpos($file, $targetBooknameMark) === 0
                || strpos($file, $targetBooknameMark2) === 0
            ) {
                // 收集目标文件名，将以“！”开头的文件作为基准
                $ext = Util::getFileExt($file);
                $baseName = mb_substr(Util::getFilename($file), 1);

                // 移除书名号和各种“校对”“精校”“文字”“全本”“作者”等多余说明
                $patterns = ['/《(.*?)》/u', '/[〔「『〖\[【（(](.*?)[)）】\] 〗』」〕]/u', '/(?:校对|作者)[:：].+/u'];
                $replacements = ['$1', '', ''];
                $cleanBaseName = preg_replace($patterns, $replacements, $baseName);
                $cleanBaseName = trim($cleanBaseName); // 移除可能产生的前后空格

                $targetFiles[] = $cleanBaseName;
                $targetFile = $cleanBaseName . "." . $ext;
                if (file_exists($targetFile)) { // 若文件名已存在，移动到 booksBak
                    rename("$booksDir/$targetFile", "$booksBakDir/$targetFile");
                    $existedTargetFiles[$targetFile] = true;
                }
                rename($file, $targetFile);
            } else if (!isset($existedTargetFiles[$file])) { // 检查是否已经将原有的 targetFile 移动到了 booksBak
                // 移动文件，将不是以“！”开头的文件移动到备份目录中
                $destPath = "$booksBakDir/$file";
                rename($sourcePath, $destPath);
            }
        }

        // 根据 targetFiles 重命名 booksBak 中的对应文件（文件名中包含对应的 targetFile）
        // 使 booksBak 和 books 中的命名一致
        foreach (scandir($booksBakDir) as $file) {
            if ($file === '.' || $file === '..') continue;
            foreach ($targetFiles as $k => $target) {
                if (str_contains($file, $target)) {
                    $newName = $target . '.' . pathinfo($file, PATHINFO_EXTENSION);
                    rename("$booksBakDir/$file", "$booksBakDir/$newName");
                    unset($targetFiles[$k]); // 每次找到就删除，避免重复匹配
                    $targetFiles = array_values($targetFiles);
                    break;
                }
            }
        }

        // 清理残留的压缩文件
        foreach (glob("$booksDir/*.{zip,rar,7z}", GLOB_BRACE) as $file) {
            unlink($file);
        }
    }
}
