<?php

namespace App\Service;

use App\Exception\AppException;
use App\Util\Util;
use App\Util\Config;

class Map
{
    protected static $useMaps    = [];
    protected static $bakUseMaps = [];
    protected static $regexMap   = [];
    protected static $bookMaps   = [];
    protected static $postFixMap = [];

    protected static $excludedWords   = [];
    protected static $excludedRegexes = [];

    // 暂时使用前缀标记各类书籍，懒得处理嵌套逻辑
    protected static $bookMapTags = ['【7】', '【8】', '【9】'];

    /**
     * @throws AppException
     */
    public static function loadUseMaps($useMapsProp = 'useMaps')
    {
        if (self::$$useMapsProp) {
            return self::$$useMapsProp;
        }

        $useMapsConfigIndex = TextFixer::getInstance()->getUseMapsConfigIndex();
        $useMapsConfig = Config::getMap('useMapsConfig');
        if (!isset($useMapsConfig[$useMapsConfigIndex])) {
            throw new AppException('校正词库索引选择有误，无法找到对应词库');
        }

        $useMaps = $useMapsConfig[$useMapsConfigIndex][$useMapsProp];
        if (array_intersect(
            ['normalMap', 'extraMap', 'oldStyleMap', 'strictMap', 'dddMap'],
            $useMaps
        )) {
            // postFixMap 主要就是用来修复一些正则产生的误改，最好放到最后一个，优先级最高
            // 不过例如 oldStyleMap 这种，为了防止单独写的正则被自定义词库里的 regexMap 覆盖
            // 需要在 useMap 设置的开头额外先搭上一个 punctuationMap，保证自定义词库先被 include
            // 逻辑略坑，待优化
            $useMaps[] = 'postFixMap';
        }

        $files = [];
        $fileMapping = Config::getMap('fileMapping');
        foreach ($useMaps as $map) {
            if (isset($fileMapping[$map])) {
                $files[] = $fileMapping[$map];
            }
        }
        $files = array_values(array_unique($files));

        $regexMap        = [];
        $extraRegexMap   = [];
        $strictRegexMap  = [];
        $excludedWords   = [];
        $excludedRegexes = [];
        foreach ($files as $file) {
            $mapFilepath = self::getMapFilepath($file);
            file_exists($mapFilepath) && include($mapFilepath);
        }

        self::$excludedWords   = $excludedWords;
        self::$excludedRegexes = $excludedRegexes;

        if (!self::$regexMap) {
            // 使用 extraMap 时更改为 extraRegexMap
            if (TextFixer::getInstance()->isUsingExtraMap()) {
                $regexMap = $extraRegexMap;
            }

            self::$regexMap = $regexMap;
        }

        $vars = get_defined_vars();
        if (TextFixer::getInstance()->getUseStrictMode()) {
            // 切换严格模式使用的词条和正则，本来同样应该写到 $useMapsConfig 里的
            // 这么弄是想突出这个单独的步骤，后面再考虑是否统一处理
            self::$$useMapsProp = [];
            self::$$useMapsProp['normalMap'] = $vars['strictMap'];
            self::$$useMapsProp['postFixMap'] = $vars['postFixMap'];
            self::$regexMap = $strictRegexMap;
        } else {
            foreach ($vars as $key => $var) {
                if (
                    in_array($key, $useMaps)
                    && str_contains($key, 'Map')
                    && $key != 'regexMap'
                ) {
                    self::$$useMapsProp[$key] = $var;
                }
            }
        }

        return self::$$useMapsProp;
    }

    /**
     * @throws AppException
     */
    public static function loadBakUseMaps()
    {
        return self::loadUseMaps('bakUseMaps');
    }

    public static function loadRegexMap()
    {
        return self::$regexMap;
    }

    /**
     * 根据书籍专有词库的信息，移除一些不需要执行或不重复执行的规则
     * mark 格式如：{移除引号间的逗号} {水气->水汽} {re:即->既} 等，可以通过 mark 名称清楚地看出改了什么
     * 每个 mark 最好是唯一的、不重复的
     * 不过如果多个词条其实解决的是同一个问题，则可以给这些词条设置同样的 mark
     *
     * @param array $map
     * @param string $bookName
     * @param string $excludedRuleName
     * @return void
     */
    public static function removeExcludedRules(&$map, $bookName, $excludedRuleName = 'excludedWords')
    {
        $excludedRules = self::$$excludedRuleName;
        $bookMap = self::$bookMaps[$bookName] ?? [];
        if (!$excludedRules && !$bookMap) {
            return;
        }

        // 若单独的书籍文件有设置此项，则与词库文件中的合并
        if (isset($bookMap[$excludedRuleName])) {
            $excludedRules = array_merge($excludedRules, $bookMap[$excludedRuleName]);
            $excludedRules = array_values(array_unique($excludedRules));
        }

        if (!$excludedRules) {
            return;
        }

        $excludedSet = array_flip($excludedRules);

        $map = array_filter(
            $map,
            function ($var) use ($excludedSet) {
                // 保留一个元素，当且仅当：
                // 1. 它没有 'mark' 键
                // 2. 或者，它的 'mark' 键的值不存在于排除集合中
                return !isset($var['mark']) || !isset($excludedSet[$var['mark']]);
            }
        );

        $map = array_values($map);
    }

