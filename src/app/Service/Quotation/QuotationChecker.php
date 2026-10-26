<?php

namespace App\Service\Quotation;

use App\Util\Util;
use App\Service\EpubFixer;
use App\Util\Console\Color;
use App\Trait\FileWalkerTrait;
use App\Exception\AppException;
use App\Service\Quotation\QuotationUi;
use App\Service\Quotation\QuotationFixer;
use App\Service\Quotation\QuotationContext;
use App\Exception\Quotation\DirectSkipException;
use App\Exception\Quotation\ReloadThenSkipException;

class QuotationChecker
{
    use FileWalkerTrait;

    protected QuotationContext $ctx;
    protected QuotationUi $ui;
    protected QuotationFixer $fixer;

    const OP_EXIT          = 1;
    const OP_FORCE_SKIP    = 'x';
    const OP_FORCE_FIX     = 'f';
    const OP_GET_ERR_COUNT = 'c';

    const REREAD_DIFF_THRESHOLD = 0.001;
    const REWIND_LINES          = 200;
    const PROGRESS_STEP         = 10000;
    const SEARCH_FOR_RD_LINES   = 100;
    const FETCH_CONTEX_LINES    = 2;
    const GUI_EXTRA_LINES       = 30;
    const MAX_OUTPUT_LEN        = 15000;

    public function __construct()
    {
        $this->ctx   = new QuotationContext();
        $this->ui    = new QuotationUi();
        $this->fixer = new QuotationFixer($this->ctx, $this->ui);
    }

    public function process(): void
    {
        if (Util::isFromGUI()) {
            $this->ctx->fromGUI = true;
            // 在 PyQt GUI 内可以强制输出颜色代码，使用 ansi2html 转成 html
            Color::setForceColor(true);
        }

        while (true) {
            $this->ui->displayInstructions();
            $this->handleUserInput();
            $this->prepareBookEnvironment();

            start_file_walk:
            $this->setInWalkFunc(function ($bookDir, $file) {
                $this->ctx->filename = $file;
                $this->ctx->filepath = $bookDir . '/' . $file;
                $this->checkQuotationMarks();
            });

            $this->walkFiles(BOOK_DIR);

            $this->ui->displayCompletionMessage();

            // 只获取错误总数
            $restart = $this->ui->askForInput();
            if ($restart === self::OP_GET_ERR_COUNT) {
                $this->ctx->getErrCount = true;
                goto start_file_walk;  // 直接重读文件，注意 goto 的位置
            }

            $this->ctx->resetProgress();
        }
    }

    protected function handleUserInput(): void
    {
        $input = $this->ui->askForInput();
        if ($input === self::OP_GET_ERR_COUNT) {
            $this->ctx->fixSingles = false;
            $this->ctx->getErrCount = true;
        } else {
            $this->ctx->fixSingles = ($input == 1);
        }
    }

    protected function prepareBookEnvironment(): void
    {
        Util::unifyAllBooksFormat();

        Util::recursiveDelete(BOOK_BAK_DIR, false);
        Util::recursiveCopy(BOOK_DIR, BOOK_BAK_DIR);

        (new EpubFixer())->mergeAllEpubText();
    }

    /**
     * @return bool
     */
    public function checkQuotationMarks(): bool
    {
        $this->ctx->reloadFile = true;
        while ($this->ctx->reloadFile) {
            // 只要 $this->ctx->reloadFile 在任意位置被设置为 true，就 reload 整个文件
            $this->ctx->reloadFile = false;

            $this->ctx->lineArr = file($this->ctx->filename);
            $this->ctx->lineCount = count($this->ctx->lineArr);
            $this->ctx->startLine = $this->calculateRestartLine();

            $this->processLines();
            if ($this->ctx->reloadFile) {
                continue;
            }

            // 报告错误总数
            if ($this->ctx->getErrCount) {
                echo "当前文件含有【{$this->ctx->errCount}】处引号错误段落" . PHP_EOL;

                $this->ctx->resetErrCount();
                $this->ctx->resetProgress();

                $this->ctx->reloadFile = true;
                continue;
            }

            // 若在之前的检查中有找到错误（后来在 GUI 或者编辑器改好了），
            // 需要从头再读一遍，确保全局修改
            if (
                $this->ctx->fixSingles
                && $this->ctx->progressLineCount
                && !$this->ctx->forceFix
            ) {
                $this->ctx->resetProgress();
                $this->ctx->reloadFile = true;
                continue;
            }

            if ($this->ctx->fixSingles) {
                $content = implode('', $this->ctx->lineArr);
                $content = str_replace(QuotationUi::ERR_MARK, '', $content);
                file_put_contents($this->ctx->filename, $content);
            }
        }

        return true;
    }

