<?php
/**
 * 生成 strip_tags 权威基准向量。
 *
 * 由真实 PHP 运行时执行 strip_tags()，把结果以 JSON 输出，
 * 供 Python 测试套件作为「外部权威」断言源使用——
 * 这样测试断言不是从 Python 自己的实现里抄来的（避免循环论证）。
 *
 * 用法: php scripts/gen_fixtures.php > tests/fixtures/strip_tags_php.json
 */

error_reporting(E_ALL);

$probes = [
    // 基础
    "plain text",
    "",
    "<p>hello</p>",
    "<p>你好</p>世界",
    "a<b>c</b>d",
    "<div><span>x</span></div>",

    // 未闭合 / 孤立尖括号
    "尾<",
    "中<后",
    "<",
    "x< y",
    "x<",
    "<b>未闭合",
    "no tags at all",

    // 尖括号后跟空白 -> 字面输出
    "< 3",
    "a < b",
    "a<\tb",
    "a<\nb",

    // 数字 / 标点 / CJK 也算标签起始
    "<3 个苹果>不是标签",
    "<.5>x",
    "<:x>y",
    "<-a->b",

    // 嵌套深度
    "<<a>>x",
    "<<<x>>>y",
    "<a<b>c>d",
    "<a<b<c>>>d",

    // 注释
    "<!-- comment -->text",
    "<a<!--b-->c>d",
    "<a<x<!--b-->>c",
    "<a<x<!--b>>c>y",
    "<a<!--b--><!--c-->d",
    "<!-->x",
    "<!--->x",
    "<!--!>x",
    "<a<!--b-->c<x>>y",

    // 处理指令
    "<a<?b?>c>d",
    "<?php echo 1; ?>x",
    "<?php x > y?>z",
    "<a<!--b--><?x?>y>z",

    // 引号保护
    "<a x=\"1>2\">z",
    "<a x=\"<b>\">y",
    "<a<x=\"q>z\"p=\"r\">w",
    "<a<x=\"q>z>y\">w",
    "<a x=\"<!--c-->\"> >y",
    "<a x='s>t'>z",
    "<!DOCTYPE \"a>b\">x",
    "<a<!--b-->x=\"q>z\">w",

    // 复杂混合
    "<html><body><p>段落一</p><p>段落二</p></body></html>",
    "前<b>中</b>后<i>尾</i>",
    "<a href=\"http://x.com/?a=1&b=2\">链接</a>",
];

$out = [];
foreach ($probes as $p) {
    $out[] = [
        "input"    => $p,
        "expected" => strip_tags($p),
    ];
}

echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), "\n";
