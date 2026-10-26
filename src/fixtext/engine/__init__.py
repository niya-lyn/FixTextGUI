"""替换引擎层：Go 子进程后端与 Python greedy 引擎的归位目录。

骨架阶段为空。约定（写入评审门禁）：
1. 引擎实现不得依赖 flashtext，也不得使用 pyahocorasick 的 iter_long；
2. Go 引擎为默认引擎，Python greedy 为可选引擎与降级路径，两者的替换语义
   以排期文档 3.1 记录的 Go 现状为准（first-wins、失败前进 1 字符、命中后跳到匹配结束、不重叠、两趟）。
"""
