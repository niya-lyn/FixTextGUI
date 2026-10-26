<?php
/**
 * T0.4 回归基线集 · 上游一致性验证（可选深度验证）
 *
 * 用途：证明本基线集的两个关键成分与「上游真实代码」逐字节一致：
 *   A. 规则集来源：用上游真实的 `App\Service\Map::flattenMaps`（含 Go 语义的
 *      array_reverse + 按字节长度降序稳定排序）对「全量词库口径」的合并结果做展开，
 *      得到 before/after 数组，与包内 rules/before.json、rules/after.json 比对 sha256。
 *   B. PHP 后端语义：用反射调用上游真实的 `App\Service\TextFixer::replaceByPHP`
 *      （$shouldReverse=true，即 Go 降级路径）对语料样本执行 count=2 替换，
 *      与包内 expected/php/<样本> 逐字节比对。
 *
 * 前置：需要上游 FixText 源码包（云盘 projects/fix_text/FixText.zip 解压后的 src 目录）。
 * 本脚本只读上游源码，不做任何修改。
 *
 * 用法：
 *   php verify_upstream_equivalence.php <上游src目录> <基线baseline目录> [语料样本文件名]
 * 示例：
 *   php verify_upstream_equivalence.php /path/FixText/src ./baseline pg27166_呐喊.txt
 */

error_reporting(E_ALL & ~E_DEPRECATED & ~E_WARNING);
$srcDir   = rtrim($argv[1] ?? '', '/');
$baseDir  = rtrim($argv[2] ?? '', '/');
$sample   = $argv[3] ?? 'pg27166_呐喊.txt';

if (!$srcDir || !is_dir($srcDir) || !$baseDir || !is_dir($baseDir)) {
    fwrite(STDERR, "用法: php verify_upstream_equivalence.php <上游src目录> <baseline目录> [样本文件名]\n");
    exit(1);
}

// ---- 引导上游运行时常量（照抄 src/scripts/autoload.php 的常量集，仅指向本地路径）----
$tmp = sys_get_temp_dir() . '/fixtext_t04_verify';
@mkdir($tmp, 0755, true);
define("SCRIPT_DIR", $srcDir);
define("BOOK_DIR", "$tmp/books");
define("BOOK_BAK_DIR", "$tmp/booksBak");
define("BOOK_FIX_DIR", "$tmp/booksFix");
define("EPUB_MERGE_LOG_DIR", "$tmp/logs/merge");
define("EPUB_LIST_LOG", "$tmp/logs/epub_list.log");
define("REPORT_DIR", "$tmp/logs/report");
const RECURSIVE_FIX = true;
const REPACK_AFTER_FIX = false;
const EXCLUDE_DIRS = [];
define("TEMP_MAP_FILE", SCRIPT_DIR . "/maps/5.临时校对表.php");
const REPLACE_BY_GO = true; // 生产默认（src/main.php:45），flattenMaps 走 Go 语义排序
define("GO_REPLACE_CMD_FILE", SCRIPT_DIR . "/tools/replace_by_go.exe");
define("TXT_REPLACE_BEFORE", $tmp . "/TXT_REPLACE_BEFORE.txt");
define("TXT_REPLACE_AFTER", $tmp . "/TXT_REPLACE_AFTER.txt");
const TOKENIZE_CONTENT = false;
define("GOJIEBA_CMD_FILE", SCRIPT_DIR . "/tools/gojieba.exe");
const GOJIEBA_DICT = SCRIPT_DIR . "/tools/gojieba_dict.txt";
ini_set("memory_limit", "4096M");
mb_internal_encoding("UTF-8");
require_once(SCRIPT_DIR . "/vendor/autoload.php");

// ---- 全量词库口径：与包内 rules/rules_meta.json 的 per_var 顺序一致 ----
$WORD_VARS = [
    ['1.自定义词库.php', 'punctuationMap'],
    ['1.自定义词库.php', 'preprocessMap'],
    ['1.自定义词库.php', 'extraPreprocessMap'],
    ['1.自定义词库.php', 'normalMap'],
    ['1.自定义词库.php', 'extraMap'],
    ['1.自定义词库.php', 'strictMap'],
    ['1.自定义词库.php', 'postFixMap'],
    ['1.自定义词库【旧式、通假写法】.php', 'oldStyleMap'],
    ['2.繁转简词库.php', 't2sMap'],
    ['2.繁转简词库.php', 't2sRadicalMap'],
    ['2.繁转简词库.php', 'radicalsSupplementMap'],
    ['3.txtFormat 词库.php', 'txtFormatMap'],
    ['4.的地得词库.php', 'dddMap'],
    ['4.的地得词库.php', 'dei2deMap'],
    ['4.的地得词库.php', 'accurateDddMap'],
    ['5.临时校对表.php', 'tempMap'],
    ['7.生僻字词库.php', 'shengpiziMap'],
    ['7.生僻字词库【扩展区】.php', 'cjkExtMap'],
    ['7.生僻字词库【扩展区】.php', 'cjkRecoverMap'],
];

$fail = 0;

