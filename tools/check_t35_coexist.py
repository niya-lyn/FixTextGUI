"""M3-T3.5 收尾自检：两个同名模块改名后能否被同时导入、互不遮蔽。

小组长 06:53 指定项。这里走真实导入 + 真实主窗口构建，不看静态 grep：

  A1  两个模块各自直接 import，取到的确实是两个不同文件、两套不同接口
  A2  模块对象不是同一个 sys.modules 条目（没被遮蔽 / 没被别名顶替）
  A3  同时 import 后各自功能调用照常（A 建还原点 / B 列阶段点）
  A4  真实构建 MainWindow —— 它经 fixtext_vocab → fixtext_snapshot、
      history_module → fixtext_run_snapshot 两条**传递依赖**把两边同时拉起；
      构建成功且两个模块都已在 sys.modules 里，才算没在启动时互相遮蔽
  A5  main_window 源码里没有任何一条相关导入被注释掉

产出：evidence/t35_coexist_import.json
"""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
UI = PKG / "fixtext_ui"
for p in (str(PKG), str(UI), str(PKG / "fixtext_import")):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

EVID = PKG / "evidence"
report: dict = {"card": "M3-T3.5", "check": "coexist_import"}
ok = True


def line(msg: str) -> None:
    print(msg)


# ---------------------------------------------------------------------------
# A1 / A2：两个模块同时导入，各自是不同文件
# ---------------------------------------------------------------------------
import fixtext_snapshot as a                      # noqa: E402
import fixtext_run_snapshot as b                  # noqa: E402

a_file = Path(inspect.getfile(a)).resolve()
b_file = Path(inspect.getfile(b)).resolve()
same_file = a_file == b_file
same_name = a.__name__ == b.__name__
a_api = dict(SnapshotStore=hasattr(a, "SnapshotStore"),
             MAX_POINTS=hasattr(a, "MAX_POINTS"),
             pack_builtin=hasattr(a.SnapshotStore, "pack_builtin"))
b_api = dict(list_points=hasattr(b, "list_points"),
             restore_point=hasattr(b, "restore_point"),
             resume_from_point=hasattr(b, "resume_from_point"),
             current_state=hasattr(b, "current_state"),
             build_export_source=hasattr(b, "build_export_source"))
# 关键：A 不该有 B 的接口，B 不该有 A 的接口（真分离，不是同一个东西换了名字）
a_has_b_api = any(hasattr(a, n) for n in
                  ("list_points", "restore_point", "resume_from_point"))
b_has_a_api = any(hasattr(b, n) for n in ("SnapshotStore", "pack_builtin"))
in_modules = ("fixtext_snapshot" in sys.modules
              and "fixtext_run_snapshot" in sys.modules)

a1 = (not same_file and not same_name and a_file.name == "fixtext_snapshot.py"
      and b_file.name == "fixtext_run_snapshot.py")
a2 = (not a_has_b_api and not b_has_a_api and in_modules)
ok = ok and a1 and a2
line(f"[A1] 同时导入：A={a_file.name}（{a.__name__}）B={b_file.name}（{b.__name__}）"
     f" → 同一文件={same_file}，同名={same_name}")
line(f"     A 接口={a_api}")
line(f"     B 接口={b_api}")
line(f"[A2] 未互相遮蔽：sys.modules 两条都在={in_modules}；"
     f"A 沾到 B 接口={a_has_b_api}，B 沾到 A 接口={b_has_a_api}")
report["a1_two_modules"] = dict(
    a_file=str(a_file), b_file=str(b_file),
    a_module_name=a.__name__, b_module_name=b.__name__,
    same_file=same_file, same_module_name=same_name,
    a_api=a_api, b_api=b_api)
report["a2_no_shadowing"] = dict(in_sys_modules=in_modules,
                                 a_has_b_api=a_has_b_api,
                                 b_has_a_api=b_has_a_api)

# ---------------------------------------------------------------------------
# A3：同时导入后各自功能真的能调用
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    store = a.SnapshotStore(Path(td) / "snap")
    pid = store.begin(label="自检", act="add", before_bytes=b'{"entries":[]}\n')
    store.commit(pid, after_bytes=b'{"entries":[1]}\n')
    a3_a = (store.point_count() == 1 and bool(store.points())
            and (store.get(pid) or {}).get("sha_after"))
    # A 的还原点载荷能正常打包 / 解包（这条链路是词库撤销的底座）
    packed = a.SnapshotStore.pack_builtin({"custom.json": b'ab'})
    a3_a = a3_a and a.SnapshotStore.unpack_builtin(packed) == {"custom.json": b'ab'}

    # B 侧：对一个空运行目录列时点，应当返回「都不可用」而不是抛异常
    empty_run = Path(td) / "run-empty"
    empty_run.mkdir()
    pts = b.list_points(empty_run)
    a3_b = (len(pts) == len(b.POINTS) and not any(p["available"] for p in pts)
            and all(p.get("reason") for p in pts))
    cur = b.current_state(Path(td) / "noruns")
    a3_b = a3_b and cur is None
line(f"[A3] 同时导入后功能调用：A 建还原点+载荷打包={a3_a}；"
     f"B 空运行列 {len(pts)} 个时点全部置灰且给了原因={a3_b}；B 空指针返回 None={cur is None}")