    public static function removeExcludedRegexes(&$regexMap, $bookName)
    {
        self::removeExcludedRules($regexMap, $bookName, 'excludedRegexes');
    }

    public static function getMapFilepath($mapFilename)
    {
        return SCRIPT_DIR . "/maps/{$mapFilename}";
    }

    /**
     * @throws AppException
     */
    public static function loadBookMaps($bookFiles)
    {
        $result = [];
        foreach ($bookFiles as $bookFile) {
            $bookFile = Util::getFilename($bookFile, true);
            $bookMapContent = '';
            $bookMap = [];
            if (is_dir(self::getMapFilepath('书籍专有替换词库'))) {
                // 查找“书籍专有替换词库”目录内的单独文件
                $bookMapFile = self::getBookMapFileWithTags($bookFile);
                $bookMapFile && $bookMapContent = include($bookMapFile);
                if (is_array($bookMapContent) && isset($bookMapContent['bookNotes'])) {
                    $bookMap = $bookMapContent['bookNotes'];
                    // 这两个属性为了兼容之前的格式先硬加上去……
                    $bookMap['excludedWords'] = $bookMapContent['excludedWords'] ?? [];
                    $bookMap['excludedRegexes'] = $bookMapContent['excludedRegexes'] ?? [];
                }
                $bookMap && self::$bookMaps[$bookFile] = $bookMap;
            }

            $bookMap && $result = array_merge_recursive($result, $bookMap);
        }

        $result && $result = self::flattenMaps($result);

        return $result;
    }

    public static function getBookMapFileWithTags($bookFile)
    {
        $bookMapFile = self::getMapFilepath("书籍专有替换词库/{$bookFile}.php");
        if (file_exists($bookMapFile)) {
            return $bookMapFile;
        }

        foreach (self::$bookMapTags as $tag) {
            $bookMapFile = self::getMapFilepath("书籍专有替换词库/{$tag}{$bookFile}.php");
            if (file_exists($bookMapFile)) {
                return $bookMapFile;
            }
        }

        return "";
    }

    /**
     * @throws AppException
     */
    public static function loadPostFixMap()
    {
        if (self::$postFixMap) {
            return self::$postFixMap;
        }

        $useMaps = self::loadUseMaps();
        if (!isset($useMaps['postFixMap']) || !$useMaps['postFixMap']) {
            return [];
        }

        $postFixMap = $useMaps['postFixMap'];
        self::$postFixMap = Map::flattenMaps($postFixMap);

        return self::$postFixMap;
    }

    public static function resetPostFixMap()
    {
        self::$postFixMap = [];
    }

    /**
     * 展开词条
     *
     * @param array $maps 可为单个 map 数组，或含有多个 map 的二维数组
     * @param bool $sortByLen 是否按照词条的长度排序
     * @return array
     * @throws AppException
     */
    public static function flattenMaps(array $maps, bool $sortByLen = true): array
    {
        if (!$maps) {
            throw new AppException('校对表为空');
        }

        // 自动包装
        isset($maps[0]['before']) && $maps = [$maps];

        $ret = [];
        foreach ($maps as $map) {
            foreach ($map as $word) {
                foreach (self::flattenWord($word) as $elem) {
                    $ret[] = $elem;
                }
            }
        }

        // 对 replaceHolder 做进一步展开操作
        // TODO: 此操作效率不高，后续如果词条数量庞大，应考虑增加缓存（序列化？）
        self::processReplaceHolder($ret);

        if ($sortByLen && TextFixer::shouldReplaceByGo()) {
            // 用 go 替换时为了和常规替换的词条设置方式保持一致，改成后面设置的词条优先级更高
            // 若用 php 替换，自带的 strtr 本身就是后面的词条优先级更高，无需逆序
            $ret = array_reverse($ret);

            // 保证较长词条先被匹配
            // 注意这个排序有点慢，若用 php 替换，strtr 无需按长度排序也可以保证替换逻辑正常
            usort($ret, fn($a, $b) => strlen($b['before']) <=> strlen($a['before']));
        }

        // 移除一些特定规则
        // 若自定义词库文件中有设置排除项则优先使用，否则使用单独的书籍词库文件中的
        if (defined('SCRIPT_DIR')) { // 单独调用时不报错
            self::removeExcludedRules($ret, TextFixer::getInstance()->getBookName());
        }

        return $ret;
    }

    protected static function flattenWord(array|string $word): array
    {
        if (!self::isValidWord($word)) {
            return [];
        }

        if (is_array($word['after'])) {
            return self::handleWordWithAfterArr($word);
        } else if (is_array($word['before'])) {
            return self::handleWordWithBeforeArr($word);
        } else {
            return self::handleWordWithNoArr($word);
        }
    }

