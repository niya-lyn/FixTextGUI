# -*- coding: utf-8 -*-
"""
T1.6 · PHP 闭包重实现 —— FixText noteBrandProcessors 的 Python 等价模块（可选增强）

来源：FixText/src/config/general.php 的 `noteBrandProcessors` 配置，3 处 PHP 闭包
（T0.2 词库迁移时因 json_encode 静默降级为 `{}`，词库 JSON 中已显式标记）：

  - moonreader（general.php 约 1086 行）：静读天下批注 —— 把划线文本尾部 " (批注)" 拆出
  - calibre  （general.php 约 1095 行）：calibre 批注 —— 删划线文本中的 Markdown 标题行、BOM
  - weread   （general.php 约 1102 行）：微信读书批注 —— "发表想法" 交换原文/想法、纯划线去 ◆、整体倒序

调用约定（与 PHP 侧 NoteParser 完全一致）：
  - 入参 `matches` 是"匹配行"的列表；每行是 list，下标语义同 PHP preg_match_all(PREG_SET_ORDER)：
      match[0] = 整体匹配文本，match[1] = 分组1（before/划线），match[2] = 分组2（after/批注，可缺失）。
  - PHP 中缺失的分组在 Python 里用 None 表示（见 _set / 行尾 None 在序列化时等价 PHP 缺键）。
  - 与 PHP 引用传参 `function (array &$matches)` 等价：三个函数全部**原地修改**传入的 matches；
    weread 末尾的整体倒序用 `matches.reverse()`（原地）实现 PHP `$matches = array_reverse($matches)`
    对调用方的重绑定效果。
  - 使用方式：
        from note_brand_processors import NOTE_BRAND_PROCESSORS
        processor = NOTE_BRAND_PROCESSORS.get(brand)
        if processor:
            processor(matches)

PCRE → Pythonre 的语义对齐说明：
  - PHP 正则全部带 `u` `m` `s` 三个修饰符（NoteParser 中拼为 "/{$pattern}/ums"）。
  - `s` = DOTALL：`.` 匹配换行 → Python `re.S`。
  - `m` = MULTILINE：`^`/`$` 按行匹配 → Python `re.M`。
  - `u` = UTF-8 模式：PCRE 无 UCP 时 `\d` 仅匹配 ASCII 数字；Python `\d` 会匹配全角数字等
    Unicode 十进制数字。为保证行为逐字节等价，模块内正则一律用显式 `[0-9]` 替代 `\d`。
  - PHP `trim($s, ' ()')` ≡ Python `str.strip(' ()')`（按字符集合剥离两端）。
  - PHP `str_contains` ≡ Python `in`；`str_replace($a, $b, $s)` ≡ `str.replace`（全部出现）。
  - PHP `preg_replace(p, r, $s)` ≡ `re.sub(p, r, s)`（全局替换）。
"""

import re

__all__ = [
    "process_moonreader",
    "process_calibre",
    "process_weread",
    "NOTE_BRAND_PROCESSORS",
]

# PHP 闭包源码所在行号（FixText/src/config/general.php，与 T0.2 迁移报告 §5 一致）
PHP_SOURCE_LINES = {
    "moonreader": 1086,
    "calibre": 1095,
    "weread": 1102,
}


def _as_str(value):
    """PHP 弱类型容错：null 按空字符串处理（仅防御，moonreader 等模式下 group1 恒存在）。"""
    return "" if value is None else value


def _set(match, index, value):
    """PHP 数组按下标自动扩展的语义：越界时先补 None（等价 PHP 缺键）再赋值。"""
    while len(match) <= index:
        match.append(None)
    match[index] = value


