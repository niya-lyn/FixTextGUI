<?php

namespace App\Service;

use App\Exception\AppException;
use App\Util\Util;
use App\Util\FileZipper;
use App\Util\Console\Show;
use App\Trait\FileWalkerTrait;

class EpubFixer
{
    use FileWalkerTrait;

    /**
     * 递归解压指定目录中的所有 epub 文件，并记录操作文件路径
     *
     * @param string $bookDir
     * @return void
     * @throws AppException
     */
    public function bulkExtractEpubs(string $bookDir): void
    {
        $this->setBeforeWalkFunc(function ($dir, $files) {
            $this->filesToWalk = $this->extractEpubs($dir, EPUB_EXTRACT_PREFIX);
        });

        $this->setInWalkFunc(function ($bookDir, $epubDir) {
            file_put_contents(EPUB_LIST_LOG, $epubDir . PHP_EOL, FILE_APPEND);
        });

        $this->walkFiles($bookDir);
    }

    /**
     * 根据前面解压操作中记录的 epub 解压文件夹路径，
     * 反向压缩文件夹，还原为 epub 文件，并覆盖原文件
     *
     * @return void
     * @throws AppException
     */
    public function bulkMakeEpubs(): void
    {
        $epubList = file_get_contents(EPUB_LIST_LOG);
        $epubDirs = explode(PHP_EOL, $epubList);
        foreach ($epubDirs as $epubDir) {
            if (!file_exists($epubDir)) {
                continue;
            }

            chdir(dirname(realpath($epubDir)));
            $arr = explode('/', $epubDir);
            $entryPath = end($arr);
            $bookName = str_ireplace(EPUB_EXTRACT_PREFIX, '', $entryPath);
            $this->packEpub($bookName, $entryPath);
        }

        // 删除原 epub 文件列表
        unlink(EPUB_LIST_LOG);
    }

    /**
     * 将 epub 文件中的所有文本文件合并成一个 txt 文件，便于到其他校对软件中进行校对
     *
     * @param string $bookDir
     * @return void
     * @throws AppException
     */
    public function bulkMergeEpubText(string $bookDir): void
    {
        if (self::findMergedEpubs()) {
            return; // 无操作，不用抛异常
        }

        Show::opStart(' EPUB 文本合并');
        $this->setBeforeWalkFunc(function ($dir, $files) {
            $this->filesToWalk = $this->extractEpubs($dir, EPUB_MERGE_PREFIX);
            $this->printDir = false;
            $this->printFinished = false;
        });

        $this->setInWalkFunc(function ($bookDir, $epubDir) {
            $dirnameArr = explode('/', $epubDir);
            $epubFilename = $dirnameArr[array_key_last($dirnameArr)];

            if (str_contains($bookDir, BOOK_BAK_DIR)) {
                $logName = EPUB_MERGE_LOG_DIR . '/' . 'bak_' . $epubFilename;
            } else {
                $logName = EPUB_MERGE_LOG_DIR . '/' . $epubFilename;
            }
            $logName .= '_' . mt_rand(10000, 99999) . '.log';    // 日志记录文件，加入随机数是想处理不同文件夹内同一文件名的情况
            $mergedFilePath = $bookDir . "/{$epubFilename}.txt"; // 合并后的 txt 文件

            $logInfo = [
                'extractedBookDir' => $epubDir,          // 原书籍解压文件路径
                'mergedFilePath'   => $mergedFilePath,   // 合并后的 txt 文件路径
                'origFilenames'    => [],                // 原文件列表
            ];

            // 扫描文本文件，进行合并操作
            $textFilesRet = $this->getEpubTextFiles($epubDir);
            chdir($textFilesRet['opfFileDir']);
            $mergeContent = '';
            foreach ($textFilesRet['files'] as $filename) {
                if (!file_exists($filename)) {
                    continue;
                }

                $mergeContent .= file_get_contents($filename) . "\n";

                $filepath = $textFilesRet['opfFileDir'] . "/" . $filename;
                $logInfo['origFilenames'][] = $filepath;
            }

            // 写入合并文件，文件内容统一用 \n 换行
            $mergeContent = str_replace("\r\n", "\n", $mergeContent);
            file_put_contents($mergedFilePath, $mergeContent);

            // 写入 log 文件
            file_put_contents($logName, Util::jsonEncode($logInfo));
        });

        $this->walkFiles($bookDir);
        Show::opEnd();
    }

