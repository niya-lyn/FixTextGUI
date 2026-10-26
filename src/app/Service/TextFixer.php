<?php

namespace App\Service;

use App\Exception\AppException;
use App\Util\Util;
use App\Util\Config;
use App\Util\Console\Show;
use App\Trait\FileWalkerTrait;

class TextFixer
{
    use FileWalkerTrait;

    private static $instance;

    /**
     * 当前处理的书籍信息
     */
    protected $bookDir      = '';
    protected $bookFile     = ''; // 书籍文件名，带前后缀，如 a.txt
    protected $bookName     = ''; // 去除后缀以及【EPUB 合并文件】前缀
    protected $bookFiles    = [];
    protected $bookDirIndex = 0; // -_-||

    /**
     * 多层递归中利用这个标记判断是否需要重新生成词库
     * 还是会造成一些重复操作，待优化
     */
    protected $rebuildReplaceMap = false;

    /**
     * @var bool 是否正在对备份书籍进行预处理
     */
    protected $preprocessing = false;

    protected $beforeArr = [];
    protected $afterArr  = [];

    protected static $goReplaceMapFiles = [];

    protected $useMapsConfigIndex = 0;

    protected $useStrictMode = 0;

    protected $zhuyinMode = 0;

    protected $splitMultiZhuyin = 0;

    /**
     * @param bool $new 是否重新生成
     * @return static
     */
    public static function getInstance(bool $new = false)
    {
        if (!static::$instance || $new) {
            static::$instance = new static();
        }

        return static::$instance;
    }

    private function __construct()
    {
        $this->bookDirIndex = mt_rand(10000, 99999);
    }

    public static function shouldReplaceByGo()
    {
        return REPLACE_BY_GO && file_exists(GO_REPLACE_CMD_FILE);
    }

    public function getBookDir(): string
    {
        return $this->bookDir;
    }

    public function setBookDir(string $bookDir)
    {
        $this->bookDir = $bookDir;
    }

    public function getBookFile()
    {
        return $this->bookFile;
    }

    public function setBookFile($bookFile)
    {
        $this->bookFile = $bookFile;
    }

    public function setPreprocessing(bool $value)
    {
        $this->preprocessing = $value;
    }

    public function setUseStrictMode($useStrictMode)
    {
        $this->useStrictMode = $useStrictMode;
    }

    public function getUseStrictMode(): int
    {
        return $this->useStrictMode;
    }

    public function setZhuyinMode($zhuyinMode)
    {
        $this->zhuyinMode = $zhuyinMode;
    }

    public function setSplitMultiZhuyin($splitMultiZhuyin)
    {
        $this->splitMultiZhuyin = $splitMultiZhuyin;
    }

    public function getZhuyinMode(): int
    {
        return $this->zhuyinMode;
    }

    public function getSplitMultiZhuyin(): int
    {
        return $this->splitMultiZhuyin;
    }

    public function setUseMapsConfigIndex($useMapsConfigIndex)
    {
        $this->useMapsConfigIndex = $useMapsConfigIndex;
    }

    public function getUseMapsConfigIndex(): int
    {
        return $this->useMapsConfigIndex;
    }

    public function getBookName()
    {
        return $this->bookName;
    }
    /**
     * @throws AppException
     */
    public function fixBooks($bookDir)
    {
        $this->setBeforeWalkFunc(function ($bookDir, $files) {
            $this->setBookDir($bookDir);

            if ($files != $this->bookFiles) {
                // 每进入一个目录，就递增 dirIndex 索引值，重新生成 map
                // 是为了加载不同目录中的特定书籍 bookMap，避免一直使用同一个目录的 bookMap
                $this->bookFiles = $files;
                $this->bookDirIndex++;
                $this->rebuildReplaceMap = true;
                Map::resetPostFixMap();
            }

            $this->preprocessing && $this->printFinished = false;
        });

        $this->setInWalkFunc(function ($bookDir, $file) {
            // 修正当前目录内所有文本文件
            $this->bookFile = $file;
            $this->bookName = Util::getFilename($this->bookFile, true);

            $content = file_get_contents($file);
            $this->replaceContent($content);
            file_put_contents($file, $content);
        });

        $this->walkFiles($bookDir);

        self::clearGoReplaceFiles();
    }

    public static function clearGoReplaceFiles()
    {
        foreach (self::$goReplaceMapFiles as $file) {
            file_exists($file) && unlink($file);
        }

        self::$goReplaceMapFiles = [];
    }

    public static function isNoPreprocessFix()
    {
        return Util::getArgvByIndex(2) == 'no-preprocess-fix';
    }

    public static function isTempFix()
    {
        return Util::getArgvByIndex(2) == 'temp-fix';
    }

