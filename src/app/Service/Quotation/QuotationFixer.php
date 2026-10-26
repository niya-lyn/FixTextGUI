<?php

namespace App\Service\Quotation;

use App\Util\Util;
use App\Exception\Quotation\DirectSkipException;
use App\Exception\Quotation\ReloadThenSkipException;
use Exception;

class QuotationFixer
{
    const OP_FIX_CUR_LINE   = 1;
    const OP_FIX_WHOLE_FILE = 2;
    const OP_SKIP_CUR_FIX   = 3;

    const OP_FORCE_SKIP    = QuotationChecker::OP_FORCE_SKIP;
    const OP_FORCE_FIX     = QuotationChecker::OP_FORCE_FIX;
    const OP_GET_ERR_COUNT = QuotationChecker::OP_GET_ERR_COUNT;
    const OP_EXIT          = QuotationChecker::OP_EXIT;

    // 构造器属性提升，PHP 8.0+ 的特性
    public function __construct(
        protected QuotationContext $ctx,
        protected QuotationUi $ui
    ) {}

    public function autoFixNestedDoubles(): self
    {
        $errName = '【双引号套双引号】';
        $errMsg = <<<DOC
        ！！会将文件中这几处双引号括起来的内容，统一改成用单引号括起来。
        随后可利用此脚本将所有【双引号外的单引号】一次性规范为双引号！！
        DOC;
        $expr = "/“([^\n。…？！；～~（）：“”‘’]+?)”(?=.*”)/um";
        // 下面这样写会报错，暂不限定外面必须存在左双引号
        // $expr = "/(?<=“.*)“([^\n。…？！；～~（）：“”‘’]+?)”(?=.*”)/um";
        $this->doAutoFix($errName, $errMsg, $expr, ['“', '”'], ['‘', '’']);

        return $this;
    }

    public function autoFixRevertedQuotations(): self
    {
        $errName = '【写反左右引号】';
        $errMsg = <<<DOC
        ！！会将文件中这几处把引号写反的内容，统一反转成正向写法，
        请【仔细考虑是否全局修改】！！
        DOC;
        // 非常蛋疼的替换设置……
        // 注意这条正则应该需要手动在文本中执行一下搜索
        // 有些类似【“aaa 说”bbb“是 ccc 的东西”】这种错误情况，无法单纯通过引号匹配情况分辨是否有误
        // 因为【“aaa”和“bbb”都是 ccc 的东西】这种正确情况，也同样能被这条正则匹配上，只能人工判断
        $expr = "/[”’]([^\n、，。…？！；～~（）：“”‘’]+?)[“‘]/um";
        $searches = ['“', '”', '‘', '’', '<<rdq>>', '<<ldq>>', '<<rsq>>', '<<lsq>>'];
        $replaces = ['<<rdq>>', '<<ldq>>', '<<rsq>>', '<<lsq>>', '”', '“', '’', '‘'];
        $this->doAutoFix($errName, $errMsg, $expr, $searches, $replaces);

        return $this;
    }

    public function autoFixRepeatedQuotations(): self
    {
        $errName = '【连续写了多个同方向引号】';
        $errMsg = <<<DOC
        ！！会将文件中这几处连续同方向的引号，统一改成正确方向。
        请【仔细考虑是否全局修改】！！
        DOC;
        $rules = [
            [
                "search"  => "/“([^\n”‘’]*?)“/um",
                "replace" => "“$1”",
            ],
            [
                "search"  => "/”([^\n“‘’]*?)”([^\n“‘’]*?)”/um",
                "replace" => "”$1“$2”",
            ],
            [
                "search"  => "/”([^\n“‘’]*?)”/um",
                "replace" => "“$1”",
            ],
            [
                "search"  => "/‘([^\n“”’]*?)‘/um",
                "replace" => "‘$1’",
            ],
            [
                "search"  => "/’([^\n“”‘]*?)’/um",
                "replace" => "‘$1’",
            ],
        ];

        $foundK = -1;
        foreach ($rules as $k => $v) {
            if (preg_match($v['search'], $this->ctx->line)) {
                $foundK = $k;
                break;
            }
        }

        if ($foundK != -1) {
            $this->doAutoFix($errName, $errMsg, $rules[$foundK]['search'], [$rules[$foundK]['search']], [$rules[$foundK]['replace']]);
        }

        return $this;
    }

    public function autoFixSoleRightDouble(): self
    {
        if ($this->ctx->hasUnclosedDouble()) return $this;
        $this->doAutoFix(
            '【句尾单独使用右双引号】',
            '！！会将这个单独误用的句尾右双引号自动移除！！',
            "/([^“]*)”((<\/p>)?[\r\n<]*)$/um",
            ["/([^“]*)”((<\/p>)?[\r\n<]*)$/um"],
            ["$1$2"]
        );

        return $this;
    }

    public function autoFixSoleRightSingle(): self
    {
        $this->doAutoFix(
            '【句尾单独使用右单引号】',
            '！！会将这个单独误用的句尾右单引号自动移除！！',
            "/([^‘]*)’((<\/p>)?[\r\n<]*)$/um",
            ["/([^‘]*)’((<\/p>)?[\r\n<]*)$/um"],
            ["$1$2"]
        );

        return $this;
    }

    public function autoFixMissingLeftDouble(): self
    {
        if ($this->ctx->hasUnclosedDouble()) return $this;
        $this->doAutoFix(
            '【右双引号前缺左双引号】',
            '！！会将这个缺失的左双引号自动加上！！',
            "/([^“\s<>【】]*”)((.*?)(<\/p>)?[\r\n<]*)$/um",
            ["/([^“\s<>【】]*”)((.*?)(<\/p>)?[\r\n<]*)$/um"],
            ["“$1$2"]
        );

        return $this;
    }

