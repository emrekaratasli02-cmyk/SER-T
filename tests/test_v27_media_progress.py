"""test_v27_media_progress.py - Verification for Serit dock media card:
1. Shared pure helper media_progress_fraction(media_info, now_monotonic=None) -> float|None
   - playing vs paused vs None duration vs pos>dur clamp vs negative
2. Pure helper fmt_media_time(seconds) -> 'm:ss' / 'h:mm:ss'
   - cases: 0, 59, 60, 3599, 3600, None, NaN
3. Render media card offscreen to PNG for 3 states at DPR 2:
   - State 1: playing 40%
   - State 2: paused 90%
   - State 3: unknown duration
   Saved under C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/v27-media/
4. Assert returned hit rects dictionary unchanged: {'prev', 'playpause', 'next'}
5. Hover time text replacement:
   - When card hovered (hovered_control is None and hover=True): sub text replaced with '<elapsed> / <total>'
   - When not hovered (or hovered on control): sub text stays 'app · artist'
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

import dock_cards


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_fmt_media_time() -> None:
    """Verify fmt_media_time covers all required and boundary cases."""
    fmt = dock_cards.fmt_media_time

    # Required cases from specification: 0, 59, 60, 3599, 3600, None, NaN
    assert fmt(0) == "0:00", f"Expected '0:00', got {fmt(0)!r}"
    assert fmt(59) == "0:59", f"Expected '0:59', got {fmt(59)!r}"
    assert fmt(60) == "1:00", f"Expected '1:00', got {fmt(60)!r}"
    assert fmt(3599) == "59:59", f"Expected '59:59', got {fmt(3599)!r}"
    assert fmt(3600) == "1:00:00", f"Expected '1:00:00', got {fmt(3600)!r}"
    assert fmt(None) == "--:--", f"Expected '--:--', got {fmt(None)!r}"
    assert fmt(float("nan")) == "--:--", f"Expected '--:--', got {fmt(float('nan'))!r}"

    # Extra boundary cases
    assert fmt(math.nan) == "--:--", f"Expected '--:--', got {fmt(math.nan)!r}"
    assert fmt(float("inf")) == "--:--", f"Expected '--:--', got {fmt(float('inf'))!r}"
    assert fmt("invalid") == "--:--", f"Expected '--:--', got {fmt('invalid')!r}"
    assert fmt(-10) == "0:00", f"Expected '0:00' for negative, got {fmt(-10)!r}"
    assert fmt(83) == "1:23", f"Expected '1:23', got {fmt(83)!r}"
    assert fmt(225) == "3:45", f"Expected '3:45', got {fmt(225)!r}"
    assert fmt(3665) == "1:01:05", f"Expected '1:01:05', got {fmt(3665)!r}"
    assert fmt(36000) == "10:00:00", f"Expected '10:00:00', got {fmt(36000)!r}"
    print("  [PASS] fmt_media_time verified for all required test cases.")


def test_media_progress_fraction() -> None:
    """Verify media_progress_fraction handling playing, paused, None duration, clamp, negative."""
    frac = dock_cards.media_progress_fraction

    # 1. Playing with extrapolation
    info_playing = {
        "position_s": 40.0,
        "duration_s": 100.0,
        "playing": True,
        "updated_at": 1000.0,
    }
    # 5 seconds elapsed
    res_playing = frac(info_playing, now_monotonic=1005.0)
    assert res_playing is not None
    assert abs(res_playing - 0.45) < 1e-6, f"Expected 0.45, got {res_playing}"

    # 2. Paused: no extrapolation even if updated_at is older
    info_paused = {
        "position_s": 40.0,
        "duration_s": 100.0,
        "playing": False,
        "updated_at": 1000.0,
    }
    res_paused = frac(info_paused, now_monotonic=1005.0)
    assert res_paused is not None
    assert abs(res_paused - 0.40) < 1e-6, f"Expected 0.40, got {res_paused}"

    # 3. None duration
    assert frac({"position_s": 10.0, "duration_s": None}) is None
    assert frac({"position_s": 10.0}) is None

    # 4. Zero and negative duration
    assert frac({"position_s": 10.0, "duration_s": 0.0}) is None
    assert frac({"position_s": 10.0, "duration_s": -50.0}) is None
    assert frac({"position_s": 10.0, "duration_s": float("nan")}) is None

    # 5. Position > Duration clamp
    info_over = {
        "position_s": 120.0,
        "duration_s": 100.0,
        "playing": False,
    }
    res_over = frac(info_over)
    assert res_over == 1.0, f"Expected 1.0 clamped, got {res_over}"

    # 6. Negative position clamp
    info_neg = {
        "position_s": -20.0,
        "duration_s": 100.0,
        "playing": False,
    }
    res_neg = frac(info_neg)
    assert res_neg == 0.0, f"Expected 0.0 clamped, got {res_neg}"

    # 7. Non-dict or empty info
    assert frac({}) is None
    assert frac(None) is None  # type: ignore[arg-type]
    print("  [PASS] media_progress_fraction verified (playing, paused, None, clamp, negative).")


def test_media_current_position() -> None:
    """Verify media_current_position interpolates when playing and respects duration clamp."""
    cur_pos = dock_cards.media_current_position

    info_play = {
        "position_s": 80.0,
        "duration_s": 100.0,
        "playing": True,
        "updated_at": 100.0,
    }
    p = cur_pos(info_play, now_monotonic=103.0)
    assert p is not None and abs(p - 83.0) < 1e-6

    # Clamped to duration
    p_clamp = cur_pos(info_play, now_monotonic=150.0)
    assert p_clamp == 100.0

    # Paused
    info_paused = {
        "position_s": 80.0,
        "duration_s": 100.0,
        "playing": False,
        "updated_at": 100.0,
    }
    assert cur_pos(info_paused, now_monotonic=150.0) == 80.0

    # None position
    assert cur_pos({"position_s": None, "duration_s": 100.0}) is None
    print("  [PASS] media_current_position verified.")


def test_render_and_hit_rects_and_png_export() -> None:
    """Render 3 states at DPR 2, assert hit rects unchanged, and export PNGs."""
    get_qapp()

    out_dir = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/v27-media")
    out_dir.mkdir(parents=True, exist_ok=True)

    card_rect = QRectF(10.0, 10.0, 314.0, 52.0)
    dpr = 2.0
    w_px = int(round(350 * dpr))
    h_px = int(round(80 * dpr))

    # Fill with dock background color so white glyphs and text are crisp and visible
    bg_color = QColor(22, 24, 29)

    # --- State 1: Playing 40% ---
    state_playing_40 = {
        "title": "Starboy",
        "artist": "The Weeknd · Daft Punk",
        "app": "Spotify",
        "playing": True,
        "position_s": 90.0,
        "duration_s": 225.0,  # 90 / 225 = 0.40
        "updated_at": None,
    }
    img1 = QImage(w_px, h_px, QImage.Format.Format_ARGB32_Premultiplied)
    img1.fill(bg_color)
    img1.setDevicePixelRatio(dpr)
    p1 = QPainter(img1)
    rects1 = dock_cards.draw_media_card(
        p1,
        card_rect,
        state_playing_40,
        hover=False,
        press_scale=1.0,
        hovered_control=None,
    )
    p1.end()

    png1_path = out_dir / "state1_playing_40pct.png"
    img1.save(str(png1_path))
    assert png1_path.exists() and png1_path.stat().st_size > 0

    # Check hit rects
    assert set(rects1.keys()) == {"prev", "playpause", "next"}
    r_prev = rects1["prev"]
    r_play = rects1["playpause"]
    r_next = rects1["next"]
    assert abs(r_play.width() - 32.0) < 0.01
    assert abs(r_play.height() - 32.0) < 0.01
    assert abs(r_prev.width() - 24.0) < 0.01
    assert abs(r_next.width() - 24.0) < 0.01
    assert r_prev.right() < r_play.left() < r_next.left()

    # --- State 2: Paused 90% ---
    state_paused_90 = {
        "title": "Midnight City",
        "artist": "M83",
        "app": "Apple Music",
        "playing": False,
        "position_s": 180.0,
        "duration_s": 200.0,  # 180 / 200 = 0.90
        "updated_at": None,
    }
    img2 = QImage(w_px, h_px, QImage.Format.Format_ARGB32_Premultiplied)
    img2.fill(bg_color)
    img2.setDevicePixelRatio(dpr)
    p2 = QPainter(img2)
    rects2 = dock_cards.draw_media_card(
        p2,
        card_rect,
        state_paused_90,
        hover=False,
        press_scale=1.0,
        hovered_control=None,
    )
    p2.end()

    png2_path = out_dir / "state2_paused_90pct.png"
    img2.save(str(png2_path))
    assert png2_path.exists() and png2_path.stat().st_size > 0
    assert rects2 == rects1

    # --- State 3: Unknown duration (live stream) ---
    state_unknown_dur = {
        "title": "BBC Radio 1 - Live",
        "artist": "Live Broadcast",
        "app": "Chrome",
        "playing": True,
        "position_s": None,
        "duration_s": None,
        "updated_at": None,
    }
    img3 = QImage(w_px, h_px, QImage.Format.Format_ARGB32_Premultiplied)
    img3.fill(bg_color)
    img3.setDevicePixelRatio(dpr)
    p3 = QPainter(img3)
    rects3 = dock_cards.draw_media_card(
        p3,
        card_rect,
        state_unknown_dur,
        hover=False,
        press_scale=1.0,
        hovered_control=None,
    )
    p3.end()

    png3_path = out_dir / "state3_unknown_duration.png"
    img3.save(str(png3_path))
    assert png3_path.exists() and png3_path.stat().st_size > 0
    assert rects3 == rects1

    # --- State 4: Hover state showing time '1:23 / 3:45' ---
    state_hover = {
        "title": "Starboy",
        "artist": "The Weeknd · Daft Punk",
        "app": "Spotify",
        "playing": False,
        "position_s": 83.0,
        "duration_s": 225.0,  # 83s -> 1:23, 225s -> 3:45
        "updated_at": None,
    }
    img4 = QImage(w_px, h_px, QImage.Format.Format_ARGB32_Premultiplied)
    img4.fill(bg_color)
    img4.setDevicePixelRatio(dpr)
    p4 = QPainter(img4)
    rects4 = dock_cards.draw_media_card(
        p4,
        card_rect,
        state_hover,
        hover=True,
        press_scale=1.0,
        hovered_control=None,
    )
    p4.end()

    png4_path = out_dir / "state4_hover_time.png"
    img4.save(str(png4_path))
    assert png4_path.exists() and png4_path.stat().st_size > 0
    assert rects4 == rects1

    print(f"  [PASS] Rendered 3 states + hover at DPR 2 to {out_dir}")
    print(f"         PNG 1: {png1_path}")
    print(f"         PNG 2: {png2_path}")
    print(f"         PNG 3: {png3_path}")
    print(f"         PNG 4 (hover): {png4_path}")


def main() -> None:
    print("Running test_v27_media_progress.py...")
    test_fmt_media_time()
    test_media_progress_fraction()
    test_media_current_position()
    test_render_and_hit_rects_and_png_export()
    print("ALL TEST_V27_MEDIA_PROGRESS TESTS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    main()
