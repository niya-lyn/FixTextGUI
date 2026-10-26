<?php
/**
 * FixText T0.2 · 步骤 5：PHP 闭包静态扫描（源码层）
 *
 * 用法: php 05_detect_closure_static.php <srcRoot> <outDir> [--alarm-log <path>]
 *
 * 扫描范围：
 *   主范围 = <srcRoot>/maps + <srcRoot>/config   （词库来源域，直接决定 JSON 词库完整性）
 *   全量   = <srcRoot> 递归所有 .php            （全仓库闭包清单，用于留痕与交接）
 *
 * 产出：
 *   <outDir>/closure_report.json   机器可读清单
 *   <alarmLog>                     报警留痕（ALARM[PHP-CLOSURE]）
 * 退出码：0 = 未发现闭包；3 = 发现闭包并已报警（供流水线判断，默认不阻断迁移，
 *         但含闭包的变量/文件一律不得静默导出）
 */

error_reporting(E_ALL & ~E_DEPRECATED);
ini_set('memory_limit', '-1');   // token_get_all 处理 6MB 级词库文件需要较大内存

$srcRoot = rtrim($argv[1] ?? '', '/');
$outDir  = rtrim($argv[2] ?? '', '/');
$alarmLog = $outDir . '/closure_alarm.log';
for ($i = 3; $i < count($argv); $i++) {
    if ($argv[$i] === '--alarm-log' && isset($argv[$i + 1])) {
        $alarmLog = $argv[++$i];
    }
}
if ($srcRoot === '' || !is_dir($srcRoot)) {
    fwrite(STDERR, "用法: php 05_detect_closure_static.php <srcRoot> <outDir> [--alarm-log <path>]\n");
    exit(2);
}
if (!is_dir($outDir)) {
    mkdir($outDir, 0755, true);
}

require_once __DIR__ . '/../lib/closure_guard.php';

function collectPhpFiles(string $dir): array
{
    if (!is_dir($dir)) {
        return [];
    }
    $out = [];
    $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir, FilesystemIterator::SKIP_DOTS));
    foreach ($it as $f) {
        /** @var SplFileInfo $f */
        if ($f->isFile() && strtolower($f->getExtension()) === 'php') {
            $out[] = $f->getPathname();
        }
    }
    sort($out);
    return $out;
}

function scanSet(array $files): array
{
    $hits = [];
    foreach ($files as $f) {
        foreach (closure_scan_static($f) as $h) {
            $h['file'] = str_replace('\\', '/', $h['file']);
            $hits[] = $h;
        }
    }
    return $hits;
}

// 主范围：词库来源域
$dictFiles = array_merge(
    collectPhpFiles($srcRoot . '/maps'),
    collectPhpFiles($srcRoot . '/config')
);
// 全量：整个 src
$allFiles = collectPhpFiles($srcRoot);

$dictHits = scanSet($dictFiles);
$allHits  = scanSet($allFiles);

$findings = [];
foreach ($dictHits as $h) {
    $findings[] = [
        'layer'  => 'static',
        'source' => 'src/maps+src/config',
        'file'   => $h['file'],
        'line'   => $h['line'],
        'kind'   => $h['kind'],
        'detail' => $h['snippet'],
    ];
}

$alarm = closure_alarm($findings, $alarmLog, 'static-scan');

$report = [
    'scanned_root'      => $srcRoot,
    'dict_scope_files'  => count($dictFiles),
    'all_scope_files'   => count($allFiles),
    'dict_scope_closures' => count($dictHits),
    'all_scope_closures'  => count($allHits),
    'alarm_raised'      => $alarm['alarm'],
    'alarm_log'         => $alarmLog,
    'dict_scope_hits'   => $dictHits,
    'all_scope_hits'    => $allHits,
];
file_put_contents(
    $outDir . '/closure_report.json',
    json_encode($report, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT)
);

echo "STATIC CLOSURE SCAN\n";
echo "  词库来源域文件数: {$report['dict_scope_files']}，闭包 {$report['dict_scope_closures']} 处\n";
echo "  全量 src 文件数:   {$report['all_scope_files']}，闭包 {$report['all_scope_closures']} 处\n";
foreach ($dictHits as $h) {
    echo "  [CLOSURE] {$h['file']}:{$h['line']} {$h['kind']}\n";
}
if ($alarm['alarm']) {
    echo "  ALARM 已触发，留痕: {$alarmLog}\n";
} else {
    echo "  未发现闭包\n";
}
exit($alarm['alarm'] ? 3 : 0);
