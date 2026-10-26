<?php

namespace App\Service\Note;

use App\Exception\AppException;
use App\Util\Console\Color;
use App\Util\Console\Show;
use App\Util\Util;

/**
 * 替换检查器 - 用于检查“临时校对表”的替换结果，报告未命中的记录
 */
class ReplacementChecker
{
    protected string $tempMapFile;
    protected string $bookDir;
    protected array $bookContents = [];

    public function __construct(string $tempMapFile, string $bookDir)
    {
        $this->tempMapFile = $tempMapFile;
        $this->bookDir = $bookDir;
    }

    /**
     * 执行检查
     */
    public function check(): void
    {
        // 1. 加载要校对的数据
        $data = $this->loadTempData();

        if (!$data['genByNotes']) { // 只有通过笔记生成的才需要检查
            return;
        }

        $tempMap = $data['tempMap'];

        if (empty($tempMap)) {
            Show::warning("校对表为空，无需检查");
            return;
        }

        // 2. 加载所有 txt 文件内容到内存
        $this->loadBookContents();

        if (empty($this->bookContents)) {
            throw new AppException("{$this->bookDir} 文件夹中没有任何 txt 文件");
        }

        // 3. 将数据按 ID 分组（处理变体逻辑）
        $groups = $this->groupItems($tempMap);

        // 4. 执行匹配检查
        $this->executeMatch($groups);
    }

    /**
     * 读取并解析临时映射文件
     */
    protected function loadTempData(): array
    {
        if (!file_exists($this->tempMapFile)) {
            throw new AppException("校对表文件不存在: {$this->tempMapFile}");
        }

        // 引入临时校对表，该文件内预期定义了 $tempMap 和 $genByNotes 变量
        require $this->tempMapFile;

        if (!isset($tempMap) || !is_array($tempMap)) {
            throw new AppException("文件中未找到有效的 \$tempMap 变量");
        }

        return [
            'tempMap'    => $tempMap,
            'genByNotes' => isset($genByNotes) ? (bool)$genByNotes : false, // 如果没定义默认 false
        ];
    }

    /**
     * 将书籍目录下的 txt 文件内容读入内存（避免重复读取，提高性能）
     */
    protected function loadBookContents(): void
    {
        $files = glob(rtrim($this->bookDir, '/\\') . '/*.txt');

        foreach ($files as $file) {
            $this->bookContents[basename($file)] = file_get_contents($file);
        }
    }

    /**
     * 将记录按 id 分组
     * 无 id 的单条记录自动分配唯一内部编号，视为单人组
     */
    protected function groupItems(array $tempMap): array
    {
        $groups = [];
        $noIdIndex = 1;

        foreach ($tempMap as $item) {
            if (isset($item['id']) && $item['id'] !== '') {
                $groupId = $item['id'];
            } else {
                // 没有 id 的分配一个伪 ID，确保它们互相独立
                $groupId = 'single_item_' . $noIdIndex;
                $noIdIndex++;
            }

            $groups[$groupId][] = $item;
        }

        return $groups;
    }

    /**
     * 核心比对逻辑
     */
    protected function executeMatch(array $groups): void
    {
        $missedResults = []; // 收集所有未命中的记录

        foreach ($groups as $groupId => $variants) {
            $isMatched = false;

            // 遍历该组内的所有变体
            foreach ($variants as $variant) {
                $searchStr = $variant['after'];

                foreach ($this->bookContents as $content) {
                    if (str_contains($content, $searchStr)) {
                        $isMatched = true;
                        break 2; // 命中则跳出变体和文件的双重循环
                    }
                }
            }

            // 如果整个组都没有命中，将其加入未命中结果数组
            if (!$isMatched) {
                if (str_starts_with($groupId, 'single_item_')) {
                    // 没有 ID 的单条变体，直接把这条记录存入
                    $missedResults[] = $variants[0];
                } else {
                    // 带有 ID 的变体组，为了清晰，将它的所有变体作为一组存入
                    $missedResults[] = [
                        'variant_group_id' => $groupId,
                        'variants'         => $variants
                    ];
                }
            }
        }

        echo PHP_EOL;
        if (empty($missedResults)) {
            Show::successWithNL("检查完成：所有校对记录均已成功命中！");
        } else {
            $missCount = count($missedResults);
            Show::warnWithNL("检查完成：共发现 {$missCount} 组记录未命中，请检查。");

            // 统一输出格式和写出文件
            Show::primaryWithNL('临时校对表中的未命中记录如下：');
            $reportContent = Util::getArrStrWithIndex($missedResults);

            // 写入本地报告文件
            $reportFilePath = REPORT_DIR . '/临时校对表未命中结果.txt';
            file_put_contents($reportFilePath, $reportContent);

            // 在控制台打印黄色文字
            Show::writeWithNL(Color::yellow($reportContent));

            // 友好提醒用户可以看文件
            Show::infoWithNL("💡 提示：详细的未命中记录已保存，您也可以前往【{$reportFilePath}】中进行查看。");
        }
    }
}