ok = ok and a3_a and a3_b
report["a3_both_callable"] = dict(a_store_works=a3_a, b_list_points_ok=a3_b,
                                  b_points=len(pts), b_current_none=cur is None)

# ---------------------------------------------------------------------------
# A4：冷启动子进程里真实构建 MainWindow（两边经传递依赖同时拉起）
# ---------------------------------------------------------------------------
a4 = False
a4_info: dict = {}
try:
    import subprocess

    probe = f'''
import json, os, sys
sys.path[:0] = [{str(PKG)!r}, {str(UI)!r}, {str(PKG / "fixtext_import")!r}]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import main_window as mw
win = mw.MainWindow()
app.processEvents()
a = sys.modules.get("fixtext_snapshot")
b = sys.modules.get("fixtext_run_snapshot")
vstore = getattr(win.vocab_module, "store", None)
hist = win.history_module
hs = sys.modules.get(type(hist).__module__)
out = dict(
    cold_start_modules=dict(a=a is not None, b=b is not None),
    a_api=bool(a and hasattr(a, "SnapshotStore")),
    b_api=bool(b and hasattr(b, "list_points")),
    a_file=getattr(a, "__file__", ""),
    b_file=getattr(b, "__file__", ""),
    vocab_store_class=type(vstore).__name__ if vstore else "",
    vocab_snap_module=getattr(type(getattr(vstore, "snap", None)), "__module__", ""),
    history_snapshot_module=getattr(getattr(hs, "snapshot", None), "__name__", ""),
    window_title=win.windowTitle(),
)
win.close()
print("PROBE=" + json.dumps(out, ensure_ascii=False))
'''
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               PYTHONPATH="/home/gem/.aily/.cli/qtenv/lib/python3.12/site-packages")
    cp = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                        text=True, timeout=180, env=env)
    raw = [ln for ln in cp.stdout.splitlines() if ln.startswith("PROBE=")]
    if raw:
        a4_info = json.loads(raw[-1][len("PROBE="):])
        a4 = bool(a4_info["cold_start_modules"]["a"]
                  and a4_info["cold_start_modules"]["b"]
                  and a4_info["a_api"] and a4_info["b_api"]
                  and a4_info["vocab_snap_module"] == "fixtext_snapshot"
                  and a4_info["history_snapshot_module"] == "fixtext_run_snapshot")
    else:
        a4_info = dict(error=(cp.stderr or cp.stdout or "")[-800:],
                       returncode=cp.returncode)
except Exception as exc:                                   # noqa: BLE001
    a4_info = dict(error=f"{type(exc).__name__}: {exc}")
    line(f"[A4] 构建 MainWindow 失败：{exc}")
ok = ok and a4
line(f"[A4] 冷启动子进程真实构建 MainWindow：两边同时拉起且各归各位={a4}；详情={a4_info}")
report["a4_main_window"] = a4_info

# ---------------------------------------------------------------------------
# A5：源码里相关导入没被注释掉（含两条传递依赖链的起点）
# ---------------------------------------------------------------------------
src = (UI / "main_window.py").read_text(encoding="utf-8")
commented = [ln.strip() for ln in src.splitlines()
             if re.match(r"^\s*#\s*(import|from)\s+(fixtext_snapshot|fixtext_run_snapshot"
                         r"|history_module|vocab_module|fixtext_vocab)", ln)]
mw_imports = re.findall(r"^\s*(?:import|from)\s+(\w+)", src, re.M)
mw_set = set(mw_imports)
# main_window 不直接摸这两个快照模块，它靠两个消费方传递依赖：
#   history_module → fixtext_run_snapshot（线 B）
#   vocab_module   → fixtext_vocab → fixtext_snapshot（线 A）
chain = dict(history_module="history_module" in mw_set,
             vocab_module="vocab_module" in mw_set)
vocab_src = (UI / "fixtext_vocab.py").read_text(encoding="utf-8")
hist_src = (UI / "history_module.py").read_text(encoding="utf-8")
leaf = dict(
    vocabs_imports_a=bool(re.search(r"^\s*from\s+fixtext_snapshot\s+import\b",
                                    vocab_src, re.M)),
    history_imports_b=bool(re.search(r"^\s*import\s+fixtext_run_snapshot\b",
                                     hist_src, re.M)),
    vocab_module_imports_vocab=bool(re.search(r"^\s*(?:import|from)\s+fixtext_vocab\b",
                                              (UI / "vocab_module.py").read_text(
                                                  encoding="utf-8"), re.M)),
)
a5 = (not commented and all(chain.values()) and all(leaf.values()))
line(f"[A5] 导入链完整：main_window 被注释掉的相关导入={commented}；"
     f"消费方入口={chain}；叶子导入={leaf}")
ok = ok and a5
report["a5_import_chain"] = dict(commented=commented, consumers=chain, leaf=leaf)

report["ok"] = bool(ok)
EVID.mkdir(parents=True, exist_ok=True)
(EVID / "t35_coexist_import.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n=== ALL PASS ===" if ok else "\n=== FAIL ===")
print("证据 →", EVID / "t35_coexist_import.json")
sys.exit(0 if ok else 1)
