import regex as re
import subprocess
import json
import os
import logging

from typing import Optional, Dict

import regex
from regex import Match
import markdown

from core.env_config import env_config


def bytes_to_readable_size(file_bytes: int, precision: int = 2) -> str:
    """
    将字节数转换为人类可读的文件大小格式（例如 KB, MB, GB）

    Args:
        file_bytes: 文件的字节数
        precision: 结果保留的小数位数

    Returns:
        一个表示文件大小的字符串
    """
    if file_bytes <= 0:
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while file_bytes >= 1024 and i < len(units) - 1:
        file_bytes /= 1024
        i += 1

    return f"{file_bytes:.{precision}f} {units[i]}"


def format_count_to_readable_chinese(count: int) -> str:
    """
    将数字转换为更易读的中文计数单位（如 千、万、亿）

    - 大于等于 1 亿时，转换为 “亿字”
    - 大于等于 1 万时，转换为 “万字”
    - 大于等于 1 千时，转换为 “千字”
    - 其他情况直接显示数字和“字”
    """
    if count >= 100_000_000:
        return f"{count / 100_000_000:.2f} 亿字"
    if count >= 10_000:
        return f"{count / 10_000:.2f} 万字"
    if count >= 1_000:
        return f"{count / 1_000:.1f} 千字"

    return f"{count} 字"


