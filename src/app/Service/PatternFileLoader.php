<?php

namespace App\Service;

class PatternFileLoader
{
    public static array $patterns = [];
    public static string $dePrefixPattern = "";
    public static string $puncts = "";

    public static function loadPatterns(): array
    {
        self::$patterns = include(SCRIPT_DIR . "/maps/手动检索规则表.php");

        return self::$patterns;
    }

    public static function loadDePrefixPattern(): string
    {
        $dePrefixPattern = "";
        include(SCRIPT_DIR . "/maps/1.自定义词库.php");
        self::$dePrefixPattern = $dePrefixPattern;

        return self::$dePrefixPattern;
    }

    public static function loadPuncts(): string
    {
        $puncts = "";
        include(SCRIPT_DIR . "/maps/1.自定义词库.php");
        self::$puncts = $puncts;

        return self::$puncts;
    }
}