    public function isUsingExtraMap(): bool
    {
        return $this->useMapsConfigIndex == Config::getMap('extraMapIndex');
    }

    public function isShengpiziIndex(): bool
    {
        return $this->useMapsConfigIndex == Config::getMap('shengpiziIndex');
    }

    /**
     * @throws AppException
     */
    protected function replaceContent(&$content)
    {
        list($beforeArr, $afterArr) = $this->buildReplaceMap();
        if (!$beforeArr || !$afterArr) {
            return;
        }

        $this->doReplace($content, $beforeArr, $afterArr);

        $this->regexReplace($content);

        $this->postFix($content);
    }

    /**
     * @throws AppException
     */
    protected function buildReplaceMap()
    {
        if ($this->beforeArr && $this->afterArr && !$this->rebuildReplaceMap) {
            // 处理多文件时不重复生成
            return [$this->beforeArr, $this->afterArr];
        }

        // 重置 map 生成标记，处理同一目录中的文件时只生成一次
        $this->rebuildReplaceMap = false;

        $useMaps = $this->preprocessing ? Map::loadBakUseMaps() : Map::loadUseMaps();
        if (!$useMaps) {
            return [[], []];
        }

        $actualMap = [];
        foreach ($useMaps as $mapName => $map) {
            $this->filterForExtraMap($mapName, $map);
            $actualMap = array_merge($actualMap, $map);
        }

        $bookMaps = Map::loadBookMaps($this->bookFiles);
        $actualMap = array_merge($actualMap, $bookMaps);

        $sortedMap = Map::flattenMaps($actualMap);
        $this->beforeArr = array_column($sortedMap, 'before');
        $this->afterArr = array_column($sortedMap, 'after');

        return [$this->beforeArr, $this->afterArr];
    }

    /**
     * 使用 extraMap 时排除掉 normalMap 中不含“的地得”和“像象”的词条
     *
     * @param string $mapName
     * @param array $map
     * @return void
     */
    protected function filterForExtraMap($mapName, &$map)
    {
        if ($mapName != 'normalMap') {
            return;
        }

        if (!$this->isUsingExtraMap()) {
            return;
        }

        $validKeywords = ['的', '地', '得', '像', '象'];
        $map = array_filter($map, function ($word) use ($validKeywords) {
            if (!is_string($word['after'])) {
                return true;
            }

            // 前后值相等的防误伤词条也需要使用
            if (is_array($word['before']) && in_array($word['after'], $word['before'])) {
                return true;
            } else if ($word['before'] == $word['after']) {
                return true;
            }

            // 检查 'before' 是否包含有效关键词
            if (is_array($word['before'])) {
                foreach ($word['before'] as $v) {
                    if (Util::multiStrContains($v, $validKeywords)) {
                        return true;
                    }
                }
            } else if (Util::multiStrContains($word['before'], $validKeywords)) {
                return true;
            }

            // 检查 'after' 是否包含有效关键词
            if (Util::multiStrContains($word['after'], $validKeywords)) {
                return true;
            }

            // 如果不满足上述任何条件，则移除该词条
            return false;
        });

        $map = array_values($map);
    }

    /**
     * @throws AppException
     */
    protected function doReplace(&$content, $beforeArr, $afterArr, $singleReplace = false, $mapSuffix = "")
    {
        if (!$beforeArr || !$afterArr) {
            return;
        }

        // 初步分析得知，部分有隐晦关联的词条还是需要二次替换来保证准确率
        Map::doSingleReplace() && $singleReplace = true;
        $replaceCount = $singleReplace ? 1 : 2; // 若是在 postFix 流程中，只替换一次就可以了

        /**
         * 替换规则说明（适用于 Go 和 PHP 两种方式）：
         * 通过额外设置如“暴发户->暴发户”的词条，当先匹配到此词条时（需要保证较长词条先被匹配）
         * 文本字符串指针就会移动到该词条后的下一位置，不会再因为“暴发->爆发”的词条存在而进行“暴发户->爆发户”的误替换
         * 也即是正向最大匹配
         */

        // 尝试使用 Go 替换，失败则降级到 PHP 替换
        if (self::shouldReplaceByGo()) {
            $usePHPFallback = !$this->replaceByGo($content, $beforeArr, $afterArr, $replaceCount, $mapSuffix);
            $shouldReverse = true;
        } else {
            $usePHPFallback = true;
            $shouldReverse = false;
        }

        if ($usePHPFallback) {
            $this->replaceByPHP($content, $beforeArr, $afterArr, $replaceCount, $shouldReverse);
        }
    }