def chn_to_arabic_num(chinese_num_str: str) -> Optional[int]:
    """
    将中文数字字符串（支持语义和逐位表示法）转换为阿拉伯整数

    支持类型:
    - 语义: '一百零八', '两千', '十五', '一亿'
    - 逐位: '一〇八' (108), '〇一〇' (10), '九九' (99)

    如果输入无效或无法解析，则返回 None。
    对于逐位表示法的 '〇一〇'，返回整数 10。
    """
    _CHINESE_DIGITS = {
        # 标准数字 (用于两种模式)
        "〇": 0,
        "零": 0,
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        # 大写数字 (仅用于语义模式)
        "壹": 1,
        "贰": 2,
        "叁": 3,
        "肆": 4,
        "伍": 5,
        "陆": 6,
        "柒": 7,
        "捌": 8,
        "玖": 9,
        # 特殊数字 (仅用于语义模式)
        "两": 2,
        "廿": 20,
        "卅": 30,
        "卌": 40,
    }
    _CHINESE_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
    _CHINESE_LARGE_UNITS = {"万": 10000, "萬": 10000, "亿": 100000000, "億": 100000000}

    # --- 集合定义 ---
    # 仅用于逐位表示法判断的基础数字字符
    _POSITIONAL_DIGITS_CHARS = {"〇", "一", "二", "三", "四", "五", "六", "七", "八", "九", "零"}
    # 所有合法的语义模式字符（包括大写、特殊、单位）
    _ALL_SEMANTIC_CHARS = set(_CHINESE_DIGITS.keys()) | set(_CHINESE_UNITS.keys()) | set(_CHINESE_LARGE_UNITS.keys())

    # --- 输入校验 ---
    if not chinese_num_str or not isinstance(chinese_num_str, str):
        return None

    # 去除可能存在的空白字符
    chinese_num_str = chinese_num_str.strip()
    if not chinese_num_str:
        return None

    # 处理直接传入的阿拉伯数字字符串
    if re.fullmatch(r"[0-9]+", chinese_num_str):
        return int(chinese_num_str)

    # --- 模式判断与处理 ---

    # 1. 判断是否为 逐位表示法 (仅包含 〇-九)
    is_positional = all(char in _POSITIONAL_DIGITS_CHARS for char in chinese_num_str)

    if is_positional:
        # 如果只有一个字符，并且是 〇 或 零，特殊处理返回 0
        if len(chinese_num_str) == 1 and chinese_num_str in ["〇", "零"]:
            return 0
        # 如果只有一个字符，并且是 1-9，也返回对应数字
        if len(chinese_num_str) == 1 and chinese_num_str in _POSITIONAL_DIGITS_CHARS:
            return _CHINESE_DIGITS[chinese_num_str]

        # 如果长度大于1，或包含非零数字，则执行逐位转换
        if len(chinese_num_str) > 0:
            arabic_str = ""
            for char in chinese_num_str:
                # 这里直接用基础映射 _CHINESE_DIGITS 就够了
                arabic_str += str(_CHINESE_DIGITS.get(char, ""))  # 安全获取
            # 转换为整数，处理 "010" -> 10 的情况
            try:
                return int(arabic_str)
            except ValueError:
                # 如果转换失败（理论上不应发生，因为已检查字符集）
                return None
        else:  # 空字符串情况 (已被前面校验覆盖，但为了逻辑完整)
            return None

    # 2. 如果不是纯粹的逐位表示法，则按 语义表示法 处理
    else:
        # 首先检查是否包含无效字符 (非数字、非单位)
        if not all(char in _ALL_SEMANTIC_CHARS for char in chinese_num_str):
            # 可以选择忽略无效字符，或直接返回 None
            logging.error(f"警告：输入 '{chinese_num_str}' 包含无法识别的语义字符。")
            # 返回 None 更安全
            return None

        # --- 语义解析逻辑 (沿用并优化之前的逻辑) ---

        # 处理特殊开头的 "十" (如 "十五") -> "一十五"
        if chinese_num_str.startswith("十") or chinese_num_str.startswith("拾"):
            chinese_num_str = "一" + chinese_num_str

        # 处理特殊结尾的 "亿/万" (如 "三亿", 需要补零才能正确分割)
        # 更好的方法是在解析时处理，这里暂时不加，看后面逻辑是否覆盖

        total = 0
        current_section = 0  # 当前 大单位(万/亿) 内的数值
        last_digit_val = 0  # 记录遇到的最后一个数字的值 (1-9)
        reading_zero = False  # 标记是否刚读过 零/〇

        for char in chinese_num_str:
            if char in _CHINESE_DIGITS:
                digit = _CHINESE_DIGITS[char]
                if digit == 0:
                    # 遇到零，标记一下，清空最后读到的数字值
                    reading_zero = True
                    last_digit_val = 0
                else:
                    # 遇到1-9, 或 两/廿/卅/卌, 更新最后读到的数字值
                    # 对于 廿/卅/卌，它们自带了单位信息，需要特殊处理
                    if char in ("廿", "卅", "卌"):
                        # 遇到这些，它们本身代表一个值 (20, 30, 40)
                        # 需要累加到 current_section，并重置 last_digit_val
                        current_section += digit
                        last_digit_val = 0
                    else:
                        last_digit_val = digit  # 普通数字 1-9, 两
                    reading_zero = False

            elif char in _CHINESE_UNITS:
                unit = _CHINESE_UNITS[char]
                # 如果 last_digit_val > 0，说明是 "三千", "五百" 等
                if last_digit_val > 0:
                    current_section += last_digit_val * unit
                # 如果 last_digit_val == 0 且刚读过零 ("一百零八")，零不参与乘法
                elif reading_zero:
                    pass  # 零后面跟单位，单位作用于已有的 current_section
                # 如果 last_digit_val == 0 且不是刚读过零 (如 "百八", 但"十五"已被处理成"一十五")
                # 这种情况理论上不应出现或已被处理，但以防万一，可视为 "一百"
                # elif not reading_zero: # 处理类似 '百八' 这种不规范但可能出现的
                #    current_section += 1 * unit # 默认是 '一'

                # 应用单位后，重置最后数字值
                last_digit_val = 0
                reading_zero = False  # 单位处理后，不再是读零状态

            elif char in _CHINESE_LARGE_UNITS:
                unit = _CHINESE_LARGE_UNITS[char]
                # 结算当前大单位(万/亿)之前的部分
                # 包括 current_section (千百十) 和 可能尾随的 last_digit_val (个位)
                section_value = current_section + last_digit_val

                # 特殊处理：如果 section_value 是 0 (例如 "万", "亿", "一千万"中万前面的部分)
                # 这意味着这个大单位前面是空的，或者是一个零，此时默认系数为 1
                if section_value == 0:
                    section_value = 1

                # 累加到总数
                total += section_value * unit

                # 重置当前段的值，为下一个大单位做准备
                current_section = 0
                last_digit_val = 0
                reading_zero = False

            # else: 无效字符已被前面检查过滤

        # 循环结束后，加上最后一部分 (最后一个大单位之后，或者没有大单位时的数值)
        total += current_section + last_digit_val

        # 对结果进行最后确认
        # 如果 total 是 0，只有当原始输入是 "零" 或 "〇" 时才返回 0，否则视为解析错误或空输入返回 None
        if total == 0:
            return 0 if all(char in ("零", "〇") for char in chinese_num_str) else None
        else:
            return total