    /**
     * @throws AppException
     */
    public function mergeAllEpubText(): void
    {
        $this->bulkMergeEpubText(BOOK_BAK_DIR);
        $this->bulkMergeEpubText(BOOK_DIR);
    }

    /**
     * @throws AppException
     */
    public function bulkSplitEpubs(): void
    {
        Show::opStart(' EPUB 文本拆分还原');
        $this->setBeforeWalkFunc(function ($logDir, $files) {
            $this->filesToWalk = Util::globOnlyFiles('*.log');
            $this->printDir = false;
            $this->printFinished = false;
        });

        $this->setInWalkFunc(function ($logDir, $log) {
            $logInfo = json_decode(file_get_contents($log), true);

            $extractedBookDir = $logInfo['extractedBookDir'];
            $mergedFilePath   = $logInfo['mergedFilePath'];
            $origFilenames    = $logInfo['origFilenames'];

            if (!file_exists($mergedFilePath)) {
                return;
            }

            $this->splitByHtmlEnd($origFilenames, $mergedFilePath);

            // 进入原书籍解压文件夹，重新打包 epub，覆盖原文件
            chdir(dirname(realpath($extractedBookDir)));
            $arr = explode("/", $extractedBookDir);
            $entryPath = end($arr);
            $bookName = str_ireplace(EPUB_MERGE_PREFIX, "", $entryPath);
            $this->packEpub($bookName, $entryPath);

            chdir(EPUB_MERGE_LOG_DIR);
            unlink($log);
        });

        $this->walkFiles(EPUB_MERGE_LOG_DIR);
        Show::opEnd();
    }

    public static function findMergedEpubs(): bool
    {
        chdir(BOOK_DIR);
        $files = Util::globOnlyFiles();
        $found = false;
        foreach ($files as $file) {
            if (str_starts_with($file, EPUB_MERGE_PREFIX)) {
                $found = true;
                break;
            }
        }

        return $found;
    }

    /**
     * @throws AppException
     */
    public function deDrm(string $bookDir): void
    {
        $this->setBeforeWalkFunc(function ($bookDir, $files) {
            $this->filesToWalk = Util::globOnlyFiles('*.epub');
        });

        $this->setInWalkFunc(function ($bookDir, $bookEpub) {
            $destDir = 'tempDest';
            !is_dir($destDir) && mkdir($destDir);
            (new DeDrmWriter)->doDeDrm($bookEpub, $destDir);
            $this->packEpub('【已解密】' . Util::getFilename($bookEpub), $destDir);
        });

        $this->walkFiles($bookDir);
    }

    protected function extractEpubs(string $bookDir = "", string $bookPrefix = ""): array
    {
        $epubDirs = [];
        $epubFiles = Util::globOnlyFiles('*.epub');
        foreach ($epubFiles as $bookEpub) {
            $bookName = basename($bookEpub, '.epub');
            $bookName = $bookPrefix . $bookName;
            $bookZip = "$bookName.zip";
            $bookDir = $bookDir ?: TextFixer::getInstance()->getBookDir();
            $epubDirs[] = "$bookDir/$bookName"; // 注意目录格式
            rename($bookEpub, $bookZip);
            (new FileZipper())->unzipTo($bookZip, $bookName);
            rename($bookZip, $bookEpub);
        }

        return $epubDirs;
    }

