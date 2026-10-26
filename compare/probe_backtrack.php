<?php
// 探针：验证 calibre 模式在大文本上的 PCRE 回溯上限行为
$src = $argv[1];
$content = file_get_contents($src);
// 复刻 NoteParser::normalizeContent 的关键步骤
$content = str_replace("\r\n", "\n", $content);
$content = $content . "\n<EOF>";
$patterns = require $argv[2] . '/config/general.php';
$pats = $patterns['noteMatchPatterns'];
$calibre = $pats['calibre'];
printf("backtrack_limit=%s\n", ini_get('pcre.backtrack_limit'));
$n = @preg_match_all("/{$calibre}/ums", $content, $m, PREG_SET_ORDER);
printf("calibre preg_match_all return=%s last_error=%s\n", var_export($n, true), preg_last_error_msg());
if ($n) { printf("match rows=%d\n", count($m)); printf("group1_len=%d\n", strlen($m[0][1])); }
