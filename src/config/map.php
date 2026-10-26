<?php

return [
    /**
     * 固定的词库操作索引
     * 下列配置中的词库数量有变更时，记得更换这里的索引值
     */
    'extraMapIndex'  => 1,   // extraMap
    'shengpiziIndex' => 7,   // 生僻字注音
    'tempFixIndex'   => 8,   // 临时替换表

    /**
     * 校正时使用的词库配置
     */
    'useMapsConfig' => [
        [
            'configTitle'    => '使用【自定义词库】进行校正（【第一轮校正】时建议使用此项）',
            'useMaps'        => [ // 对 books 文件夹内的书籍进行校正时使用的规则
                'punctuationMap',
                'normalMap',
                'cjkRecoverMap',
                'customNormalMap',
            ],
            'bakUseMaps'     => [ // 对 booksBak 文件夹内的书籍进行预处理时使用的规则，若为空则是不进行预处理
                'punctuationMap',
                'preprocessMap',
                'cjkRecoverMap',
                'customPreprocessMap',
            ],
            'enableRegexFix' => true, // 若为 false，则会跳过相关的正则修改
            'singleReplace'  => false, // 若为 true，则在 doReplace 时只替换一次
        ],
        [
            // 较多误改，可以根据需要自行调整
            'configTitle'    => '使用【自定义词库】的【extraMap】进行额外的“的地得”和“象像”校正',
            'useMaps'        => [
                'punctuationMap',
                'normalMap',
                'extraMap',
                'accurateDddMap',
                'customNormalMap',
                'customExtraMap',
            ],
            'bakUseMaps'     => [
                'punctuationMap',
                'extraPreprocessMap',
                'accurateDddMap',
                'customExtraPreprocessMap',
            ],
            'enableRegexFix' => true,
            'singleReplace'  => false,
        ],
        [
            'configTitle'    => '使用【自定义词库】修正旧式、通假的写法（旧书、港台书籍中的常见词）',
            'useMaps'        => [
                'punctuationMap',
                'oldStyleMap',
                'customOldStyleMap',
            ],
            'bakUseMaps'     => [],
            'enableRegexFix' => true,
            'singleReplace'  => false,
        ],
        [
            // 较多误改，建议在第一次使用【自定义词库】校正完毕后，
            // 再选用此项进行校正并比对结果，只是为了从 txtFormat 词库中选取一些需要的词
            'configTitle'    => '使用【txtFormat 词库】进行校正',
            'useMaps'        => [
                'txtFormatMap',
                'customTxtFormatMap',
            ],
            'bakUseMaps'     => [],
            'enableRegexFix' => false,
            'singleReplace'  => false,
        ],
        [
            // 较多误改，可以根据需要自行调整
            'configTitle'    => '使用【txtFormat 词库】的【“的地得”词库】进行校正',
            'useMaps'        => [
                'dddMap',
                'customDddMap',
            ],
            'bakUseMaps'     => [],
            'enableRegexFix' => false,
            'singleReplace'  => false,
        ],
        [
            'configTitle'    => '使用【繁转简词库】进行校正',
            'useMaps'        => [
                't2sMap',
                'cjkRecoverMap',
                'customT2sMap',
            ],
            'bakUseMaps'     => [],
            'enableRegexFix' => false,
            'singleReplace'  => false,
        ],
        [
            'configTitle'    => '使用【繁转简 t2sRadicalMap】，可参照这个 Map 的注释修正“著”字',
            'useMaps'        => [
                'cjkRecoverMap',
                't2sRadicalMap',
                'radicalsSupplementMap',
                'customT2sRadicalMap',
            ],
            'bakUseMaps'     => [],
            'enableRegexFix' => false,
            'singleReplace'  => false,
        ],
        [
            'configTitle'    => '使用【生僻字词库】进行注音',
            'useMaps'        => [
                'shengpiziMap',
                'cjkExtMap',
                'customShengpiziMap',
            ],
            'bakUseMaps'     => [],
            'enableRegexFix' => false,
            'singleReplace'  => true,
        ],
        [
            'configTitle'    => '使用【临时替换表（需要先通过批注生成）】进行校正',
            'useMaps'        => [
                'tempMap',
            ],
            'bakUseMaps'     => [],
            'enableRegexFix' => true,
            'singleReplace'  => true,
        ],
        [
            'configTitle'    => '使用【“得”转“的”表】强制将所有“得”转为“的”',
            'useMaps'        => [
                'dei2deMap',
            ],
            'bakUseMaps'     => [],
            'enableRegexFix' => false,
            'singleReplace'  => false,
        ],
    ],

    /**
     * 各 map 变量和文件名的映射
     */
    'fileMapping' => [
        'punctuationMap'        => '1.自定义词库.php',
        'preprocessMap'         => '1.自定义词库.php',
        'extraPreprocessMap'    => '1.自定义词库.php',
        'normalMap'             => '1.自定义词库.php',
        'extraMap'              => '1.自定义词库.php',
        'strictMap'             => '1.自定义词库.php',
        'postFixMap'            => '1.自定义词库.php',
        'oldStyleMap'           => '1.自定义词库【旧式、通假写法】.php',
        't2sMap'                => '2.繁转简词库.php',
        't2sRadicalMap'         => '2.繁转简词库.php',
        'radicalsSupplementMap' => '2.繁转简词库.php',
        'txtFormatMap'          => '3.txtFormat 词库.php',
        'dddMap'                => '4.的地得词库.php',
        'dei2deMap'             => '4.的地得词库.php',
        'accurateDddMap'        => '4.的地得词库.php',
        'tempMap'               => '5.临时校对表.php',
        'shengpiziMap'          => '7.生僻字词库.php',
        'cjkExtMap'             => '7.生僻字词库【扩展区】.php',
        'cjkRecoverMap'         => '7.生僻字词库【扩展区】.php',

        // 用户自定义扩展
        'customPreprocessMap'      => '6.用户扩展词库.php',
        'customExtraPreprocessMap' => '6.用户扩展词库.php',
        'customNormalMap'          => '6.用户扩展词库.php',
        'customExtraMap'           => '6.用户扩展词库.php',
        'customOldStyleMap'        => '6.用户扩展词库.php',
        'customT2sMap'             => '6.用户扩展词库.php',
        'customT2sRadicalMap'      => '6.用户扩展词库.php',
        'customTxtFormatMap'       => '6.用户扩展词库.php',
        'customDddMap'             => '6.用户扩展词库.php',
        'customShengpiziMap'       => '6.用户扩展词库.php',
    ],
];
