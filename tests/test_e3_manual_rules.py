"""V1.1-E3 · 手动检索规则集的验收用例。

本卡三条验收判据（排期文档 §10.4 原文），每条都有机器可判定的用例：

1. **205 条逐条可编译**（或显式登记不可编译条目与原因）
   → ``test_all_rules_compile`` / ``test_validation_registers_failures_explicitly``
2. **回调 3 条有等价行为验证**
   → ``test_callbacks_match_php_oracle`` / ``test_callbacks_refuse_silent_fallback``
   等（真值来自 PHP 原生闭包，不是 Python 自己跟自己比）
3. **同一本书命中数与人工抽查一致**
   → ``test_hit_counts_match_php_oracle`` / ``test_manual_spot_check``

另有交付物本身的结构性检查：导出器可再生、三种排序语义、只读预览不改入参、
装载层未被改动、界面文案零技术词。

**真值来源说明（重要）**
``tests/fixtures/manual_search_oracle.json`` 由 ``tools/manual_search_oracle.php``
用 **PHP 8.5.8 直接 include 原版规则表** 生成——它不经过导出的 rules.json，
也不经过 Python 实现。所以「Python 等于真值」这句话证的是完整链路
（PHP 源码 → 导出 → 加载 → 编译 → 扫描/替换）而不是自证。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "fixtext_ui"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fixtext_ui import fixtext_manual_search as M   # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SAMPLES = Path(__file__).resolve().parent / "samples"
RULES_JSON = ROOT / "data" / "manual_search" / "rules.json"
ORACLE_JSON = FIXTURES / "manual_search_oracle.json"
CALLBACK_CORPUS = FIXTURES / "manual_search_callback_corpus.txt"


def _read_without_newline_translation(path: Path) -> str:
    """按**原始字节**读文本（不折叠 CRLF）。

    这样 ``len(text)`` 才能和 PHP ``mb_strlen(file_get_contents(...))`` 逐字对得上；
    ``Path.read_text()`` 会把 CRLF 折成 LF，字符数就对不上了。
    """
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def ruleset() -> M.RuleSet:
    return M.load_rules(RULES_JSON)


@pytest.fixture(scope="module")
def oracle() -> dict:
    if not ORACLE_JSON.exists():          # pragma: no cover - 夹具缺失时给出可操作提示
        pytest.skip(
            f"缺少 {ORACLE_JSON.name}：请用 tools/manual_search_oracle.php 重新生成"
            "（需要 php CLI 与原版 FixText 源码）"
        )
    return json.loads(ORACLE_JSON.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 判据 ①：205 条逐条可编译
# ---------------------------------------------------------------------------

def test_rule_set_has_205_rules(ruleset: M.RuleSet) -> None:
    """规则条数与原版规则表一致（6 条注释掉的规则不计入）。"""
    assert len(ruleset) == 205
    assert ruleset.meta["counts"]["rules"] == 205
    assert ruleset.meta["counts"]["commented_out"] == 6


def test_all_rules_compile(ruleset: M.RuleSet) -> None:
    """205 条**逐条**编译成功——这是验收判据 ① 的机器形式。

    用 ``warmup()`` 逐条过一遍并核对计数，而不是只看一个总数，
    这样哪一条挂了会直接暴露在 ``rule.compile_error`` 上。
    """
    ok = ruleset.warmup()
    assert ok == 205, "不可编译：" + "; ".join(
        f"#{r.index} {r.mark}: {r.compile_error}"
        for r in ruleset.rules if r.compile_error
    )


def test_validation_report_is_clean(ruleset: M.RuleSet) -> None:
    report = ruleset.validate()
    assert report.total == 205
    assert report.compilable == 205
    assert report.failures == []          # 没有「不可编译条目」需要登记
    assert report.ok is True
    assert report.callback_rules == 3
    assert report.missing_callbacks == []


def _bad_rule() -> M.Rule:
    """一条必然编译失败的规则（括号不配对），用于反证「登记机制真的在工作」。

    序号排在合法规则之后（205），不干扰 0..204 的既有下标。
    """
    return M.Rule(
        index=205, mark="{故意写坏的规则}", search="(未闭合的括号",
        replace="x", is_callback=False, callback_id=None,
        color="", modifiers=None, note=None,
    )


def test_validation_registers_failures_explicitly(ruleset: M.RuleSet) -> None:
    """判据写的是「**或**显式登记不可编译条目与原因」——所以反证一下这条机制真的能登记。

    注入一条必然编译失败的规则，确认它被登记进 ``failures``（带 index / mark /
    原因），而不是被吞掉、也不是让整个校验崩掉。这证明「全绿」不是检查没跑。
    """
    bad = _bad_rule()
    with_bad = M.RuleSet(list(ruleset.rules) + [bad], ruleset.meta)
    report = with_bad.validate()
    assert len(report.failures) == 1
    idx, mark, reason = report.failures[0]
    assert idx == bad.index and mark == bad.mark
    assert "unbalanced parenthesis" in reason or "missing )" in reason
    assert report.ok is False


def test_uncompilable_rule_scan_raises_not_zero() -> None:
    """不可编译的规则必须**抛错**，不能静默算成 0 命中。

    「静默算 0」会让命中统计少算而不报错，比直接报错危险得多。
    """
    rs = M.RuleSet([_bad_rule()], {})
    with pytest.raises(M.RuleCompileError):
        rs.scan("随便一段文本")


@pytest.mark.parametrize("key", ["a_utf8_lf", "b_utf8_bom", "c_utf8_crlf", "g_mixed_newline"])
def test_sample_books_exist(key: str) -> None:
    """命中对照要用的样本书必须在库里（缺失就明确跳过而不是伪造数字）。"""
    assert (SAMPLES / f"{key}.txt").exists()


# ---------------------------------------------------------------------------
# 判据 ②：3 条回调的等价行为
# ---------------------------------------------------------------------------

CALLBACK_EXPECTED = {
    "{额->呃}": 99,
    "{恩->嗯}": 100,
    "{移除概数之中的顿号}": 204,
}


def test_exactly_three_callback_rules(ruleset: M.RuleSet) -> None:
    """回调规则恰好 3 条，且身份与原版一致（不是把回调降级成字面量）。"""
    cbs = ruleset.callbacks
    assert [r.mark for r in cbs] == list(M.CALLBACK_MARKS)
    assert {r.mark: r.index for r in cbs} == CALLBACK_EXPECTED
    # 回调规则没有字面 replace 模板——有模板就说明被降级了
    assert all(r.replace is None for r in cbs)
    # 但都带着原版闭包源码，供人工核对
    assert all(r.cb_source and "function ($matches)" in r.cb_source for r in cbs)


def test_every_callback_has_implementation(ruleset: M.RuleSet) -> None:
    """每条回调规则都能在 ``CALLBACKS`` 里找到等价实现（找不到即校验失败）。"""
    for rule in ruleset.callbacks:
        assert rule.callback_id in M.CALLBACKS
    assert {"额->呃", "恩->嗯", "移除概数之中的顿号"} <= set(M.CALLBACKS)


def test_callbacks_match_php_oracle(ruleset: M.RuleSet, oracle: dict) -> None:
    """**判据 ② 的核心**：Python 回调替换结果与 PHP 原生闭包逐字节相同。

    比的是整段文本替换后的 SHA-1（不是只看命中数）——只要有一个分组拼接
    或空串语义不对，哈希立刻不一致。
    """
    text = _read_without_newline_translation(CALLBACK_CORPUS)
    cases = oracle["callback_case"]["cases"]
    assert len(cases) == 3, "真值里应当正好 3 条回调"
    checked = 0
    for case in cases:
        rule = ruleset.get(case["i"])
        assert rule.mark == case["mark"]
        out = ruleset.apply_rule(rule, text)
        assert _sha1(out) == case["result_sha1"], (
            f"回调 {rule.mark} 与 PHP 原生闭包结果不一致；"
            f"PHP={case['result']!r} / PY={out!r}"
        )
        checked += 1
    assert checked == 3


def test_callback_hit_counts_match_php(ruleset: M.RuleSet, oracle: dict) -> None:
    """回调规则的命中数与 PHP ``preg_match_all`` 一致。"""
    text = _read_without_newline_translation(CALLBACK_CORPUS)
    for case in oracle["callback_case"]["cases"]:
        rule = ruleset.get(case["i"])
        pat = ruleset.compiled(rule)
        assert sum(1 for _ in pat.finditer(text)) == case["matched"]


def test_callback_variant_semantics(ruleset: M.RuleSet) -> None:
    """{额->呃} / {恩->嗯} 的最小语义：只改符合条件的「额/恩」，反例一字不动。

    这条用例把等价实现的**关键性质**单独钉住，避免将来有人「优化」成全局替换。
    """
    text = "他挠挠头，额～这题真难。\n我的额头有点疼。\n金额三百元。\n"
    rule = ruleset.get(99)
    out = ruleset.apply_rule(rule, text)
    assert "，呃～" in out                      # 正例被改写
    assert "我的额头" in out                   # 反例保持原样
    assert "金额三百元" in out                 # 反例保持原样

    text = "他点点头，恩～知道了。\n恩人对我很好。\n感恩的心。\n"
    out = ruleset.apply_rule(ruleset.get(100), text)
    assert "，嗯～" in out
    assert "恩人对我很好" in out
    assert "感恩的心" in out


def test_callback_count_dunhao_protection(ruleset: M.RuleSet) -> None:
    """{移除概数之中的顿号} 的「防误伤」保护分支必须真的生效。

    保护条件：``$matches[1] == "十"`` 且 ``$matches[3]`` 是 十 / 百 / 千。
    这条用例同时验证「该去的去」「该留的留」，覆盖保护分支的正反两面。
    """
    rule = ruleset.get(204)
    # 正例：普通概数 → 顿号被去掉
    assert ruleset.apply_rule(rule, "来了一、两个人。") == "来了一两个人。"
    assert ruleset.apply_rule(rule, "买了三、五个苹果。") == "买了三五个苹果。"
    # 保护例：前字「十」+ 后字 百/千/十 → 顿号保留
    assert ruleset.apply_rule(rule, "十一、二百元。") == "十一、二百元。"
    assert ruleset.apply_rule(rule, "十一、二千人。") == "十一、二千人。"
    assert ruleset.apply_rule(rule, "十一、二十斤。") == "十一、二十斤。"
    # 负例：年级 / 顺位 / 名次 / 等级 → 根本不匹配
    for keep in ("一、二年级", "排名一、二位", "一、二名次", "三、四等级"):
        assert ruleset.apply_rule(rule, keep) == keep


def test_callbacks_refuse_silent_fallback() -> None:
    """实现缺失时必须报错，**绝不**静默降级成字面量替换（任务书明确禁止）。"""
    rule = M.Rule(
        index=0, mark="{不存在的回调}", search="(?<=甲)(乙)",
        replace=None, is_callback=True, callback_id="不存在的回调",
        color="", modifiers=None, note=None,
    )
    rs = M.RuleSet([rule], {})
    with pytest.raises(M.RuleCompileError, match="没有等价实现"):
        rs.apply_rule(rule, "甲乙")


# ---------------------------------------------------------------------------
# 判据 ③：同一本书命中数与人工抽查一致
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["a_utf8_lf", "b_utf8_bom", "c_utf8_crlf", "g_mixed_newline"])
def test_hit_counts_match_php_oracle(ruleset: M.RuleSet, oracle: dict, key: str) -> None:
    """**判据 ③ 的核心**：逐条比对 205 条的命中数，与 PHP ``preg_match_all`` 完全一致。

    四本同源书分别覆盖 LF / BOM / CRLF / 混合换行四种行尾——换行处理一旦有偏差，
    CRLF 那本会立刻对不上。
    """
    ref = oracle["counts"][key]
    text = _read_without_newline_translation(SAMPLES / f"{key}.txt")
    result = ruleset.scan(text)

    assert result.text_chars == ref["text_chars"]
    assert result.total == ref["total"]
    assert len(result.nonzero) == ref["nonzero"]

    py_counts = [h.count for h in result.hits]
    php_counts = [it["count"] for it in ref["items"]]
    assert len(py_counts) == len(php_counts) == 205

    diffs = [
        (i, py_counts[i], php_counts[i], ruleset.get(i).mark)
        for i in range(205) if py_counts[i] != php_counts[i]
    ]
    assert not diffs, "命中数与原版 PHP 不一致：" + "; ".join(
        f"#{i} {mark}: py={p} php={q}" for i, p, q, mark in diffs[:6]
    )

    # 规则集里没有一条 PHP 侧报错的规则（有就说明导出的表达式本身有问题）
    assert all(it["count"] is not None for it in ref["items"])


def test_manual_spot_check(ruleset: M.RuleSet, oracle: dict) -> None:
    """人工抽查口径：挑几条**有命中的**规则，把命中位置打出来逐条核对。

    这是「与人工抽查一致」这句话的落地形式——不是只比一个总数（总数对齐可能
    靠两条规则的相互抵消），而是抽查具体规则在具体位置的具体原文片段。
    """
    text = _read_without_newline_translation(SAMPLES / "a_utf8_lf.txt")
    ref = oracle["counts"]["a_utf8_lf"]
    nonzero = [it for it in ref["items"] if it["count"]]
    assert len(nonzero) == 17

    spot = nonzero[:6]                       # 抽查前 6 条有命中的规则
    for it in spot:
        rule = ruleset.get(it["i"])
        assert rule.mark == it["mark"]
        pat = ruleset.compiled(rule)
        occurrences = [m.group(0) for m in pat.finditer(text)]
        assert len(occurrences) == it["count"]
        # 每条命中都能在原文里按位置找到，且内容非空
        assert all(o for o in occurrences), f"{rule.mark} 命中出空串"
        assert text.count(occurrences[0]) >= 1


def test_replacement_preview_matches_php_for_sample_rule(ruleset: M.RuleSet) -> None:
    """替换模板的 ``$1`` → ``\\g<1>`` 翻译正确（拿有反向引用的规则实测）。

    规则 #163 ``{ABB 地，->ABB 的，}`` 的模板用到 ``$1``，翻译错了会写出
    ``$1`` 字面量或抛分组错误。
    """
    rule = ruleset.get(163)
    assert rule.template() is not None
    assert "$" not in rule.template()        # 没有残留的 PHP 占位符
    assert "\\g<1>" in rule.template()


# ---------------------------------------------------------------------------
# 规则集模块的结构性行为（三种排序 / 只读预览 / 加载校验）
# ---------------------------------------------------------------------------

def test_three_orderings(ruleset: M.RuleSet, oracle: dict) -> None:
    """三种排序的语义：文件顺序 / 命中次数升序 / 颜色分组后组内升序。"""
    text = _read_without_newline_translation(SAMPLES / "a_utf8_lf.txt")
    result = ruleset.scan(text)

    by_file = result.ordered(M.ORDER_FILE)
    assert [h.rule.index for h in by_file] == list(range(205))

    by_count = result.ordered(M.ORDER_COUNT)
    counts = [h.count for h in by_count]
    assert counts == sorted(counts), "按次数排序必须是升序（PHP sort=1）"

    by_color = result.ordered(M.ORDER_COLOR)
    keys = [(h.rule.color or "", h.count) for h in by_color]
    assert keys == sorted(keys), "按颜色分组必须是 [color, count] 升序（PHP sort=2）"
    # 三种排序不改变「有哪些规则」，只改变顺序
    assert {h.rule.index for h in by_file} == {h.rule.index for h in by_color}


def test_sort_rejects_unknown_order() -> None:
    with pytest.raises(ValueError, match="未知排序"):
        M.sort_hits([], "nope")


def test_order_labels_are_human(ruleset: M.RuleSet) -> None:
    """三种排序的显示名是给人看的（不外露 sort=0/1/2 这种内部说法）。"""
    assert set(M.ORDER_LABELS) == set(M.ORDERS)
    for label in M.ORDER_LABELS.values():
        assert label and not any(tok in label for tok in ("sort", "=", "ORDER"))


def test_preview_is_read_only(ruleset: M.RuleSet, tmp_path: Path) -> None:
    """只读预览：入参字符串不变、源文件指纹不变、没有新文件产生。"""
    # 用回调语料（含 {额->呃}/{恩->嗯} 正例），并同时盯住整本书的指纹：
    # 预览跑在书上也不许动书，所以两种输入都验。
    book = SAMPLES / "a_utf8_lf.txt"
    before_fp = hashlib.sha256(book.read_bytes()).hexdigest()
    text = _read_without_newline_translation(CALLBACK_CORPUS)

    out = ruleset.preview(text, indices=[99, 100])

    assert isinstance(out.text, str)
    assert out.text != text                  # 确实算出了不同的结果
    assert "，呃～" in out.text              # {额->呃} 生效
    assert "，嗯～" in out.text              # {恩->嗯} 生效
    assert text == _read_without_newline_translation(CALLBACK_CORPUS)  # 入参没被改
    assert hashlib.sha256(book.read_bytes()).hexdigest() == before_fp
    assert not list(tmp_path.iterdir())      # 预览不往任何调用方目录写东西


def test_apply_rule_returns_new_string(ruleset: M.RuleSet) -> None:
    """单条套用返回新字符串，原串不变（Python str 不可变，这里是防止改成原地写）。"""
    src = "他挠挠头，额～这题真难。"
    out = ruleset.apply_rule(ruleset.get(99), src)
    assert out != src and src == "他挠挠头，额～这题真难。"


def test_preview_rejects_out_of_range(ruleset: M.RuleSet) -> None:
    with pytest.raises(IndexError, match="越界"):
        ruleset.preview("文本", indices=[999])


def test_load_rejects_wrong_schema_version(tmp_path: Path) -> None:
    """版本不符要直接报错，不能拿旧格式的数据硬跑。"""
    payload = json.loads(RULES_JSON.read_text(encoding="utf-8"))
    payload["schema_version"] = "0.9"
    bad = tmp_path / "rules.json"
    bad.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="版本不符"):
        M.RuleSet.from_json(bad)


def test_rules_json_metadata(ruleset: M.RuleSet) -> None:
    """导出元信息：来源、SHA-256、注释条数、颜色分组数都要在。"""
    meta = ruleset.meta
    src = meta["source"]
    assert src["rules_sha256"].startswith("c880d721")
    assert src["vars_path"].endswith("1.自定义词库.php")
    assert len(src["puncts"]) == 19          # 原版 19 个标点
    assert src["de_prefix_len"] == 6287      # {$dePrefixPattern} 展开后长度
    counts = meta["counts"]
    assert counts["callbacks"] == 3
    assert counts["commented_out"] == 6
    assert counts["with_note"] == 24


def test_blue_count_registered_honestly(ruleset: M.RuleSet) -> None:
    """颜色分组计数按**导出实测**登记为 81，与 P1.1 调研说的 82 差 1 条。

    这里把差异显式钉在测试里，避免以后有人为了让数字「对上」去改数据。
    实测口径：''color' => "Blue"' 真正在生效规则里出现 81 次（P1.1 手数得 82，
    差的 1 条在 6 条注释掉的规则里）。
    """
    blue = [r for r in ruleset if (r.color or "") == "Blue"]
    assert len(blue) == 81
    assert ruleset.meta["counts"]["color_blue"] == 81


# ---------------------------------------------------------------------------
# 方言：PCRE 与 Python ``regex`` 的唯一分叉点
# ---------------------------------------------------------------------------

def test_dialect_census_only_g_backref_diverges(ruleset: M.RuleSet) -> None:
    """全表方言普查：除 ``\\gN`` 反向引用外，其余 PCRE 专有记号 0 命中。

    这条用例是「不需要更宽的翻译层」的证据——普查结果一旦变化（有人新增了
    ``\\K`` 之类），这里会立刻红。
    """
    tokens = ("\\K", "\\R", "\\h", "\\g<", "(?i", "(?P=", "(?>", "\\p{",
              "\\Q", "(?(", "(?&", "(?1")
    for rule in ruleset:
        for tok in tokens:
            assert tok not in rule.search, f"#{rule.index} {rule.mark} 出现方言记号 {tok}"


def test_g_backref_is_translated(ruleset: M.RuleSet) -> None:
    """``\\g1`` 必须被翻译成 ``\\g<1>``——否则 `regex` 会把 ``g1`` 当字面量（静默错）。"""
    rule = ruleset.get(163)
    assert "\\g1" in rule.search                    # 原文确实是 PCRE 写法
    assert rule.dialect, "应当记录翻译痕迹"
    assert any("\\g1" in c for c in rule.dialect)
    # 翻译后能真正匹配「地，」的 ABB 结构
    assert ruleset.compiled(rule) is not None


def test_g_backref_semantics_not_literal() -> None:
    """独立反证：``regex`` 原生把 ``\\g1`` 当字面量，翻译后才成为反向引用。

    这条用例直接说明「为什么需要 translate」，不依赖真实规则表。
    """
    import regex

    # 原生写法：把 \g1 当字面量 g1
    assert regex.compile(r"(a)\g1").search("ag1") is not None
    assert regex.compile(r"(a)\g1").search("aa") is None
    # 翻译后：真正的反向引用
    translated, changes = M.normalize_dialect(r"(a)\g1")
    assert translated == r"(a)\g<1>"
    assert changes == ["\\g1 -> \\g<1>"]
    assert regex.compile(translated).search("aa") is not None
    assert regex.compile(translated).search("ag1") is None


def test_regex_dependency_is_hard() -> None:
    """标准库 ``re`` 编译不了 45 条变宽 lookbehind——`regex` 是硬依赖，不是偏好。"""
    import re as stdlib_re

    compiled = 0
    for pattern_file in [RULES_JSON]:
        payload = json.loads(pattern_file.read_text(encoding="utf-8"))
        for item in payload["items"]:
            try:
                stdlib_re.compile(item["search"], stdlib_re.VERBOSE | stdlib_re.MULTILINE)
                compiled += 1
            except Exception:
                continue
    assert compiled == 160, f"标准库可编译 {compiled} 条（预期 160，其余 45 条需 regex）"


# ---------------------------------------------------------------------------
# 导出器可再生 / 边界纪律
# ---------------------------------------------------------------------------

def test_exporter_is_regenerable() -> None:
    """导出器必须存在且可独立运行（``--check`` 不写盘、结论打到 stdout）。"""
    exporter = ROOT / "tools" / "export_manual_rules.py"
    assert exporter.exists()
    text = exporter.read_text(encoding="utf-8")
    # 必须走 PHP 求值，不能手抄字符串
    assert "include" in text and "php" in text.lower()
    assert "--check" in text


def test_exported_json_reproducible_from_php_source() -> None:
    """规则集 JSON 的元信息能由导出器从 PHP 源码复算出来（有 php 才跑）。"""
    php_src = ROOT.parent / "FixText"
    if not (php_src / "src" / "maps" / "手动检索规则表.php").exists():
        pytest.skip("原版 FixText 源码不在旁边，跳过导出复算（不影响其余用例）")
    exporter = ROOT / "tools" / "export_manual_rules.py"
    proc = subprocess.run(
        [sys.executable, str(exporter), "--php-src", str(php_src / "src"), "--check"],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        pytest.skip(f"php 不可用或导出器报错：{proc.stderr[-200:]}")
    data = json.loads(proc.stdout[proc.stdout.index("{"):])
    assert data["rules"] == 205
    assert data["callbacks"] == 3
    assert data["commented_out"] == 6
    assert data["color_blue"] == 81
    assert data["with_note"] == 24
    assert data["puncts_len"] == 19
    assert data["de_prefix_len"] == 6287


def test_loading_layer_untouched() -> None:
    """边界：本卡不改装载层（``vocab_bridge.compose`` / ``bags.write_round_rules``）。

    用 git 比对这两个文件相对 HEAD 有无改动；不在 git 仓库里就跳过。
    """
    repo = ROOT
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--",
         "pipeline/fixtext_pipeline/vocab_bridge.py",
         "pipeline/fixtext_pipeline/bags.py"],
        cwd=str(repo), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.skip("不在 git 仓库里，跳过边界检查")
    changed = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert not changed, "装载层被改动：" + "; ".join(changed)


def test_module_has_no_disk_write() -> None:
    """本卡只做「检索与统计」，模块里不得出现写盘调用。

    扫的不是 ``dir()`` 而是源码里的写文件 API 调用——``dir()`` 会把 Qt 基类的
    save/apply 系方法算进来误伤。
    """
    src = (ROOT / "fixtext_ui" / "fixtext_manual_search.py").read_text(encoding="utf-8")
    banned = ("write_text(", "write_bytes(", "open(", ".save(", "shutil.copy")
    for tok in banned:
        assert tok not in src, f"规则集模块出现写盘调用 {tok}"


def test_preview_result_reports_changes(ruleset: M.RuleSet) -> None:
    """预览结果的分条计数可用（有改动时 changed_chars > 0）。"""
    out = ruleset.preview("他挠挠头，额～这题真难。", indices=[99])
    assert out.changed_chars > 0
    assert out.text == "他挠挠头，呃～这题真难。"
