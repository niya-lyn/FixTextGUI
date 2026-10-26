<?php

namespace App\Service\Quotation;

use App\Util\Console\Show;
use App\Util\Console\Color;
use Inhere\Console\Util\Interact;

class QuotationUi
{
    const ERR_MARK = '【报错段落】';

    public function askForInput(): string|int
    {
        return Interact::readln('请输入：');
    }

    public function printExit()
    {
        Show::writeWithNL('【退出脚本】', true);
    }

    public function displayInstructions(): void
    {
        $msg = <<<DOC
        此脚本作用：
        【检查中文单双引号的使用情况，若有引号不配对则报错】

        DOC;
        Show::write(Color::foreRed($msg));

        $msg = <<<DOC

        请输入 <primary>0</primary> 或 <primary>1</primary>。
        输入 <primary>0</primary> （或可不输入，直接回车）只查错，不修复单引号；
        输入 <primary>1</primary> 则会将<primary>【双引号外的单引号】</primary>统一规范为双引号。

        DOC;
        Show::write($msg);
    }

    public function displayCompletionMessage(): void
    {
        $msg = <<<DOC

        <primary>【已完成中文引号检查和处理】</primary>
        请确认是否需要进行下一轮引号查错。
        此时输入<primary>【任意值】</primary>都会回到开头，重新查一遍引号。
        如需退出脚本，手动关闭窗口即可。

        DOC;
        Show::write($msg);
    }

    public function askRestart(): string
    {
        return Interact::readln('请输入：');
    }

    public function printProgress(int $lineKey, int $lineCount): void
    {
        $progress = number_format((($lineKey + 1) / ($lineCount + 1)) * 100, 2) . '%';
        $lineNum = ($lineKey + 1) . ' 行 / ' . ($lineCount + 1) . ' 行';

        $msg = <<<DOC

        当前进度：%s （%s）

        DOC;
        printf(
            $msg,
            Color::foreYellow($progress),
            Color::foreYellow($lineNum),
        );
    }

    public function highlightErrContent(string $contentStr): string
    {
        $result = [];
        $contentArr = explode("\n", $contentStr);
        $highlight = false;
        foreach ($contentArr as $line) {
            $isHLine = str_contains($line, self::ERR_MARK);
            $str = '';
            $arr = mb_str_split($line);
            foreach ($arr as $char) {
                in_array($char, ['“', '‘']) && $highlight = true;
                in_array($char, ['”', '’']) && $highlight = false;
                if ($highlight || in_array($char, ['”', '’'])) {
                    if ($isHLine) {
                        $str .= Color::backRedForePurple($char);
                    } else {
                        $str .= Color::forePurple($char);
                    }
                } else {
                    if ($isHLine) {
                        $str .= Color::backRed($char);
                    } else {
                        $str .= Color::foreBlue($char);
                    }
                }
            }
            $result[] = $str;
        }

        return rtrim(implode("\n", $result));
    }

    public function displayAutoFixExpr(string $expr, array $replaces)
    {
        $msg = <<<DOC

        -------

        当前 search:
        %s
        当前 replace:
        %s

        如数量过多，可尝试到【文件全局搜索】中，使用上面列出的正则表达式批量修正同类问题。
        注意：“上下文行数”请最少设置为 1 行，否则某些跨行修改会出错。

        -------

        DOC;

        // TODO: 临时打印一下，待整理
        $showExprMap = [
            "/(“[^<>”]*)(.*)\n/um" => '/(“[^<>”]*)\n/um',
        ];
        $showReplaceMap = [
            "/“([^\n。…？！；～~（）：“”‘’]+?)”(?=.*”)/um" => '‘$1’',
            "/[”’]([^\n、，。…？！；～~（）：“”‘’]+?)[“‘]/um" => '“$1”',
            "/(“[^<>”]*)(.*)\n/um" => '$1”\n',
        ];

        $showExprStr = $showExprMap[$expr] ?? $expr;
        $showExprStr = substr(str_replace(["\n", '/um'], ['\\n', ''], $showExprStr), 1);
        $showReplaceStr = $showReplaceMap[$expr] ?? str_replace("\n", '\\n', implode($replaces));

        printf($msg, Color::backPurple('【' . $showExprStr . '】'), Color::backPurple('【' . $showReplaceStr . '】'));
    }

    public function displayAutoFixOption(
        string $errName,
        string $errMsg,
        string $matchStr,
        string $replaceStr,
        string $opFixCur,
        string $opFixWhole,
        string $opSkipFix,
        string $opForceSkip,
        string $opForceFix
    ): void {
        $msg = <<<DOC

        已查出上面的%s中出现%s的错误。

        %s如下：
        %s

        可选择替换为对应的%s，如下：
        %s

        如上面显示的【替换词条】出错，需要到编辑器中手动修正该处内容。

        DOC;
        printf(
            $msg,
            Color::foreYellow(self::ERR_MARK),
            Color::foreYellow($errName),
            Color::foreYellow('“匹配词条”'),
            Color::backBlue($matchStr),
            Color::foreYellow('“替换词条”'),
            Color::backBlue($replaceStr),
        );

        echo PHP_EOL . Color::foreYellow($errMsg) . PHP_EOL . PHP_EOL;

        $msg = <<<DOC
        请在下方输入 {$opFixCur} 或 {$opFixWhole} 或 {$opSkipFix} 确认修改：
        输入 {$opFixCur} 则只改当前这一行内出现的词条
        输入 {$opFixWhole} 则在整个文件内全局替换
        输入 {$opSkipFix} 则切换自动检查和修复的类型

        输入 {$opForceSkip} 可强制跳过当前行（当这一行中确认无引号错误时），继续往下查错
        输入 {$opForceFix} 可跳过当前行并强制修复文件中的【双引号外的单引号】

        如果使用【{$opForceFix}】选项，请勿对文件进行任何额外的手动编辑，
        请在确保整个文件都无引号错误后，才使用【{$opForceFix}】选项来进行单引号的强制修复

        DOC;
        echo Color::foreRed($msg);
    }

    public function displayDefaultDump($opExit, $opForceSkip, $opForceFix)
    {
        $msg = <<<DOC

        已查出引号混乱，请查看上方报错信息，并修改原文件的相应内容。

        修改完原文件中的上述引号错误后，请输入 0 或 {$opExit} 进行后续操作：
        输入 0 （或可不输入，直接回车）继续检查
        输入 {$opExit} 退出脚本

        输入 {$opForceSkip} 可强制跳过当前行（当这一行中确认无引号错误时），继续往下查错
        输入 {$opForceFix} 可跳过当前行并强制修复文件中的【双引号外的单引号】

        如果使用【{$opForceFix}】选项，请勿对文件进行任何额外的手动编辑，
        请在确保整个文件都无引号错误后，才使用【{$opForceFix}】选项来进行单引号的强制修复。

        DOC;
        echo Color::foreRed($msg);
    }
}
