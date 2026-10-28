"""test_v22_battery.py - yalnız pil kapsülü + pil panelinde ses/parlaklık.

Gerçek ses/parlaklık/radyo API'si ASLA çağrılmaz; panel yalnız çizer ve sinyal yayar.
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import battery_panel  # noqa: E402
import dock_cards  # noqa: E402

OUT = APP_DIR / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication([])

GREEN = QColor("#30D158")
OLD_BLUE = QColor("#0A84FF")
BG = QColor(20, 22, 26)

BAT = {"present": True, "percent": 63, "plugged": False, "charging": False, "secs_left": 1320,
       "rate_w": 58.2, "full_mwh": 48686, "design_mwh": 61538, "capacity_pct": 79, "source": "Windows"}
WIFI = {"available": True, "on": True, "connected": True, "ssid": "Ev_Agi_5G", "signal": 81}
BT = {"available": True, "on": False, "connected_count": 0}
LAPTOP = {"id": "wmi:l", "name": "Dizüstü", "kind": "wmi", "level": 67, "ok": True}
EXT = {"id": "ddc:m", "name": "MSI MP223", "kind": "ddc", "level": 82, "ok": True}
BAD = {"id": "ddc:x", "name": "Dell U2720", "kind": "ddc", "level": None, "ok": False}


# --------------------------------------------------------------------------- yardımcılar
def _near(c: QColor, target: QColor, tol: int = 12) -> bool:
    return (abs(c.red() - target.red()) <= tol
            and abs(c.green() - target.green()) <= tol
            and abs(c.blue() - target.blue()) <= tol)


def _contains(img: QImage, target: QColor, tol: int = 12) -> bool:
    for y in range(img.height()):
        for x in range(img.width()):
            if _near(img.pixelColor(x, y), target, tol):
                return True
    return False


def _bbox_of(img: QImage, target: QColor, tol: int = 40) -> tuple[int, int, int, int] | None:
    x0 = y0 = 10 ** 9
    x1 = y1 = -1
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() > 128 and _near(c, target, tol):
                x0, y0 = min(x0, x), min(y0, y)
                x1, y1 = max(x1, x), max(y1, y)
    return None if x1 < 0 else (x0, y0, x1, y1)


def _pill(percent, charging, name, dpr=1.0, hovered=False, active=False):
    w, h = 120.0, 48.0
    img = QImage(max(1, int(w * dpr)), max(1, int(h * dpr)), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(8.0, 8.0, dock_cards.BATTERY_PILL_W, 32.0)
    ret = dock_cards.draw_battery_pill(p, rect, percent, charging, hovered=hovered, active=active)
    p.end()
    img.save(str(OUT / f"{name}.png"))
    return img, rect, ret


def _mouse(t, pt, btn=Qt.MouseButton.LeftButton):
    return QMouseEvent(t, QPointF(pt), QPointF(pt), btn, btn, Qt.KeyboardModifier.NoModifier)


def _wheel(pt, dy=120):
    return QWheelEvent(QPointF(pt), QPointF(pt), QPoint(0, 0), QPoint(0, dy),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)


def _panel(volume=72.0, muted=False, monitors=None):
    pnl = battery_panel.BatteryPanel()
    pnl.set_battery(BAT)
    pnl.set_wifi(WIFI)
    pnl.set_bluetooth(BT)
    pnl.set_volume(volume, muted, "Speakers")
    pnl.set_brightness([dict(m) for m in (monitors if monitors is not None else [LAPTOP, EXT])])
    pnl.render_to_image(2.0)
    return pnl


def _load_head_module():
    src = subprocess.check_output(["git", "show", "HEAD:dock_cards.py"], cwd=str(APP_DIR))
    mod = types.ModuleType("dock_cards_head")
    mod.__file__ = str(APP_DIR / "dock_cards.py")
    exec(compile(src.decode("utf-8"), mod.__file__, "exec"), mod.__dict__)
    return mod


def _head_pill_rects(mod, **kw):
    img = QImage(300, 60, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    res = mod.draw_quick_settings_pill(p, QRectF(20.0, 14.0, dock_cards.PILL_W_3, 32.0), **kw)
    p.end()
    return res


# --------------------------------------------------------------------------- kapsül
def test_pill_constant_and_geometry():
    assert 76.0 <= dock_cards.BATTERY_PILL_W <= 84.0
    img, rect, ret = _pill(99, False, "v22_pill_99_bat_dpr1", 1.0)
    assert isinstance(ret, QRectF) and ret == rect          # tüm kapsül tek isabet alanı
    assert ret.width() == dock_cards.BATTERY_PILL_W


def test_pill_states_all_dprs():
    for dpr in (1.0, 1.25, 2.0):
        tag = str(dpr).replace(".", "_")
        img_chg, rect, _ = _pill(99, True, f"v22_pill_99_chg_dpr{tag}", dpr)
        img_bat, _, _ = _pill(99, False, f"v22_pill_99_bat_dpr{tag}", dpr)
        _pill(50, False, f"v22_pill_50_dpr{tag}", dpr)
        _pill(15, False, f"v22_pill_15_dpr{tag}", dpr)
        _pill(3, True, f"v22_pill_3_dpr{tag}", dpr)
        _pill(99, False, f"v22_pill_hover_dpr{tag}", dpr, hovered=True)
        _pill(99, False, f"v22_pill_active_dpr{tag}", dpr, active=True)

        # şarj: yeşil var
        assert _contains(img_chg, GREEN), f"şarj glifinde yeşil yok dpr={dpr}"
        # boşta: yeşil ve eski mavi yok
        assert not _contains(img_bat, GREEN), f"boşta yeşil var dpr={dpr}"
        assert not _contains(img_bat, OLD_BLUE), f"boşta eski mavi var dpr={dpr}"

        # glif + metin kapsül dikdörtgeninin içinde ve kenara değmiyor (kırpılmıyor)
        for img, target in ((img_chg, GREEN), (img_bat, QColor(255, 255, 255))):
            bb = _bbox_of(img, target)
            assert bb is not None
            x0, y0, x1, y1 = [v / dpr for v in bb]
            assert x0 >= rect.left() + 0.5 and x1 <= rect.right() - 0.5, (bb, rect, dpr)
            assert y0 >= rect.top() + 0.5 and y1 <= rect.bottom() - 0.5, (bb, rect, dpr)


def test_pill_c_badge_tint():
    """v23 sade pil: zemin yok (bant rengi aynen kalır); üzerine gelince hafif gri zemin; simge renkli."""
    def render(percent, charging, hovered=False):
        img = QImage(96, 48, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(13, 15, 19))
        p = QPainter(img)
        dock_cards.draw_battery_pill(p, QRectF(8.0, 8.0, dock_cards.BATTERY_PILL_W, 32.0), percent, charging,
                                     hovered=hovered)
        p.end()
        return img

    for pct, chg in ((99.0, True), (15.0, False), (64.0, False)):
        bg = render(pct, chg).pixelColor(14, 24)  # sol kenara yakın, içerik dışı
        assert (bg.red(), bg.green(), bg.blue()) == (13, 15, 19), (pct, chg, bg.name())
        out = render(pct, chg).pixelColor(4, 24)  # kapsül dışı: ışıma yok
        assert (out.red(), out.green(), out.blue()) == (13, 15, 19), (pct, chg, out.name())
    hov = render(64.0, False, hovered=True).pixelColor(14, 24)
    d = (hov.red() - 13, hov.green() - 15, hov.blue() - 19)
    assert d[0] > 0 and max(d) - min(d) <= 2, (hov.name(), d)  # renksiz gri, hafif
    assert _contains(render(99.0, True), GREEN), "şarjda simge yeşil olmalı"


def test_pill_sheet():
    """1.0 dpr çizimlerini 4x büyütüp tek sayfada topla."""
    names = ["v22_pill_99_chg_dpr1_0", "v22_pill_99_bat_dpr1_0", "v22_pill_50_dpr1_0",
             "v22_pill_15_dpr1_0", "v22_pill_3_dpr1_0", "v22_pill_hover_dpr1_0",
             "v22_pill_active_dpr1_0"]
    labels = ["%99 şarj", "%99 pil", "%50", "%15", "%3 şarj", "hover", "active"]
    zoom = 4
    imgs = []
    for n in names:
        im = QImage(str(OUT / f"{n}.png"))
        imgs.append(im.scaled(im.width() * zoom, im.height() * zoom,
                              Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation))
    w = max(i.width() for i in imgs) + 20
    h = sum(i.height() + 26 for i in imgs) + 10
    sheet = QImage(w, h, QImage.Format.Format_ARGB32)
    sheet.fill(QColor(10, 11, 13))
    p = QPainter(sheet)
    p.setPen(QColor(255, 255, 255))
    p.setFont(QFont("Segoe UI", 10))
    y = 6
    for label, im in zip(labels, imgs):
        p.drawText(10, y + 14, label)
        y += 20
        p.drawImage(10, y, im)
        y += im.height() + 6
    p.end()
    sheet.save(str(OUT / "v22_pill_sheet.png"))
    assert (OUT / "v22_pill_sheet.png").exists()


# --------------------------------------------------------------------------- panel
def test_panel_renders():
    cases = {
        "v22_panel_full": _panel(72.0, False),
        "v22_panel_muted": _panel(72.0, True),
        "v22_panel_bright_unsupported": _panel(72.0, False, monitors=[BAD]),
        "v22_panel_volume_none": _panel(None, False),
    }
    for name, pnl in cases.items():
        assert pnl.width() == 352
        assert pnl.height() == pnl.compute_height()
        img = pnl.render_to_image(2.0)
        img.save(str(OUT / f"{name}.png"))

    full = cases["v22_panel_full"]
    assert full._av["vol"]["draggable"] and full._av["bright"]["draggable"]
    assert full._av["bright"]["monitor"]["id"] == "wmi:l"
    muted = cases["v22_panel_muted"]
    assert muted._muted and muted._av["vol"]["draggable"]
    unsup = cases["v22_panel_bright_unsupported"]
    assert not unsup._av["bright"]["draggable"] and unsup._bright_monitor() is None
    none = cases["v22_panel_volume_none"]
    assert not none._av["vol"]["draggable"] and none._volume is None


def test_panel_sheet():
    """Panel render'larını tek sayfada topla (görsel denetim için)."""
    names = ["v22_panel_full", "v22_panel_muted", "v22_panel_bright_unsupported", "v22_panel_volume_none"]
    labels = ["tam veri", "ses sessiz", "parlaklık desteklenmiyor", "ses verisi yok"]
    scale = 0.62
    tiles = []
    for n in names:
        im = QImage(str(OUT / f"{n}.png"))
        tw = int(im.width() * scale)
        th = int(im.height() * scale)
        tiles.append(im.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation))
    gap = 16
    col_w = max(t.width() for t in tiles)
    row_h = max(t.height() for t in tiles) + 26
    sheet = QImage(col_w * 2 + gap * 3, row_h * 2 + gap * 3, QImage.Format.Format_ARGB32)
    sheet.fill(QColor(10, 11, 13))
    p = QPainter(sheet)
    p.setPen(QColor(230, 233, 240))
    p.setFont(QFont("Segoe UI", 11))
    for i, (label, im) in enumerate(zip(labels, tiles)):
        cx = gap + (i % 2) * (col_w + gap)
        cy = gap + (i // 2) * (row_h + gap)
        p.drawText(cx, cy + 16, label)
        p.drawImage(cx, cy + 22, im)
    p.end()
    sheet.save(str(OUT / "v22_battery_sheet.png"))
    assert (OUT / "v22_battery_sheet.png").exists()


def test_panel_slider_drag_signals():
    pnl = _panel(40.0)
    vols = []
    pnl.volume_requested.connect(vols.append)
    tr = pnl._av["vol"]["track"]
    y = tr.center().y()
    pnl.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, QPointF(tr.left() + tr.width() * 0.25, y)))
    assert pnl._drag == "vol" and vols and abs(vols[-1] - 25.0) <= 1.0
    pnl.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, QPointF(tr.left() + tr.width() * 0.60, y)))
    assert abs(vols[-1] - 60.0) <= 1.0
    pnl.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, QPointF(tr.left() + tr.width() * 0.60, y)))
    assert pnl._drag is None
    assert all(0.0 <= v <= 100.0 for v in vols)

    # sürükleme sırasında set_volume tutacı geri zıplatmasın
    pnl.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, QPointF(tr.left() + tr.width() * 0.25, y)))
    before = pnl._volume
    pnl.set_volume(90.0, False, "Speakers")
    assert pnl._volume == before
    pnl.render_to_image(2.0)
    assert pnl._volume == before
    pnl.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, QPointF(tr.left() + tr.width() * 0.25, y)))


