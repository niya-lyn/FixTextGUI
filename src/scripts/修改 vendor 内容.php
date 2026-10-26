<?php

use App\Util\Util;

chdir(__DIR__);

include("autoload.php");

chdir("../vendor");

$replaceMaps = [
    "inhere/console/src/Component/Interact/Choose.php" => [
        "input must in the list: " => "请重试，输入的值超出了选项范围：",
        "[default:" => "[默认值：",
        "Your choice" => "请输入",
        "Quit,ByeBye." => "忽略选择，无操作",
        "int|string \$default = null" => "int|string|null \$default = null",
    ],
    "inhere/console/src/Component/ErrorHandler.php" => [
        "You can use '--debug 4' to see error details." => "出现异常，脚本已停止执行，请检查上方的报错信息。",
    ],
    "toolkit/cli-utils/src/Color.php" => [
        "notice(string \$text)\n * @method static string warning" => "notice(string \$text)\n * @method static string note(string \$text)\n * @method static string warning",
        "cyan(string \$text)\n * @method static string black" => "cyan(string \$text)\n * @method static string red1(string \$text)\n * @method static string black",
    ],
];

$regexPatterns = [
    "Dummy.php" => [
        [
            'search'    => "",
            'replace'   => "",
            'modifiers' => "um",
        ]
    ],
];

foreach ($replaceMaps as $file => $map) {
    if (!file_exists($file)) {
        continue;
    }

    echo "正在使用 replaceMaps 修改：{$file}" . PHP_EOL;

    $content = file_get_contents($file);
    $content = strtr($content, $map);
    file_put_contents($file, $content);
}

echo "==================================" . PHP_EOL;

foreach ($regexPatterns as $file => $patterns) {
    if (!file_exists($file)) {
        continue;
    }

    echo "正在使用 regexPatterns 修改：{$file}" . PHP_EOL;

    $content = file_get_contents($file);
    Util::multiRegexReplace($patterns, $content);
    file_put_contents($file, $content);
}
