"""test_v19_battery.py - pil bolumu (kapsul), pil paneli, kablosuz anahtarlar. Gercek radyo/ayar ASLA cagrilmaz."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import battery_panel  # noqa: E402
import dock_cards  # noqa: E402
import panel_style as ps  # noqa: E402
import power_net  # noqa: E402

OUT = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v19")
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication([])

spec = importlib.util.spec_from_file_location("serit_v5", str(APP_DIR / "serit_v5.pyw"))
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v19_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None

BAT_ON = {"present": True, "percent": 63, "plugged": False, "charging": False, "secs_left": 1320,
          "rate_w": 58.2, "full_mwh": 48686, "design_mwh": 61538, "capacity_pct": 79, "source": "Windows"}
BAT_CHG = dict(BAT_ON, percent=30, plugged=True, charging=True, secs_left=None, rate_w=46.0)
BAT_LOW = dict(BAT_ON, percent=15, rate_w=12.0)
WIFI_ON = {"available": True, "on": True, "connected": True, "ssid": "Ev_Agi_5G", "signal": 81}
WIFI_OFF = {"available": True, "on": False, "connected": False, "ssid": None, "signal": None}
BT_ON = {"available": True, "on": True, "connected_count": 0}
BT_OFF = {"available": True, "on": False, "connected_count": 0}
BT_NA = {"available": False, "on": False, "connected_count": 0}


def _pill(name, **kw):
    img = QImage(300, 60, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img = QImage(600, 120, QImage.Format_ARGB32_Premultiplied)
    img.fill(0xFF14161A)
    img.setDevicePixelRatio(2.0)
    p = QPainter(img)
    res = dock_cards.draw_quick_settings_pill(p, QRectF(20, 14, dock_cards.pill_width(kw.get("bat_present", False)), 32), **kw)
    p.end()
    img.save(str(OUT / f"{name}.png"))
    return res


def test_pill_geometry_and_hidden():
    res = _pill("band_bat_normal", bat_present=True, bat_percent=63, bat_charging=False, hovered_part="bat")
    assert len(res) == 3
    r_sun, r_spk, r_bat = res
    assert abs(r_sun.right() - r_spk.left()) < 0.01 and abs(r_spk.right() - r_bat.left()) < 0.01
    assert abs(r_bat.right() - (20 + 136)) < 0.01 and r_bat.width() > 40
    _pill("band_bat_charging", bat_present=True, bat_percent=30, bat_charging=True, active_part="bat")
    _pill("band_bat_low", bat_present=True, bat_percent=15, bat_charging=False)
    r2 = _pill("band_bat_none", bat_present=False)
    assert len(r2) == 2
    assert len(_pill("band_bat_unknown", bat_present=True, bat_percent=None)) == 2


def test_color_rule():
    c = dock_cards.battery_color
    assert c(30, True).name() == "#0a84ff"
    assert c(20, False).name() == "#ff453a" and c(21, False).name() == "#ff9f0a"
    assert c(35, False).name() == "#ff9f0a" and c(36, False).name() == "#ffffff"
    assert battery_panel.level_color(15, False) == ps.DANGER
    assert battery_panel.level_color(30, False) == ps.WARN
    assert battery_panel.level_color(30, True) == ps.ACCENT
    assert battery_panel.level_color(80, False) == ps.OK


def test_dock_layout():
    dock = serit_mod.SeritDock({"style": "band"}, preview_mode=True)
    sw = 1536.0
    nonlocal_sw = [sw]
    dock.resize(int(sw), 64)

    def layout(bat):
        dock._bat_info = bat
        dock.compute_layout_and_resize(initial=True)
        nonlocal_sw[0] = float(dock.width())
        img = QImage(int(sw), 64, QImage.Format.Format_ARGB32)
        dock.render(img)
        boxes = {k: r for r, k, _e in dock.hit_boxes if k in ("tray", "bright", "vol", "bat", "clock")}
        return boxes

    b = layout(BAT_ON)
    assert set(b) >= {"bright", "vol", "bat", "clock"}
    assert abs(nonlocal_sw[0] - b["clock"].right() - 14.0) <= 0.5
    assert b["bat"].right() < b["clock"].left() and b["tray"].right() < b["bright"].left()
    assert abs(b["bat"].right() - b["bright"].left() - 136.0) < 0.01
    b = layout({})
    assert "bat" not in b and abs(nonlocal_sw[0] - b["clock"].right() - 14.0) <= 0.5
    assert abs(b["vol"].right() - b["bright"].left() - 74.0) < 0.01
    b = layout(dict(BAT_ON, present=False))
    assert "bat" not in b
    assert battery_panel.pill_tooltip(BAT_ON) == "%63 · Pilde · ~22 dk kaldı"
    assert battery_panel.pill_tooltip(BAT_CHG) == "%30 · Şarj oluyor"
    assert battery_panel.pill_tooltip({}) is None
    dock.close()


def _panel(bat, wifi, bt, top=None):
    pnl = battery_panel.BatteryPanel()
    pnl.set_battery(bat)
    pnl.set_wifi(wifi)
    pnl.set_bluetooth(bt)
    if top is not None:
        pnl.set_top_load(top)
    return pnl


def test_panel_states_and_renders():
    assert battery_panel.BatteryPanel.WIDTH == 352
    top = [{"name": "Chrome", "cpu": 14.0}, {"name": "Hermes", "cpu": 6.0}]
    cases = {
        "on_battery": _panel(BAT_ON, WIFI_ON, BT_OFF, top),
        "charging": _panel(BAT_CHG, WIFI_ON, BT_OFF, top),
        "low": _panel(BAT_LOW, WIFI_ON, BT_ON),
        "wifi_off": _panel(BAT_ON, WIFI_OFF, BT_ON),
        "bt_unavailable": _panel(BAT_ON, WIFI_ON, BT_NA),
    }
    busy = _panel(BAT_ON, WIFI_ON, BT_OFF)
    busy.set_busy("wifi", False)
    cases["busy"] = busy
    for name, pnl in cases.items():
        assert pnl.width() == 352
        pnl.render_to_image(2.0).save(str(OUT / f"pil_paneli_{name}.png"))
    assert cases["on_battery"].show_top_load() and not cases["charging"].show_top_load()
    assert not cases["low"].show_top_load()   # top listesi bos + rate < 35
    assert battery_panel.chip_text(BAT_ON) == "Pilde · ~58 W"
    assert battery_panel.chip_text(BAT_CHG) == "Şarj oluyor"
    assert battery_panel.chip_text(BAT_LOW) == "Düşük pil"
    assert cases["wifi_off"]._toggle_texts("wifi") == ("Wi-Fi", "Kapalı")
    assert cases["on_battery"]._toggle_texts("wifi") == ("Ev_Agi_5G", "Sinyal %81")
    assert cases["bt_unavailable"]._toggle_texts("bluetooth") == ("Bluetooth", "Kullanılamıyor")
    assert cases["busy"]._toggle_texts("wifi")[1] == "Kapatılıyor…"
    assert battery_panel.fmt_mwh(48686) == "48.686"
    assert battery_panel.fmt_remaining(1320) == "~22 dk kaldı"
    # top-load yalniz pilde ve rate >= 35
    low_rate = _panel(dict(BAT_ON, rate_w=20.0), WIFI_ON, BT_ON, top)
    assert not low_rate.show_top_load()
    assert not _panel(BAT_ON, WIFI_ON, BT_ON).show_top_load()


def test_toggle_goes_to_worker_not_real():
    # gercek set_wifi test altinda RuntimeError atar: dogrudan cagrilmadigini da dogrula
    try:
        power_net.set_wifi(True)
        raise AssertionError("set_wifi guard yok")
    except RuntimeError:
        pass
    pnl = _panel(BAT_ON, WIFI_ON, BT_OFF)
    pnl.show()
    got, settings = [], []
    pnl.toggle_requested.connect(lambda k, on: got.append((k, on)))
    pnl.settings_requested.connect(settings.append)
    pnl.render_to_image(1.0)
    r = pnl._rects
    pnl.activate("wifi_main")
    assert got == [("wifi", False)] and pnl._toggle_state("wifi") == "busy"
    pnl.activate("wifi_main")           # busy: yok say
    assert len(got) == 1
    pnl.activate("bt_main")
    assert got[-1] == ("bluetooth", True)
    na = _panel(BAT_ON, WIFI_ON, BT_NA)
    got2 = []
    na.toggle_requested.connect(lambda k, on: got2.append(k))
    na.activate("bt_main")
    assert got2 == []
    pnl.set_wifi(WIFI_OFF)               # yeniden okuma busy'yi temizler
    assert pnl._toggle_state("wifi") == "off"
    pnl.activate("bt_chev")
    assert settings == ["bluetooth"]
    pnl.activate("footer_btn")
    assert settings[-1] == "power"
    assert {"close", "wifi_main", "wifi_chev", "bt_main", "bt_chev", "footer_btn"} <= set(r)
    pnl.hide()


def test_dock_routes_to_mocked_worker():
    dock = serit_mod.SeritDock({}, preview_mode=True)
    calls = []
    real_submit = serit_mod.sources.submit
    serit_mod.sources.submit = lambda key, fn, cb=None: calls.append(key) or True
    try:
        dock._on_bat_toggle_requested("wifi", False)
        dock._on_bat_settings_requested("wifi")
    finally:
        serit_mod.sources.submit = real_submit
    assert calls == ["bat_set_wifi", "bat_settings"]
    dock.close()


def run_all():
    for fn in (test_pill_geometry_and_hidden, test_color_rule, test_dock_layout,
               test_panel_states_and_renders, test_toggle_goes_to_worker_not_real, test_dock_routes_to_mocked_worker):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V19_BATTERY TESTS PASSED")


if __name__ == "__main__":
    run_all()