    public function autoFixMissingRightDouble(): self
    {
        $expr = '';
        $searches = [];
        $replaces = [];
        if (Util::isTxtFile($this->ctx->filename)) {
            $expr = "/(“[^<>”]*)(.*)\n/um";
            $searches = ["/(“[^<>”]*)(.*)\n/um"];
            $replaces = ["$1$2”\n"];
        } else if (Util::isHtmlFile($this->ctx->filename)) {
            $expr = "/(“[^<>”]*)(.*)<\/p>/um";
            $searches = ["/(“[^<>”]*)(.*)<\/p>/um"];
            $replaces = ["$1$2”</p>"];
        }

        if ($expr) {
            $this->doAutoFix('【句尾缺少右双引号】', '！！会将这个缺失的右双引号自动加上！！', $expr, $searches, $replaces);
        }

        return $this;
    }

    /**
     * 核心自动修复逻辑
     *
     * @param string $errName
     * @param string $errMsg
     * @param string $expr
     * @param array $searches 实际是一组正则表达式，先这样吧……
     * @param array $replaces 实际是一组正则表达式
     * @return bool
     * @throws Exception
     */
    protected function doAutoFix(string $errName, string $errMsg, string $expr, array $searches = [], array $replaces = []): bool
    {
        if (!preg_match_all($expr, $this->ctx->line, $match)) {
            return false;
        }

        if (count($searches) != count($replaces)) {
            return false;
        }

        $this->ui->displayAutoFixExpr($expr, $replaces);

        $makeRegex = function ($v) {
            if (!str_contains($v, '/um')) {
                $v = str_replace("/", "\/", $v);
                return "/$v/um";
            } else {
                return $v;
            }
        };
        $searches = array_map($makeRegex, $searches);

        $matchStr = '【' . implode('】 【', $match[0]) . '】';
        $replaceStr = $matchStr;
        foreach ($searches as $mk => $mv) {
            $replaceStr = preg_replace($mv, $replaces[$mk], $replaceStr);
        }

        $matchStr = str_replace("\n】", '】', $matchStr);
        $replaceStr = str_replace("\n】", '】', $replaceStr);

        $this->ui->displayAutoFixOption(
            $errName,
            $errMsg,
            $matchStr,
            $replaceStr,
            self::OP_FIX_CUR_LINE,
            self::OP_FIX_WHOLE_FILE,
            self::OP_SKIP_CUR_FIX,
            self::OP_FORCE_SKIP,
            self::OP_FORCE_FIX
        );

        $op = (string)$this->ui->askForInput();
        if (!$op) {
            throw new ReloadThenSkipException();
        }

        if ($op == self::OP_SKIP_CUR_FIX) {
            // 跳过当前修复，进入下一项修复
            return false;
        }

        // 处理通用操作指令 (x, f, c)
        $this->forceHandleErr($op);

        $contentReplaces = array_map(
            function ($v) use ($searches, $replaces) {
                foreach ($searches as $mk => $mv) {
                    $v = preg_replace($mv, $replaces[$mk], $v);
                }
                return $v;
            },
            $match[0]
        );

        $content = file_get_contents($this->ctx->filepath);
        $contentMatches = array_map($makeRegex, $match[0]);
        $curLine = $this->ctx->line;

        foreach ($contentMatches as $mk => $mv) {
            $rv = $contentReplaces[$mk];
            if ($op == self::OP_FIX_CUR_LINE) {
                $curLine = preg_replace($mv, $rv, $curLine);
            } else if ($op == self::OP_FIX_WHOLE_FILE) {
                $content = preg_replace($mv, $rv, $content);
            }
        }

        // 可能对 curLine 多次修改，故不能放到上面的 foreach 里
        if ($op == self::OP_FIX_CUR_LINE) {
            $this->ctx->lineArr[$this->ctx->lineKey] = $curLine;
            $content = implode("", $this->ctx->lineArr);
        }

        file_put_contents($this->ctx->filepath, $content);
        unset($content);

        // 修复完成，抛异常退出，到下一处报错
        throw new ReloadThenSkipException();
    }

    protected function forceHandleErr($op): void
    {
        // 如果什么也没输入，强制抛出异常
        // 保证重新读取在编辑器中被修改后的文件
        if (!$op) {
            throw new ReloadThenSkipException();
        }

        if ($op == self::OP_FORCE_SKIP) {
            // 强制跳过当前行（当确认该行实际无错误时），继续往下查错
            $this->ctx->forceSkip = true;
            throw new ReloadThenSkipException();
        } else if ($op == self::OP_FORCE_FIX) {
            // 强制修复双引号外的单引号
            // 此时只能使用 f 来跳过报错行（只是简单跳过当前行），
            // 而不能使用 x 跳过（用 x 会 reload 文件，再跳过当前行）
            // 只有在确认整个文件内的引号都无错误，
            // 同时脚本仍在对多重引号嵌套等情况持续报错，
            // 才考虑使用 f 强制修复，在此过程中不能对文件进行任何修改
            $this->ctx->forceFix = true;
            throw new DirectSkipException();
        } else if ($op == self::OP_GET_ERR_COUNT) {
            // 只获取错误总数，遇到错误行时一律跳过
            $this->ctx->getErrCount = true;
            throw new DirectSkipException();
        }
    }

    public function defaultDump(): void
    {
        $this->ui->displayDefaultDump(self::OP_EXIT, self::OP_FORCE_SKIP, self::OP_FORCE_FIX);

        $op = (string)$this->ui->askForInput();
        if ($op == self::OP_EXIT) {
            $this->ui->printExit();
        }

        $this->forceHandleErr($op);
    }
}
