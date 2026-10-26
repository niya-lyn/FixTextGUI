<?php

namespace App\Service\Quotation;

class QuotationContext
{
    public bool $fromGUI    = false;  // 是否为来自图形界面调用
    public bool $fixSingles = false;  // 是否将双引号外的单引号统一规范为双引号
    public bool $reloadFile = false;  // 是否重新加载文件内容

    // 文件信息
    public string $filename = '';
    public string $filepath = '';

    // 英文字母和数字
    public array $letters   = [];

    // 内容处理
    public array $lineArr = [];  // 文件内的所有行
    public array $charArr = [];  // 单行内的所有字符
    public string $line   = '';  // 当前处理的行
    public string $char   = '';  // 当前处理的字符

    // 游标与计数
    public int $lineKey   = 0;
    public int $charKey   = 0;
    public int $lineCount = 0;  // 当前的实际行数（在可能的修改之后）
    public int $startLine = 0;

    // 引号位置记录
    public int $leftSingleKey  = 0;
    public int $rightSingleKey = 0;
    public int $leftDoubleKey  = 0;
    public int $rightDoubleKey = 0;

    // 用一个栈记录所有未闭合的左引号
    // 每个元素形如：['char' => '“', 'pos' => int] 或 ['char' => '‘', 'pos' => int]
    public array $quoteStack = [];

    // 单引号自动修复记录（仅记录最外层的单引号）
    public array $outerLeftSingleKeys  = [];
    public array $outerRightSingleKeys = [];

    // 跨行状态控制
    public bool $isMultiLine = false; // 是否处于段落跨行模式
    public bool $metEOL      = false;

    // 进度与错误控制
    public int $progressLineKey   = 0;
    public int $progressLineCount = 0;  // 报错时记录的行数（在可能的修改之前）

    public bool $forceSkip = false;
    public bool $forceFix  = false;

    // 统计模式
    // $getErrCount 为 true，同时 $directCount 为 false 时，说明从此时开始计数，需要回到开头第一行
    // $getErrCount 和 $directCount 均为 true 时，说明正在进行计数，遇到报错行一律跳过并统计
    // $getErrCount 有三个输入时机，先三次设置为 true
    public bool $getErrCount = false;
    public bool $directCount = false;
    public int $errCount     = 0;

    public function __construct()
    {
        $this->letters = array_merge(
            range('a', 'z'),
            range('A', 'Z'),
            range(0, 9),
            [' ']
        );
    }

    /**
     * 判断当前栈中是否有未闭合的左单引号
     */
    public function hasUnclosedSingle(): bool
    {
        foreach ($this->quoteStack as $item) {
            if ($item['char'] === '‘') {
                return true;
            }
        }

        return false;
    }

    /**
     * 判断当前栈中是否有未闭合的左双引号
     */
    public function hasUnclosedDouble(): bool
    {
        foreach ($this->quoteStack as $item) {
            if ($item['char'] === '“') {
                return true;
            }
        }

        return false;
    }

    public function resetQuotationKeys(): void
    {
        // 只有非跨行时才清空栈
        if (!$this->isMultiLine) {
            $this->quoteStack = [];
        }
        $this->outerLeftSingleKeys  = [];
        $this->outerRightSingleKeys = [];
    }

    public function resetLineState(): void
    {
        $this->quoteStack   = [];
        $this->isMultiLine  = false;
        $this->metEOL       = false;
        $this->resetQuotationKeys();
    }

    public function resetProgress(): void
    {
        $this->progressLineKey   = 0;
        $this->progressLineCount = 0;
    }

    public function resetErrCount(): void
    {
        $this->getErrCount = false;
        $this->errCount    = 0;
        $this->directCount = false;
        $this->forceSkip   = false;
    }
}