def arabic_to_chn_num(num: int, to_upper: bool = False) -> str:
    # 节权位的位置
    unit_section_pos = 0
    chn_str = ""
    if not to_upper:
        # 单个数字转换用的数组
        chn_num_char = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
        # 节权位转换用的数组
        chn_unit_section = ["", "万", "亿", "万亿", "亿亿"]
        # 节内权位换算的数组
        chn_unit_char = ["", "十", "百", "千"]
    else:
        # 转大写
        chn_num_char = ["零", "壹", "贰", "叁", "肆", "伍", "陆", "柒", "捌", "玖"]
        chn_unit_section = ["", "万", "亿", "万亿", "亿亿"]
        chn_unit_char = ["", "拾", "佰", "仟"]
    need_zero = False

    if num == 0:
        return chn_num_char[0]

    # 节内换算的闭包
    def section_to_chn(section):
        chn_str = ""
        # 节内的位置
        unit_pos = 0
        zero = True

        while section > 0:
            v = section % 10
            if v == 0:
                if not zero:
                    zero = True
                    chn_str = chn_num_char[v] + chn_str
            else:
                zero = False
                str_insert = chn_num_char[v]
                str_insert += chn_unit_char[unit_pos]
                chn_str = str_insert + chn_str
            unit_pos += 1
            section = section // 10
        return chn_str

    while num > 0:
        section = num % 10000
        if need_zero:
            chn_str = chn_num_char[0] + chn_str
        str_insert = section_to_chn(section)
        str_insert += chn_unit_section[unit_section_pos] if section != 0 else chn_unit_section[0]
        chn_str = str_insert + chn_str
        need_zero = (section < 1000) and (section > 0)
        num = num // 10000
        unit_section_pos += 1

    if not to_upper:
        search = "一十"
        replacement = "十"
    else:
        search = "壹拾"
        replacement = "拾"
    # 处理含一十开头的（这个可根据需求处理）
    if chn_str.startswith(search):
        chn_str = replacement + chn_str[len(search) :]

    return chn_str


def arabic_to_chn_num_variant(num: str, has_lower_limit: bool = False, pad_len: int = 0) -> str:
    if has_lower_limit and len(num) < 3:  # 小于三位数的直接转为普通的中文数字
        return arabic_to_chn_num(int(num))

    if pad_len > 0:  # 高位补〇
        num = num.zfill(pad_len)

    _DIGITS = {
        "0": "〇",
        "1": "一",
        "2": "二",
        "3": "三",
        "4": "四",
        "5": "五",
        "6": "六",
        "7": "七",
        "8": "八",
        "9": "九",
    }

    result_chars = []
    for digit in num:
        result_chars.append(_DIGITS[digit])

    return "".join(result_chars)


def render_custom_markdown(text: str, extra_style: str = "") -> str:
    """
    用于渲染包含自定义规则和标准 Markdown 的文本

    Args:
        text: 包含 Markdown 和自定义语法的原始文本
        extra_style: 额外的 CSS 样式，用于自定义渲染

    Returns:
        渲染后的 HTML 字符串
    """

    html = markdown.markdown(text, extensions=["extra"])

    # 清理 HTML，移除空的 <p> 标签
    cleaned_html = re.sub(r"<p>\s*( )?\s*</p>", "", html, flags=re.IGNORECASE)

    # 读取对应主题 markdown.qss 中的固定标记，判断是否需要更换分割线的颜色
    is_dark_theme = "/* 深色主题 */" in extra_style

    if is_dark_theme:  # sigh...
        line = "─" * 60
        hr_html = (
            f'<p style="'
            f"color:white; "
            f"margin:18px 0 10px 0; "
            f"line-height:8px; "
            f"font-size:8px; "
            f"overflow:hidden; "
            f"white-space:nowrap;"
            f'">{line}</p>'
        )

        cleaned_html = re.sub(r"<hr\s*/?>", hr_html, cleaned_html, flags=re.IGNORECASE)

    extra_style = f"<style>{extra_style}</style>"

    cleaned_html = extra_style + cleaned_html

    return cleaned_html


