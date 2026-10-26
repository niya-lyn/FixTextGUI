from dataclasses import dataclass
from typing import Optional, List
import regex


@dataclass
class SearchResult:
    """封装单次导航搜索的结果"""

    # found_match 和 all_matches 均有值，说明缓存有效，直接返回匹配结果
    # found_match 有值且 all_matches 无值，说明文本有变更，需要重建缓存，同时将 found_match 直接展示
    # found_match 和 all_matches 均无值，说明没有匹配结果，下一步可能进行回绕，如继续无值则返回
    found_match: Optional[regex.Match]
    all_matches: List[regex.Match]


@dataclass
class ReplaceResult:
    """封装文本替换的结果"""

    new_text: str
    error_msg: str
    success: bool
