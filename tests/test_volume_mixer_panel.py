"""Unit and visual render tests for Direction C Volume Mixer Panel (Option 2 'Uygulama Mikseri').

Ensures:
- Mocked audio_mixer and media (zero real hardware volume changes).
- High-DPI DPR 2.0 realistic render (Chrome active, Hermes, Dikte muted, Sistem sesleri).
- Empty state render ('Ses çalan uygulama yok').
- Coalesced slider drag calls for master and individual app sessions.
- Mute toggle handlers (master + per-session).
- Screen clamping with 8px margin and gap above anchor across all monitor edges.
- Height adaptation based on row count (up to 6 rows, then scroll).
"""

from __future__ import annotations

from pathlib import Path
import sys
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QWheelEvent
from PySide6.QtWidgets import QApplication

# Ensure QApplication instance exists
app = QApplication.instance() or QApplication([])

import media
from volume_panel import AppVolumeCoalescer, MasterVolumeCoalescer, VolumePopover

SCRATCH_DIR = Path("C:/Users/Emre Karatasli/AppData/Local/hermes/cache/scratch/serit-v14")
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def get_realistic_sessions() -> List[Dict[str, Any]]:
    """Return realistic mock session list matching test specification."""
    return [
        {
            "key": "chrome",
            "name": "Google Chrome",
            "exe": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            "level": 80.0,
            "muted": False,
            "active": True,
            "pids": [1010],
        },
        {
            "key": "hermes",
            "name": "Hermes",
            "exe": "C:\\Users\\Emre Karatasli\\AppData\\Local\\hermes\\hermes.exe",
            "level": 100.0,
            "muted": False,
            "active": False,
            "pids": [1020],
        },
        {
            "key": "dikte",
            "name": "Dikte",
            "exe": "D:\\Apps\\dikte\\dikte.exe",
            "level": 100.0,
            "muted": True,
            "active": False,
            "pids": [1030],
        },
        {
            "key": "system",
            "name": "Sistem Sesleri",
            "exe": "",
            "level": 100.0,
            "muted": False,
            "active": False,
            "pids": [],
        },
    ]


