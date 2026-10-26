<?php

namespace App\Service\Note;

use App\Exception\AppException;
use App\Util\Config;

/**
 * 批注解析器 - 负责解析不同格式的批注
 */
class NoteParser
{
    protected array $noteMatchPatterns;
    protected array $noteBrandProcessors;

    public function __construct()
    {
        $this->noteMatchPatterns = Config::getGeneral('noteMatchPatterns');
        $this->noteBrandProcessors = Config::getGeneral('noteBrandProcessors');
    }

    /**
     * 解析文件内容，提取批注
     */
    public function parseFileContent(string $content): array
    {
        $content = $this->normalizeContent($content);
        $matches = $this->extractMatches($content);

        if (empty($matches)) {
            throw new AppException("未找到匹配的批注内容");
        }

        return $this->cleanMatches($matches);
    }

    /**
     * 标准化文件内容，更改换行符，添加 <EOF> 文件结尾标记
     */
    protected function normalizeContent(string $content): string
    {
        $content = str_replace(["\r\n", "\r"], "\n", $content);
        $content = str_replace(['\n　　', '\n  '], '\n', $content);

        return $content . "\n<EOF>";
    }

    /**
     * 提取匹配的批注内容
     */
    protected function extractMatches(string $content): array
    {
        foreach ($this->noteMatchPatterns as $brand => $pattern) {
            preg_match_all("/{$pattern}/ums", $content, $matches, PREG_SET_ORDER);

            if (!empty($matches)) {
                // 调用品牌特定的处理方法
                $this->processBrandSpecificMatches($brand, $matches);
                return $matches;
            }
        }

        return [];
    }

    /**
     * 处理特定品牌软件的匹配结果
     */
    protected function processBrandSpecificMatches(string $brand, array &$matches): void
    {
        $method = $this->noteBrandProcessors[$brand] ?? null;

        if ($method && is_callable($method)) {
            /**
             * 具体内容见 config/general.php 的 noteBrandProcessors 配置
             */
            $method($matches);
        }
    }

    /**
     * 清理匹配结果，移除行首的多余空格和尾行的多余换行符
     */
    protected function cleanMatches(array $matches): array
    {
        foreach ($matches as &$match) {
            $match[1] = trim($match[1], "\n");
            $match[1] = preg_replace('/^[ 　]*$\n/um', '', $match[1]);

            if (isset($match[2]) && $match[2]) {
                $match[2] = trim($match[2], "\n");
                $match[2] = preg_replace('/^[ 　]*$\n/um', '', $match[2]);
            }
        }

        return $matches;
    }
}
