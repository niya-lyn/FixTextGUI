#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动检索规则表 · 可再生导出器（V1.1-E3）

把原版 PHP FixText 的 ``src/maps/手动检索规则表.php`` 求值成一份**可直接被
Python 读的 JSON**：``data/manual_search/rules.json``。

为什么必须"求值"而不是"抄写"
----------------------------
原版规则表不是纯字面量数组，它有三个在**运行时**才定形的东西：

1. ``{$puncts}``——标点集合，定义在 ``1.自定义词库.php`` 第 89029 行，
   47 个字符（含 ``\\n`` 与 ``\\-`` 两个转义）；
2. ``{$dePrefixPattern}``——一条 6287 字符的「地」前置断言，跨多行缩进书写，
   靠 PCRE 的 ``x`` 修饰符忽略空白才成立；
3. 3 条 ``replace`` 是 **闭包**（回调），没有字符串可抄。

手工正则抄写这三处必然走形（本项目已实测：手工截取双引号串会把引号本身
带进表达式，正则语义直接错掉）。所以导出器**只做一件事**：调用本机 PHP
解释器 ``include`` 原文件，把 ``var_export`` 级别的事实收成 JSON。

零外网、零预置文本
------------------
导出器不接受"我已经抄好的规则表"作为输入——它要求 ``--php-src`` 指向原版
源码目录，缺文件就直接失败。这样 ``rules.json`` 任何时候都能从源码重生成，
产物可复现、可对账。

用法
----

    python tools/export_manual_rules.py --php-src /path/to/FixText/src

    # 只校验不写盘（CI / 交付前自检）
    python tools/export_manual_rules.py --php-src ... --check

    # 产物路径默认 <包根>/data/manual_search/rules.json
    python tools/export_manual_rules.py --php-src ... --out /tmp/rules.json

依赖：本机 ``php`` 可执行文件（PHP >= 8.0 的闭包语法）。原版是 PHP 项目，
其规则表的语义只有 PHP 自己能给准；这里的 PHP 只做**求值**，不跑业务逻辑。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: 原版规则表相对 ``src`` 的路径
RULES_REL = Path("maps") / "手动检索规则表.php"
#: 标点集合与「地」前置断言的来源文件
WORDS_REL = Path("maps") / "1.自定义词库.php"

#: 产物 schema 版本（改字段名 / 换语义时必须升版，读取侧会校验）
SCHEMA_VERSION = "1.0"

