<?php
// 对每个已导出 JSON：重新 include 原文件取原值 → json_decode 导出文件 → 严格 === 比对
error_reporting(E_ALL & ~E_DEPRECATED);
$mapsDir = $argv[1]; $expDir = $argv[2];
function loadFileVars(string $path): array { $result = include($path); $vars = get_defined_vars(); unset($vars['path'], $vars['result']); return [$result, $vars]; }
$files = [
 '1.自定义词库.php','1.自定义词库【旧式、通假写法】.php','2.繁转简词库.php','3.txtFormat 词库.php',
 '4.的地得词库.php','5.临时校对表.php','6.用户扩展词库.php','7.生僻字词库.php','7.生僻字词库【扩展区】.php',
 '书籍专有替换词库/天之下.php','书籍专有替换词库/铁鹤书.php','../config/map.php','../config/general.php',
];
$tot=0; $ok=0; $fail=0;
foreach ($files as $f) {
  [$result, $vars] = loadFileVars("$mapsDir/$f");
  $checks = [];
  foreach ($vars as $name=>$v) $checks[$name] = $v;
  if ($result !== false && $result !== 1 && $result !== null) $checks['__return__'] = $result;
  $safe = str_replace(['/', '\\', '【', '】'], '_', $f);
  foreach ($checks as $name=>$v) {
    $tot++;
    $jf = $name === '__return__' ? "$expDir/{$safe}.__return__.json" : "$expDir/{$safe}__{$name}.json";
    if (!file_exists($jf)) { echo "MISSING $f::$name\n"; $fail++; continue; }
    $decoded = json_decode(file_get_contents($jf), true);
    if ($decoded === $v) { $ok++; }
    else { echo "DIFF $f::$name\n"; $fail++; }
  }
}
echo "ROUNDTRIP total=$tot ok=$ok fail=$fail\n";
