"""test_v23_hover_preview.py - üzerine gelince önizleme kartı + bara bağlantısı (v23).

Zero side effects: panel only paints; dock runs in preview mode with winapi state changers and
window_thumbnail replaced by recorders. No real window is enumerated, captured, activated or closed.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault("SERIT_TEST", "1")

from PySide6.QtCore import QEvent, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QMouseEvent, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import hover_preview as hp  # noqa: E402

OUT = APP_DIR / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)


def W(hwnd, title, minimized=False, active=False):
    return {"hwnd": hwnd, "title": title, "minimized": minimized, "active": active}


ONE = [W(50101, "Gelen kutusu - Örnek - Google Chrome", active=True)]
TWO = [W(50201, "Proje dokümanı - Google Chrome", active=True), W(50202, "YouTube - Google Chrome")]
FOUR = [W(50301, "Gelen kutusu - Örnek"), W(50302, "Proje dokümanı", active=True),
        W(50303, "YouTube", minimized=True), W(50304, "Haftalık özet")]
SEVEN = [W(50400 + i, f"Sekme {i + 1} - Örnek sayfa") for i in range(7)]
LONG = [W(50501, "Çok uzun bir pencere başlığı: 2026 bütçe planlaması ve tedarikçi sözleşmeleri - Son sürüm"),
        W(50502, "")]
GARBAGE = [W(50601, "Gelen kutusu - Örnek"), "çöp", {}, {"hwnd": 0}, {"hwnd": True, "title": "x"},
           {"hwnd": -3, "title": "y"}, W(50602, "")]


def _solid(color, w=176, h=99):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    return img


def _icon():
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#4C8BF5"))
    p.drawEllipse(2, 2, 28, 28)
    p.end()
    return pm


def _anchor(frac=0.5):
    g = QGuiApplication.primaryScreen().availableGeometry()
    return QRectF(g.left() + g.width() * frac - 22, g.bottom() - 54, 44, 44)


def _panel(wins, thumbs=None, frac=0.5, key="chrome.exe"):
    pnl = hp.HoverPreview()
    pnl.show_for(_anchor(frac), key, "Google Chrome", _icon(), [dict(w) if isinstance(w, dict) else w for w in wins],
                 thumbs)
    pnl.render_to_image(1.0)  # kart dikdörtgenlerini doldur
    return pnl


def _press(pnl, pt, button=Qt.MouseButton.LeftButton):
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, pt, pnl.mapToGlobal(pt.toPoint()).toPointF(), button, button,
                     Qt.KeyboardModifier.NoModifier)
    pnl.mousePressEvent(ev)


def _move(pnl, pt):
    ev = QMouseEvent(QEvent.Type.MouseMove, pt, pnl.mapToGlobal(pt.toPoint()).toPointF(), Qt.MouseButton.NoButton,
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    pnl.mouseMoveEvent(ev)


def test_size_formula_and_flags():
    for wins, cards, more in ((ONE, 1, False), (TWO, 2, False), (FOUR, 4, False), (SEVEN, 4, True)):
        pnl = _panel(wins)
        w_exp, h_exp = hp.compute_size(len(wins), any(x["minimized"] for x in wins[:4]))
        assert (pnl.width(), pnl.height()) == (w_exp, h_exp)
        exp_w = 2 * hp.PAD + cards * hp.THUMB_W + (cards - 1) * hp.CARD_GAP + ((hp.CARD_GAP + hp.MORE_W) if more else 0)
        assert pnl.width() == round(exp_w), (len(wins), pnl.width(), exp_w)
        assert len(pnl._cards) == cards
        pnl.hide_instant()
    pnl = hp.HoverPreview()
    assert pnl.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert pnl.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert hp.compute_size(4, True)[1] == hp.compute_size(4, False)[1] + hp.SUB_H


def test_click_choose_close_more():
    chosen, closed, more = [], [], []
    pnl = _panel(SEVEN)
    pnl.window_chosen.connect(chosen.append)
    pnl.close_requested.connect(closed.append)
    pnl.more_requested.connect(lambda: more.append(1))
    hwnd1, card1, _thumb1, close1 = pnl._cards[1]
    _move(pnl, card1.center())
    pnl.render_to_image(1.0)
    _press(pnl, close1.center())
    assert closed == [hwnd1] and pnl.is_open(), "kapat düğmesi pencereyi kapatmalı, panel açık kalmalı"
    _press(pnl, pnl._cards[2][1].center(), Qt.MouseButton.MiddleButton)
    assert closed == [hwnd1, pnl._cards[2][0]]
    _press(pnl, pnl._more_rect.center())
    assert more == [1]
    _press(pnl, pnl._cards[0][1].center())
    assert chosen == [pnl._cards[0][0]] and not pnl.is_open()
    pnl.hide_instant()


def test_thumbnails_and_minimized_placeholder():
    pnl = _panel(FOUR)
    pnl.set_thumbnails({50301: _solid("#FF0000"), 50303: _solid("#00FF00"), 99999: _solid("#0000FF"),
                        50302: "bozuk", True: _solid("#FF00FF")})
    assert set(pnl._thumbs) == {50301, 50303}
    img = pnl.render_to_image(1.0)
    t0 = pnl._cards[0][2]
    c0 = QColor(img.pixel(int(t0.center().x()), int(t0.center().y())))
    assert c0.red() > 200 and c0.green() < 60, c0.name()
    t2 = pnl._cards[2][2]  # küçültülmüş: görüntü olsa bile simge yer tutucusu
    c2 = QColor(img.pixel(int(t2.left() + 6), int(t2.top() + 6)))
    assert c2.green() < 120, c2.name()
    pnl.set_windows([FOUR[0]])
    assert set(pnl._thumbs) == {50301} and len(pnl._windows) == 1
    pnl.set_windows([])
    assert not pnl.is_open()
    pnl.hide_instant()


def test_current_app_switch_and_garbage():
    pnl = _panel(GARBAGE)
    assert [w["hwnd"] for w in pnl._windows] == [50601, 50602]
    assert pnl.current_app() == "chrome.exe"
    pnl.show_for(_anchor(0.3), "code.exe", "VS Code", None, TWO)
    assert pnl.current_app() == "code.exe" and pnl._thumbs == {}
    pnl.hide_instant()
    assert pnl.current_app() is None


def test_anchoring_inside_screen():
    g = QGuiApplication.primaryScreen().availableGeometry()
    for frac in (0.0, 0.5, 1.0):
        pnl = _panel(FOUR, frac=frac)
        pos = pnl._target_pos()
        assert g.left() <= pos.x() and pos.x() + pnl.width() <= g.right() + 1, (frac, pos, g)
        assert pos.y() + pnl.height() <= _anchor(frac).top(), "kütüğün üstünde açılmalı"
        pnl.hide_instant()


def test_render_sheet():
    shots = []
    for wins, thumbs, hover in (
        (ONE, {50101: _solid("#E8EAED")}, None),
        (TWO, {50201: _solid("#F1F3F4"), 50202: _solid("#202124")}, 50202),
        (FOUR, {50301: _solid("#E8EAED"), 50302: _solid("#FFFFFF")}, None),
        (SEVEN, {}, None),
        (LONG, {50501: _solid("#DADCE0")}, 50501),
    ):
        pnl = _panel(wins, thumbs)
        if hover is not None:
            card = next(c for c in pnl._cards if c[0] == hover)
            _move(pnl, card[1].center())
        shots.append(pnl.render_to_image(2.0))
        pnl.hide_instant()
    gap = 40
    W_ = max(i.width() for i in shots) + 2 * gap
    H_ = sum(i.height() for i in shots) + gap * (len(shots) + 1)
    sheet = QImage(W_, H_, QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(QColor(40, 60, 96))
    p = QPainter(sheet)
    y = gap
    for im in shots:
        p.drawImage(gap, y, im)
        y += im.height() + gap
    p.end()
    sheet.save(str(OUT / "v23_hover_sheet.png"))
    assert (OUT / "v23_hover_sheet.png").exists()


# ---------------------------------------------------------------- bar bağlantısı
def _dock_mod():
    spec = importlib.util.spec_from_file_location("serit_v5_v23hp", str(APP_DIR / "serit_v5.pyw"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SETTINGS_FILE = Path(tempfile.mkdtemp(prefix="serit_v23hp_")) / "settings.json"
    m.save_settings = lambda cfg: None
    m.winapi.window_thumbnail = lambda h, *a, **k: None
    m.winapi.activate_window = lambda h: CALLS.append(("activate", h))
    m.winapi.close_window = lambda h: CALLS.append(("close", h)) or True
    m.winapi.activate_or_minimize = lambda h: CALLS.append(("toggle", h))
    return m


CALLS: list = []


def test_dock_hover_opens_preview_and_hides():
    m = _dock_mod()
    d = m.SeritDock({"style": "band"}, preview_mode=True)
    d.tiles = [{"exe": "C:/x/chrome.exe", "name": "Chrome", "running": True, "hwnds": [11, 12]},
               {"exe": "C:/x/notepad.exe", "name": "Not Defteri", "running": False, "hwnds": []}]
    d._tile_rects = [QRectF(100, 10, 44, 44), QRectF(150, 10, 44, 44)]
    d._raw_windows = [W(11, "Gelen kutusu - Örnek", active=True), W(12, "YouTube", minimized=True)]
    # çalışan kütük: zamanlayıcı kurulur; süre dolunca açılır
    d._hover_app_idx = 0
    d._on_tile_hover(0)
    assert d._hover_open_timer.isActive()
    d._open_hover_preview()
    assert d.hover_preview is not None and d.hover_preview.current_app() == "C:/x/chrome.exe"
    assert [w["hwnd"] for w in d.hover_preview._windows] == [11, 12]
    # çalışmayan kütüğe geçiş: kapanma zamanlanır, fare orada değilken kapanır
    d._hover_app_idx = 1
    d._on_tile_hover(1)
    assert d._hover_hide_timer.isActive()
    d._hide_hover_preview(force=True)
    assert not d.hover_preview.is_open()
    # ayar kapalıysa hiç açılmaz
    d.settings["hover_preview"] = False
    d._hover_app_idx = 0
    d._on_tile_hover(0)
    assert not d._hover_open_timer.isActive()


def test_dock_preview_signals_and_thumbs():
    m = _dock_mod()
    d = m.SeritDock({"style": "band"}, preview_mode=True)
    d.tiles = [{"exe": "C:/x/chrome.exe", "name": "Chrome", "running": True, "hwnds": [11, 12]}]
    d._tile_rects = [QRectF(100, 10, 44, 44)]
    d._raw_windows = [W(11, "Gelen kutusu - Örnek"), W(12, "YouTube")]
    d._hover_app_idx = 0
    d._hover_tile_idx = 0
    d._open_hover_preview()
    d._on_picker_thumbs("C:/x/chrome.exe", {11: _solid("#FF0000")})
    assert 11 in d.hover_preview._thumbs
    d._on_picker_thumbs("C:/x/other.exe", {12: _solid("#00FF00")})
    assert 12 not in d.hover_preview._thumbs
    assert set(d._cached_thumbs("C:/x/chrome.exe", [11, 12])) == {11}
    CALLS.clear()
    d.preview_mode = False
    try:
        d.hover_preview.window_chosen.emit(12)
        d.hover_preview.close_requested.emit(11)
    finally:
        d.preview_mode = True
    assert ("activate", 12) in CALLS and ("close", 11) in CALLS
    d._hide_hover_preview(force=True)


def run_all():
    for fn in (test_size_formula_and_flags, test_click_choose_close_more, test_thumbnails_and_minimized_placeholder,
               test_current_app_switch_and_garbage, test_anchoring_inside_screen, test_render_sheet,
               test_dock_hover_opens_preview_and_hides, test_dock_preview_signals_and_thumbs):
        fn()
        print(f"  [PASS] {fn.__name__}")
    print("ALL TEST_V23_HOVER_PREVIEW TESTS PASSED")


if __name__ == "__main__":
    run_all()
