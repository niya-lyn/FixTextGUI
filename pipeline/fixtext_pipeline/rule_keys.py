"""词条内容键的唯一实现（V1.1-T1.3）。

``word_states``（禁用集）与 ``vocab_bridge``（规则合成）都要按「词条内容」定位
一条规则，而 ``word_states`` 又依赖 ``vocab_bridge`` 的用户区路径推算——
若 ``vocab_bridge`` 反过来 import ``word_states`` 就成了循环依赖。

所以把键的实现单独放这里：两边都从这里 import，键的算法只有一份，
``tests/test_word_states.py`` 里「UI 侧 == 管线侧」的契约用例仍然成立
（``word_states.entry_key`` 是本模块的再导出）。
"""

from __future__ import annotations

import hashlib

#: 词条键分隔符：word 与 value 之间用 NUL，杜绝「词尾+词头」拼出歧义
ENTRY_KEY_SEP = "\x00"


def entry_key(word: str, value: str) -> str:
    """词条内容键：``sha256(word + NUL + value)`` 的十六进制。

    用内容而不是行号 / 顺序定位：词库文件重排、恢复默认都不会让禁用状态错位。
    """
    raw = (str(word) + ENTRY_KEY_SEP + str(value)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
