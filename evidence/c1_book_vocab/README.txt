V1.1-C1 dev 单提交（基线父提交 fc28253）。
evidence 落盘时间晚于代码改动完成时间。
新测试: 28 passed (c1_new_tests.log)
受影响子集: 91 passed, 3 skipped, 1 failed (c1_affected_subset.log)
其中 1 failed 为 F3 既有失败 test_t37_vocab_bridge.py::test_custom_word_takes_effect_in_real_correction
(KeyError applied_words，git stash 验证未改动基线同样失败，详见实现说明 md)