    /**
     * @throws AppException
     */
    protected function processLines(): void
    {
        foreach ($this->ctx->lineArr as $lineKey => $line) {
            if ($lineKey < $this->ctx->startLine) {
                continue;
            }

            $this->ctx->lineKey = $lineKey;
            $this->ctx->line = $line;
            $this->printProgressInfo();

            if (!Util::multiStrContains($line, ['“', '”', '‘', '’'])) {
                continue;
            }

            $this->processCharactersInLine();
            if ($this->ctx->reloadFile) {
                return;
            }
        }
    }

    /**
     * @throws AppException
     */
    protected function processCharactersInLine(): void
    {
        $this->ctx->charArr = mb_str_split($this->ctx->line);
        foreach ($this->ctx->charArr as $k => $char) {
            $this->ctx->charKey = $k;
            $this->ctx->char = $char;

            try {
                $this->checkLeftSingles();
                $this->checkRightSingles();
                $this->checkLeftDoubles();
                $this->checkRightDoubles();
                $this->checkEOL();
            } catch (ReloadThenSkipException | DirectSkipException $e) {
                $this->handleLineException($e);
                break;
            }
        }
    }

    protected function handleLineException(AppException $e): void
    {
        $this->ctx->resetLineState();

        switch (get_class($e)) {
            case ReloadThenSkipException::class:
                // 此处跳出整个文件处理，直接 reload 文件
                // 即使文件在别的地方被编辑过，也能实时获取编辑后的内容
                // 主要是在修复完当前错误后抛出此异常，此为图方便的“以异常控制流程”反模式……
                $this->ctx->reloadFile = true;
                break;
            case DirectSkipException::class:
                if ($this->ctx->getErrCount && !$this->ctx->directCount) {
                    // 第一次设置 directCount，从此开始计数
                    // 同时需要回到开头重读文件
                    $this->ctx->directCount = true;
                    $this->ctx->reloadFile = true;
                    break;
                }
                // 此处跳出当前行处理，在内存中已做出的单引号修正依旧被保留
                break;
        }
    }

    protected function calculateRestartLine(): int
    {
        if ($this->ctx->getErrCount && $this->ctx->errCount == 0) {
            return 0;
        }

        $progressLineCount = $this->ctx->progressLineCount;
        $lineCount = $this->ctx->lineCount;
        if ($progressLineCount <= 0 || $lineCount <= 0) {
            return 0;
        }

        // 这里是 reload 文件之后，在原行数 +1
        if ($this->ctx->forceSkip) {
            $this->ctx->forceSkip = false;
            return $this->ctx->progressLineKey + 1;
        }

        $diff = abs($progressLineCount - $lineCount) / min($progressLineCount, $lineCount);
        if ($diff > self::REREAD_DIFF_THRESHOLD) {
            // 行数变动超 0.1% 就从头读起
            return 0;
        }

        // 默认回退 200 行开始读
        return max($this->ctx->progressLineKey - self::REWIND_LINES, 0);
    }

    protected function printProgressInfo(): void
    {
        if (($this->ctx->lineKey + 1) % self::PROGRESS_STEP !== 0) {
            return;
        }

        $this->ui->printProgress($this->ctx->lineKey, $this->ctx->lineCount);
    }

    protected function getProgressInfo(): array
    {
        $progress = number_format(
            (($this->ctx->lineKey + 1) / ($this->ctx->lineCount + 1)) * 100,
            2
        ) . '%';
        $lineNum = ($this->ctx->lineKey + 1) . ' 行 / ' . ($this->ctx->lineCount + 1) . ' 行';

        return [$progress, $lineNum];
    }

