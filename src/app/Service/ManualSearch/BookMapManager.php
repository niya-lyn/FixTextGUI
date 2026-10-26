<?php

namespace App\Service\ManualSearch;

use App\Util\Util;
use App\Service\Map;

class BookMapManager
{
    public function excludeSearchedMarks(string $file, array &$patterns): void
    {
        $content = $this->getBookMapContent($file);
        if ($content === null) { // 无文件则不操作
            return;
        }

        $origMarks = $this->getManualSearchedMarks($content);
        $patterns = array_filter($patterns, fn($v) => !in_array($v['mark'], $origMarks));
        $patterns = array_values($patterns);
    }

    public function mergeMarksToBookMap(array $selectedMarks, string $file): void
    {
        // 在书籍专有词库中记录所使用过的 mark
        $bookName = Util::getFilename($file, true);
        $bookMapFile = $this->getOrCreateBookMapFile($bookName);

        $content = file_get_contents($bookMapFile);
        $content = $this->updateMarksInContent($content, $selectedMarks);
        $content = str_replace("\r\n", "\n", $content);

        file_put_contents($bookMapFile, $content);
    }

    public function getManualSearchedMarks(string $content): array
    {
        if (!preg_match("/'manualSearchedMarks' => \[\n        (.*?)\n    \],/si", $content, $matches)) {
            return [];
        }

        $origMarksStr = $matches[1];
        $origMarks = explode("\n", $origMarksStr);

        return array_map(fn($v) => trim($v, ' ",'), $origMarks);
    }

    protected function getBookMapContent(string $file): ?string
    {
        $bookName = Util::getFilename($file, true);
        $bookMapFile = Map::getBookMapFileWithTags($bookName);

        if (!$bookMapFile) {
            return null;
        }

        return file_get_contents($bookMapFile);
    }

    protected function getOrCreateBookMapFile(string $bookName): string
    {
        $bookMapFile = Map::getBookMapFileWithTags($bookName);

        if (!$bookMapFile) { // 无文件则新建
            $bookMapFile = Map::getMapFilepath("书籍专有替换词库/{$bookName}.php");
            $content = "<?php\n\nreturn [\n];";
            file_put_contents($bookMapFile, $content);
        }

        return $bookMapFile;
    }

    protected function updateMarksInContent(string $content, array $selectedMarks): string
    {
        $origMarks = $this->getManualSearchedMarks($content);

        if (!$origMarks) {
            return $this->insertNewMarksSection($content, $selectedMarks);
        }

        return $this->updateExistingMarksSection($content, $origMarks, $selectedMarks);
    }

    protected function insertNewMarksSection(string $content, array $selectedMarks): string
    {
        $marksStr = '        "' . implode("\",\n        \"", $selectedMarks) . '",';
        $mergeContent = "    'manualSearchedMarks' => [\n{$marksStr}\n    ],";

        return str_replace("return [", "return [\n{$mergeContent}", $content);
    }

    protected function updateExistingMarksSection(string $content, array $origMarks, array $selectedMarks): string
    {
        $mergedMarks = array_values(array_unique(array_merge($origMarks, $selectedMarks)));
        $marksStr = '        "' . implode("\",\n        \"", $mergedMarks) . '",';
        $mergeContent = "'manualSearchedMarks' => [\n{$marksStr}\n    ],";

        return preg_replace(
            "/'manualSearchedMarks' => \[(.*?)\],/si",
            $mergeContent,
            $content,
        );
    }
}
