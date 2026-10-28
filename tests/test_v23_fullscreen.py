"""test_v23_fullscreen.py - tam ekran uygulama öndeyken bar gizlenir, çıkınca geri gelir (v23).

Zero side effects: preview-mode dock; winapi.foreground_fullscreen is replaced with a stub.
No real window is read, moved or hidden apart from the test's own dock widget.
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

spec = importlib.util.spec_from_file_location("serit_v5_v23fs", str(APP_DIR / "serit_v5.pyw"))
assert spec is not None and spec.loader is not None
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v23fs_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None

import winapi  # noqa: E402

STATE = {"fs": False, "calls": 0}


def _stub(own_pid=None, dock_hwnd=None):
    STATE["calls"] += 1
    return STATE["fs"]


def _dock():
    QApplication.instance() or QApplication([])
    d = serit_mod.SeritDock({"style": "band"}, preview_mode=True)
    serit_mod.winapi.foreground_fullscreen = _stub
    d.show()
    return d


def test_hides_and_returns() -> None:
    d = _dock()
    d.preview_mode = False
    try:
        STATE["fs"] = False
        d._check_fullscreen()
        assert d.isVisible() and not d._fs_hidden
        STATE["fs"] = True
        d._check_fullscreen()
        assert not d.isVisible() and d._fs_hidden
        d._check_fullscreen()  # aynı durum: tekrar gizleme/gösterme yok
        assert not d.isVisible()
        STATE["fs"] = False
        d._check_fullscreen()
        assert d.isVisible() and not d._fs_hidden
    finally:
        d.preview_mode = True
        d.hide()


def test_setting_off_and_preview_never_hide() -> None:
    d = _dock()
    STATE["fs"] = True
    d._check_fullscreen()  # preview: hiç sormaz, gizlemez
    assert d.isVisible()
    d.preview_mode = False
    d.settings["hide_on_fullscreen"] = False
    try:
        STATE["calls"] = 0
        d._check_fullscreen()
        assert d.isVisible() and STATE["calls"] == 0
    finally:
        d.preview_mode = True
        d.hide()


def test_covers_monitor_rules() -> None:
    mon = (0, 0, 1920, 1080)
    assert winapi.covers_monitor((0, 0, 1920, 1080), mon)            # gerçek tam ekran
    assert winapi.covers_monitor((-1, -1, 1921, 1081), mon)          # taşan tam ekran
    assert not winapi.covers_monitor((-8, -8, 1928, 1008), mon)      # büyütülmüş pencere (alt boşluk)
    assert not winapi.covers_monitor((100, 100, 900, 700), mon)      # normal pencere
    assert winapi.covers_monitor((1920, 0, 3840, 1080), (1920, 0, 3840, 1080))  # ikinci monitör
    assert not winapi.covers_monitor((0, 0, 50, 50), (0, 0, 50, 50))  # anlamsız küçük monitör
    assert not winapi.covers_monitor(("x", 0, 0, 0), mon)            # bozuk veri


def test_zoomed_caption_rule() -> None:
    mon = (0, 0, 1920, 1080)
    # Chrome tam ekran: büyütülmüş bayrağı açık ama başlık çubuğu yok -> tam ekran
    assert winapi.is_fullscreen_window((0, 0, 1920, 1080), mon, zoomed=True, has_caption=False)
    # Görev çubuğu gizliyken büyütülmüş pencere ekranı kaplar ama başlık çubuğu var -> tam ekran değil
    assert not winapi.is_fullscreen_window((-8, -8, 1928, 1088), mon, zoomed=True, has_caption=True)
    # Kenarlıksız oyun / video oynatıcı
    assert winapi.is_fullscreen_window((0, 0, 1920, 1080), mon, zoomed=False, has_caption=False)
    # Normal pencere
    assert not winapi.is_fullscreen_window((100, 100, 900, 700), mon, zoomed=False, has_caption=True)


def test_real_call_is_safe_and_fast() -> None:
    """Gerçek çağrı yalnız okur; hata vermez ve bool döner (değeri ortama bağlı, kontrol edilmez)."""
    import time
    real = importlib.reload(importlib.import_module("winapi")).foreground_fullscreen
    t = time.perf_counter()
    r = real(os.getpid())
    assert isinstance(r, bool)
    assert (time.perf_counter() - t) < 0.05


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("ALL PASSED")