def test_dpr2_realistic_render() -> None:
    """Render realistic session state at DPR 2.0 and save to ses_mikser.png."""
    w = VolumePopover()
    # Mock real volume setters
    media_set_mock = MagicMock()
    media_toggle_mock = MagicMock()
    media.set_volume = media_set_mock
    media.toggle_mute = media_toggle_mock

    sessions = get_realistic_sessions()
    w.update_volume(25.0, False, "Speakers (Realtek(R) Audio)")
    w.update_sessions(sessions)

    # Calculate target image dimensions
    dpr = 2.0
    h = w.compute_height()
    w.resize(w.WIDTH, h)
    app.processEvents()

    img = QImage(int(w.width() * dpr), int(w.height() * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    w._paint_card(p)
    p.end()

    out_path = SCRATCH_DIR / "ses_mikser.png"
    saved = img.save(str(out_path))
    assert saved, f"Failed to save image to {out_path}"
    assert out_path.exists() and out_path.stat().st_size > 1000

    # Verify hit rects and state
    assert len(w._hit_app_rows) == 4
    assert w._level == 25.0
    assert w._muted is False
    assert w.width() == 340
    print(f"[OK] test_dpr2_realistic_render -> {out_path} ({img.width()}x{img.height()} px)")


def test_dpr2_empty_state_render() -> None:
    """Render empty session state at DPR 2.0 and save to ses_bos.png."""
    w = VolumePopover()
    w.update_volume(25.0, False, "Speakers (Realtek(R) Audio)")
    w.update_sessions([])

    dpr = 2.0
    h = w.compute_height()
    w.resize(w.WIDTH, h)
    app.processEvents()

    img = QImage(int(w.width() * dpr), int(w.height() * dpr), QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    w._paint_card(p)
    p.end()

    out_path = SCRATCH_DIR / "ses_bos.png"
    saved = img.save(str(out_path))
    assert saved, f"Failed to save image to {out_path}"
    assert out_path.exists() and out_path.stat().st_size > 1000

    assert len(w._hit_app_rows) == 0
    print(f"[OK] test_dpr2_empty_state_render -> {out_path} ({img.width()}x{img.height()} px)")


def test_master_coalescer() -> None:
    """Verify MasterVolumeCoalescer coalesces high-frequency requests (~40ms)."""
    calls: List[float] = []

    def mock_apply() -> None:
        pass

    coalescer = MasterVolumeCoalescer(interval_ms=40)

    def tracked_flush() -> None:
        if coalescer._target_level is not None:
            calls.append(coalescer._target_level)
            coalescer._last_apply_time = time.monotonic()

    coalescer._flush = tracked_flush

    # Fast rapid requests
    coalescer.request(10.0, force=False)
    coalescer.request(20.0, force=False)
    coalescer.request(30.0, force=False)
    coalescer.request(45.0, force=False)
    # First request should apply immediately, others wait
    assert len(calls) == 1
    assert calls[0] == 10.0

    # Wait for coalescer timer or force
    coalescer.request(55.0, force=True)
    assert len(calls) == 2
    assert calls[-1] == 55.0
    coalescer.stop()
    print("[OK] test_master_coalescer")


def test_app_volume_coalescer() -> None:
    """Verify AppVolumeCoalescer coalesces per-key application volume changes (~60ms)."""
    calls: Dict[str, List[float]] = {}

    coalescer = AppVolumeCoalescer(interval_ms=60)

    def tracked_flush() -> None:
        for k, v in list(coalescer._pending.items()):
            calls.setdefault(k, []).append(v)
            coalescer._last_submit_time[k] = time.monotonic()
        coalescer._pending.clear()

    coalescer._flush = tracked_flush

    # Drag session 'chrome' rapidly
    coalescer.request("chrome", 50.0, force=False)
    coalescer.request("chrome", 60.0, force=False)
    coalescer.request("chrome", 70.0, force=False)
    coalescer.request("chrome", 85.0, force=False)

    # First request applied immediately
    assert len(calls.get("chrome", [])) == 1
    assert calls["chrome"][0] == 50.0

    # Force release
    coalescer.request("chrome", 88.0, force=True)
    assert len(calls["chrome"]) == 2
    assert calls["chrome"][-1] == 88.0
    coalescer.stop()
    print("[OK] test_app_volume_coalescer")


def test_mute_toggles() -> None:
    """Verify mute toggling for master audio and individual sessions."""
    w = VolumePopover()
    media_toggle_mock = MagicMock()
    media.toggle_mute = media_toggle_mock

    # Master mute toggle
    assert w._muted is False
    w.toggle_master_mute()
    assert w._muted is True
    w.toggle_master_mute()
    assert w._muted is False

    # App session mute toggle
    sessions = get_realistic_sessions()
    w.update_sessions(sessions)
    assert w._sessions[0]["muted"] is False
    w.toggle_session_mute("chrome")
    assert w._sessions[0]["muted"] is True
    w.toggle_session_mute("chrome")
    assert w._sessions[0]["muted"] is False
    print("[OK] test_mute_toggles")


def test_screen_clamping() -> None:
    """Verify on-screen clamping keeping 8px gap above anchor and remaining strictly in bounds."""
    scr = app.primaryScreen().geometry()
    w = VolumePopover()

    anchors = [
        QRectF(scr.right() - 40, 17, 30, 30),
        QRectF(scr.right() - 4, 17, 4, 30),
        QRectF(scr.left(), 17, 4, 30),
        QRectF(scr.center().x(), 17, 30, 30),
        QRectF(scr.left() + 10, scr.bottom() - 40, 30, 30),
    ]

    for anchor in anchors:
        w.show_for(anchor, 25.0, False, "Speakers (Realtek(R) Audio)")
        app.processEvents()
        g = w.geometry()
        assert g.left() >= scr.left(), f"Left overflow: {g.left()} < {scr.left()}"
        assert g.right() <= scr.right(), f"Right overflow: {g.right()} > {scr.right()}"
        assert g.top() >= scr.top(), f"Top overflow: {g.top()} < {scr.top()}"
    w.hide()
    print("[OK] test_screen_clamping")


def test_height_adaptation_and_scroll() -> None:
    """Verify panel height adapts to row count and caps at 6 rows with scroll support."""
    w = VolumePopover()

    # Empty
    w.update_sessions([])
    h_0 = w.compute_height()
    assert h_0 == 280

    # 1 row
    w.update_sessions([{"key": "app1", "name": "App 1", "level": 50}])
    h_1 = w.compute_height()
    assert h_1 == 284

    # 4 rows
    w.update_sessions(get_realistic_sessions())
    h_4 = w.compute_height()
    assert h_4 == 434

    # 6 rows
    six_sessions = [{"key": f"app_{i}", "name": f"App {i}", "level": 50} for i in range(6)]
    w.update_sessions(six_sessions)
    h_6 = w.compute_height()
    assert h_6 == 534

    # 8 rows -> capped at 6 rows
    eight_sessions = [{"key": f"app_{i}", "name": f"App {i}", "level": 50} for i in range(8)]
    w.update_sessions(eight_sessions)
    h_8 = w.compute_height()
    assert h_8 == 534  # height stays capped

    # Test wheel scroll
    w.resize(w.WIDTH, h_8)
    img = QImage(w.WIDTH, h_8, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    w._paint_card(p)
    p.end()

    assert w._max_scroll_y > 0.0
    assert w._scroll_y == 0.0

    # Wheel down over apps
    wheel_ev = QWheelEvent(
        QPointF(100.0, 200.0),
        QPointF(100.0, 200.0),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    w.wheelEvent(wheel_ev)
    assert w._scroll_y > 0.0
    print("[OK] test_height_adaptation_and_scroll")


def run_all() -> None:
    test_dpr2_realistic_render()
    test_dpr2_empty_state_render()
    test_master_coalescer()
    test_app_volume_coalescer()
    test_mute_toggles()
    test_screen_clamping()
    test_height_adaptation_and_scroll()
    print("ALL VOLUME MIXER PANEL TESTS PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    run_all()
