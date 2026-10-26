<?php
/**
 * php_harness.php — FixText 引号检查 · PHP 原版参照装备
 *
 * 目的：以【未经修改的】FixText src/app/Service/Quotation/QuotationChecker.php 检测逻辑为基准，
 * 驱动其对给定文本文件执行一轮完整的引号检查，输出 JSON 事件流（每处报错一条）。
 *
 * 等价性说明（与原版 `check-quotation-marks` 命令的 'c'（只统计错误数）模式的对应关系）：
 *  - 原命令在统计模式下：第一遍撞到第一处报错 → directCount=true 并从文件头重读；
 *    第二遍从头到尾，每处 dumpErr 计 1 次错误数。因此
 *    错误总数 == 单遍全文件扫描（初始状态干净、directCount=true）中 dumpErr 的调用次数。
 *  - 本 harness 即以该单遍扫描语义运行，并把 dumpErr 的【交互式报告/修复链】替换为事件记录
 *    （原 dumpErr 在统计模式下本来就会抛 DirectSkipException 跳过交互，行为一致）。
 *  - 检测逻辑本身（checkLeftSingles/RightSingles/LeftDoubles/RightDoubles/checkEOL/
 *    checkMissingRightQuote/checkLeftQuotePrevChar/searchForRightQuote/processLines 等）
 *    全部来自原文件，一行未改；仅覆盖了纯展示性的 printProgressInfo。
 *
 * 用法：php php_harness.php <FixText/src 目录> <文件1> [文件2 ...]
 * 输出：每文件一行 JSON：{"file":..., "errCount":N, "events":[{"line":..,"char":..,"msg":..}]}
 */

if ($argc < 3) {
    fwrite(STDERR, "usage: php php_harness.php <FixText/src dir> <file...>\n");
    exit(1);
}

$fixtextSrc = rtrim($argv[1], '/');
require $fixtextSrc . '/vendor/autoload.php';
mb_internal_encoding("UTF-8");
ini_set("memory_limit", "2048M");

use App\Exception\Quotation\DirectSkipException;
use App\Service\Quotation\QuotationChecker;

class CountHarness extends QuotationChecker
{
    public array $events = [];

    public function runFile(string $path): array
    {
        $this->events = [];
        $this->ctx->filename = basename($path);
        $this->ctx->filepath = $path;
        $this->ctx->lineArr = file($path);
        $this->ctx->lineCount = count($this->ctx->lineArr);
        // 统计模式第二遍的等价单遍语义
        $this->ctx->getErrCount = true;
        $this->ctx->directCount = true;
        $this->ctx->fixSingles = false;
        $this->ctx->fromGUI = false;
        $this->ctx->startLine = 0;

        $this->processLines();
        return $this->events;
    }

    /**
     * 与原版 dumpErr 的【统计模式分支】行为一致：记录进度、计数、抛 DirectSkipException。
     * 去掉的只有交互式上下文打印与 Fixer 修复链（统计模式下二者均不会执行到）。
     */
    protected function dumpErr(string $errMsg = ''): void
    {
        $this->ctx->progressLineKey = $this->ctx->lineKey;
        $this->ctx->progressLineCount = $this->ctx->lineCount;

        $this->events[] = [
            'line' => $this->ctx->lineKey + 1,
            'char' => $this->ctx->charKey,
            'msg' => $errMsg,
        ];

        if ($this->ctx->getErrCount) {
            $this->ctx->directCount && $this->ctx->errCount++;
            throw new DirectSkipException();
        }
        throw new DirectSkipException();
    }

    /** 纯展示性进度打印，覆盖为空以免污染 JSON 输出 */
    protected function printProgressInfo(): void
    {
    }
}

$files = array_slice($argv, 2);
foreach ($files as $f) {
    $h = new CountHarness();
    $events = $h->runFile($f);
    echo json_encode(
        ['file' => basename($f), 'errCount' => count($events), 'events' => $events],
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
    ), "\n";
}
