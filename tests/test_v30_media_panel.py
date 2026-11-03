"""test_v30_media_panel.py - v30 Medya Mini-Popover Paneli (MediaPanel) birim ve görsel testleri."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import media_panel as mp  # noqa: E402


def _make_cover_bytes() -> bytes:
    img = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    g = QLinearGradient(0, 0, 80, 80)
    g.setColorAt(0.0, QColor("#10B981"))
    g.setColorAt(1.0, QColor("#047857"))
    p.fillRect(0, 0, 80, 80, g)
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def test_fmt_mmss() -> None:
    assert mp.fmt_mmss(None) == "—"
    assert mp.fmt_mmss(0) == "00:00"
    assert mp.fmt_mmss(142) == "02:22"
    assert mp.fmt_mmss(3725) == "1:02:05"


def test_panel_controls_and_seek() -> None:
    pnl = mp.MediaPanel()
    info = {
        "title": "Daft Punk — Veridis Quo",
        "artist": "Discovery",
        "app": "Spotify",
        "exe": "Spotify.exe",
        "playing": True,
        "position_s": 100.0,
        "duration_s": 200.0,
        "art_bytes": _make_cover_bytes(),
    }
    pnl.set_media(info)
    pnl.set_volume(68.0, False, "Speakers (Realtek(R) Audio)")

    controls = []
    seeks = []
    vols = []
    mutes = []
    mixers = []
    apps = []

    pnl.control_requested.connect(controls.append)
    pnl.seek_requested.connect(seeks.append)
    pnl.volume_requested.connect(vols.append)
    pnl.mute_requested.connect(mutes.append)
    pnl.open_mixer_requested.connect(lambda: mixers.append(True))
    pnl.open_app_requested.connect(apps.append)

    # Render image and verify non-empty
    img = pnl.render_to_image(1.5)
    assert img.width() == int(352 * 1.5)
    assert img.height() > 400

    # Play/pause toggles playing state and emits signal
    pnl.activate("playpause")
    assert controls == ["playpause"]
    assert pnl._media["playing"] is False

    # +10s advances position from 100/200 (0.50) to 110/200 (0.55)
    pnl.activate("fwd10")
    assert len(seeks) == 1 and abs(seeks[-1] - 0.55) < 0.02

    # -10s steps back 10s
    pnl.activate("back10")
    assert len(seeks) == 2 and abs(seeks[-1] - 0.50) < 0.02

    # Mute button toggles mute
    pnl.activate("mute_btn")
    assert mutes == [True]

    # Mixer link & open app
    pnl.activate("mixer_link")
    assert mixers == [True]
    pnl.activate("open_app")
    assert apps == ["Spotify.exe"]

    # Hit test verification
    for key in ("close", "playpause", "prev", "next", "back10", "fwd10", "mute_btn", "mixer_link"):
        r = pnl._rects[key]
        assert pnl._hit(r.center()) == key, f"Hit failed for {key}"

    pnl.close()


def test_media_icon_only_and_preview_filtering() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("serit_v5_v30", str(APP_DIR / "serit_v5.pyw"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    dock = m.SeritDock({"style": "band", "media_icon_only": True, "hide_media_win_in_preview": True}, preview_mode=True)
    dock._now_playing_info = {
        "title": "Yusuf Kavuk Cinayeti Ortaya Çıktı",
        "artist": "YouTube",
        "app": "Chrome",
        "playing": True,
    }
    dock._raw_windows = [
        {"hwnd": 101, "title": "Reports - Google Chrome", "minimized": False, "active": True},
        {"hwnd": 102, "title": "Yusuf Kavuk Cinayeti Ortaya Çıktı - YouTube - Google Chrome", "minimized": False, "active": False},
        {"hwnd": 103, "title": "Arçelik & Beko // IAS Ekim 2026 - Google Chrome", "minimized": False, "active": False},
    ]

    # 1. Verify preview window list filters out hwnd 102 (the media window)
    wins = dock._picker_windows([101, 102, 103])
    assert [w["hwnd"] for w in wins] == [101, 103], wins

    # If there is only 1 window total, never hide it
    wins_single = dock._picker_windows([102])
    assert [w["hwnd"] for w in wins_single] == [102], wins_single

    # 2. Verify media_icon_only renders 52px button instead of 314px card
    dock.resize(1536, 64)
    dock.compute_layout_and_resize(initial=True)
    img = QImage(1536, 64, QImage.Format.Format_ARGB32)
    dock.render(img)
    r_media = next(r for r, k, _e in dock.hit_boxes if k == "media")
    assert r_media.width() == 52.0, f"Expected 52.0px icon button, got {r_media.width()}"
    dock.close()


def test_real_world_emoji_title_match() -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("serit_v5_v30b", str(APP_DIR / "serit_v5.pyw"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    d = m.SeritDock({"style": "band", "hide_media_win_in_preview": True}, preview_mode=True)
    d._now_playing_info = {"title": "ÇAĞLA TUĞALTAY ANISINA 🅧 X'TE (TWITTER'DA)📅  02 Kasım 2026 I Ömer  & Asya 💫 X Odası", "app": "Chrome"}
    d._raw_windows = [
        {"hwnd": 1, "title": "[External] HOW TO ROB A BANK IAS KURULUMLARI - Google Chrome"},
        {"hwnd": 2, "title": "reporting.integralplatform.com/files/tag/download - Google Chrome"},
        {"hwnd": 3, "title": "ÇAĞLA TUĞALTAY ANISINA 🅧 X'TE (TWITTER'DA)📅 02 Kasım 2026 I Ömer & Asya 💫 X Odası - YouTube - Google Chrome"},
    ]
    assert [w["hwnd"] for w in d._picker_windows([1, 2, 3])] == [1, 2]
    assert d._find_media_hwnd() == 3
    d.close()


def main() -> int:
    test_fmt_mmss()
    test_panel_controls_and_seek()
    test_media_icon_only_and_preview_filtering()
    test_real_world_emoji_title_match()
    print("ALL TEST_V30_MEDIA_PANEL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