#: 原版 PHP 求值器。整段内联在这里，导出器不依赖"另一个脚本"。
PHP_DUMPER = r"""
<?php
namespace App\Util { class Util {} }
namespace App\Service {
  class PatternFileLoader {
    public static string $dePrefixPattern = '';
    public static string $puncts = '';
    public static string $srcDir = '';
    public static ?array $varsCache = null;

    /** include 在**当前方法作用域**内执行，词库文件里的 $puncts / $dePrefixPattern 直接可见。 */
    public static function loadVars(): array {
      if (self::$varsCache !== null) { return self::$varsCache; }
      $file = self::$srcDir . '/maps/1.自定义词库.php';
      include $file;
      self::$varsCache = ['puncts' => $puncts ?? '', 'dp' => $dePrefixPattern ?? ''];
      return self::$varsCache;
    }
    public static function loadPatterns(): array {
      return include self::$srcDir . '/maps/手动检索规则表.php';
    }
    public static function loadDePrefixPattern(): string { return self::loadVars()['dp']; }
    public static function loadPuncts(): string { return self::loadVars()['puncts']; }
  }
}
namespace {
  $src = $argv[1];
  \App\Service\PatternFileLoader::$srcDir = $src;

  $rulesPath = $src . '/maps/手动检索规则表.php';
  $srcText = file_get_contents($rulesPath);
  $lines = explode("\n", $srcText);

  // 每条规则 'search' 所在行（只算未注释的）
  $searchLines = [];
  foreach ($lines as $n => $ln) {
    if (preg_match('/^\s*\'search\'\s*=>/', $ln)) { $searchLines[] = $n + 1; }
  }
  // 被注释掉的规则行数（对齐 P1.1 的「另有 6 条注释」）
  $commented = 0;
  foreach ($lines as $ln) {
    if (preg_match('/^\s*\/\/\s*\'search\'\s*=>/', $ln)) { $commented++; }
  }

  $rules = \App\Service\PatternFileLoader::loadPatterns();
  $vars  = \App\Service\PatternFileLoader::loadVars();
  $out   = [];
  $si    = 0;

  foreach ($rules as $r) {
    $isCb = isset($r['replace']) && is_callable($r['replace']) && !is_string($r['replace']);
    $item = [
      'search'     => (string)($r['search'] ?? ''),
      'mark'       => $r['mark'] ?? null,
      'color'      => $r['color'] ?? null,
      'modifiers'  => $r['modifiers'] ?? null,
      'is_callback'=> $isCb,
      'replace'    => $isCb ? null : ($r['replace'] ?? ''),
    ];
    if ($isCb) {
      $rf = new \ReflectionFunction($r['replace']);
      $item['cb_start_line'] = $rf->getStartLine();
      $item['cb_end_line']   = $rf->getEndLine();
      $item['cb_source']     = implode("\n", array_slice(
        $lines, $rf->getStartLine() - 1, $rf->getEndLine() - $rf->getStartLine() + 1));
    }
    // 紧邻的说明注释：向上收集最多 3 行，跳过空的 / 纯代码注释
    $sl = $searchLines[$si] ?? null; $si++;
    $notes = [];
    if ($sl !== null) {
      for ($k = $sl - 2; $k >= 0 && count($notes) < 3; $k--) {
        $t = trim($lines[$k]);
        if ($t === '') { if ($notes) { break; } else { continue; } }
        if (preg_match('/^\[\s*$/', $t)) { continue; }
        if (str_starts_with($t, '//')) {
          $body = trim(substr($t, 2));
          if ($body === '' || str_contains($body, '=>') || str_contains($body, "'search'")) { continue; }
          array_unshift($notes, $body);
          continue;
        }
        break;
      }
    }
    $item['note'] = $notes ? implode(' ', $notes) : null;
    $item['extra_keys'] = array_values(array_diff(
      array_keys($r), ['search', 'replace', 'mark', 'color', 'modifiers']));
    $out[] = $item;
  }

  echo json_encode([
    'count'            => count($out),
    'commented_rules'  => $commented,
    'puncts'           => (string)($vars['puncts'] ?? ''),
    'de_prefix_len'    => strlen((string)($vars['dp'] ?? '')),
    'items'            => $out,
  ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
}
"""

class ExportError(RuntimeError):
    """导出失败（缺 PHP、缺源码、求值报错）。"""


@dataclass
class ExportResult:
    payload: dict[str, Any]
    source_sha256: str
    vars_sha256: str

    @property
    def count(self) -> int:
        return int(self.payload["count"])

    @property
    def callbacks(self) -> int:
        return sum(1 for it in self.payload["items"] if it["is_callback"])


def find_php(explicit: str | None = None) -> str:
    """定位 PHP 解释器：显式参数 > PATH。"""
    if explicit:
        return explicit
    found = shutil.which("php")
    if not found:
        raise ExportError(
            "找不到 php 可执行文件。原生规则表含 PHP 变量插值与闭包，"
            "只有 PHP 自己能给准；请安装 php，或用 --php 指定解释器路径。"
        )
    return found


