<?php

namespace App\Util;

use App\Exception\AppException;

class PatchAnalyzer
{
    protected $before = [];  // 单处差异的所有 - 行，如有跨行则合并成单行
    protected $after  = [];  // 单处差异的所有 + 行，如有跨行则合并成单行

    protected $befores = [];  // 整个 patch 中的所有 - 行（里面每个都是处理后的 before）
    protected $afters  = [];  // 整个 patch 中的所有 + 行（里面每个都是处理后的 after）

    protected $firstBeforeDiffLineKey = 0;
    protected $firstAfterDiffLineKey  = 0;

    protected $prevIsBeforeDiffLine = false;

    /**
     * @throws AppException
     */
    public function getDiffFromPatchFile(string $patchFilepath)
    {
        // 如果 windows 系统内没有设置 utf-8 文件名，
        // 可能头两行的文件名部分会有乱码，导致后续匹配失效，故这里直接将头两行移除
        $patchContent = file($patchFilepath);
        $patchContent = implode('', array_slice($patchContent, 2));

        Util::changeEncodingAndNewLineType($patchContent);

        // 强制最后有一行空行，确保对最后一处差异的提取操作可正常结束
        $patchContent = trim($patchContent) . "\n";

        $lines = explode("\n", $patchContent);
        foreach ($lines as $lineKey => $line) {
            $this->processLine($line, $lineKey, $lines);
        }

        if (count($this->befores) != count($this->afters)) {
            throw new AppException("{$patchFilepath} 中的 before 与 after 数量不一致");
        }

        return [$this->befores, $this->afters];
    }

    protected function processLine($line, $lineKey, $lines)
    {
        if ($this->isBeforeDiffLine($line)) {
            // 每个 - 行都直接提取，记录第一个 - 行的行号
            $this->processBeforeDiffLine($line, $lineKey);
        } elseif ($this->before) {
            // 单处差异的所有 - 行遍历完毕，遇到第一个非 - 行，结束对此处差异的提取
            $this->processEndOfBeforeDiff($line, $lines);
        }

        if ($this->isAfterDiffLine($line)) {
            // 每个 + 行都直接提取，记录第一个 + 行的行号
            $this->processAfterDiffLine($line, $lineKey, $lines);
        } elseif ($this->after) {
            // 单处差异的所有 + 行遍历完毕，遇到第一个非 + 行，结束对此处差异的提取
            $this->processEndOfAfterDiff($line, $lines);
        }
    }

    protected function isBeforeDiffLine($line)
    {
        return str_starts_with($line, '-') && !str_starts_with($line, '--');
    }

    protected function isAfterDiffLine($line)
    {
        return str_starts_with($line, '+') && !str_starts_with($line, '++');
    }

    protected function processBeforeDiffLine($line, $lineKey)
    {
        $this->firstBeforeDiffLineKey === 0 && $this->firstBeforeDiffLineKey = $lineKey;
        $this->before[] = ltrim($line, '-');
    }

    protected function processEndOfBeforeDiff($line, $lines)
    {
        // 需要判断紧跟在最后一个 - 行之后的是否为 + 行
        if ($this->isAfterDiffLine($line)) {
            // 若为 + 行，则将 before 内容先合并为单行，继续往下遍历 patch 内容
            $this->befores[] = implode('\n', $this->before); // 支持跨行，注意单引号

            $this->before = [];
        } else {
            // 若不为 + 行，说明双方存在相隔多行的内容差异（存在单独 - 行）
            // 需要提取 - 行的前后一行内容，生成比对结果
            if (isset($lines[$this->firstBeforeDiffLineKey - 1])) {
                $prevNonBeforeLine = ltrim($lines[$this->firstBeforeDiffLineKey - 1]);
                array_unshift($this->before, $prevNonBeforeLine);
                $this->after[] = $prevNonBeforeLine;
            }

            // 【这里是每处差异的处理出口】
            // 只有单独的 - 行，提取后结束处理
            $this->collectDiffLines($line);
        }

        $this->firstBeforeDiffLineKey = 0;
    }

    protected function processAfterDiffLine($line, $lineKey, $lines)
    {
        $prevLine = $lines[$lineKey - 1] ?? '';
        if (!$this->prevIsBeforeDiffLine) {
            $this->prevIsBeforeDiffLine = $this->isBeforeDiffLine($prevLine);
        }

        $this->firstAfterDiffLineKey === 0 && $this->firstAfterDiffLineKey = $lineKey;
        $this->after[] = ltrim($line, '+');
    }

    protected function processEndOfAfterDiff($line, $lines)
    {
        // 需要判断第一个 + 行的前一行是否为 - 行
        if ($this->prevIsBeforeDiffLine) {
            // 【这里是每处差异的处理出口】
            // 若为 - 行，可直接将对应的 - 行内容和 + 行内容合并收集，结束此处差异提取
            $lastBefore = array_pop($this->befores);
            $this->befores = array_values($this->befores);
            $lastBefore = explode('\n', $lastBefore);
            if ($this->shouldMergeAsMultiLine($lastBefore, $this->after)) {
                $this->befores = array_merge($this->befores, $lastBefore);
                $this->afters = array_merge($this->afters, $this->after);
            } else {
                $this->befores[] = implode('\n', $lastBefore);
                $this->afters[] = implode('\n', $this->after);
            }

            $this->after = [];
            $this->firstAfterDiffLineKey = 0;
            $this->prevIsBeforeDiffLine = false;
        } else {
            // 若不为 - 行，说明双方存在相隔多行的差异内容（即存在单独的 + 行）
            // 则需要提取前后行内容生成比对结果
            if (isset($lines[$this->firstAfterDiffLineKey - 1])) {
                $prevNonAfterLine = ltrim($lines[$this->firstAfterDiffLineKey - 1]);
                array_unshift($this->after, $prevNonAfterLine);
                $this->before[] = $prevNonAfterLine;
            }

            // 【这里是每处差异的处理出口】
            // 遍历完这一处差异的所有 + 行，提取后结束处理
            $this->collectDiffLines($line);
            $this->firstAfterDiffLineKey = 0;
        }
    }

    /**
     * 如果前后行元素数量相等，应该改为分行插入，这样可以避免处理跨行内容
     * 否则需要将多行合并成一行之后再插入
     *
     * @param array $before
     * @param array $after
     * @return bool
     */
    protected function shouldMergeAsMultiLine($before, $after)
    {
        if (count($before) != count($after)) {
            return false;
        }

        foreach ($before as $bk => $bv) {
            $av = $after[$bk];

            // 如果存在相同内容行，可能是连续几段的上下文中只有细微的差异
            // 也只能先合并再插入
            if ($bv == $av) {
                return false;
            }

            // 如果有单独空行也只能合并之后再插入
            if (($bv === '' && $av) || ($bv && $av === '')) {
                return false;
            }
        }

        return true;
    }

    protected function collectDiffLines($line)
    {
        $line = ltrim($line);
        $this->before[] = $line;
        $this->after[] = $line;

        $this->befores[] = implode('\n', $this->before);
        $this->afters[] = implode('\n', $this->after);

        $this->before = $this->after = [];
        $this->prevIsBeforeDiffLine = false;
    }
}