    protected static function isValidWord(array|string $word): bool
    {
        if (!isset($word['before']) || !isset($word['after'])) {
            return false;
        }

        if (
            (!$word['before']  && $word['before'] !== "0")
            || (!$word['after']  && $word['after'] !== "0")
        ) {
            return false;
        }

        return true;
    }

    protected static function handleWordWithAfterArr(array $word): array
    {
        if (!is_array($word['before'])) {
            var_dump($word);
            throw new AppException("after 为数组时，before 必须也为数组");
        }

        if (count($word['after']) != count($word['before'])) {
            var_dump($word);
            throw new AppException("after 为数组时，与 before 的数量必须相等");
        }

        $ret = [];
        foreach ($word['after'] as $k => $after) {
            if (!$after && $after !== "0") {
                continue;
            }

            $innerBefore = $word['before'][$k];
            $elem = self::createWord($innerBefore, $after, $word);
            $ret[] = $elem; // 直接追加元素
        }

        return $ret;
    }

    protected static function handleWordWithBeforeArr(array $word): array
    {
        $ret = [];
        foreach ($word['before'] as $before) {
            if (!$before) {
                continue;
            }

            $elem = self::createWord($before, $word['after'], $word);
            $ret[] = $elem; // 直接追加元素
        }

        return $ret;
    }

    protected static function handleWordWithNoArr(array $word): array
    {
        $before = $word['before'];
        $after = $word['after'];

        return [self::createWord($before, $after, $word)];
    }

    protected static function createWord($before, $after, array $word): array
    {
        $elem = [
            'before'        => $before,
            'after'         => $after,
            'replaceHolder' => $word['replaceHolder'] ?? [],
        ];
        if (isset($word['mark'])) {
            $elem['mark'] = $word['mark'];
        }

        return $elem;
    }

    /**
     * @throws AppException
     */
    protected static function processReplaceHolder(&$words)
    {
        $ret = [];
        foreach ($words as $word) {
            if (!isset($word['replaceHolder']) || !$word['replaceHolder']) {
                $ret[] = $word;
                continue;
            }

            $holderMark = '@';
            $holderCount = mb_substr_count($word['before'], $holderMark);
            if ($holderCount !== count($word['replaceHolder'])) {
                throw new AppException("{$word['after']} 的 replaceHolder 设置有误，与字符串中的占位符数量不一致");
            }

            // 预分割字符串
            $word['beforeParts'] = explode($holderMark, $word['before']);
            $word['afterParts']  = explode($holderMark, $word['after']);

            $expandedWords = self::expandWordsWithReplaceHolder($word);
            $ret = array_merge($ret, $expandedWords);
        }

        $words = $ret;
    }

    protected static function expandWordsWithReplaceHolder($word)
    {
        $combinations = self::generateCombinations($word['replaceHolder']);
        $resultArr = [];

        foreach ($combinations as $combination) {
            // 通过预分割的数组直接拼接字符串
            $resultBefore = $word['beforeParts'][0];
            $resultAfter  = $word['afterParts'][0];

            $combinationLen = count($combination);
            for ($i = 0; $i < $combinationLen; $i++) {
                $resultBefore .= $combination[$i] . $word['beforeParts'][$i + 1];
                $resultAfter  .= $combination[$i] . $word['afterParts'][$i + 1];
            }

            $resultWord = [
                'before' => $resultBefore,
                'after'  => $resultAfter,
            ];
            if (isset($word['mark'])) {
                $resultWord['mark'] = $word['mark'];
            }
            $resultArr[] = $resultWord;
        }

        return $resultArr;
    }

    protected static function generateCombinations($holderLines)
    {
        $result = [[]];
        foreach ($holderLines as $holderLine) {
            $temp = [];
            foreach ($result as $product) {
                foreach ($holderLine as $value) {
                    $temp[] = array_merge($product, [$value]);
                }
            }
            $result = $temp;
        }

        return $result;
    }

    public static function getMapConfigProp($prop)
    {
        $configIndex = TextFixer::getInstance()->getUseMapsConfigIndex();

        return Config::getMap('useMapsConfig')[$configIndex][$prop] ?? false;
    }

    /**
     * 只用某些替换表的情况下不进行正则替换
     *
     * @return bool
     */
    public static function getEnableRegexFix()
    {
        return self::getMapConfigProp('enableRegexFix');
    }

    /**
     * 只用某些替换表的情况下只替换一次
     *
     * @return bool
     */
    public static function doSingleReplace()
    {
        return self::getMapConfigProp('singleReplace');
    }

    public static function resetAll()
    {
        self::$useMaps    = [];
        self::$bakUseMaps = [];
        self::$regexMap   = [];
        self::$bookMaps   = [];
        self::$postFixMap = [];
    }
}