def parse_php_config(file_path: str) -> Dict:
    """
    通过调用 PHP 子进程来解析 PHP 数组配置文件

    Args:
        file_path: PHP 配置文件的路径

    Returns:
        解析后的 Python 字典
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Config file not found: {file_path}")

    # PHP 命令：包含(include)指定的配置文件，然后将其内容用 json_encode 输出
    # php -r 'echo json_encode(include "your_file.php");'
    php_program = env_config.php_program
    escaped_path = file_path.replace("\\", "\\\\")
    command = [php_program, "-r", f'echo json_encode(include "{escaped_path}");']

    try:
        # 执行命令并捕获输出
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            creationflags=creationflags,
        )
        # PHP 输出的 JSON 字符串
        json_output = result.stdout
        # 使用 Python 的 json 模块解析
        return json.loads(json_output)

    except FileNotFoundError:
        raise RuntimeError("PHP is not installed or not in the system's PATH.")
    except subprocess.CalledProcessError as e:
        # PHP 执行出错，打印错误信息
        raise RuntimeError(f"PHP script execution failed:\n{e.stderr}")
    except json.JSONDecodeError:
        raise ValueError("Failed to decode JSON from PHP output. The PHP file might be invalid.")


def run_php_script(script_path: str, *args) -> str:
    """
    执行 PHP 脚本，返回标准输出内容

    Args:
        script_path: PHP 脚本路径
        *args: 传递给 PHP 脚本的额外命令行参数列表

    Returns:
        PHP 脚本执行的标准输出字符串
    """
    php_program = env_config.php_program
    command = [php_program, os.path.abspath(script_path).replace("\\", "\\\\")]
    command.extend(args)

    try:
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            creationflags=creationflags,
        )
        return result.stdout

    except FileNotFoundError:
        raise RuntimeError("PHP is not installed or not in the system's PATH.")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"PHP script execution failed:\n{e.stderr}")


def change_unicode_to_pcre_format(pattern_str: str) -> str:
    r"""
    将正则表达式字符串中的 Python Unicode 转义符 (u+XXXX, U+XXXXXXXX)
    转换为 QRegularExpression/PCRE 兼容的格式 (\x{...})
    """

    def python_unicode_to_pcre(match: Match) -> str:
        r"""
        regex.sub 的回调函数
        将匹配到的 u+XXXX 或 U+XXXXXXXX 转换为 \x{...} 格式
        """
        # match.group(0) 是完整的匹配项, 例如 "\\uE000"
        # 提取 'u' 或 'U' 后面的十六进制代码部分
        hex_code = match.group(0)[2:]
        # 构造成 \x{...} 格式
        return f"\\x{{{hex_code}}}"

    # 该正则表达式匹配 \uXXXX (4位十六进制) 或 \UXXXXXXXX (8位十六进制)
    # (?-i) 确保只匹配小写的 'u' 和大写的 'U'
    unicode_pattern = r"(?-i)\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}"

    # 使用 regex.sub 进行查找和替换
    return regex.sub(unicode_pattern, python_unicode_to_pcre, pattern_str)


def process_merge_lines(text: str) -> str:
    """
    处理多行文本的合并逻辑（纯字符串操作）
    支持不完整的 <p> 标签选中情况
    :param text: 需要合并的多行字符串
    :return: 合并后的单行字符串
    :raises ValueError: 当包含边界行无法合并时抛出
    """
    if not text:
        return ""

    # 1. 提取有效行数据
    target_re = regex.compile(r"^(\s*(?:\[(?:行号|匹配)：\d+\])?\s*)(.*)$")
    boundary_markers = {"※※※（上文省略）※※※", "※※※（下文省略）※※※"}
    valid_lines = []

    for line in text.splitlines():
        match = target_re.match(line)
        if not match:
            continue

        content = match.group(2).strip()

        # 检查边界行
        if any(marker in content for marker in boundary_markers):
            raise ValueError("内容包含匹配项的边界行，不可合并")

        valid_lines.append({"prefix": match.group(1), "content": content})

    if not valid_lines:
        return ""

    # 2. 灵活处理 <p> 标签（兼容部分选中）
    start_p_re = regex.compile(r"^(<p[^>]*>)\s*")
    end_p_re = regex.compile(r"\s*(</p>)$")

    p_open = ""
    p_close = ""
    contents_to_merge = []

    for i, line in enumerate(valid_lines):
        content = line["content"]

        # 处理开头的 <p> 标签：如果存在，提取后从内容中剔除
        if m_start := start_p_re.search(content):
            if i == 0:
                p_open = m_start.group(1)  # 仅保留第一行（如果有）的开头标签
            content = content[m_start.end() :]

        # 处理结尾的 </p> 标签：如果存在，提取后从内容中剔除
        if m_end := end_p_re.search(content):
            if i == len(valid_lines) - 1:
                p_close = m_end.group(1)  # 仅保留最后一行（如果有）的结尾标签
            content = content[: m_end.start()]

        contents_to_merge.append(content.strip())

    # 3. 引号处理：如果下一行以前引号开头，且当前行不以后引号或冒号结尾，则移除下一行的前引号
    if len(contents_to_merge) >= 2:
        quote_pairs_to_strip = [("”", "“"), ("’", "‘"), ("】", "【"), ("〗", "〖")]
        in_quote = {pair[1]: False for pair in quote_pairs_to_strip}

        # 检查第一行以初始化引号状态
        first_content = contents_to_merge[0]
        for end_quote, start_quote in quote_pairs_to_strip:
            if start_quote in first_content and not first_content.endswith((end_quote, "：")):
                in_quote[start_quote] = True

        # 从第二行开始处理
        for i in range(1, len(contents_to_merge)):
            original_content = contents_to_merge[i]
            modified_content = original_content

            # 如果处于开放引号状态，并且当前行以该引号开头，则移除
            for start_quote, is_open in in_quote.items():
                if is_open and modified_content.startswith(start_quote):
                    modified_content = modified_content[1:]
                    break  # 每行只处理一次

            contents_to_merge[i] = modified_content

            # 根据当前行的原始内容更新引号状态
            for end_quote, start_quote in quote_pairs_to_strip:
                if start_quote in original_content and not original_content.endswith((end_quote, "：")):
                    in_quote[start_quote] = True
                elif original_content.endswith(end_quote):
                    in_quote[start_quote] = False

    merged = "".join(contents_to_merge)

    # 4. 构建最终的替换文本：前缀 + 头标签 + 合并后的正文 + 尾标签
    first = valid_lines[0]
    new_text = f"{first['prefix']}{p_open}{merged}{p_close}"

    return new_text


def find_last_match_by_regex(
    pattern: regex.Pattern,
    text: str,
    end_pos: int,
    initial_chunk_size: int = 50000,
    alignment_marker: Optional[str] = None,
) -> Optional[regex.Match]:
    """
    在 text[0:end_pos] 范围内用正则反向查找最后一个匹配项
    反向查找，本质仍是正向查找，需要在一定范围内搜索所有匹配，取最后一个
    这里尝试采用分块向前跳跃的方式，尽量避免在长文本末尾反查时，全文查找所有匹配
    """
    curr_search_end = end_pos
    chunk_size = initial_chunk_size

    while curr_search_end > 0:
        # 计算当前块的起始位置
        curr_chunk_start = max(0, curr_search_end - chunk_size)

        # 如果提供了对齐标记（如 "【匹配项："），则尝试对齐起始点，防止匹配项被切断
        actual_start = curr_chunk_start
        if alignment_marker and curr_chunk_start > 0:
            aligned_pos = text.rfind(alignment_marker, 0, curr_chunk_start)
            if aligned_pos != -1:
                actual_start = aligned_pos

        # 在当前块内正向搜索所有匹配，取最后一个
        last_match = None
        for m in pattern.finditer(text, pos=actual_start, endpos=curr_search_end):
            last_match = m

        if last_match:
            return last_match

        # 如果已经搜到了文档开头还没找到，直接跳出
        if actual_start == 0:
            break

        # 当前块中无结果，移动到下一个块
        # 倍增 chunk_size 以减少搜索次数
        curr_search_end = actual_start
        chunk_size *= 2

    return None


# =====================================================================
# 以下两个转换函数的说明：
#
# 目的：解决 Python 和 Qt (PySide/PyQt) 之间的索引计算错位问题
#
# 原因：
# - Python (Unicode) 中，所有字符（包含 Emoji、CJK 生僻字）长度均为 1。
# - Qt (UTF-16) 中，Emoji 和 CJK 扩展区生僻字（代理对）的长度为 2！
#
# 结果：
# 如果文本在光标之前包含哪怕一个生僻字，Python 的正则 `match.span()`
# 获取的索引，直接传给 Qt 的 `setPosition()` 时，就会发生向前的偏移错位，
# 导致误删前面的正常文字，并在尾部留下残留字符（例如多出一个 >）。
#
# 方案：
# 建立“翻译桥梁”。将文本统一转为 UTF-16 字节流来计算实际长度，
# 确保 Python 处理完毕后，还原给 Qt 的坐标与 Qt 底层计算方式绝对对齐。
# =====================================================================


def qt_to_py_index(qt_idx, full_text=""):
    """将 Qt 的 UTF-16 索引转换为 Python 的字符串索引"""
    if qt_idx == 0:
        return 0
    # 截取 Qt 索引对应字节长度的 UTF-16 数据，解码后求 Python 长度
    return len(full_text.encode("utf-16-le")[: qt_idx * 2].decode("utf-16-le", errors="replace"))


def py_to_qt_index(py_idx, full_text=""):
    """将 Python 的字符串索引转换为 Qt 的 UTF-16 索引"""
    if py_idx == 0:
        return 0
    # 将 Python 字符串编码为 UTF-16 字节流，求字节数除以 2
    return len(full_text[:py_idx].encode("utf-16-le")) // 2