    protected function checkLeftSingles(): bool
    {
        if ($this->ctx->char !== '‘') return true;

        // 1. 收集最外层单引号（栈中无双引号时），供 doFixSingles
        $hasDouble = false;
        foreach ($this->ctx->quoteStack as $item) {
            if ($item['char'] === '“') { $hasDouble = true; break; }
        }
        if (!$hasDouble) {
            $this->ctx->outerLeftSingleKeys[] = $this->ctx->charKey;
        }

        // 2. 跨行段首延续判定（单引号跨行模式）
        // 如果处于跨行状态，且换行后在段首又遇到‘
        // 如：‘我是第一段话。
        // ‘我是第二段话。
        // ‘我是最后一段话。’
        // 此时它只是延续标记，不重复压栈
        if (
            $this->ctx->isMultiLine
            && $this->ctx->metEOL
            && !empty($this->ctx->quoteStack)
            && end($this->ctx->quoteStack)['char'] === '‘'
        ) {
            // 更新左单引号在当前行的实际字符位置
            $lastIdx = array_key_last($this->ctx->quoteStack);
            $this->ctx->quoteStack[$lastIdx]['pos'] = $this->ctx->charKey;

            $this->ctx->metEOL = false;
            return true;
        }

        // 3. 【核心拦截】：单引号内直接嵌套独立单引号（如 ‘ ‘啊啊’和‘哔哔’ ’ 或 ‘他说：‘不行’ ’）
        // 判定条件：直接父级（栈顶）也是单引号‘，且当前不是紧挨着前一个‘（前一个字符不是‘）
        $prevChar = $this->ctx->charArr[$this->ctx->charKey - 1] ?? '';
        $top = end($this->ctx->quoteStack);
        if ($top !== false && $top['char'] === '‘' && $prevChar !== '‘') {
            $this->dumpErr('<左单引号前> 单引号内直接嵌套了独立单引号（应规范使用双引号）');
        }

        // 4. 正常入栈
        $this->ctx->quoteStack[] = ['char' => '‘', 'pos' => $this->ctx->charKey];
        $this->ctx->metEOL = false;

        return true;
    }

    protected function checkRightSingles(): bool
    {
        if ($this->ctx->char !== '’') return true;

        // 过滤英文撇号（如 80’s Music, Guns N’ Roses）
        // AI 说明：【’ (Curly Apostrophe / 弯撇号 / 智能撇号): 这是专业排版中使用的正确形式，也叫“所有格符号”（U+2019 RIGHT SINGLE QUOTATION MARK）。它和中文的右单引号 ’ 在视觉上非常相似，但它是半角的。】
        // 然而实际上从 txt 纯文本的角度来看，它就是和中文右单引号一模一样（Unicode 码都一样），因此直接不处理就行。另外，直接统一成英文单引号也是可行的
        $prevChar = $this->ctx->charArr[$this->ctx->charKey - 1] ?? '';
        $nextChar = $this->ctx->charArr[$this->ctx->charKey + 1] ?? '';
        if (in_array($prevChar, $this->ctx->letters) && in_array($nextChar, $this->ctx->letters)) {
            return true;
        }

        if (empty($this->ctx->quoteStack)) {
            $this->dumpErr('<右单引号前> 缺左单引号');
        }

        $top = array_pop($this->ctx->quoteStack);

        // 交叉校验：栈顶必须是左单引号
        if ($top['char'] !== '‘') {
            $this->dumpErr('<右单引号前> 引号嵌套交叉错乱，内部双引号“未闭合');
        }

        // 空单引号判断
        if ($this->ctx->charKey - $top['pos'] === 1) {
            $this->dumpErr('<右单引号前> 出现空引号‘’现象');
        }

        // 收集最外层右单引号
        $hasDouble = false;
        foreach ($this->ctx->quoteStack as $item) {
            if ($item['char'] === '“') { $hasDouble = true; break; }
        }
        if (!$hasDouble) {
            $this->ctx->outerRightSingleKeys[] = $this->ctx->charKey;
        }

        // 栈清空时，跨行状态彻底结束
        if (empty($this->ctx->quoteStack)) {
            $this->ctx->isMultiLine = false;
        }

        return true;
    }

