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


def main() -> int:
    test_fmt_mmss()
    test_panel_controls_and_seek()
    print("ALL TEST_V30_MEDIA_PANEL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
