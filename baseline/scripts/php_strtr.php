<?php
/**
 * T0.4 回归基线集 · PHP 替换后端
 *
 * 复刻上游 FixText `TextFixer::replaceByPHP` 在「Go 降级」路径上的精确语义：
 *   1. 对 before/after 数组做 array_reverse（Go 降级时 $shouldReverse=true）
 *   2. array_combine 生成映射（重复键：后出现者覆盖 → 与 Go「先出现者生效」等价）
 *   3. strtr 执行 $count 轮（生产口径 count=2，见 TextFixer::doReplace）
 *   4. 结果原文件写回（与上游 replace_by_go 的行为一致）
 *
 * 与上游逐字节等价性验证见 scripts/verify_upstream_equivalence.php。
 *
 * 用法：
 *   php php_strtr.php <替换前.json> <替换后.json> <目标文件> <替换次数>
 * 输出（stdout，JSON）：in_bytes/out_bytes/耗时/峰值内存
 */

$beforeFile = $argv[1] ?? '';
$afterFile  = $argv[2] ?? '';
$target     = $argv[3] ?? '';
$count      = (int)($argv[4] ?? 0);

if (!$beforeFile || !$afterFile || !$target || $count <= 0) {
    fwrite(STDERR, "用法: php php_strtr.php <替换前.json> <替换后.json> <目标文件> <替换次数>\n");
    exit(1);
}

$t0 = microtime(true);
$b = json_decode(file_get_contents($beforeFile), true);
$a = json_decode(file_get_contents($afterFile), true);
if (!is_array($b) || !is_array($a) || count($b) !== count($a)) {
    fwrite(STDERR, "规则文件无效或数量不匹配\n");
    exit(1);
}
$tLoad = microtime(true) - $t0;

// —— 与上游 replaceByPHP($shouldReverse=true) 一致 ——
$b = array_reverse($b);
$a = array_reverse($a);
$map = array_combine($b, $a);
$tCombine = microtime(true) - $t0 - $tLoad;

$content = file_get_contents($target);
if ($content === false) {
    fwrite(STDERR, "目标文件读取失败: $target\n");
    exit(1);
}
$inBytes = strlen($content);

$t1 = microtime(true);
for ($i = 0; $i < $count; $i++) {
    $content = strtr($content, $map);
}
$tRepl = microtime(true) - $t1;

file_put_contents($target, $content);

echo json_encode([
    'file'       => $target,
    'in_bytes'   => $inBytes,
    'out_bytes'  => strlen($content),
    'rules'      => count($b),
    'map_size'   => count($map),
    'load_s'     => round($tLoad, 3),
    'combine_s'  => round($tCombine, 3),
    'replace_s'  => round($tRepl, 3),
    'peak_mem_m' => (int)(memory_get_peak_usage(true) / 1048576),
], JSON_UNESCAPED_UNICODE), PHP_EOL;
