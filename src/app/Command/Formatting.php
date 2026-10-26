<?php

namespace App\Command;

use Exception;
use App\Util\Util;
use App\Util\Console\Show;
use Inhere\Console\Command;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;
use Inhere\Console\Util\Interact;
use App\Service\Formatting\Option;
use App\Service\Formatting\FileProcessor;

class Formatting extends Command
{
    protected static string $name = 'formatting';
    protected static string $desc = '文本排版';

    protected Option $option;

    /**
     * @throws Exception
     */
    public function execute(Input $input, Output $output): void
    {
        while (true) {
            Util::unifyAllBooksFormat();

            $this->option = new Option;

            $this->selectAction();

            (new FileProcessor($this->option))->process(BOOK_DIR);

            if (!$this->restart()) {
                Show::writeWithNL('【退出脚本】', true);
            }
        }
    }

    protected function selectAction(): void
    {
        $actionOptions = [
            [
                'desc'   => '<primary>排版文本</primary>（处理成正文的<primary>段落间无空行、每行缩进两全角空格；章节间空两行</primary>、章节标题行无缩进）',
                'action' => fn() => $this->option->changeTextFormat = true,
            ],
            [
                'desc'   => '<primary>排版文本</primary>（<primary>去除所有的空行和缩进</primary>，可简单套上 <p> 标签，用于比较不同格式的文本）',
                'action' => fn() => $this->indentationAndHtmlTagOptions(),
            ],
            [
                'desc'   => '转换文本的<primary>【编码及换行符】</primary>（仅支持 UTF-8 编码和 GB2312 中文编码，仅支持 LF 和 CRLF 换行符）',
                'action' => fn() => $this->encodingOptions(),
            ],
            [
                'desc'   => '<primary>【提取 epub 中的文本】</primary>，整体合并后转换为 txt（转出来的 txt 将按照第一项的论坛格式自动排版）',
                'action' => fn() => $this->extractTextFromHtmlOptions(),
            ],
            [
                'desc'   => '规范部分常见<primary>【标点符号】</primary>，把英文标点转为中文标点，可更改【连续多行引号】的使用形式',
                'action' => fn() => $this->punctuationOptions(),
            ],
            [
                'desc'   => '统一更改文本中的引号形式（在<primary>【弯引号】</primary> “”‘’ 和<primary>【直角引号】</primary>「」『』 间进行转换）',
                'action' => fn() => $this->quotationTypeOptions(),
            ],
            [
                'desc'   => '在文本的首尾添加<primary>【个人校对信息】</primary>（请先打开配置文件更改 username 参数）',
                'action' => fn() => $this->option->addOpInfo = true,
            ],
            [
                'desc'   => '（请务必使用 BC 检查）转换文本中的<primary>【英文大小写】</primary>（首字母大写、全改成小写、全改成大写）',
                'action' => fn() => $this->changeCaseOptions(),
            ],
            [
                'desc'   => '（请务必使用 BC 检查）将文本中的<primary>【阿拉伯数字转为中文数字】</primary>',
                'action' => fn() => $this->option->arabicToChineseNum = true,
            ],
            [
                'desc'   => '（请务必使用 BC 检查）移除正文中的<primary>【中文字符之间的空格】</primary>',
                'action' => fn() => $this->option->rmSpacesBetweenChnChars = true,
            ],
            [
                'desc'   => '将 books 和 booksBak 中的书籍文件<primary>【按标点强制分行】</primary>',
                'action' => fn() => $this->splitByPunctuationsOptions(),
            ],
            [
                'desc'   => '在中文字符和英文字母、数字之间<primary>【添加空格】</primary>，使之符合排版规范',
                'action' => fn() => $this->option->paranoidTextSpacing = true,
            ],
            [
                'desc'   => '处理自定义<primary>【分级标题】</primary>',
                'action' => fn() => $this->option->formatHeadings = true,
            ],
            [
                'desc'   => '对<primary>【极特殊字符】</primary>（如部分 Emoji 表情和生僻字）进行转义或还原',
                'action' => fn() => $this->processSpecialCharsOptions(),
            ],
        ];

        // 获取用户选择的索引
        $actionDescs = array_column($actionOptions, 'desc');
        $actionIndex = Interact::select(
            '请输入各选项前的索引数字，进行对应的排版操作：',
            $actionDescs,
            '0',
            false
        );
        Show::showSelectedOpt($actionIndex, $actionDescs);

        // 执行对应的操作
        if (isset($actionOptions[$actionIndex])) {
            $actionOptions[$actionIndex]['action']();
        }
    }

