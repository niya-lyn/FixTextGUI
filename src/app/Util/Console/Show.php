<?php

namespace App\Util\Console;

use App\Util\Util;
use Toolkit\Cli\Style;
use Inhere\Console\Util\Show as CliShow;

class Show extends CliShow
{
    protected static $opMessage = '';

    public static function writeWithNL(array|string $messages, bool $quit = false, array $opts = []): int
    {
        $ret = self::writeln($messages, $quit, $opts);
        echo PHP_EOL;

        return $ret;
    }

    public static function blockWithNL(mixed $messages, string $type = 'MESSAGE', string $style = Style::NORMAL, bool|int $quit = false): int
    {
        $ret = self::block($messages, $type, $style, $quit);
        echo PHP_EOL;

        return $ret;
    }

    public static function infoWithNL(mixed $messages, $quit = false)
    {
        $ret = self::info($messages, $quit);
        echo PHP_EOL;

        return $ret;
    }

    public static function noteWithNL(mixed $messages, $quit = false)
    {
        $ret = self::note($messages, $quit);
        echo PHP_EOL;

        return $ret;
    }

    public static function warnWithNL(mixed $messages, $quit = false)
    {
        $ret = self::warning($messages, $quit);
        echo PHP_EOL;

        return $ret;
    }

    public static function primaryWithNL(mixed $messages, $quit = false)
    {
        $ret = self::primary($messages, $quit);
        echo PHP_EOL;

        return $ret;
    }

    public static function successWithNL(string $message, $quit = false)
    {
        $ret = self::writeWithNL(
            Color::backGreen("[SUCCESS] {$message}"),
            $quit,
        );

        return $ret;
    }

    public static function opTitle($title)
    {
        return self::writeWithNL(Color::note("[操作提示]\n{$title}"));
    }

    public static function opStart($message = "", $color = "forePurple")
    {
        self::$opMessage = $message;

        self::block(Color::$color("【开始{$message}】"));
    }

    public static function opEnd($message = "", $color = "forePurple")
    {
        $message = $message ?: self::$opMessage;

        self::blockWithNL(Color::$color("【结束{$message}】"));

        self::$opMessage = "";
    }

    public static function showSelectedOpt(int|string $selection, string|array $options = "", $sleep = true): void
    {
        echo PHP_EOL;
        if ($options && is_string($options)) {
            $option = strip_tags($options);
            self::writeWithNL(
                "<info>[INFO] 已选择</info>"
                    . "<primary>【{$selection}】</primary>"
                    . "<info>，{$option}</info>"
            );
        } else if (is_array($options) && isset($options[$selection])) {
            $option = strip_tags($options[$selection]);
            self::writeWithNL(
                "<info>[INFO] 已选择</info>"
                    . "<primary>【{$selection}】</primary>"
                    . "<info>，{$option}</info>"
            );
        } else { // 无选项信息
            $selection = strip_tags($selection);
            self::writeWithNL(
                "<info>[INFO] 已选择</info>"
                    . "<primary>【{$selection}】</primary>"
            );
        }

        // 给用户一些确认选项的时间，“性能提升器”
        $sleep && Util::usleepSeconds(0.5);
    }

    public static function clearScreen()
    {
        if (strtoupper(substr(PHP_OS, 0, 3)) === 'WIN') {
            system('cls');
        } else {
            system('clear');
        }

        Util::usleepSeconds(0.1);
    }
}
