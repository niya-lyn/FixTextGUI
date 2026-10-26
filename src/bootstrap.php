<?php

ini_set("memory_limit", "4096M");
date_default_timezone_set("Asia/Shanghai");
mb_internal_encoding("UTF-8");

require_once(__DIR__ . "/vendor/autoload.php");

use App\Util\Util;
use App\Util\Console\Show;
use App\Util\Console\Color;
use Inhere\Console\IO\Input;
use Inhere\Console\IO\Output;
use Inhere\Console\Application;

// putenv(\Inhere\Console\Console::DEBUG_ENV_KEY . "=4"); // 打印所有报错信息
$meta = [
    'name'    => "fix-text",
    'version' => "1.0.0",
];
$input = new Input;
$output = new Output;
$app = new Application($meta, $input, $output);

$app->registerCommands('App\Command', __DIR__ . '/app/Command');

$app->on(Application::ON_BEFORE_RUN, function () {
    if (Util::isFromGUI()) {
        // 从 gui 界面调用时，强制输出颜色代码
        Color::setForceColor(true);
    }

    $command = Util::getArgvByIndex(1);
    if ($command) {
        Show::writeWithNL("!!!!!!! 开始执行命令：【{$command}】 !!!!!!!");
    }
});

$app->on(Application::ON_AFTER_RUN, function () {
    echo PHP_EOL;
    $command = Util::getArgvByIndex(1);
    if ($command) {
        Show::writeWithNL("!!!!!!! 结束执行命令：【{$command}】 !!!!!!!");
    }
});

// 将 PHP 警告（如无效的正则表达式）转换为异常，在业务代码中可捕获并打印上下文信息
// 这会使 php-console 的 set_error_handler 失效，但因为它本身也是转发调用自己的 handleExcepiton，
// 如果在业务代码中重新将异常抛出，最终也能走入包内自带的异常处理方法
set_error_handler(function ($severity, $message, $file, $line) {
    if (!(error_reporting() & $severity)) {
        return false; // 如果错误被抑制了（比如用了 @），则不处理
    }

    throw new ErrorException($message, 0, $severity, $file, $line);
});

$app->run();

