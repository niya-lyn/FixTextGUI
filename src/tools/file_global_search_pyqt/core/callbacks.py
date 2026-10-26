import regex

import utils.util as util
from utils.chapter_num_checker import ChapterNumChecker

# =========================== 替换回调函数 ===========================


def clear_repeated_words(match: regex.Match) -> str:
    """【替换回调】移除叠字叠词"""
    text = match.group(0)
    length = len(text)
    for i in range(1, length // 2 + 1):
        if length % i == 0:
            # 尝试将字符串分割成若干个长度为 i 的子串
            sub_str = text[:i]
            repeated_times = length // i
            if sub_str * repeated_times == text:
                return sub_str

    return text


def xx_to_multiplications(match: regex.Match) -> str:
    """【替换回调】将 'xx' 或者 '**' 转换为 '××'"""
    text = match.group(0)
    if regex.fullmatch(r"[xX]+|[*＊]+", text):
        return regex.sub(r"[xX*＊]", "×", text)

    return ""


def periods_to_commas(match: regex.Match) -> str:
    """【替换回调】句号改成逗号"""
    return match.group(0).replace("。", "，")


def commas_to_dunhaos(match: regex.Match) -> str:
    """【替换回调】逗号改成顿号"""
    return match.group(0).replace("，", "、")


def an2cn(match: regex.Match) -> str:
    """【替换回调】将阿拉伯数字转为中文"""
    return regex.sub(r"\d+", lambda m: util.arabic_to_chn_num(int(m.group())), match.group(0))


def eng_quotes_to_chn_quotes(match: regex.Match) -> str:
    """【替换回调】将英文引号转换为中文引号"""
    text = match.group(0)

    # 处理空匹配或长度为1的匹配（单个引号）
    if not text:
        return ""

    if len(text) == 1:
        if text in '"':
            return "“"
        if text == "'":
            return "’"
        return text

    start_char = text[0]
    end_char = text[-1]

    # 判断结尾字符是否是一个引号
    is_closed = end_char in "'\"“”‘’"

    # 根据起始引号确定要使用的中文引号类型
    if start_char in '"“”':
        final_start = "“"
        if end_char in "'’":
            final_end = "’"
        else:
            final_end = "”"
    elif start_char in "'‘’":
        final_start = "‘"
        if end_char in '"”':
            final_end = "”"
        else:
            final_end = "’"
    else:
        # 如果起始字符不是引号，则不应由该函数处理，按原样返回
        return text

    # 提取内容并构建新字符串
    if is_closed:
        # 如果有结束引号，内容在第一个和最后一个字符之间
        content = text[1:-1]
        return final_start + content + final_end
    else:
        # 如果没有结束引号（匹配到字符串末尾）
        content = text[1:]
        if start_char == '"':
            return "“" + content
        elif start_char == "'":
            return "’" + content


def half_width_to_full_width_punctuation(match: regex.Match) -> str:
    """【替换回调】将匹配到的英文半角标点符号转换为对应的中文全角标点"""
    # 获取匹配到的整个字符串
    text = match.group(0)

    # 规则 1：优先处理连续的点（省略号）
    if ".." in text:
        return "……"

    # 规则 2：使用字典映射处理单个标点符号
    punctuation_map = {
        ",": "，",
        "?": "？",
        "!": "！",
        "(": "（",
        ")": "）",
        ";": "；",
        ".": "。",
        ":": "：",
    }

    return punctuation_map.get(text, text)


def normalize_punctuations(match: regex.Match) -> str:
    """【替换回调】根据预设规则纠正匹配到的中文标点错误"""
    text = match.group(0)

    # 规则：移除特定标点前的空格，例如 “你好 。” -> “你好。”
    # 匹配模式: [ 　]+(?=[”’．。，,、`])
    if text.isspace():
        return ""

    # 规则：移除引号后多余的标点，例如 “。”， -> “。”
    # 匹配模式: 。”[，！？]
    if text.startswith("。”") and len(text) == 3 and text[-1] in "，！？":
        return text[:-1]

    # 规则：移除省略号后多余的点，例如 ……。 -> ……
    # 匹配模式: …+[．,、·`]+
    if text.startswith("…") and text[-1] in "．,、·`" and regex.fullmatch(r"…+[．,、·`]+", text):
        return regex.sub(r"[．,、·`]+$", "", text)

    # 规则：将各种不规范的省略号统一为“……”
    # 匹配模式: (?<!…)…(?!…)|[…]{3,}|[．.。，,、`]+…+[．,、·`]+|[．。,、·`]{2,}
    if regex.fullmatch(r"(?<!…)…(?!…)|[…]{3,}|[．.。，,、`]+…+[．,、·`]+|[．。,、·`]{2,}", text):
        return "……"

    # 规则：将竖排或特殊标点转换为对应的横排标点
    # 匹配模式: [﹑﹁﹂﹄﹃︵︶︻︼︰]
    special_punctuation_map = {
        "﹑": "、",
        "﹁": "「",
        "﹂": "」",
        "﹄": "』",
        "﹃": "『",
        "︵": "（",
        "︶": "）",
        "︻": "【",
        "︼": "】",
        "︰": "：",
    }
    if text in special_punctuation_map:
        return special_punctuation_map[text]

    # 规则：消除重复的标点，例如 。。 -> 。
    # 匹配模式: ““|””|‘‘|’’|：：|，{2,}
    if regex.fullmatch(r"““|””|‘‘|’’|：：|，{2,}", text):
        return text[0]

    # 规则：两个紧邻的不同标点，保留前者，例如 ！， -> ！
    # 匹配模式: 多个，例如 ！[，。；：、]
    adjacent_pattern = r"！[，。；：、]|，[：。！？；、]|。[，！：；？、]|：[，；！。？、]|、[。，！？；]|？[、，。；：]|·[，！：；？、…—”’]"
    if regex.fullmatch(adjacent_pattern, text):
        return text[0]

    # 规则：处理其他特定组合
    if regex.fullmatch(r"、’", text):
        return "。’"
    if regex.fullmatch(r"、”", text):
        return "。”"
    if regex.fullmatch(r"[ 　]”", text):
        return "”"
    if regex.fullmatch(r"：”", text):
        return "：“"
    if regex.fullmatch(r"：’", text):
        return "：‘"
    if regex.fullmatch(r"，”(?!.*“)", text):
        return "。”"

    # 如果没有匹配到任何特定规则，返回原始匹配文本
    return text


def normalize_sequence_marker(match: regex.Match) -> str:
    """
    【替换回调】根据上下文规范化各种序次语的写法

    - “第一”“第二”等，后面跟全角逗号：“第一，”
    - “其一”“其二”等，后面跟全角逗号：“其一，”
    - 单独的“一”、“二”等，后面跟顿号：“一、”
    - 阿拉伯数字、罗马数字、字母等，后面跟点和空格：“1. ”和“A. ”
    - “第1、” -> “第一，”
    - “首先、” -> “首先，”
    - 多级序号，如“2.1. ……”，修正为“2.1 ……”

    Args:
        match: regex.Match 对象

    Returns:
        修正后的序号字符串
    """
    matched_text = match.group(0)

    # Case 1: 处理 "首先、" "其次、" 等关键词
    text_markers = ("首先", "其次", "再次", "从次", "最后", "然后", "接着", "另外", "此外", "除此")
    if matched_text.startswith(text_markers):
        return regex.sub(r"[、.：]$", "，", matched_text)

    # 处理多级序号，如“2.1. ……”
    core_text = matched_text.strip()
    if regex.fullmatch(r"\d+\.\d+\.", core_text):
        # 将匹配到的核心文本末尾的点去掉，并保留原始的前后空白
        return matched_text.replace(core_text, core_text[:-1] + " ")

    # Case 2: 匹配以“第”或“其”开头的情况
    if matched_text.startswith(("第", "其")):
        prefix = matched_text[0]
        num_part = matched_text[1:-1].strip()  # 去除前后缀，得到纯数字

        if num_part.isdigit():
            try:
                chn_num = util.arabic_to_chn_num(int(num_part))
                return f"{prefix}{chn_num}，"
            except (ValueError, NameError):
                return f"{prefix}{num_part}，"
        else:
            return f"{prefix}{num_part}，"

    # Case 3: 匹配以其他前导字符开头的情况
    else:
        prefix_char = matched_text[0]
        num_part = matched_text[1:-1].strip()

        if not num_part:
            return matched_text

        # Case 3a: 独立的中文数字, e.g., " 一，" -> " 一、"
        if all(c in "一二三四五六七八九十" for c in num_part):
            return f"{prefix_char}{num_part}、"

        # Case 3b: 独立的字母、数字或罗马数字, e.g., " A、" -> " A. "
        allowed_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ"
        if all(c in allowed_chars for c in num_part):
            return f"{prefix_char}{num_part}. "

    return matched_text


def process_arabic_approximate_numbers(match: regex.Match) -> str:
    """【替换回调】将阿拉伯数字概数转换为中文数字，移除概数间的顿号"""
    original_text = match.group(0)
    if original_text == "2、3":
        return "两三"

    number_parts = original_text.split("、")

    # 确保分割后是两个纯数字部分
    if len(number_parts) != 2 or not all(part.isdigit() for part in number_parts):
        return original_text

    # 将两个数字部分转换为中文数字并拼接
    num1_chn = util.arabic_to_chn_num(int(number_parts[0]))
    num2_chn = util.arabic_to_chn_num(int(number_parts[1]))

    return f"{num1_chn}{num2_chn}"


def merge_lines(match: regex.Match) -> str:
    """【替换回调】合并多行文本，支持自动处理连续的引号行"""
    return util.process_merge_lines(match.group(0))


# =========================== 搜索回调函数 ===========================


def check_chapter_num(search_result: str, file_path: str) -> str:
    """
    【搜索回调】分析搜索结果中的章节号序列，检查乱序，并计算各章节间的字数

    Args:
        search_result (str): 多行的搜索结果字符串
        file_path (str): 原始文件的路径，用于字数统计

    Returns:
        str: 修改后的搜索结果字符串，匹配行被添加了【章节/乱序行】标记和字数统计
    """
    return ChapterNumChecker.check_chapter_num(search_result, file_path)
