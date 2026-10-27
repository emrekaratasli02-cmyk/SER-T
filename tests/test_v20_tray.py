"""test_v20_tray.py - TrayPanel artık panel_style v2 ortak kitini kullanıyor.

Doğrulanan davranışlar (yalnızca yerel sinyalia; GERÇEK tepsi simgesi ASLA etkinleştirilmez):
- Genişlik pt.WIDTH['tray'] (352 px)
- 24 px simge satırları, hover (soft, radius 8) ve klavye gezinmesi devam ediyor
- × kapatır; Sol tık -> item_activated("left") + kapanır; Sağ tık -> item_activated("right") + açık kalır
- Boş durum 'Simge yok'; rozet metni 'N öğe'
- Footer: 'Windows sistem tepsisi · HH:MM' + tek Yenile düğmesi -> refresh_requested
- show_for(..., switch_from_x=...) ve hide_instant() (animate_out instant) çevrimdışı çalışır
- DPR 2.0 render kanıtı: _ref/out/tepsi_normal.png, tepsi_uzun.png, tepsi_bos.png
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

APP_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_DIR))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import panel_style as ps  # noqa: E402
import tray_panel as tp  # noqa: E402

OUT = APP_DIR / "_ref" / "out"
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication.instance() or QApplication(["test_v20_tray"])

ANCHOR = QRectF(500.0, 800.0, 120.0, 32.0)

STUB_NAMES = [
    "Mesajlaşma",
    "Bulut Depolama",
    "Ekran Kartı",
    "Dikte",
    "Windows Güvenlik",
]

STUB_ITEM_COLORS = ["#BF5AF2", "#0A84FF", "#64D2FF", "#FFB020", "#30D158"]

_icon_counter = 0


def _stub_icon(color: str) -> QPixmap:
    """Sintetik tepsi simgesi (gerçek simge okunmaz, dağıtılmaz; yalnız yerel QPixmap)."""
    global _icon_counter
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(4, 4, 40, 40)
    p.setBrush(QColor(255, 255, 255, 200))
    p.drawEllipse(QPointF(24.0, 24.0), 8.0, 8.0)
    p.end()
    _icon_counter += 1
    return pm


def _stub_items(n: int = 5) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for i in range(n):
        items.append({"name": STUB_NAMES[i % len(STUB_NAMES)], "tooltip": f"stub {i}"})
    return items


def _stub_icons() -> Dict[str, QPixmap]:
    return {name: _stub_icon(STUB_ITEM_COLORS[i]) for i, name in enumerate(STUB_NAMES[:3])}


def _panel(n: int = 5, with_icons: bool = True) -> tp.TrayPanel:
    panel = tp.TrayPanel()
    icons = _stub_icons() if with_icons else None
    panel.set_items(_stub_items(n) if n else [], icons)
    panel.render_to_image(2.0)
    return panel


def _mouse(widget, pos: QPointF, btn: Qt.MouseButton = Qt.MouseButton.LeftButton,
           release: bool = False) -> None:
    posf = QPointF(pos)
    etype = QEvent.Type.MouseButtonRelease if release else QEvent.Type.MouseButtonPress
    ev = QMouseEvent(etype, posf, posf, btn, btn, Qt.KeyboardModifier.NoModifier)
    if release:
        widget.mouseReleaseEvent(ev)
    else:
        widget.mousePressEvent(ev)


def test_width_matches_shared_kit():
    panel = _panel()
    assert ps.WIDTH["tray"] == 352
    assert panel.WIDTH == 352
    assert panel.width() == ps.WIDTH["tray"]


def test_close_button_closes():
    panel = _panel(3)
    closed: List[bool] = []
    panel.show_for(ANCHOR)
    assert panel.is_open()
    panel.refresh_requested.connect(lambda: closed.append(True))
    _mouse(panel, panel._close_rect.center())
    assert not panel.is_open()
    panel.hide_instant()
    assert not panel.isVisible()
    assert closed == []  # × Yenile'yi tetiklemez


def test_row_hit_test_left_right():
    """Satır vuruşu yerel listeye sinyal yollar (gerçek tepsi etkinleştirilmez)."""
    panel = _panel(3)
    hits: List[Tuple[Any, str]] = []
    panel.item_activated.connect(lambda item, btn: hits.append((item, btn)))
    panel.show_for(ANCHOR)

    lr = panel._list_rect
    _mouse(panel, QPointF(lr.left() + 30.0, lr.top() + panel.ROW_HEIGHT / 2.0))
    assert len(hits) == 1 and hits[0][1] == "left"
    assert hits[0][0]["name"] == STUB_NAMES[0]
    assert not panel.is_open()                 # sol tık paneli kapatır
    panel.hide_instant()
    assert not panel.isVisible()

    panel.show_for(ANCHOR)
    y1 = lr.top() + panel.ROW_STRIDE + panel.ROW_HEIGHT / 2.0
    _mouse(panel, QPointF(lr.left() + 30.0, y1), btn=Qt.MouseButton.RightButton)
    assert len(hits) == 2 and hits[1][1] == "right"
    assert panel.is_open()                     # sağ tık açık kalır

    # Liste dışı alana tık: sinyal yok
    n_before = len(hits)
    _mouse(panel, QPointF(panel.width() / 2.0, ps.PAD + 2.0))
    assert len(hits) == n_before
    panel.hide_instant()
    assert not panel.isVisible()


def test_empty_state_and_chip():
    panel = _panel(0, with_icons=False)
    assert panel.EMPTY_TEXT == "Simge yok"
    assert panel.chip_text() == "0 öğe"
    img = panel.render_to_image(2.0)
    assert not img.isNull()

    five = _panel(5)
    assert five.chip_text() == "5 öğe"
    one = _panel(1, with_icons=False)
    assert one.chip_text() == "1 öğe"


def test_footer_refresh_signal():
    for panel in (_panel(5), _panel(0, with_icons=False)):
        got: List[bool] = []
        panel.refresh_requested.connect(lambda: got.append(True))
        assert not panel._refresh_rect.isNull()
        center = panel._refresh_rect.center()
        _mouse(panel, center)
        assert panel._refresh_pressed is True
        _mouse(panel, center, release=True)
        assert got == [True] and panel._refresh_pressed is False


def test_show_for_switch_and_hide_instant():
    panel = _panel(5)
    panel.show_for(ANCHOR)
    assert panel.is_open() and panel.isVisible()
    panel.hide_instant()
    assert not panel.isVisible() and panel.recently_closed()

    # Kapsül içi bölüm değişimi: switch_from_x ile yatay kaymadan açılır
    panel.show_for(ANCHOR, switch_from_x=120)
    assert panel.is_open()
    assert panel._anchor_global == ANCHOR      # kontrat: konum saklanır
    panel.hide_instant()
    assert not panel.isVisible()

    # Pozisyonel çağrı üzerinde yeni ipucu yok
    panel.show_for(ANCHOR)
    assert panel.is_open()
    panel.hide_instant()
    assert not panel.isVisible()


def test_keyboard_and_scroll_kept():
    """Klavye gezinmesi, kaydırma ve max yükseklik davranışı korunur."""
    panel = _panel(14, with_icons=False)
    assert panel._visible_list_height() == panel.LIST_MAX_HEIGHT
    assert panel._total_list_height() == 14 * panel.ROW_STRIDE

    dn1 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(dn1)
    assert panel._highlight_idx == 0
    dn2 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(dn2)
    assert panel._highlight_idx == 1
    up = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(up)
    assert panel._highlight_idx == 0
    esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    panel.keyPressEvent(esc)
    panel.hide_instant()

    # Satır hizalama: sağ tık akışında serit_v5 kullanır
    panel.show_for(ANCHOR)
    panel.render_to_image(2.0)
    idx = panel._row_at_point(
        QPointF(panel._list_rect.left() + 10.0,
                panel._list_rect.top() + 6 * panel.ROW_STRIDE + 5.0)
    )
    assert idx == 6
    panel.hide_instant()
    assert not panel.isVisible()


def test_renders_dpr2():
    """DPR 2.0 render kanıtları: normal (hover), uzun (kaydırılmış), boş."""
    normal = _panel(5)
    normal._hover_idx = 1
    img = normal.render_to_image(2.0)
    assert not img.isNull() and img.width() == 2 * 352 and img.height() > 0
    img.save(str(OUT / "tepsi_normal.png"))

    uz = _panel(14, with_icons=False)
    uz._hover_idx = 5                 # görünür aralıkta bir satır (kaydırma 120 px)
    uz._scroll_y = (14 * uz.ROW_STRIDE - uz.LIST_MAX_HEIGHT) / 2.0  # kaydırılmış orta konum
    img2 = uz.render_to_image(2.0)
    assert not img2.isNull()
    img2.save(str(OUT / "tepsi_uzun.png"))

    empty = _panel(0, with_icons=False)
    img3 = empty.render_to_image(2.0)
    assert not img3.isNull() and empty.height() < normal.height()
    img3.save(str(OUT / "tepsi_bos.png"))

    for name in ("tepsi_normal.png", "tepsi_uzun.png", "tepsi_bos.png"):
        f = OUT / name
        assert f.is_file() and f.stat().st_size > 0, name


def run_all():
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
    print("ALL TEST_V20_TRAY TESTS PASSED")


if __name__ == "__main__":
    run_all()
