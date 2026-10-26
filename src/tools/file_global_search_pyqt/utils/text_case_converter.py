import regex
from typing import List, Optional


class TextCaseConverter:
    """
    一个用于转换文本大小写的工具类
    它支持以下模式：
    1. 英文首字母大写
    2. 所有英文单词转为小写
    3. 所有英文单词转为大写
    4. 只修正特定词组的大小写
    5. 英文首字母大写（每个单词）
    """

    @classmethod
    def change_case_in_text(
        cls, content: str, mode: int, fixed_case_words: List[str], is_html_file: bool = True
    ) -> str:
        """
        主函数，根据模式对文本进行大小写转换

        Args:
            content: 原始文本
            mode: 转换模式 (1-5)
            fixed_case_words: 用于模式 4 的固定词组列表
            is_html_file: 内容是否为 HTML，影响边界判断

        Returns:
            处理后的文本
        """
        processed_content = content

        # 模式 1, 2, 3: 应用通用的大小写转换规则
        if mode in [1, 2, 3, 5]:
            processed_content = cls._apply_general_case_change(processed_content, mode, is_html_file)

        # 模式 4: 应用固定词组的大小写修正，如 "Iphone" -> "iPhone"
        if mode in [4]:
            processed_content = cls._apply_fixed_word_case(processed_content, fixed_case_words)

        return processed_content

    @classmethod
    def _apply_general_case_change(cls, content: str, mode: int, is_html_file: bool) -> str:
        """
        应用通用的大小写转换 (首字母大写, 全部小写, 全部大写)

        Args:
            content: 要处理的文本内容
            mode: 转换模式 (1, 2 或 3)
            is_html_file: 内容是否为 HTML 文件

        Returns:
            转换后的文本内容
        """

        # 1. 构建主匹配模式 (包含单词边界或不包含)
        main_pattern = "([a-zA-Z0-9]+)"
        if mode not in [2, 3, 5]:
            # 模式 1 或 4，需要复杂的前缀来确定单词边界
            prefix = r"(?<!(?<![卷章回节篇话]) |[a-zA-Z\d@.,’'])"  # HTML 文件的复杂边界
            main_pattern = f"{prefix}{main_pattern}"

        # 2. 根据文件类型，用 HTML 标签跳过逻辑进行最终包装
        if is_html_file:
            # 对于 HTML 文件，在主模式前加上跳过逻辑
            final_pattern_str = f"<[^>]*>(*SKIP)(*F)|{main_pattern}"
        else:
            # 对于纯文本，直接使用主模式
            final_pattern_str = main_pattern

        pattern = regex.compile(final_pattern_str, flags=regex.MULTILINE)

        def replacer(match):
            word = match.group(1)
            if mode == 1:
                return cls._ucfirst(word)  # 只大写第一个字母，不改变后续字母的大小写
                # return word.capitalize() # 大写第一个字母的同时将后续字母改为小写
            elif mode == 2:
                return word.lower()
            elif mode == 3:
                return word.upper()
            elif mode == 5:
                # 将每个单词的首字母都大写
                return " ".join(cls._ucfirst(w) for w in word.split(" "))
            return word

        return pattern.sub(replacer, content)

    @classmethod
    def _apply_fixed_word_case(cls, content: str, fixed_case_words: List[str]) -> str:
        """
        应用固定词组的大小写修正（例如：iphone -> iPhone）

        Args:
            content: 要处理的文本内容
            fixed_case_words: 需要修正的单词列表

        Returns:
            修正后的文本内容
        """
        if not fixed_case_words:
            return content

        # 1. 构建动态正则表达式
        fixed_pattern_str = cls._build_fixed_words_pattern(fixed_case_words)
        if fixed_pattern_str is None:
            return content

        fixed_pattern = regex.compile(fixed_pattern_str, flags=regex.IGNORECASE | regex.MULTILINE)

        # 2. 创建大小写不敏感的映射表 (key 为小写，value 为正确的大小写)
        fixed_map = {word.lower(): word for word in fixed_case_words}

        # 3. 执行替换
        # 使用 lambda 函数进行回调，查找小写 key 并替换为正确大小写的 value
        return fixed_pattern.sub(lambda m: fixed_map.get(m.group(1).lower(), m.group(1)), content)

    @classmethod
    def _ucfirst(cls, s: str) -> str:
        """
        ucfirst 的 Python 实现，只大写第一个字符，不改变后面字符的大小写
        Python 内置的 .capitalize() 会把其余部分也转为小写
        """
        if not s:
            return ""
        return s[0].upper() + s[1:]

    @classmethod
    def _build_fixed_words_pattern(cls, words: List[str]) -> Optional[str]:
        """
        根据单词列表构建一个复杂的正则表达式
        这个正则能处理普通单词和以【.&-】等特殊字符开头的单词的不同边界要求

        Args:
            words: 单词列表

        Returns:
            构建好的正则表达式字符串，如果列表为空则返回 None
        """
        if not words:
            return None

        # 长单词优先匹配，防止 "id=" 被 "ID" 这样的部分匹配优先捕获
        words.sort(key=len, reverse=True)

        special_prefix_words = []
        normal_words = []

        # 定义特殊前缀
        SPECIAL_PREFIXES = (".", "-", "#", "&")

        for word in words:
            if word.startswith(SPECIAL_PREFIXES):
                special_prefix_words.append(regex.escape(word))
            else:
                normal_words.append(regex.escape(word))

        pattern_clauses = []

        # 为普通单词创建带负向后行断言的子模式
        if normal_words:
            pattern_clauses.append(f"(?<![-<\\/a-zA-Z])({'|'.join(normal_words)})")

        # 为以 .&- 等特殊字符开头的单词创建不带该断言的子模式
        if special_prefix_words:
            pattern_clauses.append(f"({'|'.join(special_prefix_words)})")

        if not pattern_clauses:
            return None

        # 使用 "分支重置组" (?|...) 将所有子模式合并
        # 这能确保无论哪个分支匹配成功，捕获的单词总是在捕获组 m.group(1) 中
        # 最后加上统一的负向先行断言，确保匹配的后面不是这些字符
        #
        # 示例生成的模式：
        # (?|(?<![-<\\/a-zA-Z])(YouTube|iPhone|iMac)|(\\.cn|\\.com))(?![a-zA-Z]|[\"']?\\/?>)
        return f"(?|{'|'.join(pattern_clauses)})(?![a-zA-Z]|[\"']?\\/?>)"
