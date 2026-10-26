<?php

namespace App\Util;

use App\Exception\AppException;
use Noodlehaus\Config as NoodlehausConfig;

/**
 * @method static mixed getFormatting(string $item)
 * @method static mixed getMap(string $item)
 * @method static mixed getDiff(string $item)
 * @method static mixed getGeneral(string $item)
 */
class Config
{
    /**
     * @var NoodlehausConfig[]
     */
    protected static $instances;

    public static function __callStatic(string $method, array $args)
    {
        if (substr($method, 0, 3) == 'get') {
            return self::getConf($args[0], strtolower(substr($method, 3)));
        }

        throw new AppException("Config 类中不存在此方法：{$method}");
    }

    /**
     * @param string $item 为空时，返回 Config 对象
     * @param string $file 为空时，会先获取 config 下所有文件内的配置项，再读取 item
     * @return mixed
     * @throws AppException 如果配置文件不存在
     */
    public static function getConf($item = '', $file = ''): mixed
    {
        $finalFilepath = self::findConfigFile(SCRIPT_DIR . '/config', $file);
        if (!isset(self::$instances[$finalFilepath])) {
            $conf = NoodlehausConfig::load($finalFilepath);
            self::$instances[$finalFilepath] = $conf;
        } else {
            $conf = self::$instances[$finalFilepath];
        }

        return self::getConfigItem($conf, $item);
    }

    protected static function findConfigFile($basePath, $file)
    {
        if ($file === '') {
            return $basePath;
        }

        $exts = ['php', 'json', 'ini', 'xml', 'yml'];
        $extCount = count($exts);
        $extIdx = 0;
        $finalFilepath = null;

        while ($extIdx < $extCount) {
            $currentFilepath = $basePath . '/' . $file . '.' . $exts[$extIdx];
            if (file_exists($currentFilepath)) {
                $finalFilepath = $currentFilepath;
                break;
            }
            $extIdx++;
        }

        if (is_null($finalFilepath)) {
            throw new AppException("配置文件不存在：{$file}");
        }

        return $finalFilepath;
    }

    protected static function getConfigItem($conf, $item)
    {
        if ($item === "") {
            return $conf;
        }

        return $conf[$item] ?? "";
    }
}
