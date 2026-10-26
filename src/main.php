<?php

// 如果将 main.php 移动到其他目录来执行，需要修改 SCRIPT_DIR 和 BOOK_DIR 常量，
// 如果想使用到书籍备份原文件的预处理功能，还要同步修改 BOOK_BAK_DIR 常量，
// 以指定代码目录书籍目录，注意最后不要带斜杠
define("SCRIPT_DIR", __DIR__);

// 定义书籍处理目录
define("BOOK_DIR", dirname(__DIR__) . "/books");

// 定义书籍自动备份目录
define("BOOK_BAK_DIR", dirname(__DIR__) . "/booksBak");

// 定义全量修复文件的备份目录，用于后续自动生成书籍专有词条
define("BOOK_FIX_DIR", dirname(__DIR__) . "/booksFix");

// epub 文本合并记录的存放目录
define("EPUB_MERGE_LOG_DIR", dirname(__DIR__) . "/logs/merge");

// epub 文件解压/压缩记录列表
define("EPUB_LIST_LOG", dirname(__DIR__) . "/logs/epub_list.log");

// 某些统计报告的存放目录
define("REPORT_DIR" , dirname(__DIR__) . "/logs/report");

// epub 文件解压出来的目录标识前缀
const EPUB_EXTRACT_PREFIX = "【EPUB 解压文件夹】";

// epub 文本合并后的文件标识前缀
const EPUB_MERGE_PREFIX = "【EPUB 合并文件】";

// 是否递归进入子目录进行修正，若为 false 则只修正当前目录
const RECURSIVE_FIX = true;

// 校正完后是否重新打包 epub
const REPACK_AFTER_FIX = false;

// 需要忽略的目录，只检测目录名是否匹配，不考虑当前递归层次
const EXCLUDE_DIRS = [];

// 临时替换表
const TEMP_MAP_FILE = SCRIPT_DIR . "/maps/5.临时校对表.php";

// 临时使用 go 替换文本内容
const REPLACE_BY_GO = true;
define("GO_REPLACE_CMD_FILE", __DIR__ . "/tools/replace_by_go.exe");
const TXT_REPLACE_BEFORE = SCRIPT_DIR . "/TXT_REPLACE_BEFORE.txt";
const TXT_REPLACE_AFTER = SCRIPT_DIR . "/TXT_REPLACE_AFTER.txt";

// 目前设置的词条不太适合开启分词……
const TOKENIZE_CONTENT = false;
define("GOJIEBA_CMD_FILE", __DIR__ . "/tools/gojieba.exe");
const GOJIEBA_DICT = SCRIPT_DIR . "/tools/gojieba_dict.txt";

require_once(SCRIPT_DIR . "/bootstrap.php");
