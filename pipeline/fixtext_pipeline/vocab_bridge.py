"""
FixText V1 · 自定义词库 → 替换规则桥接（M3-T3.7）
==================================================

M3 独立质检 B 册的 P0：用户在「我的词库」里新增 / 合并 / 删除自定义词之后，
下一次校正是**不生效**的——因为替换阶段只读随包发布的
``data/rules/before.json`` + ``after.json``，而自定义词存在
``<包根>/workspace/vocab/custom_vocab.json``，两者之间没有任何桥接。

本模块补上这道桥，规则是硬的：

* **随包发布的词库原件只读**：``data/rules/*.json`` 一个字节都不改写，
  这里只做"读"。
* **派生物落 workspace**：每次运行前把「当前生效的通用词库 + 自定义词」
  合成为一份派生规则，写在用户区（``<包根>/workspace/vocab/derived_rules/``），
  替换阶段读的就是这份派生文件。
* **合成结果稳定可复现**：同一份输入永远得到同样的字节，于是引擎指纹里
  只要纳入派生文件与合成键的 sha，规则一改指纹必变，不会误判缓存命中。

合成语义（**自定义词优先**）
----------------------------
引擎按规则数组的先后顺序做前缀匹配（前一条命中就不再尝试后面的），所以数组
顺序就是优先级。派生文件的排列是：

1. **自定义词整体前置**，且自定义词之间**长词优先**（按原词长度降序、同长度按
   词条号升序），于是用户明确加的长词不会被内置短词抢先吃掉；
2. 其后原样接上通用词库，内置规则之间的相对顺序一个都不动。

因此用户加「萧衍 → 萧彦」这类词，一定能在下一趟替换里命中；而内置词库
304,255 条的既有行为（含替换命中数）在自定义词为空时**逐字节不变**——
空自定义词时派生文件内容与出厂内容完全一致，这是可自证的。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable

from .rule_keys import entry_key
from .book_vocab import (OVERLAY_POLICY, OVERLAY_POLICY_NOTE, book_excluded_sha,
                         resolve_excluded)

#: 派生规则文件名（与出厂同名，但落在用户区，不是同一棵树）
DERIVED_BEFORE = "before.json"
DERIVED_AFTER = "after.json"
DERIVED_META = "derived_meta.json"

#: workspace 下的派生目录名（放在「我的词库」旁边的子目录里）
DERIVED_SUBDIR = "derived_rules"


class DerivedRulesError(RuntimeError):
    """派生规则无法生成（调用方应降级为「用随包词库」并如实标注）。"""


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except (OSError, ValueError):
        return None


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".dfr-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_string_array(path: Path, label: str) -> list[str]:
    raw = _read_bytes(path)
    if raw is None:
        raise DerivedRulesError(f"{label}不存在或读不到：{path.name}")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DerivedRulesError(f"{label}不是合法规则文件：{path.name}（{type(exc).__name__}）") from exc
    if not isinstance(data, list) or any(not isinstance(x, str) for x in data):
        raise DerivedRulesError(f"{label}的顶层不是字符串数组：{path.name}")
    return data


# ---------------------------------------------------------------------------
# 读自定义词
# ---------------------------------------------------------------------------

def load_custom_entries(path: Path | str) -> tuple[list[dict], str]:
    """读自定义词库；返回 (词条列表, 错误说明)。

    读不到 / 解析不了时**不抛异常**：校正不该因为词库文件坏了就跑不起来，
    调用方按"没有自定义词"继续，并把 ``error`` 如实写进运行摘要。
    """
    p = Path(path)
    raw = _read_bytes(p)
    if raw is None:
        return [], ""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return [], f"自定义词库无法解析（{type(exc).__name__}），本次按空词库处理"
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [], "自定义词库结构异常，本次按空词库处理"
    return [e for e in entries if isinstance(e, dict)], ""


# ---------------------------------------------------------------------------
# 合成
# ---------------------------------------------------------------------------

def compose(before: Iterable[str], after: Iterable[str],
            entries: Iterable[dict],
            disabled_keys: Iterable[str] | None = None,
            *, book_excluded_keys: Iterable[str] | None = None,
            book_id: str = "") -> dict:
    """把通用词库与自定义词合成为一份派生规则（纯计算，不落盘）。

    ``disabled_keys`` 是**全局有效禁用集**（词条内容键
    ``sha256(word+NUL+value)``，见 :mod:`rule_keys`）。传了它就按内容键把
    两侧命中的规则整条剔除——**出厂侧与自定义侧一视同仁**：用户在词库里点了
    「禁用」，这条词条就既不占住原词、也不产生替换，跟它来自出厂词库还是
    自己加的无关。

    ``book_excluded_keys`` 是**按书排除集**（V1.1-C1，见 :mod:`book_vocab`），
    同一道过滤、同一个循环里生效——按卡约定，装载层只许有这一处过滤入口，
    另造第二条路径即违规。两层取**并集**，按书层**不得抵消**全局禁用：
    同一条同时命中时按全局禁用记账（``source="global"``）并计入
    ``overlap``。传 ``None`` / 空集时输出与不带按书层**逐字节一致**。

    不传 ``disabled_keys`` / ``book_excluded_keys`` 等价于空集——旧调用方的
    行为逐字节不变。注意这跟「没接过滤」在**统计字段**上是可区分的
    （``disabled_applied`` / ``disabled_custom`` 会如实给出 0 与被检查的条数）。

    返回 ``before`` / ``after`` 两个等长数组与一份统计，统计里的每个"跳过"
    都带原因与来源——不静默丢条，也不把两种排除混成一个数字。
    """
    base_before = list(before)
    base_after = list(after)
    if len(base_before) != len(base_after):
        raise DerivedRulesError(
            f"通用词库两侧条数不一致（{len(base_before)} vs {len(base_after)}）")
    if not base_before:
        raise DerivedRulesError("通用词库为空，无法生成替换规则")

    off = frozenset(disabled_keys or ())
    book_off = frozenset(book_excluded_keys or ())
    # 叠加判定只在这里算一次（:func:`book_vocab.resolve_excluded` 是唯一权威，
    # 也是单测直接核对的那个函数）。并集是真正生效的排除集；两层各自命中多少
    # 单独记账，便于证据逐条核对。
    overlay = resolve_excluded(off, book_off)
    union_off = overlay["effective"]
    sources = overlay["sources"]

    # ---- 1. 先过滤出厂侧：命中排除键的规则整条不进派生文件 ----
    kept_base_before: list[str] = []
    kept_base_after: list[str] = []
    disabled_base: list[dict] = []          # 全局禁用命中（含两层同时命中）
    book_base: list[dict] = []              # 仅按书排除命中
    overlap_base = 0
    for w, v in zip(base_before, base_after):
        key = entry_key(w, v)
        if union_off and key in union_off:
            if sources.get(key, "") in ("global", "both"):
                both = sources.get(key) == "both"
                overlap_base += 1 if both else 0
                disabled_base.append(dict(
                    word=w, value=v,
                    reason=("该词条在词库里被禁用，且本书也排除了它" if both
                            else "该词条在词库里被禁用"),
                    source="global"))
            else:
                book_base.append(dict(
                    word=w, value=v,
                    reason="本书的按书词库排除了这条词条",
                    source="book"))
            continue
        kept_base_before.append(w)
        kept_base_after.append(v)

    picked: list[tuple[str, str, int]] = []
    skipped_empty: list[dict] = []
    skipped_identity: list[dict] = []
    skipped_duplicate: list[dict] = []
    disabled_custom: list[dict] = []
    book_custom: list[dict] = []
    overlap_custom = 0
    seen: dict[str, dict] = {}

    # 长词优先：同前缀时先给长词机会，避免被短自定义词整段吃掉
    ordered = sorted(
        (e for e in entries if isinstance(e, dict)),
        key=lambda e: (-len(str(e.get("word") or "").strip()),
                       int(e.get("id") or 0) if str(e.get("id") or "0").lstrip("-").isdigit() else 0),
    )

    for e in ordered:
        word = str(e.get("word") or "").strip()
        value = str(e.get("value") or "").strip()
        rid = e.get("id")
        if not word or not value:
            skipped_empty.append(dict(word=word, value=value, id=rid,
                                      reason="原词或替换值为空"))
            continue
        if word == value:
            # 原词与替换值相同：这条规则什么都不会改，却会占住这个原词，
            # 把通用词库里更长的同类规则挡在后面——必须跳过并说清楚。
            skipped_identity.append(dict(word=word, value=value, id=rid,
                                         reason="原词与替换值相同，不会产生任何修改"))
            continue
        # 自定义侧同样受排除集约束：界面上「我的词库」也能逐条禁用，
        # 禁用了就不该再前置进规则（否则等于没禁）；按书层同理。
        key = entry_key(word, value)
        if union_off and key in union_off:
            if sources.get(key, "") in ("global", "both"):
                both = sources.get(key) == "both"
                overlap_custom += 1 if both else 0
                disabled_custom.append(dict(
                    word=word, value=value, id=rid,
                    reason=("该词条在词库里被禁用，且本书也排除了它" if both
                            else "该词条在词库里被禁用"),
                    source="global"))
            else:
                book_custom.append(dict(
                    word=word, value=value, id=rid,
                    reason="本书的按书词库排除了这条词条",
                    source="book"))
            continue
        if word in seen:
            kept = seen[word]
            skipped_duplicate.append(dict(
                word=word, value=value, id=rid,
                kept_value=kept["value"], kept_id=kept["id"],
                reason=f"同一个原词只保留一条（已保留替换值为「{kept['value']}」的那条）"))
            continue
        seen[word] = dict(word=word, value=value, id=rid)
        picked.append((word, value, rid if isinstance(rid, int) else 0))

    new_before = [w for w, _v, _i in picked] + kept_base_before
    new_after = [v for _w, v, _i in picked] + kept_base_after

    short_words = [w for w, _v, _i in picked if len(w) <= 1]
    return dict(
        before=new_before,
        after=new_after,
        stats=dict(
            base_rules=len(base_before),
            base_kept=len(kept_base_before),
            disabled_keys_checked=len(off),
            disabled_base_applied=len(disabled_base),
            disabled_custom_applied=len(disabled_custom),
            # ``disabled_applied`` 的语义**只有全局禁用**：两层同时命中时它算在
            # 全局这一侧（按书层不得抵消、也不冒充全局）。按书层单独命中不计入，
            # 单独记在下面三个 book_* 字段里——两种排除不混成一个数字。
            disabled_applied=len(disabled_base) + len(disabled_custom),
            book_id=str(book_id or ""),
            book_excluded_checked=len(book_off),
            # 「按书排除真正生效的条数」= 本书列出的、且确实被剔除的条数，
            # **含**与全局禁用叠加的那些（它们对这本书确实被排除了，只是原因
            # 记在全局侧）。另一个口径 ``book_only_applied`` 只算按书层独占的，
            # 两个数并列摆出来，谁都不会被误读成对方。
            book_only_applied=len(book_base) + len(book_custom),
            book_base_applied=len(book_base),
            book_custom_applied=len(book_custom),
            book_excluded_applied=(len(book_base) + len(book_custom)
                                   + overlap_base + overlap_custom),
            overlap_factory=overlap_base,
            overlap_custom=overlap_custom,
            overlap_applied=overlap_base + overlap_custom,
            excluded_total_applied=(len(disabled_base) + len(disabled_custom)
                                    + len(book_base) + len(book_custom)),
            excluded_policy=(OVERLAY_POLICY if union_off else ""),
            excluded_policy_note=(OVERLAY_POLICY_NOTE if union_off else ""),
            book_excluded_sha=book_excluded_sha(book_off),
            custom_input=len([e for e in entries if isinstance(e, dict)]),
            custom_applied=len(picked),
            total_rules=len(new_before),
            skipped_empty=skipped_empty,
            skipped_identity=skipped_identity,
            skipped_duplicate=skipped_duplicate,
            short_custom=short_words,
            book_excluded=book_base + book_custom,
            applied_words=[dict(word=w, value=v, id=i) for w, v, i in picked],
        ),
    )


# ---------------------------------------------------------------------------
# 落盘（带缓存：输入没变就不重写）
# ---------------------------------------------------------------------------

def compose_key(base_before_raw: bytes, base_after_raw: bytes,
                custom_raw: bytes, disabled_sha: str = "",
                book_sha: str = "") -> str:
    """合成键：三份输入的 sha 揉在一起，再把两层排除集指纹揉进去。

    禁用集一变键就变——否则「只改了启用/禁用」时缓存会误判命中，
    派生文件不重写，禁用就白点了（T1.3 的核心回归点）。V1.1-C1 同理：
    按书排除集一变键也必须变，否则改了这本书的按书配置、跑到别处仍是旧规则。
    空 ``book_sha`` 时键与 B3 收口时一致（未配置按书词库的书逐字节不变）。
    """
    h = hashlib.sha256()
    for part in (base_before_raw, base_after_raw, custom_raw):
        h.update(hashlib.sha256(part).digest())
    h.update(str(disabled_sha or "").encode("utf-8"))
    h.update(str(book_sha or "").encode("utf-8"))
    return h.hexdigest()


def canonical_disabled(disabled_keys: Iterable[str] | None) -> bytes:
    """禁用集的规范字节（键排序 + 紧凑 JSON）。

    刻意不 import ``word_states``（那会形成循环依赖），只按同一份格式复算；
    ``tests/test_t13_disabled_filter.py`` 有对拍用例锁住两处一致。
    """
    obj = {"version": 1, "disabled": sorted(set(disabled_keys or ()))}
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":")).encode("utf-8") + b"\n"


def disabled_sha(disabled_keys: Iterable[str] | None) -> str:
    """禁用集指纹（空集也给出确定值，便于进合成键与阶段指纹）。"""
    return hashlib.sha256(canonical_disabled(disabled_keys)).hexdigest()


def ruleset_sha(before: Iterable[str], after: Iterable[str]) -> str:
    """**实际下发规则集**的指纹：对即将交给引擎的两份数组取 sha。

    阶段指纹里带它，让「指纹」与「真正进引擎的规则」绑死：只改禁用集而规则
    没变（禁用了一条本就不下发的词）时规则指纹不变；反过来规则指纹变了，
    就一定有一次真实的规则变化。
    """
    h = hashlib.sha256()
    h.update(json.dumps(list(before), ensure_ascii=False).encode("utf-8"))
    h.update(b"\x00")
    h.update(json.dumps(list(after), ensure_ascii=False).encode("utf-8"))
    return h.hexdigest()


def write_derived_rules(base_before: Path | str, base_after: Path | str,
                        custom_path: Path | str | None,
                        out_dir: Path | str,
                        disabled_keys: Iterable[str] | None = None,
                        *, book_excluded_keys: Iterable[str] | None = None,
                        book_id: str = "") -> dict:
    """生成派生规则文件（落在 ``out_dir``），返回一份可直接进报告的摘要。

    幂等：三份输入都没变时复用已有文件，不重写（派生目录不会被无意义的
    写操作搅得时间戳乱跳）。``disabled_keys`` 的全局禁用集**同时**进合成键
    与规则合成——禁用了就要重写，不能被缓存挡住，否则禁用白点一次。
    V1.1-C1 的 ``book_excluded_keys`` 一样进合成键：按书配置改了必须重写。

    返回的 ``before_path`` / ``after_path`` 就是替换阶段应当使用的规则文件。
    """
    base_before = Path(base_before)
    base_after = Path(base_after)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    before_raw = _read_bytes(base_before)
    after_raw = _read_bytes(base_after)
    if before_raw is None or after_raw is None:
        raise DerivedRulesError("随包词库文件缺失，无法生成替换规则")

    custom_raw = _read_bytes(Path(custom_path)) if custom_path else None
    if custom_raw is None:
        custom_raw = b""          # 没有自定义词库 = 空输入，不是错误

    off = frozenset(disabled_keys or ())
    off_sha = disabled_sha(off)
    book_off = frozenset(book_excluded_keys or ())
    book_sha = book_excluded_sha(book_off)
    key = compose_key(before_raw, after_raw, custom_raw, off_sha, book_sha)
    meta_path = out / DERIVED_META
    d_before = out / DERIVED_BEFORE
    d_after = out / DERIVED_AFTER

    cached = _read_meta(meta_path)
    reusable = (
        cached.get("compose_key") == key
        and cached.get("disabled_sha") == off_sha
        and cached.get("book_excluded_sha") == book_sha
        and cached.get("book_id") == str(book_id or "")
        and d_before.is_file() and d_after.is_file()
        and cached.get("derived_before_sha256") == sha256_file(d_before)
        and cached.get("derived_after_sha256") == sha256_file(d_after)
    )
    if reusable:
        out_meta = dict(cached)
        out_meta.update(reused=True,
                        before_path=str(d_before), after_path=str(d_after),
                        meta_path=str(meta_path))
        return out_meta

    base_b = _load_string_array(base_before, "通用词库（替换前）")
    base_a = _load_string_array(base_after, "通用词库（替换后）")
    entries, custom_error = load_custom_entries(custom_path) if custom_path else ([], "")

    composed = compose(base_b, base_a, entries, disabled_keys=off,
                       book_excluded_keys=book_off, book_id=book_id)
    new_before = composed["before"]
    new_after = composed["after"]

    raw_before = json.dumps(new_before, ensure_ascii=False).encode("utf-8")
    raw_after = json.dumps(new_after, ensure_ascii=False).encode("utf-8")
    _atomic_write(d_before, raw_before)
    _atomic_write(d_after, raw_after)

    meta = dict(
        product="FixText",
        kind="derived_rules",
        version=2,                     # v2：规则合成开始吃禁用集（T1.3）
        compose_key=key,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        base_before=str(base_before),
        base_after=str(base_after),
        base_before_sha256=sha256_bytes(before_raw),
        base_after_sha256=sha256_bytes(after_raw),
        custom_source=str(custom_path) if custom_path else "",
        custom_sha256=sha256_bytes(custom_raw) if custom_raw else "",
        custom_error=custom_error,
        disabled_sha=off_sha,
        # book_id / book_excluded_sha 由下面 ``**composed["stats"]`` 提供（
        # 唯一来源，避免两处写同一个键、也不会两个值打架）。
        book_excluded_input=list(sorted(book_off)),
        ruleset_sha256=ruleset_sha(new_before, new_after),
        derived_before=str(d_before),
        derived_after=str(d_after),
        derived_before_sha256=sha256_bytes(raw_before),
        derived_after_sha256=sha256_bytes(raw_after),
        reused=False,
        before_path=str(d_before),
        after_path=str(d_after),
        meta_path=str(meta_path),
        **composed["stats"],
    )
    _atomic_write(meta_path, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    return meta


def _read_meta(path: Path) -> dict:
    raw = _read_bytes(path)
    if raw is None:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def default_custom_path() -> Path:
    """FixText 用户区里的自定义词库位置（与词库模块同一棵树，唯一一份）。

    用户区不在 pipeline 包内，而在包根的 ``workspace/vocab/`` 下；
    这里按包根推算，避免出现"第二份自定义词库"。
    """
    return _ui_workspace() / "vocab" / "custom_vocab.json"


def default_derived_dir() -> Path:
    """派生规则的默认落点：workspace 下「我的词库」旁边的子目录。"""
    return _ui_workspace() / "vocab" / DERIVED_SUBDIR


def _ui_workspace() -> Path:
    """用户区根目录 = **包根** ``workspace/``（M4-T4.4 写路径收口）。

    早期版本把用户区放在代码目录 ``fixtext_ui/workspace/``，与主入口
    ``main_app.py`` 建在包根的 ``workspace/`` 分裂成两棵；现在统一到包根这一棵，
    代码目录里不再出现用户数据。
    """
    try:
        from ._roots import pkg_root as _root_of

        return _root_of() / "workspace"
    except Exception:                                  # pragma: no cover
        return Path(__file__).resolve().parents[2] / "workspace"