    /**
     * @throws Exception
     */
    protected function restart()
    {
        $msg = <<<DOC

        ==================================
        <success>【已完成该轮排版】</success>
        ==================================

        请输入 <primary>0</primary> 或 <primary>1</primary>。
        输入 <primary>0</primary> 不做任何操作，直接退出脚本。
        输入 <primary>1</primary> 则可以继续选用不同的选项，进行下一轮排版。

        <red1>【请在 BC 或“文件全局搜索”中比较确认完当前这一轮的排版结果后，再进行下一轮的排版】</red1>
        DOC;
        Show::writeWithNL($msg);

        $restart = Interact::readln('请输入：');
        if ($restart === '') { // 不输入也继续下一轮
            return true;
        }

        $restart = (int)$restart;
        if ($restart == 1) {
            return true;
        }

        return false;
    }

    protected function indentationAndHtmlTagOptions(): void
    {
        $this->option->addIndentation   = false;
        $this->option->changeTextFormat = true;

        $opts = [
            '不改动 html 标签',
            '给文本中所有的段落都套上 <p></p> 标签',
            '移除每个段落中的 <p></p> 标签',
        ];
        $selection = Interact::select('选择 html 标签操作', $opts, '0', false);
        Show::showSelectedOpt($selection, $opts);
        $this->option->addHtmlTag = $selection;
    }

    protected function encodingOptions(): void
    {
        $encodingOpts = [
            '将文件编码转为 UTF-8',
            '将文件编码转成 GB18030/GB2312（中文编码，有可能出现以 ? 为标识的缺失字符，建议使用 BC 比对结果）',
        ];
        $encodingSelection = (int)Interact::select('选择文件编码', $encodingOpts, '0', false);
        $toEncoding = $encodingSelection == 1 ? 'GB18030' : 'UTF-8';
        echo PHP_EOL;

        $newlineTypeOpts = [
            '将文件换行符转为 LF（即 \n）',
            '将文件换行符转成 CR+LF（即 \r\n，如果还要用 txtFormat 进一步校对，建议选这一项）',
        ];
        $newLineSelection = (int)Interact::select('选择文件编码', $newlineTypeOpts, '0', false);
        $newLineType = $newLineSelection == 1 ? "\r\n" : "\n";

        $this->option->toEncoding = $toEncoding;
        $this->option->newLineType = $newLineType;

        $info = "编码：{$toEncoding} | ";
        $newLineType = $newLineType == "\r\n" ? 'CR+LF' : 'LF';
        $info .= "换行符：{$newLineType}";
        Show::showSelectedOpt($info);
    }

    protected function extractTextFromHtmlOptions(): void
    {
        $this->option->extractTextFromHtml = true;

        $opts = [
            '不在提取的 txt 文件中加入【论坛用户信息】',
            '在 txt 文件中自动附加【论坛用户信息】',
        ];
        $selection = Interact::select('选择操作：', $opts, '0', false);
        $this->option->setExtraTextInfo = !($selection == 0);
        Show::showSelectedOpt($selection, $opts);
    }

