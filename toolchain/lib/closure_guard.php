<?php
/**
 * FixText T0.2 · PHP 闭包显式检测与报警（运行时层）
 *
 * 背景：PHP 的 json_encode() 对 Closure 对象静默降级为 {}，
 *       不返回错误、不抛异常。迁移到 JSON 时闭包会「无声丢失」，
 *       属于排期文档 3.5 门禁 (c) 明确禁止的静默降级。
 *
 * 本库提供两种检测：
 *   1) closure_scan_runtime()  运行时：递归遍历已加载的 PHP 变量，定位 Closure 实例；
 *   2) closure_scan_static()   静态：token_get_all 扫描 PHP 源码，定位匿名函数 / 箭头函数；
 *   3) closure_alarm()         报警：写 alarm log + 返回机器可读结论（阻断静默降级）。
 *
 * 报警语义：ALARM 级别。调用方必须把「含闭包的变量 / 文件」标记为不可导出，
 *           并在迁移清单里留痕，不得直接 json_encode 后当作正常数据。
 */

date_default_timezone_set('Asia/Shanghai');   // 报警时间戳与运行环境保持一致

const CLOSURE_ALARM_TAG = 'ALARM[PHP-CLOSURE]';

if (!function_exists('closure_scan_runtime')) {
    /**
     * 递归扫描运行时值中的 Closure 实例。
     *
     * @return array<int,array{path:string,type:string,file:string,line:int}>
     */
    function closure_scan_runtime($value, string $path = '$', int $depth = 0): array
    {
        if ($depth > 12) {
            return [];
        }
        $hits = [];
        if ($value instanceof Closure) {
            $r = new ReflectionFunction($value);
            $hits[] = [
                'path'     => $path,
                'type'     => 'Closure',
                'file'     => (string)$r->getFileName(),
                'line'     => (int)$r->getStartLine(),
                'arity'    => $r->getNumberOfParameters(),
            ];
            return $hits;
        }
        if (is_array($value)) {
            foreach ($value as $k => $v) {
                $hits = array_merge($hits, closure_scan_runtime($v, $path . '[' . $k . ']', $depth + 1));
            }
            return $hits;
        }
        if (is_object($value)) {
            foreach ((array)$value as $k => $v) {
                $hits = array_merge($hits, closure_scan_runtime($v, $path . '->' . $k, $depth + 1));
            }
            return $hits;
        }
        return $hits;
    }
}

if (!function_exists('closure_scan_static')) {
    /**
     * 静态扫描 PHP 源码文件中的匿名函数 (function (...) {}) 与箭头函数 (fn (...) =>)。
     * 只扫描「函数表达式」：T_FUNCTION 后紧跟 "("，或 T_FN。
     * 不扫描具名函数声明 / 方法声明。
     *
     * @return array<int,array{file:string,line:int,kind:string,snippet:string}>
     */
    function closure_scan_static(string $file): array
    {
        $code = @file_get_contents($file);
        if ($code === false) {
            return [];
        }
        $tokens = token_get_all($code);
        $hits = [];
        $n = count($tokens);
        for ($i = 0; $i < $n; $i++) {
            $t = $tokens[$i];
            if (!is_array($t)) {
                continue;
            }
            $kind = null;
            if ($t[0] === T_FUNCTION) {
                // 具名函数/方法：T_FUNCTION 之后是标识符
                $j = $i + 1;
                while ($j < $n && is_array($tokens[$j]) && in_array($tokens[$j][0], [T_WHITESPACE, T_COMMENT, T_DOC_COMMENT], true)) {
                    $j++;
                }
                $next = $tokens[$j] ?? null;
                $isNamed = is_array($next) && in_array($next[0], [T_STRING, T_STATIC], true);
                if (!$isNamed) {
                    $kind = 'anonymous_function';
                }
            } elseif ($t[0] === T_FN) {
                $kind = 'arrow_function';
            }
            if ($kind === null) {
                continue;
            }
            // 向前回溯判断是否处于方法体/类体内（对象上下文里的闭包也算，但闭包本身才是问题）
            $snippet = '';
            for ($k = $i; $k < min($n, $i + 40); $k++) {
                $piece = is_array($tokens[$k]) ? $tokens[$k][1] : $tokens[$k];
                $snippet .= $piece;
                if (strlen($snippet) > 200) {
                    break;
                }
            }
            $hits[] = [
                'file'    => $file,
                'line'    => (int)$t[2],
                'kind'    => $kind,
                'snippet' => trim(preg_replace('/\s+/u', ' ', $snippet)),
            ];
        }
        return $hits;
    }
}

if (!function_exists('closure_alarm')) {
    /**
     * 触发闭包报警并留痕。
     *
     * @param array  $findings 每条: {layer, source, path?, file?, line?, kind?, detail?}
     * @param string $alarmLog alarm 日志文件路径
     * @param string $scope    报警来源场景（如 export/flatten/static）
     * @return array{alarm:bool, count:int, log:string}
     */
    function closure_alarm(array $findings, string $alarmLog, string $scope): array
    {
        if (!$findings) {
            return ['alarm' => false, 'count' => 0, 'log' => $alarmLog];
        }
        $dir = dirname($alarmLog);
        if (!is_dir($dir)) {
            mkdir($dir, 0755, true);
        }
        $ts = date('Y-m-d H:i:s');
        $fh = fopen($alarmLog, 'a');
        $lines = [];
        $lines[] = "[$ts] " . CLOSURE_ALARM_TAG . " scope=$scope count=" . count($findings);
        foreach ($findings as $f) {
            $loc = $f['file'] ?? '-';
            $line = isset($f['line']) ? (int)$f['line'] : '-';
            $path = $f['path'] ?? '-';
            $kind = $f['kind'] ?? '-';
            $src  = $f['source'] ?? '-';
            $lines[] = sprintf(
                "  - layer=%s source=%s path=%s file=%s line=%s kind=%s",
                $f['layer'] ?? '-', $src, $path, $loc, $line, $kind
            );
            if (!empty($f['detail'])) {
                $lines[] = "      detail: " . str_replace("\n", ' ', (string)$f['detail']);
            }
        }
        $lines[] = "  action=标记为不可导出/需引擎侧重写，禁止静默 json_encode 降级";
        $lines[] = '';
        fwrite($fh, implode("\n", $lines) . "\n");
        fclose($fh);
        return ['alarm' => true, 'count' => count($findings), 'log' => $alarmLog];
    }
}

if (!function_exists('closure_encode_safe')) {
    /**
     * 安全编码：先扫描 Closure，命中则拒绝编码并返回错误（避免静默 {} 降级）。
     *
     * @return array{ok:bool, json:?string, closures:array, error:?string}
     */
    function closure_encode_safe($value): array
    {
        $closures = closure_scan_runtime($value);
        if ($closures) {
            return [
                'ok'       => false,
                'json'     => null,
                'closures' => $closures,
                'error'    => '含 ' . count($closures) . ' 处 Closure，json_encode 会静默降级为 {}，已拒绝导出',
            ];
        }
        $json = json_encode($value, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        if ($json === false) {
            return [
                'ok'       => false,
                'json'     => null,
                'closures' => [],
                'error'    => 'json_encode failed: ' . json_last_error_msg(),
            ];
        }
        return ['ok' => true, 'json' => $json, 'closures' => [], 'error' => null];
    }
}