def test_panel_brightness_drag_signal():
    pnl = _panel(40.0, monitors=[EXT, LAPTOP])   # harici önce gelse de dizüstü seçilir
    assert pnl._av["bright"]["monitor"]["id"] == "wmi:l"
    got = []
    pnl.brightness_requested.connect(lambda mid, lvl: got.append((mid, lvl)))
    tr = pnl._av["bright"]["track"]
    y = tr.center().y()
    pnl.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, QPointF(tr.left() + tr.width() * 0.50, y)))
    pnl.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, QPointF(tr.left() + tr.width() * 0.80, y)))
    pnl.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, QPointF(tr.left() + tr.width() * 0.80, y)))
    assert got and all(mid == "wmi:l" for mid, _ in got)
    assert 0 <= got[-1][1] <= 100 and abs(got[-1][1] - 80) <= 1
    assert pnl._drag is None


def test_panel_mute_and_chevrons():
    pnl = _panel(40.0)
    mute = []
    pnl.mute_requested.connect(mute.append)
    pnl.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pnl._av["vol"]["icon_rect"].center()))
    assert mute == [True]
    pnl.set_volume(40.0, True, "Speakers")
    pnl.render_to_image(2.0)
    pnl.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, pnl._av["vol"]["icon_rect"].center()))
    assert mute[-1] is False

    opened = []
    pnl.open_volume_mixer.connect(lambda: opened.append("vol"))
    pnl.open_brightness.connect(lambda: opened.append("bright"))
    pnl.activate("vol_chev")
    pnl.activate("bright_chev")
    assert opened == ["vol", "bright"]


