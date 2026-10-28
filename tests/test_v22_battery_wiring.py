"""test_v22_battery_wiring.py - kapsülde yalnız pil + pil panelindeki ses/parlaklık bağlantısı (v22).

Zero side effects: preview-mode dock; volume coalescer, mute, brightness worker and
save_settings are replaced with recorders. Real volume / brightness are never touched.
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

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

spec = importlib.util.spec_from_file_location("serit_v5_v22b", str(APP_DIR / "serit_v5.pyw"))
assert spec is not None and spec.loader is not None
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v22b_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None

import dock_cards  # noqa: E402

CALLS: list = []


def _dock(battery: bool = True):
    QApplication.instance() or QApplication([])
    d = serit_mod.SeritDock({"style": "band"}, preview_mode=True)
    d._bat_info = {"present": True, "percent": 63.0, "charging": True} if battery else {"present": False}
    d._vol_coalescer.request = lambda lvl, force=False: CALLS.append(("vol", round(lvl)))
    d.submit_fetch = lambda key: None
    return d


def _paint(d) -> None:
    img = QImage(1600, int(serit_mod.DOCK_HEIGHT), QImage.Format.Format_ARGB32_Premultiplied)
    d.resize(1600, int(serit_mod.DOCK_HEIGHT))
    p = QPainter(img)
    try:
        d._draw_quick_pill(p, QRectF(1300, 16, d._pill_width(), 32), False, False)
    finally:
        p.end()


def test_battery_only_pill_when_battery_present() -> None:
    d = _dock(True)
    d.hit_boxes = []
    _paint(d)
    keys = [k for _, k, _ in d.hit_boxes]
    assert keys == ["bat"], keys
    assert d._pill_width() == dock_cards.BATTERY_PILL_W


def test_old_pill_without_battery() -> None:
    d = _dock(False)
    d.hit_boxes = []
    _paint(d)
    keys = [k for _, k, _ in d.hit_boxes]
    assert keys == ["bright", "vol"], keys
    assert d._pill_width() == serit_mod.ACTION_PILL_WIDTH


def test_panel_signals_wired() -> None:
    d = _dock(True)
    CALLS.clear()
    d.preview_mode = False
    old_submit = serit_mod.sources.submit
    serit_mod.sources.submit = lambda key, fn, cb=None: CALLS.append(("submit", key)) or True
    bright: list = []
    d._on_brightness_requested = lambda mid, lvl: bright.append((mid, lvl))
    try:
        d._vol_muted = True
        d.battery_panel.volume_requested.emit(40.0)
        d.battery_panel.mute_requested.emit(True)
    finally:
        serit_mod.sources.submit = old_submit
        d.preview_mode = True
    assert ("vol", 40) in CALLS
    assert ("submit", "vol_mute") in CALLS, "ses açılınca sessiz kalkmalı"
    assert d._vol_level == 40.0


def test_brightness_signal_goes_to_existing_path() -> None:
    d = _dock(True)
    seen: list = []
    d.preview_mode = True
    d.store.update("bright", [{"id": "mon_0", "name": "Dizüstü", "level": 50, "ok": True}])
    d.battery_panel.brightness_requested.emit("mon_0", 70)
    mons = d._get_store_monitors()
    assert mons and mons[0]["level"] == 70, mons
    assert seen == []


def test_push_controls_to_panel() -> None:
    d = _dock(True)
    d._vol_level, d._vol_muted = 55.0, False
    got: list = []
    d.battery_panel.set_volume = lambda lvl, muted=False, device=None: got.append(("vol", lvl, muted))
    d.battery_panel.set_brightness = lambda mons: got.append(("bright", len(mons)))
    d._push_bat_panel_controls()
    assert ("vol", 55.0, False) in got and any(g[0] == "bright" for g in got)


def test_chevrons_open_full_panels() -> None:
    d = _dock(True)
    opened: list = []
    d.vol_popover.show_for = lambda *a, **k: opened.append("vol")
    d.brightness_popover.show_for = lambda *a, **k: opened.append("bright")
    d.battery_panel.open_volume_mixer.emit()
    d.battery_panel.open_brightness.emit()
    assert opened == ["vol", "bright"], opened


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("ALL PASSED")
