"""test_v27_marquee.py - kayan medya başlığı ve sade güncellemeler rozeti."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import dock_cards  # noqa: E402
import settings_window  # noqa: E402
import updates  # noqa: E402

DPR = 1.25
CARD = QRectF(10.0, 6.0, 314.0, 52.0)
LONG = "The Mentalist · 7. Sezon 13. Bölüm · Kırmızı John'un Son Oyunu"
SHORT = "Kısa"


def _render(title: str, offset):
    img = QImage(int(340 * DPR), int(64 * DPR), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    img.fill(QColor(13, 15, 19))
    p = QPainter(img)
    dock_cards.draw_media_card(p, CARD, {"title": title, "app": "Chrome", "artist": "Web", "playing": True},
                               title_offset=offset)
    p.end()
    return img


def _title_strip(img: QImage) -> bytes:
    bx, bw = dock_cards.media_title_layout(CARD)
    return bytes(img.copy(int(bx * DPR), int(14 * DPR), int(bw * DPR), int(16 * DPR)).constBits())


def test_overflow_only_for_long_titles() -> None:
    assert dock_cards.media_title_overflow(CARD, SHORT) == 0.0
    assert dock_cards.media_title_overflow(CARD, LONG) > 40.0


def test_offset_curve_pauses_scrolls_and_returns() -> None:
    ov = 100.0
    f = dock_cards.marquee_offset
    pause = dock_cards.MARQUEE_PAUSE_S
    travel = ov / dock_cards.MARQUEE_SPEED_PX_S
    assert f(0.0, ov) == 0.0 and f(pause * 0.9, ov) == 0.0          # başta bekler
    mid = f(pause + travel / 2.0, ov)
    assert 40.0 < mid < 60.0                                          # yolun ortası
    assert f(pause + travel + pause * 0.5, ov) == ov                 # sonda bekler
    assert f(2 * (pause + travel) - 0.001, ov) < 1.0                 # başa döner
    assert f(5.0, 0.0) == 0.0                                         # taşma yoksa hiç kaymaz
    prev = -1.0
    for i in range(50):                                               # kayış monoton
        v = f(pause + travel * i / 49.0, ov)
        assert v >= prev - 1e-9
        prev = v


def test_scrolled_title_actually_moves_and_stays_clipped() -> None:
    a = _render(LONG, 0.0)
    b = _render(LONG, 60.0)
    assert _title_strip(a) != _title_strip(b), "ofset başlığı kaydırmalı"
    # başlık önceki düğmesinin üstüne taşmamalı
    bx, bw = dock_cards.media_title_layout(CARD)
    x_ctrl = int((bx + bw + 3.0) * DPR)
    for img in (a, b):
        for x in range(x_ctrl, x_ctrl + int(4 * DPR)):
            for y in range(int(14 * DPR), int(26 * DPR)):
                assert QColor(img.pixel(x, y)).lightness() < 60, (x, y)


def test_short_title_ignores_offset() -> None:
    assert _title_strip(_render(SHORT, None)) == _title_strip(_render(SHORT, 50.0))


def test_marquee_toggle_in_settings() -> None:
    keys = [k for k, *_ in settings_window.TOOL_DEFS]
    assert "media_marquee_enabled" in keys
    assert settings_window.SETTING_DEFAULTS["media_marquee_enabled"] is True


def test_updates_badge_has_no_blue() -> None:
    img = QImage(int(38 * DPR), int(30 * DPR), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(DPR)
    img.fill(QColor(13, 15, 19))
    p = QPainter(img)
    updates.draw_updates_badge(p, QRectF(0, 0, 38.0, 30.0), {"count": 28}, hover=False)
    p.end()
    inked = 0
    for x in range(img.width()):
        for y in range(img.height()):
            c = QColor(img.pixel(x, y))
            assert c.blue() - c.red() < 25, f"mavi piksel kaldı: {c.name()}"
            inked += c.lightness() > 60
    assert inked > 20, "rozet hâlâ görünür olmalı"


def test_idle_netspeed_is_muted_and_active_keeps_colour() -> None:
    import netspeed

    def render(state):
        img = QImage(int(70 * DPR), int(40 * DPR), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(DPR)
        img.fill(QColor(13, 15, 19))
        p = QPainter(img)
        netspeed.draw_net_band(p, QRectF(4, 4, 62, 32), state)
        p.end()
        return img

    def colourful(img) -> int:
        n = 0
        for x in range(img.width()):
            for y in range(img.height()):
                c = QColor(img.pixel(x, y))
                n += (max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue())) > 40
        return n

    assert colourful(render({"down": 0, "up": 0, "visible": True})) == 0, "boşta renkli ok kalmamalı"
    assert colourful(render({"down": 250_000, "up": 30_000, "visible": True})) > 5, "trafikte oklar renkli"


def test_tray_chevron_rest_matches_neighbours() -> None:
    def peak(hover: bool) -> int:
        img = QImage(int(30 * DPR), int(30 * DPR), QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(DPR)
        img.fill(QColor(0, 0, 0))
        p = QPainter(img)
        dock_cards.draw_action_button(p, QRectF(0, 0, 30, 30), "tray", hover=hover)
        p.end()
        return max(QColor(img.pixel(x, y)).red() for x in range(img.width()) for y in range(img.height()))

    assert peak(False) <= 175, peak(False)   # ~%65 beyaz
    assert peak(True) >= 230                  # üzerine gelince parlak


def run_all() -> None:
    for fn in (test_overflow_only_for_long_titles, test_offset_curve_pauses_scrolls_and_returns,
               test_scrolled_title_actually_moves_and_stays_clipped, test_short_title_ignores_offset,
               test_marquee_toggle_in_settings, test_updates_badge_has_no_blue,
               test_idle_netspeed_is_muted_and_active_keeps_colour, test_tray_chevron_rest_matches_neighbours):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V27_MARQUEE TESTS PASSED")


if __name__ == "__main__":
    run_all()
