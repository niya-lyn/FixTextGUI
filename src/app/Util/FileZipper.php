<?php

namespace App\Util;

use App\Exception\AppException;
use ZipArchive;

class FileZipper extends ZipArchive
{
    /**
     * @throws AppException
     */
    public function recursiveZip($entryPath, $destFile)
    {
        $entryPath = rtrim($entryPath, '/');
        if (!file_exists($entryPath)) {
            throw new AppException("文件路径有误：$entryPath");
        }

        $destFile = rtrim($destFile, '/');
        $res = $this->open($destFile, ZipArchive::CREATE | ZipArchive::OVERWRITE);
        if ($res === true) {
            $this->addDir($entryPath);
            $this->close();
        }
    }

    public function unzipTo($entryFile, $destPath)
    {
        $entryFile = rtrim($entryFile, '/');
        $destPath = rtrim($destPath, '/');
        if ($this->open($entryFile) === true) {
            // 此处逻辑暂时为如果目标目录存在就不解压
            if (!file_exists($destPath)) {
                mkdir($destPath);
                $this->extractTo($destPath);
            } else {
                echo "解压目标目录已存在：{$destPath}，无操作" . PHP_EOL;
            }
            $this->close();
        }
    }

    /**
     * 添加压缩包内部结构
     *
     * @param string $filePath 压缩包外文件路径
     * @param string $entryPath 压缩包内文件路径，为空就是从压缩包内根目录开始打包
     * @return void
     */
    protected function addDir(string $filePath, string $entryPath = '')
    {
        $entryPath && $this->addEmptyDir($entryPath);
        $entryPath && $entryPath .= '/';
        $filePath .= '/';
        $dir = opendir($filePath);
        while ($file = readdir($dir)) {
            if ($file == '.' || $file == '..') {
                continue;
            }
            if (is_dir($filePath . $file)) {
                $this->addDir($filePath . $file, $entryPath . $file);
            } else {
                $this->addFile($filePath . $file, $entryPath . $file);
            }
        }
    }
}
