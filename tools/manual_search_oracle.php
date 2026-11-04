<?php
/**
 * 手动检索规则集 · PHP 真值生成器（oracle）
 * =====================================================================
 * 用途：给 `tests/test_e3_manual_rules.py` 提供**原版 PHP 行为**的冻结真值。
 *
 * 为什么需要它：「同一本书命中数与人工抽查一致」「回调 3 条等价行为验证」
 * 这两条判据，靠 Python 自己跟自己比是证明不了的——必须有一个不依赖 Python
 * 实现的独立真值。这里用 PHP 直接跑**原版规则表与原生闭包**，产出的数字冻结
 * 进 `tests/fixtures/manual_search_oracle.json`，测试再拿 Python 结果去比。
 *
 * 它读的是**原版 FixText 源码目录**（`--php-src`），不是导出的 rules.json。
 * 这样一次比较同时验证两件事：
 *   1. rules.json 的导出（含 {$puncts} / {$dePrefixPattern} 展开）没走样；
 *   2. Python 侧 3 条回调的等价实现与 PHP 原生闭包行为一致。
 *
 * 运行示例（需要 php CLI 与原版源码）：
 *   php tools/manual_search_oracle.php \
 *       --php-src=/path/to/FixText --mode=count --book=tests/samples/a_utf8_lf.txt
 *   php tools/manual_search_oracle.php \
 *       --php-src=/path/to/FixText --mode=callback \
 *       --text=tests/fixtures/manual_search_callback_corpus.txt
 *
 * 输出：单个 JSON（stdout）。逐条失败不静默——`preg_match_all` 返回 false 时
 * 该条记 `err`，让调用方看得见。
 */

namespace App\Util {
    class Util
    {
        public static function e(string $s): string { return $s; }
    }
}

namespace App\Service {
    class PatternFileLoader
    {
        /** 原版在方法作用域 include 词库文件，`{$puncts}` 等变量才能展开。 */
        private static function vars(string $srcDir): array
        {
            $puncts = '';
            $dePrefixPattern = '';
            include $srcDir . '/src/maps/1.自定义词库.php';
            return ['puncts' => $puncts, 'dePrefixPattern' => $dePrefixPattern];
        }
        public static function loadPuncts(): string
        {
            return self::vars(self::$srcDir)['puncts'];
        }
        public static function loadDePrefixPattern(): string
        {
            return self::vars(self::$srcDir)['dePrefixPattern'];
        }
        public static string $srcDir = '';
    }
}

namespace {

    $opt = [];
    foreach (array_slice($argv, 1) as $a) {
        if (preg_match('/^--([a-z-]+)=(.*)$/s', $a, $m)) {
            $opt[$m[1]] = $m[2];
        }
    }
    $srcDir = rtrim($opt['php-src'] ?? '', '/');
    $mode   = $opt['mode'] ?? 'count';
    if ($srcDir === '' || !is_dir($srcDir)) {
        fwrite(STDERR, "--php-src 必须是原版 FixText 源码目录（当前：" . $srcDir . "）\n");
        exit(2);
    }
    \App\Service\PatternFileLoader::$srcDir = $srcDir;

    // 规则表自身会调 PatternFileLoader，因此加载顺序必须晚于上面那个桩类。
    $patterns = include $srcDir . '/src/maps/手动检索规则表.php';

    $rules = [];
    foreach ($patterns as $r) {
        if (isset($r['search'])) { $rules[] = $r; }
    }

    $varsLen = [
        'puncts'    => strlen(\App\Service\PatternFileLoader::loadPuncts()),
        'de_prefix' => strlen(\App\Service\PatternFileLoader::loadDePrefixPattern()),
    ];

    $out = [
        'mode'     => $mode,
        'php'      => PHP_VERSION,
        'vars_len' => $varsLen,
        'rules'    => count($rules),
    ];

    if ($mode === 'count') {
        $book = $opt['book'] ?? '';
        if ($book === '' || !is_readable($book)) {
            fwrite(STDERR, "--book 不可读：" . $book . "\n");
            exit(2);
        }
        $content = file_get_contents($book);        // 与 file_get_contents 一次读全书的原版口径一致
        $items = [];
        foreach ($rules as $i => $r) {
            $re = '/' . $r['search'] . '/umx';      // 原版默认修饰符
            $n  = @preg_match_all($re, $content, $m, PREG_PATTERN_ORDER);
            if ($n === false) {
                $items[] = ['i' => $i, 'mark' => $r['mark'], 'count' => null,
                            'err' => preg_last_error_msg()];
                continue;
            }
            $items[] = ['i' => $i, 'mark' => $r['mark'], 'count' => $n];
        }
        $out['book']       = basename($book);
        $out['bytes']      = filesize($book);
        $out['text_chars'] = mb_strlen($content, 'UTF-8');
        $out['items']      = $items;
        $out['total']      = array_sum(array_map(fn($x) => (int)($x['count'] ?? 0), $items));
        $out['nonzero']    = count(array_filter($items, fn($x) => ($x['count'] ?? 0) > 0));
    } elseif ($mode === 'callback') {
        $textFile = $opt['text'] ?? '';
        if ($textFile === '' || !is_readable($textFile)) {
            fwrite(STDERR, "--text 不可读：" . $textFile . "\n");
            exit(2);
        }
        $content = file_get_contents($textFile);
        $cases = [];
        foreach ($rules as $i => $r) {
            $replace = $r['replace'] ?? null;
            if (!($replace instanceof \Closure)) { continue; }   // 只跑回调规则
            $re = '/' . $r['search'] . '/umx';
            $matched = @preg_match_all($re, $content, $m, PREG_PATTERN_ORDER);
            if ($matched === false) {
                $cases[] = ['i' => $i, 'mark' => $r['mark'], 'matched' => null,
                            'err' => preg_last_error_msg(), 'result' => null];
                continue;
            }
            $result = @preg_replace_callback($re, $replace, $content);
            $cases[] = [
                'i'           => $i,
                'mark'        => $r['mark'],
                'matched'     => $matched,
                'sample'      => array_slice($m[0], 0, 30),     // 匹配到的原文片段
                'result'      => $result,
                'result_sha1' => $result === null ? null : sha1($result),
            ];
        }
        $out['text']       = basename($textFile);
        $out['bytes']      = filesize($textFile);
        $out['text_chars'] = mb_strlen($content, 'UTF-8');
        $out['cases']      = $cases;
    } else {
        fwrite(STDERR, "未知 --mode（count | callback）\n");
        exit(2);
    }

    echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
}
