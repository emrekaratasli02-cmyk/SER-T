"""test_v21_settings_wiring.py - Sağ tık 'Ayarlar…' ve 'Uygula' bağlantısı (v21).

Zero side effects: preview-mode dock, save_settings and every taskbar / AppBar call are
replaced with recorders; the real settings.json is never written.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

from PySide6.QtWidgets import QApplication  # noqa: E402

spec = importlib.util.spec_from_file_location("serit_v5_wiring", str(APP_DIR / "serit_v5.pyw"))
assert spec is not None and spec.loader is not None
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)

serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v21w_")) / "settings.json"
SAVED: list = []
serit_mod.save_settings = lambda cfg: SAVED.append(dict(cfg))
TASKBAR_CALLS: list = []
serit_mod.winapi.taskbar_autohide_set = lambda enable: TASKBAR_CALLS.append(bool(enable))
serit_mod.winapi.taskbar_autohide_get = lambda: False

import settings_window  # noqa: E402


def _dock(cfg: dict):
    QApplication.instance() or QApplication([])
    d = serit_mod.SeritDock(dict(cfg), preview_mode=True)
    d.appbar_calls = []
    d._register_appbar = lambda: d.appbar_calls.append("reg") or True
    d._unregister_appbar = lambda: d.appbar_calls.append("unreg")
    return d


def test_menu_has_settings_first() -> None:
    d = _dock({"style": "band"})
    acts = d.build_dock_menu_actions()
    assert acts[0]["id"] == "settings" and acts[0]["text"] == "Ayarlar…", acts[0]
    assert callable(acts[0]["callback"])


def test_apply_cards_alerts_pins_reserve() -> None:
    SAVED.clear()
    TASKBAR_CALLS.clear()
    d = _dock({"style": "band", "alerts_enabled": True, "reserve_space": True, "hide_taskbar": False,
               "cards": {"mail": True}, "pinned": [{"exe": "a.exe", "name": "A"}, {"exe": "b.exe", "name": "B"}]})
    d.apply_settings_from_window({"style": "band", "alerts_enabled": False, "reserve_space": False,
                                  "hide_taskbar": False, "cards": {"mail": False, "sys": True},
                                  "pinned": [{"exe": "b.exe", "name": "B"}]})
    assert d.settings["cards"] == {"mail": False, "sys": True}
    assert d.settings["alerts_enabled"] is False
    assert d.settings["reserve_space"] is False
    assert [p["exe"] for p in d.pins] == ["b.exe"]
    assert d.appbar_calls == ["unreg"], d.appbar_calls
    assert TASKBAR_CALLS == [], "görev çubuğu değişmediyse dokunulmamalı"
    assert SAVED == [], "önizleme modunda kayıt yok"


def test_apply_style_and_taskbar_change_only_when_changed() -> None:
    TASKBAR_CALLS.clear()
    d = _dock({"style": "band", "hide_taskbar": False})
    d.preview_mode = True
    d.apply_settings_from_window({"style": "pill", "hide_taskbar": True})
    assert d.settings["style"] == "pill"
    assert d.settings["hide_taskbar"] is True
    assert TASKBAR_CALLS == [True]
    TASKBAR_CALLS.clear()
    d.apply_settings_from_window(dict(d.settings))  # aynı ayarlar: hiçbir yan etki yok
    assert TASKBAR_CALLS == []


def test_open_settings_single_window_with_provider() -> None:
    d = _dock({"style": "band"})

    class FakeMon:
        def stats(self):
            return {"count": 2, "worst_ms": 640, "last": []}

    d.stall_monitor = FakeMon()
    d.action_open_settings()
    win = d._settings_win
    assert isinstance(win, settings_window.SettingsWindow)
    assert win.isVisible()
    d.action_open_settings()
    assert d._settings_win is win, "ikinci tık yeni pencere açmamalı"
    win.close()
    win.deleteLater()


def test_garbage_apply_is_ignored() -> None:
    d = _dock({"style": "band"})
    before = dict(d.settings)
    d.apply_settings_from_window(None)  # type: ignore[arg-type]
    assert d.settings == before


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("ALL PASSED")
