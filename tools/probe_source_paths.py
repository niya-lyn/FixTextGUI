"""源码模式路径探针：在未冻结状态下验证各根目录解析是否一致。

用途：打包前的"基线自证"——确认 fixtext_paths.pkg_root() 与各消费方拿到的
路径在源码模式下全部指向包根，且替换引擎按平台取到的是 Linux 二进制。
冻结后同一套断言由 fxbundle_smoke.py / fixtext_self_check.py 再验一遍。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
for _sub in ("fixtext_ui", "fixtext_import", "fixtext_error_center"):
    sys.path.insert(0, os.path.join(ROOT, _sub))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fails = []


def show(name, value):
    print(f"{name}: {value}")


def check(name, cond, detail=""):
    ok = bool(cond)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'  ' + detail if detail else ''}")
    if not ok:
        fails.append(name)


import fixtext_paths as P  # noqa: E402

print("== fixtext_paths ==")
show("frozen", getattr(sys, "frozen", False))
root = P.pkg_root()
show("pkg_root", root)
check("pkg_root 存在且是包根", os.path.isdir(root) and os.path.isdir(os.path.join(root, "fixtext_ui")),
      str(root))
rules = root / "data" / "rules"
workspace = root / "workspace"
runs = root / "runs"
show("data/rules", rules)
show("workspace", workspace)
show("runs", runs)

r = str(rules)
files = sorted(os.listdir(r)) if os.path.isdir(r) else []
show("rules 文件", files)
check("词库目录可用（含 before/after.json）",
      os.path.isfile(os.path.join(r, "before.json")) and os.path.isfile(os.path.join(r, "after.json")))

import fixtext_ui.main_window as mw  # noqa: E402

print("== main_window ==")
show("PKG_ROOT", getattr(mw, "PKG_ROOT", "<未定义>"))
check("main_window.PKG_ROOT == pkg_root",
      os.path.abspath(str(getattr(mw, "PKG_ROOT", ""))) == os.path.abspath(root),
      str(getattr(mw, "PKG_ROOT", None)))

print("== 引擎（按平台取）==")
try:
    eng = mw.MainWindow._pick_engine()
except Exception as exc:  # noqa: BLE001
    eng = None
    show("_pick_engine 异常", f"{type(exc).__name__}: {exc}")
show("_pick_engine()", eng)
if eng:
    check("引擎文件存在", os.path.isfile(eng), str(eng))
    check("Linux 上取到 linux 二进制", os.path.basename(str(eng)).endswith("linux-amd64"),
          os.path.basename(str(eng)))
    check("Linux 上不取 windows 二进制", "windows" not in os.path.basename(str(eng)).lower())
else:
    check("引擎文件存在", False)

print("== 其它消费方根目录 ==")
import fixtext_ui.fixtext_settings as st  # noqa: E402

os.environ.pop("FIXTEXT_SETTINGS_FILE", None)   # 取默认落点
_sp = st.settings_path()
show("settings_path()", _sp)
check("设置文件默认落在包内 workspace/",
      os.path.abspath(str(_sp)) == os.path.abspath(os.path.join(root, "workspace", "settings.ini")),
      str(_sp))
check("settings.PKG_ROOT == pkg_root",
      os.path.abspath(str(st.PKG_ROOT)) == os.path.abspath(root), str(st.PKG_ROOT))

import fixtext_ui.fixtext_vocab as vb  # noqa: E402

show("vocab workspace 根", getattr(vb, "WORKSPACE_DIR", getattr(vb, "_WORKSPACE", "<无>")))
check("vocab 根目录 == pkg_root/workspace",
      os.path.abspath(str(getattr(vb, "CUSTOM_DIR", ""))) == os.path.abspath(os.path.join(root, "workspace", "vocab")),
      str(getattr(vb, "CUSTOM_DIR", None)))
check("vocab 规则目录 == pkg_root/data/rules",
      os.path.abspath(str(getattr(vb, "RULES_DIR", ""))) == os.path.abspath(str(rules)),
      str(getattr(vb, "RULES_DIR", None)))

import fixtext_ui.import_module as imp  # noqa: E402


_dw = imp.default_workspace()
show("import 默认工作区", _dw)
check("import 默认工作区 == pkg_root/workspace",
      _dw is not None and os.path.abspath(str(_dw)) == os.path.abspath(os.path.join(root, "workspace")),
      str(_dw))

import fixtext_error_center.diaglog as dl  # noqa: E402

_ld = dl.log_dir()
show("diaglog.log_dir()", _ld)
check("日志根在包内 logs", "logs" in str(_ld), str(_ld))

import fixtext_ui.fixtext_export as ex  # noqa: E402

_pr = ex.ensure_vendor(None)
show("export ensure_vendor(None)", _pr)
check("export 默认 pipeline 根 == pkg_root/pipeline",
      os.path.abspath(str(_pr)) == os.path.abspath(os.path.join(root, "pipeline")), str(_pr))

import fixtext_pipeline.engine_choice as ec  # noqa: E402

show("engine_choice 模块", getattr(ec, "__name__", "?"))
_m = __import__("fixtext_pipeline._roots", fromlist=["x"])
pr = _m.pkg_root()
show("_roots.pkg_root()", pr)
check("pipeline _roots.pkg_root() == pkg_root",
      os.path.abspath(str(pr)) == os.path.abspath(root), str(pr))

_ecs = ec.settings_file()
show("engine_choice.settings_file()", _ecs)
check("engine_choice 设置落点 == pkg_root/workspace/settings.ini",
      os.path.abspath(str(_ecs)) == os.path.abspath(os.path.join(root, "workspace", "settings.ini")),
      str(_ecs))

print()
print("RESULT:", "PASS" if not fails else f"FAIL {fails}")
sys.exit(0 if not fails else 1)
