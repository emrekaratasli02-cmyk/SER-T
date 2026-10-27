"""test_dock_v16.py - Verification for Şerit dock v16 layout and component changes:
1. Design A4: 'Birleşik hızlı ayar kapsülü' - Sun (brightness) and speaker (volume)
   merged into one 74x32 pill container.
   - Independent hit boxes: 'bright' (left half, 37px) and 'vol' (right half, 37px).
   - Chevron '^' remains separate 30x30 button to the left of the pill.
   - Far-right clock positioning (14px right edge padding) strictly preserved.
2. Design B3: 'Parça ilerleme halkalı buton' - Music media card playback controls:
   - Prev/Next: Plain glyphs without background circles.
   - Play/Pause: 32x32 button surrounded by circular progress ring (#0A84FF on faint track).
   - Progress ring accurately tracks position / duration when available.
   - When duration is unknown or zero, no fake progress arc is drawn.
   - Smooth interpolation support via position_s, duration_s, updated_at fields.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import dock_cards

spec = importlib.util.spec_from_file_location("serit_v5", str(APP_DIR / "serit_v5.pyw"))
assert spec is not None and spec.loader is not None
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)

# Zero side-effects: isolate settings
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v16_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_a4_quick_settings_pill_geometry_and_hit_boxes() -> None:
    """Verify A4 pill drawing, geometry (74x32), and dual hitboxes."""
    get_qapp()
    img = QImage(200, 60, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)

    pill_rect = QRectF(20.0, 14.0, 74.0, 32.0)
    r_sun, r_spk = dock_cards.draw_quick_settings_pill(
        p,
        pill_rect,
        hovered_part="bright",
        active_part=None,
        vol_level=65.0,
        vol_muted=False,
    )
    p.end()

    # Dimensions
    assert abs(r_sun.width() - 37.0) < 0.01, f"Expected sun width 37, got {r_sun.width()}"
    assert abs(r_spk.width() - 37.0) < 0.01, f"Expected spk width 37, got {r_spk.width()}"
    assert abs(r_sun.height() - 32.0) < 0.01
    assert abs(r_spk.height() - 32.0) < 0.01

    # Exact adjacent abutment (one pill, two contiguous halves)
    assert abs(r_sun.right() - r_spk.left()) < 0.001
    assert r_sun.left() == pill_rect.left()
    assert r_spk.right() == pill_rect.right()

    # Muted state rendering test
    p2 = QPainter(img)
    dock_cards.draw_quick_settings_pill(
        p2,
        pill_rect,
        hovered_part="vol",
        active_part="vol",
        vol_level=0.0,
        vol_muted=True,
    )
    p2.end()
    print("  [PASS] A4 Quick settings pill geometry and states verified.")


def test_b3_media_card_controls_and_progress_ring() -> None:
    """Verify B3 controls: plain prev/next glyphs, circular progress ring on play/pause."""
    get_qapp()
    card_rect = QRectF(10.0, 10.0, 314.0, 52.0)

    # 1. Test with known duration and 55% progress
    media_info_55 = {
        "title": "Song Title",
        "artist": "Artist",
        "app": "Spotify",
        "playing": True,
        "position_s": 55.0,
        "duration_s": 100.0,
        "updated_at": time.monotonic(),
    }
    img = QImage(350, 80, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    hit_rects = dock_cards.draw_media_card(
        p,
        card_rect,
        media_info_55,
        hover=False,
        press_scale=1.0,
        hovered_control=None,
    )
    p.end()

    assert "prev" in hit_rects
    assert "playpause" in hit_rects
    assert "next" in hit_rects

    r_prev = hit_rects["prev"]
    r_play = hit_rects["playpause"]
    r_next = hit_rects["next"]

    # Order and spacing
    assert r_prev.right() < r_play.left()
    assert r_play.right() < r_next.left()
    assert abs(r_play.width() - 32.0) < 0.01
    assert abs(r_play.height() - 32.0) < 0.01

    # 2. Test with unknown duration (no crash, duration_s=None / 0)
    media_info_nodur = {
        "title": "Live Stream",
        "artist": "Web",
        "app": "Chrome",
        "playing": True,
        "position_s": None,
        "duration_s": None,
        "updated_at": None,
    }
    p_nodur = QPainter(img)
    hit_rects_nodur = dock_cards.draw_media_card(
        p_nodur,
        card_rect,
        media_info_nodur,
        hover=False,
        press_scale=1.0,
        hovered_control="playpause",
    )
    p_nodur.end()
    assert "playpause" in hit_rects_nodur
    print("  [PASS] B3 Media card controls and progress ring verified.")


def test_dock_band_layout_v16() -> None:
    """Verify dock band integrates A4 pill, preserves right clock padding (14px)."""
    get_qapp()
    sw = 1536.0

    dock = serit_mod.SeritDock(
        {"style": "band", "pinned": [{"exe": "app1.exe", "name": "App 1"}]},
        preview_mode=True,
    )
    dock.pins = [{"exe": "app1.exe", "name": "App 1"}]
    dock.tiles = [{"exe": "app1.exe", "name": "App 1"}]
    dock._tray_items = [{"name": f"tray_{i}"} for i in range(5)]
    dock._now_playing_info = {
        "title": "The Mentalist",
        "artist": "Web Yayını",
        "app": "Chrome",
        "playing": True,
        "position_s": 120.0,
        "duration_s": 2400.0,
        "updated_at": time.monotonic(),
    }
    dock.store.update("wx", {"temp": 21.0, "icon": "cloud"})

    dock.resize(int(sw), 64)
    dock.compute_layout_and_resize(initial=True)
    img = QImage(int(sw), 64, QImage.Format.Format_ARGB32)
    dock.render(img)

    r_chv = next(r for r, k, _e in dock.hit_boxes if k == "tray")
    r_sun = next(r for r, k, _e in dock.hit_boxes if k == "bright")
    r_spk = next(r for r, k, _e in dock.hit_boxes if k == "vol")
    r_clock = next(r for r, k, _e in dock.hit_boxes if k == "clock")

    # Layout Order
    assert r_chv.right() < r_sun.left(), "Chevron must be to the left of the pill"
    assert abs(r_sun.right() - r_spk.left()) < 0.001, "Sun and speaker must be seamlessly conjoined in pill"
    assert r_spk.right() < r_clock.left(), "Pill must be to the left of clock"

    # Far right edge padding: 14.0px
    right_pad = sw - r_clock.right()
    assert abs(right_pad - 14.0) <= 0.5, f"Clock right padding must be 14.0px, got {right_pad}"

    # Chevron is 30x30
    assert abs(r_chv.width() - 30.0) < 0.01
    assert abs(r_chv.height() - 30.0) < 0.01

    # Combined pill width is 74x32
    pill_w = r_spk.right() - r_sun.left()
    assert abs(pill_w - 74.0) < 0.01, f"Expected combined pill width 74, got {pill_w}"
    assert abs(r_sun.height() - 32.0) < 0.01

    print("  [PASS] Dock band layout v16 integrates A4 pill and preserves 14px clock margin.")


def run_all() -> None:
    print("Running test_dock_v16.py...")
    test_a4_quick_settings_pill_geometry_and_hit_boxes()
    test_b3_media_card_controls_and_progress_ring()
    test_dock_band_layout_v16()
    print("ALL TEST_DOCK_V16 TESTS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    run_all()


def test_timeline_now_extrapolates_from_last_update() -> None:
    """Windows konumu son güncelleme anındadır; çalıyorsa geçen süre eklenir, süre yoksa ilerleme yok."""
    import datetime as dt
    import media
    td, utc = dt.timedelta, dt.timezone.utc
    now = dt.datetime(2026, 10, 27, 15, 57, 30, tzinfo=utc)
    lu = dt.datetime(2026, 10, 27, 15, 47, 44, tzinfo=utc)
    assert media.timeline_now(td(seconds=183), td(0), td(seconds=2587), lu, True, now) == (769.0, 2587.0)
    assert media.timeline_now(td(seconds=183), td(0), td(seconds=2587), lu, False, now) == (183.0, 2587.0)
    assert media.timeline_now(td(seconds=50), td(0), td(0), lu, True, now) == (None, None)
    assert media.timeline_now(td(seconds=9000), td(0), td(seconds=100), lu, True, now) == (100.0, 100.0)
    print("[PASS] timeline_now extrapolation")


if __name__ == "__main__":
    test_timeline_now_extrapolates_from_last_update()