def process_moonreader(matches):
    # PHP general.php L1086-1093（原文逐条对照见本行下方注释块）
    #
    #   'moonreader' => function (array &$matches) {
    #       foreach ($matches as &$match) {
    #           if (preg_match('/(.*?)( \(.*\))/ums', $match[1], $ret) && isset($ret[2])) {
    #               $match[1] = $ret[1];
    #               $match[2] = trim($ret[2], ' ()');
    #           }
    #       }
    #   },
    #
    # 行为：对每条匹配，在划线文本（分组1）里找 " ("（空格+左括号）：
    #   - 分组1 = 第一个 " (" 之前的全部内容（懒匹配 ⇒ 取最早出现的 " ("）；
    #   - 分组2 = 从该 " (" 到字符串中**最后一个** ")"（`.*` 贪婪 + `s` 跨行）；
    #   - 命中时：分组1 改为括号前文本，分组2 = 括号段按 ' ()' 字符集 trim 两端（批注）。
    #   - `isset($ret[2])` 在 preg_match 成功时恒真（分组2 非可选），保留判断仅为逐行对齐。
    _rx = re.compile(r"(.*?)( \(.*\))", re.S)  # ums 中的 m 无锚点不影响；u 见模块头说明
    for match in matches:
        m = _rx.search(_as_str(match[1]))
        if m and m.group(2) is not None:
            match[1] = m.group(1)
            _set(match, 2, m.group(2).strip(" ()"))


def process_calibre(matches):
    # PHP general.php L1095-1100
    #
    #   'calibre' => function (array &$matches) {
    #       foreach ($matches as &$match) {
    #           $match[1] = preg_replace('/#+ .*/um', '', $match[1]);
    #           $match[1] = str_replace('﻿', '', $match[1]);
    #       }
    #   },
    #
    # 行为：对每条匹配的划线文本（分组1）：
    #   - 删除所有 `#+ `（≥1 个 # 加空格）起、至**行尾**的片段（无 `s` 修饰符 ⇒ `.` 不跨行；
    #     行内 "xxx # yyy" → "xxx "，即只删 "#" 空格之后的部分）；
    #   - 删除 U+FEFF（零宽不换行空格 / BOM，源码中为不可见字符）。
    _heading = re.compile(r"#+ .*")  # PHP /um：m 无锚点不影响，`.` 不匹配 \n 与 Python 默认一致
    for match in matches:
        match[1] = _heading.sub("", _as_str(match[1]))
        match[1] = match[1].replace("\ufeff", "")


def process_weread(matches):
    # PHP general.php L1102-1119
    #
    #   'weread' => function (array &$matches) {
    #       foreach ($matches as &$match) {
    #           if (str_contains($match[0], '发表想法')) {
    #               preg_match('/发表想法\n(.*?)原文：(.*)/ums', $match[0], $ret);
    #               // 颠倒顺序……
    #               $match[1] = $ret[2] ?? '';
    #               $match[2] = $ret[1] ?? '';
    #           } else {
    #               // 纯划线
    #               $match[1] = str_replace('◆ ', '', $match[0]);
    #           }
    #       }
    #       // 如果对某一处同时划线和批注，划线被放到了后一条
    #       // 结果需要反过来才能保证批注的优先级更高……
    #       $matches = array_reverse($matches);
    #   },
    #
    # 行为：对每条匹配：
    #   - 整体匹配含 "发表想法" 时：从 "发表想法\n" 到 "原文：" 之间是想法（分组1），"原文：" 之后到
    #     整体匹配末尾是原文（分组2，贪婪 + `s` 跨行）。交换后：match[1]=原文（before）、match[2]=想法
    #     （after）。若内层 preg_match 失败（如缺 "原文："），$ret 为空数组 ⇒ `?? ''` 使两值均为 ''；
    #   - 否则为纯划线：match[1] = 整体匹配去掉所有 "◆ "，match[2] 保持缺失（PHP 不设置该键）；
    #   - 最后**整体倒序**所有匹配（原地，等价 PHP 引用重绑定 array_reverse）。
    _note = re.compile(r"发表想法\n(.*?)原文：(.*)", re.S)
    for match in matches:
        if "发表想法" in match[0]:
            m = _note.search(match[0])
            # PHP：$ret[2] ?? ''、$ret[1] ?? ''（失败时均为 ''）
            _set(match, 1, m.group(2) if m else "")
            _set(match, 2, m.group(1) if m else "")
        else:
            # 纯划线
            _set(match, 1, match[0].replace("◆ ", ""))
            # 分组2 保持缺失（None），等价 PHP 不设置 $match[2]
    matches.reverse()


# 注册表：brand → Python 处理函数（供词库引擎按 noteBrandProcessors 键接入）
NOTE_BRAND_PROCESSORS = {
    "moonreader": process_moonreader,
    "calibre": process_calibre,
    "weread": process_weread,
}
