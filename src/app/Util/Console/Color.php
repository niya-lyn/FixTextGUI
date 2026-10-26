<?php

namespace App\Util\Console;

use Toolkit\Cli\Color as CliColor;

/**
 * 扩展颜色
 *
 * SGR 写法：https://blog.csdn.net/q1003675852/article/details/134999871
 *
 * 下面这几种值控制了输出样式：
 * 1-粗体 3-斜体 4-下划线（Windows 默认好像只能支持下划线）
 * 30-37 基本的几个前景色
 * 40-47 基本的几个背景色
 * 还有 90-97 100-107 这两类“bright”的基本前背景颜色，
 * php-console 用的 Color 类应该只处理了上述几种基本颜色。
 *
 * 如果使用 38;5 表示前景色，48;5 表示背景色，可支持更丰富的 256 色：
 * 38;5;n 表示特定前景色，48;5;n 表示特定背景色
 * 使用这种写法，如果前景背景要采用不同颜色，可输入 6 个值，如：
 * [38, 5, 200, 48, 5, 88]
 * 如果还要加下划线之类的效果，可以在前面再加标记，如：
 * [4, 38, 5, 200, 48, 5, 88]
 */
class Color extends CliColor
{
    public static function foreRed($text)
    {
        return self::red1((string)$text);
    }

    public static function foreYellow($text)
    {
        return self::yellow((string)$text);
    }

    public static function foreGreen($text)
    {
        return self::green((string)$text);
    }

    public static function foreBlue($text)
    {
        return self::note((string)$text);
    }

    public static function forePurple($text)
    {
        return self::render((string)$text, [38, 5, 200]);
    }

    public static function foreGray($text)
    {
        return self::render((string)$text, [38, 5, 248]);
    }

    public static function foreOrange($text)
    {
        return self::render((string)$text, [38, 5, 172]);
    }

    public static function foreWhite($text)
    {
        return self::white((string)$text);
    }

    public static function backRed($text)
    {
        return self::render(((string)$text), [38, 5, 15, 48, 5, 88]);
    }

    public static function backGreen($text)
    {
        return self::render(((string)$text), [38, 5, 0, 48, 5, 10]);
    }

    public static function backRedForePurple($text)
    {
        return self::render((string)$text, [38, 5, 200, 48, 5, 88]);
    }

    public static function backBlue($text)
    {
        return self::render(((string)$text), [38, 5, 15, 48, 5, 20]);
    }

    public static function backYellow($text)
    {
        return self::render((string)$text, [38, 5, 9, 48, 5, 226]);
    }

    public static function backPurple($text)
    {
        return self::render((string)$text, [38, 5, 15, 48, 5, 91]);
    }
}
