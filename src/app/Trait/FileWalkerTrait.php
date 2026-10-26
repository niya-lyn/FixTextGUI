<?php

namespace App\Trait;

use Exception;
use App\Util\Util;
use App\Service\TextFixer;
use App\Util\Console\Show;
use App\Util\Console\Color;

trait FileWalkerTrait
{
    /**
     * 如果在 beforeWalkFunc 中设置了此项，则以这个值作为遍历处理的文件列表
     * 否则默认扫描 *.{txt} 获取文件列表
     *
     * @var array
     */
    protected array $filesToWalk = [];

    /**
     * 遍历文件列表前回调
     * 形式为：beforeWalkFunc($dir, $files)
     *
     * @var callable|null
     */
    protected $beforeWalkFunc;

    /**
     * 处理列表中的单个文件时回调
     * 形式为：inWalkFunc($dir, $file)
     *
     * @var callable|null
     */
    protected $inWalkFunc;

    /**
     * 遍历文件列表后回调
     * 形式为：afterWalkFunc($dir, $files)
     *
     * @var callable|null
     */
    protected $afterWalkFunc;

    /**
     * 是否打印目录信息
     * 需要在 beforeWalkFunc 中设置
     *
     * @var bool
     */
    protected bool $printDir = true;

    /**
     * 是否打印开始信息
     * 需要在 beforeWalkFunc 中设置
     *
     * @var bool
     */
    protected bool $printStarted = true;

    /**
     * 是否打印完成信息
     * 需要在 beforeWalkFunc 中设置
     *
     * @var bool
     */
    protected bool $printFinished = true;

    /**
     * 附加的进度打印信息，基本没啥用
     *
     * @var string
     */
    protected string $extraProgressInfo = '';

    /**
     * @throws Exception
     */
    public function walkFiles(string $dir, array $exts = ['txt']): void
    {
        Util::recursiveFileActionHook($dir, [$this, "walkFiles"]);

        // 过滤被此脚本合并产生的 epub 解压目录
        if (str_contains($dir, EPUB_MERGE_PREFIX)) {
            return;
        }

        chdir($dir);
        $extsStr = implode(',', $exts);
        $this->filesToWalk = Util::globOnlyFiles("*.{{$extsStr}}");

        if (is_callable($this->beforeWalkFunc)) {
            call_user_func_array($this->beforeWalkFunc, [$dir, $this->filesToWalk]);
        }

        // 纯粹是为了在 Windows 下打印反斜杠，这里如果直接覆盖 dir 变量，会导致后续路径替换出错
        $realDir = realpath($dir);
        if ($this->printDir) {
            Show::write(">>>>>>> 进入目录：【{$realDir}】 >>>>>>>");
        }

        $count = count($this->filesToWalk);
        foreach ($this->filesToWalk as $key => $file) {
            if ($this->printStarted) {
                self::printFileProgress($file, $key, $count);
            }

            call_user_func_array($this->inWalkFunc, [$dir, $file]);

            if ($this->printFinished) {
                self::printFileProgress($file, $key, $count, 1, $this->extraProgressInfo);
                $this->extraProgressInfo = "";
            }
        }

        if (is_callable($this->afterWalkFunc)) {
            call_user_func_array($this->afterWalkFunc, [$dir, $this->filesToWalk]);
        }

        if ($this->printDir) {
            Show::write("<<<<<<< 离开目录：【{$realDir}】 <<<<<<<");
        }
    }

    public function disablePrint(): void
    {
        $this->printDir      = false;
        $this->printStarted  = false;
        $this->printFinished = false;
    }

    public function enablePrint(): void
    {
        $this->printDir      = true;
        $this->printStarted  = true;
        $this->printFinished = true;
    }

    /**
     * @param callable $func 形式为：function($dir, $files)
     * @return void
     */
    public function setBeforeWalkFunc(callable $func): void
    {
        $this->beforeWalkFunc = $func;
    }

    /**
     * @param callable $func 形式为：function($dir, $file)
     * @return void
     */
    public function setInWalkFunc(callable $func): void
    {
        $this->inWalkFunc = $func;
    }

    /**
     * @param callable $func 形式为：function($dir, $files)
     * @return void
     */
    public function setAfterWalkFunc(callable $func): void
    {
        $this->afterWalkFunc = $func;
    }

    protected static function printFileProgress(string $filename, int $key, int $count, int $state = 0, string $extraInfo = ""): void
    {
        $curKey = $key + 1;
        $bytes = is_dir($filename) ? Util::getDirSize($filename) : filesize($filename);
        $fileSize = Util::bytesToReadableSize($bytes);
        $time = Util::getTimeStr();
        $printName = str_replace(TextFixer::getInstance()->getBookDir(), "", $filename);

        $info = $state == 0 ? '处理中：' : '已完成：';
        $info .= str_pad("$curKey/$count", 8)
            . ' 当前时间：' . str_pad($time, 12)
            . ' 文件大小：' . str_pad($fileSize, 10)
            . ' 文件名：' . $printName . $extraInfo
            . PHP_EOL;

        if ($state === 0) {
            Show::write(Color::yellow($info), false);
        } else if ($state === 1) {
            Show::write(Color::green($info), false);
        }
    }
}