    /**
     * @return bool 是否替换成功
     */
    protected function replaceByGo(&$content, $beforeArr, $afterArr, $replaceCount, $mapSuffix)
    {
        // 要在用 Go 替换前再写一遍文件，待优化写法
        if (!file_put_contents($this->bookFile, $content)) {
            Show::warning('go 替换：文件写入失败，转用 php 替换');
            return false;
        }

        $content = null; // 释放内存

        // 准备 Go 替换所需的映射
        list($goBeforeMap, $goAfterMap) = $this->goReplaceMap($beforeArr, $afterArr, $mapSuffix);

        // 执行 Go 替换命令
        list($execOutput, $execCode) = Util::formatArgsAndExec(
            GO_REPLACE_CMD_FILE,
            true,
            $this->getBookFilepath($this->bookFile),
            $goBeforeMap,
            $goAfterMap,
            $replaceCount,
        );

        // 读取替换后的内容
        $content = file_get_contents($this->bookFile);

        // 验证结果
        if (!$content) {
            throw new AppException("替换异常，{$this->bookName} 文件内容为空");
        }

        if ($execCode !== 0) {
            Show::warning("go 替换报错（退出码: {$execCode}），转用 php 替换，可及时在论坛反馈");
            return false;
        }

        return true;
    }

    /**
     * 使用 PHP 原生函数进行替换
     */
    protected function replaceByPHP(&$content, $beforeArr, $afterArr, $replaceCount, $shouldReverse)
    {
        if ($shouldReverse) {
            // 从 Go 替换降级到 PHP 替换时，需要逆序以恢复从短到长
            // 直接使用 PHP 替换则无需逆序
            $beforeArr = array_reverse($beforeArr);
            $afterArr = array_reverse($afterArr);
        }

        $map = array_combine($beforeArr, $afterArr);

        // strtr 函数执行结果和 Go 替换方法一致
        // 性能说明：短词条时与 Go 相近，但词条变长时效率会急剧下降
        // 注意：不要尝试使用 str_replace，会直接跪
        for ($i = 0; $i < $replaceCount; $i++) {
            $content = strtr($content, $map);
        }
    }

    protected function goReplaceMap($beforeArr, $afterArr, $mapSuffix = '')
    {
        $goBeforeMap = TXT_REPLACE_BEFORE . $this->bookDirIndex . '.txt';
        $goAfterMap = TXT_REPLACE_AFTER . $this->bookDirIndex . '.txt';

        if ($mapSuffix) {
            $goBeforeMap = $goBeforeMap . $mapSuffix . '.txt';
            $goAfterMap = $goAfterMap . $mapSuffix . '.txt';
        }

        if (!in_array($goBeforeMap, self::$goReplaceMapFiles)) {
            self::$goReplaceMapFiles[] = $goBeforeMap;
            self::$goReplaceMapFiles[] = $goAfterMap;
        }

        if (file_exists($goBeforeMap) && file_exists($goAfterMap)) {
            return [$goBeforeMap, $goAfterMap];
        }

        $beforeStr = json_encode(array_values($beforeArr), JSON_UNESCAPED_UNICODE);
        file_put_contents($goBeforeMap, $beforeStr);
        $afterStr = json_encode(array_values($afterArr), JSON_UNESCAPED_UNICODE);
        file_put_contents($goAfterMap, $afterStr);

        return [$goBeforeMap, $goAfterMap];
    }

    public function getBookFilepath($filename)
    {
        return $this->getBookDir() . "/{$filename}";
    }

    /**
     * @throws AppException
     */
    protected function regexReplace(&$content)
    {
        if ($this->preprocessing || !Map::getEnableRegexFix()) {
            return;
        }

        $regexMap = Map::loadRegexMap();
        Map::removeExcludedRegexes($regexMap, $this->bookName);
        Util::multiRegexReplace($regexMap, $content);
    }

    /**
     * @throws AppException
     */
    protected function postFix(&$content)
    {
        if ($this->preprocessing) {
            return;
        }

        $bookMaps = Map::loadBookMaps($this->bookFiles);
        $postFixMap = Map::loadPostFixMap();
        // 合并书籍词条，避免 postFixMap 误改
        $postFixMap = array_values(array_merge($bookMaps, $postFixMap));
        if ($postFixMap) {
            $this->doReplace(
                $content,
                array_column($postFixMap, 'before'),
                array_column($postFixMap, 'after'),
                true,
                '【POSTFIX】'
            );
        }

        // 单独替换书籍词条，保证修改
        $this->doReplace(
            $content,
            array_column($bookMaps, 'before'),
            array_column($bookMaps, 'after'),
            true,
            '【BOOKMAPS】'
        );

        // 生僻字注音
        if ($this->isShengpiziIndex()) {
            (new ZhuyinProcessor($this))->processZhuyin($content);
        }
    }
}
