<?php

namespace App\Service;

use App\Exception\AppException;
use App\Util\Util;
use App\Util\FileZipper;

class DeDrmWriter
{
    protected array $existedDirs              = [];
    protected array $filenameMap              = [];
    protected array $urlEncodedFilenameMap    = [];
    protected array $unescapedStarFilenameMap = [];
    protected array $destFileList             = [];

    public function doDeDrm(string $bookEpub, string $destDir): void
    {
        $fileZipper = new FileZipper();
        if ($fileZipper->open($bookEpub) !== true) {
            throw new AppException('无法打开或处理 EPUB 文件：' . $bookEpub);
        }

        for ($i = 0; $i < $fileZipper->numFiles; $i++) {
            $this->writeToDestDir($destDir, $i, $fileZipper);
        }

        $this->replaceDestFileContent();
    }

    protected function writeToDestDir(string $destDir, int $fileIndex, FileZipper $fileZipper): void
    {
        $filename = $fileZipper->getNameIndex($fileIndex);
        $filename = str_replace('\\', '/', $filename);
        $nameParts = explode('/', $filename);
        $partCount = count($nameParts);

        foreach ($nameParts as $k => $namePart) {
            $destFilename = $this->processDestFilename($namePart, $fileIndex);

            if ($k < $partCount - 1) { // 处理子目录
                $destDir .= "/{$destFilename}";

                if (!isset($this->existedDirs[$destDir])) {
                    $this->existedDirs[$destDir] = true;
                    mkdir($destDir, 0755, true);
                }
            } else { // 处理文件名
                if (!$namePart) {
                    continue;
                }

                if ($namePart == 'encryption.xml') {
                    continue;
                }

                $destFilePath = $destDir . "/{$destFilename}";
                $this->destFileList[] = $destFilePath;

                $content = $fileZipper->getFromIndex($fileIndex);
                file_put_contents($destFilePath, $content);
            }
        }
    }

    protected function processDestFilename(string $namePart, int $fileIndex): string
    {
        if (!str_contains($namePart, ':') && !str_contains($namePart, '*')) {
            return $namePart;
        }

        if (isset($this->filenameMap[$namePart])) {
            return $this->filenameMap[$namePart];
        }

        if (str_contains($namePart, '~slim')) {
            $prevIndex = $fileIndex - 1;
            $destFilename = "file{$prevIndex}~slim"; // 处理全面屏图片
        } else {
            $destFilename = "file{$fileIndex}";
        }

        $fileExt = Util::getFileExt($namePart);
        if ($fileExt) {
            $destFilename .= ".{$fileExt}";
        }

        $urlencodedName = urlencode($namePart);
        $unescapedStarName = str_replace('%2A', '*', $urlencodedName);

        $this->filenameMap[$namePart] = $destFilename;
        $this->urlEncodedFilenameMap[$urlencodedName] = $destFilename;
        $this->unescapedStarFilenameMap[$unescapedStarName] = $destFilename;

        return $destFilename;
    }

    protected function replaceDestFileContent(): void
    {
        $replExts = ['html', 'htm', 'xhtml', 'xhtm', 'xml', 'opf', 'ncx', 'js', 'css'];

        // 构建完整的映射表
        $wholeMap = array_merge(
            $this->filenameMap,
            $this->urlEncodedFilenameMap,
            $this->unescapedStarFilenameMap
        );

        foreach ($this->destFileList as $destFilePath) {
            $destFileExt = Util::getFileExt($destFilePath);
            if (!in_array($destFileExt, $replExts)) {
                continue;
            }

            $content = file_get_contents($destFilePath);
            $newContent = strtr($content, $wholeMap);

            // 只在内容有变化时才写入
            if ($newContent !== $content) {
                file_put_contents($destFilePath, $newContent);
            }
        }
    }
}
