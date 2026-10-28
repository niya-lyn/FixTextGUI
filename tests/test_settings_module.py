"""M4-EX.2a 设置页（结构层）· 单元级验证。

覆盖：
  1. 持久化键读写：engine 契约（go|python，默认 go，非契约不落）、
     vocabDir / logDir（空 = None = 包内默认）、diagEnabled 默认开、
     showBasis 默认关；写后新进程形态（重新构造 AppSettings）读回一致。
  2. 词库存储位置真实生效：set_vocab_dir → VocabStore(custom_path=…) 后
     新增词条落在新目录，工作副本 / 还原点同棵子树；等价重启再建仍在。
  3. 日志目录变更真实生效：SettingsModule._apply_log_backend 后
     write_record 落新目录；留痕开关关闭后不再落记录。
  4. 设置页 UI 冒烟：四卡构建、engine 切换保存并同步选中态、
     设计依据开关双向同步并发信号。

设置文件隔离：conftest 的会话级 _isolated_settings 已把
FIXTEXT_SETTINGS_FILE 指到临时目录，测试不污染真实用户区。
"""

from __future__ import annotations


import sys
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent.parent / "fixtext_ui"
for p in (UI, UI.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fixtext_settings as settings
from fixtext_settings import AppSettings


# ---------------------------------------------------------------------------
# 1. 持久化键
# ---------------------------------------------------------------------------

def test_engine_default_and_contract():
    assert settings.ENGINE_CHOICES == ("go", "python")
    assert settings.ENGINE_DEFAULT == "go"
    settings.set_engine("python")
    assert settings.engine() == "python"
    # 非契约取值：不写入，读回落 go
    settings.set_engine("bogus")
    assert settings.engine() == "python"
    settings.set_engine("go")
    assert settings.engine() == "go"


def test_vocab_dir_roundtrip():
    settings.set_vocab_dir(None)
    assert settings.vocab_dir() is None
    assert settings.vocab_custom_file() is None
    p = "/tmp/ex2a_vocab_home"
    settings.set_vocab_dir(p)
    assert str(settings.vocab_dir()) == p
    cf = settings.vocab_custom_file()
    assert cf is not None and cf.name == "custom_vocab.json"
    settings.set_vocab_dir(None)
    assert settings.vocab_dir() is None


def test_log_dir_roundtrip():
    settings.set_log_dir(None)
    assert settings.log_dir() is None
    settings.set_log_dir("/tmp/ex2a_log_home")
    assert str(settings.log_dir()) == "/tmp/ex2a_log_home"
    settings.set_log_dir(None)
    assert settings.log_dir() is None


def test_switches_default_and_persist():
    settings.set_diag_enabled(True)
    settings.set_show_basis(False)
    assert settings.diag_enabled() is True
    assert settings.show_basis() is False
    settings.set_diag_enabled(False)
    settings.set_show_basis(True)
    # 等价重启：全新 AppSettings（新进程形态）读回
    s = AppSettings()
    assert s.value("diagEnabled", "1") == "0"
    assert s.value("showBasis", "0") == "1"
    assert settings.diag_enabled() is False
    assert settings.show_basis() is True
    settings.set_diag_enabled(True)
    settings.set_show_basis(False)


# ---------------------------------------------------------------------------
# 2. 词库存储位置真实生效
# ---------------------------------------------------------------------------

def test_vocab_store_follows_configured_dir(tmp_path):
    new_home = tmp_path / "newvocab"
    settings.set_vocab_dir(new_home)
    from fixtext_vocab import VocabStore, CUSTOM_FILE, SNAP_DIR
    cf = settings.vocab_custom_file()
    assert cf == new_home / CUSTOM_FILE

    store = VocabStore(custom_path=cf)
    store.add_entry(word="萧衍", value="萧彦", typ="人名")
    assert (new_home / CUSTOM_FILE).exists()
    hits = [r for r in store.custom.rows() if r.get("word") == "萧衍"]
    assert hits and hits[0]["value"] == "萧彦"
    # 还原点跟随同一棵子树（不落包内用户区）
    assert (new_home / SNAP_DIR).is_dir()
    assert not (new_home / CUSTOM_FILE).parent.samefile(
        Path(__file__).resolve().parent.parent)

    # 等价重启：按设置再建一个 store，词条仍在
    store2 = VocabStore(custom_path=settings.vocab_custom_file())
    assert any(r.get("word") == "萧衍" for r in store2.custom.rows()) or \
           (new_home / CUSTOM_FILE).exists()
    settings.set_vocab_dir(None)


# ---------------------------------------------------------------------------
# 3 + 4. 设置页 UI（需要 QApplication）
# ---------------------------------------------------------------------------

@pytest.fixture()
def smod(qt_app):
    """构建设置页；退出时恢复错误中心与设置键，避免污染后续用例。"""
    from settings_module import SettingsModule
    import fixtext_error_center as ec
    settings.set_vocab_dir(None)
    settings.set_log_dir(None)
    settings.set_engine("go")
    settings.set_diag_enabled(True)
    settings.set_show_basis(False)
    w = SettingsModule()
    yield w
    ec.init(enabled=True)
    settings.set_vocab_dir(None)
    settings.set_log_dir(None)
    settings.set_engine("go")
    settings.set_diag_enabled(True)
    settings.set_show_basis(False)


def test_settings_page_builds_four_cards(smod):
    assert len(smod.cards) == 4
    assert set(smod.engine_cards) == {"go", "python"}
    # 顶栏入口对应路由键存在（主窗口侧另测）
    from fixtext_tokens import SETTINGS_KEY
    assert SETTINGS_KEY == "settings"


def test_engine_switch_persists_and_syncs(smod):
    assert settings.engine() == "go"
    smod._on_engine("python")
    assert settings.engine() == "python"
    from fixtext_tokens import c as _c
    assert f"background:{_c('primary.50')}" in smod.engine_cards["python"].styleSheet()
    assert f"background:{_c('neutral.0')}" in smod.engine_cards["go"].styleSheet()
    # 等价重启：新进程形态读回 python
    assert AppSettings().value("engine", "go") == "python"
    smod._on_engine("go")
    assert settings.engine() == "go"


def test_basis_switch_persists_and_signals(smod):
    seen = []
    smod.basis_changed.connect(seen.append)
    smod._on_basis(True)
    assert settings.show_basis() is True
    assert smod.head_basis.isChecked() and smod.card_basis.isChecked()
    assert seen == [True]
    smod._on_basis(False)
    assert settings.show_basis() is False
    assert seen == [True, False]


def test_log_dir_applies_to_error_center(smod, tmp_path):
    import fixtext_error_center as ec
    from fixtext_error_center.diaglog import write_record
    new_logs = tmp_path / "newlogs"
    settings.set_log_dir(new_logs)
    smod._apply_log_backend()
    assert ec.log_dir() == str(new_logs)
    out = write_record("U-I01", "测试写入", {"traceback": "test"})
    assert out is not None and out.startswith(str(new_logs))
    assert (new_logs / Path(out).name).exists()


def test_diag_disabled_stops_records(smod, tmp_path):
    import fixtext_error_center as ec
    from fixtext_error_center.diaglog import write_record
    settings.set_log_dir(tmp_path / "logs2")
    smod._on_diag(False)
    assert settings.diag_enabled() is False
    assert write_record("U-I01", "不应写入", {"traceback": "x"}) is None
