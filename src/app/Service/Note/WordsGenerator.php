<?php

namespace App\Service\Note;

use App\Exception\AppException;
use App\Util\Config;
use App\Util\Util;
use App\Util\Console\Show;
use App\Service\Note\NoteParser;
use App\Service\Note\NoteConverter;
use App\Service\Note\NoteClassifier;
use App\Service\Note\MultilineProcessor;
use App\Service\Note\ResultGenerator;
use Inhere\Console\Util\Interact;

/**
 * 根据文石、多看、静读天下等软件导出的校对批注，生成 FixText 脚本所需的临时词条
 * 注意，批注的具体内容中不能包含相应标记的字符串
 */
class WordsGenerator
{
    protected string $bookExt = "txt";

    protected NoteParser $parser;
    protected NoteConverter $converter;
    protected NoteClassifier $classifier;
    protected MultilineProcessor $multilineProcessor;
    protected TagVariantWrapper $tagVariantWrapper;
    protected ResultGenerator $resultGenerator;

    public function __construct()
    {
        $fixedNoteRules = Config::getGeneral("fixedNoteRules");
        $simpleFixedCombos = Config::getGeneral("simpleFixedCombos");

        $this->parser = new NoteParser();
        $this->converter = new NoteConverter($fixedNoteRules, $simpleFixedCombos);
        $this->classifier = new NoteClassifier();
        $this->resultGenerator = new ResultGenerator();
    }

    /**
     * 生成临时校对表
     */
    public function generate(): void
    {
        // 1. 选择书籍格式
        $this->selectBookFormat();

        // 2. 初始化多行、标签变体处理器（根据书籍格式）
        $this->multilineProcessor = new MultilineProcessor($this->bookExt);
        $this->tagVariantWrapper = new TagVariantWrapper($this->bookExt);

        // 3. 获取批注文件
        chdir(dirname(EPUB_MERGE_LOG_DIR));
        $textFiles = Util::globOnlyFiles("*");

        // 4. 处理所有批注文件
        $this->processBatchNotes($textFiles);

        // 5. 生成结果文件
        $maps = $this->classifier->getMaps();
        $this->resultGenerator->generate($maps);

        Show::successWithNL("已从批注中生成临时校对表");
    }

    /**
     * 根据固定规则转换单个批注（供外部调用）
     */
    public function convertByFixedNoteRules(string $before, string $after): string
    {
        $match = ['', $before, $after];
        $note = $this->converter->createNote($match);
        $convertedNote = $this->converter->convertNoteByRules($note);

        if (!$convertedNote) {
            return '';
        }

        return $this->resultGenerator->convertSingleRule([$convertedNote]);
    }

    /**
     * 选择书籍格式
     */
    protected function selectBookFormat(): void
    {
        $exts = ['epub', 'txt'];
        $selectedExt = (int)Interact::select(
            '需要用批注修改哪种格式的书籍？',
            $exts,
            '0',
            false
        );

        $this->bookExt = $exts[$selectedExt];
    }

    /**
     * 批量处理批注文件
     */
    protected function processBatchNotes(array $textFiles): void
    {
        foreach ($textFiles as $file) {
            $content = file_get_contents($file);

            try {
                $matches = $this->parser->parseFileContent($content);
                foreach ($matches as $match) {
                    $note = $this->converter->createNote($match);
                    $this->processNote($note);
                }
            } catch (AppException $e) {
                throw new AppException("在 {$file} 中出现异常：" . $e->getMessage());
            }
        }
    }

    /**
     * 处理单个批注
     */
    protected function processNote(array $note): void
    {
        // 尝试对规则进行一些特定转换
        $convertedNote = $this->converter->convertNoteByRules($note);

        if ($convertedNote) { // 如果为 null，说明是“普通映射”，不用标记
            $convertedNote['convertedByRules'] = true; // 标记为通过规则转换
            $note = $convertedNote;
        }

        // 处理多行变体
        $notes = $this->multilineProcessor->mergeMultilineVariants($note);

        // 处理标签变体
        $finalNotes = [];
        foreach ($notes as $lineNote) {
            $tagVariants = $this->tagVariantWrapper->processTagVariants($lineNote);
            foreach ($tagVariants as $v) {
                $finalNotes[] = $v;
            }
        }

        // 如果最终生成的记录数大于 1，说明存在变体
        if (count($finalNotes) > 1) {
            // 生成一个唯一的 ID（这里使用 uniqid 加前缀，足够满足本地脚本生成需求）
            $groupId = uniqid('word_');

            // 遍历所有衍生出的变体，给它们分配相同的 ID
            foreach ($finalNotes as &$singleNote) {
                $singleNote['id'] = $groupId;
            }
            unset($singleNote); // 释放引用
        }

        // 进行分类
        foreach ($finalNotes as $singleNote) {
            $this->classifier->classify($singleNote);
        }
    }
}