    /**
     * @throws AppException
     */
    public function packEpub(string $bookName, string $entryPath = '', bool $deleteEntryDir = true): void
    {
        $entryPath = $entryPath ?: $bookName;
        $bookZip = "$bookName.zip";
        $bookEpub = "$bookName.epub";
        (new FileZipper())->recursiveZip($entryPath, $bookZip);
        file_exists($bookEpub) && unlink($bookEpub);
        rename($bookZip, $bookEpub);
        $deleteEntryDir && Util::recursiveDelete($entryPath);
    }

    protected function splitByHtmlEnd(array $origFilenames, string $mergedFilePath): void
    {
        $content = file_get_contents($mergedFilePath);

        // 被 python 等外部程序修改后，换行符可能变成 \r\n
        Util::changeEncodingAndNewLineType($content);

        // 规范 html 标签，以防万一
        $content = str_ireplace(
            ["HTML>", "</html><", "</html>\n\n"],
            ["html>", "</html>\n<", "</html>\n"],
            $content
        );

        $delimiter = "</html>\n";
        $chapters = explode($delimiter, $content);
        $chapterCount = count($chapters);
        foreach ($chapters as $k => $v) {
            $k != $chapterCount - 1 && $chapters[$k] = $v . $delimiter;
            $chapters[$k] = str_replace("\n<?xml", "<?xml", $chapters[$k]);
        }

        foreach ($origFilenames as $k => $origFilename) {
            if (!is_file($origFilename)) {
                continue;
            }

            file_put_contents($origFilename, $chapters[$k]);
        }

        // 每次拆分还原完成后，删除原合并文本
        unlink($mergedFilePath);
    }

    /**
     * 解析根文件读取文本列表
     *
     * @param string $epubDir
     * @return array
     * @throws AppException
     */
    protected function getEpubTextFiles(string $epubDir): array
    {
        chdir($epubDir);

        if (!file_exists('META-INF/container.xml')) {
            throw new AppException("无法定位 {$epubDir} 的 container.xml，请使用 Calibre 或 Sigil 规范 epub 文件结构");
        }

        $containerXml = simplexml_load_file('META-INF/container.xml');
        if (!$containerXml) {
            throw new AppException("{$epubDir} 的 container.xml 解析有误");
        }

        if (!isset($containerXml->rootfiles->rootfile)) {
            throw new AppException("{$epubDir} 的 container.xml 未正确设置 rootfile");
        }

        if (count($containerXml->rootfiles->rootfile) != 1) {
            throw new AppException("{$epubDir} 的 container.xml 内的 opf 文件数量有误，目前脚本只支持含有 1 个 opf 的 epub");
        }

        $rootFilepath = $containerXml->rootfiles->rootfile[0]['full-path'];
        if (!file_exists($rootFilepath)) {
            throw new AppException("{$epubDir} 的 opf 文件路径有误");
        }
        $opfFileDir = dirname(realpath($rootFilepath));

        $contentXml = simplexml_load_file($rootFilepath);
        if (!$contentXml) {
            throw new AppException("{$epubDir} 的 opf 文件解析有误");
        }

        if (!isset($contentXml->manifest->item) || !isset($contentXml->spine->itemref)) {
            throw new AppException("{$epubDir} 的根文件中 manifest 及 spine 段设置有误，请使用 Calibre 或 Sigil 规范 epub 文件结构");
        }

        $manifestItems = $contentXml->manifest->item;
        $spineItems = $contentXml->spine->itemref;

        // 提取 manifest 中的文件
        $manifest = [];
        foreach ($manifestItems as $item) {
            $href = (string)$item['href'];
            $id = (string)$item['id'];
            $manifest[$id] = $href;
        }

        // 提取 spine 中的顺序
        $spine = [];
        foreach ($spineItems as $item) {
            $idref = (string)$item['idref'];
            $manifestHref = $manifest[$idref];

            // 排除 3.0 导航页
            if (str_starts_with($idref, 'nav.') || $manifestHref == 'nav.xhtml') {
                continue;
            }

            $spine[] = $manifestHref;
        }

        // 按照 spine 的顺序获取文件名
        $files = [];
        foreach ($spine as $item) {
            $files[] = $item;
        }

        return compact('files', 'opfFileDir');
    }
}
