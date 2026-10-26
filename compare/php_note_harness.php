<?php
/**
 * T1.6 PHP 权威行为 harness：调用 FixText 真实 NoteParser，输出三个阶段的匹配结果 JSON。
 *   stage1: 正则提取后、品牌闭包处理前（raw）
 *   stage2: 品牌闭包处理后、cleanMatches 前
 *   stage3: cleanMatches 后（parseFileContent 最终返回值）
 * 用法: php php_note_harness.php <src_dir> <input_file> <output_json>
 * 无匹配时输出 {"ok":false,"__exception__":"未找到匹配的批注内容"}
 */
define("SCRIPT_DIR", $argv[1]);
require_once SCRIPT_DIR . "/vendor/autoload.php";

use App\Service\Note\NoteParser;
use App\Exception\AppException;

class ProbingParser extends NoteParser
{
    /** 返回 [normalize 后内容, 闭包处理后的 matches（无匹配时为 []）] */
    public function probe(string $content): array
    {
        $normalized = $this->normalizeContent($content);
        $matches = $this->extractMatches($normalized);
        return [$normalized, $matches];
    }

    /** raw 提取（不含品牌闭包处理），并返回命中的 brand */
    public function probeRaw(string $content): array
    {
        $normalized = $this->normalizeContent($content);
        foreach ($this->noteMatchPatterns as $brand => $pattern) {
            preg_match_all("/{$pattern}/ums", $normalized, $matches, PREG_SET_ORDER);
            if (!empty($matches)) {
                return [$brand, $matches];
            }
        }
        return ['', []];
    }
}

function simplify(array $matches): array
{
    $out = [];
    foreach ($matches as $m) {
        $row = [];
        foreach (array_values($m) as $v) {
            $row[] = $v;
        }
        $out[] = $row;
    }
    return $out;
}

$inputFile = $argv[2];
$outputFile = $argv[3];
$content = file_get_contents($inputFile);

$payload = [];
try {
    $p = new ProbingParser();
    [$brand, $raw] = $p->probeRaw($content);
    if (empty($raw)) {
        $payload = ["ok" => false, "__exception__" => "未找到匹配的批注内容"];
    } else {
        [, $afterProcessor] = $p->probe($content);
        $final = $p->parseFileContent($content);
        $payload = [
            "ok" => true,
            "brand" => $brand,
            "stage1_raw" => simplify($raw),
            "stage2_after_processor" => simplify($afterProcessor),
            "stage3_final" => simplify($final),
        ];
    }
} catch (AppException $e) {
    $payload = ["ok" => false, "__exception__" => $e->getMessage()];
}

file_put_contents($outputFile, json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES));
