# T1.4 引号检查 · PHP 原版 vs Python 重实现 等价性比对报告

- 比对对象：PHP `../../../input/fixtext_src/FixText/src/app/Service/Quotation/QuotationChecker.php`（检测逻辑未修改，
  经 php_harness.php 以统计模式单遍语义驱动）vs Python `fixtext_quotation/checker.py`
- 语料：../../../input/baseline/FixText_T0.4_回归基线集_v1/baseline/corpus 下 15 份 txt
- 比对口径：逐文件事件流（行号 + 行内字符下标 + 报错文案）完全相等

## 逐文件结论

| 语料 | PHP 错误数 | Python 错误数 | 等价 |
| --- | --- | --- | --- |
| novel_fanpai_ch001-060.txt | 3 | 3 | ✅ |
| novel_guimie_full.txt | 22 | 22 | ✅ |
| novel_quehun_ch001-060.txt | 0 | 0 | ✅ |
| pg23863_水滸傳.txt | 4 | 4 | ✅ |
| pg23910_封神演義.txt | 0 | 0 | ✅ |
| pg23950_三國志演義.txt | 6 | 6 | ✅ |
| pg23962_西遊記.txt | 252 | 252 | ✅ |
| pg24032_儒林外史.txt | 428 | 428 | ✅ |
| pg24141_警世通言.txt | 0 | 0 | ✅ |
| pg24226_史記.txt | 0 | 0 | ✅ |
| pg24230_今古奇觀.txt | 0 | 0 | ✅ |
| pg24264_紅樓夢.txt | 7680 | 7680 | ✅ |
| pg27166_呐喊.txt | 138 | 138 | ✅ |
| pg51828_聊齋志異.txt | 61 | 61 | ✅ |
| pg52200_金瓶梅.txt | 33 | 33 | ✅ |

**结论：15/15 份语料事件流逐条完全一致，等价性通过。**