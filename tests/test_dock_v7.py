"""test_dock_v7.py - Comprehensive unit & integration tests for Serit dock v7 features:
1) Clock V1 'Sade' (dynamic text width, hit boxes, midnight date rollover)
2) Claude official symbol Option C with graceful fallback when SVG is missing
3) Tray cluster icon count shrinking when space is tight
4) Brightness pending-value coalescing and worker thread resubmission with set_level mocked
5) Band vs Pill hit boxes verification
"""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import dock_cards
import sources

# Import serit_v5 safely with isolated settings
spec = importlib.util.spec_from_file_location("serit_v5_v7", str(PROJECT_ROOT / "serit_v5.pyw"))
serit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serit_mod)
serit_mod.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v7_")) / "settings.json"
serit_mod.save_settings = lambda cfg: None


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_clock_v1_metrics_and_midnight_roll() -> None:
    """Verify Clock V1 dynamic width, hit boxes priority, and midnight rollover."""
    get_qapp()

    # 1. Midnight date rollover
    t_before_midnight = dt.datetime(2026, 10, 27, 23, 59, 0, tzinfo=sources.LOCAL_TZ)
    t_after_midnight = dt.datetime(2026, 10, 28, 0, 1, 0, tzinfo=sources.LOCAL_TZ)

    date_tue = dock_cards.format_clock_v1_date(t_before_midnight.date())
    date_wed = dock_cards.format_clock_v1_date(t_after_midnight.date())

    assert date_tue == "Sal, 27 Ekim", f"Expected 'Sal, 27 Ekim', got {date_tue}"
    assert date_wed == "Çar, 28 Ekim", f"Expected 'Çar, 28 Ekim', got {date_wed}"

    # 2. Dynamic width calculation (not fixed 70px)
    w_with_wx = dock_cards.measure_clock_v1_width(t_before_midnight, temp_str="16°", has_weather=True)
    w_no_wx = dock_cards.measure_clock_v1_width(t_before_midnight, temp_str=None, has_weather=False)

    assert w_with_wx > 100.0, f"Expected dynamic width > 100px with weather, got {w_with_wx}"
    assert w_no_wx < w_with_wx, f"Expected no-weather width ({w_no_wx}) < with-weather ({w_with_wx})"
    assert w_with_wx != 70.0, "Clock V1 width must not be fixed 70px"

    # 3. Hit boxes & weather priority
    img = QImage(300, 64, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    rect = QRectF(10.0, 6.0, w_with_wx, 52.0)
    r_clk, r_wx = dock_cards.draw_clock_v1(
        p, rect, temp_str="16°", hover=True, wx_icon="cloud", has_weather=True, now=t_before_midnight
    )
    p.end()

    assert r_clk == rect
    assert r_wx is not None
    assert r_wx.left() >= rect.left()  # hava durumu artık solda (27 Eki 2026), saat en sağda
    assert r_wx.right() <= rect.right()

    # Test hit priority: pos on weather portion hits wx first
    pos_weather = QPointF(r_wx.center().x(), r_wx.center().y())
    pos_time = QPointF(rect.right() - 20.0, rect.center().y())  # saat artık sağ kenarda

    hit_boxes = [(r_wx, "wx", None), (r_clk, "clock", None)]
    # First match wins (or reversed if checked reversed)
    # When clicking pos_weather:
    hit_wx = next(k for r, k, _e in hit_boxes if r.contains(pos_weather))
    assert hit_wx == "wx", f"Clicking weather area should resolve to 'wx', got {hit_wx}"

    hit_clk = next(k for r, k, _e in hit_boxes if r.contains(pos_time))
    assert hit_clk == "clock", f"Clicking time area should resolve to 'clock', got {hit_clk}"
    print("[PASS] Clock V1 metrics, hit boxes & midnight date roll verified.")


def test_claude_symbol_fallback() -> None:
    """Verify Claude symbol Option C renders with SVG and falls back to star if missing."""
    get_qapp()
    img = QImage(200, 64, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    rect = QRectF(0.0, 0.0, 182.0, 52.0)
    claude_data = {"session": 55, "week": 20, "session_reset": "4sa 12dk"}

    # 1. Normal render with existing SVG
    dock_cards.draw_claude_card(p, rect, claude_data)

    # 2. Render with non-existent SVG file
    with patch.object(dock_cards, "APP_DIR", Path(tempfile.gettempdir())):
        dock_cards._CLAUDE_SVG_CACHE.clear()
        # Must not raise, falls back to draw_claude_tile_star
        dock_cards.draw_claude_card(p, rect, claude_data)

    p.end()
    # Restore cache
    dock_cards._CLAUDE_SVG_CACHE.clear()
    print("[PASS] Claude symbol fallback when SVG is missing verified.")


def test_tray_cluster_shrinking() -> None:
    """Verify individual tray icons are not placed on the band (delegated to tray panel)."""
    get_qapp()

    dock = serit_mod.SeritDock({"style": "band", "pinned": []}, preview_mode=True)
    dock._tray_items = [{"name": f"app_{i}"} for i in range(10)]
    dock.resize(1536, 64)
    dock.compute_layout_and_resize(initial=True)
    img_wide = QImage(1536, 64, QImage.Format.Format_ARGB32)
    dock.render(img_wide)

    tray_hits = [e for r, k, e in dock.hit_boxes if k == "tray_icon"]
    assert len(tray_hits) == 0, f"Expected 0 tray icons on band, got {len(tray_hits)}"
    print("[PASS] Tray icons absent from band verified.")


def test_brightness_coalescing_and_resubmission() -> None:
    """Verify brightness pending-value coalescing and worker resubmission."""
    get_qapp()

    dock = serit_mod.SeritDock({"style": "band", "pinned": []}, preview_mode=False)

    called_levels: list[int] = []

    def mock_set_level(mon_id: str, lvl: int) -> bool:
        called_levels.append(lvl)
        time.sleep(0.05)  # Simulate slow I2C/DDC bus write
        return True

    with patch("brightness.set_level", side_effect=mock_set_level):
        # Request 40
        dock._on_brightness_requested("mon1", 40)
        # Immediately while worker is in flight, request 50 then 60
        dock._on_brightness_requested("mon1", 50)
        dock._on_brightness_requested("mon1", 60)

        # Process Qt event loop until in-flight and pending workers complete
        t0 = time.time()
        while time.time() - t0 < 3.0:
            QApplication.processEvents()
            time.sleep(0.04)
            if len(called_levels) >= 2 and called_levels[-1] == 60:
                break

        assert 60 in called_levels, f"Final level 60 was not applied! Called levels: {called_levels}"
        assert called_levels[-1] == 60, f"Last applied level should be 60, got {called_levels[-1]}"

    # Test mouse wheel over sun button
    sun_rect = QRectF(100, 10, 30, 30)
    dock.hit_boxes = [(sun_rect, "bright", None)]
    dock.store.update("bright", [{"id": "mon1", "name": "Dizüstü", "level": 50, "ok": True}])

    wheel_ev = QWheelEvent(
        QPointF(115, 25),
        QPointF(115, 25),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    dock.wheelEvent(wheel_ev)
    updated_monitors = dock._get_store_monitors()
    assert updated_monitors[0]["level"] == 55, f"Expected 55 after wheel up (+5), got {updated_monitors[0]['level']}"

    # Test tooltip
    tip = dock.get_tooltip_text("bright", None)
    assert tip == "Parlaklık · Dizüstü %55", f"Expected 'Parlaklık · Dizüstü %55', got '{tip}'"
    print("[PASS] Brightness coalescing, resubmission and wheel adjustment verified.")


def test_band_vs_pill_hit_boxes() -> None:
    """Verify band mode vs pill mode layout and hit boxes contract."""
    get_qapp()

    # Band style
    band = serit_mod.SeritDock({"style": "band", "pinned": []}, preview_mode=True)
    band._tray_items = [{"name": "app1"}, {"name": "app2"}]
    band.compute_layout_and_resize(initial=True)
    img_b = QImage(band.size(), QImage.Format.Format_ARGB32)
    band.render(img_b)

    band_keys = [k for _r, k, _e in band.hit_boxes]
    assert "claude" in band_keys
    assert "clock" in band_keys
    assert "tray" in band_keys
    assert "bright" in band_keys
    assert "vol" in band_keys
    assert "tray_icon" not in band_keys

    # Clock must be pinned to the far right edge (within 14px of screen width)
    clock_rect = next(r for r, k, _e in band.hit_boxes if k == "clock")
    assert band.width() - clock_rect.right() == 14.0, (
        f"Clock should end 14px from right screen edge, got {band.width() - clock_rect.right()}"
    )

    # Pill style
    pill = serit_mod.SeritDock({"style": "pill", "pinned": []}, preview_mode=True)
    pill._tray_items = [{"name": "app1"}, {"name": "app2"}]
    pill.compute_layout_and_resize(initial=True)
    img_p = QImage(pill.size(), QImage.Format.Format_ARGB32)
    pill.render(img_p)

    pill_keys = [k for _r, k, _e in pill.hit_boxes]
    assert "claude" in pill_keys
    assert "clock" in pill_keys
    assert "tray" in pill_keys
    assert "bright" in pill_keys
    assert "vol" in pill_keys
    # No tray icons in pill style
    assert "tray_icon" not in pill_keys

    print("[PASS] Band vs Pill hit boxes contract verified.")


def run_all() -> None:
    test_clock_v1_metrics_and_midnight_roll()
    test_claude_symbol_fallback()
    test_tray_cluster_shrinking()
    test_brightness_coalescing_and_resubmission()
    test_band_vs_pill_hit_boxes()
    print("ALL DOCK V7 TESTS PASSED SUCCESSFULLY.")


if __name__ == "__main__":
    run_all()