    protected function checkLeftDoubles(): bool
    {
        if ($this->ctx->char !== '“') return true;

        $prevChar = $this->ctx->charArr[$this->ctx->charKey - 1] ?? '';

        // 1. 跨行段首延续判定
        // 如果处于跨行状态，且换行后在段首又遇到“
        // 如：“我是第一段话。
        // “我是第二段话。
        // “我是最后一段话。”
        // 此时它只是延续标记，不重复压栈
        if (
            $this->ctx->isMultiLine
            && $this->ctx->metEOL
            && !empty($this->ctx->quoteStack)
            && end($this->ctx->quoteStack)['char'] === '“'
        ) {
            // 更新左双引号在当前行的实际字符位置
            $lastIdx = array_key_last($this->ctx->quoteStack);
            $this->ctx->quoteStack[$lastIdx]['pos'] = $this->ctx->charKey;

            $this->ctx->metEOL = false;
            return true;
        }

        // 2. 【核心拦截】：双引号内直接嵌套独立双引号（如 ““啊啊”和“哔哔”” 或 “他说：“不行””）
        // 判定条件：直接父级（栈顶）也是双引号“，且当前不是紧挨着前一个“（前一个字符不是“）
        $top = end($this->ctx->quoteStack);
        if ($top !== false && $top['char'] === '“' && $prevChar !== '“') {
            $this->dumpErr('<左双引号前> 双引号内直接嵌套了独立双引号（应规范使用单引号）');
        }

        // 3. 正常入栈
        $this->ctx->quoteStack[] = ['char' => '“', 'pos' => $this->ctx->charKey];
        $this->ctx->metEOL = false;

        return true;
    }

    protected function checkRightDoubles(): bool
    {
        if ($this->ctx->char !== '”') return true;

        if (empty($this->ctx->quoteStack)) {
            $this->dumpErr('<右双引号前> 缺左双引号');
        }

        $top = array_pop($this->ctx->quoteStack);

        // 交叉校验：栈顶必须是左双引号
        if ($top['char'] !== '“') {
            $this->dumpErr('<右双引号前> 引号嵌套交叉错乱，内部单引号‘未闭合');
        }

        // 空引号判断：紧挨着则报空引号
        if ($this->ctx->charKey - $top['pos'] === 1) {
            $this->dumpErr('<右双引号前> 出现空引号“”现象');
        }

        // 如果栈空了，说明跨行引用也在此彻底结束
        if (empty($this->ctx->quoteStack)) {
            $this->ctx->isMultiLine = false;
        }

        return true;
    }

    protected function checkEOL(): bool
    {
        if ($this->ctx->char !== "\n") return true;

        if (!empty($this->ctx->quoteStack)) {
            // 【跨行通用入口】：只有当且仅当最外层只有 1 层引号未闭合时，才允许向下跨行探测
            if (count($this->ctx->quoteStack) === 1) {
                $topChar = $this->ctx->quoteStack[0]['char'];
                $rightQuote = ($topChar === '“') ? '”' : '’';

                $this->checkMissingRightQuote($topChar, $rightQuote);
                $this->ctx->isMultiLine = true; // 跨行验证通过，保持跨行标记
            } else {
                // 单引号未闭合，或多层双引号嵌套未闭合，一律换行报错
                $top = end($this->ctx->quoteStack);
                $type = $top['char'] === '“' ? '双' : '单';
                $this->dumpErr("<换行时> 存在未闭合的{$type}引号（多层嵌套不允许跨行）");
            }
        }

        $this->doFixSingles();
        $this->ctx->resetQuotationKeys();
        $this->ctx->metEOL = true;

        return true;
    }

    /**
     * 通用跨行闭合检查（支持双引号与单引号）
     */
    protected function checkMissingRightQuote(string $leftQuote = '“', string $rightQuote = '”'): bool
    {
        $quoteName = ($leftQuote === '“') ? '双' : '单';

        if ($this->ctx->lineKey == $this->ctx->lineCount - 1) {
            $this->dumpErr("<换行时> 缺右{$quoteName}引号（已到文件末尾）");
        }

        $lastLeftKey = end($this->ctx->quoteStack)['pos'] ?? 0;
        if (!$this->checkLeftQuotePrevChar($lastLeftKey)) {
            $this->dumpErr("<换行时> 缺右{$quoteName}引号，段首左{$quoteName}引号的位置有误");
        }

        if (!$this->searchForRightQuote($leftQuote, $rightQuote)) {
            $this->dumpErr("<换行时> 缺右{$quoteName}引号，且下方多行内都无法查找到右{$quoteName}引号");
        }

        return true;
    }