def _run_php(php: str, script: str, *args: str, timeout: int = 120) -> str:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "dump.php"
        # `<?php` 必须是文件第一条语句——常量字符串带前导换行，先剥掉
        p.write_text(script.lstrip("\n"), encoding="utf-8")
        proc = subprocess.run(
            [php, "-d", "memory_limit=512M", str(p), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    if proc.returncode != 0:
        raise ExportError(f"PHP 求值失败（rc={proc.returncode}）：{proc.stderr.strip()[:800]}")
    out = proc.stdout.strip()
    if not out:
        raise ExportError(f"PHP 求值没有输出；stderr={proc.stderr.strip()[:400]}")
    return out


def export(php_src: Path, php: str | None = None) -> ExportResult:
    """从原版 PHP 源码导出规则集。``php_src`` 指向原版 ``src`` 目录。"""
    src = Path(php_src).expanduser().resolve()
    rules_path = src / RULES_REL
    words_path = src / WORDS_REL
    for need in (rules_path, words_path):
        if not need.is_file():
            raise ExportError(f"原版源码缺少文件：{need}")

    php_bin = find_php(php)

    # 不碰原版源码树：dumper 直接在方法作用域里 include 词库文件取两个变量，
    # 不生成任何临时 .php（上一版曾在源码目录落 _vars_only.php，失败时残留）。
    raw = _run_php(php_bin, PHP_DUMPER, str(src))

    try:
        dumped = json.loads(raw)
    except json.JSONDecodeError as exc:      # pragma: no cover - 防御
        raise ExportError(f"PHP 输出不是合法 JSON：{exc}") from exc

    if not dumped.get("items"):
        raise ExportError("PHP 求值结果为空——规则表没有被正确 include。")

    source_sha = hashlib.sha256(rules_path.read_bytes()).hexdigest()
    vars_sha = hashlib.sha256(words_path.read_bytes()).hexdigest()

    payload = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "origin": "原版 PHP FixText · src/maps/手动检索规则表.php",
            "rules_path": str(RULES_REL).replace("\\", "/"),
            "rules_sha256": source_sha,
            "vars_path": str(WORDS_REL).replace("\\", "/"),
            "vars_sha256": vars_sha,
            "puncts": dumped.get("puncts", ""),
            "de_prefix_len": dumped.get("de_prefix_len", 0),
        },
        "counts": {
            "rules": dumped["count"],
            "callbacks": sum(1 for it in dumped["items"] if it["is_callback"]),
            "commented_out": dumped.get("commented_rules", 0),
            "color_blue": sum(1 for it in dumped["items"] if it.get("color") == "Blue"),
            "with_note": sum(1 for it in dumped["items"] if it.get("note")),
        },
        "items": dumped["items"],
    }
    return ExportResult(payload=payload, source_sha256=source_sha, vars_sha256=vars_sha)


def default_out() -> Path:
    """默认产物路径：<包根>/data/manual_search/rules.json。"""
    try:
        from fixtext_paths import pkg_root          # noqa: PLC0415
        return pkg_root() / "data" / "manual_search" / "rules.json"
    except Exception:                                # pragma: no cover
        return Path(__file__).resolve().parent.parent / "data" / "manual_search" / "rules.json"


def write(payload: dict[str, Any], out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    out.write_text(text + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="从原版 PHP 源码导出手动检索规则集")
    ap.add_argument("--php-src", required=True, help="原版 FixText 的 src 目录")
    ap.add_argument("--php", default=None, help="php 可执行文件路径（默认取 PATH）")
    ap.add_argument("--out", default=None, help="产物路径（默认 data/manual_search/rules.json）")
    ap.add_argument("--check", action="store_true", help="只校验：不写盘，结论打到 stdout")
    args = ap.parse_args(argv)

    try:
        res = export(Path(args.php_src), args.php)
    except ExportError as exc:
        print(f"[导出失败] {exc}", file=sys.stderr)
        return 2

    out = Path(args.out) if args.out else default_out()
    if not args.check:
        write(res.payload, out)

    c = res.payload["counts"]
    print(json.dumps({
        "out": str(out),
        "written": not args.check,
        "rules": c["rules"],
        "callbacks": c["callbacks"],
        "commented_out": c["commented_out"],
        "color_blue": c["color_blue"],
        "with_note": c["with_note"],
        "puncts_len": len(res.payload["source"]["puncts"]),
        "de_prefix_len": res.payload["source"]["de_prefix_len"],
        "source_sha256": res.source_sha256[:16],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