// ============ A. 规则集来源 ============
echo "== A. 规则集：上游 Map::flattenMaps 产出 vs 包内 rules/*.json ==\n";
$merged = [];
foreach ($WORD_VARS as [$file, $var]) {
    $path = SCRIPT_DIR . "/maps/{$file}";
    if (!is_file($path)) {
        fwrite(STDERR, "缺少词库文件: $path\n");
        exit(1);
    }
    // include 并捕获目标变量（与上游 Map::loadUseMaps 的 include 语义一致）
    (function () use ($path, $var, &$merged) {
        $result = include $path; // phpcs:ignore
        $val = ${$var} ?? null;
        if (is_array($val)) {
            $merged = array_merge($merged, $val);
        }
    })();
}

$tf = App\Service\TextFixer::getInstance(true);
$sorted = App\Service\Map::flattenMaps($merged);
$upstreamBefore = array_column($sorted, 'before');
$upstreamAfter  = array_column($sorted, 'after');
echo "上游 flatten 规则数: " . count($upstreamBefore) . "\n";

$pkgBefore = json_decode(file_get_contents("{$baseDir}/rules/before.json"), true);
$pkgAfter  = json_decode(file_get_contents("{$baseDir}/rules/after.json"), true);
echo "包内规则数: " . count($pkgBefore) . "\n";

$same = ($upstreamBefore === $pkgBefore) && ($upstreamAfter === $pkgAfter);
echo "A1 before 数组逐元素一致: " . ($upstreamBefore === $pkgBefore ? "是" : "否") . "\n";
echo "A2 after  数组逐元素一致: " . ($upstreamAfter  === $pkgAfter  ? "是" : "否") . "\n";
echo "A  判定: " . ($same ? "PASS" : "FAIL") . "\n";
if (!$same) {
    $fail++;
    // 定位首个差异
    foreach ($upstreamBefore as $i => $b) {
        if (!isset($pkgBefore[$i]) || $pkgBefore[$i] !== $b) {
            echo "   首个差异下标 $i: 上游[{$b}] 包内[" . ($pkgBefore[$i] ?? 'null') . "]\n";
            break;
        }
    }
}

// ============ B. PHP 后端语义 ============
echo "== B. PHP 后端：上游 TextFixer::replaceByPHP（反射） vs expected/php ==\n";
$corpusFile = "{$baseDir}/corpus/{$sample}";
if (!is_file($corpusFile)) {
    fwrite(STDERR, "语料样本不存在: $corpusFile\n");
    exit(1);
}
$content = file_get_contents($corpusFile);
$m = new ReflectionMethod(App\Service\TextFixer::class, 'replaceByPHP');
// 注：PHP 8.1+ 对非 public 方法反射调用无需 setAccessible
$m->invokeArgs($tf, [&$content, $upstreamBefore, $upstreamAfter, 2, true]);

$pkgPhpOut = file_get_contents("{$baseDir}/expected/php/{$sample}");
$pkgGoOut  = file_get_contents("{$baseDir}/expected/go/{$sample}");
$bPhp = ($content === $pkgPhpOut);
$bGo  = ($content === $pkgGoOut);
echo "B1 上游 replaceByPHP 输出 == 包内 expected/php: " . ($bPhp ? "是" : "否") . "\n";
echo "B2 上游 replaceByPHP 输出 == 包内 expected/go : " . ($bGo  ? "是" : "否") . "\n";
echo "B  判定: " . (($bPhp && $bGo) ? "PASS" : "FAIL") . "\n";
if (!$bPhp || !$bGo) {
    $fail++;
    echo "   字节数: 上游=" . strlen($content) . " php=" . strlen($pkgPhpOut) . " go=" . strlen($pkgGoOut) . "\n";
}

// ============ C. PHP 直连配置（REPLACE_BY_GO=false） ============
// 该配置下 Map::flattenMaps 不逆序、不按长度排序（sortByLen=false），
// replaceByPHP 以 $shouldReverse=false 直接 array_combine + strtr。
// 此处以同一套上游代码重放该配置，验证其输出同样与 Go 输出逐字节一致。
echo "== C. PHP 直连配置（REPLACE_BY_GO=false） vs expected/go ==\n";
$flatC = App\Service\Map::flattenMaps($merged, false);
$beforeC = array_column($flatC, 'before');
$afterC  = array_column($flatC, 'after');
$mapC = array_combine($beforeC, $afterC);
$sampleFiles = array_slice($argv, 4);
if (!$sampleFiles) {
    $sampleFiles = ['pg24264_紅樓夢.txt', 'novel_guimie_full.txt', 'pg27166_呐喊.txt'];
}
$cFail = 0;
foreach ($sampleFiles as $sf) {
    $f = "{$baseDir}/corpus/{$sf}";
    if (!is_file($f)) { echo "  [跳过] 样本不存在: {$sf}\n"; continue; }
    $c = file_get_contents($f);
    $c = strtr($c, $mapC);
    $c = strtr($c, $mapC);
    $g = file_get_contents("{$baseDir}/expected/go/{$sf}");
    $ok = ($c === $g);
    echo "  [{$sf}] C 配置输出 == expected/go: " . ($ok ? "是" : "否") . "\n";
    if (!$ok) { $cFail++; $fail++; }
}
echo "C  判定: " . ($cFail === 0 ? "PASS" : "FAIL") . "\n";

echo "== 总结: " . ($fail === 0 ? "全部一致（PASS）" : "存在不一致（FAIL）") . " ==\n";
exit($fail === 0 ? 0 : 1);