    /**
     * 校验左引号前置字符的合法性
     */
    protected function checkLeftQuotePrevChar(int $leftQuoteKey, array $charArr = [], string $prevAllowedExpr = ""): bool
    {
        $charArr = $charArr ?: $this->ctx->charArr;
        $prevK = max($leftQuoteKey - 1, 0);
        $prevChar = $charArr[$prevK] ?? '';
        $prevAllowedExpr = $prevAllowedExpr ?: "/[【〖。？！：，> 　\r\n]/um";

        if ($leftQuoteKey > 0 && !preg_match($prevAllowedExpr, $prevChar)) {
            // 这种情况只允许左双引号写在特定的结尾字符之后
            // 在其他字符后面则报错
            return false;
        }

        return true;
    }

    /**
     * 向下探测右引号（同时支持单/双引号）
     */
    public function searchForRightQuote(string $leftQuote = '“', string $rightQuote = '”'): bool
    {
        $quoteName = ($leftQuote === '“') ? '双' : '单';
        $foundRightQuote = false;
        $nextLineHasLeftQuote = false;
        $prevNextLineKey = 0;

        for ($i = 1; $i <= self::SEARCH_FOR_RD_LINES; $i++) {
            $nextLineKey = (!$prevNextLineKey) ? min($this->ctx->lineKey + 1, $this->ctx->lineCount - 1) : min($prevNextLineKey, $this->ctx->lineCount - 1);

            do {
                if ($nextLineKey >= $this->ctx->lineCount) break 2;
                $nextLine = $this->ctx->lineArr[$nextLineKey];
                $nextLineKey++;
            } while (
                // 空行一律跳过
                (preg_match("/^[ 　\r\n]*$/", $nextLine) || in_array($nextLine, ["\r\n", "\n"]))
                && $nextLineKey < $this->ctx->lineCount
            );

            $prevNextLineKey = $nextLineKey;
            $nextCharArr = mb_str_split($nextLine);
            $nextLeftQuoteK = mb_strpos($nextLine, $leftQuote);

            if (empty($nextCharArr)) {
                $this->dumpErr("<换行时> 缺右{$quoteName}引号");
            }

            // 检查隔行出现的左引号是否在行首
            if ($nextLeftQuoteK !== false) {
                $nextExpr = "/[> 　\r\n]/um";
                if (!$this->checkLeftQuotePrevChar($nextLeftQuoteK, $nextCharArr, $nextExpr)) {
                    $this->dumpErr("<换行时> 缺右{$quoteName}引号，隔行出现左{$quoteName}引号错位");
                }
            }

            // 统一风格校验
            if ($i == 1) {
                if (str_contains($nextLine, $leftQuote)) {
                    // 紧跟 $this->lineKey 的下一行内的左引号情况，
                    // 决定了应该采用【允许接下来的行首无左引号】
                    // 还是【不允许接下来的行首无左引号】的风格
                    $nextLineHasLeftQuote = true;
                }
            } else {
                if (str_contains($nextLine, $leftQuote) && !$nextLineHasLeftQuote) {
                    // 紧跟 $this->lineKey 的下一行中没有左引号，
                    // 却在再隔一行的行首出现左引号
                    $this->dumpErr("<换行时> 缺右{$quoteName}引号，两行后却出现不应有的左{$quoteName}引号");
                }

                if (!str_contains($nextLine, $leftQuote) && $nextLineHasLeftQuote) {
                    // 紧跟 $this->lineKey 的下一行中出现左引号，
                    // 却在再隔一行的行首没有左引号
                    $this->dumpErr("<换行时> 缺右{$quoteName}引号，两行后却缺失应有的左{$quoteName}引号");
                }
            }

            // 检查右引号（注意单引号需过滤英文撇号）
            if (str_contains($nextLine, $rightQuote)) {
                if ($rightQuote === '’') {
                    // 若为单引号，确保包含的不是纯英文撇号
                    $cleanLine = preg_replace('/[a-zA-Z0-9]’[a-zA-Z0-9]/u', '', $nextLine);
                    if (str_contains($cleanLine, '’')) {
                        $foundRightQuote = true;
                        break;
                    }
                } else {
                    $foundRightQuote = true;
                    break;
                }
            }
        }

        return $foundRightQuote;
    }

    protected function doFixSingles(): bool
    {
        if (!$this->ctx->fixSingles) return true;
        if (!$this->ctx->outerLeftSingleKeys || !$this->ctx->outerRightSingleKeys) return true;

        foreach ($this->ctx->outerLeftSingleKeys as $lk) $this->ctx->charArr[$lk] = '“';
        foreach ($this->ctx->outerRightSingleKeys as $rk) $this->ctx->charArr[$rk] = '”';

        $this->ctx->lineArr[$this->ctx->lineKey] = implode($this->ctx->charArr);

        return true;
    }