def test_panel_wheel():
    pnl = _panel(40.0)
    vols = []
    pnl.volume_requested.connect(vols.append)
    pnl.wheelEvent(_wheel(pnl._av["vol"]["row_rect"].center(), 120))
    assert vols and abs(vols[-1] - 42.0) <= 0.5
    brights = []
    pnl.brightness_requested.connect(lambda mid, lvl: brights.append((mid, lvl)))
    pnl.wheelEvent(_wheel(pnl._av["bright"]["row_rect"].center(), 120))
    assert brights and brights[-1][0] == "wmi:l" and brights[-1][1] == 69


def test_panel_public_api_kept():
    pnl = battery_panel.BatteryPanel()
    for name in ("set_battery", "set_wifi", "set_bluetooth", "set_top_load", "set_supported",
                 "set_busy", "is_busy", "is_open", "recently_closed", "show_for",
                 "hide_animated", "hide_instant", "panel_x", "activate", "compute_height",
                 "set_volume", "set_brightness", "render_to_image"):
        assert callable(getattr(pnl, name)), name
    for sig in ("toggle_requested", "settings_requested", "volume_requested", "mute_requested",
                "brightness_requested", "open_volume_mixer", "open_brightness"):
        assert hasattr(pnl, sig), sig
    pnl.hide_instant()


