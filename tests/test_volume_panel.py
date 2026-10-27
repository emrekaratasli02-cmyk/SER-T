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


def test_presets_turkish_and_clickable():
    w = sv.VolumePopover()
    img = QImage(w.WIDTH, w.HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    hr = media.draw_volume_slider_panel(p, QRectF(0, 0, w.WIDTH, w.HEIGHT), level=25, muted=False,
                                        device="Speakers (Realtek(R) Audio)")
    p.end()
    presets = hr["presets"]
    assert [v for _, v in presets] == [25.0, 50.0, 75.0, 100.0]
    assert hr["mute_btn"].right() < presets[0][0].left()
    assert presets[-1][0].right() <= w.WIDTH - 12
    src = (ROOT / "media.py").read_text(encoding="utf-8")
    assert '("25%"' not in src and '("100%"' not in src
    w._hit_rects = hr
    got = []
    w._request_volume = lambda v, force=False: got.append(v)
    for r, _ in presets:
        w.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, r.center(), r.center(),
                                      Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert got == [25.0, 50.0, 75.0, 100.0], got


if __name__ == "__main__":
    test_device_names()
    test_panel_stays_on_screen()
    test_presets_turkish_and_clickable()
    print("test_volume_panel: PASS")
