"""历史页的快照与恢复执行层（M3-T3.4，不依赖 Qt）
================================================

.. note::
   本模块原名 ``fixtext_snapshot.py``，M3-T3.5 集成时改名，因为同目录已有另一个
   ``fixtext_snapshot.py``（M3-T3.2 的词库还原点仓库，被 ``fixtext_vocab.py``
   依赖）。两者完全不同的东西：那个管**词库文件**的撤销 / 时点恢复，本模块管
   **运行产物的阶段点**恢复与续跑。改名后两套并存，互不覆盖。

「快照」= 一次运行在某个阶段边界上的产物目录状态。M1 管线本来就按阶段
落盘（``01_merge`` … ``06_restore``），所以**不需要另造一套快照存储**：
恢复 = 把某阶段为止的产物原样复制成一份「当前工作区」，并让它可导出、
可从该点继续后面的阶段。

本层提供四件事，全部落真实磁盘、可核验：

1. :func:`list_points` —— 枚举一次运行里真实存在哪些阶段点（缺就置灰并给原因）；
2. :func:`restore_point` —— 建一份现场副本 + 记「当前工作区」指针，
   副本里的工作正文与该阶段产物**逐字节一致**（sha 当场比对，不一致就不落指针）；
3. :func:`undo_restore` —— 回退到恢复前的「当前工作区」（无前值 = 回到未指定）；
4. :func:`resume_from_point` / :func:`seed_state` —— 用管线自己的断点续跑
   （``state.json`` + ``--resume``）跳过该点之前已完成的阶段，只跑后面的。

约定（与排期 §2.2 入口⑥ 验收② 对齐）：恢复**只读原书**，历史记录与运行目录
一概不动；所有影响都收在 ``runs/_snapshots/`` 下，因此天然可撤销。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SNAPSHOT_DIRNAME = "_snapshots"
CURRENT_FILE = "current.json"
META_FILE = "ui_snapshot.json"

#: 阶段点定义：key 与 M1 管线阶段同名（内部标识，只用于落盘与续跑），
#: name / desc 是给人看的文案（界面只呈现这两个）。
POINTS: list[dict[str, str]] = [
    dict(key="merge", name="导入合并完成",
         desc="全书正文已从原书里读出来，章节清单齐备"),
    dict(key="layout", name="排版完成",
         desc="标点与排版已整理，正文可直接替换"),
    dict(key="replace", name="替换完成",
         desc="词库替换已跑完，含改前 / 改后正文"),
    dict(key="quote", name="引号检查完成",
         desc="引号配对已检查过，正文与替换完成一致"),
    dict(key="restore", name="还原完成",
         desc="成品电子书已生成并通过校验"),
]
POINT_BY_KEY = {p["key"]: p for p in POINTS}
POINT_ORDER = [p["key"] for p in POINTS]

#: 每个阶段点必须具备的产物角色（缺任一即视为该点不可恢复）
POINT_NEEDS: dict[str, tuple[str, ...]] = {
    "merge": ("merge_text", "merge_ledger"),
    "layout": ("layout_text", "layout_ledger"),
    "replace": ("after_text", "before_text"),
    "quote": ("after_text", "quote_report"),
    "restore": ("after_text", "restored_epub", "restore_report"),
}

#: 该点的「工作正文」是哪个产物（恢复后导出、续跑都从它出发）
POINT_TEXT_ROLE: dict[str, str] = {
    "merge": "merge_text",
    "layout": "layout_text",
    "replace": "after_text",
    "quote": "after_text",
    "restore": "after_text",
}

#: 恢复该点时要把哪些阶段目录原样搬进现场（续跑要读到前面的产物）
POINT_DIRS: dict[str, tuple[str, ...]] = {
    "merge": ("01_merge",),
    "layout": ("01_merge", "02_layout"),
    "replace": ("01_merge", "02_layout", "03_replace"),
    "quote": ("01_merge", "02_layout", "03_replace", "04_quote"),
    "restore": ("01_merge", "02_layout", "03_replace", "04_quote",
                "05_bookmap", "06_restore"),
}

#: 阶段目录名（顺序即流水线顺序）
STAGE_DIR_OF = {
    "merge": "01_merge",
    "layout": "02_layout",
    "replace": "03_replace",
    "quote": "04_quote",
    "bookmap": "05_bookmap",
    "restore": "06_restore",
}

SUMMARY_FILE = Path("report") / "ui_run_summary.json"


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def sha256_file(path: str | Path, *, chunk: int = 1 << 20) -> str:
    """文件 sha256（分块读，不把大文件塞进内存）。"""
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _read_json(path: Path) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, payload: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_run_summary(run_dir: str | Path) -> dict:
    return _read_json(Path(run_dir) / SUMMARY_FILE)


def _newest(files: list[Path]) -> Path | None:
    files = [p for p in files if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: (p.stat().st_mtime, p.name))


def _glob_one(base: Path, pattern: str) -> Path | None:
    if not base.is_dir():
        return None
    return _newest(sorted(base.glob(pattern)))


# ---------------------------------------------------------------------------
# 产物定位（只按运行目录里真的有什么来认，不按文件名猜）
# ---------------------------------------------------------------------------

def _relocate(run: Path, path: str | Path | None) -> Path | None:
    """把产物路径落到这个运行目录里的真实文件上。

    运行摘要里的产物是**绝对路径**，运行目录一旦被整体搬动 / 复制
    （换机器、备份还原、验收里的副本），旧路径就指到别处去了。
    这里只做一件事：按阶段目录名把路径尾部搬到本运行目录下再确认存在；
    搬过去也不存在就返回 ``None``（宁可不认，也不拿别人的文件充数）。
    """
    if not path:
        return None
    p = Path(str(path))
    if p.is_file():
        try:
            p.relative_to(run)
            return p
        except ValueError:
            pass
    parts = p.parts
    for i, part in enumerate(parts):
        if part in set(STAGE_DIR_OF.values()):
            cand = run.joinpath(*parts[i:])
            if cand.is_file():
                return cand
            break
    # 阶段目录层级对不上时，按文件名在该阶段里找一次
    for stage_dir in STAGE_DIR_OF.values():
        cand = run / stage_dir / p.name
        if cand.is_file():
            return cand
    return None


def resolve_artifacts(run_dir: str | Path,
                      summary: dict | None = None) -> dict[str, str]:
    """读出一个运行目录里**真实存在**的阶段产物（角色 → 绝对路径）。

    定位顺序与导出层同口径：运行摘要自述的权威路径 → 阶段报告自述 →
    目录里实际枚举。定位不到的就不放进结果（调用方据此置灰）。
    """
    run = Path(run_dir)
    data = summary if summary is not None else load_run_summary(run)
    art = dict(data.get("artifacts") or {})
    out: dict[str, str] = {}

    def _put(role: str, path: str | Path | None) -> None:
        found = _relocate(run, path)
        if found is not None:
            out.setdefault(role, str(found))

    # 1) 摘要在收尾时回传的绝对路径
    _put("after_text", art.get("after_text"))
    _put("before_text", art.get("before_text"))
    _put("layout_text", art.get("laid_out_text"))
    _put("restored_epub", art.get("restored_epub"))

    # 2) 阶段报告自述
    merge = _read_json(run / "01_merge" / "merge_report.json")
    _put("merge_text", merge.get("text_path"))
    _put("merge_ledger", merge.get("ledger_path"))

    layout = _read_json(run / "02_layout" / "layout_report.json")
    _put("layout_text", layout.get("text_path"))

    replace = _read_json(run / "03_replace" / "replace_report.json")
    _put("after_text", replace.get("after_path"))
    _put("before_text", replace.get("before_path"))

    quote = _read_json(run / "04_quote" / "quote_summary.json")
    _put("quote_report", quote.get("report_json"))
    _put("quote_summary", str(run / "04_quote" / "quote_summary.json"))
    _put("after_text", quote.get("checked_file"))

    restore = _read_json(run / "06_restore" / "validate_report.json")
    _put("restored_epub", restore.get("restored_epub"))
    _put("restore_report", str(run / "06_restore" / "validate_report.json"))

    # 3) 目录实际枚举（摘要与报告都失效时的兜底，取最新那份）
    if "merge_text" not in out:
        _put("merge_text", _glob_one(run / "01_merge", "*.txt"))
    ledgers = sorted((run / "01_merge").glob("*.bundle.json")) if (run / "01_merge").is_dir() else []
    _put("merge_ledger", _newest(ledgers))
    if "layout_text" not in out:
        _put("layout_text", _glob_one(run / "02_layout", "*.txt"))
    _put("layout_ledger", _newest(sorted((run / "02_layout").glob("*.bundle.json")))
         if (run / "02_layout").is_dir() else None)
    if "after_text" not in out:
        _put("after_text", _glob_one(run / "03_replace" / "after", "*.txt"))
    if "before_text" not in out:
        _put("before_text", _glob_one(run / "03_replace" / "before", "*.txt"))
    if "restored_epub" not in out:
        _put("restored_epub", _glob_one(run / "06_restore", "*.epub"))
    if "quote_report" not in out:
        # 摘要里没写具体报告名时，按引号检查目录里实际留下的那份报告认
        _put("quote_report", _glob_one(run / "04_quote", "*.report.json"))
    if "merge_ledger" not in out:
        _put("merge_ledger", _newest(sorted((run / "01_merge").glob("*.bundle.json")))
             if (run / "01_merge").is_dir() else None)

    # 账本：替换后的正文要用排版时落的账本切章（导出与还原都靠它）
    if "ledger" not in out:
        out["ledger"] = out.get("layout_ledger") or out.get("merge_ledger") or ""
    return {k: v for k, v in out.items() if v}


# ---------------------------------------------------------------------------
# 阶段点枚举
# ---------------------------------------------------------------------------

@dataclass
class Point:
    """一个可恢复的阶段点。"""

    key: str
    name: str
    desc: str
    available: bool = False
    reason: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def text_path(self) -> str:
        """该点的工作正文（继续后续阶段、导出都从它出发）。"""
        role = POINT_TEXT_ROLE.get(self.key) or "after_text"
        return self.artifacts.get(role) or ""

    def to_dict(self) -> dict[str, Any]:
        return dict(key=self.key, name=self.name, desc=self.desc,
                    available=self.available, reason=self.reason,
                    artifacts=dict(self.artifacts),
                    text_path=self.text_path)


def list_points(run_dir: str | Path,
                summary: dict | None = None) -> list[dict[str, Any]]:
    """枚举该运行可用的阶段点（有产物 = 可恢复；缺 = 置灰 + 原因）。

    返回顺序固定为流水线顺序；``available`` 是机器判定，不是写的。
    """
    run = Path(run_dir)
    if not run.is_dir():
        return []
    arts = resolve_artifacts(run, summary)
    out: list[dict[str, Any]] = []
    for spec in POINTS:
        key = spec["key"]
        needs = POINT_NEEDS[key]
        missing = [r for r in needs if not arts.get(r)]
        # 该点自己用得到的产物（不要把后续阶段的产物挂到前面的点上）
        own_roles = set(needs) | {"ledger"}
        own = {r: arts[r] for r in own_roles if arts.get(r)}
        own.setdefault("text", arts.get(POINT_TEXT_ROLE[key]) or "")
        point = Point(key=key, name=spec["name"], desc=spec["desc"],
                      artifacts={k: v for k, v in own.items() if v})
        if missing:
            point.available = False
            point.reason = "这次运行没有走到这一步，没有留下可恢复的结果"
        else:
            point.available = True
        out.append(point.to_dict())
    return out


def point_count(run_dir: str | Path, summary: dict | None = None) -> tuple[int, int]:
    """(可恢复点数, 总点数)。"""
    pts = list_points(run_dir, summary)
    return sum(1 for p in pts if p["available"]), len(pts)


# ---------------------------------------------------------------------------
# 当前工作区（磁盘指针）
# ---------------------------------------------------------------------------

def store_root(runs_root: str | Path) -> Path:
    return Path(runs_root) / SNAPSHOT_DIRNAME


def current_state(runs_root: str | Path) -> dict | None:
    """读「当前工作区」指针（没有 = 未指定）。**重启后照样读得出来**。"""
    raw = _read_json(store_root(runs_root) / CURRENT_FILE)
    if not raw or not raw.get("snapshot_dir"):
        return None
    if not Path(str(raw["snapshot_dir"])).is_dir():
        return None
    return raw


def _set_current(runs_root: str | Path, payload: dict | None) -> None:
    root = store_root(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / CURRENT_FILE
    if payload is None:
        if path.exists():
            path.unlink()
        return
    _write_json(path, payload)


def current_working_text(runs_root: str | Path) -> str:
    cur = current_state(runs_root)
    return str((cur or {}).get("working_text") or "")


# ---------------------------------------------------------------------------
# 恢复
# ---------------------------------------------------------------------------

@dataclass
class RestoreResult:
    ok: bool = False
    message: str = ""
    snapshot_dir: str = ""
    run_dir: str = ""
    point: str = ""
    point_name: str = ""
    title: str = ""
    working_text: str = ""
    ledger: str = ""
    template_epub: str = ""
    restored_epub: str = ""
    #: 逐项 sha 对照：{角色: {"source": .., "copy": .., "equal": bool}}
    verify: dict[str, dict[str, Any]] = field(default_factory=dict)
    prev_snapshot: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(ok=self.ok, message=self.message,
                    snapshot_dir=self.snapshot_dir, run_dir=self.run_dir,
                    point=self.point, point_name=self.point_name,
                    title=self.title, working_text=self.working_text,
                    ledger=self.ledger, template_epub=self.template_epub,
                    restored_epub=self.restored_epub,
                    verify=self.verify, prev_snapshot=self.prev_snapshot)


#: 各点该用哪个账本切章（合并点只有合并账本，排版之后才有排版账本）
POINT_LEDGER: dict[str, tuple[str, ...]] = {
    "merge": ("merge_ledger", "ledger"),
    "layout": ("layout_ledger", "ledger", "merge_ledger"),
    "replace": ("layout_ledger", "ledger", "merge_ledger"),
    "quote": ("layout_ledger", "ledger", "merge_ledger"),
    "restore": ("layout_ledger", "ledger", "merge_ledger"),
}


def _ledger_in_copy(dest: Path, run: Path, arts: dict[str, str],
                    point_key: str) -> str:
    """在**这次真正复制过来的阶段目录**里找一个存在的账本。

    账本决定了导出时按章切正文；只认副本里真的存在的那一份——
    找不到就返回空（导出会退回按行处理），绝不指向没搬过来的文件。
    """
    for role in POINT_LEDGER.get(point_key, ("ledger",)):
        src = arts.get(role)
        if not src:
            continue
        try:
            cand = dest / Path(src).relative_to(run)
        except ValueError:
            continue
        if cand.is_file():
            return str(cand)
    return ""


def _copy_stage_dirs(run: Path, dest: Path, point_key: str) -> list[str]:
    """把该点为止的阶段目录原样搬进现场副本，返回搬了哪些。"""
    copied: list[str] = []
    for name in POINT_DIRS[point_key]:
        src = run / name
        if not src.is_dir():
            continue
        shutil.copytree(src, dest / name, dirs_exist_ok=True)
        copied.append(name)
    return copied


def restore_point(run_dir: str | Path, point_key: str,
                  runs_root: str | Path, *,
                  summary: dict | None = None) -> RestoreResult:
    """把「当前工作区」切到该运行的某个阶段点。

    * 现场副本落在 ``<runs_root>/_snapshots/snap-<运行>-<点>-<时间>/``；
    * 副本里的工作正文 / 账本 / 成品与该点产物**逐字节一致**（逐个比 sha，
      有任何一项不一致就判定失败、不写指针）；
    * 恢复不动原书、不动运行目录，只写这一个指针，因此可撤销。
    """
    run = Path(run_dir)
    res = RestoreResult(run_dir=str(run), point=point_key,
                        point_name=POINT_BY_KEY.get(point_key, {}).get("name", point_key))
    if point_key not in POINT_BY_KEY:
        res.message = "没有这个时点"
        return res
    if not run.is_dir():
        res.message = "这次运行的结果已经不在了"
        return res

    data = summary if summary is not None else load_run_summary(run)
    arts = resolve_artifacts(run, data)
    missing = [r for r in POINT_NEEDS[point_key] if not arts.get(r)]
    if missing:
        res.message = "这次运行没有走到这一步，没有可恢复的结果"
        return res

    title = str(data.get("title") or data.get("book") or run.name)
    res.title = title
    root = store_root(runs_root)
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = root / f"snap-{run.name}-{point_key}-{stamp}"
    n = 1
    while dest.exists():
        n += 1
        dest = root / f"snap-{run.name}-{point_key}-{stamp}-{n}"

    copied = _copy_stage_dirs(run, dest, point_key)

    # 现场里的对应文件（与源同相对位置），源 → 副本逐个比 sha
    verify: dict[str, dict[str, Any]] = {}
    for role, src in arts.items():
        p = Path(src)
        try:
            rel = p.relative_to(run)
        except ValueError:
            continue
        copy = dest / rel
        if not copy.exists():
            continue
        src_sha = sha256_file(p)
        copy_sha = sha256_file(copy)
        verify[role] = dict(source=src_sha, copy=copy_sha,
                            equal=(src_sha == copy_sha), name=rel.as_posix())
    res.verify = verify
    broken = [r for r, v in verify.items() if not v["equal"]]
    if broken:
        shutil.rmtree(dest, ignore_errors=True)
        res.message = "现场复制校验没通过，已撤掉这份副本"
        return res

    working = ""
    role = POINT_TEXT_ROLE[point_key]
    if arts.get(role) and _is_within(run, arts[role]):
        working = str(dest / Path(arts[role]).relative_to(run))
    before = ""
    if arts.get("before_text") and _is_within(run, arts["before_text"]):
        before = str(dest / Path(arts["before_text"]).relative_to(run))
    ledger = _ledger_in_copy(dest, run, arts, point_key)
    restored = ""
    if arts.get("restored_epub"):
        try:
            restored = str(dest / Path(arts["restored_epub"]).relative_to(run))
        except ValueError:
            restored = ""
    template = str(data.get("source_epub") or "")

    prev = current_state(runs_root)
    meta = dict(
        version=1,
        created_at=time.time(),
        created_at_text=time.strftime("%Y-%m-%d %H:%M", time.localtime()),
        run_dir=str(run),
        point=point_key,
        point_name=res.point_name,
        title=title,
        book=f"《{title}》",
        stage_dirs=copied,
        artifacts={k: str(dest / Path(v).relative_to(run))
                   for k, v in arts.items() if _is_within(run, v)},
        working_text=working,
        before_text=before,
        ledger=ledger,
        restored_epub=restored,
        template_epub=template if Path(template).is_file() else "",
        verify=verify,
        prev_snapshot=str((prev or {}).get("snapshot_dir") or ""),
    )
    _write_json(dest / META_FILE, meta)
    res.snapshot_dir = str(dest)
    res.working_text = working
    res.ledger = ledger
    res.restored_epub = restored
    res.template_epub = meta["template_epub"]
    res.prev_snapshot = meta["prev_snapshot"]

    _set_current(runs_root, dict(
        snapshot_dir=str(dest),
        run_dir=str(run),
        point=point_key,
        point_name=res.point_name,
        title=title,
        book=f"《{title}》",
        created_at=meta["created_at"],
        created_at_text=meta["created_at_text"],
        working_text=working,
        before_text=before,
        ledger=ledger,
        restored_epub=restored,
        template_epub=meta["template_epub"],
        prev_snapshot=meta["prev_snapshot"],
        verify=verify,
    ))
    res.ok = True
    res.message = f"已恢复到《{title}》的「{res.point_name}」时点"
    return res


def _is_within(root: Path, path: str | Path) -> bool:
    try:
        Path(str(path)).relative_to(root)
        return True
    except ValueError:
        return False


def undo_restore(runs_root: str | Path) -> dict | None:
    """撤销恢复：指针回到恢复前的「当前工作区」。

    返回撤销后的当前状态（``None`` = 已回到「未指定」，即恢复前的状态）。
    """
    cur = current_state(runs_root)
    if not cur:
        return None
    prev_dir = str(cur.get("prev_snapshot") or "")
    prev_meta = _read_json(Path(prev_dir) / META_FILE) if prev_dir else {}
    if prev_dir and prev_meta and Path(prev_dir).is_dir():
        restored_prev = dict(
            snapshot_dir=prev_dir,
            run_dir=str(prev_meta.get("run_dir") or ""),
            point=str(prev_meta.get("point") or ""),
            point_name=str(prev_meta.get("point_name") or ""),
            title=str(prev_meta.get("title") or ""),
            book=str(prev_meta.get("book") or ""),
            created_at=prev_meta.get("created_at") or 0,
            created_at_text=str(prev_meta.get("created_at_text") or ""),
            working_text=str(prev_meta.get("working_text") or ""),
            before_text=str(prev_meta.get("before_text") or ""),
            ledger=str(prev_meta.get("ledger") or ""),
            restored_epub=str(prev_meta.get("restored_epub") or ""),
            template_epub=str(prev_meta.get("template_epub") or ""),
            prev_snapshot=str(prev_meta.get("prev_snapshot") or ""),
            verify=prev_meta.get("verify") or {},
        )
        _set_current(runs_root, restored_prev)
        return restored_prev
    _set_current(runs_root, None)
    return None


def current_summary_text(cur: dict | None) -> str:
    """「当前工作区」这一行的人话文案（界面直接用）。"""
    if not cur:
        return "当前工作区：未指定（保持「导入后」状态）"
    book = cur.get("book") or f"《{cur.get('title') or '这本书'}》"
    point = cur.get("point_name") or "某个时点"
    when = cur.get("created_at_text") or ""
    tail = f"（{when} 恢复）" if when else ""
    return f"当前工作区：{book} · {point}{tail}"


# ---------------------------------------------------------------------------
# 导出源（从「当前工作区」出发）
# ---------------------------------------------------------------------------

def build_export_source(state: dict | None,
                        pipeline_root: str | Path | None = None):
    """由「当前工作区」构造导出源（复用 T2.7 导出层的 :class:`ExportSource`）。

    返回的源与「那次运行的结果」等价：正文 / 账本 / 原书都在现场副本里，
    所以导出的成品与恢复点一致（EPUB 还原对同一份正文是确定性的）。
    """
    import fixtext_export as fx

    cur = state or {}
    src = fx.ExportSource(pipeline_root=str(pipeline_root or ""))
    src.title = str(cur.get("title") or "")
    src.original_title = src.title
    src.run_dir = str(cur.get("snapshot_dir") or "")
    text = str(cur.get("working_text") or "")
    if text and Path(text).is_file():
        src.text_path = text
    before = str(cur.get("before_text") or "")
    if before and Path(before).is_file():
        src.before_text = before
    ledger = str(cur.get("ledger") or "")
    if ledger and Path(ledger).is_file():
        src.ledger_path = ledger
    template = str(cur.get("template_epub") or "")
    if template and Path(template).is_file() and src.ledger_path:
        src.source_kind = "epub"
        src.template_epub = template
    src.corrected = bool(src.text_path)
    src.resolve_notes.append("导出源：当前工作区（恢复点副本）")
    return src


# ---------------------------------------------------------------------------
# 从该点继续（走管线自己的断点续跑）
# ---------------------------------------------------------------------------

class _NullLog:
    def log(self, *_a, **_k):
        pass

    def close(self):
        pass


def seed_state(snapshot_dir: str | Path, epub: str | Path,
               rules_before: str | Path, rules_after: str | Path,
               engine_path: str | Path, *, up_to: str,
               summary: dict | None = None,
               pipeline_root: str | Path | None = None) -> dict:
    """在现成副本里写 ``state.json``：把 ``up_to`` 及之前的阶段标成已完成。

    指纹用管线自己的 ``Stage.fingerprint()`` 现算（只读哈希，不执行阶段），
    所以随后的 ``--resume`` 走的是**同一条**判定：状态 done + 指纹一致 +
    产物齐全 → 跳过。任何一条不满足，管线自己会重跑，不会被这里糊过去。
    """
    import fixtext_export as fx
    fx.ensure_vendor(pipeline_root)

    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.state import StateStore
    from fixtext_pipeline.stages import STAGES

    snap = Path(snapshot_dir)
    cfg = PipelineConfig(epub=Path(epub), workdir=snap,
                         rules_before=Path(rules_before),
                         rules_after=Path(rules_after),
                         engine_path=Path(engine_path))
    store = StateStore(Path(snap) / "state.json").load()
    store.set_config(cfg.to_dict())

    elapsed = (summary or {}).get("stage_elapsed") or {}
    seeded: dict[str, dict] = {}
    for key in POINT_ORDER[:POINT_ORDER.index(up_to) + 1]:
        stage = STAGES[key](cfg, _NullLog())
        try:
            fp = stage.fingerprint()
        except Exception as exc:                          # noqa: BLE001
            seeded[key] = dict(status="failed", reason=f"{type(exc).__name__}")
            continue
        outs = [str(p) for p in stage.outputs()]
        present = [p for p in outs if Path(p).exists()]
        if len(present) != len(outs):
            seeded[key] = dict(status="incomplete", reason="产物不全")
            continue
        store.mark(key, status="done", fingerprint=fp,
                   elapsed_s=float(elapsed.get(key) or 0.0),
                   outputs=outs, report={}, started_at=None,
                   ended_at=time.time())
        seeded[key] = dict(status="done", outputs=outs, fingerprint=fp)
    store.save()
    return seeded


def _adopt_workspace(work_dir: str | Path, runs_root: str | Path, *,
                     prev_snapshot: str, src_meta: dict) -> dict:
    """把「接着往下跑完」的那份目录登记成当前工作区。

    续跑成功后，这本书实际已经往前走了（后面几个阶段真的产出了新东西），
    所以当前工作区要跟着指向它；``prev_snapshot`` 仍指向续跑前的那个快照，
    撤销时回到续跑前的样子。
    """
    work = Path(work_dir)
    pts = [p for p in list_points(work) if p["available"]]
    point_key = pts[-1]["key"] if pts else "restore"
    point_name = POINT_BY_KEY.get(point_key, {}).get("name", point_key)
    arts = resolve_artifacts(work)
    title = str(src_meta.get("title") or work.name)
    role = POINT_TEXT_ROLE.get(point_key, "after_text")
    meta = dict(
        version=1,
        created_at=time.time(),
        created_at_text=time.strftime("%Y-%m-%d %H:%M", time.localtime()),
        run_dir=str(src_meta.get("run_dir") or ""),
        # M3-T3.5 修：续跑后这里就是新的「当前工作区」现场，指针必须带上
        # snapshot_dir，否则 current_state() 判定「没有时点」直接返回 None，
        # 「导出当前工作区」会在续跑成功后反而失效。
        snapshot_dir=str(work),
        point=point_key,
        point_name=point_name,
        title=title,
        book=f"《{title}》",
        stage_dirs=[d for d in STAGE_DIR_OF.values() if (work / d).is_dir()],
        artifacts=arts,
        working_text=arts.get(role) or "",
        before_text=arts.get("before_text") or "",
        ledger=arts.get("ledger") or "",
        restored_epub=arts.get("restored_epub") or "",
        template_epub=str(src_meta.get("template_epub") or ""),
        verify={},
        prev_snapshot=str(prev_snapshot or ""),
        continued=True,
    )
    _write_json(work / META_FILE, meta)
    _set_current(runs_root, {k: v for k, v in meta.items()
                             if k not in ("stage_dirs", "continued")})
    return meta


def resume_from_point(snapshot_dir: str | Path,
                      runs_root: str | Path,
                      *,
                      point: str,
                      epub: str | Path,
                      rules_before: str | Path,
                      rules_after: str | Path,
                      engine_path: str | Path,
                      pipeline_root: str | Path | None = None,
                      work_dir: str | Path | None = None,
                      adopt: bool = True) -> dict:
    """从该点继续后面的阶段（管线 resume），返回退出码与阶段耗时证据。

    ``work_dir`` 给了就在副本的拷贝上跑（验收要保住原现场不被改写）。
    """
    import fixtext_export as fx
    fx.ensure_vendor(pipeline_root)

    from fixtext_pipeline.config import PipelineConfig
    from fixtext_pipeline.runner import run_pipeline

    src = Path(snapshot_dir)
    work = Path(work_dir) if work_dir else src
    if work != src:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(src, work)

    summary = _read_json(src / META_FILE)
    run_summary = load_run_summary(str(summary.get("run_dir") or ""))
    seeded = seed_state(work, epub, rules_before, rules_after, engine_path,
                        up_to=point, summary=run_summary,
                        pipeline_root=pipeline_root)

    cfg = PipelineConfig(epub=Path(epub), workdir=work,
                         rules_before=Path(rules_before),
                         rules_after=Path(rules_after),
                         engine_path=Path(engine_path),
                         resume=True, force=False, keep_going=False)
    started = time.time()
    code, report = run_pipeline(cfg)
    elapsed = round(time.time() - started, 3)
    adopted: dict = {}
    if code == 0 and adopt and work != src:
        adopted = _adopt_workspace(work, runs_root,
                                   prev_snapshot=str(summary.get("snapshot_dir")
                                                     or src),
                                   src_meta=summary)
    return dict(exit_code=code, report=report, seeded=seeded,
                work_dir=str(work), resume_from=point,
                elapsed_s=elapsed, adopted=adopted)