def test_quick_settings_pill_geometry_unchanged():
    head = _load_head_module()
    cases = [
        dict(bat_present=True, bat_percent=63, bat_charging=False, hovered_part="bat"),
        dict(bat_present=True, bat_percent=30, bat_charging=True, active_part="bat"),
        dict(bat_present=False),
        dict(bat_present=True, bat_percent=None),
    ]
    for kw in cases:
        new = _head_pill_rects(dock_cards, **kw)
        old = _head_pill_rects(head, **kw)
        assert len(new) == len(old), kw
        for rn, ro in zip(new, old):
            assert abs(rn.x() - ro.x()) < 1e-9, (kw, rn, ro)
            assert abs(rn.width() - ro.width()) < 1e-9, (kw, rn, ro)
            assert abs(rn.y() - ro.y()) < 1e-9 and abs(rn.height() - ro.height()) < 1e-9


def run_all():
    for fn in (test_pill_constant_and_geometry, test_pill_states_all_dprs, test_pill_c_badge_tint, test_pill_sheet,
               test_panel_renders, test_panel_sheet, test_panel_slider_drag_signals,
               test_panel_brightness_drag_signal, test_panel_mute_and_chevrons,
               test_panel_wheel, test_panel_public_api_kept,
               test_quick_settings_pill_geometry_unchanged):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V22_BATTERY TESTS PASSED")


if __name__ == "__main__":
    run_all()
