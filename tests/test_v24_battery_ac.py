"""test_v24_battery_ac.py - prizde + dolu iken fiş + "Prizde", panelde pil sağlığı satırı (v24).

Zero side effects: offscreen QImage renders with sample battery dicts; no real battery/power call.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import battery_panel  # noqa: E402
import dock_cards  # noqa: E402
import panel_style as ps  # noqa: E402

DPR = 1.25
FULL_AC = {"present": True, "percent": 99, "plugged": True, "charging": False, "rate_w": 0.0,
           "full_mwh": 48686, "design_mwh": 61538, "capacity_pct": 79, "source": "Windows"}
CHARGING = dict(FULL_AC, percent=64, charging=True)
ON_BAT = dict(FULL_AC, percent=64, plugged=False, rate_w=12.0)


def _pill(on_ac_full: bool, hovered: bool = False) -> QImage:
    img = QImage(int(100 * DPR), int(48 * DPR), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    img.fill(QColor(13, 15, 19))
    p = QPainter(img)
    dock_cards.draw_battery_pill(p, QRectF(10, 8, dock_cards.BATTERY_PILL_W, 32), 99.0, True,
                                 hovered=hovered, on_ac_full=on_ac_full)
    p.end()
    return img


def _ink(img: QImage) -> tuple:
    xs, ys, green = [], [], 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            if max(abs(c.red() - 13), abs(c.green() - 15), abs(c.blue() - 19)) > 40:
                xs.append(x)
                ys.append(y)
                if c.green() > c.red() + 40 and c.green() > c.blue() + 20:
                    green += 1
    return min(xs) / DPR, min(ys) / DPR, (max(xs) + 1) / DPR, (max(ys) + 1) / DPR, green


def test_state_helpers() -> None:
    assert battery_panel.on_ac_full(FULL_AC)
    assert not battery_panel.on_ac_full(CHARGING)
    assert not battery_panel.on_ac_full(ON_BAT)
    assert not battery_panel.on_ac_full(dict(FULL_AC, percent=90))  # prizde ama dolu değil
    assert battery_panel.state_label(FULL_AC) == "Prizden çalışıyor"
    assert battery_panel.pill_tooltip(FULL_AC) == "%99 · Prizden çalışıyor"
    assert battery_panel.pill_tooltip(dict(FULL_AC, percent=90)) == "%90 · Prizde"


def test_health_parts() -> None:
    lbl, val, right, col = battery_panel.health_parts(FULL_AC)
    assert (lbl, val, right) == ("Pil sağlığı ", "%79", "48,7 / 61,5 Wh")
    assert col == ps.TEXT_BODY  # %79 alarm değil
    assert battery_panel.health_parts(dict(FULL_AC, capacity_pct=65))[3] == ps.WARN
    assert battery_panel.health_parts(dict(FULL_AC, capacity_pct=45))[3] == ps.DANGER
    assert battery_panel.health_parts(dict(FULL_AC, full_mwh=None)) is None  # uydurma yok
    assert battery_panel.health_parts(dict(FULL_AC, capacity_pct=None))[1] == "—"


def test_plug_glyph_drawn_centred_and_green() -> None:
    x0, y0, x1, y1, green = _ink(_pill(True))
    assert green > 40, green
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    assert abs(cx - (10 + dock_cards.BATTERY_PILL_W / 2.0)) <= 1.5, (x0, x1)
    assert abs(cy - 24.0) <= 1.0, (y0, y1)
    assert x0 >= 10 and x1 <= 10 + dock_cards.BATTERY_PILL_W  # kapsülden taşmaz


def test_hover_and_default_keep_percent_view() -> None:
    plain = _pill(False)
    assert _pill(True, hovered=True).bits().tobytes() != _pill(True).bits().tobytes()
    # varsayılan (on_ac_full=False) eski çizimle aynı: parametre eklemek görünümü değiştirmez
    p2 = QImage(plain.size(), plain.format())
    p2.setDevicePixelRatio(DPR)
    p2.fill(QColor(13, 15, 19))
    p = QPainter(p2)
    dock_cards.draw_battery_pill(p, QRectF(10, 8, dock_cards.BATTERY_PILL_W, 32), 99.0, True)
    p.end()
    assert p2 == plain


def test_panel_card_has_health_row_not_header_capacity() -> None:
    texts = []
    orig_card = ps.draw_card

    def spy(p, rect, overline=None, overline_right=None, hover=False):
        texts.append((overline, overline_right))
        return orig_card(p, rect, overline, overline_right, hover)

    ps.draw_card = spy
    try:
        pn = battery_panel.BatteryPanel()
        pn.set_battery(FULL_AC)
        pn.resize(pn.WIDTH, pn.compute_height())
        pn.render_to_image(DPR)
    finally:
        ps.draw_card = orig_card
    bat_card = [t for t in texts if t[0] == "Pil durumu"]
    assert bat_card and bat_card[0][1] is None, texts


def run_all() -> None:
    for fn in (test_state_helpers, test_health_parts, test_plug_glyph_drawn_centred_and_green,
               test_hover_and_default_keep_percent_view, test_panel_card_has_health_row_not_header_capacity):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V24_BATTERY_AC TESTS PASSED")


if __name__ == "__main__":
    run_all()
