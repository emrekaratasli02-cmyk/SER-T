"""Ses paneli: ekrandan taşmama, Türkçe aygıt adı ve yüzde biçimi (27 Eki 2026)."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
import media  # noqa: E402

spec = importlib.util.spec_from_file_location("sv", ROOT / "serit_v5.pyw")
sv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sv)
import tempfile as _tf  # noqa: E402
sv.SETTINGS_FILE = Path(_tf.mkdtemp(prefix="serit_vol_")) / "settings.json"  # never touch real settings
sv.save_settings = lambda cfg: None


def test_device_names():
    cases = {
        "Speakers (Realtek(R) Audio)": "Hoparlör · Realtek Audio",
        "Headphones (WH-1000XM4 Stereo)": "Kulaklık · WH-1000XM4 Stereo",
        "Speakers": "Hoparlör",
        "Default Audio": "",
        "": "",
        "MSI MP223 (NVIDIA High Definition Audio)": "MSI MP223 · NVIDIA High Definition Audio",
    }
    for raw, want in cases.items():
        got = media.tr_device_name(raw)
        assert got == want, (raw, got, want)


def test_panel_stays_on_screen():
    scr = app.primaryScreen().geometry()
    w = sv.VolumePopover()
    for anchor in (QRectF(scr.right() - 40, 17, 30, 30), QRectF(scr.right() - 4, 17, 4, 30),
                   QRectF(scr.left(), 17, 4, 30), QRectF(scr.center().x(), 17, 30, 30)):
        w.show_for(anchor, 25, False, "Speakers (Realtek(R) Audio)")
        app.processEvents()
        g = w.geometry()
        assert g.left() >= scr.left() and g.right() <= scr.right() and g.top() >= scr.top(), (anchor, g)
    w.hide()


def test_mixer_panel_controls():
    w = sv.VolumePopover()
    img = QImage(w.WIDTH, w.compute_height(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    w._paint_card(p)
    p.end()

    # Check Turkish percentage formatting in source
    src = (ROOT / "media.py").read_text(encoding="utf-8")
    assert '("25%"' not in src and '("100%"' not in src

    # Mute button toggle
    assert w._muted is False
    mute_rect = w._hit_master_mute
    w.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, mute_rect.center(), mute_rect.center(),
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert w._muted is True

    # Slider click
    slider_rect = w._hit_master_slider
    got = []
    w._request_master_volume = lambda v, force=False: got.append(v)
    w.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, slider_rect.center(), slider_rect.center(),
                                  Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert len(got) == 1
    assert 40.0 <= got[0] <= 60.0


if __name__ == "__main__":
    test_device_names()
    test_panel_stays_on_screen()
    test_mixer_panel_controls()
    print("test_volume_panel: PASS")