    protected function punctuationOptions()
    {
        $info = <<<DOC
        <note>【此选项有如下效果】</note>

        1. 将英文标点转为中文标点（不影响纯英文内容）
        2. 去除部分标点间的空格
        3. 将全角的英文数字及部分数学符号等改为半角
        4. 更改连续多行的引号使用形式

        关于此选项的细节可以查看 <primary>src/config/formatting</primary> 文件中的 <primary>punctuationPatterns</primary> 配置，
        可以自行删改一些正则表达式

        —————————————————————————————

        DOC;
        Show::writeWithNL($info);

        $type1Doc = <<<DOC
        “我是第一段话。
        我是第二段话。
        我是最后一段话。”
        DOC;

        $type2Doc = <<<DOC
        “我是第一段话。
        “我是第二段话。
        “我是最后一段话。”
        DOC;

        $info = <<<DOC
        <note>【请在下方输入对应数字更改多行引号使用形式】</note>

        输入<primary>【0】</primary>不更改多行引号使用形式。

        —————————————————————————————

        输入<primary>【1】</primary>将如下多行引号使用形式：

        {$type1Doc}

        改为：

        {$type2Doc}

        —————————————————————————————

        输入<primary>【2】</primary>将如下多行引号使用形式：

        {$type2Doc}

        改为：

        {$type1Doc}
        DOC;
        Show::writeWithNL($info);

        $selection = (int)Interact::readln('请输入：');
        $info = '无操作';
        if ($selection == 0) {
            $info = '不改动多行引号使用形式';
        } else if ($selection == 1) {
            $info = '更改为规范的多行引号形式';
        } else if ($selection == 2) {
            $info = '在连续段落中仅保留开头行和结尾行的引号';
        }
        Show::showSelectedOpt($selection, $info);
        $this->option->normalizePunctuations = true;
        $this->option->consecutiveQuotationsType = $selection;
    }

    protected function quotationTypeOptions()
    {
        $opts = [
            '不改变引号形式',
            '将文本中所有引号转为弯引号 “”‘’',
            '将文本中所有引号转为直角引号 「」『』',
        ];
        $selection = (int)Interact::select('选择操作：', $opts, '0', false);
        Show::showSelectedOpt($selection, $opts);
        $this->option->quotationType = $selection;
    }

    protected function changeCaseOptions()
    {
        $opts = [
            '无操作，不做任何修改',
            '将文本中的英文单词和句子的<primary>【首字母】</primary>改成大写',
            '将文本中的所有英文<primary>全改成小写</primary>',
            '将文本中的所有英文<primary>全改成大写</primary>',
            '只处理固定的英文词组（在 <primary>fixedCaseWords</primary> 变量中进行设置）',
        ];
        $selection = (int)Interact::select('选择操作：', $opts, '0', false);
        Show::showSelectedOpt($selection, $opts);
        $this->option->changeCaseInText = $selection;
    }

    protected function splitByPunctuationsOptions()
    {
        Show::primaryWithNL('【此选项会在文本的每个结尾标点处增加“分隔+换行”，'
            . '减轻文本比较时因标点和换行有差异带来的影响】');
        Show::primaryWithNL('【注意会同时移除文件中的所有空格缩进，'
            . '后续需要重新进行排版】');
        $opts = [
            '无操作，不做任何修改',
            '根据【，。？！】等标点<primary>强制分行</primary>',
            '去除分行标记，<primary>还原分行</primary>',
        ];
        $selection = (int)Interact::select('选择操作：', $opts, '0', false);
        Show::showSelectedOpt($selection, $opts);
        $this->option->splitByPunctuations = $selection;
    }

    protected function processSpecialCharsOptions()
    {
        Show::primaryWithNL('此选项会给极特殊的字符（包括部分 Emoji）添加转义标记，避免在 BC 比较时，'
            . '含 Emoji 的段落因长度过长而被截断，或因出现过于生僻的字符，导致报编码错误无法编辑');
        $opts = [
            '无操作，不做任何修改',
            '给 Emoji 表情和特殊生僻字<primary>添加标记，进行转义</primary>',
            '<primary>去除转义标记</primary>，还原 Emoji 表情和特殊生僻字',
        ];
        $selection = (int)Interact::select('选择操作：', $opts, '0', false);
        Show::showSelectedOpt($selection, $opts);
        $this->option->processSpecialChars = $selection;

        if ($selection == 1) {
            $opts = [
                '处理所有特殊字符（包括 Emoji 表情等）',
                '只处理特殊的生僻字（主要是 CJK 扩展区的字符）',
            ];
            $selection = (int)Interact::select('选择操作：', $opts, '0', false);
            Show::showSelectedOpt($selection, $opts);
            $this->option->specialCharsScope = $selection;
        }
    }
}