    protected function dumpErr(string $errMsg = ''): void
    {
        // 记录进度，重读文件时从该进度的前面一点开始读取，不重复从头读起
        $this->ctx->progressLineKey = $this->ctx->lineKey;
        $this->ctx->progressLineCount = $this->ctx->lineCount;

        // 统计错误数时直接跳过所有错误处理，强制跳到下一处错误
        if ($this->ctx->getErrCount) {
            $this->ctx->directCount && $this->ctx->errCount++;
            throw new DirectSkipException();
        }

        // 准备错误上下文
        $prevN = self::FETCH_CONTEX_LINES;
        $this->ctx->fromGUI && $prevN += self::GUI_EXTRA_LINES; // 在 GUI 多显示一些上下文内容
        $prevNK = max($this->ctx->lineKey - $prevN, 0);
        $this->ctx->lineArr[$this->ctx->lineKey] = QuotationUi::ERR_MARK . $this->ctx->lineArr[$this->ctx->lineKey];
        $contentErrArr = array_slice($this->ctx->lineArr, $prevNK, $prevN * 2 + 1);
        $contentErrStr = implode($contentErrArr);

        // 防止输出内容过长，超过缓冲区大小
        $maxLen = self::MAX_OUTPUT_LEN;
        $contentLen = mb_strlen($contentErrStr);
        if ($contentLen > $maxLen) {
            // 找到错误标记的位置，以确保它在截取后的内容中可见
            $errorMarkerPos = mb_strpos($contentErrStr, QuotationUi::ERR_MARK);
            if ($errorMarkerPos !== false) {
                // 计算理想的起始点，尝试将错误标记置于截取窗口的中央
                $startPos = $errorMarkerPos - (int)floor($maxLen / 2);

                // 修正起始点，确保它在有效范围内
                // 1. 不能为负数
                $startPos = max(0, $startPos);
                // 2. 确保加上最大长度后不会超出原字符串
                $startPos = min($startPos, $contentLen - $maxLen);

                $contentErrStr = mb_substr($contentErrStr, $startPos, $maxLen);
            } else {
                // 作为备用方案，如果找不到标记，则使用原始的居中截取
                $start = (int)floor(($contentLen - $maxLen) / 2);
                $contentErrStr = mb_substr($contentErrStr, $start, $maxLen);
            }
        }

        list($progress, $lineNum) = $this->getProgressInfo();

        if ($this->ctx->fromGUI) {
            // 单独打印一下当前路径，让 GUI 支持递归文件处理
            echo "文件路径：{$this->ctx->filepath}" . PHP_EOL;
            // GUI 中的原文段落不可添加高亮颜色
            Color::setNoColor(true);
            Color::setForceColor(false);
        } else {
            $contentErrStr = $this->ui->highlightErrContent($contentErrStr);
        }

        $msg = <<<DOC

        ======= ↓↓↓ =======
        %s
        文件名：《%s》
        当前进度：%s （%s）

        原文内容如下：
        %s
        ======= ↑↑↑ =======

        DOC;
        printf(
            $msg,
            Color::backRed("报错信息：！！{$errMsg}！！"),
            Color::foreYellow($this->ctx->filename),
            Color::foreYellow($progress),
            Color::foreYellow($lineNum),
            $contentErrStr,
        );

        // 恢复强制输出颜色代码
        if ($this->ctx->fromGUI) {
            Color::setNoColor(false);
            Color::setForceColor(true);
        }

        // 链式调用 Fixer 进行修复尝试
        // 如果某一种修复被采用，直接修改文件，抛出 ReloadThenSkipException，处理后续文本
        // 如果某一种修复被跳过，则返回 $this->fixer，继续下一种修复，直至无更多修复可尝试
        $this->fixer->autoFixNestedDoubles()
            ->autoFixRevertedQuotations()
            ->autoFixRepeatedQuotations()
            ->autoFixSoleRightDouble()
            ->autoFixSoleRightSingle()
            ->autoFixMissingLeftDouble()
            ->autoFixMissingRightDouble()
            // 上述的自动修复都无法搞定时，输出默认报错信息
            ->defaultDump();
    }
}
